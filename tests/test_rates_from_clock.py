"""No tool or test holds a rate that was exact only at 78 MHz.

Every RC divides MCK/2, so a rate written as a number is right for one
clock only. The suite runs at 90 MHz; a literal 453488 is 39 MHz // 86 and
nothing at 45 MHz, and a tool that asks for it gets a different rate than
it names while every counter stays green. This reads the tree for them.

A number is flagged when it is a rate at 39 MHz and not at 45 MHz (200000
is both, and passes), when it is a clock constant (39_000_000, 78_000_000),
and a dictionary literal with such a key is reported whole so its other
keys are reviewed with it. Rates that are no divisor at either clock, and
period lattices, are not visible to a scan and are listed in
docs/analog-validation-plan.md.
"""
import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCANNED = ("tests", "host", "tools", "gui")
TC_OLD = 39_000_000       # MCK 78 / 2
TC_NEW = 45_000_000       # MCK 90 / 2
CLOCKS = (39_000_000, 78_000_000)
#: Below this a number is a count, not a rate, and always divides both.
MIN_RATE = 1000

#: (file, value) -> why the number is not a stale rate.
EXCLUDED = {
    ("tests/test_board_clock.py", 78_000_000):
        "the other clock a board can be on, the input to the refusal",
    ("tools/issue5_metric.py", 78_000_000):
        "the clock the comb lattice was measured at, which the metric refuses to leave",
    ("tests/test_phase0.py", 78_000_000):
        "the other clock a record can be at, the input to the refusals",
    ("tests/test_repeat.py", 78_000_000):
        "a clock recorded in a synthetic row, the input to the mixed-clock refusal",
    ("tests/test_issue5_metric.py", 78_000_000):
        "the clock recorded in a synthetic row, the input to the refusal",
    ("tests/test_pam_oracle.py", 8191):
        "PAM64's symbols per period, 2^13 - 1, not a rate",
    ("tests/test_etspattern.py", 8191):
        "PAM64's symbols per period, 2^13 - 1, not a rate",
    ("tests/test_dso_metrics.py", 11775):
        "a sample count of a synthetic record, not a rate",
    ("tests/test_dso_metrics.py", 65000):
        "a sample count of a synthetic record, not a rate",
    ("tests/test_gui.py", 453488):
        "a synthetic stream's rate; the GUI tests take any",
    ("tests/test_noise.py", 453488):
        "the sampling rate of a synthetic signal whose spectrum the test knows; any rate works",
    ("tests/test_seq_steps.py", 402061):
        "the rate field of a synthetic frame header",
    ("tools/issue5_alias_sweep.py", 209677):
        "the issue-5 campaign's registered trigger set, defined in Hz at MCK 78",
    ("tools/issue5_alias_sweep.py", 205263):
        "the issue-5 campaign's registered trigger set, defined in Hz at MCK 78",
    ("tools/issue5_alias_sweep.py", 203125):
        "the issue-5 campaign's registered trigger set, defined in Hz at MCK 78",
    ("tools/issue52_threeclock.py", 78_000_000):
        "analyses records taken at MCK 78; the nominal is theirs",
    ("tools/issue82_ksweep.py", 8200):
        "a seed, not a rate",
}
#: Files whose job is to describe the 78 MHz image, with the reason.
FILES_EXCLUDED = {
    "tests/test_rates_from_clock.py": "this file's own examples",
}


def _sources():
    for top in SCANNED:
        for path in sorted((ROOT / top).rglob("*.py")):
            yield path.relative_to(ROOT).as_posix(), path.read_text(encoding="utf-8")


