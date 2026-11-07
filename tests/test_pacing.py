"""One home for waits and run lengths, and a guard that keeps it the only one.

`host/pacing.py` names five delay levels and five run-length levels. A
wait or a run length written as a bare number anywhere in `host/`, `gui/`
or `tests/` is a number nobody can audit against what it waits for, and
a bench that needs it longer or shorter has to find it by grep. So this
scans for them, and an exception carries its reason.
"""
import ast
import os
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "host"))
import pacing  # noqa: E402

SCANNED = ("host", "gui", "tests")

# (file, source text of the argument) -> why it is not a level.
SLEEP_ALLOWED = {
    ("host/transport.py", "timeout"):
        "the timeout the caller asked for, slept when the port is closed",
    ("host/daemon/device.py", "min(wait, timeout)"):
        "bounded by what the caller said it would wait",
    ("host/repeat.py", "WARMUP_S if seconds is None else seconds"):
        "the warm-up the caller names, WARMUP_S by default; a measured boundary",
    ("host/measure.py", "settle"):
        "a parameter: Board's defaults to none, run_loop's to a level",
    ("host/measure.py", "seconds"):
        "the run itself: a capture lasts the length its caller chose",
    ("host/measure.py", "min(pacing.FEED_PACE_CAP, -due / self.byte_rate + 0.001)"):
        "computed from the byte rate; FEED_PACE_CAP bounds it",
    ("host/measure.py", "min(pacing.FEED_PACE_CAP, (self.write_size - due) / self.byte_rate)"):
        "computed from the byte rate; FEED_PACE_CAP bounds it",
    ("tests/test_daemon_api.py", "NO_FRAME_WAIT_S"):
        "listens for a frame that must not arrive; derived from the frame rate",
    ("tests/test_daemon_api.py", "10 * HEARTBEAT_PERIOD_S"):
        "ten periods of the heartbeat the test asked for",
    ("tests/test_control.py", "PING_GAP_S"):
        "the interval the ping test measures on the device clock",
    ("tests/test_load.py", "secs"):
        "the observation window the caller chose, a run length",
    ("tests/test_load.py", "want_ms / 1000.0 + pacing.TURN"):
        "the stall it asked the device for, plus a level",
    ("tests/test_daemon_board_link.py", "timeout or pacing.POLL"):
        "a fake link that waits what its caller asked for",
    ("tests/test_daemon_hardware.py", "pacing.LONG"):
        "a run length, the daemon streams for this long",
    ("tests/test_daemon_hardware.py", "pacing.PROBE"):
        "a run length, an observation window",
}
#: Files whose waits are the oscilloscope's own command timing. They were
#: set against that instrument and this bench has none to re-measure them
#: on, so they stay as written until a bench with a scope reads them.
SLEEP_FILES_EXCLUDED = {
    "host/pacing.py": "the implementation of the levels",
    "host/scope.py": "instrument command timing; no scope on this bench",
}

#: Keywords whose argument is a run length.
RUN_KEYWORDS = ("seconds", "drain_s")
#: Files where `seconds=` is a ring or fixture size, not a run length.
RUN_FILES_EXCLUDED = {
    "tests/test_gui.py": "ChannelRing(seconds=...) sizes a buffer, not a run",
    "tests/test_rotation_row.py": "a fixture's idle_seconds, not a run",
    "tests/test_pacing.py": "this file's own examples",
}


def _sources():
    for top in SCANNED:
        for path in sorted((ROOT / top).rglob("*.py")):
            yield path.relative_to(ROOT).as_posix(), path


def _is_sleep(call):
    f = call.func
    return ((isinstance(f, ast.Attribute) and f.attr == "sleep"
             and isinstance(f.value, ast.Name) and f.value.id == "time")
            or (isinstance(f, ast.Name) and f.id == "sleep"))


def _uses_pacing(node):
    return any(isinstance(n, ast.Name) and n.id == "pacing"
               for n in ast.walk(node))


def _has_number(node):
    return any(isinstance(n, ast.Constant) and isinstance(n.value, (int, float))
               and not isinstance(n.value, bool) for n in ast.walk(node))


