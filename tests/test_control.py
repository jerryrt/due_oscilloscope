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

# Which tracks implement the optional opcodes.
#
# An opcode a track does not implement answers CTL_ERR_OPCODE rather
# than a body of zeroes - lib/due_shared/src/ctl_port.h says why: zero
# is a measurement, and a host cannot tell "the counter read nothing"
# from "this firmware does not keep that counter" unless the device
# says so.
#
# The table is here rather than a bare try/except so that a refusal is
# only tolerated where it is expected. Track B losing its stream stats
# still fails; Track A refusing them is the documented answer.
IMPLEMENTS = {
    # ctl_stream_stats_t and ctl_bench_t carry Track B's own USB stack
    # counters - usb_devisr, usb_ep0isr, usb_devimr. Track A enumerates
    # through the Arduino core and has no equivalent.
    "stream_stats": {"b"},
    "bench": {"b"},
    # The load monitor is shared - lib/due_shared/src/load.c, compiled by
    # both tracks - so this is no longer a per-track capability. It was
    # one while the monitor lived in bsp/: what the Arduino core does not
    # do is *enable* DWT's cycle counter, and load_init() does, on both.
    # Kept in the table rather than deleted because `available` inside
    # the report is still a runtime answer, and a part without CYCCNT
    # would say so there.
    "load": {"a", "b"},
    # ADC_ACR.TSON and channel 15 - per-track register programming,
    # implemented on both from 2026-08-28 (issue #11).
    "temp": {"a", "b"},
}


def requires(what, track):
    """Skip unless this track implements the opcode."""
    if track not in IMPLEMENTS[what]:
        pytest.skip(
            f"track {track.upper()} answers {what} with CTL_ERR_OPCODE; "
            f"it is a per-track capability, not universal protocol - see "
            f"lib/due_shared/src/ctl_port.h")


@pytest.fixture
def link(board, track):
    """An open conversation with the command port."""
    # The board owns the one control link for the session, the same way
    # it owns the console port and for the same reason. A fixture that
    # opened its own used to work; it stopped the day measure.py started
    # using the channel too, because the port does not open twice.
    c = board.ctl()
    if c is None:
        pytest.fail("the board does not present a command port"
                    + (f" ({board.ctl_why})" if board.ctl_why else ""))
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


def test_identity_reports_this_board(link, board, baseline, track):
    """What a host would refuse a mismatched pairing on.

    Checked against the same baseline the banner is checked against,
    so the control channel and the console cannot disagree about the
    clock without one of them failing.
    """
    ident = link.identity()
    assert ident["track"] == track
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
        f"lib/due_shared/src/fw_version.h says "
        f"{baseline['firmware']['version']}")


def test_the_two_identity_channels_agree(link, board):
    """The console `v` line and CTL_OP_IDENTITY describe one board.

    measure.parse_identity documents its result as "the same shape as
    the control channel's IDENTITY record, so a caller can use either
    interchangeably". Nothing asserted it, and they were not
    interchangeable: bf791f3 bumped FW_VERSION_MINOR and left
    FW_VERSION_STR behind, so the numbers went to this record as 0.2.0
    while the string went to the console as 0.1.0, in every build since.
    Hand-copying version.h between the tracks kept both copies in
    agreement at the wrong value, which is why neither track caught it.

    The version is now derived from the numbers in one shared header, so
    this cannot drift by construction - but "by construction" is what
    was believed about the two copies too. Assert it.
    """
    from_ctl = link.identity()
    from_console = measure.parse_identity(board.ask("v", secs=1.5))
    assert from_console is not None, "no identity line on the console"

    for field in ("track", "fw_version", "ctl_version", "frame_version",
                  "mck_hz", "adc_clock_hz", "frame_bytes", "frame_samples"):
        assert from_console[field] == from_ctl[field], (
            f"the two identity channels disagree about {field}: console "
            f"says {from_console[field]!r}, the control channel says "
            f"{from_ctl[field]!r}. They are documented as interchangeable.")


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


def test_stream_stats_says_what_the_console_says(link, board, track):
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
    requires("stream_stats", track)
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


def test_bench_leaves_the_division_to_the_host(link, track):
    """Bytes and microseconds off the device; the rate computed here.

    A throughput is arithmetic over two counters, and a Cortex-M3 that
    is mid-benchmark is the worst place to do it.
    """
    requires("bench", track)
    b = link.bench()
    for key in ("mode", "in_bytes", "out_bytes", "elapsed_us", "resets",
                "turn", "dma_in_arms", "dma_out_arms", "loop_passes"):
        assert key in b
    assert b["elapsed_us"] > 0
    assert b["in_mbps"] == b["in_bytes"] / b["elapsed_us"]


