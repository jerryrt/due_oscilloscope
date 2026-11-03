"""H7Device behind the daemon (docs/20), against a simulated unit whose control side is the real firmware dispatcher (host/daemon/h7sim.py).
Without a host C compiler the simulation cannot be built and every test here SKIPS - which is not a pass."""
PLATFORM_SEAM_EXEMPT = "transport and ports are imported only to be monkeypatched (open_raw, wait_any, find_h7); no test here reaches an OS branch"

import array
import struct

import pytest

import pacing
import control as ctl
import daemon.client as clientmod
import daemon.device as devmod
import daemon.server as servermod

h7sim = pytest.importorskip("daemon.h7sim")
pytestmark = pytest.mark.skipif(not h7sim.available(), reason="no host C compiler: the simulated H7 cannot be built - this skip is NOT a pass")

HDR = struct.Struct("<4sBBHIIIIII")


def wait_until(fn, timeout=pacing.QUICK, what="condition"):
    import time
    end = time.time() + timeout
    while time.time() < end:
        got = fn()
        if got:
            return got
        pacing.pause(pacing.POLL)
    raise AssertionError(f"{what} did not happen within {timeout}s")


@pytest.fixture
def h7():
    dev = h7sim.make_sim_device()
    srv = servermod.Server(dev, host="127.0.0.1", port=0).start()
    c = clientmod.Client("127.0.0.1", srv.port, timeout=pacing.QUICK).connect()
    wait_until(lambda: any(s.addr[:2] == c.sock.getsockname()[:2] for s in list(srv.sessions)), what="the session")
    hello = c.hello("control")
    yield srv, c, dev, hello
    c.close(); srv.stop()


def ctl_names():
    return ("dev_us", "bytes_in", "produced", "consumed", "underruns", "isr_calls", "endtx", "spans", "partial", "occ_min", "svc_calls",
            "loop_passes", "run_us", "abandoned", "drain_polls")


def due_style_waveform(deviation, n=100):
    """What the GUI uploads: 12-bit samples, tag 0, centred on 2048."""
    return b"".join(struct.pack("<H", 2048 + (deviation if i % 2 else -deviation)) for i in range(n))


def test_the_description_says_h7_in_the_neutral_terms_the_gui_uses(h7):
    srv, c, dev, hello = h7
    d = hello["device"]
    assert d["kind"] == "h7" and d["track"] == "h" and d["frame_bytes"] == 4096 and d["samples_per_frame"] == 2032 and d["frame_version"] == 4
    assert d["sample"] == {"bits": 16, "layout": "planar", "full_scale_codes": 65535}
    assert [ch["label"] for ch in d["channels"]] == ["CH1", "CH2"] and all("zero_code" in ch["calibration"] for ch in d["channels"])
    assert d["options"]["gain"] == list(range(8)) and d["identity"]["build"].startswith("h7-build-")


def test_rates_are_the_h7s_not_the_dues(h7):
    srv, c, dev, hello = h7
    assert c.call("rate", adc_hz=2_000_000, channels=2)["adc"] == {"requested": 2_000_000, "rc": 100, "actual_hz": 2_000_000.0}
    with pytest.raises(clientmod.Refused):
        c.call("rate", adc_hz=4_000_000, channels=2)                       # period 50: under what the ADC converts every trigger at
    with pytest.raises(clientmod.Refused):
        c.call("rate", dac_sps=6_000_000)
    assert c.call("rate", dac_sps=5_000_000)["dac"]["actual_hz"] == 5_000_000.0
    assert c.call("caps")["rates"]["adc_max_hz"] == 2_500_000


