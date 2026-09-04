"""The daemon's API, over a real socket, against a synthetic device.

Why no board here: what these tests judge - framing, ownership,
refusals, backpressure, recording - is not a property of the Due, and
tying it to hardware would mean the API could only be exercised at a
bench. The hardware suite around this file still runs on the real
thing for everything about signals, timing and transport, and
`test_daemon_hardware.py` carries the one case that needs both.

The synthetic device produces frames in the device's own format, CRC
and sequence numbers included, so `measure.parse_frames` is what checks
they arrived intact.
"""

import gc
import json
import os
import socket
import sys
import threading
import time

import pytest

import measure
from daemon import client as clientmod
from daemon import device as devmod
from daemon import protocol as proto
from daemon import rates as ratemod
from daemon import server as servermod


def wait_until(fn, timeout=5.0, what="condition"):
    end = time.time() + timeout
    while time.time() < end:
        got = fn()
        if got:
            return got
        time.sleep(0.02)
    raise AssertionError(f"{what} did not happen within {timeout}s")


@pytest.fixture
def make_server():
    made = []

    def _make(**kw):
        pace = kw.pop("pace", True)
        dev = kw.pop("device", None) or devmod.FakeDevice(pace=pace)
        srv = servermod.Server(dev, host="127.0.0.1", port=0, **kw).start()
        made.append(srv)
        return srv

    yield _make
    for s in made:
        s.stop()


@pytest.fixture
def srv(make_server):
    return make_server()


@pytest.fixture
def connect(srv):
    made = []

    def _connect(role=None, server=None, timeout=5.0):
        target = server or srv
        c = clientmod.Client("127.0.0.1", target.port,
                             timeout=timeout).connect()
        made.append(c)
        # A TCP connect completes in the kernel's backlog, so returning
        # from it says nothing about whether the daemon has accepted the
        # socket. Until the accept loop has, the client is not in
        # `sessions`, and a broadcast issued in that window does not
        # queue for it - it is addressed to the sessions that exist and
        # the client never learns there was one. Wait for the session by
        # the address the kernel gave this socket, or a test that
        # expects an event it did not ask for is racing the accept
        # thread over a window of a millisecond or two.
        mine = c.sock.getsockname()[:2]
        wait_until(lambda: any(s.addr[:2] == mine
                               for s in list(target.sessions)),
                   what="the daemon to accept the connection")
        if role:
            c.hello(role)
        return c

    yield _connect
    for c in made:
        c.close()


# -- handshake and ownership -----------------------------------------

@pytest.mark.smoke
def test_hello_reports_the_protocol_and_the_device(connect):
    reply = connect().hello()
    assert reply["event"] == "hello"
    assert reply["protocol"] == proto.PROTOCOL_VERSION
    assert reply["role"] == "observer"
    assert reply["device"]["kind"] == "fake"


@pytest.mark.smoke
def test_the_first_client_to_ask_gets_control(connect):
    assert connect().hello("control")["role"] == "control"


def test_a_second_control_client_is_told_it_did_not_get_it(connect):
    """Silently demoting a client that asked for control is how two
    front ends end up both believing they own the board."""
    connect("control")
    second = connect().hello("control")
    assert second["role"] == "observer"
    assert second["granted"] is False


def test_an_observer_cannot_drive_the_device(connect):
    connect("control")
    observer = connect("observer")
    with pytest.raises(clientmod.Refused) as e:
        observer.call("start", mode="capture", adc_hz=200000)
    assert e.value.code == "not_control"


def test_control_is_released_when_its_holder_disconnects(srv, connect):
    holder = connect("control")
    holder.close()
    wait_until(lambda: srv.controller is None, what="control release")
    assert connect().hello("control")["role"] == "control"


# -- command surface --------------------------------------------------

@pytest.mark.smoke
def test_ping_answers_with_the_id_it_was_given(connect):
    c = connect()
    reply = c.call("ping")
    assert reply["event"] == "pong"
    assert reply["id"] == 1


def test_an_unknown_op_is_named_in_the_error(connect):
    with pytest.raises(clientmod.Refused) as e:
        connect().call("nonsense")
    assert e.value.code == "unknown_op"
    assert "nonsense" in e.value.message


def test_malformed_json_does_not_take_the_connection_down(connect):
    c = connect("control")
    c.send_raw(proto.encode(proto.T_CMD, b"{not json"))
    evt = c.wait_event("error")
    assert evt["code"] == "bad_json"
    assert c.call("ping")["event"] == "pong"


def test_a_client_may_not_send_events(connect):
    c = connect()
    c.send_raw(proto.encode_json(proto.T_EVT, {"event": "hello"}))
    assert c.wait_event("error")["code"] == "bad_type"


def test_a_broken_frame_closes_one_connection_and_no_others(srv, connect):
    good = connect()
    bad = connect()
    bad.send_raw(b"\x00\x00\x00\x00\x00\x00\x00\x00")
    wait_until(lambda: len(srv.sessions) == 1, what="the bad client to go")
    assert good.call("ping")["event"] == "pong"


def test_caps_carries_the_limits_a_client_would_otherwise_hardcode(connect):
    caps = connect().call("caps")
    assert caps["rates"]["acq_min_rc"] == {"1": 44, "2": 86} or \
           caps["rates"]["acq_min_rc"] == {1: 44, 2: 86}
    assert caps["rates"]["dac_max_hz"] == ratemod.hz_for(ratemod.DAC_MIN_RC)
    assert "capability report" not in caps["rates"]["source"]
    assert set(caps["modes"]) == set(devmod.MODES)


# -- rates ------------------------------------------------------------

