"""The SOF frequency reference, checked as a behaviour rather than a call.

Issue #56. Track A reported MCK as 75,599,350 Hz - `-30,777 ppm` - while
Track B on the same board the same afternoon read `-9.8`, and every
counter said the span was clean: `ambiguous` 0, `restarts` 0,
`available` true. Nothing downstream could tell that figure from a good
one, which is the same failure a body of zeroes would be and the reason
the per-track rule forbids one.

The cause was a missing epoch reset. `frames` counts from the moment the
span starts and `dev_us` accumulates over the same period, so the two
must track; a span carried across a USB discontinuity gains frames that
no elapsed time paid for. The error was quantised in whole 2048-frame
FNUM wraps - one at cold boot and two per native-port bounce - and it is
CUMULATIVE, so it decays as 1/t and never reaches usability rather than
washing out.

WHY THIS IS NOT A PARITY TEST ON A SYMBOL NAME. `tests/test_track_parity.py`
asserts that every track calls the shared init. Track B and Track C call
`clockref_init()` from `drivers/`; **Track A must not**, because invariant
3 keeps register programming independent - "two independent programmings
of the same silicon is what makes a behavioural divergence point at one
of them". Track A's peer is `ctl_port_sof_poll()` in
`sketches/bringup/ctl_port.cpp`, reading the same register with its own
code, and a grep for `clockref` in `sketches/` correctly finds nothing.

That is exactly how the defect stayed invisible: the symbol was absent
because it is required to be absent, and the behaviour was wrong for an
unrelated reason. So this file asserts the behaviour, which every track
owes regardless of what it names the thing that provides it.

The oracle is what found it - Track B held to one frame in 139,538
across three port bounces while Track A gained a wrap each time - and
these bounds are set well outside both so the test fails on the defect
and not on the clock.
"""
import pytest

pytestmark = pytest.mark.smoke

#: A wrap is 2048 frames. The bound has to sit far below that and far
#: above the real clock offset, and those are three orders of magnitude
#: apart, so the choice is not delicate.
WRAP_FRAMES = 2048
FLOOR_FRAMES = 100.0

#: The clock offset itself shows up in this quantity - the board's
#: crystal against the host's SOF - and it is real signal, not error.
#: Measured across three benches it is single-digit to low-double-digit
#: ppm: -7.6 to -8.1 here, +12.5 on windows-desk against its own host.
#: 100 ppm is an order of magnitude of headroom on the largest of those.
#:
#: The span term is what keeps a long soak from failing on honest drift.
#: It also sets this test's reach: a single wrap stops clearing the bound
#: once the span passes ~20M frames, about five and a half hours, and a
#: session that long should be reading `restarts` directly anyway.
OFFSET_PPM = 100e-6


def _sof(board):
    ctl = board.ctl()
    if ctl is None:
        pytest.skip("no control channel on this build - nothing to ask")
    sof = ctl.heartbeat()["sof"]
    if not sof["available"]:
        pytest.skip(
            "no SOF reference yet: the host emits frames from the moment "
            "it configures the device, so this means the span has not "
            "started rather than that the reference is broken")
    return sof


def test_the_sof_span_is_not_carried_across_a_discontinuity(board):
    """`frames` and `dev_us` measure one span, so they must track.

    A frame is 1 ms exactly, by definition of SOF, so `frames` and
    `dev_us / 1000` are the same quantity counted two ways and their
    difference is the board's clock offset and nothing else. A span
    stitched across a USB outage gains frames that no elapsed time paid
    for, and this is where that shows up.

    Stated in FRAMES rather than ppm on purpose. The defect is quantised
    in whole 2048-frame wraps and does not scale with the span, so an
    absolute bound catches it on a span of any length - including the
    few seconds of one that exists right after the suite flashes the
    board, which is when the cold-boot wrap would be the only one there.
    """
    sof = _sof(board)
    frames, dev_us = sof["frames"], sof["dev_us"]
    deficit = frames - dev_us / 1000.0
    bound = max(FLOOR_FRAMES, frames * OFFSET_PPM)

    assert abs(deficit) < bound, (
        f"the SOF span does not add up: {frames} frames against "
        f"{dev_us} us of device time is a deficit of {deficit:.1f} frames "
        f"({deficit / WRAP_FRAMES:.3f} FNUM wraps), bound {bound:.1f}.\n"
        f"ambiguous={sof['ambiguous']} restarts={sof['restarts']} - and if "
        f"those are 0 the device believes this span is clean, which is the "
        f"half of issue #56 that made the wrong number silent.\n"
        f"A deficit near a whole multiple of {WRAP_FRAMES} is a span "
        f"carried across a USB discontinuity: the epoch was not reset when "
        f"the host stopped emitting SOF.")


def test_the_reported_mck_is_a_frequency_or_a_refusal(board):
    """Zero is "not yet". A number has to be a plausible MCK.

    `ctl_fill_sof()` already refuses to publish a figure from a span too
    short to mean anything, and that refusal is the right shape - the
    device says nothing rather than saying something wrong. What it did
    not refuse was a figure from a span whose ORIGIN was wrong, which
    read 3% low and looked like a measurement.

    1000 ppm is deliberately loose. A real MCK error of that size would
    be a broken crystal and is not what this guards; it is here to catch
    a figure computed from a poisoned span, which was out by 30,777.
    """
    sof = _sof(board)
    hz = sof["mck_meas_hz"]
    if not hz:
        pytest.skip(
            "no figure published yet - the device suppresses one below a "
            "minute of span, which is a refusal and not a failure")

    ppm = (hz - 78_000_000) / 78.0
    assert abs(ppm) < 1000, (
        f"mck_meas_hz = {hz} is {ppm:+.1f} ppm from the nominal 78 MHz.\n"
        f"MCK is derived from the crystal by the PLL and does not move by "
        f"this much; a figure this far out is the span it was computed "
        f"from, not the clock. See issue #56, where a carried epoch read "
        f"-30,777 ppm and decayed as 1/t.\n"
        f"frames={sof['frames']} dev_us={sof['dev_us']} "
        f"ambiguous={sof['ambiguous']} restarts={sof['restarts']}")
