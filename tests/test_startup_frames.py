"""Frames lost between the capture ring starting and the first transfer.

Issue #41. Above 200 kHz every capture loses a fixed handful of frames
before the first one reaches the host, nine runs of nine on three
benches. The cause is `cmd_stream` printing its banner *after*
`stream_start`: invariant 8 costs 13-20 ms of blocked main loop, the
ring holds `STREAM_NBUF` frames, and everything past that runway is
gone. Moving the two prints ahead of the start takes it to zero at
every rate - see docs/debugging.md.

**The suite had no test for this and the defect is as old as the
presets.** It surfaced because `tools/gallery.py` refused to caption a
screenshot "clean" over a non-zero counter; the number had been on
screen for as long as anyone had been looking at that pane and read as
ordinary noise. That is what this file is for: the count is now pinned,
so it cannot drift without somebody being told.

The shape follows OVERSUPPLIED and RESIDUAL in test_integrity.py - xfail
a known, characterised defect rather than deleting the assertion - with
one addition those did not start with and issue #5 had to learn: **a
bound**. #5's guard asserted a z-score and never looked at the
amplitude, so the displacement doubled from 1-8 codes to 14+ with the
suite green. An unbounded xfail is a defect with permission to grow.

So: zero is a pass, a count within the measured envelope is an xfail
naming the issue, and anything past the envelope is a failure.
"""

import pytest

import measure

pytestmark = pytest.mark.scope

# The runway is STREAM_NBUF frames, so the loss cannot exceed it by much
# without meaning something else entirely - the ring emptying twice, or
# the loop stopping rather than stalling. Measured 3 on Track B/Windows
# and 3-4 on Track A/macOS at the two rates above the threshold; 8 is
# double the ring and comfortably past anything the banner can cost.
STARTUP_FRAMES_ENVELOPE = 8

# Presets whose rate is past the point where the banner outlasts the
# ring's runway. 3 (200 kHz) is below it and must stay clean.
AFFECTED = {"4", "5"}


@pytest.mark.parametrize("preset", ["3", "4", "5"])
def test_capture_does_not_lose_frames_before_the_first_one(board, preset):
    """The overrun counter in the first frame that reaches the host.

    `first_overrun` is the right statistic and `max_overrun` is not:
    this defect is entirely spent before the first transfer, so first
    equals max, and a loss that appears later is a different issue
    (#44) with a different mechanism.
    """
    res = measure.run_capture(board, preset=preset, seconds=6.0)
    ps = res.stream
    assert ps.frames > 100, f"preset {preset} produced only {ps.frames} frames"

    first = ps.first_overrun or 0
    if first and preset in AFFECTED:
        assert first <= STARTUP_FRAMES_ENVELOPE, (
            f"preset {preset} lost {first} frames before the first "
            f"transfer, past the {STARTUP_FRAMES_ENVELOPE}-frame envelope "
            f"issue #41 was characterised within. That is more than the "
            f"banner can cost against this ring, so it is not #41 as "
            f"measured - see docs/debugging.md for the arithmetic.")
        pytest.xfail(
            f"issue #41: preset {preset} loses {first} frames while "
            f"cmd_stream prints its banner after stream_start. Zero here "
            f"means the reorder landed.")

    assert first == 0, (
        f"preset {preset} lost {first} frames before the first transfer. "
        f"Below the #41 threshold this should be clean; see "
        f"docs/debugging.md.")
