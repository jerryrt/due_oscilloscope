"""rules.ground_plane on boards built here from numbers; every property is broken once on purpose by mutate_kit.py."""
import pytest

from arrays import Arr, rect
from pcbkit import rules
from pcbkit.config import ConfigError

CFG = dict(GND='GND', PLANE_LAYER='B')
PLANE = [(False, rect(0, 0, 50, 50))]


def good():
    a = Arr('GND', 'SIG').z('GND', 1, PLANE).part('C1', 10, 10).p('C1', '1', 10, 10, 'GND').p('C1', '2', 12, 10, 'SIG').v('GND', 11, 11).s('GND', 0, 10, 10, 11, 11)       # its own via, joined by its own track
    return a


def run(a, **over):
    return rules.ground_plane(a.build(), {**CFG, **over})


def test_a_good_board_passes_and_says_so():
    r = run(good())
    assert r.ok and r.figures['plane_pieces'] == 1 and r.figures['gnd_pads'] == 1 and r.figures['pads_without_via'] == 0
    assert r.detail == '2 layers, one plane, 1 GND pads each with its own via (a plated hole of the pad counts)'


@pytest.mark.parametrize('what,build,detail', [
    ('no zone', lambda: Arr('GND', 'SIG').part('C1', 10, 10).p('C1', '1', 10, 10, 'GND').v('GND', 11, 11), 'no bottom GND zone'),
    ('two GND zones', lambda: good().z('GND', 1, [(False, rect(60, 60, 70, 70))]), '2 bottom GND zones, not 1'),
    ('unfilled', lambda: Arr('GND').z('GND', 1, PLANE, filled=False), 'bottom zone not filled'),
    ('another net', lambda: good().z('SIG', 1, [(False, rect(60, 60, 70, 70))]), 'bottom zone of SIG: the bottom layer carries the ground plane only'),
    ('two pieces', lambda: Arr('GND').z('GND', 1, [(False, rect(0, 0, 10, 10)), (False, rect(20, 0, 30, 10))]), 'bottom plane is 2 pieces, not 1'),
    ('four layers', lambda: Arr('GND', layers=4).z('GND', 1, PLANE), '4 copper layers'),
])
def test_plane_findings(what, build, detail):
    a = build()
    r = run(a)
    assert not r.ok and detail in r.detail, (what, r.detail)


def test_a_hole_is_not_a_piece_and_a_keepout_is_not_copper():
    a = Arr('GND').z('GND', 1, [(False, rect(0, 0, 50, 50)), (True, rect(10, 10, 20, 20))])
    assert run(a).figures['plane_pieces'] == 1
    b = Arr('GND', 'SIG').z('GND', 1, PLANE).z('SIG', 1, PLANE, keepout=True)       # a rule area on the layer: not a split plane
    assert run(b).ok
    c = Arr('GND').z('GND', 0, PLANE)                                                # a top zone is not the bottom plane
    assert not run(c).ok


def test_plane_layer_is_a_project_choice_and_the_words_follow_it():
    a = Arr('GND').z('GND', 0, PLANE)
    r = run(a, PLANE_LAYER='F')
    assert r.ok
    r = run(Arr('GND'), PLANE_LAYER=0)
    assert r.detail == 'no top GND zone'


def test_every_smd_ground_pad_needs_a_via_of_its_own():
    a = good()
    a.part('C2', 20, 10).p('C2', '1', 20, 10, 'GND')                                  # a second pad, no via for it: the one via is taken
    r = run(a)
    assert not r.ok and '1 SMD ground pads without a via of their own' in r.detail and 'C2.1' in r.detail
    b = good().v('GND', 21, 11)
    assert run(b).ok
    two = Arr('GND').z('GND', 1, PLANE).part('C1', 10, 10).p('C1', '1', 10, 10, 'GND').p('C1', '2', 12, 10, 'GND').v('GND', 11, 10.5).s('GND', 0, 10, 10, 11, 10.5).s('GND', 0, 12, 10, 11, 10.5)
    r2 = run(two)
    assert not r2.ok and '1 SMD ground pads without a via' in r2.detail          # one via within reach of both pads serves only one
    assert run(good().v('SIG', 21, 11)).ok is True                                    # a via of another net changes nothing for C1
    c = Arr('GND', 'SIG').z('GND', 1, PLANE).part('C1', 10, 10).p('C1', '1', 10, 10, 'GND').v('SIG', 11, 11)
    assert not run(c).ok                                                              # ... and does not serve as the GND via
    d = Arr('GND').z('GND', 1, PLANE).part('J1', 10, 10).p('J1', '1', 10, 10, 'GND', smd=False)
    assert run(d).ok                                                                  # a through-hole pad needs none


def test_via_reach_is_a_tunable_with_a_default_of_3_mm():
    near = Arr('GND').z('GND', 1, PLANE).part('C1', 10, 10).p('C1', '1', 10, 10, 'GND').v('GND', 13.0, 10).s('GND', 0, 10, 10, 13.0, 10)
    far = Arr('GND').z('GND', 1, PLANE).part('C1', 10, 10).p('C1', '1', 10, 10, 'GND').v('GND', 13.01, 10).s('GND', 0, 10, 10, 13.01, 10)
    assert run(near).ok and not run(far).ok
    assert run(far, GND_VIA_REACH=3.5).ok and not run(near, GND_VIA_REACH=2.5).ok


def test_copper_layer_count_is_a_tunable_with_a_default_of_2():
    a = Arr('GND', layers=4).z('GND', 1, PLANE)
    assert not run(a).ok and run(a, COPPER_LAYERS=4).ok


def test_project_names_raise_naming_the_key_and_tunables_default_and_are_reported():
    a = good().build()
    with pytest.raises(ConfigError, match='GND'):
        rules.ground_plane(a, {'PLANE_LAYER': 'B'})
    with pytest.raises(ConfigError, match='PLANE_LAYER'):
        rules.ground_plane(a, {'GND': 'GND'})
    rep = []
    rules.ground_plane(a, {**CFG, 'GND_VIA_REACH': 4.0}, rep)
    assert {k: (v, s) for k, v, s in rep} == {'GND': ('GND', 'project'), 'PLANE_LAYER': ('B', 'project'), 'COPPER_LAYERS': (2, 'default'),
                                              'GND_VIA_REACH': (4.0, 'project'), 'GND_VIA_TIE': (True, 'default')}
