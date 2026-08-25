"""
The native port's control channel.

Two halves. The framing tests need no board and cover what the codec
rejects, which is most of what a framing layer is for - a parser that
meets a frame it did not expect must reject it rather than half-read
it. The protocol tests talk to the board and check that the device
agrees, including on every refusal: the error path is the half that
never runs by accident, so it is exercised deliberately here.

Both halves skip on Track A, which has no control channel yet. When it
grows one they must pass unchanged against both, because the wire
format is the only thing the two tracks share.
"""

import struct
import time
import zlib

import pytest

import control
import measure
import ports

pytestmark = pytest.mark.smoke


# ---------------------------------------------------------------- codec

def test_encode_round_trips():
    frame, rest = control.decode(control.encode(control.OP_PING, 42))
    assert rest == b""
    assert (frame.opcode, frame.req_id, frame.crc_ok) == (
        control.OP_PING, 42, True)


def test_decode_resyncs_on_the_magic():
    """Leading rubbish is skipped, not misread.

    The channel is a byte stream shared with nothing, but a host that
    reconnects mid-frame sees exactly this, and half-reading it would
    turn a resync into a wrong answer.
    """
    wire = b"\x00\x01DUE" + control.encode(control.OP_IDENTITY, 3)
    frame, rest = control.decode(wire)
    assert frame is not None and frame.opcode == control.OP_IDENTITY
    assert rest == b""


def test_decode_waits_for_a_whole_frame():
    wire = control.encode(control.OP_PING, 1, b"12345678")
    for cut in range(1, len(wire)):
        frame, rest = control.decode(wire[:cut])
        assert frame is None, f"decoded a frame from {cut} of {len(wire)} bytes"
    frame, rest = control.decode(wire)
    assert frame is not None and rest == b""


def test_decode_flags_a_bad_checksum_rather_than_raising():
    """A corrupt frame is data, not an exception.

    The caller decides: the device answers a bad checksum with an
    error, and the host raises. Deciding here would take that choice
    away from both.
    """
    frame, _ = control.decode(control.encode(control.OP_PING, 1,
                                             crc=0xdeadbeef))
    assert frame is not None and frame.crc_ok is False


def test_encoded_header_matches_the_documented_layout():
    """The header is a contract, so it is asserted byte by byte.

    Track A has to reach this same layout through different code. A
    test that only checked the codec against itself would pass while
    the two tracks disagreed.
    """
    wire = control.encode(0x1234, 0xabcd, b"xy")
    assert wire[0:4] == b"DUEC"
    assert wire[4] == control.VERSION
    assert wire[5] == 0                                   # flags
    assert struct.unpack_from("<H", wire, 6)[0] == 0xabcd  # req_id
    assert struct.unpack_from("<H", wire, 8)[0] == 0x1234  # opcode
    assert struct.unpack_from("<H", wire, 10)[0] == 2      # length
    assert struct.unpack_from("<I", wire, 12)[0] == (
        zlib.crc32(wire[:12] + b"xy") & 0xffffffff)
    assert wire[16:] == b"xy"


# ------------------------------------------------------------- hardware

@pytest.fixture
def link(board, track):
    """An open conversation with the command port."""
    if track != "b":
        pytest.skip("Track A has no control channel yet")
    # The board owns the one control link for the session, the same way
    # it owns the console port and for the same reason. A fixture that
    # opened its own used to work; it stopped the day measure.py started
    # using the channel too, because the port does not open twice.
    c = board.ctl()
    if c is None:
        pytest.fail("the board does not present a command port")
    try:
        yield c
    finally:
        # Take whatever is still in flight off the wire before closing.
        # These tests deliberately provoke refusals, and a queue left
        # full at close() is how objective 0c starts.
        # Drained, not closed: the board owns it.
        c.drain()


def test_ping_answers_and_counts(link):
    """Liveness, and the device's own clock.

    seq increments so that a cached or duplicated response cannot pass
    as a fresh one, and dev_us advances so a frozen main loop is
    distinguishable from a healthy quiet one.
    """
    us0, ms0, seq0 = link.ping()
    time.sleep(0.05)
    us1, ms1, seq1 = link.ping()
    assert seq1 == seq0 + 1, "ping sequence did not advance"
    assert us1 > us0, "the device clock did not advance between pings"
    assert 30 <= (us1 - us0) / 1000.0 <= 500, (
        f"a 50 ms sleep measured {(us1 - us0) / 1000.0:.0f} ms on the "
        f"device clock; suspect the main loop is blocked")


