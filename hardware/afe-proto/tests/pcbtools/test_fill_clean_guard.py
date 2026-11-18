"""pcbtools.fill_clean's pour-gap guard: it will not run without a named reference, and its reference is the board of record, not the input's stale fill.
Broken on purpose: removing the refusal lets the bare invocation run (this test then fails on the exit status)."""
import pathlib
import subprocess
import sys

import pytest

AFE = pathlib.Path(__file__).resolve().parents[2]


@pytest.mark.pcbnew
def test_fill_clean_stops_before_doing_anything_without_a_reference(pcbnew_required, tmp_path):
    src = tmp_path / 'x.kicad_pcb'
    src.write_text('(kicad_pcb)')
    r = subprocess.run([sys.executable, '-m', 'pcbtools.fill_clean', str(src), str(tmp_path / 'y.kicad_pcb')], cwd=AFE, capture_output=True, text=True)
    assert r.returncode != 0 and 'name the board whose pour gaps' in (r.stderr + r.stdout)
    assert not (tmp_path / 'y.kicad_pcb').exists()