@pytest.mark.smoke
def test_a_rate_that_divides_the_clock_comes_back_unchanged(connect):
    got = connect().call("rate", adc_hz=200000, channels=2)["adc"]
    assert (got["rc"], got["actual_hz"]) == (195, 200000)


def test_a_rate_between_two_dividers_reports_the_one_it_will_get(connect):
    """The defect this prevents: a header that declared the requested
    rate rather than the one the hardware makes."""
    got = connect().call("rate", adc_hz=200001, channels=2)["adc"]
    assert got["requested"] == 200001
    assert got["actual_hz"] == ratemod.hz_for(got["rc"]) == 201030


def test_a_capture_rate_past_the_trigger_floor_is_refused_by_name(connect):
    with pytest.raises(clientmod.Refused) as e:
        connect().call("rate", adc_hz=906976, channels=2)
    assert e.value.code == "refused"
    assert "RC 86" in e.value.message and "silently" in e.value.message


def test_one_channel_has_its_own_floor_and_it_is_not_half(connect):
    """RC 43 measures a clean ratio and is still wrong: the two-channel
    floor cannot be halved, which is why the table is measured."""
    c = connect()
    assert c.call("rate", adc_hz=886363, channels=1)["adc"]["rc"] == 44
    with pytest.raises(clientmod.Refused):
        c.call("rate", adc_hz=906976, channels=1)


def test_a_dac_rate_past_the_dacc_ceiling_is_refused(connect):
    with pytest.raises(clientmod.Refused) as e:
        connect().call("rate", dac_sps=2000000)
    assert "DACC ceiling" in e.value.message


def test_starting_reports_the_rate_the_hardware_will_produce(connect):
    reply = connect("control").call("start", mode="capture", adc_hz=200001,
                                    channels=2)
    assert reply["rates"]["adc"]["actual_hz"] == 201030


# -- streaming --------------------------------------------------------

@pytest.mark.smoke
def test_frames_arrive_and_parse_as_the_device_wrote_them(connect):
    c = connect("control")
    c.subscribe()
    c.call("start", mode="capture", adc_hz=200000, channels=2)
    frames = c.wait_frames(5, timeout=10.0)
    assert all(len(f) == devmod.FRAME_BYTES for f in frames)
    ps = measure._finish(measure.parse_frames(b"".join(frames)))
    assert ps.frames >= 5
    assert ps.seq_gaps == 0 and ps.crc_bad == 0
    assert ps.declared_rate_hz == 200000


def test_a_client_gets_no_frames_until_it_subscribes(connect):
    c = connect("control")
    c.call("start", mode="capture", adc_hz=200000, channels=2)
    time.sleep(0.3)
    assert c.frames_received == 0
    c.subscribe()
    c.wait_frames(2, timeout=10.0)


def test_unsubscribing_stops_them(connect):
    c = connect("control")
    c.subscribe()
    c.call("start", mode="capture", adc_hz=200000, channels=2)
    c.wait_frames(2, timeout=10.0)
    c.subscribe(frames=False)
    time.sleep(0.1)
    settled = c.frames_received
    time.sleep(0.3)
    assert c.frames_received == settled


def test_the_device_is_drained_even_with_nobody_listening(srv, connect):
    """A CDC device that stops being drained hangs the host in close().
    The reader runs whether or not anyone wants the data."""
    c = connect("control")
    c.call("start", mode="capture", adc_hz=200000, channels=2)
    first = wait_until(lambda: srv.frames_read, what="frames read")
    wait_until(lambda: srv.frames_read > first + 5, what="more frames read")
    assert not any(s.subscribed for s in srv.sessions)


def test_two_clients_see_the_same_frames(connect):
    a = connect("control")
    b = connect()
    a.subscribe()
    b.subscribe()
    a.call("start", mode="capture", adc_hz=200000, channels=2)
    fa = a.wait_frames(4, timeout=10.0)
    fb = b.wait_frames(4, timeout=10.0)
    assert fa[0][:32] == fb[0][:32]


def test_stopping_stops_the_device_and_tells_everyone(connect):
    a = connect("control")
    b = connect()
    a.call("start", mode="capture", adc_hz=200000, channels=2)
    b.wait_event("started")
    a.call("stop")
    assert b.wait_event("stopped")["event"] == "stopped"


def test_status_describes_what_is_going_on(srv, connect):
    c = connect("control")
    c.subscribe()
    c.call("start", mode="capture", adc_hz=200000, channels=2)
    c.wait_frames(2, timeout=10.0)
    st = c.call("status")["status"]
    assert st["running"] is True and st["mode"] == "capture"
    assert st["rates"]["adc_hz"] == 200000
    assert st["frames_read"] >= 2
    assert st["controller"] is not None
    assert any(s["subscribed"] for s in st["clients"])
    assert st["protocol"] == proto.PROTOCOL_VERSION


# -- backpressure -----------------------------------------------------

def test_a_client_that_stops_reading_loses_frames_and_nothing_else_does(
        make_server):
    """The rule the display and the recorder both live by: drop, count,
    and keep going. A wedged client must not slow the device or anyone
    else, and it must not be able to hide what it missed."""
    srv = make_server(pace=False, client_queue_frames=4)

    raw = socket.create_connection(("127.0.0.1", srv.port))
    raw.sendall(proto.encode_json(proto.T_CMD, {"op": "hello", "id": 1}))
    raw.sendall(proto.encode_json(proto.T_CMD,
                                  {"op": "subscribe", "frames": True,
                                   "id": 2}))

    good = clientmod.Client("127.0.0.1", srv.port).connect()
    try:
        good.hello("control")
        good.subscribe()
        good.call("start", mode="capture", adc_hz=200000, channels=2)

        dropped = wait_until(
            lambda: max((s.dropped for s in srv.sessions), default=0) > 0,
            timeout=20.0, what="the silent client to start losing frames")
        assert dropped > 0
        before = good.frames_received
        wait_until(lambda: good.frames_received > before + 20, timeout=20.0,
                   what="the reading client to keep receiving")
        st = good.call("status")["status"]
        assert any(cl["dropped"] > 0 for cl in st["clients"])
    finally:
        good.close()
        raw.close()