def test_identity_reports_this_board(link, board, baseline):
    """What a host would refuse a mismatched pairing on.

    Checked against the same baseline the banner is checked against,
    so the control channel and the console cannot disagree about the
    clock without one of them failing.
    """
    ident = link.identity()
    assert ident["track"] == "b"
    assert ident["ctl_version"] == control.VERSION
    assert ident["mck_hz"] == baseline["clock"]["mck_hz"]
    assert ident["adc_clock_hz"] == baseline["clock"]["adc_clock_hz"]
    assert ident["frame_bytes"] == 4096
    assert ident["frame_samples"] == 2032
    assert ident["build"], "no build identity"
    # The firmware version, which is neither wire contract above. Checked
    # against the header the firmware was built from, so the two cannot
    # drift apart silently - that they *can* is why this field exists.
    assert ident["fw_version"] == baseline["firmware"]["version"], (
        f"board reports fw {ident['fw_version']}, "
        f"drivers/version.h says {baseline['firmware']['version']}")


def test_response_echoes_the_request_id(link):
    """A reply carries the id of the question it answers.

    Without this a late reply to an abandoned request reads as the
    answer to the next one, which is the kind of defect that shows up
    as an impossible measurement rather than as an error.
    """
    for req_id in (1, 0x1234, 0xffff):
        frame = link.request(control.OP_PING, req_id=req_id)
        assert frame.req_id == req_id
        assert frame.flags & control.FLAG_RESPONSE
        assert frame.opcode == control.OP_PING


@pytest.mark.parametrize("case,kwargs,payload,code", [
    ("unknown opcode", {}, b"", control.ERR_OPCODE),
    ("bad version", {"version": 9}, b"", control.ERR_VERSION),
    ("bad checksum", {"crc": 0xdeadbeef}, b"", control.ERR_CRC),
    ("unwanted payload", {}, b"nope", control.ERR_LENGTH),
])
def test_the_device_refuses_in_words(link, case, kwargs, payload, code):
    """Every refusal is a framed answer, never silence.

    Silence is indistinguishable from a wedged device, and this project
    has spent more time on wedged devices than on anything else. The
    text matters too: it is the same wording the console prints, so a
    host can show it to a person without inventing its own.
    """
    opcode = 0x00ff if case == "unknown opcode" else control.OP_PING
    with pytest.raises(control.ControlError) as e:
        link.call(opcode, payload, **kwargs)
    assert e.value.code == code, f"{case}: wrong error code"
    assert e.value.text.strip(), f"{case}: refused with no words"


def test_the_parser_resynchronises_after_rubbish(link):
    """Garbage on the wire costs the next frame, not the channel.

    A parser that could be desynchronised permanently would turn one
    bad write into a board that needs a power cycle, and the deployed
    board's only reset is the cable.
    """
    link.send_raw(b"\xa5" * 700)                 # never a valid magic
    assert link.ping()[2] >= 1, "rubbish alone broke the channel"

    # A header that stops half way is worse: without a way back the
    # parser reads the next frame as the tail of this one, for ever.
    link.send_raw(b"DUEC" + b"\x00" * 4)
    time.sleep(0.35)                             # past the idle timeout
    assert link.ping()[2] >= 2, (
        "a truncated frame retired the channel; the parser's idle "
        "timeout is what is supposed to abandon it")


