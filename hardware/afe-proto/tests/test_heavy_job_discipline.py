"""Heavy jobs run one at a time through the capped runner: no pools, and ngspice only via simtools.

Scans the pipeline's own modules (pcbtools/, simtools/), not the frozen studies in whatif/
and not the legacy sim/ callers, which are ported separately and only where their output reproduces.
"""
import re
from pathlib import Path

AFE = Path(__file__).resolve().parents[1]
SCOPE = ["pcbtools", "simtools"]
POOLS = re.compile(r"\b(multiprocessing|ProcessPoolExecutor|ThreadPoolExecutor|Pool\()")
NGSPICE_CALL = re.compile(r"""["']ngspice["']""")


def sources():
    files = [f for d in SCOPE for f in (AFE / d).rglob("*.py") if "__pycache__" not in f.parts]
    assert len(files) >= 5, f"only {len(files)} files scanned; the scope moved"      # a floor: it must look at something
    return files


def test_no_process_pools_in_the_pipeline_modules():
    bad = [(f.relative_to(AFE).as_posix(), m.group(0)) for f in sources() for m in POOLS.finditer(f.read_text())]
    assert not bad, bad


def test_ngspice_is_only_started_by_the_shared_runner():
    allowed = {"simtools/ngspice_run.py", "simtools/netlib_common.py"}
    bad = [f.relative_to(AFE).as_posix() for f in sources()
           if NGSPICE_CALL.search(f.read_text()) and f.relative_to(AFE).as_posix() not in allowed]
    assert not bad, bad