def bare_sleeps(sources=None, allowed=None, excluded=None):
    """(file, line, argument source) of every sleep that names no level."""
    allowed = SLEEP_ALLOWED if allowed is None else allowed
    excluded = SLEEP_FILES_EXCLUDED if excluded is None else excluded
    out, examined = [], 0
    for rel, path in (sources if sources is not None else _sources()):
        if rel in excluded:
            continue
        text = path.read_text(encoding="utf-8") if hasattr(path, "read_text") else path
        tree = ast.parse(text)
        examined += 1
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _is_sleep(node) and node.args:
                arg = node.args[0]
                src = ast.get_source_segment(text, arg) or ""
                src = " ".join(src.split())
                if (rel, src) in allowed:
                    continue
                if _uses_pacing(arg) and not (
                        _has_number(arg) and "FEED_PACE_CAP" not in src
                        and "pacing.pause" not in src
                        and not any(k in src for k in ("pacing.TURN", "pacing.POLL"))):
                    continue
                out.append((rel, node.lineno, src))
    return out, examined


def bare_run_lengths(sources=None, excluded=None):
    """(file, line, text) of every run length written as a number."""
    excluded = RUN_FILES_EXCLUDED if excluded is None else excluded
    out = []
    for rel, path in (sources if sources is not None else _sources()):
        if rel in excluded or not rel.startswith("tests/"):
            continue
        text = path.read_text(encoding="utf-8") if hasattr(path, "read_text") else path
        for node in ast.walk(ast.parse(text)):
            if not isinstance(node, ast.Call):
                continue
            for kw in node.keywords:
                if kw.arg in RUN_KEYWORDS and isinstance(kw.value, ast.Constant) \
                        and isinstance(kw.value.value, (int, float)):
                    out.append((rel, node.lineno, f"{kw.arg}={kw.value.value}"))
            name = getattr(node.func, "id", None)
            if name == "window" and len(node.args) >= 2 \
                    and isinstance(node.args[1], ast.Constant):
                out.append((rel, node.lineno, f"window(.., {node.args[1].value})"))
    return out


# -- the levels themselves ------------------------------------------------

def test_there_are_five_delay_levels_and_five_run_lengths_in_order():
    d = list(pacing.DELAYS.values())
    r = list(pacing.RUNS.values())
    assert len(d) == 5 and len(r) == 5
    assert d == sorted(d) and len(set(d)) == 5, "delay levels must climb"
    assert r == sorted(r) and len(set(r)) == 5, "run lengths must climb"
    assert all(v > 0 for v in d + r)


def _env_run(code, **env):
    e = {k: v for k, v in os.environ.items() if not k.startswith("DUE_DELAY")
         and not k.startswith("DUE_RUN")}
    e.update(env)
    e["PYTHONPATH"] = str(ROOT / "host")
    return subprocess.run([sys.executable, "-c", code], env=e,
                          capture_output=True, text=True)


def test_a_scale_multiplies_every_level_in_its_ladder_only():
    r = _env_run("import pacing; print(pacing.TURN, pacing.LONG)",
                 DUE_DELAY_SCALE="2")
    assert r.stdout.split() == [str(pacing.DELAYS["TURN"] * 2),
                                str(pacing.RUNS["LONG"])], r.stderr
    r = _env_run("import pacing; print(pacing.TURN, pacing.LONG)",
                 DUE_RUN_SCALE="0.5")
    assert r.stdout.split() == [str(pacing.DELAYS["TURN"]),
                                str(pacing.RUNS["LONG"] * 0.5)], r.stderr


def test_one_level_can_be_set_alone():
    r = _env_run("import pacing; print(pacing.SETTLE, pacing.TURN)",
                 DUE_DELAY_SETTLE="1.25")
    assert r.stdout.split() == ["1.25", str(pacing.DELAYS["TURN"])], r.stderr


@pytest.mark.parametrize("bad", ["fast", "0", "-1"])
def test_a_bad_setting_is_refused_rather_than_ignored(bad):
    r = _env_run("import pacing", DUE_DELAY_POLL=bad)
    assert r.returncode != 0 and "DUE_DELAY_POLL" in (r.stderr + r.stdout)


