"""Every track's main() is the one file it does not share - so compare them.

Issue #45. `tools/track_parity.py` exists because four defects landed on
Track C in one day, all of the same shape: something present in Track B's
`main()` and absent, or differently bound, in Track C's. Nothing failed
when they did. Not the build, not the link, and not a board test - a
command a track does not bind is usually only reachable from a test that
already skips on that track, and the watchdog one presented as a flaky
control link rather than as a missing line.

The tool was written as a tool deliberately, and `linux-x1` left the
placement here to this bench while #50 and #54 were in flight over
`tests/`. This is that placement: the guard holds because a run fails,
not because somebody remembers to invoke it.

Verified against history before being trusted (windows-desk, 2026-08-31):
run against the parent of each fixing commit, the tool reports all four
of the original defects, and each report clears at the fix -

    3aadf90~1   WDT->WDT_MR = WDT_MR_WDDIS absent from Track C
    1eec02b~1   clockref_init/clockref_poll absent from Track C
    9829719~1   COLLISION 'T': h_sink_dma on B, c_time on C
    96b3c23~1   COLLISION 'k': h_dac_30m on B, c_time on C

Board-free and textual: no compiler, no build, no board.
"""

import os
import sys

import pytest

pytestmark = pytest.mark.smoke

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

sys.path.insert(0, os.path.join(REPO, "tools"))
import track_parity  # noqa: E402


def test_track_a_and_b_consoles_agree():
    """The two complete tracks bind the same letters to the same behaviour.

    The failure this catches is not a missing command - it is a letter
    that both tracks answer, neither errors on, and which does something
    different on each. A reviewer reading one file cannot see it.

    Scoped to the console table. `check()` also compares the init
    sequence, and A-vs-B init legitimately differs: Track A is an Arduino
    sketch, so `pinMode()`/`analogReadResolution()` stand where Track B
    writes registers, and it decomposes the same work under other names
    (`acq_init`/`gen_init` against `adc_init`/`dac_init`). Asserting on
    that whole list would fail permanently for reasons that are not
    defects. The init sequence is checked below, against the rule that
    actually holds.
    """
    lt = track_parity.table(track_parity.MAINS["A"])
    rt = track_parity.table(track_parity.MAINS["B"])
    bad = []
    for letter in sorted(set(lt) & set(rt)):
        if track_parity._norm(lt[letter]) != track_parity._norm(rt[letter]):
            bad.append("COLLISION: %r is %s on A and %s on B"
                       % (letter, lt[letter], rt[letter]))
    for letter in sorted(set(lt) ^ set(rt)):
        who = "A" if letter in lt else "B"
        bad.append("only track %s binds %r" % (who, letter))
    assert not bad, (
        "Track A and Track B console tables have diverged:"
        + "".join("\n  " + b for b in bad)
        + "\n\nRun  python tools/track_parity.py  for the full comparison."
    )


# Drivers that are not a track's own business: shared code every track is
# required to run, where an absence is a defect and not a decomposition.
# `clockref` is the whole of the list because it is the whole of what has
# been ruled so far - #52 requires the board to report its own clock, and
# the instruction was "all tracks". Add to it when another shared driver
# earns the same ruling; do not add track-local init here.
SHARED_INIT = ["clockref_init()"]


@pytest.mark.xfail(strict=True, reason=(
    "Track A does not run clockref at all - see issue #56. Only Track B "
    "and Track C call clockref_init()/clockref_poll(); in sketches/ the "
    "name appears in three comments and no code. strict=True so this "
    "starts failing the day Track A is fixed and the marker is not "
    "removed with it."))
def test_every_track_runs_the_shared_init():
    """Shared drivers reach every track, or the suite says which one they missed.

    This is the exact defect class that produced four Track C failures in
    a day - `clockref` among them - and it was invisible because nothing
    fails when an init call does not propagate. Not the build, not the
    link, not a board test.
    """
    missing = {}
    for track in sorted(track_parity.MAINS):
        seq = track_parity.init_sequence(track_parity.MAINS[track])
        gaps = [c for c in SHARED_INIT if c not in (seq or [])]
        if gaps:
            missing[track] = gaps
    assert not missing, "shared init absent: " + "; ".join(
        "track %s does not call %s" % (t, " ".join(g))
        for t, g in sorted(missing.items()))


def test_the_comparison_still_parses_every_main():
    """A parser that silently reads nothing would pass every check above.

    `check()` returns "could not parse" as an ordinary divergence string,
    so a renamed file or a restructured main() would otherwise surface as
    a confusing assertion rather than as itself.
    """
    for track, path in sorted(track_parity.MAINS.items()):
        assert os.path.exists(path), f"track {track}: no main() at {path}"
        assert track_parity.table(path), f"track {track}: no console table parsed"
        assert track_parity.init_sequence(path) is not None, (
            f"track {track}: no init sequence parsed from {path}")


def test_report_track_c_gap_without_failing_on_it(record_property):
    """Track C's gap is recorded on every run, and does not fail it.

    Track C is a track under construction with a known, tracked porting
    gap, so failing the suite on it would fail every run for a reason
    already on an issue and teach people to ignore this file. Attached to
    the run rather than printed, so the number travels with the result
    instead of scrolling past. When Track C is complete this becomes an
    assertion; until then a silent zero here would be the real bug, so
    the parse is checked above.
    """
    bad = track_parity.check("B", "C")
    record_property("track_c_divergences", len(bad))
    for line in bad:
        print("track C gap:", line)
