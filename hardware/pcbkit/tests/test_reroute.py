"""pcbkit.reroute on boards built from numbers: the chains of track, the grid search that re-routes one so that it passes rules.track_geometry, the pads a run lay across. Each is broken on
purpose by mutate_reroute.sh."""
import math

import numpy as np
import pytest

from arrays import Arr
from pcbkit import reroute, rules


def two_pads(extra=None, w=0.2):
    """pad U1.1 at (0, 0) and pad U2.1 at (6, 4), both 0.8 x 1.0 (long side along y), the track between them a straight 0.2 mm run at an angle the rules refuse"""
    a = Arr('SIG', 'OTHER').part('U1', 0, 0).p('U1', '1', 0, 0, 'SIG', size=0.8, sy=1.0).part('U2', 6, 4).p('U2', '1', 6, 4, 'SIG', size=0.8, sy=1.0)
    a.s('SIG', 0, 0, 0, 6, 4, w=w)
    if extra:
        extra(a)
    return a.build()


def chain_of(b, net='SIG'):
    return [c for c in reroute.chains(b, 0) if b.nets[c.net] == net][0]


def apply(b_arr_builder, poly, w=0.2):
    a = b_arr_builder
    for p, q in zip(poly[:-1], poly[1:]):
        a.s('SIG', 0, p[0], p[1], q[0], q[1], w=w)
    return a


def test_chains_run_from_pad_to_pad_through_joints_of_two_and_stop_at_a_tee_a_via_and_a_free_end():
    a = Arr('SIG').part('U1', 0, 0).p('U1', '1', 0, 0, 'SIG', size=0.8).part('U2', 9, 0).p('U2', '1', 9, 0, 'SIG', size=0.8)
    a.s('SIG', 0, 0, 0, 3, 0).s('SIG', 0, 3, 0, 3, 2).s('SIG', 0, 3, 2, 9, 2).s('SIG', 0, 9, 2, 9, 0)
    cs = reroute.chains(a.build(), 0)
    assert len(cs) == 1 and len(cs[0].segs) == 4 and {e.kind for e in cs[0].ends} == {'pad'}
    tee = Arr('SIG').s('SIG', 0, 0, 0, 3, 0).s('SIG', 0, 3, 0, 6, 0).s('SIG', 0, 3, 0, 3, 3)
    cs = reroute.chains(tee.build(), 0)
    assert len(cs) == 3 and all(len(c.segs) == 1 for c in cs)                                # three runs of one segment, meeting at the tee
    assert sorted(e.kind for c in cs for e in c.ends).count('junction') == 3
    via = Arr('SIG').v('SIG', 3, 0).s('SIG', 0, 0, 0, 3, 0).s('SIG', 0, 3, 0, 6, 0)
    assert sorted(e.kind for c in reroute.chains(via.build(), 0) for e in c.ends).count('via') == 2
    free = reroute.chains(Arr('SIG').s('SIG', 0, 0, 0, 3, 0).build(), 0)
    assert [e.kind for e in free[0].ends] == ['free', 'free']


def test_an_end_resting_on_the_body_of_another_track_of_the_net_is_a_tap_not_a_free_end():
    a = Arr('SIG', 'OTHER').s('SIG', 0, 0, 0, 6, 0).s('SIG', 0, 3, 2, 3, 0.05)              # the second ends 0.05 above the first's centre line: inside its 0.2 mm body
    cs = reroute.chains(a.build(), 0)
    assert sorted(e.kind for c in cs for e in c.ends).count('junction') >= 1
    b = Arr('SIG', 'OTHER').s('SIG', 0, 0, 0, 6, 0).s('OTHER', 0, 3, 2, 3, 0.05)            # another net's body is not a tap
    assert all(e.kind == 'free' for c in reroute.chains(b.build(), 0) if c.net == 1 for e in c.ends)


def test_a_route_between_two_pads_passes_the_geometry_rules_it_was_made_for():
    b = two_pads()
    assert {k for k, *_ in rules.track_geometry_parts(b, {})} >= {'angle', 'entry'}           # the straight run at 33.7 degrees fails both
    poly = reroute.route(b, chain_of(b))
    assert poly is not None and len(poly) >= 2
    a = Arr('SIG', 'OTHER').part('U1', 0, 0).p('U1', '1', 0, 0, 'SIG', size=0.8, sy=1.0).part('U2', 6, 4).p('U2', '1', 6, 4, 'SIG', size=0.8, sy=1.0)
    fixed = apply(a, poly).build()
    assert rules.track_geometry_parts(fixed, {}) == []


