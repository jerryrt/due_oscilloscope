"""pcbtools.silkruns: runs found, counted by one, labelled once at the end that has room; the renaming of the board text; the check. Hand-built boards
(no pcbnew) and the live board's text. Broken once on purpose, as the suite requires."""
import dataclasses
import json
import pathlib
import re
import types

import numpy as np
import pytest

from pcbtools import silkruns as S
from tests.pcbtools.synth import Synth

CFG = types.SimpleNamespace(DESIGNATOR_ADVANCE=0.95, DESIGNATOR_INK_H=1.2)
BOARD = pathlib.Path(__file__).resolve().parents[2] / 'v2' / 'layout' / 'integrated' / 'afe-v2-integrated.kicad_pcb'


def board(s):
    return dataclasses.replace(s.build(), outline=np.array([[0.0, 0.0], [60.0, 0.0], [60.0, 40.0], [0.0, 40.0]]))


def part(s, ref, x, y, vertical=False, silk=True):
    """a two-pad 0603-like part: courtyard 3.0 x 1.5 (or 1.5 x 3.0), pads at its two ends"""
    hw, hh = (0.75, 1.5) if vertical else (1.5, 0.75)
    s.part(ref, x, y, box=(x - hw, y - hh, x + hw, y + hh), rot=90.0 if vertical else 0.0, silk=silk)
    dx, dy = (0, 0.8) if vertical else (0.8, 0)
    s.p(ref, '1', x - dx, y - dy, size=0.6).p(ref, '2', x + dx, y + dy, size=0.6)
    return s


def row(refs, x0=10.0, y=20.0, pitch=3.5, vertical=False, **kw):
    s = Synth('/N')
    for k, r in enumerate(refs):
        part(s, r, x0 + k * pitch, y, vertical=vertical, **kw)
    return s


def test_a_row_of_horizontal_parts_is_one_axial_run_left_to_right():
    b = board(row(['R103', 'R102', 'R101']))
    runs, grids = S.find_runs(b, CFG)
    assert len(runs) == 1 and grids == [] and runs[0].kind == 'row' and runs[0].refs == ['R103', 'R102', 'R101'] and runs[0].axial


def test_parts_side_by_side_are_a_run_that_is_not_axial_and_a_gap_or_a_misalignment_ends_a_run():
    side = S.find_runs(board(row(['R101', 'R102'], pitch=2.5, vertical=True)), CFG)[0]
    assert len(side) == 1 and not side[0].axial                           # vertical parts in a row: counted, each labelled for itself
    s = row(['R101', 'R102'], pitch=6.0)                                   # 3 mm between courtyards: no run
    assert S.find_runs(board(s), CFG)[0] == []
    s = Synth('/N')
    part(s, 'R101', 10.0, 20.0)
    part(s, 'R102', 13.5, 20.4)                                            # 0.4 off the line
    assert S.find_runs(board(s), CFG)[0] == []
    assert S.find_runs(board(row(['R101', 'C101'])), CFG)[0] == []        # unlike kinds


def test_a_part_in_a_row_and_a_column_is_a_grid_and_in_no_run():
    s = Synth('/N')
    for ref, x, y in (('C401', 10.0, 20.0), ('C402', 13.5, 20.0), ('C403', 10.0, 21.5)):
        part(s, ref, x, y)
    runs, grids = S.find_runs(board(s), CFG)
    assert runs == [] and sorted(g[0] for g in grids) != [] and any('C401' in g for g in grids)


def test_numbers_count_up_from_the_end_that_has_room_and_the_label_sits_on_the_line_beyond_it():
    b = board(row(['R103', 'R101', 'R102']))
    p = S.plan(b, CFG)
    (run,) = p.runs
    assert p.end[id(run)] == 'first' and p.new == {'R103': 'R101', 'R101': 'R102', 'R102': 'R103'}
    x, y, ang = p.label[id(run)]
    assert ang == 0 and abs(y - 20.0) <= 0.3 and x < 10.0 - 1.5                          # beyond the left end, on the line
    assert 0 < (10.0 - 1.5) - (x + 4 * 0.95 / 2) <= 1.5                                    # within 1.5 mm of its courtyard


def test_a_pad_at_the_reading_end_sends_the_low_number_to_the_other_end():
    s = row(['R103', 'R101', 'R102'])
    part(s, 'C901', 6.0, 20.0)                                            # a part right at the left end
    p = S.plan(board(s), CFG)
    (run,) = [r for r in p.runs if 'R103' in r.refs]
    assert p.end[id(run)] == 'last' and p.new == {'R102': 'R101', 'R101': 'R102'}
    assert p.order[id(run)] == ['R102', 'R101', 'R103'] and p.label[id(run)][0] > 10.0 + 3.5 * 2 + 1.5


def test_a_run_with_no_room_at_either_end_is_blocked_and_keeps_its_numbers_if_they_already_count():
    s = row(['R102', 'R101'])
    part(s, 'C901', 6.0, 20.0)
    part(s, 'C902', 20.0, 20.0)
    p = S.plan(board(s), CFG)
    (run,) = [r for r in p.runs if 'R101' in r.refs]
    assert [x for x, _ in [(r.refs, w) for r, w in p.blocked]] == [['R102', 'R101']] and id(run) not in p.label and p.new == {}