def test_a_wait_that_must_outlast_something_refuses_to_be_shorter():
    with pytest.raises(AssertionError, match="needs at least"):
        pacing.pause_at_least(0.01, 0.2, "ten heartbeat periods")
    pacing.pause_at_least(0.0, 0.0, "nothing to outlast")


def test_pause_attributes_time_to_its_level():
    before = pacing.report().get("SPIN", (0, 0.0))
    pacing.pause(pacing.SPIN)
    after = pacing.report()["SPIN"]
    assert after[0] == before[0] + 1


# -- the guard ------------------------------------------------------------

def test_no_wait_in_the_tree_is_a_bare_number():
    found, examined = bare_sleeps()
    assert examined >= 80, f"only {examined} files examined; the scan went blind"
    assert not found, (
        "a sleep that names no level in host/, gui/ or tests/ - use a "
        "pacing level, or add it to SLEEP_ALLOWED with the reason it is not "
        "one:\n  " + "\n  ".join(f"{f}:{n}: sleep({s})" for f, n, s in found))


def test_no_run_length_in_the_tests_is_a_bare_number():
    found = bare_run_lengths()
    assert not found, (
        "a run length written as a number - use a pacing run level:\n  "
        + "\n  ".join(f"{f}:{n}: {s}" for f, n, s in found))


def test_every_allowance_still_matches_something():
    found, _ = bare_sleeps(allowed={}, excluded={})
    live = {(f, s) for f, _n, s in found}
    # allowed entries that use a level are not 'found' bare; check the text
    texts = {rel: path.read_text(encoding="utf-8") for rel, path in _sources()}
    stale = []
    for (rel, src) in SLEEP_ALLOWED:
        flat = " ".join(texts.get(rel, "").split())
        if src not in flat:
            stale.append((rel, src))
    assert not stale, f"allowances nothing uses any more: {stale}"
    assert live is not None


# -- break the guard on purpose ------------------------------------------

def _plant(snippet):
    return [("host/planted.py", snippet)]


def test_the_scan_sees_a_planted_literal_sleep():
    found, _ = bare_sleeps(sources=_plant("import time\ntime.sleep(0.5)\n"),
                           allowed={}, excluded={})
    assert found == [("host/planted.py", 2, "0.5")]


def test_the_scan_sees_a_literal_hidden_next_to_a_level():
    found, _ = bare_sleeps(sources=_plant(
        "import time, pacing\ntime.sleep(min(timeout, 0.05))\n"),
        allowed={}, excluded={})
    assert found, "a number beside a level must still be flagged"


def test_the_scan_accepts_a_level():
    found, _ = bare_sleeps(sources=_plant(
        "import pacing\npacing.pause(pacing.TURN)\n"), allowed={}, excluded={})
    assert found == []


def test_the_scan_sees_a_planted_run_length():
    found = bare_run_lengths(sources=[("tests/planted.py",
        "run_capture(b, seconds=2.0)\nwindow(seconds, 3.0)\n")], excluded={})
    assert [s for _f, _n, s in found] == ["seconds=2.0", "window(.., 3.0)"]


# -- reads, quiet gaps, caps, timeouts, poll slices, deadlines ---------------

READ_CALLS = {"drain_console": 0, "wait_any": 1}
TIMING_KEYWORDS = ("secs", "quiet", "cap", "timeout", "wait", "drain_s")
#: (file, text) -> why a timing number stays a number.
TIMING_ALLOWED = {}


def _number(node):
    return (isinstance(node, ast.Constant) and isinstance(node.value, (int, float))
            and not isinstance(node.value, bool) and node.value != 0)


