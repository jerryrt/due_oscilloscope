"""Every 3D model each board names (v2 and v1) is a file that resolves, and U401's is the project's own stand-in (KiCad 10 ships none for the LM27762's
WSON-12, so the library's link dangled and the part rendered without a body). ${KIPRJMOD} is the board's folder, KICAD10_3DMODEL_DIR the
image's 3D library (default /usr/share/kicad/3dmodels). Nothing is allowlisted: the three BNCs name KiCad's Amphenol B6252HB model.
Pure text on the board file. Broken once on purpose, as the suite requires."""
import os
import pathlib
import re

import pytest

from pcbtools.boards import v1 as CFG1
from pcbtools.boards import v2_layout as CFG2

P = pathlib.Path(__file__).resolve().parents[2]
BOARDS = {'v2': P / 'v2' / 'layout' / 'integrated' / 'afe-v2-integrated.kicad_pcb', 'v1': P / 'kicad' / 'afe-proto.kicad_pcb'}
CFGS = {'v1': CFG1, 'v2': CFG2}
DESIGNS = sorted(BOARDS)
MODEL_DIR = pathlib.Path(os.environ.get('KICAD10_3DMODEL_DIR', '/usr/share/kicad/3dmodels'))
MODEL = re.compile(r'\n\t\t\(model "([^"]+)"')


def expand(path, board):
    return pathlib.Path(path.replace('${KIPRJMOD}', str(board.parent)).replace('${KICAD10_3DMODEL_DIR}', str(MODEL_DIR)))


def unresolved(text, board):
    """[model path as written] whose file is not there; a path through ${KICAD10_3DMODEL_DIR} needs the library to exist at all"""
    refs = MODEL.findall(text)
    assert len(refs) >= 100, f'{len(refs)} model entries: the scan moved'                 # a floor: the board's parts, not an empty list
    unknown = sorted({r for r in refs if '${' in r and not r.startswith(('${KIPRJMOD}', '${KICAD10_3DMODEL_DIR}'))})
    assert not unknown, f'an unknown variable in {unknown}'
    if any(r.startswith('${KICAD10_3DMODEL_DIR}') for r in refs) and not MODEL_DIR.is_dir():
        pytest.skip(f'no 3D library at {MODEL_DIR} (set KICAD10_3DMODEL_DIR; the PCB image has it)')
    return sorted({r for r in refs if not expand(r, board).is_file()})


def _set_models():
    import sys
    sys.path.insert(0, str(P / 'v2' / 'layout'))
    import set_models as S
    return S


@pytest.mark.parametrize('design', DESIGNS)
def test_every_model_path_on_the_board_resolves_to_a_file(design):
    assert unresolved(BOARDS[design].read_text(), BOARDS[design]) == []


@pytest.mark.parametrize('design', DESIGNS)
def test_u401_uses_the_projects_standin_from_the_config(design):
    board = BOARDS[design]
    text = board.read_text()
    (path,) = CFGS[design].MODEL_BY_REF.values()
    assert expand(path, board).is_file() and expand(path, board).suffix == '.wrl'
    assert path in MODEL.findall(text)
    assert 'Package_SON.3dshapes/WSON-12-1EP' not in text          # the dangling library link is gone


@pytest.mark.parametrize('design', DESIGNS)
def test_broken_once_u401_pointed_at_a_missing_file_is_caught(design):
    board = BOARDS[design]
    bad, changed = _set_models().set_models(board.read_text(), {'U401': '${KIPRJMOD}/lib/afe.3dshapes/not-there.wrl'})
    assert changed == ['U401']
    assert unresolved(bad, board) == ['${KIPRJMOD}/lib/afe.3dshapes/not-there.wrl']


@pytest.mark.parametrize('design', DESIGNS)
def test_setting_the_models_again_changes_nothing(design):
    text = BOARDS[design].read_text()
    assert _set_models().set_models(text, CFGS[design].MODEL_BY_REF) == (text, [])