def test_the_labelled_runs_are_the_checkers_own_reading_and_a_label_off_the_line_loses_them():
    s2 = row(['R101', 'R102', 'R103'])
    s2.rt[0] = (5.5, 20.0, 1.0, 0.8, 0.12, 0.0, 0, True, 0)                                                      # R101's label beyond the left end, on the line
    s2.rt[1] = (13.5, 20.0, 1.0, 0.8, 0.12, 0.0, 0, False, 1)
    s2.rt[2] = (17.0, 20.0, 1.0, 0.8, 0.12, 0.0, 0, False, 2)
    assert S.hidden_members(board(s2)) == {'R102', 'R103'}
    s2.rt[0] = (5.5, 21.0, 1.0, 0.8, 0.12, 0.0, 0, True, 0)                                                      # 1 mm off the line: no run, nothing may be hidden
    assert S.hidden_members(board(s2)) == set()


def test_a_grid_counts_row_by_row_when_the_config_says_so():
    s = Synth('/N')
    for ref, x, y in (('C401', 10.0, 20.0), ('C402', 13.5, 20.0), ('C404', 10.0, 21.5), ('C403', 13.5, 21.5)):
        part(s, ref, x, y)
    b = board(s)
    assert S.find_runs(b, CFG)[0] == []
    cfg = types.SimpleNamespace(DESIGNATOR_ADVANCE=0.95, DESIGNATOR_INK_H=1.2, RUN_GRID_ROWS=True)
    runs, grids = S.find_runs(b, cfg)
    assert grids == [] and sorted(r.refs for r in runs) == [['C401', 'C402'], ['C404', 'C403']]
    p = S.plan(b, cfg)
    assert p.new == {'C404': 'C403', 'C403': 'C404'}                                                             # each row counts up from its left end


def test_rename_is_a_whole_word_rewrite_with_the_schematic_path_following_and_it_reverses():
    from pcbtools.boards import v2_layout as L
    ns = L.SCH_NS
    from pcbtools.schematic import make_uid
    uid = lambda ref: make_uid(ns, 'sym', ref, 1)               # noqa: E731
    text = BOARD.read_text()
    inv = {v: k for k, v in L.RENUMBER.items()}
    back = S.rename(text, inv, uid)
    fwd = S.rename(back, L.RENUMBER, uid)
    assert fwd == text and back != text                           # the board is the renumbered one; undoing then redoing is the identity
    for old, new in L.RENUMBER.items():
        assert f'(property "Reference" "{new}"' in text and f'(path "/{make_uid(ns, "root")}/{uid(new)}")' in text


def pairing(parts):
    """{function: {block: number in the hundred}} of the scope parts that both channels have, where the two numbers differ"""
    by = {}
    for p in parts:
        if p['sim'].startswith('scope.') and p['block'] in ('CH1', 'CH2') and p['ref'][0] in 'RCD':
            by.setdefault(p['sim'], {})[p['block']] = int(p['ref'][1:]) % 100
    both = {k: v for k, v in by.items() if len(v) == 2}
    assert len(both) >= 11                                                  # a floor: the eleven functions the channels share, not an empty comparison
    return {k: v for k, v in both.items() if v['CH1'] != v['CH2']}


def test_both_channels_take_one_permutation_so_r1nn_and_r2nn_do_the_same_job():
    from pcbtools.boards import v2_sch
    assert pairing(v2_sch.PARTS) == {}


def test_broken_once_a_permutation_that_differs_between_channels_is_caught():
    from pcbtools.boards import v2_sch
    parts = [dict(p) for p in v2_sch.PARTS]
    by = {p['ref']: p for p in parts}
    by['R203']['ref'], by['R204']['ref'] = 'R204', 'R203'                    # CH2's R1a and R3b trade numbers, CH1's stay
    assert set(pairing(parts)) == {'scope.R1a', 'scope.R3b'}


def test_the_design_is_the_old_one_renamed_nets_and_parts_by_function(tmp_path):
    """design.py with the old numbering (RN and CN the identity, BR102 called BR101) has the same nets and parts under the rename"""
    import importlib.util
    from pcbtools.boards import v2_layout as L
    src = (BOARD.parents[2] / 'kicad' / 'design.py').read_text()
    src = re.sub(r'RN = \{[^}]*\}', 'RN = {k: k for k in range(1, 9)}', src)
    src = re.sub(r'CN = \{[^}]*\}', 'CN = {k: k for k in range(1, 4)}', src).replace("'BR102'", "'BR101'")
    old_path = tmp_path / 'design_old.py'
    old_path.write_text(src)
    spec = importlib.util.spec_from_file_location('design_old', old_path)
    old = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(old)
    from pcbtools.boards import v2_sch
    ren = {r: L.RENUMBER.get(r, r) for r in (p['ref'] for p in old.PARTS)}
    po = {ren[p['ref']]: p for p in old.PARTS}
    pn = {p['ref']: p for p in v2_sch.PARTS}
    assert set(po) == set(pn)
    for r in pn:
        a, b = dict(po[r]), dict(pn[r])
        a.pop('ref')
        b.pop('ref')
        a.pop('note')
        b.pop('note')
        assert a == b, r                                            # value, LCSC, footprint, pins (nets), sim name, block: unchanged by the rename
    assert old.PARTS_BY_REF['R201']['sim'] == 'scope.R1a' and pn['R203']['sim'] == 'scope.R1a'


