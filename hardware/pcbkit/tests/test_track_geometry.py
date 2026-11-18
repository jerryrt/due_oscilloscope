"""rules.track_geometry on boards built from numbers; every property is broken once on purpose by mutate_geometry.sh."""
import pytest

from arrays import Arr, rect
from pcbkit import rules
from pcbkit.config import ConfigError


def run(a, **over):
    return rules.track_geometry_parts(a.build(), over)


def kinds(a, **over):
    return sorted({k for k, *_ in run(a, **over)})


def base():
    return Arr('GND', 'SIG', 'OTHER')


def test_a_clean_board_passes_and_says_so():
    a = base().s('SIG', 0, 0, 0, 5, 0).s('SIG', 0, 5, 0, 8, 3).s('SIG', 0, 8, 3, 8, 9)       # 0, 45 and 90 degrees, runs of 5, 4.2 and 6
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


def test_the_segment_into_an_elongated_pad_runs_along_its_long_axis_and_a_squarer_pad_takes_either():
    long_pad = lambda angle_end, rot=0.0: base().part('U1', 0, 0).p('U1', '1', 0, 0, 'SIG', size=0.3, sy=1.2, rot=rot).s('SIG', 0, 0, 0, *angle_end)     # 0.3 x 1.2: long axis is y
    assert 'entry' not in kinds(long_pad((0, 3))) and 'entry' in kinds(long_pad((3, 0)))
    assert 'entry' not in kinds(long_pad((3, 0), rot=90.0)) and 'entry' in kinds(long_pad((0, 3), rot=90.0))           # the pad turned
    sq = lambda e: base().part('C1', 0, 0).p('C1', '1', 0, 0, 'SIG', size=0.8, sy=0.95).s('SIG', 0, 0, 0, *e)
    assert 'entry' not in kinds(sq((3, 0))) and 'entry' not in kinds(sq((0, 3))) and 'entry' in kinds(sq((3, 3)))     # either axis, but not 45 degrees
    assert 'entry' in kinds(long_pad((0, 3)), TRACK_ELONGATED_RATIO=10.0) is False or 'entry' not in kinds(long_pad((3, 0)), TRACK_ELONGATED_RATIO=10.0)
    rnd = base().part('C1', 0, 0).p('C1', '1', 0, 0, 'SIG', size=0.8, shape=0).s('SIG', 0, 0, 0, 3, 3)
    assert 'entry' not in kinds(rnd)                                            # a round pad has no axis
    other = base().part('C1', 0, 0).p('C1', '1', 0, 0, 'OTHER', size=0.3, sy=1.2).s('SIG', 0, 0, 0, 3, 0)
    assert 'entry' not in kinds(other)                                          # another net's pad is not entered by this track


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


def test_the_configuration_names_and_defaults_are_declared():
    text = rules.effective_config({}, 'track_geometry')
    for n in ('TRACK_ANGLE_STEP', 'TRACK_ANGLE_TOL', 'TRACK_MIN_LEG', 'TRACK_FINE_PITCH', 'TRACK_ELONGATED_RATIO', 'TRACK_OVERLAP_TOL'):
        assert n in text and 'default' in text
    with pytest.raises(ConfigError):
        rules.track_geometry(base().build(), dict(TRACK_MIN_LEGG=0.5))
