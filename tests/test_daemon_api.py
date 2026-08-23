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
        c = clientmod.Client("127.0.0.1", (server or srv).port,
                             timeout=timeout).connect()
        if role:
            c.hello(role)
        made.append(c)
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

    c = connect("observer")             # hello caches the description
    srv.device = Loud()
    st = c.call("status")["status"]
    assert "stats" in st
    assert st["device"]["kind"] == "fake"


def test_counters_are_available_when_asked_for(connect):
    got = connect().call("counters")["counters"]
    assert "underruns" in got


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
