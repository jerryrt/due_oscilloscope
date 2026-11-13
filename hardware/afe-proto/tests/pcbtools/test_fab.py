"""The JLC fabrication set (pcbtools/fab.py, v2/layout/fab/build_fab.sh): every member present, the outline equals the config's, the drill files
equal the holes counted independently from the board text, and a fresh build equals the committed manifest. Each check is also run on a
mutant and must fail: a member removed, an outline coordinate moved, one drill hit dropped, a board whose via has another size."""
import hashlib, json, pathlib, re, shutil, sys, zipfile

import pytest

AFE = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(AFE))
from pcbtools import fab
from pcbtools.boards import v2_layout as L

BOARD = AFE / 'v2/layout/integrated/afe-v2-integrated.kicad_pcb'
MANIFEST = AFE / 'v2/layout/fab/manifest.json'
W, H = round(L.BOARD_RECT[2] - L.BOARD_RECT[0], 4), round(L.BOARD_RECT[3] - L.BOARD_RECT[1], 4)
pytestmark = pytest.mark.skipif(not shutil.which('kicad-cli'), reason='needs kicad-cli (the PCB image)')


@pytest.fixture(scope='module')
def built(tmp_path_factory):
    d = tmp_path_factory.mktemp('fab')
    zp = fab.build(str(BOARD), str(d), str(AFE / f'v2/bom/{fab.IDENT}-bom.csv'), str(AFE / f'v2/bom/{fab.IDENT}-cpl.csv'))
    return zp, d


def text(zp, key):
    return zipfile.ZipFile(zp).read(f'{fab.IDENT}-{key}').decode()


def test_the_zip_has_every_expected_member_and_nothing_else(built):
    assert fab.check_members(zipfile.ZipFile(built[0]).namelist()) == []
    assert len(fab.expected_members()) == 12


def test_the_outline_is_the_configured_size(built):
    assert (W, H) == (100.0, 62.34)
    assert fab.check_outline(text(built[0], 'Edge_Cuts.gm1'), W, H) == []


def test_the_drills_equal_the_holes_of_the_board_file(built):
    assert fab.check_drills(text(built[0], 'PTH.drl'), text(built[0], 'NPTH.drl'), BOARD.read_text()) == []
    pth, npth = fab.board_holes(BOARD.read_text())
    assert sum(pth.values()) == 144 and sum(npth.values()) == 2


def test_a_fresh_build_equals_the_committed_manifest_and_a_second_build_is_identical(built, tmp_path):
    zp2 = fab.build(str(BOARD), str(tmp_path), str(AFE / f'v2/bom/{fab.IDENT}-bom.csv'), str(AFE / f'v2/bom/{fab.IDENT}-cpl.csv'))
    assert open(zp2, 'rb').read() == open(built[0], 'rb').read()
    assert fab.manifest(built[0]) == json.loads(MANIFEST.read_text())


# ------------------------------------------------------------------------------------ break each check on purpose
def test_a_missing_member_is_caught(built):
    assert fab.check_members([n for n in zipfile.ZipFile(built[0]).namelist() if not n.endswith('F_Paste.gtp')]) == [f'missing {fab.IDENT}-F_Paste.gtp']


def test_a_moved_outline_coordinate_is_caught(built):
    t = text(built[0], 'Edge_Cuts.gm1')
    xs = re.findall(r'^X(\d+)Y', t, re.M)
    bad = t.replace('X' + max(xs, key=int) + 'Y', 'X' + str(int(max(xs, key=int)) + 500000) + 'Y', 1)
    assert fab.check_outline(bad, W, H)


def test_a_dropped_drill_hit_is_caught(built):
    pth = text(built[0], 'PTH.drl')
    lines = pth.splitlines()
    i = max(k for k, l in enumerate(lines) if re.match(r'^X-?[\d.]+Y-?[\d.]+$', l))
    del lines[i]
    assert fab.check_drills('\n'.join(lines), text(built[0], 'NPTH.drl'), BOARD.read_text())


def test_a_changed_board_hole_is_caught(built):
    b = BOARD.read_text().replace('(drill 0.3)', '(drill 0.4)', 1)
    assert fab.check_drills(text(built[0], 'PTH.drl'), text(built[0], 'NPTH.drl'), b)
