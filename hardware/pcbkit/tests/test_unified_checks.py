"""The checks pcbkit.labels shares with pcbkit.rules and pcbkit.outlines, on boxes: the one two-way core, the region rule, the baseline rule. Each is broken on purpose."""
import pytest
from pcbkit import rules, outlines


def test_two_way_core_flags_a_label_nearer_another_part_and_a_part_nearer_another_label():
    solid = {'R1': [(0, 0, 1, 1)], 'R2': [(0, 3, 1, 4)]}
    ok = rules.two_way_core(solid, {'R1': [(0, 1.2, 1, 2.0)], 'R2': [(0, 4.2, 1, 5.0)]}, ('U',), 0.15, 0.0)
    assert all(not s1 and not s2 for _, s1, s2 in ok.values())
    near = rules.two_way_core(solid, {'R1': [(0, 2.0, 1, 2.9)]}, ('U',), 0.15, 0.0)         # R1's label sits 0.1 from R2 and 1.0 from R1
    assert near['R1'][1] is not None
    a = rules.two_way_core(solid, {'R1': [(0, 1.1, 1, 1.9)], 'R2': [(0, 1.0, 1, 1.9)]}, ('U',), 0.15, 0.0)      # R2's label hangs on R1
    assert a['R1'][2] is not None
    assert rules.two_way_core(solid, {'R1': [(0, 2.0, 1, 2.9)]}, ('U',), 0.15, 5.0)['R1'][1] is None    # the allowance (EPS) is applied


def test_anchors_are_compared_only_with_their_own_kind():
    solid = {'U1': [(0, 0, 1, 1)], 'R1': [(0, 2, 1, 3)]}
    lab = {'U1': [(0, 1.9, 1, 2.0)]}                        # nearer the resistor than the IC: fine for an anchor, a finding for a passive
    assert rules.two_way_core(solid, lab, ('U',), 0.15, 0.0)['U1'][1] is None
    assert rules.two_way_core(solid, lab, (), 0.15, 0.0)['U1'][1] is not None


def test_shares_baseline_is_the_one_label_rule():
    assert rules.shares_baseline(0, 1, 0.4, 1.4) and not rules.shares_baseline(0, 1, 0.6, 1.6)


OUT = {'A': [(0, 0, 10, 10)], 'B': [(20, 0, 30, 10)]}


def test_region_rule_each_branch():
    f = lambda lab, xy, blk, strays=(), ref=None, anchor=False, ao=False: outlines.label_region_findings(lab, xy, blk, OUT, strays, ref, 0.1, 0.0, anchor, ao)
    assert f((2, 2, 4, 3), (3, 3), 'A') == []                                            # inside its own rectangle
    assert f((9, 2, 12, 3), (3, 3), 'A')                                                 # part inside, label crossing the line
    assert f((11, 2, 13, 3), (3, 3), 'A', anchor=True) and f((11, 2, 13, 3), (3, 3), 'A', anchor=True, ao=True) == []     # an anchor may sit outside every rectangle when allowed
    assert f((21, 2, 23, 3), (3, 3), 'A', anchor=True, ao=True)                          # but not inside another block's
    assert f((2, 2, 4, 3), (12, 3), 'A')                                                 # a part outside its rectangle with its label inside it: a finding
    assert f((21, 2, 23, 3), (12, 3), 'A')                                               # a part outside its rectangle: its label in no rectangle
    assert f((21, 2, 23, 3), (12, 3), 'A', strays=('R9',), ref='R9')                     # a stray: not in another block's
    assert f((12, 2, 14, 3), (12, 3), 'A', strays=('R9',), ref='R9') == []
    assert f((2, 2, 4, 3), (12, 3), 'A', strays=('R9',), ref='R9') == []                  # a stray may have its label inside its own rectangle; any other part outside it may not
    assert f((2, 2, 4, 3), (50, 3), 'EDGE') == [] and f((21, 2, 23, 3), (50, 3), 'EDGE') == []      # an edge part: anywhere


def test_outline_line_checker_closed_edges_breaks_and_crossings():
    rects = {'A': [(0, 0, 10, 10)]}
    full = [(0, 0, 10, 0), (10, 0, 10, 10), (0, 10, 10, 10), (0, 0, 0, 10)]
    assert outlines.check_outline_lines(full, rects, [], 0.075, 0.2) == []
    assert outlines.check_outline_lines(full[1:], rects, [], 0.075, 0.2)                     # an edge missing with nothing there
    assert outlines.check_outline_lines(full, rects, [(4, -0.1, 5, 0.1)], 0.075, 0.2)        # a line across a pad
    broken = [(0, 0, 3.8, 0), (5.2, 0, 10, 0)] + full[1:]
    assert outlines.check_outline_lines(broken, rects, [(4, -0.1, 5, 0.1)], 0.075, 0.2) == []     # broken 0.2 clear each side
    tight = [(0, 0, 3.95, 0), (5.05, 0, 10, 0)] + full[1:]
    assert outlines.check_outline_lines(tight, rects, [(4, -0.1, 5, 0.1)], 0.075, 0.2)       # 0.05 clear is not enough
    assert outlines.check_outline_lines([(0, 0, 3.95, 0), (5.2, 0, 10, 0)] + full[1:], rects, [(4, -0.1, 5, 0.1)], 0.075, 0.2)     # too short on the start side only
    assert outlines.check_outline_lines([(0, 0, 3.8, 0), (5.05, 0, 10, 0)] + full[1:], rects, [(4, -0.1, 5, 0.1)], 0.075, 0.2)     # and on the end side only
    assert outlines.check_outline_lines(full + [full[0]], rects, [], 0.075, 0.2)             # a line drawn twice