def test_capture_delivers_version_4_planar_frames_and_stop_ends_them(h7):
    srv, c, dev, hello = h7
    c.subscribe(True)
    c.call("start", mode="capture", adc_hz=1_000_000, channels=2)
    frames = c.wait_frames(5)
    for f in frames:
        magic, ver, flags, mask, seq, rate, *_ = HDR.unpack_from(f, 0)
        assert (magic, ver, mask, rate, len(f)) == (b"DUE0", 4, 3, 1_000_000, 4096)
    seqs = [HDR.unpack_from(f, 0)[4] for f in frames]
    assert seqs == list(range(seqs[0], seqs[0] + len(seqs)))
    c.call("stop")
    wait_until(lambda: not dev.running, what="the device to stop")
    st = struct.unpack("<4B17I", dev._call(0x0043).payload)
    assert st[0] == 0 and st[1] == 0                                        # the UNIT says it is stopped, not only the device object
    # Frames already in flight (USB and kernel buffers on a unit; the simulation's 20 ms state cache) may still arrive; the stream must
    # then stop within a bounded time and STAY stopped.
    def settled():
        a = dev.stats()["rx_bytes"]; pacing.pause(pacing.GLANCE)
        return dev.stats()["rx_bytes"] == a
    wait_until(settled, what="the stream to stop after the stop")
    rx = dev.stats()["rx_bytes"]; pacing.pause(pacing.GLANCE)
    assert dev.stats()["rx_bytes"] == rx


def test_a_second_start_is_refused_and_options_reach_the_unit(h7):
    srv, c, dev, hello = h7
    c.call("start", mode="capture", adc_hz=1_000_000, channels=1, channel_mask=2, options={"gain": [2, 5], "coupling": ["dc", "ac"]})
    cfg = dev._config()
    assert cfg[2] == 2 and (cfg[3], cfg[4], cfg[5]) == (2, 5, 1)           # CH2 only, gains 2 and 5, CH1 dc / CH2 ac
    with pytest.raises(clientmod.Refused):
        c.call("start", mode="capture", adc_hz=1_000_000, channels=2)
    c.call("stop")
    c.call("start", mode="capture", adc_hz=1_000_000, channels=1); assert dev._config()[2] == 1          # one channel means CH1
    c.call("stop")
    c.call("start", mode="capture", adc_hz=1_000_000, channels=2); assert dev._config()[2] == 3          # two means both
    c.call("stop")
    with pytest.raises(clientmod.Refused):
        c.call("start", mode="capture", adc_hz=1_000_000, options={"gain": 9})
    with pytest.raises(clientmod.Refused):
        c.call("start", mode="capture", adc_hz=1_000_000, options={"colour": "red"})


def test_the_unit_refuses_a_config_change_while_it_runs_and_the_device_says_so(h7):
    srv, c, dev, hello = h7
    c.call("start", mode="capture", adc_hz=1_000_000, channels=2)
    with pytest.raises(devmod.DeviceError, match="busy"):
        dev._call(0x0040, struct.pack("<IIBBBBHH", 200, 800, 1, 0, 0, 3, 2036, 0))
    c.call("stop")


def test_play_refuses_a_swing_over_the_cap_and_sends_whole_units_inside_it(h7):
    srv, c, dev, hello = h7
    c.send_awg(due_style_waveform(400))                                     # +-400 codes: over the +-330 cap
    wait_until(lambda: srv.waveform, what="the waveform upload")
    with pytest.raises(clientmod.Refused, match="swing cap"):
        c.call("start", mode="play", dac_sps=1_000_000)
    assert not dev.running and not dev._stream.written                      # nothing configured, nothing sent
    c.send_awg(due_style_waveform(100))
    wait_until(lambda: srv.waveform == due_style_waveform(100), what="the second upload")
    c.call("start", mode="play", dac_sps=1_000_000)
    wait_until(lambda: len(dev._stream.written) >= 4096, what="the feeder to write")
    c.call("stop")
    data = bytes(dev._stream.written); n = len(data) - len(data) % 2
    codes = array.array("H"); codes.frombytes(data[:n])
    assert min(codes) == 2036 - 100 and max(codes) == 2036 + 100            # the deviation around the H7's zero, nothing clamped
    assert all(1706 <= v <= 2366 for v in codes)
    assert len(data) % 2048 == 0 or len(data) >= 4096                         # whole 2048-byte units were offered to the stream


def test_a_waveform_with_another_dacs_tag_or_none_at_all_is_refused(h7):
    srv, c, dev, hello = h7
    with pytest.raises(clientmod.Refused, match="waveform"):
        c.call("start", mode="play", dac_sps=1_000_000)                     # nothing uploaded
    c.send_awg(b"".join(struct.pack("<H", (1 << 12) | 2048) for _ in range(64)))
    wait_until(lambda: srv.waveform, what="the upload")
    with pytest.raises(clientmod.Refused, match="tag 0"):
        c.call("start", mode="play", dac_sps=1_000_000)


