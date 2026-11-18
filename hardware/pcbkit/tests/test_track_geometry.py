"""rules.track_geometry on boards built from numbers; every property is broken once on purpose by mutate_geometry.sh."""
import pytest

from arrays import Arr, rect
from pcbkit import rules
from pcbkit.config import ConfigError


def run_all(a, **over):
    return rules.track_geometry_parts(a.build(), over)


def run(a, **over):
    res = run_all(a, **over)
    return rules.WaivedList([f for f in res if f[0] not in ROUTE], res.waived)


ROUTE = ('detour', 'dangling', 'tspur', 'wide')                               # the route kinds have their own tests (test_route_checks.py): these boards end tracks in the air


def kinds(a, **over):
    return sorted({k for k, *_ in run(a, **over) if k not in ROUTE})


def base():
    return Arr('GND', 'SIG', 'OTHER')


def test_a_clean_board_passes_and_says_so():
    a = base().part('U1', 0, 0).p('U1', '1', 0, 0, 'SIG', size=1.0).p('U1', '2', 8, 9, 'SIG', size=1.0)
    a.s('SIG', 0, 0, 0, 5, 0).s('SIG', 0, 5, 0, 8, 3).s('SIG', 0, 8, 3, 8, 9)       # 0, 45 and 90 degrees, runs of 5, 4.2 and 6, from pad to pad
    r = rules.track_geometry(a.build(), {})
    assert r.ok and r.figures['segments'] == 3 and r.figures['violations'] == 0 and 'on the angle step' in r.detail


def test_a_segment_off_the_angle_step_is_found_within_the_tolerance_it_is_not():
    import math
    off = lambda deg: base().s('SIG', 0, 0, 0, 10 * math.cos(math.radians(deg)), 10 * math.sin(math.radians(deg)))
    assert kinds(off(40)) == ['angle'] and kinds(off(135.4)) == [] and kinds(off(135.7)) == ['angle'] and kinds(off(1.0)) == ['angle']
    assert kinds(off(40), TRACK_ANGLE_TOL=6.0) == [] and kinds(off(40), TRACK_ANGLE_STEP=20.0) == []       # the step and the tolerance are configuration


def test_a_leg_between_bends_shorter_than_the_minimum_is_a_jog_and_a_longer_one_is_not():
    jog = lambda leg: base().s('SIG', 0, 0, 0, 5, 0).s('SIG', 0, 5, 0, 5, leg).s('SIG', 0, 5, leg, 10, leg)
    assert kinds(jog(0.3)) == ['jog'] and kinds(jog(0.7)) == []
    assert kinds(jog(0.3), TRACK_MIN_LEG=0.2) == [] and kinds(jog(0.7), TRACK_MIN_LEG=0.8) == ['jog']
    assert len(run(jog(0.3))) == 1                                              # one finding per leg, not one per bend


def test_a_collinear_chain_is_one_leg_and_a_tee_or_a_pad_or_a_via_is_not_a_bend():
    chain = base().s('SIG', 0, 0, 0, 5, 0).s('SIG', 0, 5, 0, 5, 0.3).s('SIG', 0, 5, 0.3, 5, 0.6).s('SIG', 0, 5, 0.6, 10, 0.6)      # the 0.6 mm vertical leg is two 0.3 segments
    assert kinds(chain) == []
    tee = base().s('SIG', 0, 0, 0, 5, 0).s('SIG', 0, 5, 0, 5, 0.3).s('SIG', 0, 5, 0, 10, 0)
    assert kinds(tee) == []                                                     # three segments meet: not a bend
    onpad = base().part('C1', 5, 0).p('C1', '1', 5, 0, 'SIG', size=1.0).s('SIG', 0, 0, 0, 5, 0).s('SIG', 0, 5, 0, 5, 0.3)
    assert 'jog' not in kinds(onpad)
    onvia = base().v('SIG', 5, 0).s('SIG', 0, 0, 0, 5, 0).s('SIG', 0, 5, 0, 5, 0.3)
    assert kinds(onvia) == []


