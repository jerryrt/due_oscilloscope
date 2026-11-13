"""schematic_check against the OLD check.py (frozen v1, goldens taken in the image): the same rows with the same verdicts and
details on the frozen project, and every arm failing the check it is aimed at. The comparators are tested with known answers."""
import pathlib
import re
import shutil
import types

import pytest

from pcbtools import schematic_check as sc
from pcbtools.boards import v1_frozen as v1

GOLDEN = pathlib.Path(__file__).resolve().parents[1] / 'golden' / 'v1-34b2e51-image' / 'check_pcb.out'
FIX = pathlib.Path(v1.SOURCE_DIR)

PARTS = [{'ref': 'R1', 'value': '1k', 'fp': 'R_0603', 'lcsc': 'C1', 'pins': {'1': 'A', '2': 'B'}, 'dnp': False, 'fitted_by': 'jlc'},
         {'ref': 'R2', 'value': '2k', 'fp': 'R_0603', 'lcsc': 'C2', 'pins': {'1': 'B', '2': 'GND'}, 'dnp': False, 'fitted_by': 'jlc'},
         {'ref': 'TP1', 'value': 'TP', 'fp': 'TP', 'lcsc': '', 'pins': {'1': 'A'}, 'dnp': True, 'fitted_by': 'none'}]


# ------------------------------------------------------------------------------------------------ pure comparators
def test_design_nets():
    assert sc.design_nets(PARTS) == {'A': [('R1', '1'), ('TP1', '1')], 'B': [('R1', '2'), ('R2', '1')], 'GND': [('R2', '2')]}


def test_strip_flags_drops_no_connect_nets_and_flag_symbols_and_the_slash():
    got = sc.strip_flags({'/A': [('R1', '1'), ('#FLG01', '1')], 'unconnected-(R2-Pad2)': [('R2', '2')], '/B': [('#PWR1', '1')]})
    assert got == {'A': [('R1', '1')]}


def test_compare_nets_sees_a_swap_a_rename_and_an_extra_net():
    want = {'A': [('R1', '1')], 'B': [('R1', '2'), ('R2', '1')]}
    assert sc.compare_nets(want, dict(want)) == []
    assert sc.compare_nets(want, {'A': [('R1', '1')], 'C': [('R1', '2'), ('R2', '1')]}) == ['net B is named C in KiCad']
    assert len(sc.compare_nets(want, {'A': [('R1', '2')], 'B': [('R1', '1'), ('R2', '1')]})) == 4
    assert sc.compare_nets(want, {**want, 'X': [('R9', '1')]}) == ["KiCad net X [('R9', '1')] not in the design"]


def test_compare_parts():
    comps = {'R1': dict(value='1k', footprint='R_0603', fields={'LCSC': 'C1'}), 'R2': dict(value='2k', footprint='R_0603', fields={'LCSC': 'C2'}),
             'TP1': dict(value='TP', footprint='TP', fields={})}
    assert sc.compare_parts(PARTS, comps) == []
    comps['R2']['value'] = '3k'
    comps['R1']['fields']['LCSC'] = 'C9'
    del comps['TP1']
    d = sc.compare_parts(PARTS, comps)
    assert "R2 value '3k' != '2k'" in d and "R1 LCSC 'C9' != 'C1'" in d and 'TP1 missing from the netlist' in d


def test_bom_txt_and_compare_bom(tmp_path):
    p = tmp_path / 'bom.txt'
    p.write_text('   1  100k 0603 C1234 x2\n      R1-R2   x2   (note)\n   2  mount C99 x1\n      MH601   x1\n')
    bom = sc.bom_txt(p)
    assert bom == {'R1': 'C1234', 'R2': 'C1234'}
    parts = [dict(PARTS[0], lcsc='C1234'), dict(PARTS[1], lcsc='C1234')]
    assert sc.compare_bom(parts, bom, {}) == []
    assert sc.compare_bom([dict(parts[0], lcsc='C5')] + parts[1:], bom, {}) == ['R1: design C5 != bom.txt C1234']
    assert sc.compare_bom(parts, {'R1': 'C1234'}, {}) == ['R2 (C1234) fitted but not in bom.txt']
    assert sc.compare_bom(parts, bom, {'R1': 'why'}) == ['R1 is listed as a delta but bom.txt now carries it: drop the delta']
    with pytest.raises(ValueError):
        p.write_text('   1  100k 0603 C1234 x3\n      R1-R2   x3\n')
        sc.bom_txt(p)


def test_run_arms_counts_and_an_arm_that_does_not_fail_the_check_fails_the_summary():
    rows = sc.run_arms([sc.Arm('A', 'a', lambda: True), sc.Arm('B', 'b', lambda: False)])
    assert [(r.id, r.ok) for r in rows] == [('A', True), ('B', False), ('M*', False)]
    assert rows[-1].detail == '1 of 2 mutation arms failed the check as they must'


# ------------------------------------------------------------------------------------------------ against the old check.py
def golden_rows():
    out = {}
    for line in GOLDEN.read_text().splitlines():
        m = re.match(r'^(PASS|FAIL) (S[1-4]|P[1-3]|M1|M2|M2b|M3|M4|MP[1-3]): (.*)$', line)
        if m:
            out[m[2]] = (m[1] == 'PASS', m[3])
    return out