# -- waveform ---------------------------------------------------------

def test_a_waveform_upload_is_held_for_the_next_play(srv, connect):
    c = connect("control")
    c.send_awg(b"\x01\x02" * 512)
    evt = c.wait_event("awg_ok")
    assert evt["bytes"] == 1024 and evt["held"] == 1024
    assert srv.waveform == b"\x01\x02" * 512
    assert c.call("status")["status"]["waveform_bytes"] == 1024


def test_a_second_upload_replaces_the_first(srv, connect):
    c = connect("control")
    c.send_awg(b"a" * 16)
    c.wait_event("awg_ok")
    c.send_awg(b"b" * 8)
    c.wait_event("awg_ok")
    assert srv.waveform == b"b" * 8


def test_an_observer_cannot_upload_a_waveform(connect):
    connect("control")
    obs = connect()
    obs.send_awg(b"\x00" * 8)
    assert obs.wait_event("error")["code"] == "not_control"


# -- recording --------------------------------------------------------

@pytest.mark.smoke
def test_a_recording_is_the_frames_verbatim(tmp_path, connect):
    """Byte-identical, headers included. Sequence numbers, timestamps
    and the overrun flag stay in the file, which is what makes
    continuity provable after the fact rather than assumed."""
    path = str(tmp_path / "cap.due")
    c = connect("control")
    c.subscribe()
    c.call("start", mode="capture", adc_hz=200000, channels=2)
    c.wait_frames(2, timeout=10.0)
    c.call("record.start", path=path)
    c.wait_frames(c.frames_received + 6, timeout=10.0)
    side = c.call("record.stop")["sidecar"]
    c.call("stop")

    blob = open(path, "rb").read()
    assert side["frames"] >= 5
    assert side["dropped"] == 0 and side["error"] is None
    assert len(blob) == side["bytes"] == side["frames"] * devmod.FRAME_BYTES
    ps = measure._finish(measure.parse_frames(blob))
    assert ps.seq_gaps == 0 and ps.crc_bad == 0
    # The frames in the file are frames the client also received.
    got = set(bytes(f) for f in c.frames)
    n = devmod.FRAME_BYTES
    assert any(blob[i:i + n] in got for i in range(0, len(blob), n))


def test_the_sidecar_says_what_the_frames_cannot(tmp_path, connect):
    path = str(tmp_path / "cap.due")
    c = connect("control")
    c.call("start", mode="capture", adc_hz=200000, channels=2)
    c.call("record.start", path=path)
    time.sleep(0.2)
    c.call("record.stop")
    side = json.load(open(path + ".json"))
    assert side["rates"]["adc_hz"] == 200000
    assert side["mode"] == "capture"
    assert side["frame_bytes"] == devmod.FRAME_BYTES
    assert side["device"]["kind"] == "fake"
    assert side["stopped_unix"] >= side["started_unix"]
    assert "verbatim" in side["note"] or "exactly" in side["note"]


def test_recording_twice_at_once_is_refused(tmp_path, connect):
    c = connect("control")
    c.call("record.start", path=str(tmp_path / "one.due"))
    with pytest.raises(clientmod.Refused) as e:
        c.call("record.start", path=str(tmp_path / "two.due"))
    assert "already recording" in e.value.message
    c.call("record.stop")


def test_stopping_a_recording_that_never_started_is_refused(connect):
    with pytest.raises(clientmod.Refused):
        connect("control").call("record.stop")


def test_a_recording_survives_the_client_that_asked_for_it(tmp_path,
                                                           srv, connect):
    """The reason the daemon writes the file and the GUI does not."""
    path = str(tmp_path / "cap.due")
    c = connect("control")
    c.call("start", mode="capture", adc_hz=200000, channels=2)
    c.call("record.start", path=path)
    c.close()
    wait_until(lambda: srv.controller is None, what="control release")
    before = srv.recorder.frames
    wait_until(lambda: srv.recorder.frames > before + 3, timeout=10.0,
               what="the recording to continue")
    side = srv.recorder.stop()
    srv.recorder = None
    assert side["frames"] > before
    assert os.path.getsize(path) == side["bytes"]


# -- device errors ----------------------------------------------------

def test_the_console_op_needs_a_device_that_has_one(connect):
    with pytest.raises(clientmod.Refused) as e:
        connect("control").call("console", text="h")
    assert "console" in e.value.message


def test_starting_an_unknown_mode_is_refused(connect):
    with pytest.raises(clientmod.Refused) as e:
        connect("control").call("start", mode="telepathy")
    assert "telepathy" in e.value.message


def test_starting_twice_is_refused_rather_than_silently_restarting(connect):
    c = connect("control")
    c.call("start", mode="capture", adc_hz=200000, channels=2)
    with pytest.raises(clientmod.Refused):
        c.call("start", mode="capture", adc_hz=200000, channels=2)


def test_an_internal_failure_is_reported_not_swallowed(srv, connect):
    class Broken(devmod.FakeDevice):
        def counters(self):
            raise ZeroDivisionError("boom")

    srv.device = Broken()
    with pytest.raises(clientmod.Refused) as e:
        connect().call("counters")
    assert e.value.code == "internal" and "ZeroDivisionError" in e.value.message


