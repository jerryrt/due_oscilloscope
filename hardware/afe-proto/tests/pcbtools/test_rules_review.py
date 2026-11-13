"""Known-answer tests for what the review of the port found (findings 1-10, 17), on hand-built boards: each defect has a board that
shows it, the figure checked exactly, and a mutation arm on the real fixture boards (tests/pcbtools/test_rules_equivalence.py runs
every arm of pcbtools.boards.v2_arms); tests/pcbtools/mutate_rules.py breaks each fix and requires these tests to fail.
No pcbnew, no fixtures except where a real board is named."""
import os

import numpy as np
import pytest

from pcbtools import boardio, check as CK, drc, mutate as M, rules as R, shapes
from pcbtools.boards import v2, v2_arms
from synth import Synth, cfg

SQ = lambda x0, y0, x1, y1: [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
HERE = os.path.dirname(os.path.abspath(__file__))
ARR = os.path.join(HERE, '..', 'fixtures', 'arrays')
FX = os.path.join(HERE, '..', 'fixtures', 'v2-8a1f7ac')


# ------------------------------------------------------------------------------------------------ 1, 2: LR-6 and LR-8
CB = cfg(GROUPS={'/R': {'scope': {'U1'}, 'awg': {'U2'}}}, STAR={'/R': [('U0', '1')]}, BRIDGE_PADS=[],
         BRIDGES=[('BR1', '/R', '/R_U')])


def rail_board(scope_leg=True, awg_leg=True, tie=None):
    """a star pad U0.1 on /R; the AWG consumer U2 on /R; the scope consumer U1 on /R_U, behind the 0 ohm bridge BR1 (pad 1 on /R,
    pad 2 on /R_U). `tie`: a track of that net joining U1 and U2 directly (the two groups share copper on the REAL nets)"""
    s = Synth('/R', '/R_U').part('U0', 0, 0).p('U0', '1', 0, 0, '/R')
    s.part('BR1', 5, 0).p('BR1', '1', 5, 0, '/R').p('BR1', '2', 6, 0, '/R_U')
    s.part('U1', 10, 0).p('U1', '1', 10, 0, '/R_U').part('U2', 0, 10).p('U2', '1', 0, 10, '/R')
    if scope_leg:
        s.s('/R', 'F', 0.2, 0, 5, 0).s('/R_U', 'F', 6, 0, 10, 0)
    if awg_leg:
        s.s('/R', 'F', 0, 0.2, 0, 10)
    if tie:
        s.s(tie, 'F', 10, 0, 0, 10)
    return s.build()


def test_lr6_sees_a_group_behind_a_bridge_and_keeps_the_groups_apart():
    r = R.lr6(rail_board(), CB)
    assert r.ok and r.figures['groups_reached'] == 2 and r.figures['groups_absent'] == 0
    assert R.family(CB, '/R') == {'/R', '/R_U'} and R.family(CB, '/R_U') == {'/R', '/R_U'}
    # the scope group's only pad is on /R_U: without the bridge table it is on no net the rule can find (the old blindness)
    r = R.lr6(rail_board(), cfg(GROUPS=CB.GROUPS, STAR=CB.STAR, BRIDGE_PADS=[], BRIDGES=[]))
    assert not r.ok and 'consumer group scope has no supply pad on the rail' in r.detail


@pytest.mark.parametrize('tie', ['/R', '/R_U'])
def test_lr6_two_groups_sharing_copper_on_the_real_nets_fail(tie):
    """a track of the bridged net, or of the star net, between the two consumers: no pad is re-netted"""
    r = R.lr6(rail_board(tie=tie), CB)
    assert not r.ok and r.detail == "/R: one piece of copper serves ['awg', 'scope']"


def test_lr6_an_unrouted_branch_fails_and_names_the_group():
    r = R.lr6(rail_board(scope_leg=False), CB)
    assert not r.ok and r.detail == '/R: consumer group scope is not connected to the star: U1.1 unreachable by copper'
    r = R.lr6(rail_board(awg_leg=False), CB)
    assert not r.ok and r.detail == '/R: consumer group awg is not connected to the star: U2.1 unreachable by copper'
    r = R.lr6(rail_board(scope_leg=False, awg_leg=False), CB)
    assert 'group scope' in r.detail and 'group awg' in r.detail


def test_lr6_a_group_whose_parts_are_not_on_the_board_is_absent_not_unreachable():
    s = Synth('/R', '/R_U').part('U0', 0, 0).p('U0', '1', 0, 0, '/R').part('U2', 0, 10).p('U2', '1', 0, 10, '/R').s('/R', 'F', 0, 0.2, 0, 10)
    r = R.lr6(s.build(), CB)
    assert r.ok and r.figures['groups_absent'] == 1 and r.figures['groups_reached'] == 1


C8 = cfg(VREF_SOURCE=[('U1', '1')], VREF_BRANCHES=[[('R1', '1')], [('R2', '1'), ('BR2', '1')]], BRIDGE_PADS=[], BRIDGES=[('BR2', '/VREF', '/VREF_M')])


def vref_board(leg1=True, leg2=True, tie=False):
    s = Synth('/VREF', '/VREF_M').part('U1', 0, 0).p('U1', '1', 0, 0, '/VREF').part('R1', 10, 0).p('R1', '1', 10, 0, '/VREF')
    s.part('R2', 0, 10).p('R2', '1', 0, 10, '/VREF_M').part('BR2', 0, 6).p('BR2', '1', 0, 6, '/VREF').p('BR2', '2', 0, 7, '/VREF_M')
    if leg1:
        s.s('/VREF', 'F', 0.2, 0, 10, 0)
    if leg2:
        s.s('/VREF', 'F', 0, 0.2, 0, 6).s('/VREF_M', 'F', 0, 7, 0, 10)
    if tie:
        s.s('/VREF', 'F', 10, 0, 0, 10)
    return s.build()


def test_lr8_branches_reach_the_source_through_a_bridge():
    r = R.lr8(vref_board(), C8)
    assert r.ok and r.figures['branches_reached'] == 2 and r.detail == 'VREF: 2 branches each on its own copper'
    assert not R.lr8(vref_board(tie=True), C8).ok                                    # shared copper still fails


def test_lr8_an_unrouted_branch_fails_and_names_it():
    r = R.lr8(vref_board(leg1=False), C8)
    assert not r.ok and r.detail == 'VREF: branch 0 (R1.1) is not connected to the source U1.1 by copper'
    r = R.lr8(vref_board(leg2=False), C8)
    assert not r.ok and r.detail.startswith('VREF: branch 1 (BR2.1, R2.1')
    r = R.lr8(vref_board(leg1=False, leg2=False), C8)
    assert r.detail.count('is not connected to the source') == 2


def test_lr8_a_board_without_the_source_part_has_nothing_to_reach():
    s = Synth('/VREF').part('R1', 10, 0).p('R1', '1', 10, 0, '/VREF')
    r = R.lr8(s.build(), C8)
    assert r.ok and r.figures['branches_unchecked'] == 2


def test_the_real_integrated_board_resolves_the_scope_group():
    b = boardio.load_npz(os.path.join(ARR, 'v2-integrated-990d4b03.npz'))
    assert {'/+3V3A', '/+3V3A_K', '/+3V3A_S', '/+3V3A_U', '/+3V3A_R'} == R.family(v2, '/+3V3A')
    pt = R.pads(b)
    assert not [k for j, k in enumerate(pt.keys) if k[0] == 'U101' and b.nets[pt.net[j]] == '/+3V3A']    # no scope pad on /+3V3A itself
    r = R.lr6(b, v2)
    assert r.ok and r.figures['groups_reached'] == 4 and r.figures['groups_absent'] == 0


# ------------------------------------------------------------------------------------------------ 3: both layers and zones
def X(**kw):
    return cfg(BRIDGE_PADS=[], BRIDGES=[], **kw)


def pads2(mask=1, net='/X'):
    s = Synth(net, '/GND').part('R1', 0, 0).p('R1', '1', 0, 0, net, mask=mask).part('R2', 10, 0).p('R2', '1', 10, 0, net, mask=mask)
    return s


def npc(s):
    """pieces that hold a pad (a track or a zone alone is a piece too: the rules count pads)"""
    return sum(1 for p in R.pieces(s.build(), X(), '/X') if p)


def test_pieces_join_through_a_bottom_hop_with_vias_and_not_without():
    assert npc(pads2().s('/X', 'B', 0, 0, 10, 0)) == 2         # a B.Cu track under two SMD pads touches neither of them
    s = pads2().s('/X', 'B', 0, 0, 10, 0).v('/X', 0, 0).v('/X', 10, 0)
    assert npc(s) == 1                                         # a via in each pad box and the bottom track between: one piece
    assert npc(pads2(mask=3).s('/X', 'B', 0, 0, 10, 0)) == 1   # through-hole pads reach B.Cu themselves
    assert npc(pads2().s('/X', 'F', 0, 0, 10, 0)) == 1
    s = pads2().s('/X', 'B', 0, 0, 4, 0).s('/X', 'F', 4, 0, 10, 0)
    assert npc(s.v('/X', 0, 0)) == 2                           # the layers meet only at a via: none at (4, 0) yet
    assert npc(s.v('/X', 4, 0)) == 1


def test_tracks_on_different_layers_do_not_touch_each_other_without_a_via():
    n = lambda s: len(R.pieces(s.build(), X(), '/X'))
    assert n(Synth('/X').s('/X', 'F', 0, 0, 5, 0).s('/X', 'B', 5, 0, 10, 0)) == 2
    assert n(Synth('/X').s('/X', 'F', 0, 0, 5, 0).s('/X', 'B', 5, 0, 10, 0).v('/X', 5, 0)) == 1


def test_a_zone_fill_joins_what_lies_in_it_on_its_layer_hole_aware():
    zone = [(SQ(-1, -1, 11, 1), False)]
    assert npc(pads2().z('/X', 'F', zone)) == 1                # both pads in one top fill
    assert npc(pads2().z('/X', 'B', zone)) == 2                # the fill is on B.Cu and the SMD pads are on F.Cu only
    assert npc(pads2(mask=3).z('/X', 'B', zone)) == 1          # through-hole pads are in it
    assert npc(pads2().z('/X', 'F', zone + [(SQ(9, -0.5, 11, 0.5), True)])) == 2     # a hole round R2 cuts it out of the fill
    assert npc(pads2().z('/X', 'F', [(SQ(-1, -1, 1, 1), False), (SQ(9, -1, 11, 1), False)])) == 2      # two islands are two pieces
    assert npc(pads2().z('/X', 'F', zone, filled=False)) == 2  # an unfilled zone has no copper
    assert npc(pads2().z('/GND', 'F', zone)) == 2              # a zone of another net is not this net's copper
    two = lambda: Synth('/X').s('/X', 'F', 0, 0, 3, 0).s('/X', 'F', 6, 0, 9, 0)           # two tracks that touch nothing
    assert len(R.pieces(two().build(), X(), '/X')) == 2
    assert len(R.pieces(two().z('/X', 'F', zone).build(), X(), '/X')) == 1                  # a top fill under both joins them
    assert len(R.pieces(two().z('/X', 'B', zone).build(), X(), '/X')) == 3                  # a bottom fill does not touch top tracks


def test_the_integrated_boards_bottom_hop_is_one_piece_with_its_vias():
    """the bottom hop (45.7, 27) - (48.2, 27) of /+3V3A: the top-only graph counts it as 8 pieces, there are 7"""
    b = boardio.load_npz(os.path.join(ARR, 'v2-integrated-990d4b03.npz'))
    assert len(R.pieces(b, v2, '/+3V3A', v2.STAR['/+3V3A'])) == 7
    on = (b.s_net == b.net_id('/+3V3A')) & (b.s_layer == 1)
    assert on.sum() >= 1


# ------------------------------------------------------------------------------------------------ 4, 5: LR-1
def lr1_base(extra=None, zones=1):
    s = Synth('/GND', '/SCL', '/A0')
    s.part('C1', 10, 10).p('C1', '1', 10, 10, '/GND').v('/GND', 11, 10)
    s.z('/GND', 'B', [(SQ(0, 0, 50, 50), False)])
    if extra:
        extra(s)
    return s.build()


C1 = cfg(ANALOG_REFS=frozenset(), ANALOG_FENCE=(), OUTLINE={}, XSENS=('/A0',))


def test_lr1_checks_every_bottom_zone():
    assert R.lr1(lr1_base(), C1).ok
    r = R.lr1(lr1_base(lambda s: s.z('/SCL', 'B', [(SQ(60, 0, 70, 10), False)])), C1)
    assert not r.ok and r.detail == 'bottom zone of /SCL: the bottom layer carries the ground plane only'
    r = R.lr1(lr1_base(lambda s: s.z('/GND', 'B', [(SQ(60, 0, 70, 10), False)])), C1)
    assert not r.ok and r.detail == '2 bottom GND zones, not 1; bottom plane is 2 pieces, not 1'
    r = R.lr1(lr1_base(lambda s: s.z('', 'B', [(SQ(60, 0, 70, 10), False)])), C1)        # a bottom zone with no net is not ground either
    assert not r.ok and 'bottom zone of no net' in r.detail
    assert R.lr1(lr1_base(lambda s: s.z('/SCL', 'F', [(SQ(60, 0, 70, 10), False)])), C1).ok       # on the TOP it is nobody's concern here
    # an unfilled other-net bottom zone is still a zone that fills the moment it is refilled
    assert not R.lr1(lr1_base(lambda s: s.z('/SCL', 'B', [(SQ(60, 0, 70, 10), False)], filled=False)), C1).ok
    r = R.lr1(lr1_base(lambda s: s.z('/GND', 'B', [(SQ(60, 0, 70, 10), False)], filled=False)), C1)
    assert not r.ok and '2 bottom GND zones' in r.detail


def test_lr1_a_hop_of_two_segments_meeting_at_a_T_is_one_run():
    one = lambda s: s.s('/SCL', 'B', 30, 30, 32.5, 30)
    r = R.lr1(lr1_base(lambda s: one(s)), C1)
    assert r.ok and r.figures['max_run_mm'] == 2.5
    r = R.lr1(lr1_base(lambda s: one(s).s('/SCL', 'B', 31.2, 30, 31.2, 32)), C1)             # the second one's end is on the first's interior
    assert not r.ok and r.detail == '/SCL: bottom run 4.5 mm, 0 vias (limit 3.0 mm, 2)' and r.figures['bottom_runs'] == 1
    # other net: no join; the same T at the first's END is the old end-to-end case
    r = R.lr1(lr1_base(lambda s: one(s).s('/A0', 'B', 31.2, 30, 31.2, 32)), C1)
    assert r.ok and r.figures['bottom_runs'] == 2
    r = R.lr1(lr1_base(lambda s: one(s).s('/SCL', 'B', 32.5, 30, 32.5, 32)), C1)
    assert not r.ok and '4.5 mm' in r.detail
    r = R.lr1(lr1_base(lambda s: one(s).s('/SCL', 'B', 31.2, 29, 31.2, 31)), C1)             # a crossing is one run too
    assert not r.ok and '4.5 mm' in r.detail
    r = R.lr1(lr1_base(lambda s: one(s).s('/SCL', 'B', 31.2, 30.02, 31.2, 32)), C1)          # 0.02 mm clear of the first: not touching
    assert r.ok and r.figures['bottom_runs'] == 2


# ------------------------------------------------------------------------------------------------ 9, 10: exact copper edges
def test_pad_shapes_have_the_size_and_rotation_the_arrays_hold():
    s = Synth('/X').part('R1', 0, 0)
    s.p('R1', '1', 5, 5, '/X', size=2.0, sy=0.6, rot=90.0)                   # 2 x 0.6, turned: 0.6 wide, 2 tall
    s.p('R1', '2', 5, 8, '/X', size=1.0, shape=0)                           # a circle of diameter 1
    s.p('R1', '3', 5, 12, '/X', size=3.0, sy=1.0, shape=2, rot=0.0)         # an oval 3 x 1: the capsule of its long axis
    b = s.build()
    cu = shapes.pad_copper(b, [0])
    box = lambda x0, y0, x1, y1: [x0, y0, x1, y1]
    assert cu.gap_to_box(box(6.0, 0, 7.0, 10))[0] == pytest.approx(0.7)       # x edge at 5.3
    assert cu.gap_to_box(box(0, 6.5, 10, 7.0))[0] == pytest.approx(0.5)       # y edge at 6.0
    assert cu.gap_to_box(box(5.2, 5, 9, 9))[0] == 0.0                         # overlapping
    cc = shapes.pad_copper(b, [1])
    assert cc.gap_to_box(box(6.0, 0, 7.0, 20))[0] == pytest.approx(0.5)       # radius 0.5
    co = shapes.pad_copper(b, [2])
    assert co.gap_to_box(box(7.5, 0, 9, 20))[0] == pytest.approx(1.0)         # reaches x = 6.5: its round end
    assert co.gap_to_box(box(0, 13.0, 20, 14))[0] == pytest.approx(0.5)       # 0.5 half height


def test_lr4_a_rotated_pad_is_measured_by_its_rotated_extent():
    """the FB pad is 2.0 x 0.6 turned 90 degrees at (40, 40): it spans x 39.7-40.3 and y 39-41"""
    kw = dict(fb_pad_kw=dict(size=2.0, sy=0.6, rot=90.0))
    r = R.lr4(lr4_board_(pour=[(SQ(40.3 + 0.45, 30, 60, 60), False)], **kw), cfg())          # the pad's 0.3 half width side
    assert not r.ok and r.figures['pour_gap_AWG_FB_mm'] == pytest.approx(0.45)
    r = R.lr4(lr4_board_(pour=[(SQ(30, 20, 60, 39 - 0.55), False)], **kw), cfg())            # below the pad's lower end: 0.55
    assert r.ok and r.figures['pour_gap_AWG_FB_mm'] == pytest.approx(0.55)
    r = R.lr4(lr4_board_(pour=[(SQ(30, 20, 60, 39 - 0.45), False)], **kw), cfg())
    assert not r.ok and r.figures['pour_gap_AWG_FB_mm'] == pytest.approx(0.45)


def lr4_board_(**kw):
    from test_rules_synthetic import lr4_board
    return lr4_board(fb=(0.0, 0.0), **kw)


def test_lr4_judges_the_ch1_n_node_and_reports_the_follower_output_node():
    def extra(s):
        s.part('R107', 0, 0).p('R107', '1', 60, 60, '/CH1_N').part('R109', 0, 0).p('R109', '1', 70, 60, '/CH1_OUT')
    ring = lambda x: [(SQ(x, 50, x + 6, 70), False)]
    r = R.lr4(lr4_board_(extra=extra, pour=ring(60.3 + 0.4)), cfg())
    assert not r.ok and "['top pour CH1_N']" in r.detail and r.figures['pour_gap_CH1_N_mm'] == pytest.approx(0.4)
    assert r.figures['pour_gap_CH1_OUT_mm'] > 2                                      # not near the pour
    r = R.lr4(lr4_board_(extra=extra, pour=ring(70.3 + 0.4)), cfg())               # the output node has the 0.4 gap: REPORTED, not judged
    assert r.ok and r.figures['pour_gap_CH1_OUT_mm'] == pytest.approx(0.4)


def test_lr4_gap_is_inf_when_there_is_no_pour_or_no_node_copper():
    r = R.lr4(lr4_board_(), cfg())
    assert r.ok and np.isinf(r.figures['pour_gap_AWG_FB_mm']) and np.isinf(r.figures['pour_gap_CH2_N_mm'])


def test_lr5_the_limit_itself_passes_and_a_hair_inside_fails():
    from test_rules_synthetic import C5
    base = lambda: Synth('/A0').part('U401', 1, 1, box=(0, 0, 2, 2)).part('C409', 50, 50, box=(49, 49, 51, 51))
    r = R.lr5(base().s('/A0', 'F', 12.0, -5, 12.0, 5, w=0.0).build(), C5)            # a zero-width track exactly 10.0 mm out
    assert r.ok and r.figures['min_distance_mm'] == 10.0
    assert not R.lr5(base().s('/A0', 'F', 11.999, -5, 11.999, 5, w=0.0).build(), C5).ok
    r = R.lr5(base().part('R1', 20, 20).p('R1', '1', 12.25, 1.0, '/A0', size=0.5).build(), C5)       # a 0.5 pad whose edge is at x = 12.0
    assert r.ok and r.figures['min_distance_mm'] == 10.0
    assert not R.lr5(base().part('R1', 20, 20).p('R1', '1', 12.24, 1.0, '/A0', size=0.5).build(), C5).ok


def test_lr5_a_rotated_pad_is_measured_by_its_extent():
    from test_rules_synthetic import C5
    # a 3.0 x 0.6 pad turned 90 degrees: 0.6 wide in x, 3.0 tall in y; its centre is (11.3, 6) , the box is (0, 0, 2, 2):
    # the nearest point is its lower end (11, 4.5) (11.3 - 0.3 = 11.0 in x; 6 - 1.5 = 4.5 in y): hypot(9, 2.5)
    s = Synth('/A0').part('U401', 1, 1, box=(0, 0, 2, 2)).part('C409', 50, 50, box=(49, 49, 51, 51))
    s.part('R1', 20, 20).p('R1', '1', 11.3, 6.0, '/A0', size=3.0, sy=0.6, rot=90.0)
    r = R.lr5(s.build(), C5)
    assert not r.ok and r.figures['min_distance_mm'] == pytest.approx(np.hypot(9.0, 2.5))
    assert r.detail == f'/A0 pad R1.1 {np.hypot(9.0, 2.5):.1f} mm'


# ------------------------------------------------------------------------------------------------ 6, 8: the command line
def board_npz():
    return os.path.join(ARR, 'v2-integrated-990d4b03.npz')


def test_an_arm_on_a_rule_that_already_fails_is_not_testable_and_the_run_is_not_clean(capsys):
    b = boardio.load_npz(board_npz())
    always_fails = lambda b, c: R.Result(False, 'broken before the arm', {})
    out = []
    miss = CK.run_arms(b, v2, [('on a failing rule', always_fails, lambda b, c: b), ('flips', R.lr5, v2_arms.mut5)], out=out.append,
                       no_drc=True)
    assert miss == [] and CK.run_arms.untestable == ['on a failing rule']
    assert out[0].startswith('[NOT TESTABLE on this board] on a failing rule (clean board: fail')
    assert not any('FAILED AS REQUIRED] on a failing rule' in l for l in out)
    assert out[1].startswith('[FAILED AS REQUIRED] flips')
    assert out[-2].startswith('[SKIP] LR-10 arm')
    assert out[-1] == 'NOT TESTABLE on this board: on a failing rule'


def test_cli_mutate_exits_nonzero_when_an_arm_is_not_testable(capsys):
    rc = CK.main([board_npz(), '--mutate', '--rows', 'LR-4', '--no-drc'])           # LR-4 fails on the integrated board
    out = capsys.readouterr().out
    assert rc == 1 and 'NOT TESTABLE on this board' in out and 'every arm caught' not in out
    rc = CK.main([board_npz(), '--mutate', '--rows', 'LR-6', '--no-drc'])           # LR-6 passes there: its arms are evidence
    out = capsys.readouterr().out
    assert rc == 0 and out.strip().endswith('every arm caught (LR-10 arm skipped by request)')


def test_lr10_not_run_is_not_all_pass(capsys):
    rc = CK.main([board_npz(), '--rows', 'LR-1', 'LR-10'])                           # an .npz has no board file to run DRC on
    out = capsys.readouterr().out.strip().splitlines()
    assert rc == 1 and out[-1] == 'LR-10 NOT RUN' and out[-2].startswith('[NOT RUN] LR-10') and 'ALL PASS' not in '\n'.join(out)
    rc = CK.main([board_npz(), '--rows', 'LR-1', 'LR-10', '--no-drc'])
    out = capsys.readouterr().out.strip().splitlines()
    assert rc == 0 and out[-1] == 'ALL PASS (LR-10 skipped by request)' and out[-2].startswith('[SKIP] LR-10')
    rc = CK.main([board_npz(), '--rows', 'LR-1', 'LR-5'])                            # LR-10 not asked for
    assert rc == 0 and capsys.readouterr().out.strip().splitlines()[-1] == 'ALL PASS'
    rc = CK.main([board_npz(), '--rows', 'LR-1', 'LR-4', 'LR-10'])                   # a failing row and no DRC: both are said
    assert rc == 1 and capsys.readouterr().out.strip().splitlines()[-1] == 'FAIL: LR-4; LR-10 NOT RUN'


def test_lr10_is_not_all_pass_when_drc_was_asked_for_and_cannot_run(capsys):
    """--drc on a board whose file is not there (a cache of a moved board): the row says NOT RUN, the run is not a pass"""
    b = boardio.load_npz(board_npz()).replace(path='/nonexistent/board.kicad_pcb')
    out = []
    fails = CK.run_rows(b, v2, ['LR-1', 'LR-10'], want_drc=True, out=out.append)
    assert fails == [] and CK.run_rows.not_run and out[-1] == 'LR-10 NOT RUN' and out[-2].startswith('[NOT RUN] LR-10')


# ------------------------------------------------------------------------------------------------ 7: the LR-10 arm's work copy
def test_the_lr10_arm_is_made_in_the_same_work_copy_as_the_base_run(tmp_path):
    src = tmp_path / 'src'
    (src / 'lib').mkdir(parents=True)
    (src / 'lib' / 'x.pretty').write_text('lib')
    name = 'v2-refcal-326f141b'
    for f in (name + '.kicad_pcb', name + '.kicad_pro', 'fp-lib-table'):
        (src / f).write_bytes(open(os.path.join(FX, f), 'rb').read())
    b = boardio.load_npz(os.path.join(ARR, name + '.npz')).replace(path=str(src / (name + '.kicad_pcb')))
    base = drc._work_copy(b.path, str(tmp_path / 'base'))
    arm = drc.lr10_arm(b, str(tmp_path / 'arm'), v2)
    names = lambda p: sorted(os.listdir(os.path.dirname(p)))
    assert names(arm) == names(base) and 'fp-lib-table' in names(arm) and 'lib' in names(arm) and name + '.kicad_pro' in names(arm)
    assert os.path.isdir(os.path.join(os.path.dirname(arm), 'lib'))
    text = open(arm).read()
    assert text.count('(net "/CH1_N") (uuid "00000000-0000-4000-8000-000000000101")') == 1
    assert open(base).read() == open(b.path).read() and text != open(b.path).read()
    assert open(b.path).read() == open(os.path.join(FX, name + '.kicad_pcb')).read()          # the original is untouched
    # and what DRC is then run on is again a work copy of the arm, in a different folder: no clash with the arm's own
    again = drc._work_copy(arm, str(tmp_path / 'arm'))
    assert again != arm


# ------------------------------------------------------------------------------------------------ added for the mutation proof
def test_lr4_the_keep_back_limit_itself_passes():
    """a 0.5 mm square FB pad (edge at 39.75, exact in binary) and a pour edge at 39.25: the gap is exactly 0.5, which is allowed"""
    kw = dict(fb_pad_kw=dict(size=0.5))
    r = R.lr4(lr4_board_(pour=[(SQ(20, 30, 39.25, 60), False)], **kw), cfg())
    assert r.ok and r.figures['pour_gap_AWG_FB_mm'] == 0.5
    assert not R.lr4(lr4_board_(pour=[(SQ(20, 30, 39.26, 60), False)], **kw), cfg()).ok


def test_lr4_a_ground_track_is_measured_against_the_nodes_track_edge_too():
    """the FB track ends at (43, 44) (0.2 wide, edge 0.1 round); a 0.2 wide ground track at x = 43.6 is 0.4 mm clear edge to edge"""
    from test_rules_synthetic import lr4_board
    r = R.lr4(lr4_board(gnd_track=(43.6, 43, 43.6, 45)), cfg())
    assert not r.ok and r.figures['gnd_track_gap_AWG_FB_mm'] == pytest.approx(0.4)
    assert R.lr4(lr4_board(gnd_track=(43.8, 43, 43.8, 45)), cfg()).ok


def test_an_oval_pad_follows_its_rotation():
    s = Synth('/X').part('R1', 0, 0).p('R1', '1', 5, 12, '/X', size=3.0, sy=1.0, shape=2, rot=90.0)         # long axis vertical
    cu = shapes.pad_copper(s.build(), [0])
    assert cu.gap_to_box([0, 14.0, 20, 15])[0] == pytest.approx(0.5)             # its end at y = 13.5
    assert cu.gap_to_box([6.0, 0, 7.0, 20])[0] == pytest.approx(0.5)             # its side at x = 5.5


def test_an_arc_joins_what_its_chords_touch():
    import dataclasses
    s = pads2()
    b = s.build()
    arc = dataclasses.replace(b, a_idx=[9], a_x0=[0.0], a_y0=[0.0], a_xm=[5.0], a_ym=[3.0], a_x1=[10.0], a_y1=[0.0], a_w=[0.2],
                              a_layer=[0], a_net=[b.net_id('/X')])
    assert len([p for p in R.pieces(b, X(), '/X') if p]) == 2
    assert len([p for p in R.pieces(arc, X(), '/X') if p]) == 1


def test_lr2_checks_every_channel_of_the_config():
    from test_rules_synthetic import lr2_board
    r = R.lr2(lr2_board(), cfg())                                                # the two-channel v2 table; the board has no CH2 copper
    assert 'CH2: output run 0.0 mm is not longer than the divider side 0.0 mm' in r.detail
