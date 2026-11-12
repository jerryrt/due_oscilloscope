"""The new rules against the OLD tools' recorded output (tests/golden/v2-8a1f7ac), on the cached arrays of the seven
frozen boards (no pcbnew).

Every (board, row) must give the old verdict. The detail text must equal the old text except where DIFFS says why not,
and each DIFFS entry must really differ (a stale entry fails) and be explained by the one cause there is: a figure
that sits exactly on a rounding boundary of the printed 0.1 mm (1.45 prints 1.5 from one sum of floats and 1.4 from
another). The old tool summed track lengths from the board's 1e-9 nm integers, the new one sums coordinates rounded to
1e-6; the length is 1.45 in both, and the print is a coin toss.

Differences that are by design, not by rounding (each is also asserted below):

  | what                                  | old                                  | new                                         |
  |---------------------------------------|--------------------------------------|---------------------------------------------|
  | LR-1/3/5/9 point tests                | any sample point every 0.1-0.5 mm    | exact segment tests (geom): same verdicts   |
  | LR-5 distance figure                  | nearest sample point                 | exact: never larger than the old figure     |
  | LR-4 'pour near FB' arm               | a point list `extra_top_gnd`         | a top GND track: detail says 'GND track'    |
  | LR-4 top-pour test                    | HitTestFilledArea(accuracy 0.02 mm)  | even-odd point-in-ring, hole-aware, no 0.02 |
  | LR-6/LR-8 touch tests                 | samples every 0.05 / 0.1 mm          | exact: an end 0.05 mm from a line touches   |
  | LR-10                                 | in lr_check.py                       | pcbtools.drc (kicad-cli), see test_drc      |
"""
import glob
import json
import os
import re

import numpy as np
import pytest

from pcbtools import boardio, fence, rules as R
from pcbtools.boards import v2, v2_arms
import pcbtools.check as CK

HERE = os.path.dirname(os.path.abspath(__file__))
GOLD = os.path.join(HERE, '..', 'golden', 'v2-8a1f7ac')
ARR = os.path.join(HERE, '..', 'fixtures', 'arrays')

LR_BOARDS = sorted(os.path.basename(p)[:-len('.lr_check.json')] for p in glob.glob(os.path.join(GOLD, '*.lr_check.json')))
ROWS = [n for n, _ in R.ROWS]
assert len(LR_BOARDS) == 6 and len(ROWS) == 12          # a floor: a glob that matched nothing must not pass


def gold(board):
    with open(os.path.join(GOLD, f'{board}.lr_check.json')) as f:
        return {r['name']: r for r in json.load(f)['rows']}


def arrays(board):
    return boardio.load_npz(os.path.join(ARR, f'{board}.npz'))


# (board, row) -> the printed figure sits on a rounding boundary: {figure key: exact value}
DIFFS = {
    ('v2-awg-bc96e334', 'LR-4 INV_MAX'): {'CH2_OUT': 1.45},
    ('v2-awg-bc96e334', 'LR-7'): {'dac0_mm': 1.85},
    ('v2-power-a5605a04', 'LR-4 INV_MAX'): {'CH2_OUT': 1.45},
    ('v2-power3-7c838703', 'LR-4 INV_MAX'): {'CH2_OUT': 1.45},
    ('v2-refcal-326f141b', 'LR-4 INV_MAX'): {'CH2_OUT': 1.45},
}


@pytest.mark.parametrize('board', LR_BOARDS)
@pytest.mark.parametrize('row', ROWS)
def test_verdict_and_detail_match_the_old_tool(board, row):
    old = gold(board)[row]
    new = dict(R.ROWS)[row](arrays(board), v2)
    assert ('PASS' if new.ok else 'FAIL') == old['verdict'], (new.detail, old['detail'])
    if (board, row) in DIFFS:
        assert new.detail != old['detail'], 'stale DIFFS entry: the details agree now'
        for key, exact in DIFFS[(board, row)].items():
            assert new.figures[key] == pytest.approx(exact, abs=1e-9)           # the value is the boundary value
        assert re.sub(r'\d', '#', new.detail) == re.sub(r'\d', '#', old['detail']), 'more than a digit differs'
    else:
        assert new.detail == old['detail']


FIG = re.compile(r'(\d+(?:\.\d+)?)')


