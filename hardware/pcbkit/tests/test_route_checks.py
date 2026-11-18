"""rules.track_geometry's route kinds on boards built from numbers: 'dangling' (a track end touching nothing of its net), 'detour' (a hook or V kink, or a run far longer than its octilinear shortest path),
'tspur' (a T that is too short, at an odd angle or too close to a bend, another junction or a pad) and 'wide' (wider than the net's rule). Every limit is broken on purpose by mutate_geometry.sh."""
import pytest

from arrays import Arr
from pcbkit import rules


def base():
    return Arr('GND', 'SIG', 'OTHER')


def got(a, kind, **over):
    return [f for f in rules.track_geometry_parts(a.build(), over) if f[0] == kind]


def two_pads(a, x0=0, y0=0, x1=10, y1=0, net='SIG'):
    return a.part('U1', 0, 0).p('U1', '1', x0, y0, net, size=1.0).p('U1', '2', x1, y1, net, size=1.0)


# ---------------------------------------------------------------- dangling
def test_a_track_end_touching_nothing_of_its_net_is_dangling_and_one_on_a_pad_or_via_or_track_is_not():
    a = two_pads(base()).s('SIG', 0, 0, 0, 10, 0)
    assert got(a, 'dangling') == []
    free = base().part('U1', 0, 0).p('U1', '1', 0, 0, 'SIG', size=1.0).s('SIG', 0, 0, 0, 6, 0)
    assert [(round(x, 2), round(y, 2)) for _, _, x, y in got(free, 'dangling')] == [(6.0, 0.0)]
    via = base().part('U1', 0, 0).p('U1', '1', 0, 0, 'SIG', size=1.0).v('SIG', 6, 0).s('SIG', 0, 0, 0, 6, 0)
    assert got(via, 'dangling') == []
    tee = two_pads(base()).s('SIG', 0, 0, 0, 10, 0).s('SIG', 0, 5, 0, 5, 3)
    assert [(round(x, 2), round(y, 2)) for _, _, x, y in got(tee, 'dangling')] == [(5.0, 3.0)]     # the spur's far end hangs; its end on the trunk's body does not
    other = base().part('U1', 0, 0).p('U1', '1', 0, 0, 'SIG', size=1.0).s('SIG', 0, 0, 0, 6, 0).s('OTHER', 0, 6, 0, 6, 3)
    assert len(got(other, 'dangling')) == 3                                                        # a track of another net is not a connection (and the other net's ends hang)


def test_the_round_end_cap_decides_not_the_end_point_and_nothing_beyond_it():
    def edge(gap, w=0.2):
        return base().part('U1', 0, 0).p('U1', '1', 0, 0, 'SIG', size=1.0).s('SIG', 0, 0, 0.5 + gap, 0, 9, w)         # a vertical track whose end is `gap` above the pad's top edge (y 0.5)
    n_ok = len(got(edge(0.09), 'dangling'))
    assert n_ok == 1                                                                               # the cap reaches the pad: only the far end (y 9) hangs
    assert len(got(edge(0.11), 'dangling')) == n_ok + 1                                             # the cap (radius 0.1) no longer reaches the pad
    assert len(got(edge(0.14, w=0.3), 'dangling')) == n_ok                                          # a wider track reaches further
    assert len(got(edge(0.16, w=0.3), 'dangling')) == n_ok + 1


def test_an_exposed_pad_made_of_several_pads_of_one_number_is_touched_by_any_of_them():
    a = base().part('U1', 0, 0).p('U1', '13', 0, 0, 'GND', size=1.0).p('U1', '13', 0, 3, 'GND', size=1.0).s('GND', 0, 0, 0, 0, 3.0)
    assert got(a, 'dangling') == []                                                               # both ends on a pad 13, the first of them too
    b = base().part('U1', 0, 0).p('U1', '', 0, 0, 'GND', size=1.0).p('U1', '', 0, 3, 'GND', size=1.0).s('GND', 0, 0, 0, 0, 3.0)
    assert got(b, 'dangling') == []                                                               # unnumbered pads share the empty pin


# ---------------------------------------------------------------- detour
HOOK = [(0, 0), (2, 0), (2, 0.6), (1.4, 0.6)]


