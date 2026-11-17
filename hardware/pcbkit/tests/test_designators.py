"""rules.designators (silk requirement, legibility terms, the two-way nearest test) on boards built here from numbers; each broken once on purpose."""
import pytest

from arrays import Arr
from pcbkit import board as K
from pcbkit import rules
from pcbkit.config import ConfigError

REQ = dict(SILK_REQUIRED_PREFIXES=('U', 'J', 'TP', 'D'), DESIGNATOR_MIN_H=0.8)


def silk_board():
    return (Arr().part('U1', 0, 0).label('U1', 0, 2).part('R1', 10, 0).label('R1', 10, 2, layer=2).part('R2', 20, 0).label('R2', 20, 2)
            .part('C1', 30, 0).part('J1', 40, 0).label('J1', 40, 2, h=0.7).part('D1', 50, 0).label('D1', 50, 2, layer=2))


# ---------------------------------------------------------------------------------------------- silk required
def test_silk_required_anchors_passives_and_the_height_floor():
    bad, noff, n = rules.silk_required_parts(silk_board().build(), REQ)
    assert n == 6 and noff == 1                                               # R1's designator is on F.Fab: allowed for a passive
    assert bad == [('C1', False), ('J1', True), ('D1', True)]                  # C1 has none (and is not on F.Fab), J1 is too small, D1 is an anchor on F.Fab


def test_a_passive_may_have_no_silk_but_must_have_a_fab_one_and_None_means_every_part_is_an_anchor():
    b = silk_board().build()
    r = rules.designators(b, {**REQ, 'LABEL_TEXTS': {}}) if False else None
    bad, _, _ = rules.silk_required_parts(b, dict(SILK_REQUIRED_PREFIXES=None, DESIGNATOR_MIN_H=0.8))
    assert ('R1', True) in bad and ('C1', True) in bad
    bad, _, _ = rules.silk_required_parts(b, {**REQ, 'DESIGNATOR_MIN_H': 0.6})
    assert ('J1', True) not in bad                                            # 0.7 >= 0.6


def test_silk_required_project_names_raise():
    b = silk_board().build()
    for k in REQ:
        with pytest.raises(ConfigError, match=k):
            rules.silk_required_parts(b, {kk: v for kk, v in REQ.items() if kk != k})


# ---------------------------------------------------------------------------------------------- legibility terms
LEG = dict(BLOCK={}, OUTLINE={}, DESIGNATOR_GAP_MIN=0.2, DESIGNATOR_DIST_MAX=3.0)


def leg_board(x2=10.0, y2=2.0):
    # R1 and R2 each 0.4 pad at the origin, labels 1.9 x 1.2 boxes
    return Arr('N').part('R1', 0, 0).p('R1', '1', 0, 0, 'N', size=0.8).label('R1', 0, 2).part('R2', x2, 0).p('R2', '1', x2, 0, 'N', size=0.8).label('R2', x2, y2)


def test_two_designators_closer_than_the_gap_are_a_finding():
    close, over, far, n = rules.designator_findings(leg_board(x2=2.0).build(), LEG)       # boxes x -0.95..0.95 and 1.05..2.95: gap 0.1
    assert n == 2 and close == [('R1', 'R2', 0.1)]
    assert rules.designator_findings(leg_board(x2=2.3).build(), LEG)[0] == []             # gap 0.4
    assert rules.designator_findings(leg_board(x2=2.3).build(), {**LEG, 'DESIGNATOR_GAP_MIN': 0.5})[0] == [('R1', 'R2', 0.4)]


def test_a_label_over_another_parts_pad_and_far_from_its_own_are_findings():
    a = Arr('N').part('R1', 0, 0).p('R1', '1', 0, 0, 'N', size=0.8).label('R1', 6, 0).part('R2', 6, 0).p('R2', '1', 6, 0, 'N', size=0.8)
    close, over, far, n = rules.designator_findings(a.build(), LEG)
    assert over == [('R1', 'R2')] and far == [('R1', 4.65)] and n == 1                      # box x 5.05..6.95 lies on R2's pad; 5.05 - 0.4 from R1's own
    assert rules.designator_findings(a.build(), {**LEG, 'DESIGNATOR_DIST_MAX': 5.0})[2] == []


def test_two_labels_on_one_baseline_read_as_one_label():
    assert rules.one_label_pairs(leg_board(x2=2.0).build(), LEG) == [('R1', 'R2', 0.1)]
    assert rules.one_label_pairs(leg_board(x2=2.0, y2=2.7).build(), LEG) == []             # another baseline (vertical overlap 0.5 < half a box)
    assert rules.one_label_pairs(leg_board(x2=2.7).build(), LEG) == []                     # gap 0.8 >= 0.6
    assert rules.one_label_pairs(leg_board(x2=2.7).build(), {**LEG, 'DESIGNATOR_GAP_ONE_LABEL': 1.0}) == [('R1', 'R2', 0.8)]