def test_temperature_is_a_reading_and_says_what_it_was_taken_at(link, track):
    """The sensor answers, and the answer carries its own conditions.

    Deliberately not asserting a temperature. The device reports a raw
    code and the offset is per-part and uncalibrated, so any degrees
    figure here would be this test inventing a calibration - which is
    the failure mode `docs/scope.md` warns about, on a number that would
    then be read as established.

    What can be checked is that it is a *measurement*: TSON was on while
    the conversions happened, the average lies between the extremes it
    reports, and the count is the one the device says it used.
    """
    requires("temp", track)
    t = link.temperature()

    assert t["channel"] == 15, (
        f"the sensor is ADC channel 15 on this part; the device reported "
        f"channel {t['channel']}")
    assert t["samples"] > 0
    assert t["tson"], (
        "ADC_ACR.TSON reads clear in the register the device captured "
        "during the conversions, so whatever was measured, it was not "
        "the temperature sensor")
    assert t["code_min"] <= t["code"] <= t["code_max"], (
        f"the average {t['code']:.2f} is outside the range the device "
        f"reported for the same conversions ({t['code_min']}..{t['code_max']})")
    # A floating input rails or wanders; a bandgap sits still. Loose
    # enough not to be a temperature assertion, tight enough to fail an
    # unconnected channel.
    assert 1 <= t["code"] <= 4094, (
        f"code {t['code']:.2f} is at a rail, which is what an unenabled "
        f"or unconnected channel reads")


def test_temperature_honours_the_sample_count_it_reports(link, track):
    """Averaging more must actually average more, and be bounded.

    The count is a request rather than a promise - the device clamps it,
    because invariant 7 wants a worst case that does not depend on what
    a host sent - so what is checked is that the report says what was
    really done, not that the request was obeyed.
    """
    requires("temp", track)

    one = link.temperature(samples=1)
    assert one["samples"] == 1
    assert one["code_min"] == one["code_max"], (
        "a single conversion cannot have a spread; the device reported "
        f"{one['code_min']}..{one['code_max']}")

    many = link.temperature(samples=64)
    assert many["samples"] == 64

    # Past the ceiling the device clamps rather than obeying or refusing.
    huge = link.temperature(samples=65535)
    assert huge["samples"] <= 4096, (
        f"asked for 65535 conversions and the device says it did "
        f"{huge['samples']}; the clamp is what keeps one main-loop pass "
        f"bounded")


def test_temperature_leaves_the_capture_channels_alone(link, board, track):
    """Reading it must not change what the next stream converts.

    This is the one that would hurt silently. Channel count *divides*
    the aggregate rate and channel skew is real, so a sensor left in the
    sequencer turns every two-channel figure into a three-channel one -
    and the stream would still look perfectly healthy while doing it.
    The device saves ADC_CHSR and restores it; this is what says so from
    the outside.
    """
    requires("temp", track)
    link.temperature()

    res = measure.run_capture(board, preset="3", seconds=1.0)
    assert res.stream.frames, f"no frames after a temperature read: {res.console}"

    mask = res.stream.channel_mask
    got = {i for i in range(16) if mask & (1 << i)}
    assert got == {measure.CH_A0, measure.CH_A1}, (
        f"after a temperature reading the capture's channel mask is "
        f"{mask:#06x} = {sorted(got)}, not the A0+A1 pair asked for. "
        f"Channel 15 is the sensor: if it is in that set it was left in "
        f"the sequencer, which changes the aggregate rate of every run "
        f"after it.")


def test_measurement_does_not_come_from_the_console_on_this_track(board, track):
    """The rule, enforced rather than remembered.

    Invariant 8 has been in CLAUDE.md the whole time and measure.py still
    read its counters by printing them, twice inside a running loop. A
    rule nothing checks is a rule that decays, so this checks it: where
    the board has a control channel, the suite's measurement helpers must
    have used it.

    Track A used to be exempt because it had no control channel at all,
    and the exemption said it was meant to disappear when objective 1c
    landed. It landed on 2026-08-27: Track A reports ctlver=3 and runs
    the same parser. The skip is deleted and this covers both tracks
    unchanged, which is exactly what the old comment promised.
    """
    assert board.ctl() is not None, (
        f"track {track.upper()} reports a control channel but the suite's "
        f"helpers did not use it")

    counters = measure.play_counters(board)
    assert counters.via == "control", (
        "play_counters() fell back to the console on a board that has a "
        "control channel: measurement is coming from printf again, which "
        "is invariant 8. Check why the control link dropped.")

    occ = measure.occupancy(board)
    assert occ.via == "control", (
        "occupancy() fell back to the console on a board that has a "
        "control channel - see above")
