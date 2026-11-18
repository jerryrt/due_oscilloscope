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


def test_a_hook_or_u_turn_changes_the_heading_by_180_degrees_net_and_a_dog_leg_or_lane_change_does_not():
    assert got(chain(HOOK), 'detour')                                                             # east, north, west: 180 net
    assert not got(chain([(0, 0), (4, 0), (5, 1), (9, 1)]), 'detour')                              # a dog-leg, 45 + 45 the same way... 90 net
    assert [f for f in got(chain(HOOK), 'detour', TRACK_MAX_TURN=200.0) if 'hook' in f[1]] == []    # the limit is the config's
    assert [f for f in got(chain(HOOK), 'detour', TRACK_TURN_WINDOW=0.1) if 'hook' in f[1]] == []   # the window is the config's: the two 90s are 0.6 mm apart
    assert [f for f in got(chain(HOOK), 'detour', TRACK_TURN_WINDOW=0.7) if 'hook' in f[1]]
    lane = chain([(0, 0), (4, 0), (4, -1.5), (9, -1.5)])                                          # a Z: 90 one way, 90 back, 1.5 mm over: a lane change
    assert not got(lane, 'detour')
    assert not got(chain([(0, 0), (4, 0), (5, -1), (9, -1)]), 'detour')


def test_a_v_kink_or_bump_comes_back_to_its_heading_within_a_small_offset():
    v = chain([(0, 0), (4, 0), (4.5, -0.5), (5.0, 0), (9, 0)])                                    # 45 down, 90 up, 45 level: a V dip on a straight run
    f = got(v, 'detour')
    assert f and 'V kink' in f[0][1]
    z = chain([(0, 0), (4, 0), (4, -0.4), (8, -0.4)])                                            # a Z with a 0.4 mm lane change: 90 + 90, back to the heading 0.4 mm over
    assert got(z, 'detour') and 'V kink' in got(z, 'detour')[0][1]
    assert not got(z, 'detour', TRACK_KINK_OFFSET=0.3)                                            # the offset limit is the config's
    assert not got(chain([(0, 0), (4, 0), (4, -1.5), (8, -1.5)]), 'detour')                       # 1.5 mm over: a lane change, not a kink


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


def test_an_end_that_already_meets_another_tracks_end_is_a_joint_and_is_never_snapped_onto_a_nearby_body():
    a = base().s('SIG', 0, 0, 0, 0, 6, 0.3).s('SIG', 0, 0, 6, -0.3, 6, 0.3).s('SIG', 0, -0.3, 6, -1.5, 6, 0.2)       # a trunk turning west through a 0.3 mm piece: its far end is 0.3 mm from the trunk, caps touching
    assert got(a, 'tspur') == []                                                                                    # it is a joint with the next piece, not a tap on the trunk
    assert len(got(a, 'dangling')) == 2                                                                             # the trunk's start and the neck's end hang, nothing else


def test_the_shortest_path_is_octilinear_not_euclidean():
    one = chain([(0, 0), (3, 0), (4, 1)])                                                       # 3 mm along, then a 45 degree step: exactly its octilinear shortest path (4.414 mm)
    assert not any('times' in f[1] for f in got(one, 'detour', TRACK_DETOUR_RATIO=1.02, TRACK_DETOUR_MIN_LEN=1.0))


def test_a_v_with_a_tap_on_its_first_diagonal_is_still_one_track_through_the_junction():
    a = chain([(0, 0), (4, 0), (4.5, -0.5), (5.0, 0), (9, 0)]).s('SIG', 0, 4.25, -0.25, 3.25, -1.25)      # a spur at 90 degrees on the middle of the first 45 degree leg
    assert any('V kink' in f[1] for f in got(a, 'detour'))


def test_a_pad_of_another_net_at_the_end_does_not_connect_it():
    a = base().part('U1', 0, 0).p('U1', '1', 0, 0, 'OTHER', size=1.0).s('SIG', 0, 0, 0, 5, 0)
    assert any(abs(x) < 1e-6 for _, _, x, y in got(a, 'dangling'))


def test_collinear_pieces_beyond_a_short_one_are_one_track_for_the_distance_to_a_bend():
    a = base().s('SIG', 0, 0, 0, 4.6, 0).s('SIG', 0, 4.6, 0, 10, 0).s('SIG', 0, 5.0, 0, 5.0, 2.0)                # 0.4 mm of piece, then a joint, then straight on for 4.6 mm: no bend within 0.6 mm
    assert not got(a, 'tspur')


