"""The v2 schematic tools, ported onto pcbtools (schematic.py, schematic_rows.py, spicecmp.py, boards/v2_sch.py, boards/v2_checks.py).

Three tiers:
  pure       no kicad-cli: the comparators with known answers on synthetic parts lists, every v2 row on the real design (built from
             the part list the way KiCad's netlist would hold it), every arm's mutation made to FLIP its row, and each arm broken once
             on purpose (the row forced to pass: the arm must then not be caught). Also the NOT TESTABLE rule.
  pcbnew     kicad-cli: the generator is byte-identical to the old build_sch.py, and the rows on the frozen committed project equal the
             old check.py's golden rows, verdict AND text.
  slow       the 24 mutation arms through KiCad, equal to the old golden's arm rows, text included.

The frozen inputs (tests/fixtures/v2-kicad-276a116) hold the OLD tools and the project they were run on; the goldens
(tests/golden/v2-kicad-276a116) hold what the old check.py printed in the image.
"""
import copy
import filecmp
import hashlib
import os
import pathlib
import re
import shutil
import subprocess
import types

import pytest

import sch_synth
from pcbtools import schematic as sch
from pcbtools import schematic_rows as sr
from pcbtools import spicecmp
from pcbtools.boards import v2_checks as v2
from pcbtools.boards import v2_sch
from pcbtools.schematic_check import Row

TESTS = pathlib.Path(__file__).resolve().parents[1]
FIX = TESTS / 'fixtures' / 'v2-kicad-276a116'
GOLD = TESTS / 'golden' / 'v2-kicad-276a116'
SIM = FIX / 'sim'
HAVE_CLI = bool(shutil.which('kicad-cli'))
SYMDIR = os.environ.get('KICAD_SYMBOL_DIR', '/usr/share/kicad/symbols')
need_cli = pytest.mark.skipif(not HAVE_CLI, reason='no kicad-cli')


def pure_rows(parts=None, spice=None, tag=''):
    """every row but S1 on a project built from the parts (no KiCad)"""
    parts = copy.deepcopy(v2.PARTS) if parts is None else parts
    spice = v2.spice_texts(str(SIM)) if spice is None else spice
    p = sch_synth.project_from_parts(parts, v2.DATASHEET_PINS, str(FIX / 'kicad'))
    rows = [sr.s2_row(p, v2, tag), sr.s3_row(p, v2, tag), sr.e1_row(p, v2, tag), sr.e2_row(p, v2, tag), sr.e3_row(p, v2, tag),
            sr.e4_row(p, v2, tag), v2.b1_row(parts, str(SIM), tag)]
    rows += [sr.spice_row(p, v2, cid, block, spice[block], tag) for cid, block, _ in v2.SPICE_ROWS]
    rows += sr.d_rows(p, v2, tag)
    rows += v2.computed_rows(p, tag)
    rows += [sr.bridge_row(p, v2, tag), sr.header_row(p, v2, tag)]
    return rows


def verdicts(rows):
    return {r.id.split('~')[0]: r.ok for r in rows}


# ================================================================================================ the frozen inputs
def test_the_fixture_design_is_the_live_design():
    """the equivalence tests run the live design.py against the frozen project: when the design moves, regenerate and re-freeze"""
    assert (FIX / 'kicad' / 'design.py').read_bytes() == pathlib.Path(v2_sch.PROJECT_DIR, 'design.py').read_bytes()


def test_the_design_is_loaded_from_one_place_and_leaves_no_plain_module_name():
    import sys
    assert 'design' not in sys.modules and v2_sch._design.__name__ == 'pcbtools._live_v2.design'
    assert v2_sch._load_design(str(FIX / 'kicad' / 'design.py')).PARTS == v2_sch.PARTS


def test_the_old_tools_are_frozen_with_what_they_read():
    assert sorted(p.name for p in (FIX / 'kicad').iterdir() if p.is_file()) == sorted(
        ['build_sch.py', 'check.py', 'spicecmp.py', 'design.py', 'afe-v2.kicad_sch', 'afe-v2.kicad_pro', 'sym-lib-table', 'fp-lib-table'])
    assert not [p for p in FIX.rglob('*.pyc')]


def test_the_golden_is_the_old_check_in_the_image():
    g = (GOLD / 'check.raw.txt').read_text()
    assert g.rstrip().endswith('exit=1') and '\nPASS M*: 24 of 24 mutation arms failed the way they must\n' in g
    stamp = (GOLD / 'STAMP.json').read_text()
    assert 'sha256:d59d53c2f00f' in stamp and '"reproduced"' in stamp


