"""A gate-3 render set shows every footprint that has a 3D model WITH its model.

The committed 3D renders of both boards showed U401 as bare pads: its model is the project's own stand-in (`${KIPRJMOD}/lib/afe.3dshapes/...`, v2's
`${KIPRJMOD}/../../../kicad/lib/...`), and the renders had been made from a copy of the board in a scratch directory, where `${KIPRJMOD}` points at nothing. kicad-cli
renders a footprint whose model it cannot find as its pads alone, says nothing, and exits 0. Every other model is in the image's stock library (`${KICAD10_3DMODEL_DIR}`).

What this holds, for each of the two gate-3 packages' boards (v1 kicad/, v2 v2/layout/integrated/):
  * text, no pcbnew: every footprint that names a model has one, the board's footprints with a model are counted (a floor), every `${KIPRJMOD}` model file is there
    beside the board's project, and the render folder's renders.sha256.json (written by render.sh, last, through pcbkit.render's check) records the same number of
    models checked, none missing and none unresolved;
  * pcbnew (the image): pcbkit.render.check_models, the guard the renders went through, finds nothing missing and nothing unresolved from the board's own directory;
  * the render scripts render the 3D views through pcbkit.render and never call `kicad-cli pcb render` themselves, which has no guard.
Broken on purpose: moving kicad/lib away fails the text and pcbnew tests naming U401 (the record is in the commit that added this); the checks below are each fired on
a synthetic board or manifest that has the defect."""
import json
import os
import pathlib
import re

import pytest

from pcbtools import sexpr

AFE = pathlib.Path(__file__).resolve().parents[2]
SETS = {'v1': (AFE / 'kicad' / 'afe-proto.kicad_pcb', AFE / 'kicad' / 'render', AFE / 'kicad' / 'render.sh'),
        'v2': (AFE / 'v2' / 'layout' / 'integrated' / 'afe-v2-integrated.kicad_pcb', AFE / 'v2' / 'layout' / 'integrated' / 'render', AFE / 'v2' / 'layout' / 'render.sh')}
STOCK = '/usr/share/kicad/3dmodels'
FLOOR = 90                       # footprints with a model, on either board (v1 111 models, v2 102): the scan must have looked at the board


def footprint_models(text):
    """[(reference, model file)] of every `(model ...)` of every footprint of a .kicad_pcb's text; and the references of the footprints that name none"""
    tree = sexpr.parse(text)
    models, bare = [], []
    for fp in tree:
        if not (isinstance(fp, list) and fp and fp[0] == 'footprint'):
            continue
        ref = next((c[2] for c in fp if isinstance(c, list) and len(c) > 2 and c[0] == 'property' and c[1] == 'Reference'), '?')
        ms = [str(c[1]) for c in fp if isinstance(c, list) and c and c[0] == 'model']
        models += [(ref, m) for m in ms]
        if not ms:
            bare.append(ref)
    return models, bare


def project_models_missing(models, project_dir):
    """the `${KIPRJMOD}` models whose file is not there, from the project's directory"""
    return [(r, f) for r, f in models if f.startswith('${KIPRJMOD}') and not os.path.isfile(os.path.normpath(f.replace('${KIPRJMOD}', str(project_dir))))]


def manifest_problems(manifest, n_models):
    """what is wrong with the model record of a render folder's manifest, against the board's own model count"""
    m = manifest.get('models')
    if m is None:
        return ['renders.sha256.json records no models: render.sh did not write it']
    out = []
    if m.get('checked') != n_models:
        out.append(f'models checked {m.get("checked")}, the board has {n_models}')
    if m.get('missing'):
        out.append(f'models missing at render time: {m["missing"]}')
    if m.get('unresolved'):
        out.append(f'models unresolved at render time: {m["unresolved"]}')
    return out


@pytest.mark.parametrize('name', sorted(SETS))
def test_every_model_file_is_there_beside_the_board_and_the_render_recorded_it(name):
    board, render, _ = SETS[name]
    models, bare = footprint_models(board.read_text())
    assert len(models) >= FLOOR, f'{len(models)} models: the scan must have found the board\'s'
    assert project_models_missing(models, board.parent) == [], 'a model file is missing from the board\'s project directory; a render made now shows the part bare'
    assert any(f.startswith('${KIPRJMOD}') for _, f in models), 'no project model examined: this check would look at nothing for U401'
    assert manifest_problems(json.loads((render / 'renders.sha256.json').read_text()), len(models)) == []


@pytest.mark.pcbnew
@pytest.mark.parametrize('name', sorted(SETS))
def test_the_guard_finds_every_model_from_the_boards_own_directory(name, pcbnew_required, monkeypatch):
    from pcbkit import render
    monkeypatch.setenv('KICAD10_3DMODEL_DIR', os.environ.get('KICAD10_3DMODEL_DIR') or STOCK)
    board = SETS[name][0]
    n, missing, unresolved = render.check_models(str(board))
    assert n == len(footprint_models(board.read_text())[0]) >= FLOOR
    assert missing == [] and unresolved == []


@pytest.mark.parametrize('name', sorted(SETS))
def test_the_render_script_renders_3d_through_the_guard(name):
    text = SETS[name][2].read_text()
    assert 'kicad-cli pcb render' not in text and text.count('python3 -m pcbkit.render') == 2        # top and bottom, both guarded, neither a raw kicad-cli


BOARD = '''(kicad_pcb (footprint "R" (property "Reference" "R1" (at 0 0)) (model "${KIPRJMOD}/lib/a.step" (offset (xyz 0 0 0))))
 (footprint "U" (property "Reference" "U1" (at 0 0)) (model "${KICAD10_3DMODEL_DIR}/x.step") (model "${KIPRJMOD}/lib/b.wrl"))
 (footprint "TP" (property "Reference" "TP1" (at 0 0))))'''


def test_the_checks_fire_on_a_board_and_a_manifest_that_have_the_defect(tmp_path):
    models, bare = footprint_models(BOARD)
    assert models == [('R1', '${KIPRJMOD}/lib/a.step'), ('U1', '${KICAD10_3DMODEL_DIR}/x.step'), ('U1', '${KIPRJMOD}/lib/b.wrl')] and bare == ['TP1']
    assert project_models_missing(models, tmp_path) == [('R1', '${KIPRJMOD}/lib/a.step'), ('U1', '${KIPRJMOD}/lib/b.wrl')]     # no lib/ beside this board
    (tmp_path / 'lib').mkdir()
    (tmp_path / 'lib' / 'a.step').write_text('x')
    assert project_models_missing(models, tmp_path) == [('U1', '${KIPRJMOD}/lib/b.wrl')]                                        # one of two present: the other is named
    (tmp_path / 'lib' / 'b.wrl').write_text('x')
    assert project_models_missing(models, tmp_path) == []
    good = dict(models=dict(checked=3, missing=[], unresolved=[]))
    assert manifest_problems(good, 3) == []
    assert manifest_problems(dict(models=dict(checked=3, missing=[['U1', 'f']], unresolved=[])), 3)
    assert manifest_problems(dict(models=dict(checked=3, missing=[], unresolved=[['U1', 'f']])), 3)
    assert manifest_problems(good, 4) and manifest_problems({}, 3)                                                             # a count that differs, a manifest with no record