def chain(pts, w=0.2):
    a = base()
    for p, q in zip(pts, pts[1:]):
        a.s('SIG', 0, p[0], p[1], q[0], q[1], w)
    return a


def test_a_hook_or_u_turn_turns_180_degrees_or_more_within_the_window_and_a_dog_leg_does_not():
    assert got(chain(HOOK), 'detour')                                                             # 90 + 90 within 1.4 mm of track
    dog = chain([(0, 0), (4, 0), (5, 1), (9, 1)])                                                 # 45 + 45
    assert got(dog, 'detour') == []
    assert [f for f in got(chain(HOOK), 'detour', TRACK_MAX_TURN=200.0) if 'degrees' in f[1]] == []   # the limit is the config's
    turns = lambda a, **o: [f for f in got(a, 'detour', **o) if 'degrees' in f[1]]
    assert turns(chain(HOOK), TRACK_TURN_WINDOW=0.1) == []                                         # the window is the config's: the two 90s are 0.6 mm apart
    assert turns(chain(HOOK), TRACK_TURN_WINDOW=0.7)


def test_a_v_kink_is_180_degrees_in_a_short_stretch():
    v = chain([(0, 0), (4, 0), (4.5, -0.5), (5.0, 0), (9, 0)])                                    # 45 down, 90 up, 45 level: a V dip on a straight run
    f = got(v, 'detour')
    assert f and 'V kink' in f[0][1]


def test_a_v_on_a_trunk_is_found_straight_through_a_t_junction():
    a = chain([(0, 0), (4, 0), (4.5, -0.5), (5.0, 0), (9, 0)])                                   # the trunk with a V ...
    a.s('SIG', 0, 7, 0, 7, 4)                                                                     # ... and a spur tapping it beyond the V
    assert got(a, 'detour')
    b = chain([(0, 0), (4, 0), (4.5, -0.5), (5.0, 0), (9, 0)]).s('SIG', 0, 2, 0, 2, 4)             # a tap before the V
    assert got(b, 'detour')


def test_a_run_longer_than_the_ratio_times_its_shortest_path_is_a_detour_and_a_short_one_is_not_judged():
    long_ = chain([(0, 0), (0, 3), (3, 3), (3, 0), (4, 0)])                                       # 10 mm of track for a 4 mm gap, ratio 2.5
    assert any('times' in f[1] for f in got(long_, 'detour'))
    assert not any('times' in f[1] for f in got(long_, 'detour', TRACK_DETOUR_RATIO=3.0))
    tiny = chain([(0, 0), (0, 0.3), (0.3, 0.3), (0.3, 0)])                                        # 0.9 mm of track: under TRACK_DETOUR_MIN_LEN
    assert not any('times' in f[1] for f in got(tiny, 'detour'))
    assert any('times' in f[1] for f in got(tiny, 'detour', TRACK_DETOUR_MIN_LEN=0.5))
    straight = chain([(0, 0), (4, 0), (5, 1), (9, 1)])                                            # the octilinear shortest path itself
    assert not any('times' in f[1] for f in got(straight, 'detour'))


# ---------------------------------------------------------------- T spurs
def tee(spur_len=2.0, at=5.0, angle_end=None, w=0.2):
    a = base().s('SIG', 0, 0, 0, 10, 0)
    end = angle_end if angle_end else (at, spur_len)
    return a.s('SIG', 0, at, 0, end[0], end[1])


def test_a_t_spur_shorter_than_the_minimum_is_found():
    assert got(tee(0.4), 'tspur') and not got(tee(0.8), 'tspur')
    assert not got(tee(0.4), 'tspur', TRACK_SPUR_MIN=0.3)


def test_a_t_spur_at_an_odd_angle_is_found_and_90_or_45_degrees_is_not():
    assert got(tee(angle_end=(7, 1.2)), 'tspur')
    assert not got(tee(angle_end=(6.5, 1.5)), 'tspur')                                            # 45 degrees
    assert not got(tee(angle_end=(5.0, 2.0)), 'tspur')                                            # 90