def test_a_short_leg_out_of_a_fine_pitch_pad_is_a_breakout_and_out_of_a_coarse_pad_is_not():
    def board(pitch):
        a = base().part('U1', 0, 0).p('U1', '1', 0, 0, 'SIG', size=0.3, sy=0.6).p('U1', '2', pitch, 0, 'OTHER', size=0.3, sy=0.6)
        return a.s('SIG', 0, 0, 0, 0, 0.4).s('SIG', 0, 0, 0.4, 3, 3.4)
    assert kinds(board(0.5)) == [] and kinds(board(0.65)) == [] and 'jog' in kinds(board(0.7))
    assert 'jog' in kinds(board(0.5), TRACK_FINE_PITCH=0.4)


def test_the_second_short_leg_of_a_fan_out_is_a_breakout_only_within_the_breakout_reach():
    def board(pitch=0.5, net='SIG'):
        a = base().part('U1', 0, 0).p('U1', '1', 0, 0, net, size=0.3, sy=0.6).p('U1', '2', pitch, 0, 'OTHER', size=0.3, sy=0.6)
        return a.s('SIG', 0, 0, 0, 0, 0.45).s('SIG', 0, 0, 0.45, -0.2, 0.65).s('SIG', 0, -0.2, 0.65, -0.2, 4)          # out of the pad 0.45, a 0.28 mm diagonal, then on
    assert 'jog' in kinds(board())                                                         # the diagonal is not the leg that ends on the pad: flagged by default
    assert 'jog' not in kinds(board(), TRACK_BREAKOUT_REACH=0.8)
    assert 'jog' in kinds(board(), TRACK_BREAKOUT_REACH=0.3)                               # its ends are further than that from the pad centre
    assert 'jog' in kinds(board(pitch=0.7), TRACK_BREAKOUT_REACH=0.8)                      # a coarse part has no breakout
    assert 'jog' in kinds(board(net='OTHER'), TRACK_BREAKOUT_REACH=0.8)                    # the pad is of another net


def test_the_segment_into_a_pad_is_perpendicular_to_the_edge_it_enters_along_either_pad_axis():
    pad = lambda end, rot=0.0: base().part('U1', 0, 0).p('U1', '1', 0, 0, 'SIG', size=0.3, sy=1.2, rot=rot).s('SIG', 0, end[0], end[1], 0, 0)       # a 0.3 x 1.2 pad, the track from `end` to its centre
    assert 'entry' not in kinds(pad((0, 3))) and 'entry' not in kinds(pad((3, 0)))        # along the long axis, and along the short one (the part's axis, from the outer end)
    assert 'entry' in kinds(pad((3, 3)))                                                   # 45 degrees to the pad
    assert 'entry' not in kinds(pad((3, 0), rot=90.0)) and 'entry' not in kinds(pad((0, 3), rot=90.0)) and 'entry' in kinds(pad((3, 3), rot=90.0))      # the pad turned
    assert 'entry' in kinds(base().part('U1', 0, 0).p('U1', '1', 0, 0, 'SIG', size=0.3, sy=1.2, rot=30.0).s('SIG', 0, 3, 0, 0, 0))                    # a pad at 30 degrees is not entered along the world axes
    assert 'entry' not in kinds(pad((3, 0)), TRACK_ANGLE_TOL=0.5) and 'entry' not in kinds(base().part('U1', 0, 0).p('U1', '1', 0, 0, 'SIG', size=0.3, sy=1.2, rot=30.0).s('SIG', 0, 3 * 0.866025, 3 * 0.5, 0, 0))
    rnd = base().part('C1', 0, 0).p('C1', '1', 0, 0, 'SIG', size=0.8, shape=0).s('SIG', 0, 3, 3, 0, 0)
    assert 'entry' not in kinds(rnd)                                                       # a round pad has no edge
    other = base().part('C1', 0, 0).p('C1', '1', 0, 0, 'OTHER', size=0.3, sy=1.2).s('SIG', 0, 3, 3, 0, 0)
    assert 'entry' not in kinds(other)                                                     # another net's pad is not entered by this track