def test_status_never_asks_the_device_anything(srv, connect):
    """Status is a poll path. Asking the board for its banner while it
    plays costs eleven underruns, every call - measured - so anything a
    client may poll must be answerable from the host alone."""
    class Loud(devmod.FakeDevice):
        def counters(self):
            raise AssertionError("status must not ask the device")

        def describe(self, *a, **kw):
            raise AssertionError("status must not ask the device")

        def trace(self):
            raise AssertionError("status must not ask the device")

    c = connect("observer")             # hello caches the description
    srv.device = Loud()
    st = c.call("status")["status"]
    assert "stats" in st
    assert st["device"]["kind"] == "fake"


def test_counters_are_available_when_asked_for(connect):
    got = connect().call("counters")["counters"]
    assert "underruns" in got


def test_the_rate_trace_is_available_when_asked_for(connect):
    """`trace` is its own operation, not part of `counters`.

    Different device command, a reply two orders of magnitude longer,
    and a different question: counters say what went wrong, the trace
    says what rate the converter actually held. Folding them together
    would put a 256-entry reply on a path clients are expected to call
    often.
    """
    got = connect().call("trace")["trace"]
    for key in ("rate_decim", "rate_us", "window_rates", "traced_byte_rate"):
        assert key in got, f"trace reply is missing {key}: {sorted(got)}"

    # The windows must be derivable from the timestamps, because that is
    # the whole contract: the device sends absolute microseconds and the
    # host differences them.
    decim, us = got["rate_decim"], got["rate_us"]
    assert len(got["window_rates"]) == len(us) - 1
    expected = decim * 1024 * 1e6 / (us[1] - us[0])
    assert got["window_rates"][0] == pytest.approx(expected)


# -- lifecycle --------------------------------------------------------

def test_the_server_leaves_no_threads_behind(make_server):
    before = set(threading.enumerate())
    srv = make_server()
    c = clientmod.Client("127.0.0.1", srv.port).connect()
    c.hello("control")
    c.subscribe()
    c.call("start", mode="capture", adc_hz=200000, channels=2)
    c.wait_frames(2, timeout=10.0)
    c.close()
    srv.stop()
    wait_until(lambda: not (set(threading.enumerate()) - before),
               timeout=10.0, what="every daemon thread to exit")


def test_the_bind_address_is_a_setting(make_server):
    """Open by default on a trusted network, but as a parameter, so the
    day it runs somewhere less trusted is a config change."""
    srv = make_server()
    assert srv.host == "127.0.0.1"
    assert servermod.Server(devmod.FakeDevice()).host == "0.0.0.0"


# -- allocation behaviour ---------------------------------------------

def _stream_and_count(make_server, n_frames):
    """Warm every code path, then measure what streaming actually costs."""
    srv = make_server(pace=False)
    c = clientmod.Client("127.0.0.1", srv.port, timeout=30.0,
                         frame_capacity=16)
    c.connect()
    c.hello("control")
    c.subscribe()
    c.call("start", mode="capture", adc_hz=200000, channels=2)
    c.wait_frames(200, timeout=30.0)
    gc.collect()
    base_blocks = sys.getallocatedblocks()
    base_gen0 = gc.get_stats()[0]["collections"]
    start = c.frames_received
    c.wait_frames(start + n_frames, timeout=60.0)
    out = (sys.getallocatedblocks() - base_blocks,
           gc.get_stats()[0]["collections"] - base_gen0,
           c.frames_received - start)
    c.call("stop")
    c.close()
    return out


@pytest.mark.slow
def test_streaming_does_not_grow_the_heap(make_server):
    """A daemon that allocates per frame has a pause waiting to happen.

    The frame bytes are not the problem - the cycle collector does not
    even track them. Container churn is: a tuple per frame per client is
    a tracked object 442 times a second. So frames and events ride
    separate queues and the 8-byte header is cached per length rather
    than concatenated onto 4 KB of payload.

    Measured after that change: 2,000 frames grow the heap by 40 to 96
    blocks in total, which is not a function of the frame count. The
    bound here is far above what was measured and far below anything
    proportional.
    """
    blocks, _, got = _stream_and_count(make_server, 2000)
    assert got >= 2000
    assert blocks < 500, (
        f"{blocks} blocks for {got} frames ({blocks / got:.2f} each): the "
        f"streaming path is allocating per frame again")


@pytest.mark.slow
def test_streaming_does_not_wake_the_cycle_collector(make_server):
    """Measured at zero collections over 2,000 frames, twice."""
    _, gen0, got = _stream_and_count(make_server, 2000)
    assert gen0 <= 1, (
        f"{gen0} generation-0 collections while streaming {got} frames: "
        f"something in the hot path is creating tracked containers")


def test_the_daemon_can_quiet_the_cycle_collector(make_server):
    """Off by default, because importing a library must not change the
    collector of whatever process loads it. The daemon process turns it
    on for itself."""
    assert gc.isenabled(), "the test process should start with gc on"
    srv = make_server(tune_gc=True)
    try:
        assert not gc.isenabled()
    finally:
        srv.stop()
    assert gc.isenabled(), "stopping the daemon must give the collector back"


# -- latency instrumentation ------------------------------------------

@pytest.mark.smoke
def test_status_carries_where_the_latency_is(connect):
    """Counters say a buffer went dry; these say by how much the thread
    that fills it was late, which is the number a fix has to move."""
    c = connect("control")
    c.subscribe()
    c.call("start", mode="capture", adc_hz=200000, channels=2)
    c.wait_frames(20, timeout=15.0)
    j = c.call("status")["status"]["jitter"]

    assert set(j) >= {"read_gap", "fanout"}
    assert j["read_gap"]["n"] > 0
    assert j["fanout"]["n"] >= 20
    for name in ("read_gap", "fanout"):
        s = j[name]
        assert s["max_us"] >= s["mean_us"], f"{name}: a maximum below its mean"
        assert s["p99_us"] >= 0