def test_a_t_junction_close_to_a_bend_another_junction_or_a_pad_on_the_trunk_is_found():
    assert got(tee(at=0.5), 'tspur')                                                              # 0.5 mm from the trunk's end
    assert not got(tee(at=1.0), 'tspur')
    assert got(tee(at=1.0), 'tspur', TRACK_SPUR_CLEAR=1.5)
    two = tee(at=5.0).s('SIG', 0, 5.4, 0, 5.4, 2.0)                                              # a second T 0.4 mm along
    assert got(two, 'tspur')


def test_three_tracks_meeting_where_a_trunk_turns_are_a_junction_at_a_bend():
    a = base().s('SIG', 0, 0, 0, 5, 0).s('SIG', 0, 5, 0, 5, 5).s('SIG', 0, 5, 0, 8, 3)
    f = got(a, 'tspur')
    assert f and 'bend' in f[0][1]


# ---------------------------------------------------------------- wide
def test_a_segment_wider_than_the_nets_rule_is_found_and_a_net_with_no_rule_is_not_judged():
    a = two_pads(base()).s('SIG', 0, 0, 0, 10, 0, 0.5)
    assert got(a, 'wide', TRACK_NET_WIDTHS={'SIG': 0.3})
    assert not got(a, 'wide', TRACK_NET_WIDTHS={'SIG': 0.5})
    assert not got(a, 'wide', TRACK_NET_WIDTHS={'SIG': 0.499, 'OTHER': 0.1}, TRACK_WIDTH_TOL=0.01)
    assert not got(a, 'wide', TRACK_NET_WIDTHS={'OTHER': 0.2})                                     # no entry for SIG and no '*'
    assert got(a, 'wide', TRACK_NET_WIDTHS={'*': 0.25}) and not got(a, 'wide', TRACK_NET_WIDTHS={'*': 0.25, 'SIG': 0.6})
    assert not got(a, 'wide')                                                                      # no table: nothing judged
    g = base().part('U1', 0, 0).p('U1', '1', 0, 0, 'GND', size=1.0).s('GND', 0, 0, 0, 5, 0, 1.2)
    assert got(g, 'wide', TRACK_NET_WIDTHS={'*': 0.25})                                            # a 1.2 mm bar


def test_a_trunk_drawn_as_two_collinear_segments_is_one_track_for_the_distance_to_its_bends():
    split = base().s('SIG', 0, 0, 0, 5, 0).s('SIG', 0, 5, 0, 10, 0).s('SIG', 0, 5, 0, 5, 2)         # the T sits where two collinear segments meet
    assert not got(split, 'tspur')
    bend_near = base().s('SIG', 0, 0, 0, 5, 0).s('SIG', 0, 5, 0, 5.4, 0).s('SIG', 0, 5.4, 0, 8, 2.6).s('SIG', 0, 5, 0, 5, 2)    # a real bend 0.4 mm beyond the T
    assert got(bend_near, 'tspur')
    three = base().s('SIG', 0, 0, 0, 3, 0).s('SIG', 0, 3, 0, 5, 0).s('SIG', 0, 5, 0, 10, 0).s('SIG', 0, 5, 0, 5, 2)             # three collinear pieces
    assert not got(three, 'tspur')
    near_end = base().s('SIG', 0, 4.6, 0, 10, 0).s('SIG', 0, 5, 0, 5, 2)                                                       # only 0.4 mm of trunk on one side
    assert got(near_end, 'tspur')


def test_an_end_whose_cap_overlaps_another_track_is_a_tap_not_a_dangling_end_and_a_short_one_is_a_t_stub():
    pad = lambda: base().part('U1', 0, 0).p('U1', '1', 0, 0, 'SIG', size=0.3)
    near = pad().s('SIG', 0, 0, 0, 0.3, 0).s('SIG', 0, 0.45, -3, 0.45, 3)               # the stub's end is 0.15 mm off the other track's centre line: the caps (0.1 + 0.1) overlap
    assert not any(abs(x - 0.3) < 1e-6 for _, _, x, y in got(near, 'dangling'))
    assert got(near, 'tspur')                                                              # a T stub: 0.45 mm from the pad to the track
    far = pad().s('SIG', 0, 0, 0, 0.3, 0).s('SIG', 0, 0.55, -3, 0.55, 3)                  # 0.25 mm off: the caps do not reach
    assert any(abs(x - 0.3) < 1e-6 for _, _, x, y in got(far, 'dangling'))
