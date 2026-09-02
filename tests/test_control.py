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

import re
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

# Which opcodes this build implements: the device answers, the test
# asks. Issue #7.
#
# This replaces a hand-written IMPLEMENTS table mapping names to sets of
# tracks. The table could not express the truth: the capability list is
# a property of the *build*, not the track - two Track B images
# legitimately answer differently when PLAY_RATE_TRACE_ENABLED is
# compiled out - and it was already wrong once, listing four optional
# opcodes where the dispatch refuses seven. The device's own list is
# held to the dispatch's actual behaviour by
# test_the_capability_list_matches_what_the_device_actually_does below.
#
# What the table did that this does not: fail, rather than skip, a track
# that unexpectedly refused an opcode it was supposed to have. A build
# that genuinely drops an opcode now skips its tests, and the skip
# message names the opcode so the loss is visible in the summary rather
# than silent. The cross-check test is what still fails when the list
# and the dispatch disagree.

# Human names for the optional opcodes, used in skip and failure
# messages. The list itself always comes from the device.
CAPABILITY_PROBES = {
    control.OP_STREAM_STATS: "stream stats",
    control.OP_BENCH: "bench counters",
    control.OP_OCCUPANCY: "occupancy histogram",
    control.OP_RATE_TRACE: "rate trace",
    control.OP_LOAD: "load monitor",
    control.OP_TEMP: "temperature sensor",
    control.OP_GEN: "generator",
}


def requires(link, op):
    """Skip unless this build dispatches the opcode - the device's own
    capability list is the authority, not a table in this file."""
    if op not in link.capabilities():
        what = CAPABILITY_PROBES.get(op, f"0x{op:04x}")
        pytest.skip(
            f"this build does not dispatch {what} (0x{op:04x}) - its own "
            f"capability list says so (CTL_OP_CAPABILITY, issue #7)")


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

    **The opcode read is bracketed by two console reads, and nothing is
    classified as settled.** The earlier form split the fields into ones
    that "cannot move between two reads" and three free-running ones,
    and that split was wrong: with no consumer on the native port the
    ring overflows continuously, so `ringovf` free-runs too - measured
    at 197/s on linux-x1, where the failing delta was exactly the
    inter-read sleep times that rate. It passed elsewhere only because
    the counter happened to be still on those hosts, which is luck and
    not a property the test may rest on.

    Bracketing removes the need to classify, and it is *stronger* than
    what it replaces. A stationary field still pins the opcode exactly,
    because both console reads return the same number. A moving field is
    pinned to the interval it moved through, which catches an opcode
    reporting a different quantity - where the old "did not go
    backwards" check on `produced` and friends caught only an opcode
    reporting a smaller one.
    """
    requires(link, control.OP_STREAM_STATS)
    board.stop()
    board.drain_console(0.3)
    board.cmd("3")
    time.sleep(1.5)
    try:
        board.cmd("?")
        before = board.drain_console(0.8)
        st = link.stream_stats()
        board.cmd("?")
        after = board.drain_console(0.8)
    finally:
        board.stop()

    def console_kv(text):
        return dict((k, int(v)) for k, v in
                    re.findall(r"([A-Za-z_][A-Za-z0-9_-]*)=(-?\d+)", text))

    kv0, kv1 = console_kv(before), console_kv(after)
    fields = [("frames", "frames"), ("resync", "resync"),
              ("refused", "refused"), ("ring_overflow", "ringovf"),
              ("govre", "govre"), ("rxbuff_overruns", "rxbuff"),
              ("dma_frames", "dma-frames"), ("dma_stalls", "dma-stalls"),
              ("usb_configured", "cfg"), ("usb_line_state", "dtr"),
              ("produced", "prod"), ("consumed", "cons"),
              ("gen_endtx", "endtx")]
    for op_key, con_key in fields:
        if con_key not in kv0 or con_key not in kv1:
            continue
        lo, hi = sorted((kv0[con_key], kv1[con_key]))
        assert lo <= st[op_key] <= hi, (
            f"{op_key}: the control channel says {st[op_key]}, which is "
            f"outside the interval the console bracketed it with - "
            f"{con_key} went {kv0[con_key]} -> {kv1[con_key]} around the "
            f"opcode read. The two are not reporting the same quantity.")


def test_bench_leaves_the_division_to_the_host(link, track):
    """Bytes and microseconds off the device; the rate computed here.

    A throughput is arithmetic over two counters, and a Cortex-M3 that
    is mid-benchmark is the worst place to do it.
    """
    requires(link, control.OP_BENCH)
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
    requires(link, control.OP_TEMP)
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
    requires(link, control.OP_TEMP)

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
    requires(link, control.OP_TEMP)
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
    landed. It landed on 2026-08-27: Track A reports ctlver=4 and runs
    the same parser. The skip is deleted and this covers both tracks
    unchanged, which is exactly what the old comment promised.
    """
    assert board.ctl() is not None, (
        f"track {track.upper()} reports a control channel but the suite's "
        f"helpers did not use it")

    # These raise rather than falling back (#51 q3), so reaching the
    # assertion at all means the control channel answered. `via` is
    # checked anyway because it is what a *record* carries, and a
    # record mislabelled "control" is the failure this cannot see.
    counters = measure.play_counters(board)
    assert counters.via == "control", (
        f"play_counters() returned via={counters.via!r} on a board with a "
        f"control channel. It no longer has a console path, so this is a "
        f"mislabelled record rather than a fallback.")

    occ = measure.occupancy(board)
    assert occ.via == "control", (
        f"occupancy() returned via={occ.via!r} - see above")


