"""`tools/issue79_held_link.py` must refuse before it opens the board.

The tool used to take its bench from `DUE_BENCH` with `"linux-x1"` as
the default, ignore its arguments, and open the record with `"w"`. On
`windows-desk`, `issue79_held_link.py --help` ran the whole experiment
and then replaced `linux-x1`'s committed rows with `windows-desk`'s
under `linux-x1`'s name. `5ee8442` put three refusals in front of it.

**The one that matters most had never been exercised**, because the
bench that wrote the guard has a `bench.json` and could not reach the
no-bench branch. A refusal that fires *after* the board is opened still
runs the experiment on someone's board, so each case here asserts both
the exit and that `measure` was never imported.

Needs no board, on purpose. The last test is the positive control - with
a bench and no existing record the tool must reach `measure.Board`, or
the three refusals above are an unconditional refusal that passes by
refusing. It gets there against a stubbed `Board` that raises instead of
opening a port, so the control runs identically on a bench with no
hardware and writes nothing.

Each case runs in its own interpreter, because `measure` is imported by
other tests in this process and "was it imported" is only a question a
fresh one can answer.
"""
import json
import os
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(REPO, "tools", "issue79_held_link.py")
SENTINEL = "the-tool-reached-the-board"

DRIVER = """
import json, os, runpy, sys
sys.path.insert(0, os.path.join({repo!r}, "host"))
import provenance
provenance.bench = lambda: {bench!r}
if {stub!r}:
    # Reached the board, without opening one. Nothing is written: the
    # tool binds `board` before its try block, so this propagates
    # before any row exists.
    import measure
    def _no(*a, **k):
        raise RuntimeError({sentinel!r})
    measure.Board = _no
code, msg, reached = 0, "", False
try:
    runpy.run_path({tool!r}, run_name="__main__")
except SystemExit as e:
    code, msg = (1, e.code) if isinstance(e.code, str) else (e.code or 0, "")
except BaseException as e:
    code, msg = 99, f"{{type(e).__name__}}: {{e}}"
    reached = {sentinel!r} in str(e)
print("@@" + json.dumps({{"code": code, "msg": msg, "reached": reached,
                          "measure": "measure" in sys.modules}}))
"""


def _run(bench, argv=(), stub=False):
    src = DRIVER.format(repo=REPO, tool=TOOL, bench=bench, stub=stub,
                        sentinel=SENTINEL)
    env = dict(os.environ)
    env.pop("DUE_BENCH", None)
    out = subprocess.run([sys.executable, "-c", src, *argv],
                         capture_output=True, text=True, env=env, cwd=REPO)
    for line in out.stdout.splitlines():
        if line.startswith("@@"):
            return json.loads(line[2:])
    raise AssertionError(
        f"driver produced no verdict:\n{out.stdout}\n{out.stderr}")


def test_no_bench_refuses_before_the_board_is_opened():
    """The branch the guard's author could not reach: no DUE_BENCH, no
    bench.json."""
    got = _run({})
    assert got["code"] == 1, got
    assert "REFUSING" in got["msg"] and "no bench" in got["msg"], got
    assert not got["measure"], (
        "the tool imported measure before refusing: a refusal after the "
        "board is opened still runs the experiment on someone's board")


def test_an_existing_record_is_refused_by_name():
    """Never truncate a record; that is how linux-x1's rows were lost."""
    got = _run({"bench": "linux-x1"})
    assert got["code"] == 1 and "already exists" in got["msg"], got
    assert not got["measure"], got


@pytest.mark.parametrize("argv,code", [(["--help"], 0), (["--rounds=4"], 2)])
def test_any_argument_prints_and_exits(argv, code):
    """`--help` must not be a way to run the experiment."""
    got = _run({"bench": "nowhere"}, argv=argv)
    assert got["code"] == code, got
    assert not got["measure"], got


def test_the_guard_lets_a_declared_bench_through():
    """The positive control. Without it the three refusals above are
    satisfied by a tool that refuses everything."""
    got = _run({"bench": "no-such-bench-please-never-exist"}, stub=True)
    assert got["reached"], (
        "with a bench and no existing record the tool never reached "
        f"measure.Board; the refusals above then prove nothing: {got}")