def _rate_at(n, tc):
    """True when n = tc // rc for some integer rc."""
    if n <= 0:
        return False
    lo = tc // (n + 1) + 1          # smallest rc with tc // rc <= n
    return any(tc // rc == n for rc in range(max(lo - 1, 1), tc // n + 2))


def stale(n):
    """Why a number is stale, or None."""
    if n in CLOCKS:
        return "clock constant"
    if n >= MIN_RATE and _rate_at(n, TC_OLD) and not _rate_at(n, TC_NEW):
        return "a rate at 39 MHz that is none at 45 MHz"
    return None


def _number(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) \
            and not isinstance(node.value, bool):
        v = node.value
        if isinstance(v, float):
            if not v.is_integer():
                return None
            v = int(v)
        return v
    return None


def find(sources=None, excluded=None, files_excluded=None):
    """(file, line, value, why) of every stale number; (files examined)."""
    excluded = EXCLUDED if excluded is None else excluded
    files_excluded = FILES_EXCLUDED if files_excluded is None else files_excluded
    out, examined = [], 0
    for rel, text in (sources if sources is not None else _sources()):
        if rel in files_excluded:
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        examined += 1
        dict_nodes = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                for k in node.keys:
                    if k is not None:
                        dict_nodes[id(k)] = node
        reported = set()
        for node in ast.walk(tree):
            n = _number(node)
            if n is None:
                continue
            why = stale(n)
            if why is None or (rel, n) in excluded:
                continue
            owner = dict_nodes.get(id(node))
            if owner is not None:
                if id(owner) in reported:
                    continue
                reported.add(id(owner))
                out.append((rel, owner.lineno, n, why + " (a dictionary key; the whole literal)"))
            else:
                out.append((rel, node.lineno, n, why))
    return out, examined


# -- the tree --------------------------------------------------------------

def test_no_number_in_the_tree_is_a_rate_that_was_exact_only_at_78_mhz():
    found, examined = find()
    assert examined >= 200, f"only {examined} files examined; the scan went blind"
    assert not found, (
        "a number that is a rate at 39 MHz and none at 45, or a clock constant. "
        "Take it from measure.hz_for / measure.TC_CLOCK_HZ, or add (file, value) "
        "to EXCLUDED with the reason it is not a stale rate:\n  "
        + "\n  ".join(f"{f}:{n}: {v} - {why}" for f, n, v, why in found))


# -- break the scan on purpose ----------------------------------------------

def _plant(src, rel="host/planted.py"):
    return [(rel, src)]


def test_the_scan_says_which_numbers_are_stale_and_which_are_not():
    assert stale(453488) and stale(886363) and stale(906976) and stale(1392857)
    assert stale(39_000_000) and stale(78_000_000)
    for ok in (200000, 100000, 600000, 50000, 1_000_000, 523255, 1_022_727, 45_000_000, 512, 5):
        assert stale(ok) is None, ok


def test_the_scan_sees_a_planted_rate_in_a_tool_a_test_and_a_dictionary_key():
    for rel in ("tools/planted.py", "tests/planted.py", "host/planted.py"):
        assert find(sources=_plant("rate = 453488\n", rel), excluded={},
                    files_excluded={})[0], rel
    found, _ = find(sources=_plant("PRESETS = {200000: '3', 453_488: '5', 100000: '2'}\n"),
                    excluded={}, files_excluded={})
    assert len(found) == 1 and "dictionary key" in found[0][3]


def test_the_scan_normalises_a_float_and_an_underscore_spelling():
    for src in ("x = 453488.0\n", "x = 453_488\n", "x = 39_000_000\n"):
        assert find(sources=_plant(src), excluded={}, files_excluded={})[0], src


def test_the_scan_does_not_read_prose():
    src = '"""the 453488 ceiling at MCK 78"""\n# 886363 sps\nx = "906976"\n'
    assert find(sources=_plant(src), excluded={}, files_excluded={})[0] == []


def test_an_exclusion_is_a_file_and_a_value():
    src = "x = 453488\n"
    assert find(sources=_plant(src), excluded={("host/planted.py", 453488): "why"},
                files_excluded={})[0] == []
    assert find(sources=_plant(src), excluded={("host/other.py", 453488): "why"},
                files_excluded={})[0]


def test_every_exclusion_still_matches_a_number_in_the_tree():
    texts = dict(_sources())
    stale_ex = []
    for (rel, value) in EXCLUDED:
        found, _ = find(sources=[(rel, texts.get(rel, ""))], excluded={}, files_excluded={})
        if not any(v == value for _f, _n, v, _w in found):
            stale_ex.append((rel, value))
    assert not stale_ex, f"exclusions nothing uses any more: {stale_ex}"


# -- the tools follow the clock ----------------------------------------------

import json  # noqa: E402
import os  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402

import pytest  # noqa: E402

PROBE = r'''
import json, sys
sys.path.insert(0, "host"); sys.path.insert(0, "tools")
import clock, eqtime, measure, noisetool, dso_metrics, clock_calib, bench
import issue5_alias_sweep as sw
from daemon import rates
print(json.dumps({
    "clock": [clock.MCK_HZ, clock.TC_CLOCK_HZ],
    "measure": measure.TC_CLOCK_HZ, "eqtime": eqtime.TC_CLOCK_HZ,
    "rates": rates.TC_CLOCK_HZ, "bench": bench.TIMER_HZ,
    "calib": [clock_calib.TC_CLOCK_HZ, clock_calib.MCK_NOMINAL_HZ],
    "floor": [noisetool.PRESETS["5"], dso_metrics.GEN_TIOA0_MAX_HZ],
    "dacc": dso_metrics.DACC_CEILING_HZ,
    "p3": noisetool.PRESETS["3"], "rc": sw.rc_of(200000)}))
'''


@pytest.mark.parametrize("mck", [78_000_000, 90_000_000])
def test_every_converted_tool_follows_the_clock_it_is_given(mck):
    env = dict(os.environ, DUE_MCK_HZ=str(mck))
    out = subprocess.run([sys.executable, "-c", PROBE], cwd=ROOT, env=env,
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr[-600:]
    got, tc = json.loads(out.stdout), mck // 2
    assert got["clock"] == [mck, tc]
    assert got["measure"] == got["eqtime"] == got["rates"] == got["bench"] == tc
    assert got["calib"] == [tc, mck]
    assert got["floor"] == [tc // 86, tc // 86]
    assert got["dacc"] == tc // 28
    assert got["p3"] == tc // (tc // 200_000)
    assert got["rc"] == tc // 200_000
