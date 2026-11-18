"""rules.ground_plane (LR-1): every SMD GND pad has a via of its own: joined to it by its own GND track chain, lying in the pad, or a plated hole of the pad; within the reach; one via per pad.
Broken once on purpose by mutate_geometry.sh."""
from arrays import Arr, rect
from pcbkit import rules


def board(*pads, plane=True):
    a = Arr('GND', 'SIG', layers=2)
    if plane:
        a.z('GND', 1, [(False, rect(-20, -20, 40, 40))])                    # a bottom plane
    a.part('U1', 0, 0)
    for n, (x, y, smd) in enumerate(pads):
        a.p('U1', str(n + 1), x, y, 'GND', smd=smd, size=1.0, mask=1 if smd else 3)
    return a


def missing(a, **over):
    plane, vias, _ = rules.ground_plane_parts(a.build(), dict(GND='GND', PLANE_LAYER='B', **over))
    return vias


def test_a_via_two_millimetres_away_that_the_pad_does_not_reach_is_not_its_own():
    a = board((0, 0, True)).v('GND', 2.0, 0)
    assert missing(a)
    assert not missing(board((0, 0, True)).v('GND', 2.0, 0).s('GND', 0, 0, 0, 2.0, 0))             # joined by its own track


def test_a_track_chain_of_several_segments_counts_and_a_gap_does_not():
    chain = board((0, 0, True)).v('GND', 2.0, 1.0).s('GND', 0, 0, 0, 1.0, 0).s('GND', 0, 1.0, 0, 1.0, 1.0).s('GND', 0, 1.0, 1.0, 2.0, 1.0)
    assert not missing(chain)
    gap = board((0, 0, True)).v('GND', 2.0, 1.0).s('GND', 0, 0, 0, 1.0, 0).s('GND', 0, 1.0, 0.4, 1.0, 1.0).s('GND', 0, 1.0, 1.0, 2.0, 1.0)     # 0.4 mm of nothing in the middle
    assert missing(gap)


def test_a_via_lying_in_the_pad_and_a_plated_hole_of_the_pad_are_its_own():
    assert not missing(board((0, 0, True)).v('GND', 0.2, 0))
    assert not missing(board((0, 0, True), (0.1, 0.2, False)))                                    # a plated hole (not SMD) in the pad
    assert missing(board((0, 0, True), (2.5, 0.2, False)))                                        # one 2.5 mm away, tied to nothing


def test_one_via_serves_one_pad_and_a_track_of_another_net_is_no_tie():
    two = board((0, 0, True), (0.9, 0, True)).v('GND', 0.45, 0)
    assert len(missing(two)[0].split("'")) >= 1 and missing(two)                                  # two pads, one via between them: one of them has none
    other = Arr('GND', 'SIG', layers=2).z('GND', 1, [(False, rect(-20, -20, 40, 40))]).part('U1', 0, 0).p('U1', '1', 0, 0, 'GND', size=1.0).v('GND', 2.0, 0).s('SIG', 0, 0, 0, 2.0, 0)
    assert missing(other)


def test_the_reach_is_the_configs():
    a = board((0, 0, True)).v('GND', 2.0, 0).s('GND', 0, 0, 0, 2.0, 0)
    assert not missing(a) and missing(a, GND_VIA_REACH=1.0)


def test_a_hole_in_the_middle_of_a_big_pad_is_in_that_pad_however_far_the_edge_is():
    a = Arr('GND', 'SIG', layers=2)
    a.z('GND', 1, [(False, rect(-20, -20, 40, 40))])
    a.part('U1', 0, 0).p('U1', '1', 0, 0, 'GND', smd=True, size=1.0, sy=2.65, mask=1)           # an exposed pad 1.0 x 2.65
    a.v('GND', 0, 0.0)                                                                                     # a via at its centre: 0.5 mm from the edge, more than its 0.3 radius
    assert not missing(a)


def test_a_via_whose_annulus_overlaps_the_pad_edge_is_its_own_though_its_centre_is_outside():
    assert not missing(board((0, 0, True)).v('GND', 0.7, 0))                                      # pad half-width 0.5, via radius 0.3: overlaps by 0.1
    assert missing(board((0, 0, True)).v('GND', 0.9, 0))                                          # 0.1 mm short of touching


def test_without_the_tie_rule_a_via_in_reach_counts_by_nearness_alone():
    a = board((0, 0, True)).v('GND', 2.0, 0)
    assert missing(a)                                                                              # tied by nothing: not its own
    assert not missing(a, GND_VIA_TIE=False)                                                        # the first-release rule: within reach is enough
