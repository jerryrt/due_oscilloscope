"""`tools/enum_probe.py` flashes: it must parse before it does, and it
must not name a port.

Two defects, both measured on this bench. The tool hardcoded `COM7` as
the programming port, and the native numbers move on every reflash, so
as committed it either aimed the 1200-baud erase at whatever now
answers to that name or failed outright. And it ran at import, so
`--help` was a way to start fifteen flashes - the failure
`tests/test_held_link_guard.py` records for another tool.

Needs no board. Each case runs in its own interpreter with
`measure.flash` stubbed to raise, so "did it reach the flash" is
answerable without one, and the last case is the positive control: a
guard that lets nothing through would satisfy the first two by
refusing everything.
"""
import json
import os
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(REPO, "tools", "enum_probe.py")
SENTINEL = "the-tool-reached-the-flash"
#: What the stubbed flash exits with. Any value the tool itself
#: never uses; it returns 0 or 1.
REACHED_CODE = 77

DRIVER = """
import json, os, runpy, sys
sys.path.insert(0, os.path.join({repo!r}, "host"))
import measure
seen = {{}}
def _flash(track=None, control=None, **kw):
    seen["track"] = track
    seen["control"] = control
    # SystemExit, not an ordinary exception: the tool catches Exception
    # around the flash on purpose - a failed flash is a row in its
    # report - so anything it can catch would not answer "did it get
    # here".
    raise SystemExit({reached_code!r})
measure.flash = _flash
code, reached = 0, False
try:
    runpy.run_path({tool!r}, run_name="__main__")
except SystemExit as e:
    code = e.code if isinstance(e.code, int) else 1
    reached = code == {reached_code!r}
except BaseException as e:
    code, reached = 99, {sentinel!r} in str(e)
print("@@" + json.dumps({{"code": code, "reached": reached, "seen": seen}}))
"""


def _run(argv=()):
    src = DRIVER.format(repo=REPO, tool=TOOL, sentinel=SENTINEL,
                        reached_code=REACHED_CODE)
    out = subprocess.run([sys.executable, "-c", src, *argv],
                         capture_output=True, text=True, cwd=REPO)
    for line in out.stdout.splitlines():
        if line.startswith("@@"):
            return json.loads(line[2:])
    raise AssertionError(
        f"driver produced no verdict:\n{out.stdout}\n{out.stderr}")


@pytest.mark.parametrize("argv,code", [(["--help"], 0), (["--runs=x"], 2)])
def test_arguments_are_read_before_the_board_is_touched(argv, code):
    got = _run(argv)
    assert got["code"] == code, got
    assert not got["reached"], (
        f"{argv} reached measure.flash; --help must not be a way to start "
        f"a run of flashes")


def test_no_port_is_named_unless_one_is_asked_for():
    """The hardcoded `COM7` is the defect. With no `--port`, the tool
    passes None and `measure.flash()` discovers by USB VID/PID."""
    got = _run(["--runs", "1"])
    assert got["reached"], got
    assert got["seen"]["control"] is None, (
        f"the tool named a port nobody asked for: {got['seen']!r}")
    assert got["seen"]["track"] == "a", got


def test_a_port_given_on_the_command_line_is_used():
    """The positive control for the argument, and for the parse: a tool
    that ignored its arguments would pass None here too."""
    got = _run(["--runs", "1", "--port", "COM42"])
    assert got["reached"], got
    assert got["seen"]["control"] == "COM42", got
