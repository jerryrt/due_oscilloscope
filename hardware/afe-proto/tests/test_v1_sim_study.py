"""The v1 scope + AWG study (v1/sim: v2's harnesses with the v1 board's values and the extracted strays) reproduces its golden.

The golden is tests/golden_sim/v1-gate3 (STAMP.json says how it was taken: in the PCB image, twice, byte-identical). A later change
to the study, to v2's harness it patches, to simtools or to the vendor macro's derivation moves a number and fails this test. It
needs the vendor macro (models/tph2501/TPH2501.mdl, local and gitignored, MC-6): without it the test SKIPS with that reason
(and FAILS under --require-tool=vendor); it never passes without running."""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from simtools.compare import compare_trees

pytestmark = [pytest.mark.vendor, pytest.mark.ngspice, pytest.mark.slow]

AFE = Path(__file__).resolve().parents[1]
GOLD = Path(__file__).resolve().parent / "golden_sim" / "v1-gate3"
MODEL = AFE / "models" / "tph2501" / "TPH2501.mdl"


def _copy(tmp_path):
    root = tmp_path / "afe-proto"
    for part in ("v1", "v2", "simtools", "models", "models-open"):
        shutil.copytree(AFE / part, root / part, ignore=shutil.ignore_patterns("__pycache__", "results", "work*"))
    return root


def test_v1_study_reproduces_its_golden(tmp_path):
    if not MODEL.is_file():
        pytest.skip(f"{MODEL} is absent (vendor file, MC-6): python3 -I hardware/afe-proto/tools/fetch_models.py")
    root = _copy(tmp_path)
    out = tmp_path / "new"
    r = subprocess.run([sys.executable, "-I", "run_study.py", "--out", str(out), "--work", str(tmp_path / "w")], cwd=root / "v1" / "sim",
                       capture_output=True, text=True, timeout=1500)
    assert r.returncode == 0, r.stdout[-400:] + r.stderr[-800:]
    names = sorted(p.name for p in out.glob("*.json"))
    assert names == sorted(p.name for p in GOLD.glob("*.json") if p.name != "STAMP.json"), names     # nothing missing, nothing extra
    g = tmp_path / "gold"
    g.mkdir()
    for f in GOLD.glob("*.json"):
        if f.name != "STAMP.json":
            shutil.copy(f, g / f.name)
    assert compare_trees(g, out, rtol=1e-12) == []


def test_golden_is_not_empty():
    # the golden itself: a tree with no JSON in it would make the comparison above vacuous
    assert len([p for p in GOLD.glob("*.json") if p.name != "STAMP.json"]) >= 4


def test_v1_harness_netlists_are_v1s_circuit(tmp_path):
    """pcbtools.spicecmp: each harness netlist against v1's schematic (generated from the design data, exported by kicad-cli),
    and four mutants that must fail, so the comparison is known to be able to"""
    import os
    if not shutil.which("kicad-cli"):
        pytest.skip("kicad-cli is absent (the PCB image carries it)")
    if not MODEL.is_file():
        pytest.skip(f"{MODEL} is absent (vendor file, MC-6): the netlists are built through the vendor derivation")
    root = _copy(tmp_path)
    for part in ("pcbtools", "kicad", "tests/fixtures"):
        if (AFE / part).exists():
            shutil.copytree(AFE / part, root / part, ignore=shutil.ignore_patterns("__pycache__", "wip"), dirs_exist_ok=True)
    env = dict(os.environ, PCBTOOLS_V1_SOURCE=str(root / "kicad"))
    r = subprocess.run([sys.executable, "-I", "v1/sim/compare.py", "--mutate"], cwd=root, capture_output=True, text=True, env=env, timeout=600)
    assert r.returncode == 0, r.stdout[-800:] + r.stderr[-800:]
    lines = r.stdout.splitlines()
    assert sum("SAME CIRCUIT" in ln for ln in lines) == 2, r.stdout
    assert sum("FAILS as it must" in ln for ln in lines) == 4 and not any("blind" in ln for ln in lines), r.stdout
