"""A recorded figure must say which instrument produced it.

Issue #51. `play_counters()` and `occupancy()` read over the control
channel where there is one and fall back to `B` and `O` on the console,
and they say which they used in `.via`. The two are not two tolerances
of one instrument: control reads a counter in 146 us, the console
fallback costs 13.14 ms and 15.40 ms of blocked main loop **taken while
the sample path is running**, which is invariant 8. They are two
experiments.

A dropped link used to stick for a whole session, so a session could
hold two populations of measurements with nothing marking the boundary.
That bug is fixed. What was not fixed, and is what made #51
unanswerable after the fact, is that **no record this project wrote
carried `via`** - so no stored figure said which instrument produced
it, and the question "did your numbers move when your link dropped?"
had no way to be asked of the data.

This project already requires a figure to carry its bench, and #5
established it must carry its firmware commit. This is the same rule a
third time.

**The rule is derived here, not listed.** A list of tools goes stale
the moment someone adds the eleventh, silently, which is exactly how
`track="b"` ended up hardcoded in nine of them (#53). So the check is:
*if a tool reads playback counters and writes a record, it must record
the instrument.* A new tool that does both is caught the day it lands.
"""

import os
import re

import pytest

pytestmark = pytest.mark.smoke

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
TOOLS = os.path.join(REPO, "tools")

#: Reading the playback counters. `run_play` hands back a result whose
#: `.play` is the PlayCounters that `play_counters()` built, so any
#: attribute access through it is a counter read.
READS_COUNTERS = re.compile(r"\.play\.")

#: Writing a record. Every record-writing tool here serialises rows with
#: json.dumps; `run_fields` is the provenance they all carry.
WRITES_RECORD = re.compile(r"json\.dumps\(|run_fields\(")

#: Recording the instrument.
RECORDS_VIA = re.compile(r"\bvia\b")


def _tools():
    for name in sorted(os.listdir(TOOLS)):
        if not name.endswith(".py"):
            continue
        path = os.path.join(TOOLS, name)
        with open(path, encoding="utf-8") as fh:
            yield name, fh.read()


def _obliged():
    """Tools that read playback counters *and* write a record."""
    return [(n, s) for n, s in _tools()
            if READS_COUNTERS.search(s) and WRITES_RECORD.search(s)]


def test_the_rule_has_something_to_check():
    """Guard against the derivation quietly matching nothing.

    A rule that selects an empty set passes for ever and protects
    nothing, which is a worse failure than the one it is written to
    catch because it looks like a green test.
    """
    obliged = _obliged()
    assert len(obliged) >= 5, (
        "the regexes no longer select the record-writing tools - "
        f"matched {[n for n, _ in obliged]}. Fix the derivation, do not "
        "delete the test")


def test_every_tool_recording_counters_records_its_instrument():
    """A row of counters without its instrument is unattributable.

    Not merely under-documented: a reader has no reason to distrust it,
    and a figure taken with printf blocking the main loop it is
    measuring reads exactly like one taken over the control channel.
    """
    missing = [n for n, s in _obliged() if not RECORDS_VIA.search(s)]
    assert not missing, (
        "these tools read playback counters and write records without "
        f"recording which instrument read them: {missing}. Add "
        "`via=r.play.via` to the row - `PlayCounters.via` is declared "
        "and defaults to None, so it is always safe to read")


def test_via_is_declared_not_attached():
    """`via` must exist on every PlayCounters, not only on some.

    It used to be attached by `play_counters()` alone, so an object a
    parser built directly had no such attribute and a caller recording
    it needed a getattr guard. A field that exists only on the objects
    that happened to pass through one constructor cannot be recorded
    reliably, and `None` has to remain distinguishable from "console" -
    it means no instrument was recorded, which is not the same claim.
    """
    import sys
    sys.path.insert(0, os.path.join(REPO, "host"))
    import measure

    assert measure.PlayCounters().via is None
    assert measure.OccHist().via is None