def test_a_designator_inside_another_blocks_outline_is_foreign_unless_waived_shared_or_edge():
    out = {'A': [(-5, -5, 5, 5)], 'B': [(-5, 1.5, 5, 2.5)]}                                 # R1's label centre (0, 2) lies in B
    cfg = {**LEG, 'BLOCK': {'R1': 'A', 'R2': 'B'}, 'OUTLINE': out}
    a = leg_board(x2=30.0, y2=100.0).build()
    assert rules.foreign_labels(a, cfg) == [('R1', 'B')]
    assert rules.foreign_labels(a, {**cfg, 'DESIGNATOR_FOREIGN_WAIVED': {'R1': 'B'}}) == []
    assert rules.foreign_labels(a, {**cfg, 'SHARED_PARTS': {'R1': 'A'}}) == []
    assert rules.foreign_labels(a, {**cfg, 'BLOCK': {'R1': 'EDGE', 'R2': 'B'}, 'EDGE_BLOCK': 'EDGE'}) == []
    assert rules.foreign_labels(a, {**cfg, 'BLOCK': {'R1': 'EDGE', 'R2': 'B'}, 'EDGE_BLOCK': 'EDGE', 'BLOCK_OVERRIDE': ['R1']}) == []     # an overridden part is not judged here either
    assert rules.foreign_labels(a, {**cfg, 'BLOCK': {'R2': 'B'}}) == []                    # a part with no block of its own is not judged


def test_legibility_project_names_raise_and_the_box_tunables_default():
    a = leg_board().build()
    for k in ('BLOCK', 'OUTLINE', 'DESIGNATOR_GAP_MIN', 'DESIGNATOR_DIST_MAX'):
        with pytest.raises(ConfigError, match=k):
            rules.designator_findings(a, {kk: v for kk, v in LEG.items() if kk != k})
    rep = []
    rules.designator_findings(a, LEG, rep)
    got = {k: (v, s) for k, v, s in rep}
    assert got['DESIGNATOR_ADVANCE'] == (0.95, 'default') and got['DESIGNATOR_INK_H'] == (1.2, 'default') and got['DESIGNATOR_GAP_MIN'] == (0.2, 'project')


# ---------------------------------------------------------------------------------------------- the two-way test
TW = dict(SILK_REQUIRED_PREFIXES=('U', 'J', 'TP', 'D'))


def tw_part(a, ref, x, y, label=None, ang=0.0):
    a.part(ref, x, y).p(ref, '1', x, y, 'N', size=0.8).body(ref, x - 0.8, y - 0.4, x + 0.8, y + 0.4)
    if label:
        a.label(ref, *label, ang=ang)
    return a


def tw_base():
    return tw_part(tw_part(Arr('N'), 'R1', 0, 0, (0, 1.5)), 'R2', 10, 0, (10, 1.5))


def test_a_clear_board_passes_and_the_own_distance_is_measured_to_the_solid():
    out = rules.two_way_test(tw_base().build(), TW)
    assert sorted(out) == ['R1', 'R2'] and out['R1'] == (pytest.approx(0.5), None, None)         # label box y 0.9..2.1 above the body's 0.4


def test_step_1_from_the_label_another_part_nearer_than_the_own_part_plus_the_margin():
    a = tw_part(tw_base(), 'R3', 0, 3.1)                                      # R3's body at 2.7: 0.6 from the label, own is 0.5; 0.5 + 0.15 > 0.6
    own, s1, s2 = rules.two_way_test(a.build(), TW)['R1']
    assert s1 and s1[1] == 'R3' and s1[2] == pytest.approx(0.5) and s1[3] == pytest.approx(0.6) and s2 is None
    assert rules.two_way_test(tw_part(tw_base(), 'R3', 0, 3.2).build(), TW)['R1'][1] is None          # 0.7 >= 0.65
    assert rules.two_way_test(a.build(), {**TW, 'READ_MARGIN': 0.05})['R1'][1] is None


def test_step_2_from_the_part_another_label_nearer_than_its_own_label_plus_the_margin():
    a = tw_part(tw_base(), 'R4', 0, -3.0, (0, -1.5))                          # R4's label box -2.1..-0.9 is 0.5 from R1's body, as R1's own label
    own, s1, s2 = rules.two_way_test(a.build(), TW)['R1']
    assert s2 and s2[1] == 'R4' and s2[2] == pytest.approx(0.5) and s2[3] == pytest.approx(0.5)


