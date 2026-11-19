"""The stored pour of a committed board is the pour KiCad fills with the board's own project file beside it (pcbtools.fillcheck), and fill_clean will not fill without that project.

Broken on purpose: a board stored from a fill at other rules fails the check (here the project of a copy is changed to the edge clearance KiCad uses by default, 0.5 mm against the project's 0.45); a missing project file stops both tools and names the file; the verdict needs both the outline and the area to match."""
import json
import pathlib
import shutil
import subprocess
import sys

import pytest

AFE = pathlib.Path(__file__).resolve().parents[2]
BOARDS = {'AFE-1': AFE / 'kicad' / 'afe-proto.kicad_pcb', 'AFE-2': AFE / 'v2' / 'layout' / 'integrated' / 'afe-v2-integrated.kicad_pcb'}

pytestmark = pytest.mark.pcbnew


def _copy(board, d, pro=True):
    dst = d / board.name
    shutil.copyfile(board, dst)
    if pro:
        shutil.copyfile(board.with_suffix('.kicad_pro'), dst.with_suffix('.kicad_pro'))
    return dst


@pytest.mark.parametrize('name', sorted(BOARDS))
def test_the_stored_pour_is_what_kicad_fills_with_the_project(pcbnew_required, name, tmp_path):
    from pcbtools import fillcheck
    rows = fillcheck.compare(_copy(BOARDS[name], tmp_path))
    assert rows and fillcheck.ok(rows), rows
    assert [r[0] for r in rows] == ['F', 'B']


def test_a_fill_made_at_other_rules_fails_the_check(pcbnew_required, tmp_path):
    from pcbtools import fillcheck
    b = _copy(BOARDS['AFE-1'], tmp_path)
    pro = b.with_suffix('.kicad_pro')
    p = json.loads(pro.read_text())
    assert p['board']['design_settings']['rules']['min_copper_edge_clearance'] == 0.45
    p['board']['design_settings']['rules']['min_copper_edge_clearance'] = 0.5              # KiCad's default: what a fill without the project used
    pro.write_text(json.dumps(p, indent=2))
    rows = fillcheck.compare(b)
    assert not fillcheck.ok(rows), rows
    assert [(n, x > 1.0 and abs(s - r) > 0.1) for n, s, r, x in rows if n == 'B'] == [('B', True)], rows            # the plane runs to the edge; the top rectangles stop 0.5 mm short of it and barely move


def test_without_the_project_file_both_tools_stop_and_name_it(pcbnew_required, tmp_path):
    from pcbtools import fillcheck
    b = _copy(BOARDS['AFE-1'], tmp_path, pro=False)
    with pytest.raises(fillcheck.ProjectMissing):
        fillcheck.compare(b)
    r = subprocess.run([sys.executable, '-m', 'pcbtools.fillcheck', str(b)], cwd=AFE, capture_output=True, text=True)
    assert r.returncode == 2 and str(b.with_suffix('.kicad_pro')) in r.stdout
    out = tmp_path / 'out.kicad_pcb'
    r = subprocess.run([sys.executable, '-m', 'pcbtools.fill_clean', str(b), str(out), '--reference', str(b)], cwd=AFE, capture_output=True, text=True)
    assert r.returncode != 0 and str(b.with_suffix('.kicad_pro')) in (r.stderr + r.stdout) and not out.exists()


def test_the_verdict_needs_both_the_outline_and_the_area_to_match():
    from pcbtools import fillcheck
    assert fillcheck.ok([('F', 1000.0, 1000.0000005, 0.0), ('B', 1200.0, 1200.0, 0.0)])
    assert not fillcheck.ok([('F', 1000.0, 1000.0, 0.01)])                 # same length, other area
    assert not fillcheck.ok([('F', 1000.0, 1000.001, 0.0)])                # same area, other length
    assert not fillcheck.ok([('F', 1000.0, 1000.0, 0.0), ('B', 1200.0, 1201.0, 0.0)])