# ================================================================================================ spicecmp: known answers
def test_parse_value_and_sig():
    assert spicecmp.parse_value('510k 1%') == 510000.0 and spicecmp.parse_value('22p C0G') == pytest.approx(2.2e-11)
    assert spicecmp.parse_value('1Meg') == 1e6 and spicecmp.parse_value('2.2e-11') == pytest.approx(2.2e-11)
    assert spicecmp.parse_value('0R') == 0.0 and spicecmp.parse_value('BAV99') is None
    assert spicecmp.sig(1.23456789) == 1.23457


RULES = dict(anchors={'0': 'GND'}, drop={'Vs': 'source'}, short=['Vam'], esr=[('Cb', 'Rb')], subckt_models={})
NET = """* a divider with an ammeter, an ESR capacitor and a source
Vs in 0 1
Rt in mid 1k
Vam mid mid2 0
Rbot mid2 0 3k
Cb mid2 x 1u
Rb x 0 0.1
.op
"""


def test_read_spice_applies_the_reductions():
    els = spicecmp.read_spice(NET, RULES)
    # the source is dropped, the 0 V ammeter shorted, the ESR resistor folded into its capacitor
    assert sorted((e['kind'], e['value']) for e in els) == [('C', 1e-06), ('R', 1000.0), ('R', 3000.0)]
    nodes = {e['name']: [n for _, n in e['pins']] for e in els}
    assert nodes['Rbot'][0] == nodes['Rt'][1]            # mid and mid2 are one node


def test_a_rule_naming_a_vanished_element_and_an_unlisted_element_both_fail():
    with pytest.raises(ValueError, match='no longer has'):
        spicecmp.read_spice(NET.replace('Vs in 0 1\n', ''), RULES)
    with pytest.raises(ValueError, match='unclassified'):
        spicecmp.read_spice(NET + 'Qx a b c\n', RULES)


def test_fold_parallel_parts():
    els = [dict(name='R1', kind='R', value=100.0, pins=[('p', 'a'), ('p', 'b')]), dict(name='R2', kind='R', value=100.0, pins=[('p', 'b'), ('p', 'a')]),
           dict(name='C1', kind='C', value=1e-6, pins=[('p', 'a'), ('p', 'b')]), dict(name='C2', kind='C', value=1e-6, pins=[('p', 'a'), ('p', 'b')])]
    out = spicecmp.fold(els)
    assert sorted((e['kind'], e['value']) for e in out) == [('C', 2e-06), ('R', 50.0)]


def test_colours_see_a_swapped_connection_and_a_changed_value_and_ignore_names():
    a = [dict(name='x', kind='R', value=1.0, pins=[('p', 'n1'), ('p', 'GND')]), dict(name='y', kind='R', value=2.0, pins=[('p', 'n1'), ('p', 'n2')])]
    b = [dict(name='P', kind='R', value=1.0, pins=[('p', 'q1'), ('p', 'GND')]), dict(name='Q', kind='R', value=2.0, pins=[('p', 'q2'), ('p', 'q1')])]
    anchors = {'GND': 'GND'}
    assert spicecmp.colours(a, anchors) == spicecmp.colours(b, anchors)
    a.append(dict(name='z', kind='R', value=3.0, pins=[('p', 'n2'), ('p', 'GND')]))
    b.append(dict(name='R', kind='R', value=3.0, pins=[('p', 'q2'), ('p', 'GND')]))
    assert spicecmp.colours(a, anchors) == spicecmp.colours(b, anchors)
    swapped = [dict(b[0], pins=[('p', 'q2'), ('p', 'GND')]), b[1], b[2]]          # the 1 ohm part moved from node q1 to node q2
    assert spicecmp.colours(a, anchors) != spicecmp.colours(swapped, anchors)
    assert spicecmp.colours(a, anchors) != spicecmp.colours([dict(b[0], value=1.1), b[1], b[2]], anchors)


def test_compare_on_the_real_blocks_has_no_difference_and_a_changed_value_is_one():
    p = sch_synth.project_from_parts(copy.deepcopy(v2.PARTS), v2.DATASHEET_PINS)
    for cid, block, rel in v2.SPICE_ROWS:
        d, ns, nc_ = spicecmp.compare(block, (SIM / rel).read_text(), p.comps, p.nets, v2)
        assert d == [] and ns == nc_ and ns >= 10, (block, d)
    p.comps['R303']['value'] = '4.7k 1%'
    d, _, _ = spicecmp.compare('awg', (SIM / 'awg' / 'awg.cir').read_text(), p.comps, p.nets, v2)
    assert d and 'R 3000.0' in d[0]


