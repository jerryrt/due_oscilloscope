"""Tests that restart the board on purpose run after every other test.

The board is shared by the whole session. A deliberate fault detaches USB
and re-enumerates it, so any test that ran after one would be aimed at a
node that no longer exists - which is what happened the first time a
fault test sat in the middle of the board tier: a run of errors in
unrelated files. `conftest.py` sorts anything marked `disruptive` to the
end of its track.

This collects the suite (no board needed) and holds that ordering.
"""
import os
import subprocess
import sys

import pytest

pytestmark = pytest.mark.smoke

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _collect(track):
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q",
         f"--track={track}", "-p", "no:cacheprovider"],
        cwd=ROOT, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return [l.split("::")[0] for l in proc.stdout.splitlines() if "::" in l]


@pytest.mark.parametrize("which", ["a", "b"])
def test_the_disruptive_tests_come_last_within_a_track(which):
    files = _collect(which)
    assert files, "collected nothing: this test would pass on an empty suite"
    hits = [i for i, f in enumerate(files)
            if f.endswith("test_crash_record_board.py")]
    assert hits, "the disruptive tests were not collected at all"
    first = hits[0]
    assert hits == list(range(first, len(files))), (
        f"track {which}: tests after the first disruptive one are not all "
        f"disruptive; the board is restarted under them")
