"""The shared layout rules on the v1 board (pcbtools.boards.v1 / v1_arms) against the old v1 tool's goldens, taken in the image
(tests/golden/v1-34b2e51-image/lr_check.out and lr_check_mutate.out): the same board, row by row, and arm by arm.

What the shared rules (v2's shapes, pcbtools/CONFIG_FIELDS.md) change on the v1 board, and the test holds each to its reason:
  * the decoupling distance is its own row, LR-12, per named cap: old 'LR-4 FAIL (nearest C103 at 3.7 mm)' is now LR-4 PASS and
    LR-12 FAIL 'C103 is 3.7 mm from U101 pin 8'.
  * LR-6 / LR-8 say 'not connected to the star / the source by copper' where the old text said 'is not one piece': the same
    unrouted board fails the same rows.
  * LR-11 judges the six bridges: R109 (a CH1 bridge) lies inside the REFCAL fence at its floorplan point, which the old tool
    exempted; it is the one extra reason over the old output (R108 in REFCAL, D201 / R108 missing from SCOPE, C306 from AWG stay).
  * dropped arms (the shared rules do not look at that): LR-9 SCL1 inside the AWG fence, LR-11 test point in the wrong block.
"""
import os
import re
import shutil
import types

import pytest

from pcbtools import boardio, check as CK, rules as R
from pcbtools.boards import v1, v1_arms

HERE = os.path.dirname(os.path.abspath(__file__))
FX = os.path.join(HERE, '..', 'fixtures', 'v1-34b2e51', 'kicad')
GOLD = os.path.join(HERE, '..', 'golden', 'v1-34b2e51-image')

pytestmark = pytest.mark.pcbnew


def _golden(name):
    return open(os.path.join(GOLD, name + '.out')).read()


@pytest.fixture(scope='module')
def board(tmp_path_factory):
    """the frozen v1 board, read once from a throw-away copy (a pcbnew read leaves .kicad_prl beside the file)"""
    d = tmp_path_factory.mktemp('v1board')
    shutil.copy(os.path.join(FX, 'afe-proto.kicad_pcb'), d)
    return boardio.read_board(str(d / 'afe-proto.kicad_pcb'))


def _cfg(**over):
    c = types.SimpleNamespace(**{k: v for k, v in vars(v1).items() if k.isupper()})
    for k, v in over.items():
        setattr(c, k, v)
    return c


def test_every_row_has_the_old_tools_verdict(board):
    old = {row: verdict for verdict, row in re.findall(r'\[(PASS|FAIL)\] (LR-\d+):', _golden('lr_check'))}
    new = {n: fn(board, v1) for n, fn in R.ROWS}
    for row in ('LR-1', 'LR-2', 'LR-3', 'LR-5', 'LR-6', 'LR-7', 'LR-8', 'LR-9', 'LR-11'):
        assert (old[row] == 'PASS') == new[row].ok, row
    assert old['LR-4'] == 'FAIL' and new['LR-4'].ok and not new['LR-12 DECOUP_MAX'].ok
    assert 'C103 is 3.7 mm from U101 pin 8' in new['LR-12 DECOUP_MAX'].detail
    assert new['LR-4 INV_MAX'].ok


def test_the_reasons_name_the_same_defects(board):
    d = {n: fn(board, v1).detail for n, fn in R.ROWS}
    assert '45 SMD ground pads without a via' in d['LR-1'] and 'no bottom GND zone' in d['LR-1']
    assert d['LR-2'].count('is not longer than the divider side') == 2
    assert 'unreachable by copper' in d['LR-6'] and 'AWG' in d['LR-6'] and 'REF/ADS' in d['LR-6']
    assert 'not connected to the source' in d['LR-8']
    for x in ("REFCAL: outline holds ['R108', 'R109'] extra", "SCOPE: outline holds [] extra, lacks ['D201', 'R108']",
              "AWG: outline holds [] extra, lacks ['C306']"):
        assert x in d['LR-11']