def test_a_bridge_that_is_not_zero_ohm_is_refused():
    p = sch_synth.project_from_parts(copy.deepcopy(v2.PARTS), v2.DATASHEET_PINS)
    p.comps['BR101']['value'] = '1k 1%'
    with pytest.raises(ValueError, match='0 ohm'):
        spicecmp.schematic_elements(p.comps, p.nets, 'scope', v2)


# ================================================================================================ the generic rows, known answers
def mini(**over):
    base = dict(ERC_EXCLUDED=1, MIN_NETS=1, MIN_COMPS=1, COMPARE_FIELDS=(), FOOTPRINT_DIR='/nonexistent', PROJECT_LIB_NAME='proj',
                FITTED_BY_BOARD_HOUSE='fab', DATASHEET_PINS={'IC': {'1': 'IN', '2': 'OUT'}}, BLOCKDIGIT={'A': 1, 'B': 2},
                KEY_PARTS={'A': {'R101', 'U101', 'BR101'}, 'B': {'R201'}}, ROW_IDS={'numbering': ('D1', 'D2'), 'bridge': 'C6'}, BRIDGE_JOINS={'BR101': (('pin', 'R101', '1'), ('fn', 'U101', 'OUT'))},
                BRIDGE_SIDES=[(('pin', 'R101', '2'), ('pin', 'R201', '1'))], BRIDGE_TEXT='sides ok',
                HEADER_TABLE={'HDR': {'1': 'X'}}, HEADER_BLOCK='A', HEADER_PART_PREFIX='Conn_0', HEADER_LABEL='test', MIN_SPICE_ELEMENTS=1)
    base.update(over)
    return types.SimpleNamespace(**base)


def part(ref, sym, value, pins, block, nc=(), fitted_by='fab', lcsc='C1234', fp='lib:fp'):
    return dict(ref=ref, sym=sym, value=value, fp=fp, lcsc=lcsc, pins=pins, block=block, nc=nc, fitted_by=fitted_by, sim='', note='', dnp=False)


MINI = [part('R101', 'Device:R', '1k', {'1': 'X', '2': 'Y'}, 'A'),
        part('U101', 'lib:IC', 'IC', {'1': 'Y', '2': 'Z'}, 'A', nc=()),
        part('R201', 'Device:R', '2k', {'1': 'Y', '2': 'Z'}, 'B'),
        part('BR101', 'Device:R', '0R', {'1': 'X', '2': 'Z'}, 'A')]


def mp(parts=MINI, **kw):
    return sch_synth.project_from_parts(parts, {'IC': {'1': 'IN', '2': 'OUT'}}, **kw)


def test_e1_a_declared_nc_must_be_unconnected_and_every_other_pin_connected():
    cfg = mini()
    parts = copy.deepcopy(MINI)
    parts[1]['pins'] = {'1': 'Y'}                                    # pin 2 left out and not declared: KiCad still lists it as an NC net
    p = mp(parts)
    p.nets['unconnected-(U101-Pad2)'] = [('U101', '2', 'OUT')]
    r = sr.e1_row(p, cfg)
    assert not r.ok and "KiCad NC pins ['2'] != declared []" in r.detail
    parts[1]['nc'] = ('2',)                                          # declared, and the netlist has its unconnected net
    assert sr.e1_row(mp(parts), cfg).ok
    parts[1]['nc'] = ()                                              # declared NC, then the net is missing: a pin the netlist lost
    p = mp(parts)
    assert sr.e1_row(p, cfg).ok                                      # (nothing declared, nothing unconnected)
    parts = copy.deepcopy(MINI) + [part('J101', 'Connector_Generic:Conn_01x02', 'H', {'1': 'X'}, 'A', nc='rest')]
    p = mp(parts)
    assert sr.e1_row(p, cfg).ok                                      # a header passes its unused pins through
    p.nets['unconnected-(J101-Pad1)'] = [('J101', '1', '')]
    assert not sr.e1_row(p, cfg).ok                                  # but a CONNECTED pin that KiCad calls unconnected is wrong


def test_e2_a_net_with_one_pin_fails_and_names_it():
    parts = copy.deepcopy(MINI)
    parts[2]['pins']['2'] = 'ORPHAN'
    r = sr.e2_row(mp(parts), mini())
    assert not r.ok and 'ORPHAN' in r.detail
    assert sr.e2_row(mp(), mini()).ok