# The capability list is only worth having if it is true, and "true" is
# checkable: ask the device what it implements, then ask it each opcode
# and see whether the answers agree. Issue #7.
#
# The list is built on the device from the same word the dispatch refuses
# on, so this cannot fail by drift between two firmware tables - it can
# only fail if that word disagrees with what the handler actually does,
# which is the one thing no amount of care inside the firmware prevents.


def test_the_capability_list_matches_what_the_device_actually_does(link, track):
    """Every opcode claimed answers; every one not claimed refuses.

    This is the whole value of CTL_OP_CAPABILITY. A host greys out a
    feature on the strength of this list, so a list that over-claims
    produces a feature that fails when used, and one that under-claims
    hides a feature that works. Both are worse than the CTL_ERR_OPCODE
    discovery it replaces, because that at least could not lie.

    Note what this does *not* assert: that a claimed opcode returns
    useful data. `load` reports its own `available` and `rate_trace`
    can be compiled out - "does this build dispatch it" and "is it
    working right now" are different questions and both stay
    answerable.
    """
    claimed = link.capabilities()

    assert control.OP_PING in claimed and control.OP_IDENTITY in claimed, (
        f"track {track.upper()} does not claim PING or IDENTITY, which "
        f"every build must answer - a device that could not answer them "
        f"could not have been asked this question")
    assert control.OP_CAPABILITY in claimed, (
        "the capability reply does not list itself, so a host cannot "
        "tell 'this build has no capability opcode' from 'it has one "
        "and forgot to mention it'")

    wrong = []
    for op, what in sorted(CAPABILITY_PROBES.items()):
        try:
            link.call(op)
            answered = True
        except control.ControlError as e:
            if e.code != control.ERR_OPCODE:
                # Refused for some other reason - busy, bad length -
                # which means it *is* implemented. ERR_OPCODE is the
                # only code that means "not here".
                answered = True
            else:
                answered = False
        if answered != (op in claimed):
            wrong.append(
                f"{what} (0x{op:04x}): claimed={op in claimed} "
                f"actual={'answers' if answered else 'CTL_ERR_OPCODE'}")

    assert not wrong, (
        f"track {track.upper()}'s capability list disagrees with its own "
        f"dispatch on {len(wrong)} opcode(s): {'; '.join(wrong)}. The list "
        f"is built from the word the dispatch refuses on, so this means "
        f"ctl_port_capabilities() and the handler disagree.")