def test_a_track_enters_through_the_edge_not_across_a_corner():
    def pad(y, w=0.2, **over):
        return kinds(base().part('C1', 0, 0).p('C1', '1', 0, 0, 'SIG', size=1.0).s('SIG', 0, 3, y, 0, y, w=w), **over)       # a 1 x 1 pad, the track along x at height y
    assert 'entry' not in pad(0.0) and 'entry' not in pad(0.4)                              # its whole width on the edge (0.4 + 0.1 = 0.5)
    assert 'entry' in pad(0.45) and 'entry' in pad(0.4, w=0.4)                              # its side over the corner
    assert 'entry' not in pad(0.45, TRACK_ENTRY_EDGE_TOL=0.1)
    side = lambda x: kinds(base().part('C1', 0, 0).p('C1', '1', 0, 0, 'SIG', size=1.0).s('SIG', 0, x, 3, x, 0))       # the same along y, at offset x
    assert 'entry' not in side(0.4) and 'entry' in side(0.45)


def test_a_track_over_the_pads_of_a_part_it_does_not_end_on_is_found_even_on_its_own_net():
    def board(net='SIG', end=(10, 0), pad_net='SIG'):
        return base().part('C1', 5, 0).p('C1', '1', 5, 0, pad_net, size=1.0).s('SIG', 0, 0, 0, *end)
    assert kinds(board()) == ['over_pad']                                      # through the pad of its own net
    assert kinds(board(pad_net='OTHER')) == ['over_pad']
    assert kinds(board(end=(5, 0))) == []                                      # ending on it is routing to it
    assert kinds(board(end=(3.0, 0))) == []                                    # not reaching it
    two = base().part('C1', 5, 0).p('C1', '1', 5, 0, 'SIG', size=1.0).p('C1', '2', 6.5, 0, 'SIG', size=1.0).s('SIG', 0, 0, 0, 6.5, 0)
    assert kinds(two) == []                                                    # the part it ends on may have other pads under it
    grazing = base().part('C1', 5, 0.6).p('C1', '1', 5, 0.6, 'SIG', size=1.0).s('SIG', 0, 0, 0, 10, 0)
    assert kinds(grazing) == []                                                # the track's edge touches the pad's edge at most
    assert kinds(grazing, TRACK_OVERLAP_TOL=-0.2) == ['over_pad']
    bottom = base().part('C1', 5, 0).p('C1', '1', 5, 0, 'SIG', size=1.0, mask=1).s('SIG', 1, 0, 0, 10, 0)
    assert kinds(bottom) == []                                                 # a pad on the top is not under a bottom track


def test_a_run_that_starts_on_a_pad_and_turns_is_still_on_its_part_and_a_run_that_does_not_is_not():
    def board(start_on_pad):
        a = base().part('U1', 0, 0).p('U1', '2', 1.0, 1.5, 'SIG', size=0.4)
        if start_on_pad:
            a = a.p('U1', '1', 0, 0, 'SIG', size=0.3)
        return a.s('SIG', 0, 0, 0, 0, 1.5).s('SIG', 0, 0, 1.5, 3, 1.5)           # up from pad 1, then along y = 1.5 over pad 2
    assert 'over_pad' not in kinds(board(True)) and 'over_pad' in kinds(board(False))
    other = base().part('U1', 0, 0).p('U1', '2', 1.0, 1.5, 'SIG', size=0.4).part('U2', 0, 0).p('U2', '1', 0, 0, 'SIG', size=0.3).s('SIG', 0, 0, 0, 0, 1.5).s('SIG', 0, 0, 1.5, 3, 1.5)
    assert 'over_pad' in kinds(other)                                            # starting on another part's pad does not excuse it


def test_the_configuration_names_and_defaults_are_declared():
    text = rules.effective_config({}, 'track_geometry')
    for n in ('TRACK_ANGLE_STEP', 'TRACK_ANGLE_TOL', 'TRACK_MIN_LEG', 'TRACK_FINE_PITCH', 'TRACK_ENTRY_EDGE_TOL', 'TRACK_OVERLAP_TOL'):
        assert n in text and 'default' in text
    with pytest.raises(ConfigError):
        rules.track_geometry(base().build(), dict(TRACK_MIN_LEGG=0.5))