def test_e3_footprint_value_and_lcsc(tmp_path):
    fpd = tmp_path / 'fps'
    (fpd / 'lib.pretty').mkdir(parents=True)
    (fpd / 'lib.pretty' / 'fp.kicad_mod').write_text('x')
    cfg = mini(FOOTPRINT_DIR=str(fpd))
    assert sr.e3_row(mp(), cfg).ok
    parts = copy.deepcopy(MINI)
    parts[0]['lcsc'] = ''
    assert 'no LCSC' in sr.e3_row(mp(parts), cfg).detail
    parts[0]['lcsc'] = 'X12'
    assert 'not a Cnnn code' in sr.e3_row(mp(parts), cfg).detail
    parts[0]['lcsc'] = 'C1234'
    parts[0]['fp'] = 'lib:missing'
    assert 'not in any library' in sr.e3_row(mp(parts), cfg).detail
    parts[0]['fp'] = 'lib:fp'
    parts[0]['fitted_by'] = 'owner'                                  # not fitted by the board house: no code needed
    parts[0]['lcsc'] = ''
    assert sr.e3_row(mp(parts), cfg).ok


def test_e4_pin_names_equal_the_table():
    cfg = mini()
    assert sr.e4_row(mp(), cfg).ok
    r = sr.e4_row(mp(), mini(DATASHEET_PINS={'IC': {'1': 'IN', '2': 'IN'}}))
    assert not r.ok and "'OUT'" in r.detail
    assert not sr.e4_row(mp(), mini(DATASHEET_PINS={'NOPE': {}})).ok          # a table that matches no part examined nothing


def test_d1_d2_hundreds_digit_and_key_part_list():
    cfg = mini()
    assert all(r.ok for r in sr.d_rows(mp(), cfg))
    parts = copy.deepcopy(MINI)
    parts[2]['block'] = 'A'                                           # R201 claimed by block A
    r1, r2 = sr.d_rows(mp(parts), cfg)
    assert not r1.ok and 'R201 (A)' in r1.detail and not r2.ok
    parts = copy.deepcopy(MINI)
    parts[2]['ref'] = 'R301'
    r1, r2 = sr.d_rows(mp(parts), cfg)
    assert not r1.ok and not r2.ok and 'missing' in r2.detail


def test_c6_a_bridge_must_join_what_the_config_says_and_the_sides_must_hold():
    cfg = mini()
    # BR101 joins X and Z: R101 pin 1 is on X, U101's OUT is on Z
    assert sr.bridge_row(mp(), cfg).ok
    parts = copy.deepcopy(MINI)
    parts[3]['pins']['2'] = 'W'                                       # the bridge no longer reaches U101's output
    assert not sr.bridge_row(mp(parts), cfg).ok
    assert not sr.bridge_row(mp(), mini(BRIDGE_SIDES=[(('pin', 'R101', '1'), ('pin', 'R201', '1'))])).ok


def test_h1_header_pins_equal_the_table():
    parts = copy.deepcopy(MINI) + [part('J101', 'Connector_Generic:Conn_01x01', 'HDR', {'1': 'X'}, 'A')]
    assert sr.header_row(mp(parts), mini()).ok
    parts[-1]['pins']['1'] = 'Y'
    assert not sr.header_row(mp(parts), mini()).ok
    assert not sr.header_row(mp(), mini()).ok                         # the header is missing


def test_resistor_chain_arithmetic():
    parts = [part('R1', 'Device:R', '10k', {'1': 'A', '2': 'M'}, 'A'), part('R2', 'Device:R', '2.2k', {'1': 'M', '2': 'B'}, 'A'),
             part('R3', 'Device:R', '1k', {'1': 'M', '2': 'T'}, 'A')]
    p = sch_synth.project_from_parts(parts, {})
    R = sr.rmap(p)
    assert R['R1'] == (10000.0, 'A', 'M') and sr.chain(R, 'A', 'B', p.real) is None          # M carries three pins: not a series chain
    assert sr.chain(R, 'A', 'M', p.real) == 10000.0
    assert sr.chain(R, 'T', 'M', p.real) == 1000.0
    assert sr.chain(R, 'A', 'NOWHERE', p.real) is None


