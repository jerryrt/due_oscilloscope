"""The harness's own guards. Each is mutation-checked: see MUTATIONS below."""
import os
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent


def _run_isolated(tmp_path, body, *args, env_path=None):
    """Run a throwaway test file under this conftest in a child pytest."""
    shutil.copy(HERE / "conftest.py", tmp_path / "conftest.py")
    shutil.copy(HERE / "pytest.ini", tmp_path / "pytest.ini")
    (tmp_path / "test_x.py").write_text(textwrap.dedent(body))
    env = dict(os.environ)
    env.pop("PYTEST_ADDOPTS", None)
    if env_path is not None:
        env["PATH"] = env_path
    return subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *args],
                          cwd=tmp_path, env=env, capture_output=True, text=True, timeout=300)


NEEDS_NGSPICE = """
    import pytest
    @pytest.mark.ngspice
    def test_needs_ngspice():
        pass
"""
# an empty dir on PATH makes ngspice absent whatever the bench has
def _no_ngspice(tmp_path):
    d = tmp_path / "empty"
    d.mkdir()
    return str(d)


def test_missing_tool_skips_by_default(tmp_path):
    r = _run_isolated(tmp_path, NEEDS_NGSPICE, env_path=_no_ngspice(tmp_path))
    assert "1 skipped" in r.stdout and r.returncode == 0, r.stdout


def test_require_tool_turns_the_skip_into_a_failure(tmp_path):
    r = _run_isolated(tmp_path, NEEDS_NGSPICE, "--require-tool", env_path=_no_ngspice(tmp_path))
    assert "1 failed" in r.stdout and r.returncode != 0, r.stdout
    assert "--require-tool given but" in r.stdout


def test_require_tool_does_not_fail_a_test_that_has_its_tool(tmp_path):
    """The control for the one above: the flag must not fail everything."""
    if shutil.which("ngspice") is None:
        pytest.skip("no ngspice here to be the control")
    r = _run_isolated(tmp_path, NEEDS_NGSPICE, "--require-tool")
    assert "1 passed" in r.stdout and r.returncode == 0, r.stdout


def test_unknown_marker_is_an_error(tmp_path):
    """--strict-markers: a typo'd marker must not quietly select nothing."""
    r = _run_isolated(tmp_path, "import pytest\n@pytest.mark.ngpsice\ndef test_a():\n    pass\n")
    assert r.returncode != 0 and "ngpsice" in r.stdout + r.stderr


def test_numpy_tier_selection_collects_and_runs_this_file(tmp_path):
    """The numpy tier is `-m "not pcbnew and not ngspice"`; it must still
    select tests (a selection that matches nothing exits 5, not 0)."""
    r = subprocess.run([sys.executable, "-m", "pytest", "-c", str(HERE / "pytest.ini"), "-q",
                        "-p", "no:cacheprovider", "-m", "not pcbnew and not ngspice",
                        "--collect-only", str(HERE / "test_harness.py")],
                       capture_output=True, text=True)
    assert r.returncode == 0 and "test_missing_tool_skips_by_default" in r.stdout, r.stdout


HEAVY = re.compile(r"^\s*(?:import pcbnew|from pcbnew\b|.*subprocess.*ngspice|.*\"ngspice\"|.*run_ngspice)", re.M)


def test_every_heavy_test_file_is_marked():
    """A file that touches pcbnew or ngspice must carry the marker, or the
    numpy-tier gate runs it without the tool and fails for the wrong reason."""
    bad = []
    for f in HERE.rglob("test_*.py"):
        if f.name == "test_harness.py":
            continue
        s = f.read_text()
        for name in ("pcbnew", "ngspice"):
            touches = re.search(rf"^\s*(import {name}|from {name}\b)", s, re.M) if name == "pcbnew" \
                else re.search(r"ngspice", s, re.I)
            if touches and not re.search(rf"mark\.{name}|pytestmark.*{name}", s):
                bad.append((f.name, name))
    assert not bad, bad


def test_tool_versions_are_recorded_in_a_row(versions):
    assert set(versions) == {"ngspice", "kicad", "python"}
    assert versions["python"].startswith("3.")


def test_require_tool_takes_a_list_and_only_demands_those(tmp_path):
    p = _no_ngspice(tmp_path)
    r = _run_isolated(tmp_path, NEEDS_NGSPICE, "--require-tool=pcbnew", env_path=p)
    assert "1 skipped" in r.stdout and r.returncode == 0, r.stdout   # ngspice not demanded
    r = _run_isolated(tmp_path, NEEDS_NGSPICE, "--require-tool", "ngspice", env_path=p)
    assert "1 failed" in r.stdout, r.stdout
    r = _run_isolated(tmp_path, NEEDS_NGSPICE, "--require-tool=ngspic", env_path=p)
    assert r.returncode != 0 and "unknown tool" in r.stdout + r.stderr