def test_every_old_arm_is_here_or_declared_dropped():
    txt = _golden('lr_check_mutate')
    old = [m for m in re.findall(r'\[FAILED AS REQUIRED\] (.+?) \(rule on the prepared board', txt)]
    old += re.findall(r'\[REPAIR CLEARS IT\] (.+?): before', txt)
    new = {a[0].replace('REPAIR ', '') for a in v1_arms.ARMS}
    renamed = {'LR-4 100 nF far from U301.8': 'LR-12 100 nF far from U301.8', 'LR-11 silk and the three test points added': 'LR-11 silk added'}
    dropped = {'LR-9 SCL1 inside the AWG fence', 'LR-11 test point in the wrong block'}
    missing = [o for o in old if renamed.get(o, o) not in new and o not in dropped]
    assert not missing and len(old) == 48, (len(old), missing)
    assert len(v1_arms.ARMS) == 48 - len(dropped)


def test_every_arm_is_caught_on_the_clean_board(board, capsys):
    miss = CK.run_arms(board, v1, v1_arms.ARMS, no_drc=True, lr10_arm=False)
    out = capsys.readouterr().out
    assert miss == [] and CK.run_arms.untestable == [], out
    assert out.count('FAILED AS REQUIRED') == len(v1_arms.ARMS), out


# ---------------------------------------------------------------------------------------------------- break the checks on purpose
def _run(board, cfg, name):
    arms = [a for a in v1_arms.ARMS if a[0] == name]
    assert len(arms) == 1
    return CK.run_arms(board, cfg, arms, no_drc=True, lr10_arm=False)


@pytest.mark.parametrize('name,over', [
    ('LR-1 4 mm hop', dict(HOP_MAX=99.0)),                          # the limit loosened: the hop is no violation
    ('LR-3 16 mm of CH2_N', dict(HIZ=())),                          # the net no longer watched
    ('LR-7 DAC0 30 mm', dict(AWG=dict(v1.AWG, dac_net='/AWG_OUT'))),    # the rule pointed at another net
    ('LR-11 missing test point (AWG_OUT)', dict(TP_NETS={})),       # the test points no longer demanded
    ('LR-12 100 nF far from U301.8', dict(DECOUP=[])),              # the cap no longer named
])
def test_an_arm_fails_when_its_rule_is_broken(board, name, over):
    assert _run(board, _cfg(**over), name) == [name]


def test_the_keyword_gates_the_verdict(board):
    """a keyword the rule's reason does not contain is NOT CAUGHT, whatever else the rule says"""
    name, rule, arm = next(a for a in v1_arms.ARMS if a[0] == 'LR-1 4 mm hop')
    wrong = v1_arms._Keyed(R.lr1, 'no such words')
    assert CK.run_arms(board, v1, [(name, wrong, arm)], no_drc=True, lr10_arm=False) == [name]


def test_a_repair_that_repairs_nothing_is_not_testable_never_caught(board):
    """a repair that does not clear its reason cannot show the rule can pass: NOT TESTABLE (the facet has other causes), not NOT CAUGHT"""
    name, rule, fix = next(a for a in v1_arms.ARMS if a[0].startswith('REPAIR LR-1 '))
    miss = CK.run_arms(board, v1, [(name, v1_arms._Gone(R.lr1, 'without a via', lambda b, cfg: b), lambda b, cfg: b)], no_drc=True, lr10_arm=False)
    assert miss == [] and CK.run_arms.untestable == [name]


def test_a_repair_where_the_reason_is_not_there_is_not_testable(board):
    name, rule, fix = next(a for a in v1_arms.ARMS if a[0].startswith('REPAIR LR-1 '))
    CK.run_arms(board, v1, [(name, v1_arms._Gone(R.lr1, 'no such reason', fix), fix)], no_drc=True, lr10_arm=False)
    assert CK.run_arms.untestable == [name]


def test_a_mutant_is_not_prepared_twice(board):
    """_a preps before the mutation and the wrapper must not prep the mutant again (which would undo, e.g., the silk arm)"""
    name, rule, arm = next(a for a in v1_arms.ARMS if a[0] == 'LR-11 designator under 0.8 mm / not on silk')
    m = arm(board, v1)
    assert 'R101: designator not on silk' in rule(m, v1).detail