def test_a_net_turning_90_with_bends_adding_to_180_is_not_a_v_kink():
    pts = [(0, 0), (1, 0), (1.141, 0.141), (1.141, 0.341), (1.0, 0.483), (1.0, 3.0)]                           # +45, +45, +45, -45: 90 net, 180 in all, back within 0.5 mm of the line
    assert got(chain(pts), 'detour') == []


def test_a_short_stub_ending_just_beyond_the_end_of_another_track_is_not_a_tap_on_it():
    a = base().part('U1', 0, 0).p('U1', '1', 0, 0, 'SIG', size=1.0).p('U1', '2', -2.65, 2.2, 'SIG', size=0.5, sy=0.25)
    a.s('SIG', 0, 0, 0, -2.2, 2.2, 0.3).s('SIG', 0, -2.2, 2.2, -2.4, 2.2, 0.25)                     # a 45 degree track and a 0.2 mm stub into a pad, the stub's far end 0.2 from the diagonal's end, past it along its axis
    assert got(a, 'tspur') == []
    assert got(a, 'dangling') == []


def test_two_tracks_whose_end_caps_overlap_across_a_hair_gap_are_joined_not_dangling():
    a = base().part('U1', 0, 0).p('U1', '1', 0, 0, 'SIG', size=1.0).p('U1', '2', 10, 0, 'SIG', size=1.0)
    a.s('SIG', 0, 0, 0, 5.0, 0, 0.25).s('SIG', 0, 5.1, 0, 10, 0, 0.25)                               # 0.1 mm apart, the caps overlap
    assert got(a, 'dangling') == []
    b2 = base().part('U1', 0, 0).p('U1', '1', 0, 0, 'SIG', size=1.0).p('U1', '2', 10, 0, 'SIG', size=1.0)
    b2.s('SIG', 0, 0, 0, 5.0, 0, 0.25).s('SIG', 0, 5.5, 0, 10, 0, 0.25)                              # 0.5 mm apart: two dangling ends
    assert len(got(b2, 'dangling')) == 2


def test_two_opposite_90_degree_bends_with_a_short_middle_leg_are_a_stair_where_one_45_degree_leg_would_do():
    z = [(0, 0), (3, 0), (3, 0.8), (6, 0.8)]                                                         # east 3, north 0.8, east 3: net heading 0, every leg over 0.6 (no jog)
    assert [f for f in got(chain(z), 'stair')] and not got(chain(z), 'jog')
    assert not got(chain([(0, 0), (3, 0), (3, 1.6), (6, 1.6)]), 'stair')                              # a middle leg of 1.6 mm is a deliberate lane change
    assert got(chain([(0, 0), (3, 0), (3, 1.6), (6, 1.6)]), 'stair', TRACK_STAIR_MAX=2.0)
    assert not got(chain([(0, 0), (0.2, 0), (0.2, 0.8), (3, 0.8)]), 'stair')                          # the leg before is 0.2 mm, under half the step: a 45 degree leg would not fit
    assert not got(chain([(0, 0), (3, 0), (3.8, 0.8), (6.8, 0.8)]), 'stair')                          # the step is already a 45 degree leg
    assert not got(chain([(0, 0), (3, 0), (3, 0.8), (3, 4)]), 'stair')                                # bends in the same sense, then straight on: a corner, not a Z
    z2 = [(0, 0), (1.5, 0), (3, 0), (3, 0.8), (6, 0.8)]                                               # collinear pieces make one leg
    assert len(got(chain(z2), 'stair')) == 1
    assert got(chain([(0, 0), (3, 0), (3, -0.8), (6, -0.8)]), 'stair')                                # either way round


def test_a_stair_needs_opposite_90_degree_bends_and_counts_a_leg_in_pieces_as_one_leg():
    assert not got(chain([(0, 0), (3, 0), (3, 0.8), (0, 0.8)]), 'stair')                              # 90 and 90 the same way: a U, not a Z
    assert not got(chain([(0, 0), (3, 0), (3.8, 0.8), (4.6, 0)]), 'stair')                            # 45 then 90 back: not two 90 degree bends
    assert got(chain([(0, 0), (0.2, 0), (0.4, 0), (0.4, 0.8), (3, 0.8)]), 'stair')                    # the leg before is 0.4 mm in two pieces: exactly half the step
    assert got(chain([(0, 0), (3, 0), (3, 0.4), (3, 0.8), (6, 0.8)]), 'stair')                        # the middle leg in two pieces is one leg