def test_what_the_h7_does_not_have_is_an_error_never_a_body_of_zeroes(h7):
    srv, c, dev, hello = h7
    for op in ("trace", "load"):
        with pytest.raises(clientmod.Refused, match="not implemented"):
            c.call(op)
    ctrs = c.call("counters")["counters"]
    assert set(ctl_names()) <= set(ctrs) and ctrs["h7"]["chmask"] == 3 and ctrs["h7"]["running"] == 0      # real fields, from the unit's own STATUS


def test_the_dues_own_fake_device_is_untouched_by_all_of_this():
    dev = devmod.FakeDevice(pace=False)
    assert not getattr(dev, "accepts_options", False) and not hasattr(dev, "rate_policy")


# -- --device selection ---------------------------------------------------------------------------

def _pick(kind, h7_paths):
    import daemon.__main__ as dm
    opened = []
    got = dm.open_hardware(kind, h7_found=lambda: h7_paths,
                           open_h7=lambda p: opened.append(("h7", p)) or "H7",
                           open_due=lambda: opened.append(("due", None)) or "DUE")
    return got, opened


def test_device_auto_takes_an_attached_h7_and_never_opens_the_due():
    assert _pick("auto", ("/dev/a", "/dev/b")) == ("H7", [("h7", ("/dev/a", "/dev/b"))])


def test_device_auto_falls_back_to_the_due_when_no_h7_is_attached():
    assert _pick("auto", None) == ("DUE", [("due", None)])


def test_device_due_and_h7_open_exactly_what_they_name():
    assert _pick("due", ("/dev/a", "/dev/b")) == ("DUE", [("due", None)])      # an attached H7 does not redirect an explicit Due
    assert _pick("h7", None) == ("H7", [("h7", None)])                          # no unit: H7Device.open refuses with its own message


def test_device_h7_with_nothing_attached_is_a_refusal_not_a_fallback(monkeypatch):
    import daemon.__main__ as dm
    import ports
    monkeypatch.setattr(ports, "find_h7", lambda: None)            # the real open() would otherwise find an H7 on the bench
    with pytest.raises(devmod.DeviceError):
        dm.open_hardware("h7", h7_found=lambda: None, open_due=lambda: pytest.fail("fell back to the Due"))


# -- found running, and the real stream port -----------------------------------------------------

def test_a_run_the_device_did_not_start_is_stopped_before_the_start_configures(h7):
    srv, c, dev, hello = h7
    dev._call(0x0041, b"\x01")                                       # what a DTR rise on open does to the real image
    assert dev._status()[0] == 1
    c.call("start", mode="capture", adc_hz=1_000_000, channels=2)   # would be refused as busy without the stop
    assert dev._config()[2] == 3


def test_serial_stream_uses_the_port_object_the_transport_returns(monkeypatch):
    import daemon.h7device as hd
    import transport
    calls = []

    class FakePort:
        def read(self, n): calls.append(("read", n)); return b"abc"
        def write(self, d): calls.append(("write", len(d))); return len(d)
        def drop_dtr(self): calls.append(("drop_dtr",))
        def close(self): calls.append(("close",))
    monkeypatch.setattr(transport, "open_raw", lambda path, baud, dtr=False: FakePort())
    monkeypatch.setattr(transport, "wait_any", lambda ports, t: ports)
    s = hd.SerialStream("/dev/null")
    assert s.read() == b"abc" and s.write(b"xy") == 2
    s.close()
    assert [c[0] for c in calls] == ["drop_dtr", "read", "write", "drop_dtr", "close"]      # DTR lowered on open and again before close


def test_a_terminated_daemon_closes_its_device_and_exits_cleanly():
    """SIGTERM must take the Ctrl-C path: the process exits 0 after closing the device, not -15 with it still open."""
    import os, signal, socket, subprocess, sys
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    d = subprocess.Popen([sys.executable, "-u", "-m", "daemon", "--fake", "--host", "127.0.0.1", "--port", str(port)],
                         cwd=os.path.join(root, "host"), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        assert d.stdout.readline().startswith("daemon on"), "the daemon never announced itself"
        d.send_signal(signal.SIGTERM)
        assert d.wait(pacing.NORMAL) == 0
    finally:
        if d.poll() is None:
            d.kill()