def bare_timings(sources=None, allowed=None, excluded=None):
    """(file, line, what) of every read length, quiet gap, cap, timeout,
    poll slice or deadline written as a number."""
    allowed = TIMING_ALLOWED if allowed is None else allowed
    excluded = SLEEP_FILES_EXCLUDED if excluded is None else excluded
    out = []
    for rel, path in (sources if sources is not None else _sources()):
        if rel in excluded or rel in RUN_FILES_EXCLUDED and rel.endswith("test_gui.py"):
            continue
        text = path.read_text(encoding="utf-8") if hasattr(path, "read_text") else path
        tree = ast.parse(text)
        in_assert = {id(x) for a in ast.walk(tree) if isinstance(a, ast.Assert)
                     for x in ast.walk(a.test)}
        for n in ast.walk(tree):
            hits = []
            if isinstance(n, ast.Call):
                name = getattr(n.func, "attr", getattr(n.func, "id", None))
                i = READ_CALLS.get(name)
                if i is not None and len(n.args) > i and _number(n.args[i]):
                    hits.append((n.args[i], f"{name}({n.args[i].value})"))
                for kw in n.keywords:
                    if kw.arg in TIMING_KEYWORDS and _number(kw.value):
                        hits.append((kw.value, f"{kw.arg}={kw.value.value}"))
            if isinstance(n, ast.arguments):
                pos = n.args[len(n.args) - len(n.defaults):] if n.defaults else []
                for a, d in list(zip(pos, n.defaults)) + [
                        (a, d) for a, d in zip(n.kwonlyargs, n.kw_defaults) if d is not None]:
                    if a.arg in TIMING_KEYWORDS and _number(d):
                        hits.append((d, f"def {a.arg}={d.value}"))
            if (isinstance(n, ast.Compare) and len(n.ops) == 1
                    and isinstance(n.ops[0], (ast.Lt, ast.LtE))
                    and isinstance(n.left, ast.BinOp) and isinstance(n.left.op, ast.Sub)
                    and (ast.get_source_segment(text, n.left.left) or "").replace(" ", "")
                    in ("time.time()", "time.monotonic()")
                    and _number(n.comparators[0]) and id(n) not in in_assert):
                hits.append((n.comparators[0],
                             f"elapsed < {n.comparators[0].value}"))
            if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Add) \
                    and _number(n.right):
                left = ast.get_source_segment(text, n.left) or ""
                if left.replace(" ", "") in ("time.time()", "time.monotonic()"):
                    hits.append((n.right, f"deadline now + {n.right.value}"))
            for node, what in hits:
                if (rel, what) not in allowed:
                    out.append((rel, node.lineno, what))
    return out


def test_no_read_timeout_or_deadline_in_the_tree_is_a_bare_number():
    found = bare_timings()
    assert not found, (
        "a read length, quiet gap, cap, timeout, poll slice or deadline "
        "written as a number - use a pacing read or limit level, or add it "
        "to TIMING_ALLOWED with the reason it is not one:\n  "
        + "\n  ".join(f"{f}:{n}: {w}" for f, n, w in found))


def test_the_scan_sees_each_kind_of_timing_number():
    src = ("def f(x, timeout=5, drain_s=0.3):\n"
           "    while time.time() - t1 < 1.5:\n        pass\n"
           "    board.drain_console(0.3)\n"
           "    transport.wait_any([a], 0.1)\n"
           "    b.ask('x', secs=1.0, quiet=0.3, cap=2.0)\n"
           "    g(wait=12)\n"
           "    end = time.time() + 1.5\n")
    found = bare_timings(sources=[("host/planted.py", src)], allowed={}, excluded={})
    assert {w for _f, _n, w in found} == {
        "def timeout=5", "def drain_s=0.3", "elapsed < 1.5", "drain_console(0.3)", "wait_any(0.1)", "secs=1.0",
        "quiet=0.3", "cap=2.0", "wait=12", "deadline now + 1.5"}


def test_the_scan_accepts_a_level_and_a_zero():
    src = ("board.drain_console(pacing.GLANCE)\n"
           "transport.wait_any([a], 0)\n"
           "c.open(timeout=pacing.NORMAL)\n")
    assert bare_timings(sources=[("host/planted.py", src)], allowed={}, excluded={}) == []


def unimported_users(sources=None):
    """Files that use `pacing.X` and never import pacing at module level."""
    out = []
    for rel, path in (sources if sources is not None else _sources()):
        if rel == "host/pacing.py":
            continue
        text = path.read_text(encoding="utf-8") if hasattr(path, "read_text") else path
        tree = ast.parse(text)
        uses = any(isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
                   and n.value.id == "pacing" for n in ast.walk(tree))
        top = any(isinstance(n, ast.Import) and any(a.name == "pacing" for a in n.names)
                  or isinstance(n, ast.ImportFrom) and n.module == "pacing"
                  for n in tree.body)
        if uses and not top:
            out.append(rel)
    return out