def test_the_heartbeat_is_the_device_talking_first(link, track):
    """The one frame the device sends without being asked.

    Every other opcode here is host-initiated, which is a blind spot
    rather than a design: what is worth knowing about a board is exactly
    what it cannot answer questions during. Issue #33 stopped Track A's
    main loop and the console, the control channel and GET_LOAD went
    dark together, because all three are answered *by* that loop.

    So this asserts the properties that make a beat useful rather than
    the fact that one arrived. It is periodic to the cadence the device
    agreed to; `seq` increments by one, which is what turns a lost beat
    into a visible gap rather than a slightly stale number; and it
    carries a loop-pass counter that moves, which is the liveness signal
    itself.
    """
    requires(link, control.OP_HEARTBEAT)

    assert link.heartbeat(0)["period_ms"] == 0, "the beat must start off"

    period = 100
    got = link.heartbeat(period)
    assert got["period_ms"] == period, (
        f"asked for {period} ms and the device reports "
        f"{got['period_ms']}; the reply is meant to say what it took")
    try:
        beats = link.beats(1.5)

        assert len(beats) >= 8, (
            f"{len(beats)} beats in 1.5 s at a {period} ms cadence; the "
            f"device stopped talking or the notification form is not "
            f"reaching the host")

        gaps = {b["seq"] - a["seq"] for a, b in zip(beats, beats[1:])}
        assert gaps == {1}, (
            f"sequence gaps {sorted(gaps)}: a beat is only a liveness "
            f"signal if a missing one is visible, which is what seq is for")

        spans = [b["uptime_ms"] - a["uptime_ms"]
                 for a, b in zip(beats, beats[1:])]
        assert all(abs(s - period) <= period // 2 for s in spans), (
            f"intervals {spans} ms against a {period} ms cadence: the "
            f"device is not keeping its own schedule")

        passes = [b["counters"]["loop_passes"] for b in beats]
        assert passes[-1] > passes[0], (
            "loop_passes did not move across the run, so the beat is "
            "arriving but reports nothing about whether the loop is "
            "running - which is the whole point of carrying it")
    finally:
        link.heartbeat(0)

    assert link.beats(0.6) == [], (
        "beats kept arriving after the cadence was set to 0; a device "
        "that cannot be told to stop pushing is one a host cannot own")


def test_the_heartbeat_outlives_a_stalled_main_loop(link, board, track):
    """The beat keeps arriving while the loop that answers everything is dead.

    This is the property the feature exists for, and until the beat moved
    into a timer interrupt it was not true. Issue #33 stalled a main loop
    and the console, the control channel and GET_LOAD went dark together,
    because all three are answered *by* that loop - so the board looked
    exactly like one that had been unplugged, and the only recovery
    anyone reached for also reset it and erased the evidence.

    The trigger is the console's own `=<ms>S`, which is deterministic,
    capped at 2000 ms by both tracks and recovers by itself. The earlier
    way to produce a stall was to feed bulk OUT until the firmware hung,
    which needed megabytes, a specific host buffering behaviour and a
    reset afterwards - far too heavy to assert on.

    What is checked is not that beats arrive, but that they arrive
    *carrying the stall*: `seq` advances, so the timer is running, while
    `loop_passes` does not, so the loop is not. A beat that only proved
    the first would be a liveness signal for the interrupt controller.
    """
    requires(link, control.OP_HEARTBEAT)

    link.heartbeat(50)
    try:
        board.poll_console()
        board.cmd("=2000S")
        beats = link.beats(2.0)

        assert len(beats) >= 15, (
            f"{len(beats)} beats during a 2000 ms stall at a 50 ms "
            f"cadence; the beat is not surviving the stall, which is the "
            f"whole reason it is driven from a timer")

        gaps = {b["seq"] - a["seq"] for a, b in zip(beats, beats[1:])}
        assert gaps == {1}, (
            f"sequence gaps {sorted(gaps)} while stalled: beats are being "
            f"dropped, so the endpoint or the emitter is not independent "
            f"of the loop after all")

        passes = [b["counters"]["loop_passes"] for b in beats]
        assert len(set(passes)) <= 2, (
            f"loop_passes took {len(set(passes))} distinct values during "
            f"the stall ({sorted(set(passes))[:4]}...); the loop was still "
            f"running, so this run proves nothing about surviving a stall")

        uptimes = [b["uptime_ms"] for b in beats]
        assert uptimes[-1] > uptimes[0], (
            "uptime_ms did not advance across the stall, so the beats "
            "are stale copies rather than a timer still firing")
    finally:
        link.heartbeat(0)