def test_every_leg_of_a_route_is_at_least_the_minimum_and_the_minimum_is_configuration():
    b = two_pads()
    for leg in (0.6, 1.5):
        poly = reroute.route(b, chain_of(b), min_leg=leg)
        legs = [math.hypot(q[0] - p[0], q[1] - p[1]) for p, q in zip(poly[:-1], poly[1:])]
        assert min(legs) >= leg - 1e-6, (leg, legs)
    for p, q in zip(poly[:-1], poly[1:]):
        assert abs((math.degrees(math.atan2(q[1] - p[1], q[0] - p[0])) + 360) % 45) in (pytest.approx(0, abs=1e-6), pytest.approx(45, abs=1e-6))


def test_a_route_goes_round_the_copper_of_other_nets_by_the_clearance_and_over_no_pad():
    def with_wall(a):
        a.part('X', 3, 2).p('X', '1', 3, 2, 'OTHER', size=1.0, sy=3.0)                            # a foreign pad across the straight way
    b = two_pads(with_wall)
    poly = reroute.route(b, chain_of(b))
    assert poly is not None
    pts = np.vstack([np.linspace(p, q, 80) for p, q in zip(poly[:-1], poly[1:])])
    inside = (np.abs(pts[:, 0] - 3) <= 0.5 + 0.2 + 0.1 - 1e-6) & (np.abs(pts[:, 1] - 2) <= 1.5 + 0.2 + 0.1 - 1e-6)
    assert not inside.any()                                                                   # clear of the pad by the clearance and the half width
    a = Arr('SIG', 'OTHER').part('U1', 0, 0).p('U1', '1', 0, 0, 'SIG', size=0.8, sy=1.0).part('U2', 6, 4).p('U2', '1', 6, 4, 'SIG', size=0.8, sy=1.0)
    a.part('X', 3, 2).p('X', '1', 3, 2, 'OTHER', size=1.0, sy=3.0)
    assert 'over_pad' not in {k for k, *_ in rules.track_geometry_parts(apply(a, poly).build(), {})}
    tight = reroute.route(b, chain_of(b), clear=1.5)                                          # a clearance that leaves no way round inside the window
    assert tight is None or tight != poly


def test_a_pad_of_the_same_net_that_is_not_an_end_is_not_run_over_and_is_reported_by_overlapped_pads():
    def mid(a):
        a.part('M', 3, 2).p('M', '1', 3, 2, 'SIG', size=0.6, sy=0.6)
    straight = Arr('SIG').part('U1', 0, 0).p('U1', '1', 0, 0, 'SIG', size=0.8).part('U2', 6, 0).p('U2', '1', 6, 0, 'SIG', size=0.8).part('M', 3, 0).p('M', '1', 3, 0, 'SIG', size=0.6)
    straight.s('SIG', 0, 0, 0, 6, 0)
    b = straight.build()
    c = chain_of(b)
    ex = reroute.overlapped_pads(b, c)
    assert len(ex) == 1
    poly = reroute.route(b, c)
    pts = np.vstack([np.linspace(p, q, 80) for p, q in zip(poly[:-1], poly[1:])])
    assert not ((np.abs(pts[:, 0] - 3) <= 0.3 + 0.1) & (np.abs(pts[:, 1]) <= 0.3 + 0.1)).any()           # round it, not through it
    other = Arr('SIG', 'OTHER').part('U1', 0, 0).p('U1', '1', 0, 0, 'SIG', size=0.8).part('U2', 6, 0).p('U2', '1', 6, 0, 'SIG', size=0.8).part('M', 3, 0).p('M', '1', 3, 0, 'OTHER', size=0.6)
    other.s('SIG', 0, 0, 0, 6, 0)
    assert reroute.overlapped_pads(other.build(), chain_of(other.build())) == []                 # another net's pad is not one the track connected