def test_a_named_exception_waives_exactly_one_finding_and_a_stale_or_ambiguous_one_fails():
    import pytest
    from pcbkit.config import ConfigError

    def board(pad_net='SIG'):
        return base().part('C1', 5, 0).p('C1', '1', 5, 0, pad_net, size=1.0).s('SIG', 0, 0, 0, 10, 0)
    ok = [('over_pad', 'SIG', 'C1.1', 'daisy chain through the clamp')]
    assert kinds(board()) == ['over_pad'] and kinds(board(), GEOMETRY_EXCEPTIONS=ok) == []
    assert kinds(board(), GEOMETRY_EXCEPTIONS=[('over_pad', 'SIG', 'C1', 'r')]) == []                     # a ref covers any of its pins
    assert kinds(board(), GEOMETRY_EXCEPTIONS=[('over_pad', 'SIG', (5.0, 0.0), 'r')]) == []                # a place within 0.5 mm
    for bad in ([('over_pad', 'OTHER', 'C1.1', 'x')], [('over_pad', 'SIG', 'C1.2', 'x')], [('jog', 'SIG', 'C1.1', 'x')], [('over_pad', 'SIG', (9.0, 9.0), 'x')]):
        assert kinds(board(), GEOMETRY_EXCEPTIONS=bad) == ['over_pad', 'stale_exception'], bad          # it matches nothing: the finding stays and the entry fails
    assert kinds(board(), GEOMETRY_EXCEPTIONS=ok + ok) == []                                           # two entries on one finding are each exactly one match
    two = base().part('C1', 5, 0).p('C1', '1', 5, 0, 'SIG', size=1.0).p('C1', '2', 6.5, 0, 'SIG', size=1.0).part('C2', 12, 0).p('C2', '1', 12, 0, 'SIG', size=1.0).s('SIG', 0, 0, 0, 20, 0)
    res = run(two, GEOMETRY_EXCEPTIONS=[('over_pad', 'SIG', 'C1', 'x')])
    assert sorted(k for k, *_ in res) == ['over_pad', 'over_pad', 'over_pad', 'stale_exception'] and not res.waived        # C1 has two pins hit: ambiguous, so it waives nothing and fails
    res = run(two, GEOMETRY_EXCEPTIONS=[('over_pad', 'SIG', 'C2.1', 'x'), ('over_pad', 'SIG', 'C1.1', 'x')])
    assert sorted(k for k, *_ in res) == ['over_pad'] and len(res.waived) == 2
    ten = base().part('C10', 5, 0).p('C10', '1', 5, 0, 'SIG', size=1.0).s('SIG', 0, 0, 0, 10, 0)
    assert kinds(ten, GEOMETRY_EXCEPTIONS=[('over_pad', 'SIG', 'C1', 'x')]) == ['over_pad', 'stale_exception']      # C1 is not C10
    assert kinds(board(pad_net='OTHER'), GEOMETRY_EXCEPTIONS=ok) == []
    with pytest.raises(ConfigError):
        kinds(board(), GEOMETRY_EXCEPTIONS=[('over_pad', 'SIG', 'C1.1', '')])
    with pytest.raises(ConfigError):
        kinds(board(), GEOMETRY_EXCEPTIONS=[('over_pad', 'SIG', 'C1.1')])


def test_every_pad_of_a_part_counts_not_one_per_pin_number():
    """an exposed pad is several pads of one number, and unnumbered pads share the empty pin: the first of them is lying under a track like any other"""
    def board(track):
        a = base().part('U1', 5, 0)
        a.p('U1', '13', 5, 0, 'GND', size=1.0)                                  # the first pad of number 13 (a later one of the same number follows)
        a.p('U1', '13', 5, 4, 'GND', size=1.0)
        a.p('U1', '', 9, 0, 'OTHER', size=1.0)                                  # two unnumbered pads
        a.p('U1', '', 9, 4, 'OTHER', size=1.0)
        return a.s(*track)
    assert 'over_pad' in kinds(board(('SIG', 0, 2, 0, 8, 0)))                  # across the FIRST pad 13
    assert 'over_pad' in kinds(board(('SIG', 0, 7, 0, 11, 0)))                 # across the first unnumbered pad
    assert 'over_pad' in kinds(board(('SIG', 0, 7, 4, 11, 4)))                 # and the second
    one = base().part('U1', 5, 0).p('U1', '13', 5, 0, 'GND', size=1.0).p('U1', '13', 5, 4, 'GND', size=1.0)
    assert 'entry' in kinds(one.s('GND', 0, 2, 3, 5, 0))                       # a 45 degree entry into the first pad 13
