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
  | LR-4 top-pour test                    | HitTestFilledArea(accuracy 0.02 mm)  | exact edge distance to the fill (finding 9) |
  | LR-6/LR-8 touch tests                 | samples every 0.05 / 0.1 mm          | exact: an end 0.05 mm from a line touches   |
  | LR-10                                 | in lr_check.py                       | pcbtools.drc (kicad-cli), see test_drc      |

The differences that are IMPROVEMENTS (the review of the port: bridge-joined nets, unrouted nets, both layers and zones, the exact
pour gap) are data in known_improvements.py. Exactly those are explained: a difference not listed there fails, and a listed one
that no longer differs fails (a stale entry).
"""
import glob
import json
import os
import re

import numpy as np
import pytest

from pcbtools import boardio, fence, mutate as M, rules as R
from pcbtools.boards import v2, v2_arms
import pcbtools.check as CK
import known_improvements as KI

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
    if (board, row) in KI.KNOWN:
        k = KI.KNOWN[(board, row)]
        assert old['verdict'] == k['old'], 'the entry names a golden verdict that is not the golden one'
        assert ('PASS' if new.ok else 'FAIL') == k['new'], (new.detail, k)
        assert k['contains'] in new.detail, new.detail
        assert new.detail != old['detail'], 'stale known improvement: the new detail equals the golden one'
        assert (board, row) not in DIFFS
        return
    assert ('PASS' if new.ok else 'FAIL') == old['verdict'], (new.detail, old['detail'])
    if (board, row) in DIFFS:
        assert new.detail != old['detail'], 'stale DIFFS entry: the details agree now'
        for key, exact in DIFFS[(board, row)].items():
            assert new.figures[key] == pytest.approx(exact, abs=1e-9)           # the value is the boundary value
        assert re.sub(r'\d', '#', new.detail) == re.sub(r'\d', '#', old['detail']), 'more than a digit differs'
    else:
        assert new.detail == old['detail']


def test_known_improvements_are_listed_for_real_cells_only():
    cells = {(b, r) for b in LR_BOARDS for r in ROWS}
    assert set(KI.KNOWN) <= cells and len(KI.KNOWN) >= 10                          # a floor: the data was not emptied
    assert {k['finding'] for k in KI.KNOWN.values()} == {1, 2}


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
    dec = {c: (ic, pin) for c, ic, pin in v2.DECOUP}
    old |= {f'{c}>{dec[c][0]}.{dec[c][1]}': d for c, d in re.findall(r'(C\d+) is (\d+\.\d) mm from', g['LR-12 DECOUP_MAX']['detail'])}
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
    assert len(v2_arms.OLD_ARMS) == 28 and len(set(names)) == len(ARMS)         # 27 + 'LR-4 top GND zone near FB'; the new arms have new names
    assert len(v2_arms.NEW_ARMS) >= 12 and not {a[0] for a in v2_arms.NEW_ARMS} & set(old)


def _clean_board(rule):
    """a board on which the rule PASSES, which an arm needs to show a flip. The integrated board, except: LR-11 fails on it before any
    arm (its arms run on the refcal block board)"""
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
    """the --mutate output of the old tool on the integrated board, minus the designed differences: the one extra arm, the LR-10 arm,
    and the arms that are now reported NOT TESTABLE (known_improvements.ARM_NOT_TESTABLE: the rule fails on the clean board)"""
    old = json.load(open(os.path.join(GOLD, 'v2-integrated-990d4b03.lr_check_mutate.json')))['raw'].splitlines()
    lines = []
    CK.run_arms(arrays('v2-integrated-990d4b03'), v2, [a for a in v2_arms.OLD_ARMS if a[0] != 'LR-4 top GND zone near FB'],
                out=lines.append, no_drc=True)
    assert lines[-2].startswith('[SKIP] LR-10 arm') and len(lines) == len(old) == 29          # 27 arms, the LR-10 line, the summary
    seen, seen_text = set(), set()
    for a, b in zip(old, lines):
        if 'LR-10' in a:
            continue
        if a.startswith('every arm caught'):
            assert b.startswith('NOT TESTABLE on this board: ') and not b.startswith('every arm caught')
            continue
        name = a.split('] ', 1)[1].split(' (clean board')[0]
        if name in KI.ARM_NOT_TESTABLE:
            seen.add(name)
            assert b.startswith(f'[NOT TESTABLE on this board] {name} (clean board: fail')
            continue
        if name in KI.ARM_TEXT:
            seen_text.add(name)
            head = f'[FAILED AS REQUIRED] {name} (clean board: pass): '
            assert a.startswith(head) and b.startswith(head) and a != b
        elif 'pour near FB' in a:
            assert a.replace("['added ground copper']", "['GND track']") == b
        else:
            assert a == b
    assert seen == set(KI.ARM_NOT_TESTABLE) and seen_text == set(KI.ARM_TEXT)


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
    """the row lines are the old tool's, except LR-4 (finding 9, known_improvements); the LR-10 row and the summary say that DRC did
    not run, and the run is not a pass"""
    npz = os.path.join(ARR, 'v2-integrated-990d4b03.npz')
    rc = CK.main([npz, '--config', 'v2'])
    out = capsys.readouterr().out.splitlines()
    old = json.load(open(os.path.join(GOLD, 'v2-integrated-990d4b03.lr_check.json')))['raw'].splitlines()
    assert rc == 1
    body = [l for l in out if 'LR-10' not in l and not l.startswith('FAIL:')]
    want = [l for l in old if 'LR-10' not in l and not l.startswith('FAIL:')]
    assert len(body) == len(want)
    for a, b in zip(body, want):
        assert a == b
    assert any(l.startswith('[NOT RUN] LR-10') for l in out)
    assert out[-1] == 'FAIL: LR-11; LR-10 NOT RUN'


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
    miss = CK.run_arms(b, v2, [('does nothing', R.lr5, lambda b, c: b)], no_drc=True)
    assert miss == ['does nothing']
    out = capsys.readouterr().out
    assert '[NOT CAUGHT] does nothing' in out and out.strip().endswith('NOT CAUGHT: does nothing')
