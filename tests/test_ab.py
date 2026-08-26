"""
The A/B harness's refusal. No board required.

tools/ab.py exists because four findings in one day were negative
results with no control that ever reproduced. Its whole value is the
one branch that declines to report, so that branch is tested rather
than trusted - an enforcement nobody exercises is a comment.
"""

import subprocess
import sys
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AB = os.path.join(REPO, "tools", "ab.py")


def _run(args):
    return subprocess.run([sys.executable, AB] + args,
                          capture_output=True, text=True, cwd=REPO)


def test_a_failing_flash_command_stops_the_run():
    """A condition that will not flash must not be measured as clean."""
    r = _run(["--control", "exit 3", "--arm", "exit 0", "--rounds", "1"])
    assert r.returncode != 0
    assert "flash command failed" in (r.stdout + r.stderr)


def test_the_arms_are_named_in_the_usage():
    """--arm is repeatable, because one control and one treatment is the
    degenerate case and not the intended one."""
    r = _run(["--help"])
    assert r.returncode == 0
    assert "--arm" in r.stdout and "repeatable" in r.stdout


def test_it_requires_a_control():
    """There is no mode that compares treatments to each other with no
    untreated arm - that is the shape of the mistake it exists to stop."""
    r = _run(["--arm", "true", "--rounds", "1"])
    assert r.returncode != 0
    assert "--control" in (r.stdout + r.stderr)
