"""bench.py: the single-step selection, and a ratio-table header written from the run's own metadata."""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import bench  # noqa: E402


def _run(*args):
    return subprocess.run([sys.executable, str(HERE / "bench.py"), *args], capture_output=True, text=True)


def test_list_prints_board_slash_step():
    r = _run("--list")
    lines = r.stdout.split()
    assert r.returncode == 0 and len(lines) > 10, r.stderr
    assert all("/" in x for x in lines)


def test_step_selects_nothing_for_an_unknown_name_and_refuses():
    r = _run("--step", "no-such-step")
    assert r.returncode == 1 and "no step selected" in r.stderr


def test_header_states_the_measured_load_not_a_fixed_claim():
    quiet = bench.md_pairs([], {"machine": "montreal5", "load": {"before": 0.2, "after": 0.3, "cpus": 8}})
    assert "0.20 before and 0.30 after" in quiet and "montreal5" in quiet
    assert "loaded machine" not in quiet
    assert "not measured" in bench.md_pairs([], {"machine": "x"})
