"""The daemon against the real board.

`test_daemon_api.py` covers the API without hardware, deliberately.
What cannot be covered that way is the one thing this file checks: that
`BoardDevice` drives a real Due, that whole frames come out of a real
serial stream, and that the daemon's teardown leaves the port in a
state the next run can open. Everything else about signals and timing
belongs to the suite around it.

Kept to one streaming case on purpose. This is the slowest kind of test
in the project and its value is the wiring, not the measurement.
"""

import time

import pytest

import measure
from helpers import record
from daemon import client as clientmod
from daemon import device as devmod
from daemon import server as servermod


@pytest.mark.slow
@pytest.mark.scope
def test_the_daemon_streams_real_frames_and_lets_go_of_the_port(board, track):
    dev = devmod.BoardDevice(board)
    srv = servermod.Server(dev, host="127.0.0.1", port=0).start()
    c = clientmod.Client("127.0.0.1", srv.port, timeout=15.0)
    try:
        c.connect()
        assert c.hello("control")["device"]["kind"] == "board"
        c.subscribe()
        c.call("start", mode="capture", preset="1")

        frames = c.wait_frames(20, timeout=20.0)
        assert all(len(f) == devmod.FRAME_BYTES for f in frames)

        ps = measure._finish(measure.parse_frames(b"".join(frames)))
        assert ps.frames >= 20
        assert ps.crc_bad == 0, "frames reached the client corrupt"
        assert ps.seq_gaps == 0, (
            f"{ps.seq_gaps} sequence gaps: the daemon lost frames the "
            f"device sent")
        assert ps.declared_rate_hz > 0

        st = c.call("status")["status"]
        assert st["running"] is True
        assert st["frames_read"] >= 20
        assert st["discarded_bytes"] < devmod.FRAME_BYTES, (
            "more than one frame's worth of bytes was discarded before "
            "framing locked on")

        c.call("stop")
    finally:
        c.close()
        srv.stop()

    # The port must be usable immediately afterwards. A daemon that
    # leaves the device streaming, or the native node held, turns into
    # the next run's mystery.
    time.sleep(0.5)
    fd = board.open_native()
    try:
        measure.drain_until_quiet(fd, quiet=0.3, cap=3.0)
    finally:
        board.close_native(fd)


@pytest.mark.slow
@pytest.mark.scope
def test_the_daemon_delivers_the_full_rate_without_dropping(board, track,
                                                            calibration):
    """The number nobody had, and the one the GUI plan depends on.

    The daemon reads the ADC's complete in-spec output, splits it into
    4 KB frames and fans each one out in Python. Whether that sustains
    is not something to assume in either direction: measured on this
    host it delivered 3,859 frames in 8 s with nothing dropped, no
    sequence gaps and not one byte discarded, so the assertions here are
    exact rather than tolerant. If Python ever stops keeping up, this is
    where it will show, and a drop count is the evidence.
    """
    dev = devmod.BoardDevice(board)
    srv = servermod.Server(dev, host="127.0.0.1", port=0).start()
    c = clientmod.Client("127.0.0.1", srv.port, timeout=20.0,
                         frame_capacity=20000)
    try:
        c.connect()
        c.hello("control")
        c.subscribe()
        c.call("start", mode="capture", preset="5")

        t0 = time.time()
        time.sleep(6.0)
        elapsed = time.time() - t0
        c.call("stop")
        # Both counts are read after the stream is quiet. Sampling them
        # while it runs compares two different instants and reports a
        # frame in flight as a lost one.
        time.sleep(0.5)
        read_at_stop = srv.frames_read
        got_at_stop = c.frames_received
        dropped = max((s.dropped for s in srv.sessions), default=0)

        frames = list(c.frames)[:got_at_stop]
        ps = measure._finish(measure.parse_frames(b"".join(frames)))

        record(calibration, f"daemon_fullrate_{track}", {
            "frames": read_at_stop,
            "mbs": round(read_at_stop * devmod.FRAME_BYTES / elapsed / 1e6, 3),
            "dropped": dropped,
            "declared_hz": ps.declared_rate_hz})

        assert ps.frames > 1000, (
            f"only {ps.frames} frames in {elapsed:.1f}s; the stream never "
            f"reached rate")
        assert ps.crc_bad == 0
        assert ps.seq_gaps == 0, (
            f"{ps.seq_gaps} sequence gaps at the full rate: frames the "
            f"device sent did not reach the client")
        assert dropped == 0, (
            f"the daemon dropped {dropped} frames toward a client that was "
            f"reading: it is not keeping up at {ps.declared_rate_hz} Hz")
        assert got_at_stop == read_at_stop, (
            f"daemon read {read_at_stop} frames, client received "
            f"{got_at_stop}")
        assert srv._splitter.discarded == 0
    finally:
        c.close()
        srv.stop()