@pytest.mark.parametrize('board', LR_BOARDS)
def test_figures_agree_with_the_old_printed_ones(board):
    """every number the old tool printed for a row is the new float rounded to the same digits (boundary rows excepted)"""
    g, b = gold(board), arrays(board)
    r = R.lr4_inv(b, v2)
    for lab, val in re.findall(r'(AWG_FB|CH1_OUT|CH2_OUT) (\d+\.\d) mm', g['LR-4 INV_MAX']['detail']):
        if (board, 'LR-4 INV_MAX') not in DIFFS or lab != 'CH2_OUT':
            assert f'{r.figures[lab]:.1f}' == val
    r = R.lr12(b, v2)
    old = dict(re.findall(r'(C\d+>U\d+\.\d) (\d+\.\d)', g['LR-12 DECOUP_MAX']['detail']))
    old |= {f'{c}>{v2.DECOUP[c][0]}.{v2.DECOUP[c][1]}': d for c, d in re.findall(r'(C\d+) is (\d+\.\d) mm from', g['LR-12 DECOUP_MAX']['detail'])}
    assert old
    for k, val in old.items():
        assert f'{r.figures[k]:.1f}' == val, k
    r = R.lr4(b, v2)
    m = re.search(r'\((\d+)/(\d+) mm\); FB node (\d+\.\d) mm', g['LR-4']['detail'])
    assert (f'{r.figures["a0_mm"]:.0f}', f'{r.figures["a1_mm"]:.0f}', f'{r.figures["fb_mm"]:.1f}') == m.groups()
    assert f'{R.lr2(b, v2).figures["divider_gap_mm"]:.1f}' == re.search(r'pads (\d+\.\d) mm', g['LR-2']['detail']).group(1)


def test_golden_figures_were_reparsed_and_hold_both_numbers_of_a_slash_group():
    d = json.load(open(os.path.join(GOLD, 'v2-integrated-990d4b03.lr_check.json')))
    assert d['figures_reparsed'] is True and d['raw']
    lr4 = next(r for r in d['rows'] if r['name'] == 'LR-4')
    assert [f['value'] for f in lr4['figures']][:2] == [46.0, 58.0]


def test_lr5_distance_is_exact_not_sampled():
    """the old tool's nearest sample point can only be farther than the exact distance: figure_new <= figure_old"""
    for board in LR_BOARDS:
        b = arrays(board)
        m = re.search(r'sensitive copper >= (\d+\.\d)', gold(board)['LR-5']['detail'])
        assert m and R.lr5(b, v2).figures['min_distance_mm'] >= float(m.group(1)) - 1e-9     # passes: both are above the limit


# ------------------------------------------------------------------------------------------------ mutation arms
ARMS = v2_arms.ARMS


def test_the_old_arms_are_all_ported():
    old = [l.split(' (clean board')[0].split('] ', 1)[1] for l in
           json.load(open(os.path.join(GOLD, 'v2-integrated-990d4b03.lr_check_mutate.json')))['raw'].splitlines() if l.startswith('[')]
    names = [a[0] for a in ARMS]
    assert len(old) == 28 and old[-1].startswith('LR-10')
    assert set(old[:-1]) <= set(names)                                          # the 27 numpy arms of the old tool
    assert len(ARMS) == 28 and len(set(names)) == 28                            # 27 + 'LR-4 top GND zone near FB'


def _clean_board(rule):
    """the integrated board, except for LR-11, which fails on it before any arm: its arms run on the refcal block board"""
    return arrays('v2-refcal-326f141b' if rule is R.lr11 else 'v2-integrated-990d4b03')


@pytest.mark.parametrize('name, rule, arm', ARMS, ids=[a[0] for a in ARMS])
def test_every_arm_flips_its_rule_from_pass_to_fail(name, rule, arm):
    b = _clean_board(rule)
    assert rule(b, v2).ok, f'the clean board must pass {name}: {rule(b, v2).detail}'
    mutated = arm(b, v2)
    assert mutated is not b
    r = rule(mutated, v2)
    assert not r.ok, f'{name}: NOT CAUGHT'
    assert r.detail != rule(b, v2).detail