def test_s2_and_s3_compare_nets_and_fields():
    cfg = mini(COMPARE_FIELDS=(('Block', 'block'),))
    p = mp()
    assert sr.s2_row(p, cfg).ok and sr.s3_row(p, cfg).ok
    p.nets['Y'] = [('R101', '2', ''), ('R201', '1', '')]               # U101's pin moved off Y
    p.nets['Z'] = sorted(p.nets['Z'] + [('U101', '1', '')])
    assert not sr.s2_row(p, cfg).ok
    p = mp()
    p.comps['R101']['fields']['Block'] = 'B'
    assert "Block 'B' != 'A'" in sr.s3_row(p, cfg).detail


# ================================================================================================ the arm rule: a flip, never a row that was already failing
def test_flip_row_wants_pass_then_fail():
    clean = {'N1': True, 'B1': True}
    assert sr.flip_row('x', ('N1', 'B1'), clean, {'N1', 'B1', 'S3'}).ok
    r = sr.flip_row('x', ('N1', 'B1'), clean, {'N1'})
    assert not r.ok and r.detail == "['N1'] failed; wanted ['N1', 'B1']"
    r = sr.flip_row('x', ('N1',), {'N1': False}, {'N1'})
    assert not r.ok and r.detail.startswith('NOT TESTABLE') and "['N1']" in r.detail
    assert not sr.flip_row('x', ('Q9',), clean, {'Q9'}).ok            # a row that does not exist cannot be caught either


def test_finish_arms_counts():
    rows = sr.finish_arms([Row('a', True, ''), Row('b', False, '')])
    assert rows[-1].id == 'M*' and not rows[-1].ok and rows[-1].detail == '1 of 2 mutation arms failed the way they must'


# ================================================================================================ v2 rows on the real design (no KiCad)
def test_every_row_passes_on_the_real_design():
    rows = pure_rows()
    assert [r.id for r in rows] == ['S2', 'S3', 'E1', 'E2', 'E3', 'E4', 'B1', 'N1', 'N2', 'D1', 'D2', 'C1', 'C2', 'C3', 'C4', 'C5', 'C6', 'H1']
    assert all(r.ok for r in rows), [r.line() for r in rows if not r.ok]


def test_known_figures_of_the_power_calibration_and_scope_rows():
    d = {r.id: r.detail for r in pure_rows()}
    assert d['C1'].startswith('V+ = 3.3176 V (R1 120000, R2 68000), V- = -2.0032 V (R3 64200, R4 100000)')
    assert d['C2'].startswith('6 rungs of [330.0]') and d['C3'].startswith('k = 0.400, Rm 10000 vs Rs + Rt||Rb 9900')
    assert "B touches ['R508', 'R509', 'R511'] only" in d['C4']
    assert "reference loaded by ['R106', 'R206', 'R305']" in d['C5']
    assert d['N1'] == 'scope: 29 SPICE elements after reduction, 29 schematic elements'
    assert d['N2'] == 'awg: 14 SPICE elements after reduction, 14 schematic elements'
    assert d['D2'].startswith('each block holds exactly its key part list: CH1 18, CH2 15, AWG 17, POWER 21, REFCAL 21, EDGE 9')
    assert d['B1'] == '64 studied parts against 65 parts.csv keys' and d['C6'].startswith("BR101 joins ['+3V3A', '+3V3A_U']")


def test_study_rows_known_entries():
    w = v2.study_rows(str(SIM))
    assert w['scope.R1a'][2] == 'C23192' and w['awg.R3'][0] == 1 and len(w) == 65
    assert v2.expand_refs('R_L1..R_L3 (ladder), C_X') == ['R_L1', 'R_L2', 'R_L3', 'C_X']
    assert v2.csv_value('330R 1%') == 330.0 and v2.csv_value('100n X7R') == pytest.approx(1e-7) and v2.csv_value('TPH2502') is None


def test_block_of_parts_and_key_parts_agree_with_the_design():
    got = {}
    for ref, b in v2.block_of_parts().items():
        got.setdefault(b, set()).add(ref)
    assert got == v2.KEY_PARTS


NO_ERC_ARMS = ('GND flag removed', 'pin left out without NC')           # the first needs KiCad's ERC, the second is the generator's refusal
PURE_ARMS = [a for a in v2.flip_arms() if a.why not in NO_ERC_ARMS]


def test_there_are_24_arms_with_the_old_names():
    arms = v2.flip_arms()
    assert len(arms) == 24 and len({a.why for a in arms}) == 24
    old = re.findall(r'^PASS M-(.*?): ', (GOLD / 'check.raw.txt').read_text(), re.M)
    assert [a.why for a in arms] == old and len(old) == 24
    assert [(a.why, a.expect) for a in arms if a.why in NO_ERC_ARMS] == [('pin left out without NC', ()), ('GND flag removed', ('S1',))]


