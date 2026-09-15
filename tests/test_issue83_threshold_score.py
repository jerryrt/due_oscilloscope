"""The #83 step-shape verdict (V1d): each reading, and the shapes it must not score.

Needs no board. The readings were registered on #83 before any row
existed, so this holds the code to them: STEP AT, STEP BELOW and RAMP are
disjoint, a non-monotone or incomplete shape is named rather than scored,
and a value whose blocks disagree or whose control is floor is not scored
at all. The most likely wrong answer is a ramp read out of one noisy
marginal rung, which is why STEP BELOW allows exactly one.
"""
import json
import os
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(REPO, "tools", "issue83_threshold_score.py")
sys.path.insert(0, os.path.join(REPO, "tools"))
import issue83_threshold_score as ts  # noqa: E402

V3 = [1408, 1440, 1472, 1504, 1536, 1568]     # 512 x 3 is the fifth
T3 = 1536
RATIO = {"floor": 1.0, "marginal": 1.3, "lifted": 2.0}


def _seq(classes, ratios=None):
    ratios = ratios or [RATIO[c] for c in classes]
    return list(zip(V3, classes, ratios))


F, M, L = "floor", "marginal", "lifted"


@pytest.mark.parametrize("classes, expect", [
    ([F, F, F, F, L, L], "STEP AT 512 x VALUE"),
    ([F, F, F, F, M, L], "STEP AT 512 x VALUE"),
    ([F, F, F, F, F, L], "STEP AT 512 x VALUE"),
    ([F, F, F, L, L, L], "STEP BELOW 512 x VALUE"),
    ([F, F, M, L, L, L], "STEP BELOW 512 x VALUE"),
    ([F, M, L, L, L, L], "STEP BELOW 512 x VALUE"),
    ([F, F, M, M, L, L], "RAMP"),
    ([F, M, M, M, M, L], "RAMP"),
    ([F, F, F, M, M, L], "RAMP"),
    ([F, F, F, F, F, F], "NO STEP IN WINDOW"),
    ([M, M, L, L, L, L], "ONSET BELOW WINDOW"),
    ([L, L, L, L, L, L], "ONSET BELOW WINDOW"),
    ([F, F, M, M, M, M], "NOT LIFTED BY THE TOP RUNG"),
    ([F, F, L, F, L, L], "NON-MONOTONE"),
    ([F, M, L, M, L, L], "NON-MONOTONE"),
])
def test_each_shape_reads_as_registered(classes, expect):
    assert ts.step_reading(_seq(classes), T3) == expect


def test_a_ramp_must_not_fall():
    assert ts.step_reading(_seq([F, F, M, M, L, L], [1, 1, 1.4, 1.3, 2, 2]), T3) \
        == "RAMP NOT RISING"
    assert ts.step_reading(_seq([F, F, M, M, L, L], [1, 1, 1.3, 1.3, 2, 2]), T3) == "RAMP"


def test_a_step_above_the_threshold_is_named_not_scored():
    ivs = [1408, 1440, 1536, 1568, 1600, 1632]
    seq = list(zip(ivs, [F, F, F, M, L, L], [1, 1, 1, 1.3, 2, 2]))
    assert ts.step_reading(seq, 1536) == "STEP ABOVE 512 x VALUE"
    assert "STEP ABOVE 512 x VALUE" not in ts.REGISTERED_READINGS


def test_the_three_readings_are_disjoint_over_every_shape():
    import itertools
    for classes in itertools.product((F, M, L), repeat=6):
        got = ts.step_reading(_seq(list(classes)), T3)
        at = (all(c == F for iv, c in zip(V3, classes) if iv < T3)
              and all(c == L for iv, c in zip(V3, classes) if iv > T3))
        if got == "STEP BELOW 512 x VALUE" or got == "RAMP":
            assert not at


# ---- end to end, through the record guards and the uninformative checks

RUNGS = {3: [704, 720, 736, 752, 768, 784], 4: [960, 976, 992, 1008, 1024, 1040]}
ORDER = [3, 4, 0, 1, 0, 4, 3]
LEVEL = {F: 30.0, M: 40.0, L: 70.0}


def _record(tmp_path, shape, override=None):
    """shape: {value: [class per rung]}; override: {(block, rc): class}."""
    rows = []
    for blk, v in enumerate(ORDER, 1):
        build = "478db5f" if v == 0 else f"478db5f+{v:08x}"
        for value in (3, 4):
            for i, rc in enumerate(RUNGS[value]):
                cls = (F if v == 0 else L if v == 1 else
                       shape[value][i] if v == value else F)
                cls = (override or {}).get((blk, rc), cls)
                for run in range(1, 8):
                    base = LEVEL[cls] + (run % 3) - 1
                    rows.append({"run": run, "run1": run == 1, "rc": rc,
                                 "fw_build": build, "hold_ok": True,
                                 "total_abs": base, "n_sites": 0})
    p = tmp_path / "v1d.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return p


def _score(path):
    spec = ";".join(f"{v}:{','.join(map(str, r))}" for v, r in RUNGS.items())
    r = subprocess.run([sys.executable, TOOL, str(path), "--order",
                        ",".join(map(str, ORDER)), "--per-block", "84",
                        "--steps", spec], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    verdicts = r.stdout.split("REGISTERED VERDICTS")[1]
    lines = verdicts.splitlines()
    out = {}
    for i, line in enumerate(lines):
        if line.strip().startswith("REFRESH 3,") or line.strip().startswith("REFRESH 4,"):
            out[int(line.split()[1].rstrip(","))] = lines[i + 1].strip()
    return out


def test_end_to_end_reads_both_values(tmp_path):
    got = _score(_record(tmp_path, {3: [F, F, M, M, L, L], 4: [F, F, F, F, L, L]}))
    assert got[3] == "RAMP"
    assert got[4] == "STEP AT 512 x VALUE"


def test_blocks_that_disagree_leave_the_value_unscored(tmp_path):
    # block 7 is value 3's second block; flip one rung from marginal to lifted
    got = _score(_record(tmp_path, {3: [F, F, M, M, L, L], 4: [F, F, F, F, L, L]},
                         override={(7, 736): L}))
    assert got[3].startswith("UNINFORMATIVE") and "736" in got[3]
    assert got[4] == "STEP AT 512 x VALUE"


def test_a_floor_control_leaves_the_value_unscored(tmp_path):
    # block 4 is the REFRESH 1 control
    got = _score(_record(tmp_path, {3: [F, F, M, M, L, L], 4: [F, F, F, F, L, L]},
                         override={(4, 992): F}))
    assert got[4].startswith("UNINFORMATIVE") and "992" in got[4]
    assert got[3] == "RAMP"