def test_the_fanout_cost_is_recorded_per_frame(connect):
    """One sample per frame, not per client and not per read: the
    question it answers is what a frame costs the reader thread."""
    c = connect("control")
    c.subscribe()
    c.call("start", mode="capture", adc_hz=200000, channels=2)
    c.wait_frames(30, timeout=15.0)
    st = c.call("status")["status"]
    # The status reply is a snapshot, not an atomic one: frames_read is
    # read before the histograms are, so a frame that arrives between
    # the two leaves fan-out one ahead. Locking the read path to tidy
    # that up would cost more than the tidiness is worth.
    assert st["jitter"]["fanout"]["n"] <= st["frames_read"] + 2
    assert st["jitter"]["fanout"]["n"] >= 25

# -- replay -----------------------------------------------------------
#
# The other half of recording, and until it existed the Record button
# wrote a format with no reader. What these assert is one property and
# its consequences: a recording replayed through the daemon delivers the
# frames that were recorded, byte for byte, so everything above the
# daemon - trigger, measurements, FFT, export - is running over the
# capture rather than over a second decoding of it.


@pytest.fixture
def recording(tmp_path, make_server):
    """A real recording, made the way the front end makes one.

    Recorded through the server rather than written by hand, so what
    the replay tests read back is what `record.start` actually
    produces - sidecar, geometry and all.
    """
    def _record(frames=8, adc_hz=200000, channels=2, name="cap.due"):
        path = str(tmp_path / name)
        # Paced, so the count is close to what was asked for. An
        # unpaced fake produces frames as fast as the reader takes
        # them, and a fixture that overshoots to eighty frames turns
        # every replay assertion below into a race with the drop
        # policy rather than a test of the replay.
        srv = make_server(pace=True)
        c = clientmod.Client("127.0.0.1", srv.port, timeout=5.0,
                             frame_capacity=1024).connect()
        try:
            c.hello("control")
            c.subscribe()
            c.call("start", mode="capture", adc_hz=adc_hz, channels=channels)
            c.call("record.start", path=path)
            wait_until(lambda: srv.recorder and srv.recorder.frames >= frames,
                       timeout=15.0, what=f"{frames} frames recorded")
            side = c.call("record.stop")["sidecar"]
            c.call("stop")
        finally:
            c.close()
        assert side["dropped"] == 0 and side["error"] is None
        return path, open(path, "rb").read(), side
    return _record


def replay(make_server, path, **kw):
    """A server whose device is that recording.

    `pace=False` by default: these tests care what comes out, not how
    fast, and the recordings are short enough that nothing is dropped
    on the way. The paced default is what the GUI gets, and has a test
    of its own below.
    """
    kw.setdefault("pace", False)
    return make_server(device=devmod.FileDevice(path, **kw))


@pytest.mark.smoke
def test_a_replay_delivers_the_bytes_that_were_recorded(recording,
                                                        make_server, connect):
    """The whole claim, in one assertion.

    Not "the same samples" or "the same measurements" - the same bytes,
    headers included. Anything weaker would let a replay agree with a
    live capture everywhere except where it matters.
    """
    path, blob, side = recording(frames=8)
    srv = replay(make_server, path)
    c = connect("control", server=srv)
    c.subscribe()
    c.call("start", mode="capture")
    c.wait_frames(side["frames"], timeout=15.0)
    got = b"".join(bytes(f) for f in c.frames)
    assert got == blob


def test_a_replay_says_it_is_a_file_and_which_one(recording, make_server,
                                                  connect):
    path, blob, side = recording(frames=4)
    srv = replay(make_server, path)
    dev = connect("control", server=srv).call("hello", role="control")["device"]
    assert dev["kind"] == "file"
    assert dev["path"] == os.path.basename(path)
    assert dev["frames"] == side["frames"]
    assert dev["truncated_bytes"] == 0


def test_a_replay_carries_the_bench_the_samples_came_from(recording,
                                                          make_server,
                                                          connect):
    """`kind` is the source, `recorded` is the origin, and they are two
    fields because conflating them is how a replayed capture gets read
    as a live board of that track. The project has two benches wired
    differently; a capture without its bench is not comparable with
    anything."""
    path, blob, side = recording(frames=4)
    srv = replay(make_server, path)
    dev = connect(server=srv).call("hello", role="observer")["device"]
    assert dev["kind"] == "file"
    assert dev["recorded"]["kind"] == "fake"
    assert dev["recorded_mode"] == "capture"
    assert dev["recorded_rates"]["adc_hz"] == 200000
    assert dev["recorded_dropped"] == 0


def test_a_replay_reports_the_rate_it_was_recorded_at(recording, make_server,
                                                      connect):
    """A file cannot be asked to convert at another rate. Answering
    `status` with the rate the caller asked for would put a number in a
    reply that nothing measured, and every time axis drawn from it would
    be wrong."""
    path, blob, side = recording(frames=4, adc_hz=100000)
    srv = replay(make_server, path)
    c = connect("control", server=srv)
    c.call("start", mode="capture", adc_hz=400000, channels=2)
    st = c.call("status")["status"]
    assert st["rates"]["adc_hz"] == 100000
    assert st["rates"]["source"] == "recording"


def test_a_replay_stops_at_the_end_of_the_recording(recording, make_server,
                                                    connect):
    path, blob, side = recording(frames=6)
    srv = replay(make_server, path)
    c = connect("control", server=srv)
    c.subscribe()
    c.call("start", mode="capture")
    wait_until(lambda: not c.call("status")["status"]["running"],
               timeout=15.0, what="the replay to reach the end")
    ct = c.call("counters")["counters"]
    assert ct["at_end"] is True
    assert ct["frames"] == side["frames"] == ct["frames_total"]
    assert ct["loops"] == 0