@pytest.mark.parametrize('arm', PURE_ARMS, ids=lambda a: a.why)
def test_each_arm_flips_its_rows_from_pass_to_fail(arm):
    clean = verdicts(pure_rows())
    assert all(clean.values())
    parts = copy.deepcopy(v2.PARTS)
    if arm.mut_parts:
        arm.mut_parts(parts)
    spice = v2.spice_texts(str(SIM))
    if arm.mut_spice:
        arm.mut_spice(spice)
    failed = {k for k, ok in verdicts(pure_rows(parts, spice, '~x')).items() if not ok}
    assert set(arm.expect) <= failed, (failed, arm.expect)
    assert sr.flip_row(arm.why, arm.expect, clean, failed).ok


@pytest.mark.parametrize('arm', PURE_ARMS, ids=lambda a: a.why)
def test_each_arm_broken_once_on_purpose_is_not_caught(arm):
    """break what the arm leans on: with any one of its rows forced to pass on the changed copy, or forced to fail on the clean
    board, the arm must report itself not caught (the second is the NOT TESTABLE case)"""
    parts = copy.deepcopy(v2.PARTS)
    if arm.mut_parts:
        arm.mut_parts(parts)
    spice = v2.spice_texts(str(SIM))
    if arm.mut_spice:
        arm.mut_spice(spice)
    failed = {k for k, ok in verdicts(pure_rows(parts, spice, '~x')).items() if not ok}
    clean = verdicts(pure_rows())
    for row in arm.expect:
        assert not sr.flip_row(arm.why, arm.expect, clean, failed - {row}).ok
        r = sr.flip_row(arm.why, arm.expect, dict(clean, **{row: False}), failed)
        assert not r.ok and r.detail.startswith('NOT TESTABLE')


def test_an_arm_whose_row_already_fails_on_the_clean_board_is_not_testable():
    """a broken clean board (the rail feedback value moved) makes the 'LCSC changed' arm's row B1 fail before any mutation"""
    parts = copy.deepcopy(v2.PARTS)
    v2.arm_rail(parts)
    clean = verdicts(pure_rows(parts))
    assert not clean['C1'] and not clean['B1']
    arm = next(a for a in v2.flip_arms() if a.why == 'LCSC changed')
    r = sr.flip_row(arm.why, arm.expect, clean, {'B1'})
    assert not r.ok and r.detail.startswith('NOT TESTABLE')
    assert not sr.finish_arms([r])[-1].ok


@pytest.mark.skipif(not os.path.isdir(SYMDIR), reason='no KiCad symbol libraries')
def test_the_generator_refuses_a_pin_left_out_and_a_declared_nc_that_is_connected():
    lib = sch.Library(SYMDIR, os.path.join(v2_sch.PROJECT_DIR, 'lib', 'afe.kicad_sym'))
    sch.check_nc(copy.deepcopy(v2.PARTS), lib)                         # the design passes
    parts = copy.deepcopy(v2.PARTS)
    v2.arm_omit_pin(parts)
    with pytest.raises(sch.SchematicError, match=r"R306: pins \['2'\] neither connected nor declared NC"):
        sch.check_nc(parts, lib)
    parts = copy.deepcopy(v2.PARTS)
    v2.P(parts, 'U502')['nc'] = ('2', '4')                             # pin 4 is connected
    with pytest.raises(sch.SchematicError, match='declared NC and connected'):
        sch.check_nc(parts, lib)
    parts = copy.deepcopy(v2.PARTS)
    v2.P(parts, 'R306')['pins']['9'] = 'X'
    with pytest.raises(sch.SchematicError, match='not in symbol'):
        sch.check_nc(parts, lib)


def test_the_new_modules_hold_no_reference_or_net_literal():
    import test_no_board_literals as t
    for mod in ('schematic.py', 'schematic_rows.py', 'spicecmp.py', 'schematic_check.py'):
        text = (pathlib.Path(t.PKG) / mod).read_text()
        assert t.violations(text) == [], mod
    assert t.violations((pathlib.Path(t.PKG) / 'spicecmp.py').read_text() + "\nBAD = 'BR101'\n")            # the scan does see them


def test_the_scan_of_the_v2_files_is_what_it_looks_like_the_literals_live_only_there():
    import test_no_board_literals as t
    for mod in ('boards/v2_sch.py', 'boards/v2_checks.py'):
        assert t.violations((pathlib.Path(t.PKG) / mod).read_text()), mod


