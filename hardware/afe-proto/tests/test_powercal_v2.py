"""v2 powercal is numpy only (no ngspice): its committed results are its golden, and a run must regenerate them.

Taken in the PCB image: run_all.sh reproduces every file in results/ and report.md byte for byte in 12 s. The
test runs the same scripts on a copy and compares the JSON at rtol 1e-9, so another numpy's last digits do not
fail it, and the report by line count.
"""
import shutil
import subprocess
import sys
from pathlib import Path

from simtools.compare import compare_trees

AFE = Path(__file__).resolve().parents[1]
STEPS = ["power", "refladder", "sense", "sc7", "coupling", "wires", "parts", "pw1_awg"]


def test_v2_powercal_regenerates_its_committed_results(tmp_path):
    v2 = tmp_path / "v2"
    shutil.copytree(AFE / "v2", v2, ignore=shutil.ignore_patterns("__pycache__", "raw*", "work*", "netlists*"))
    pc = v2 / "sim" / "powercal"
    for s in STEPS + ["report"]:
        r = subprocess.run([sys.executable, "-I", f"{s}.py"], cwd=pc, capture_output=True, text=True, timeout=300)
        assert r.returncode == 0, f"{s}.py: " + r.stdout[-300:] + r.stderr[-300:]
    committed = AFE / "v2" / "sim" / "powercal" / "results"
    assert len(list(committed.glob("*.json"))) >= 15
    assert compare_trees(committed, pc / "results", rtol=1e-9) == []
    assert (pc / "report.md").read_text().count("\n") == (AFE / "v2/sim/powercal/report.md").read_text().count("\n")
