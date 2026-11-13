"""Run one section of a simulation study on a throw-away copy, for the bench.

    python3 hardware/afe-proto/tests/bench_sim.py sim/scope dc

The studies write their results and netlists beside themselves, so they run on a copy in a temp directory and
the repository is left as found. They need the vendor models, which are fetched, hash-pinned, by
tools/fetch_models.py and are not in git: a missing model is an error here, not a skip.
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

AFE = Path(__file__).resolve().parents[1]
study, *args = sys.argv[1:]
if not (AFE / "models" / "opa365").is_dir():
    sys.exit("bench_sim: vendor models are not fetched (python3 -I hardware/afe-proto/tools/fetch_models.py)")
with tempfile.TemporaryDirectory(prefix="bench-sim-") as d:
    root = Path(d) / "afe-proto"
    for part in ("sim", "simtools", "models", "models-open", "v2"):
        shutil.copytree(AFE / part, root / part, ignore=shutil.ignore_patterns("__pycache__", "netlists*", "work*", "raw*"))
    r = subprocess.run([sys.executable, "-I", "run.py", *args], cwd=root / study)
    sys.exit(r.returncode)
