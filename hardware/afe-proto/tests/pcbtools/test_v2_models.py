"""Every 3D model the v2 board names is a file that resolves, and U401's is the project's own stand-in (KiCad 10 ships none for the LM27762's
WSON-12, so the library's link dangled and the part rendered without a body). ${KIPRJMOD} is the board's folder, KICAD10_3DMODEL_DIR the
image's 3D library (default /usr/share/kicad/3dmodels). Nothing is allowlisted: the three BNCs name KiCad's Amphenol B6252HB model.
Pure text on the board file. Broken once on purpose, as the suite requires."""
import os
import pathlib
import re

import pytest

from pcbtools.boards import v2_layout as CFG

BOARD = pathlib.Path(__file__).resolve().parents[2] / 'v2' / 'layout' / 'integrated' / 'afe-v2-integrated.kicad_pcb'
MODEL_DIR = pathlib.Path(os.environ.get('KICAD10_3DMODEL_DIR', '/usr/share/kicad/3dmodels'))
MODEL = re.compile(r'\n\t\t\(model "([^"]+)"')


def expand(path, board=BOARD):
    return pathlib.Path(path.replace('${KIPRJMOD}', str(board.parent)).replace('${KICAD10_3DMODEL_DIR}', str(MODEL_DIR)))


def unresolved(text, board=BOARD):
    """[model path as written] whose file is not there; a path through ${KICAD10_3DMODEL_DIR} needs the library to exist at all"""
    refs = MODEL.findall(text)
    assert len(refs) >= 100, f'{len(refs)} model entries: the scan moved'                 # a floor: the board's parts, not an empty list
    unknown = sorted({r for r in refs if '${' in r and not r.startswith(('${KIPRJMOD}', '${KICAD10_3DMODEL_DIR}'))})
    assert not unknown, f'an unknown variable in {unknown}'
    if any(r.startswith('${KICAD10_3DMODEL_DIR}') for r in refs) and not MODEL_DIR.is_dir():
        pytest.skip(f'no 3D library at {MODEL_DIR} (set KICAD10_3DMODEL_DIR; the PCB image has it)')
    return sorted({r for r in refs if not expand(r, board).is_file()})


def test_every_model_path_on_the_board_resolves_to_a_file():
    assert unresolved(BOARD.read_text()) == []


def test_u401_uses_the_projects_standin_from_the_config():
    text = BOARD.read_text()
    (path,) = CFG.MODEL_BY_REF.values()
    assert expand(path).is_file() and expand(path).suffix == '.wrl'
    assert path in MODEL.findall(text)
    assert 'Package_SON.3dshapes/WSON-12-1EP' not in text          # the dangling library link is gone


def test_broken_once_u401_pointed_at_a_missing_file_is_caught():
    import sys
    sys.path.insert(0, str(BOARD.parents[1]))
    import set_models as S
    bad, changed = S.set_models(BOARD.read_text(), {'U401': '${KIPRJMOD}/../../../kicad/lib/afe.3dshapes/not-there.wrl'})
    assert changed == ['U401']
    got = unresolved(bad)
    print(got)
    assert got == ['${KIPRJMOD}/../../../kicad/lib/afe.3dshapes/not-there.wrl']


def test_setting_the_models_again_changes_nothing():
    import sys
    sys.path.insert(0, str(BOARD.parents[1]))
    import set_models as S
    text = BOARD.read_text()
    assert S.set_models(text) == (text, [])
