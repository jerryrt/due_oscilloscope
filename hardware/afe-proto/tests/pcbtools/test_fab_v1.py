"""Version 1's JLC fabrication set (pcbtools/fab.py --design v1, kicad/fab/build_fab.sh): the same engine and the same checks as version 2's test_fab.py:
every member present and named from the configuration, the outline equals the configured size, the drill files equal the holes counted independently
from the board text, the BOM and CPL list exactly the board's JLC-assembled footprints, bom.md and the order file count the same placements and joints,
and a fresh build equals the committed manifest. Each check is also broken once on purpose and must fail.

pcbnew-free but needs kicad-cli (the PCB image)."""
import csv, json, pathlib, re, shutil, sys, zipfile

import pytest

AFE = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(AFE))
from pcbtools import fab
from pcbtools.boards import v1 as L

IDENT, STEM, BOMDIR = fab.design_ident('v1')
BOARD = AFE / 'kicad/afe-proto.kicad_pcb'
MANIFEST = AFE / 'kicad/fab/manifest.json'
BOM = AFE / 'bom/v1' / f'{IDENT}-bom.csv'
CPL = AFE / 'bom/v1' / f'{IDENT}-cpl.csv'
W, H = round(L.BOARD_RECT[2] - L.BOARD_RECT[0], 4), round(L.BOARD_RECT[3] - L.BOARD_RECT[1], 4)
needs_cli = pytest.mark.skipif(not shutil.which('kicad-cli'), reason='needs kicad-cli (the PCB image)')


@pytest.fixture(scope='module')
def built(tmp_path_factory):
    if not shutil.which('kicad-cli'):
        pytest.skip('needs kicad-cli (the PCB image)')
    d = tmp_path_factory.mktemp('fab1')
    return fab.build(str(BOARD), str(d), str(BOM), str(CPL), IDENT, STEM), d


def text(zp, key):
    return zipfile.ZipFile(zp).read(f'{IDENT}-{key}').decode()


def test_the_names_come_from_the_configuration():
    assert IDENT == f'{L.NAME}-{L.MODEL}-REV{L.REV}' == 'COPPIA-AFE-1-REVA' == L.FILE_STEM
    assert fab.expected_members(IDENT)[0].startswith('COPPIA-AFE-1-REVA-') and len(fab.expected_members(IDENT)) == 12


@needs_cli
def test_the_zip_has_every_expected_member_and_nothing_else(built):
    assert fab.check_members(zipfile.ZipFile(built[0]).namelist(), IDENT) == []
    assert pathlib.Path(built[0]).name == f'{IDENT}-fab.zip'


@needs_cli
def test_the_outline_round_trips_at_the_configured_size(built):
    assert (W, H) == (100.0, 62.34)
    assert fab.check_outline(text(built[0], 'Edge_Cuts.gm1'), W, H) == []


@needs_cli
def test_the_drills_equal_the_holes_of_the_board_file(built):
    assert fab.check_drills(text(built[0], 'PTH.drl'), text(built[0], 'NPTH.drl'), BOARD.read_text()) == []
    pth, npth = fab.board_holes(BOARD.read_text())
    assert pth == {(0.3, 'round'): 59, (1.0, 'round'): 95, (2.2, 'round'): 6} and npth == {(2.7, 'round'): 2}     # written down, counted by hand from the board


def _jlc_refs(board_text):
    """the designators the board marks `Fitted by JLC` and not DNP, counted from its text with no code of the engine"""
    out = []
    for blk in re.split(r'\n\t\(footprint ', board_text)[1:]:
        ref = re.search(r'\(property "Reference" "([^"]*)"', blk).group(1)
        fitted = re.search(r'\(property "Fitted by" "([^"]*)"', blk)
        attr = re.search(r'\(attr ([^)]*)\)', blk)
        if fitted and fitted.group(1) == 'JLC' and 'dnp' not in (attr.group(1).split() if attr else []):
            out.append(ref)
    return sorted(out)


def test_the_bom_and_cpl_list_exactly_the_jlc_footprints_of_the_board():
    want = _jlc_refs(BOARD.read_text())
    assert len(want) == 99
    bom_refs = sorted(r for row in list(csv.reader(open(BOM, newline='')))[1:] for r in row[1].split(','))
    cpl_rows = list(csv.reader(open(CPL, newline='')))
    assert bom_refs == want and sorted(r[0] for r in cpl_rows[1:]) == want
    assert all(r[3] in ('Top', 'Bottom') for r in cpl_rows[1:]) and len(cpl_rows[0]) == 5


def test_bom_md_and_the_order_file_count_the_same_placements_and_joints():
    pat = r'\| JLC placements / SMT joints per board \| (\d+) / (\d+) \|'
    a = re.search(pat, (AFE / 'bom/v1/bom.md').read_text())
    b = re.search(pat, (AFE / 'bom/v1/order-5-100.md').read_text())
    assert a and b and a.groups() == b.groups() == ('99', '234')
    assert len(_jlc_refs(BOARD.read_text())) == int(a.group(1))


@needs_cli
def test_a_fresh_build_equals_the_committed_manifest_and_a_second_build_is_identical(built, tmp_path):
    zp2 = fab.build(str(BOARD), str(tmp_path), str(BOM), str(CPL), IDENT, STEM)
    assert open(zp2, 'rb').read() == open(built[0], 'rb').read()
    assert fab.manifest(built[0]) == json.loads(MANIFEST.read_text())


# ------------------------------------------------------------------------------------ break each check on purpose
@needs_cli
def test_a_missing_member_is_caught(built):
    assert fab.check_members([n for n in zipfile.ZipFile(built[0]).namelist() if not n.endswith('F_Paste.gtp')], IDENT) == [f'missing {IDENT}-F_Paste.gtp']


@needs_cli
def test_a_moved_outline_coordinate_is_caught(built):
    t = text(built[0], 'Edge_Cuts.gm1')
    xs = re.findall(r'^X(\d+)Y', t, re.M)
    assert fab.check_outline(t.replace('X' + max(xs, key=int) + 'Y', 'X' + str(int(max(xs, key=int)) + 500000) + 'Y', 1), W, H)


@needs_cli
def test_a_dropped_drill_hit_is_caught(built):
    lines = text(built[0], 'PTH.drl').splitlines()
    del lines[max(k for k, l in enumerate(lines) if re.match(r'^X-?[\d.]+Y-?[\d.]+$', l))]
    assert fab.check_drills('\n'.join(lines), text(built[0], 'NPTH.drl'), BOARD.read_text())


def test_a_bom_that_lost_a_part_is_caught():
    want = _jlc_refs(BOARD.read_text())
    rows = list(csv.reader(open(BOM, newline='')))[1:]
    rows[0][1] = ','.join(rows[0][1].split(',')[1:])                     # one designator dropped from the first line
    assert sorted(r for row in rows for r in row[1].split(',') if r) != want


def test_the_count_check_fails_when_the_order_file_disagrees():
    pat = r'\| JLC placements / SMT joints per board \| (\d+) / (\d+) \|'
    txt = (AFE / 'bom/v1/order-5-100.md').read_text().replace('99 / 234', '98 / 234')
    assert re.search(pat, txt).groups() != re.search(pat, (AFE / 'bom/v1/bom.md').read_text()).groups()