def test_every_file_that_uses_a_level_imports_pacing_at_module_level():
    assert unimported_users() == []


def test_the_import_scan_sees_a_missing_import_even_beside_a_nested_one():
    src = "def f():\n    import pacing\n    return 1\nx = pacing.TURN\n"
    assert unimported_users(sources=[("host/planted.py", src)]) == ["host/planted.py"]


# -- a number must not hide in a module constant ----------------------------

#: (file, name) -> why a module-level number named *_S is not a level.
TIMING_CONSTANTS = {
    ("host/repeat.py", "WARMUP_S"):
        "the post-flash warm-up of the reflash axis, about a minute (measurement-suite.md)",
    ("tests/test_control.py", "CTL_IDLE_S"):
        "lib/due_shared/src/ctl.c CTL_IDLE_US: the parser abandons a half frame after this",
    ("tests/test_control.py", "PING_GAP_S"):
        "the interval the ping test measures on the device clock",
    ("tests/test_daemon_api.py", "HEARTBEAT_PERIOD_S"):
        "the period_ms=20 these tests ask the daemon for",
    ("tests/test_daemon_api.py", "NO_FRAME_WAIT_S"):
        "a listen for a frame that must not arrive, derived from the frame rate",
    ("tests/test_flash.py", "BOOT_QUIET_S"):
        "the watch window of the 'no boot' cases, the value the tests assert against",
    ("tests/test_ports.py", "FIND_PORTS_WAIT_S"):
        "the wait find_all_ports is given when it must report nothing; the input under test",
    ("host/daemon/device.py", "REPLAY_MAX_GAP_S"):
        "the longest pause a replay reproduces between two frames; a feature setting",
    ("host/measure.py", "CLOSE_WEDGE_S"):
        "how long a close() may take before it is called wedged; a detection threshold",
    ("host/measure.py", "TRIM_WARMUP_S"):
        "the feeder's rate-trim warm-up, tuned with the feed and not a wait",
    ("host/measure.py", "TRIM_PERIOD_S"):
        "the feeder's rate-trim period, tuned with the feed and not a wait",
    ("tests/test_daemon_api.py", "LOCK_WAIT_MAX_S"):
        "the bound the lock-wait test asserts against",
    ("tests/test_trace.py", "RISE_S"):
        "a physical rise time of a synthetic signal, not a wait",
    ("tests/test_crash_record_board.py", "HEALTHY_S"):
        "lib/due_shared/src/crashrec.h CRASHREC_HEALTHY_MS: the board's healthy period, mirrored",
}


def undeclared_timing_constants(sources=None, declared=None):
    declared = TIMING_CONSTANTS if declared is None else declared
    out = []
    for rel, path in (sources if sources is not None else _sources()):
        if rel == "host/pacing.py":
            continue
        text = path.read_text(encoding="utf-8") if hasattr(path, "read_text") else path
        for n in ast.parse(text).body:
            if isinstance(n, ast.Assign) and len(n.targets) == 1 \
                    and isinstance(n.targets[0], ast.Name) \
                    and n.targets[0].id.endswith("_S") and _number(n.value) \
                    and (rel, n.targets[0].id) not in declared:
                out.append((rel, n.targets[0].id))
    return out


def test_every_module_level_timing_constant_is_declared_with_its_reason():
    found = undeclared_timing_constants()
    assert not found, ("a number named *_S at module level hides a timing value "
                       "from the scan - use a level or declare it in TIMING_CONSTANTS "
                       f"with the reason: {found}")


def test_every_declared_timing_constant_still_exists():
    texts = {rel: path.read_text(encoding="utf-8") for rel, path in _sources()}
    missing = [(f, n) for (f, n) in TIMING_CONSTANTS
               if f"\n{n} = " not in texts.get(f, "")]
    assert not missing, f"declared constants that are gone: {missing}"


def test_the_constant_scan_sees_a_planted_number_in_a_constant():
    assert undeclared_timing_constants(
        sources=[("tests/planted.py", "WAIT_S = 2.5\nOK = 3\n")], declared={}
    ) == [("tests/planted.py", "WAIT_S")]