def test_a_spur_runs_from_a_pad_to_the_copper_of_the_net_and_ends_inside_it():
    a = Arr('SIG').part('U1', 0, 0).p('U1', '1', 0, 0, 'SIG', size=0.8).part('U2', 8, 0).p('U2', '1', 8, 0, 'SIG', size=0.8).part('M', 4, 3).p('M', '1', 4, 3, 'SIG', size=0.6, sy=1.0)
    a.s('SIG', 0, 0, 0, 8, 0)
    b = a.build()
    pa = rules._pad_arrays(b)
    h = [i for i in range(len(pa['rows'])) if b.fp_ref[pa['fp'][i]] == 'M'][0]
    c = reroute.Chain(int(b.s_net[0]), 0, [], (reroute.End('pad', 4.0, 3.0, pad=h), reroute.End('free', 0.0, 0.0)), 0.2)
    poly = reroute.route(b, c, goal=False)
    assert poly is not None and abs(poly[-1][1]) <= 0.1 + 1e-9                                  # it finishes on the track's body (y = 0 +- half the width)
    assert abs(poly[0][1] - 3) <= 0.5 + 1e-9 and abs(poly[0][0] - 4) <= 0.3 + 1e-9               # and starts inside the pad


def test_an_end_that_cannot_be_reached_says_why_and_two_pads_narrower_than_the_track_are_both_necked():
    wall = lambda a: a.part('X', 6, 4).p('X', '1', 6, 4, 'OTHER', size=3.0, sy=3.0)
    b = two_pads(wall)
    assert reroute.route(b, chain_of(b)) is None and reroute.LAST_WHY[0]
    narrow = Arr('SIG').part('U1', 0, 0).p('U1', '1', 0, 0, 'SIG', size=0.5, sy=0.25).part('U2', 6, 0).p('U2', '1', 6, 0, 'SIG', size=0.5, sy=0.25).s('SIG', 0, 0, 0, 6, 0, w=0.3).build()
    c = chain_of(narrow)
    assert reroute.route(narrow, c) is not None and sorted(k for k, _ in reroute.LAST_NECKS) == ['goal', 'start']      # 0.3 mm does not fit the 0.25 mm edge: both ends are necked down
    assert reroute.route(narrow, c, width=0.2) is not None and reroute.LAST_NECKS == []                               # 0.2 mm fits, no neck


def test_a_track_too_wide_for_a_pad_is_necked_down_at_the_pad_for_the_last_millimetre_only():
    narrow = Arr('SIG').part('U1', 0, 0).p('U1', '1', 0, 0, 'SIG', size=0.5, sy=0.25).part('U2', 6, 0).p('U2', '1', 6, 0, 'SIG', size=2.0, sy=2.0).s('SIG', 0, 0, 0, 6, 0, w=0.3).build()
    c = chain_of(narrow)
    poly = reroute.route(narrow, c)                                                          # the wide pad takes 0.3 mm, the narrow one does not: it is necked down there alone
    assert poly is not None and reroute.LAST_NECKS == [('start', int(c.ends[0].pad))] or reroute.LAST_NECKS == [('goal', int(c.ends[1].pad))]
    pieces = reroute.expand(poly, 0.3, reroute.LAST_NECKS)
    ws = [w for _, _, w in pieces]
    assert ws[0] == pytest.approx(0.2) and ws[-1] == pytest.approx(0.3) and len(pieces) >= 2
    assert sum(math.hypot(q[0] - p[0], q[1] - p[1]) for p, q, w in pieces if w < 0.3) == pytest.approx(1.0, abs=1e-6)        # one millimetre of neck
    assert pieces[0][0] == poly[0] and pieces[-1][1] == poly[-1]


def test_expand_necks_the_whole_leg_when_it_is_shorter_than_the_neck_and_both_ends_when_both_are_narrow():
    assert [w for *_, w in reroute.expand([(0, 0), (0.5, 0)], 0.3, [('start', 0)])] == [0.2]
    both = reroute.expand([(0, 0), (5, 0)], 0.3, [('start', 0), ('goal', 1)])
    assert [round(w, 2) for *_, w in both] == [0.2, 0.3, 0.2] and both[0][1] == (1.0, 0.0) and both[-1][0] == (4.0, 0.0)
    assert [w for *_, w in reroute.expand([(0, 0), (5, 0)], 0.3, [])] == [0.3]