def test_a_looping_replay_starts_again_and_the_seam_is_a_gap(recording,
                                                             make_server,
                                                             connect):
    """A loop is a convenience, not a longer capture. The sequence
    numbers jump backwards at the seam, so the daemon counts a gap there
    and the front end draws a discontinuity - which is right: the two
    passes were never continuous."""
    path, blob, side = recording(frames=6)
    srv = replay(make_server, path, loop=True)
    c = connect("control", server=srv)
    c.subscribe()
    c.call("start", mode="capture")
    c.wait_frames(side["frames"] + 3, timeout=15.0)
    ct = c.call("counters")["counters"]
    assert ct["loops"] >= 1
    assert ct["seq_gaps"] >= 1


def test_a_recording_with_another_frame_geometry_is_refused_by_name(
        recording, tmp_path):
    """`frame.h` calls the 4096-byte frame load-bearing and the ramp
    test failed 4 runs in 15 the last time it moved. Read across that
    and every sample after the first header lands at the wrong offset -
    and still decodes to a plausible number, which is the dangerous
    part."""
    path, blob, side = recording(frames=4)
    side["frame_bytes"] = devmod.FRAME_BYTES // 2
    with open(path + ".json", "w") as f:
        json.dump(side, f)
    with pytest.raises(devmod.DeviceError) as e:
        devmod.FileDevice(path)
    assert str(devmod.FRAME_BYTES // 2) in str(e.value)
    assert str(devmod.FRAME_BYTES) in str(e.value)


def test_a_truncated_recording_says_how_much_is_not_a_frame(recording,
                                                            make_server,
                                                            connect):
    """A recorder killed mid-write leaves a part-frame. Trimming it in
    silence would make a file whose end is unknown look like one whose
    end is known."""
    path, blob, side = recording(frames=4)
    with open(path, "ab") as f:
        f.write(b"\x00" * 10)
    srv = replay(make_server, path)
    dev = connect(server=srv).call("hello")["device"]
    assert dev["truncated_bytes"] == 10
    assert dev["frames"] == side["frames"]


def test_a_file_with_no_whole_frame_is_refused(tmp_path):
    path = str(tmp_path / "stub.due")
    with open(path, "wb") as f:
        f.write(b"DUE0" + b"\x00" * 16)
    with pytest.raises(devmod.DeviceError):
        devmod.FileDevice(path)


def test_a_recording_has_no_generator_and_the_refusal_keeps_the_session(
        recording, make_server, connect):
    """The waveform path is not covered by the dispatch guard, so a
    device refusal there used to be a dead connection rather than an
    answer. A front end that uploads to a replay gets told no and stays
    connected."""
    path, blob, side = recording(frames=4)
    srv = replay(make_server, path)
    c = connect("control", server=srv)
    c.send_awg(b"\x00" * 64)
    ev = c.wait_event("error")
    assert ev["code"] == "refused" and "generator" in ev["message"]
    assert c.call("ping")["event"] == "pong"
    assert c.call("status")["status"]["waveform_bytes"] == 0


def test_a_recording_refuses_to_play(recording, make_server, connect):
    path, blob, side = recording(frames=4)
    srv = replay(make_server, path)
    c = connect("control", server=srv)
    with pytest.raises(clientmod.Refused) as e:
        c.call("start", mode="play", dac_sps=200000)
    assert "replay" in e.value.message


def test_a_paced_replay_follows_the_recorded_timestamps(recording,
                                                        make_server, connect):
    """The default, and the reason the GUI can be pointed at a file at
    all: its ring is sized in seconds. Frames come back at the interval
    the device stamped them with rather than as fast as the socket will
    take them."""
    path, blob, side = recording(frames=8, adc_hz=100000)
    srv = replay(make_server, path, pace=True)
    c = connect("control", server=srv)
    c.subscribe()
    t0 = time.monotonic()
    c.call("start", mode="capture")
    c.wait_frames(8, timeout=15.0)
    elapsed = time.monotonic() - t0
    # 2032 samples over two channels at 100 kHz is 10.16 ms a frame, so
    # seven intervals is about 71 ms. The bound is loose on the high
    # side because a scheduler is not a clock; what it has to catch is a
    # replay that ignores the timestamps entirely.
    assert elapsed > 0.04, f"eight frames in {elapsed:.3f}s is not paced"
    assert elapsed < 2.0


# -- what the device holds while it waits -----------------------------
#
# A device that sleeps holding its own lock blocks every client thread
# for as long as it sleeps, and nothing above notices: the frames still
# arrive, and the cost lands on whoever calls `start`, `stop` or
# `status` next. Nor is it visible on an interpreter that hands a
# contended lock over fairly - CPython 3.14 makes a waiter here wait
# 1-11 ms and 3.12 makes it wait 0.3-4.3 s for the same code, so the
# suite trips over this on one interpreter and not the other. These
# assert the property directly instead.


def worst_lock_wait(dev, attempts=20):
    """The longest a client thread waits for a device that is pacing.

    `stats()` is the cheapest client-side call that takes the same lock
    `read()` does, which is the whole content of the measurement: how
    long a reader in its pacing wait keeps everyone else out.
    """
    stop = threading.Event()

    def reader():
        while not stop.is_set():
            dev.read(timeout=0.1)

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    try:
        time.sleep(0.05)                  # let it reach the pacing wait
        worst = 0.0
        for _ in range(attempts):
            t0 = time.monotonic()
            dev.stats()
            worst = max(worst, time.monotonic() - t0)
            time.sleep(0.005)
        return worst
    finally:
        stop.set()
        t.join(timeout=2.0)


# Held well below the 0.1 s a reader spends in one wait, and well above
# the sub-millisecond an uncontended acquire costs, so neither a slow
# bench nor a starved container decides the answer.
LOCK_WAIT_MAX_S = 0.03


def test_a_paced_fake_does_not_hold_its_lock_while_it_waits():
    dev = devmod.FakeDevice(pace=True)
    # 2032 samples over two channels at 2 kHz is half a second a frame,
    # so a reader on a 0.1 s timeout is inside its wait for essentially
    # all of the measurement: the lock is either free throughout or
    # held throughout, and there is no middle reading to interpret.
    dev.start("capture", adc_hz=2000, channels=2)
    try:
        worst = worst_lock_wait(dev)
    finally:
        dev.stop()
    assert worst < LOCK_WAIT_MAX_S, (
        f"a client waited {worst * 1000:.0f} ms for the fake's lock; "
        f"the reader is holding it across its pacing sleep")


def test_a_paced_replay_does_not_hold_its_lock_while_it_waits(recording):
    path, blob, side = recording(frames=8, adc_hz=100000)
    # `speed` rather than a slower recording: 10.16 ms a frame replayed
    # at 1/50 speed is about half a second, which puts this device in
    # the same regime as the fake above with nothing else changed.
    dev = devmod.FileDevice(path, pace=True, speed=0.02)
    dev.start("capture")
    try:
        worst = worst_lock_wait(dev)
    finally:
        dev.close()
    assert worst < LOCK_WAIT_MAX_S, (
        f"a client waited {worst * 1000:.0f} ms for the replay's lock; "
        f"the reader is holding it across its pacing sleep")


# -- the device's own heartbeat --------------------------------------
#
# Issue #33 is why these exist. When Track A's main loop stopped, the
# console, the control channel and GET_LOAD went dark *together* -
# every one of them is answered by that loop - so the board became
# indistinguishable from one that had been unplugged. The beat is
# emitted from a timer interrupt instead, which is what lets it carry
# the failure rather than only vanish with it.

def test_the_heartbeat_is_off_until_a_client_asks(srv, connect):
    """The firmware's decision, and the daemon does not second-guess it.

    A board that pushes at a host which never asked is a board deciding
    for itself what the wire carries.
    """
    c = connect("control")
    assert srv.status()["heartbeat"]["period_ms"] == 0
    time.sleep(0.3)
    assert not [e for e in list(c.events) if e.get("event") == "heartbeat"]


def test_beats_reach_every_client_not_only_subscribers(srv, connect):
    """A subscriber is someone who wants sample frames. Whether the
    board's loop is alive is not a sample, and an observer watching a
    board it does not stream from is exactly who needs to know."""
    ctl = connect("control")
    obs = connect("observer")          # never subscribes
    ctl.call("heartbeat", period_ms=20)
    time.sleep(0.4)
    for who, c in (("controller", ctl), ("observer", obs)):
        beats = [e for e in list(c.events) if e.get("event") == "heartbeat"]
        assert beats, f"{who} got no beats"
        assert "seq" in beats[0]["beat"]


def test_a_frozen_loop_is_reported_while_beats_keep_arriving(srv, connect):
    """The whole point of moving the emitter into a timer interrupt.

    `seq` and `uptime_ms` come from the interrupt and keep advancing;
    `loop_passes` comes from the main loop and stops. A beat arriving
    with a frozen count is the stall reporting itself, live, on a board
    with no console and no debugger.
    """
    c = connect("control")
    c.call("heartbeat", period_ms=20)
    time.sleep(0.2)
    assert srv.status()["heartbeat"]["stalled"] is False
    srv.device.stall_loop = True
    time.sleep(0.4)
    assert srv.status()["heartbeat"]["stalled"] is True
    stalled = [e for e in list(c.events)
               if e.get("event") == "heartbeat" and e.get("stalled")]
    assert stalled, "no beat carried the stall to the clients"
    # And the beats did not stop - that is the difference between this
    # and a board that has simply gone.
    seqs = [e["beat"]["seq"] for e in stalled]
    assert seqs == sorted(seqs) and seqs[-1] > seqs[0]


def test_status_still_asks_the_device_nothing(srv, connect):
    """`docs/daemon-api.md` promises it, and the heartbeat must not be
    the thing that breaks it: beats arrive unbidden, so reporting the
    newest one is reading a variable, not a round trip."""
    c = connect("control")
    c.call("heartbeat", period_ms=20)
    time.sleep(0.2)
    before = srv.device.counters()["frames"]
    for _ in range(20):
        srv.status()
    assert srv.device.counters()["frames"] == before


def test_a_device_without_a_heartbeat_says_so(make_server, connect):
    """Not a body of zeroes. A caller cannot tell that from a board
    whose loop has stopped, which is the distinction this whole feature
    exists to make."""
    class Mute(devmod.FakeDevice):
        def heartbeat(self, period_ms=None, sink=None):
            return {}

        def heartbeat_state(self):
            return devmod.Device.heartbeat_state(self)

    srv = make_server(device=Mute())
    c = connect("control", server=srv)
    assert srv.status()["heartbeat"] == {"supported": False}
    with pytest.raises(clientmod.Refused):
        c.call("heartbeat", period_ms=50)


def test_heartbeat_needs_control(srv, connect):
    """It changes what the board does with its own timer."""
    connect("control")
    obs = connect("observer")
    with pytest.raises(clientmod.Refused) as e:
        obs.call("heartbeat", period_ms=50)
    assert "control" in e.value.message


def test_the_description_names_the_track_without_the_whole_banner():
    """Issue #38.

    `measure.which_track` returns `(track, the text it read it from)`,
    and `describe()` stored the pair whole - so `track` was a tuple
    where every consumer expects a string. The front end formatted it
    straight into its Source line, complete with the escaped CRLF, the
    label's width hint followed its text, and the window blew out to
    22,727 pixels wide. A string comparison elsewhere (`track != "fake"`)
    was silently comparing a tuple and never matching.
    """
    class OneLineBoard:
        def poll_console(self):
            pass

    class M:
        FRAME_BYTES = 4096
        FRAME_SAMPLES = 2032

        @staticmethod
        def which_track(board, **kw):
            return "b", "# id: track=B fw=0.2.0 ctlver=4\r\n"

    dev = devmod.BoardDevice(OneLineBoard(), measure_mod=M())
    info = dev.describe()
    assert info["track"] == "b", "the track must be the letter alone"
    assert isinstance(info["track"], str)
    assert "\r\n" not in str(info["track"])
    # The text is still available, just not masquerading as the track.
    assert info["identity"].startswith("# id:")


# ---------------------------------------------- per-run jitter metrics (#40)

def test_read_gap_is_not_measured_across_a_deliberate_stop(srv, connect):
    """Issue #40: 3.8 s of idle reported as a data-path stall.

    The reader thread runs for the daemon's lifetime and the device does
    not. Without scoping, the first frame of a run measures its gap
    against the last frame of the *previous* run, so the idle time
    between them lands in `read_gap` - and it lands in a column of
    per-run counters, beside Discontinuities and Device overruns, which
    the GUI resets on every start. `tools/gallery.py` produced
    `Read gap max 3,797,000 us` exactly this way.

    The gap here is deliberately long relative to any real one: at
    200 ksps the device produces a frame every few milliseconds, so a
    0.6 s idle is two orders of magnitude above anything the running
    path can generate.
    """
    c = connect("control")
    c.subscribe()
    c.call("start", mode="capture", adc_hz=200000, channels=2)
    c.wait_frames(4, timeout=10.0)
    c.call("stop")

    time.sleep(0.6)

    c.call("start", mode="capture", adc_hz=200000, channels=2)
    c.wait_frames(4, timeout=10.0)
    gap = c.call("status")["status"]["jitter"]["read_gap"]
    c.call("stop")

    assert gap["max_us"] < 300_000, (
        f"read_gap max is {gap['max_us']} us after a 0.6 s stop; the "
        f"idle between two runs has been measured as a read gap")


def test_starting_a_run_resets_the_jitter_histograms(srv, connect):
    """`max` must be this run's, not the daemon's lifetime maximum.

    Two runs, and the second one's summary must not carry the first
    one's sample count. Otherwise the panel reports a maximum over every
    run the daemon has ever served while sitting next to counters that
    are per-run, with nothing on screen to distinguish them.
    """
    c = connect("control")
    c.subscribe()
    c.call("start", mode="capture", adc_hz=200000, channels=2)
    c.wait_frames(8, timeout=10.0)
    first = c.call("status")["status"]["jitter"]["read_gap"]["n"]
    c.call("stop")
    assert first > 0, "no read gaps recorded at all; the test proves nothing"

    c.call("start", mode="capture", adc_hz=200000, channels=2)
    c.wait_frames(2, timeout=10.0)
    second = c.call("status")["status"]["jitter"]["read_gap"]["n"]
    c.call("stop")

    assert second < first, (
        f"the second run reports {second} read-gap samples against the "
        f"first run's {first}; the histogram was never reset, so `max` "
        f"is a lifetime figure in a per-run column")


def test_only_the_server_reports_jitter(srv):
    """One home for the metric, because there used to be three.

    `_Session` and `_Recorder` each carried a byte-identical copy of
    `jitter()` referring to `self.read_gap` and `self.fanout`, which
    neither class has ever defined. Both were dead and both would have
    raised AttributeError if anything had called them - and a metric
    added to the live copy would have drifted from two silent ones.
    """
    from daemon import server as servermod
    assert hasattr(servermod.Server, "jitter")
    for cls in (servermod._Session, servermod._Recorder):
        assert not hasattr(cls, "jitter"), (
            f"{cls.__name__} has a jitter() again. It has no read_gap "
            f"and no fanout, so it is dead code that raises on call and "
            f"drifts from Server.jitter() in the meantime")


def test_load_is_its_own_operation_and_never_rides_on_status(srv, connect):
    """`Control.load` existed and no host could reach it.

    The device has a load metric - `bsp/load.c`, GET_LOAD - and CLAUDE.md
    is explicit that new instrumentation goes there rather than into a
    printf, because one console status command blocks the main loop for
    13-20 ms while twenty GET_LOAD queries cost 0.29 ms in total. The
    control-channel client implemented it. The daemon never exposed it,
    so the only way to ask a running board how hard its loop was working
    was the method the rule exists to forbid.

    It is its own op for the same reason `trace` is, and it stays off
    the poll path: `docs/daemon-api.md` guarantees status asks the
    device nothing.
    """
    c = connect("control")
    load = c.call("load")["load"]
    assert load["passes"] > 0
    assert load["hist"] and any(load["hist"])
    # The fake must answer with the device's own keys and nothing else.
    # It did not, at first: it invented `mean_us`, and the first script
    # written against it failed on a board instead of in this suite.
    for key in ("dev_us", "passes", "max_cycles", "max_us", "mck_hz",
                "hist", "hist_us"):
        assert key in load, f"the fake is missing {key!r}"
    assert "mean_us" not in load, (
        "the device does not return mean_us; a fake that does teaches "
        "callers a field that is not there")

    status = c.call("status")["status"]
    assert "load" not in status, (
        "status must stay answerable without asking the device anything")
