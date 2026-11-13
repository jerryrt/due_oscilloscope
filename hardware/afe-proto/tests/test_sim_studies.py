"""Each study on the shared tools reproduces its golden, number for number.

The golden is the OLD code's output run in the PCB image (tests/golden_sim/<study>/STAMP.json says how); a ported
study is kept only while it reproduces that to rtol 1e-9. A study that cannot is reported, never loosened.
"""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from simtools.compare import compare_trees

pytestmark = [pytest.mark.vendor, pytest.mark.ngspice, pytest.mark.slow]

AFE = Path(__file__).resolve().parents[1]
GOLD = Path(__file__).resolve().parent / "golden_sim"


def run_study(tmp_path, study, *args):
    root = tmp_path / "afe-proto"
    for part in ("sim", "simtools", "models", "models-open", "v2"):
        shutil.copytree(AFE / part, root / part, ignore=shutil.ignore_patterns("__pycache__", "netlists*", "work*"))
    r = subprocess.run([sys.executable, "-I", "run.py", *args], cwd=root / study, capture_output=True, text=True, timeout=1500)
    assert r.returncode == 0, r.stdout[-400:] + r.stderr[-400:]
    return root / study / "results"


def test_v1_scope_hz_reproduces_its_golden(tmp_path):
    res = run_study(tmp_path, "sim/scope")
    gold = GOLD / "v1-scope-hz"
    # only the top-level files are this variant's output; subfolders hold other variants' committed copies
    new = tmp_path / "new"
    new.mkdir()
    for f in gold.glob("*.json"):
        if f.name != "STAMP.json":
            shutil.copy(res / f.name, new / f.name)
    g = tmp_path / "gold"
    g.mkdir()
    for f in gold.glob("*.json"):
        if f.name != "STAMP.json":
            shutil.copy(f, g / f.name)
    assert compare_trees(g, new, rtol=1e-9) == []