def test_a_long_payload_is_refused_and_skipped(link):
    """An oversized frame is rejected and its body stepped over.

    Resyncing by hunting for the next magic instead would stop on any
    payload byte that happened to spell DUEC, so the skip is by count
    and this is what says so.
    """
    body = b"DUEC" * 64                    # 256 bytes, all of them magic
    wire = control.encode(control.OP_PING, 5, body)
    # Claim far more payload than the device will buffer.
    wire = wire[:10] + struct.pack("<H", 4096) + wire[12:]
    link.send_raw(wire)
    frame = link.recv(timeout=1.0)
    assert frame is not None, "no refusal for an oversized frame"
    assert frame.is_error and frame.error[0] == control.ERR_LENGTH
    # And the channel still works, which means the body was stepped
    # over rather than parsed as frames. The device is still waiting
    # for the rest of a payload that will never come, so this also
    # rests on the idle timeout.
    time.sleep(0.35)
    assert link.ping()[2] >= 1


def test_stream_stats_says_what_the_console_says(link, board):
    """The opcode must carry the console's measurement, not a new one.

    This is the migration's whole risk: an opcode that quietly reports
    something else than `?` does replaces a slow instrument with a wrong
    one. So the two are read against the same running stream and
    compared field by field.

    Only the fields that cannot move between two reads are asserted.
    `produced`, `consumed` and `gen_endtx` are free-running at 200 kHz
    and advance measurably in the time it takes the console form to
    print twenty-four numbers - which is the reason the opcode exists.
    """
    board.stop()
    board.drain_console(0.3)
    board.cmd("3")
    time.sleep(1.5)
    try:
        st = link.stream_stats()
        board.drain_console(0.2)
        board.cmd("?")
        text = board.drain_console(0.8)
    finally:
        board.stop()

    kv = dict((k, int(v)) for k, v in
              __import__("re").findall(r"([A-Za-z_][A-Za-z0-9_-]*)=(-?\d+)",
                                       text))
    settled = [("frames", "frames"), ("resync", "resync"),
               ("refused", "refused"), ("ring_overflow", "ringovf"),
               ("govre", "govre"), ("rxbuff_overruns", "rxbuff"),
               ("dma_frames", "dma-frames"), ("dma_stalls", "dma-stalls"),
               ("usb_configured", "cfg"), ("usb_line_state", "dtr")]
    for op_key, con_key in settled:
        if con_key in kv:
            assert st[op_key] == kv[con_key], (
                f"{op_key}: control channel says {st[op_key]}, console "
                f"says {con_key}={kv[con_key]}")

    # The moving ones must at least be moving in the right direction.
    for op_key, con_key in (("produced", "prod"), ("consumed", "cons"),
                            ("gen_endtx", "endtx")):
        if con_key in kv:
            assert kv[con_key] >= st[op_key], (
                f"{op_key} went backwards between the control read and "
                f"the console read: {st[op_key]} -> {kv[con_key]}")


def test_bench_leaves_the_division_to_the_host(link):
    """Bytes and microseconds off the device; the rate computed here.

    A throughput is arithmetic over two counters, and a Cortex-M3 that
    is mid-benchmark is the worst place to do it.
    """
    b = link.bench()
    for key in ("mode", "in_bytes", "out_bytes", "elapsed_us", "resets",
                "turn", "dma_in_arms", "dma_out_arms", "loop_passes"):
        assert key in b
    assert b["elapsed_us"] > 0
    assert b["in_mbps"] == b["in_bytes"] / b["elapsed_us"]


def test_measurement_does_not_come_from_the_console_on_this_track(board, track):
    """The rule, enforced rather than remembered.

    Invariant 8 has been in CLAUDE.md the whole time and measure.py still
    read its counters by printing them, twice inside a running loop. A
    rule nothing checks is a rule that decays, so this checks it: where
    the board has a control channel, the suite's measurement helpers must
    have used it.

    Track A is exempt because it has no control channel at all, not
    because the console is acceptable there. That exemption is objective
    1c and it is meant to disappear - when it does, delete the skip and
    this test covers both tracks unchanged.
    """
    if track != "b":
        pytest.skip("Track A has no control channel yet (objective 1c)")
    assert board.ctl() is not None, "Track B board with no control channel"

    counters = measure.play_counters(board)
    assert counters.via == "control", (
        "play_counters() fell back to the console on a board that has a "
        "control channel: measurement is coming from printf again, which "
        "is invariant 8. Check why the control link dropped.")

    occ = measure.occupancy(board)
    assert occ.via == "control", (
        "occupancy() fell back to the console on a board that has a "
        "control channel - see above")