@pytest.fixture(scope='module')
def run(tmp_path_factory):
    if not shutil.which('kicad-cli'):
        pytest.skip('no kicad-cli')
    work = tmp_path_factory.mktemp('schcheck')
    proj = work / 'project'
    shutil.copytree(FIX, proj, ignore=shutil.ignore_patterns('3d', '__pycache__', 'render', '*.kicad_prl', '~*'))
    from pcbtools import boardio
    rows, nets = sc.schematic_rows(str(proj / 'afe-proto.kicad_sch'), v1.PARTS, v1)
    path = str(proj / 'afe-proto.kicad_pcb')
    board = boardio.read_board(path)
    more, _ = sc.board_rows(board, nets, v1, drc_path=path)
    arm_rows = sc.run_arms(sc.arms(v1, nets, board, path, str(work)))
    return {r.id: r for r in rows + more + arm_rows}


@pytest.mark.pcbnew
def test_rows_equal_the_old_check_rows(run):
    g = golden_rows()
    for cid in ('S1', 'S2', 'S3', 'S4', 'P1', 'P2', 'P3'):
        assert (run[cid].ok, run[cid].detail) == g[cid], cid          # verdict AND detail, including P2's DRC counts


@pytest.mark.pcbnew
def test_every_arm_fails_the_check_it_is_aimed_at_as_in_the_old_check(run):
    g = golden_rows()
    for cid in ('M1', 'M2', 'M2b', 'M3', 'M4', 'MP1', 'MP2', 'MP3'):
        assert run[cid].ok and g[cid][0], cid
    assert run['M*'].ok


# ------------------------------------------------------------------------------------------------ R1: the committed files are what the generators make
OLD_SCH_COMMENTS = ['Generated by hardware/afe-proto/kicad/build_sch.py from design.py: edit those, not this file',
                    'Values and parts: whatif/bom.txt. Connectivity: the simulated circuit (docs/architecture.md)',
                    'Own work, CC BY-SA 4.0']
OLD_RECT = (17.0, 0.0, 117.0, 53.34)        # the frozen 34b2e51 outline: the v1 config's own outline now overhangs 5 mm south (MC-1 amended)
OLD_PCB_COMMENTS = ['Generated by hardware/afe-proto/kicad/build_pcb.py from design.py; not routed', 'Own work, CC BY-SA 4.0']


def _digest(p):
    """sha256 of a file's bytes; of a .kicad_pro, of its content WITHOUT the board-setup sections the generator now adds
    (v1.BOARD_SETUP: the design rules; the frozen old project file has none): that is the one deliberate difference"""
    import hashlib
    import json
    p = pathlib.Path(p)
    if p.name.endswith('.kicad_pro'):
        d = {k: v for k, v in json.loads(p.read_text()).items() if k not in v1.BOARD_SETUP}
        return hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _regenerate(tmp, parts):
    import subprocess
    from pcbtools import build as bd
    from pcbtools import schematic as sch
    sch.write_all(parts, v1.sch_cfg(COMMENTS=OLD_SCH_COMMENTS), str(tmp))
    s = tmp / 'afe-proto.kicad_sch'
    subprocess.run(['kicad-cli', 'sch', 'upgrade', str(s)], capture_output=True, check=True)
    out = tmp / 'afe-proto.kicad_pcb'
    bd.build_board(parts, v1.pcb_cfg(OUTLINE=OLD_RECT, KEEPOUTS=[], COMMENTS=OLD_PCB_COMMENTS), v1.pcb_place(), bd.schematic_nets(s), str(out),
                   legalise_overlaps=True, anchors=v1.ANCHORS)
    return {f: _digest(tmp / f) for f in ('afe-proto.kicad_sch', 'afe-proto.kicad_pro', 'sym-lib-table', 'fp-lib-table',
                                          'lib/afe.kicad_sym', 'afe-proto.kicad_pcb')}


def test_the_generated_project_carries_the_board_setup(tmp_path):
    """the design rules (0.45 mm copper-to-edge, net class 0.2 / 0.2 / via 0.6 / 0.3) are in the generator's data and reach the project
    file; remove them from the config and the section is gone"""
    import json
    from pcbtools import schematic as sch
    if not __import__('os').path.isdir(v1.SYMBOL_DIR):
        pytest.skip('no KiCad symbol libraries')
    sch.write_all(v1.PARTS, v1.sch_cfg(), str(tmp_path))
    d = json.loads((tmp_path / 'afe-proto.kicad_pro').read_text())
    assert d['board']['design_settings']['rules']['min_copper_edge_clearance'] == 0.45
    cls = d['net_settings']['classes'][0]
    assert (cls['track_width'], cls['clearance'], cls['via_diameter'], cls['via_drill']) == (0.2, 0.2, 0.6, 0.3)
    (tmp_path / 'b').mkdir()
    sch.write_all(v1.PARTS, v1.sch_cfg(BOARD_SETUP=None), str(tmp_path / 'b'))
    assert 'board' not in json.loads((tmp_path / 'b' / 'afe-proto.kicad_pro').read_text())


@pytest.mark.pcbnew
def test_r1_the_committed_project_regenerates_byte_for_byte_and_one_changed_value_shows(tmp_path):
    if not shutil.which('kicad-cli'):
        pytest.skip('no kicad-cli')
    import copy
    have = {f: _digest(FIX / f) for f in ('afe-proto.kicad_sch', 'afe-proto.kicad_pro', 'sym-lib-table', 'fp-lib-table',
                                          'lib/afe.kicad_sym', 'afe-proto.kicad_pcb')}
    (tmp_path / 'a').mkdir(); (tmp_path / 'b').mkdir()
    assert _regenerate(tmp_path / 'a', v1.PARTS) == have                                   # R1
    parts = copy.deepcopy(v1.PARTS)
    next(p for p in parts if p['value'] == '22 1%')['value'] = '22R 1%'
    assert _regenerate(tmp_path / 'b', parts) != have                                       # MR1: the arm