# ================================================================================================ through KiCad
GOLDEN_LINE = re.compile(r'^(PASS|FAIL) ([^:~]+): (.*)$')


def golden(prefix=None):
    out = {}
    for ln in (GOLD / 'check.raw.txt').read_text().splitlines():
        m = GOLDEN_LINE.match(ln)
        if m and '~' not in m[2] and (prefix is None or m[2].startswith(prefix)):
            out[m[2]] = (m[1] == 'PASS', m[3])
    return out


def digest(p):
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


@pytest.mark.pcbnew
@need_cli
def test_generator_is_byte_identical_to_the_old_build_sch(tmp_path):
    """the committed files and the old script's own output are the references; the only differences are the two that are the
    old project's, and both are explained"""
    out = tmp_path / 'new'
    v2.build(str(out), comments=v2_sch.LEGACY_SCH_COMMENTS)          # the old script's header text: the only change of a regeneration
    for f in ('afe-v2.kicad_sch', 'sym-lib-table', 'fp-lib-table', 'lib/afe.kicad_sym'):
        assert (out / f).read_bytes() == (FIX / 'kicad' / f).read_bytes(), f
    old = {}
    for ln in (GOLD / 'build_sch.sha256.txt').read_text().splitlines():
        if '  generated  ' in ln:
            h, f = ln.split('  generated  ')
            old[f] = h
    assert old['afe-v2.kicad_pro'] == digest(out / 'afe-v2.kicad_pro')       # the old generator's project file, in the image
    assert all(old[f] == digest(out / f) for f in old)
    # the committed project file is stale: its ERC exclusion carries the pin uuid of U3 pin 1, the part's name before U401
    new, committed = (out / 'afe-v2.kicad_pro').read_text(), (FIX / 'kicad' / 'afe-v2.kicad_pro').read_text()
    stale = sch.make_uid(v2_sch.NS, 'pin', 'U3', 1, '1')
    assert new != committed and committed.replace(stale, sch.make_uid(v2_sch.NS, 'pin', 'U401', 1, '1')) == new


@pytest.mark.pcbnew
@need_cli
def test_the_default_header_text_is_the_only_difference_from_the_committed_schematic(tmp_path):
    out = tmp_path / 'new'
    v2.build(str(out))
    a = (out / 'afe-v2.kicad_sch').read_text().splitlines()
    b = (FIX / 'kicad' / 'afe-v2.kicad_sch').read_text().splitlines()
    diff = [(x, y) for x, y in zip(a, b) if x != y]
    assert len(a) == len(b) and len(diff) == 1 and 'pcbtools.schematic' in diff[0][0] and 'build_sch.py' in diff[0][1]


@pytest.fixture(scope='module')
def project(tmp_path_factory):
    work = tmp_path_factory.mktemp('v2proj')
    proj = work / 'project'
    shutil.copytree(FIX / 'kicad', proj, ignore=shutil.ignore_patterns('__pycache__', '*.py'))
    return work, proj


@pytest.mark.pcbnew
@need_cli
def test_rows_equal_the_old_check_rows_verdict_and_text(project):
    work, proj = project
    rows = v2.all_rows(str(proj / 'afe-v2.kicad_sch'), v2.PARTS, v2.spice_texts(str(SIM)), '', str(SIM))
    g = golden()
    assert [r.id for r in rows] == ['S1', 'S2', 'S3', 'E1', 'E2', 'E3', 'E4', 'B1', 'N1', 'N2', 'D1', 'D2', 'C1', 'C2', 'C3', 'C4', 'C5', 'C6', 'H1']
    for r in rows:
        assert (r.ok, r.detail) == g[r.id], r.id
    assert not g['S1'][0] and all(ok for k, (ok, _) in g.items() if not k.startswith('M') and k != 'S1')     # the stale .kicad_pro: S1 alone


def with_footprints(gen):
    """the project folder as the owner keeps it: the generator writes the schematic, tables and symbol library, the footprint
    library afe.pretty is hand-kept beside them"""
    shutil.copytree(FIX / 'kicad' / 'lib' / 'afe.pretty', pathlib.Path(gen) / 'lib' / 'afe.pretty')
    return gen


@pytest.mark.pcbnew
@need_cli
def test_a_regenerated_project_passes_every_row(tmp_path):
    v2.build(str(tmp_path / 'gen'))
    with_footprints(tmp_path / 'gen')
    rows = v2.all_rows(str(tmp_path / 'gen' / 'afe-v2.kicad_sch'), v2.PARTS, v2.spice_texts(str(SIM)), '', str(SIM))
    assert all(r.ok for r in rows), [r.line() for r in rows if not r.ok]