@pytest.mark.slow
@pytest.mark.awg
@pytest.mark.scope
def test_a_waveform_uploaded_through_the_daemon_reaches_the_pin(board, track,
                                                                baseline,
                                                                calibration):
    """The whole instrument, through the socket: a client uploads a
    sine, the daemon feeds it to the DAC, and the ADC's view of it comes
    back over the same connection.

    Judged the way the rest of the suite judges playback - the tone
    amplitude per window against the theoretical maximum, never a
    whole-run average, and underruns from the device's own counters.
    This is the first time `BoardDevice`'s feed path runs against
    hardware at all.
    """
    dac_sps = 200000
    wave, tone_hz = measure.build_waveform(1000.0, dac_sps)

    dev = devmod.BoardDevice(board)
    srv = servermod.Server(dev, host="127.0.0.1", port=0).start()
    c = clientmod.Client("127.0.0.1", srv.port, timeout=20.0,
                         frame_capacity=20000)
    try:
        c.connect()
        c.hello("control")
        c.subscribe()
        c.send_awg(wave)
        assert c.wait_event("awg_ok")["bytes"] == len(wave)

        c.call("start", mode="loop", dac_sps=dac_sps, adc_hz=dac_sps,
               channels=2)
        c.wait_frames(600, timeout=20.0)
        frames = list(c.frames)
        c.call("stop")
        # After the stop, deliberately. Asking the board anything
        # mid-playback costs console time the DAC does not have: the
        # banner alone is eleven underruns a call, measured. `B` is
        # short and measures clean, but the rule is worth keeping.
        counters = c.call("counters")["counters"]

        ps = measure._finish(measure.parse_frames(
            b"".join(frames), settle_us=measure.SETTLE_US, settle_cap=16384))
        amps = [a for _, a in ps.window_amplitudes(
            measure.CH_A0, tone_hz, size=8192, from_us=measure.SETTLE_US)]
        assert amps, "no settled window of samples came back"
        amps.sort()
        median = amps[len(amps) // 2]
        floor = baseline["amplitude"]["window_floor_codes"]
        good = sum(1 for a in amps if a >= floor)

        record(calibration, f"daemon_loop_{track}", {
            "median_codes": round(median, 1),
            "windows": len(amps),
            "underruns": counters.get("underruns"),
            "partial": counters.get("partial")})

        assert ps.seq_gaps == 0 and ps.crc_bad == 0
        assert median >= floor, (
            f"median window amplitude {median:.1f} against a {floor} floor: "
            f"what reached the pin is not what the client uploaded")
        assert good >= baseline["amplitude"]["window_fraction"] * len(amps), (
            f"only {good}/{len(amps)} windows reached {floor} codes")
        if counters.get("underruns") is not None:
            assert counters["underruns"] <= \
                baseline["playback"]["ladder_underrun_tolerance"], (
                f"{counters['underruns']} underruns: the daemon's feed did "
                f"not hold the device ring")
        if counters.get("partial") is not None:
            assert counters["partial"] == 0, (
                "a DMA span ended off a slot edge; see the lost-sample "
                "defect in docs/status.md")
    finally:
        c.close()
        srv.stop()