def test_an_anchor_is_compared_only_with_its_own_kind_and_a_passive_with_all():
    anchor = tw_part(tw_part(Arr('N'), 'U1', 0, 0, (0, 1.5)), 'R3', 0, 3.1)           # a passive nearer than the margin: not a rival for an anchor
    assert rules.two_way_test(anchor.build(), TW)['U1'][1] is None
    passive = tw_part(tw_part(Arr('N'), 'R1', 0, 0, (0, 1.5)), 'U3', 0, 3.1)           # an anchor nearer than the margin: a rival for a passive
    assert rules.two_way_test(passive.build(), TW)['R1'][1][1] == 'U3'
    two = tw_part(tw_part(Arr('N'), 'U1', 0, 0, (0, 1.5)), 'U3', 0, 3.1)               # same kind: a rival
    assert rules.two_way_test(two.build(), TW)['U1'][1][1] == 'U3'
    tp = tw_part(tw_part(Arr('N'), 'TP1', 0, 0, (0, 1.5)), 'U3', 0, 3.1)               # the longest prefix: TP is not U
    assert rules.two_way_test(tp.build(), TW)['TP1'][1] is None


def test_step_2_an_anchors_own_label_is_compared_only_with_labels_of_its_own_kind():
    a = tw_part(tw_part(Arr('N'), 'U1', 0, 0, (0, 1.5)), 'R4', 0, -3.0, (0, -1.5))     # a passive's label as near U1 as U1's own label
    assert rules.two_way_test(a.build(), TW)['U1'][2] is None
    b = tw_part(tw_part(Arr('N'), 'R1', 0, 0, (0, 1.5)), 'U4', 0, -3.0, (0, -1.5))     # an anchor's label as near R1 as R1's own: a rival for a passive
    assert rules.two_way_test(b.build(), TW)['R1'][2][1] == 'U4'


def test_a_label_text_counts_as_part_of_its_parts_label_and_the_turned_box_is_vertical():
    a = tw_part(Arr('N'), 'J1', 0, 0, (0, 5.0))
    far = rules.two_way_test(a.build(), TW)['J1'][0]
    assert far == pytest.approx(4.0)                                           # box y 4.4..5.6 from the body at 0.4
    near = tw_part(Arr('N'), 'J1', 0, 0, (0, 5.0)).text('CH1 IN', -1, 1.0, 1, 2.0)
    assert rules.two_way_test(near.build(), {**TW, 'LABEL_TEXTS': {'CH1 IN': 'J1'}})['J1'][0] == pytest.approx(0.6)
    assert rules.two_way_test(near.build(), TW)['J1'][0] == pytest.approx(4.0)         # not mapped: not a label
    ghost = tw_part(Arr('N'), 'J1', 0, 0, (0, 5.0)).text('CH9 IN', -1, 1.0, 1, 2.0)
    assert 'ZZ9' not in rules.two_way_test(ghost.build(), {**TW, 'LABEL_TEXTS': {'CH9 IN': 'ZZ9'}})              # a text for a part that is not on the board
    v = tw_part(Arr('N'), 'R1', 0, 0, (3.0, 0.0), ang=90.0)                        # turned: 1.2 wide, 1.9 tall: x 2.4..3.6
    assert rules.two_way_test(v.build(), TW)['R1'][0] == pytest.approx(1.6)


def test_hidden_and_fab_designators_are_not_labels_and_a_part_without_one_is_not_judged():
    a = tw_part(tw_base(), 'R5', 20, 0)
    a.label('R5', 20, 1.5, silk=False)
    assert sorted(rules.two_way_test(a.build(), TW)) == ['R1', 'R2']
    f = tw_part(Arr('N'), 'R1', 0, 0).label('R1', 0, 1.5, layer=2)
    assert rules.two_way_test(f.build(), TW) == {}


def test_the_fields_of_a_pcbkit_read_are_required_and_the_project_names_raise():
    b = tw_base().build().replace(read_fields=frozenset())
    with pytest.raises(K.FieldNotRead, match='fp_fab_x0'):
        rules.two_way_test(b, TW)
    with pytest.raises(ConfigError, match='SILK_REQUIRED_PREFIXES'):
        rules.two_way_test(tw_base().build(), {})
    rep = []
    rules.two_way_test(tw_base().build(), TW, rep)
    got = {k: (v, s) for k, v, s in rep}
    assert got['READ_MARGIN'] == (0.15, 'default') and got['LABEL_TEXTS'] == ({}, 'default')


def test_designators_composes_the_silk_requirement_and_the_two_way_test():
    ok = tw_base()
    r = rules.designators(ok.build(), {**REQ, **TW})
    assert r.ok and r.detail == '2 designators, 2 silk labels pass the two-way test'
    a = tw_part(tw_base(), 'R3', 0, 3.1)
    r = rules.designators(a.build(), {**REQ, **TW})
    assert not r.ok and 'R1: from its label, R3 is at 0.60 mm and its own part at 0.50' in r.detail and r.figures['violations'] == 2.0      # and R3 has no designator
    r = rules.designators(silk_board().build(), {**REQ, **TW})
    assert not r.ok and 'C1: designator not on silk at 0.8 mm or more, and not on F.Fab either' in r.detail