@pytest.mark.pcbnew
@need_cli
def test_the_command_line(tmp_path, capsys):
    gen = tmp_path / 'gen'
    assert v2.main(['--build', str(gen)]) == 0 and 'cells' in capsys.readouterr().out
    with_footprints(gen)
    assert v2.main(['--project', str(gen), '--sim', str(SIM)]) == 0
    out = capsys.readouterr().out
    assert out.rstrip().endswith('ALL PASS') and out.count('PASS ') >= 19
    stale = tmp_path / 'stale'
    shutil.copytree(FIX / 'kicad', stale, ignore=shutil.ignore_patterns('__pycache__', '*.py'))
    assert v2.main(['--project', str(stale), '--sim', str(SIM)]) == 1                          # the committed project: S1
    assert capsys.readouterr().out.rstrip().endswith('FAIL: S1')
    assert v2.main(['--pcb']) == 2


@pytest.mark.pcbnew
@need_cli
def test_a_changed_part_value_shows_in_the_rows_through_kicad(tmp_path):
    parts = copy.deepcopy(v2.PARTS)
    v2.arm_value_awg(parts)
    rows = v2.variant_rows(parts, v2.spice_texts(str(SIM)), None, str(tmp_path), '~x', v2_sch.PROJECT_DIR, str(SIM))
    assert {r.id.split('~')[0] for r in rows if not r.ok} == {'N2', 'B1'}


@pytest.mark.slow
@pytest.mark.pcbnew
@need_cli
def test_the_24_arms_equal_the_old_arms_text_included(tmp_path):
    rows = v2.run_arms(str(tmp_path), project_dir=str(FIX / 'kicad'), sim_dir=str(SIM))
    g = golden('M')
    assert len(rows) == 25 and rows[-1].id == 'M*' and rows[-1].ok
    assert not any(r.detail.startswith('NOT TESTABLE') for r in rows)
    for r in rows:
        assert (r.ok, r.detail) == g[r.id], r.id
    assert [r.id for r in rows] == list(g)


@pytest.mark.slow
@pytest.mark.pcbnew
@need_cli
def test_an_arm_aimed_at_a_row_that_fails_on_the_clean_board_is_reported_not_testable(tmp_path, monkeypatch):
    """break the clean baseline on purpose: the generator is given a design whose rail feedback is wrong, so C1 and B1 fail before
    any mutation, and the two arms aimed at them cannot be caught"""
    bad = copy.deepcopy(v2.PARTS)
    v2.arm_rail(bad)
    monkeypatch.setattr(v2, 'PARTS', bad)
    arms = [a for a in v2.flip_arms() if a.why in ('rail feedback value', 'LCSC changed', 'ADS1115 pair')]
    rows = v2.run_arms(str(tmp_path), arms=arms, project_dir=str(FIX / 'kicad'), sim_dir=str(SIM))
    got = {r.id: r for r in rows}
    assert got['M-rail feedback value'].detail.startswith('NOT TESTABLE') and got['M-LCSC changed'].detail.startswith('NOT TESTABLE')
    assert got['M-ADS1115 pair'].ok and not got['M*'].ok


@pytest.mark.slow
@pytest.mark.pcbnew
@need_cli
def test_breaking_the_spice_row_on_purpose_makes_its_arms_uncaught(tmp_path, monkeypatch):
    """the positive control of the arms themselves: with the netlist comparison blinded (it passes whatever it is given), the three
    arms aimed at N1 and N2 through KiCad must stop being caught, and the summary must say so"""
    real = sr.spice_row
    monkeypatch.setattr(sr, 'spice_row', lambda p, cfg, row_id, block, text, tag='': Row(row_id + tag, True, 'blinded'))
    arms = [a for a in v2.flip_arms() if a.why in ('scope pin swap', 'SPICE awg value', 'LCSC changed')]
    rows = v2.run_arms(str(tmp_path), arms=arms, project_dir=str(FIX / 'kicad'), sim_dir=str(SIM))
    got = {r.id: r for r in rows}
    assert not got['M-scope pin swap'].ok and not got['M-SPICE awg value'].ok and got['M-LCSC changed'].ok     # B1 is not blinded
    assert not got['M*'].ok and got['M*'].detail == '1 of 3 mutation arms failed the way they must'
    monkeypatch.setattr(sr, 'spice_row', real)