def test_the_arms_leave_the_clean_board_alone():
    b = arrays('v2-integrated-990d4b03')
    before = {n: np.array(getattr(b, n), copy=True) for n in ('s_x0', 'v_x', 'p_net', 'fp_x', 'z_xy') }
    for _, _, arm in ARMS:
        arm(b, v2)
    for n, v in before.items():
        assert np.array_equal(getattr(b, n), v)


def test_arm_output_equals_the_old_tool_line_for_line():
    """the --mutate output of the old tool on the integrated board, minus the two designed differences"""
    old = json.load(open(os.path.join(GOLD, 'v2-integrated-990d4b03.lr_check_mutate.json')))['raw'].splitlines()
    lines = []
    CK.run_arms(arrays('v2-integrated-990d4b03'), v2, [a for a in ARMS if a[0] != 'LR-4 top GND zone near FB'], out=lines.append)
    assert len(lines) == len(old) - 1                                           # no LR-10 arm line, and the summary
    for a, b in zip(old, lines):
        if 'pour near FB' in a:
            assert a.replace("['added ground copper']", "['GND track']") == b
        elif a.startswith('every arm caught'):
            assert b == a
        elif 'LR-10' not in a:
            assert a == b


# ------------------------------------------------------------------------------------------------ fence
FENCE_CASES = [('v2-awg-bc96e334', 'AWG'), ('v2-power-a5605a04', 'POWER'), ('v2-power3-7c838703', 'POWER'),
               ('v2-refcal-326f141b', 'REFCAL'), ('v2-scope2east-05ee441f', 'SCOPE')]


@pytest.mark.parametrize('board, block', FENCE_CASES)
def test_fence_verdict_matches_fence_check(board, block):
    g = json.load(open(os.path.join(GOLD, f'{board}.fence_check.json')))
    r = fence.check_fence(arrays('v2-BASE-056e1d03'), arrays(board), block, v2)
    assert r.ok == g['clean']
    assert r.violations == g['violations']                                       # same wording, same order
    assert fence.violations(arrays('v2-BASE-056e1d03'), arrays(board), block, v2) == g['violations']
    n_copper = sum(len(v) for d in r.outside_changed_idx.values() for v in d.values())
    assert n_copper == len(g['violations'])                                       # one violation per changed outside item here
    assert r.foreign_moved == []


def test_fence_cases_include_both_clean_and_dirty():
    verdicts = {json.load(open(os.path.join(GOLD, f'{b}.fence_check.json')))['clean'] for b, _ in FENCE_CASES}
    assert verdicts == {True, False}


# ------------------------------------------------------------------------------------------------ the command line
def test_cli_prints_the_old_lines(capsys):
    npz = os.path.join(ARR, 'v2-integrated-990d4b03.npz')
    rc = CK.main([npz, '--config', 'v2'])
    out = capsys.readouterr().out.splitlines()
    old = json.load(open(os.path.join(GOLD, 'v2-integrated-990d4b03.lr_check.json')))['raw'].splitlines()
    assert rc == 1
    assert [l for l in out if 'LR-10' not in l] == [l for l in old if 'LR-10' not in l and not l.startswith('FAIL:')] + ['FAIL: LR-11']
    assert any(l.startswith('[SKIP] LR-10') for l in out)


def test_cli_all_pass_and_rows_and_exit_codes(capsys):
    npz = os.path.join(ARR, 'v2-integrated-990d4b03.npz')
    assert CK.main([npz, '--rows', 'LR-1', 'LR-5']) == 0
    out = capsys.readouterr().out
    assert out.count('[PASS]') == 2 and 'ALL PASS' in out
    assert CK.main(['/nonexistent.npz']) == 2
    assert CK.main([npz, '--config', 'nope']) == 2
    capsys.readouterr()
    assert CK.main([npz, '--mutate', '--rows', 'LR-5']) == 0
    assert 'every arm caught' in capsys.readouterr().out


def test_cli_mutate_reports_an_arm_that_is_not_caught(capsys):
    b = arrays('v2-integrated-990d4b03')
    miss = CK.run_arms(b, v2, [('does nothing', R.lr5, lambda b, c: b)])
    assert miss == ['does nothing']
    out = capsys.readouterr().out
    assert '[NOT CAUGHT] does nothing' in out and out.strip().endswith('NOT CAUGHT: does nothing')
