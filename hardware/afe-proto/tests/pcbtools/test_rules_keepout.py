"""A rule area (keepout zone) is not copper: z_keepout in BoardArrays, and the rules that look at zones skip it. Numpy only, so the
mutation harness (mutate_rules.py) can run it against a broken copy of rules.py."""
import numpy as np

from pcbtools import boardio, rules as R

from synth import Synth, cfg


def test_a_cache_without_z_keepout_loads_with_every_zone_a_pour(tmp_path):
    s = Synth('/GND').z('/GND', 'B', [([(0, 0), (5, 0), (5, 5), (0, 5)], False)]).z('', 'F', [], filled=False, keepout=True)
    b = s.build()
    assert b.z_keepout.tolist() == [False, True]
    p = tmp_path / 'b.npz'
    boardio.save_npz(b, p)
    d = dict(np.load(p, allow_pickle=False))
    del d['z_keepout']                                                                  # a cache written before the field existed
    np.savez_compressed(tmp_path / 'old.npz', **d)
    o = boardio.load_npz(str(tmp_path / 'old.npz'))
    assert o.z_keepout.tolist() == [False, False] and o.z_layer.tolist() == b.z_layer.tolist()


def lr1_with(keepout):
    s = Synth('/GND').part('C1', 10, 10).p('C1', '1', 10, 10, '/GND').v('/GND', 11, 10)
    s.z('/GND', 'B', [([(0, 0), (50, 0), (50, 50), (0, 50)], False)])
    if keepout:
        s.z('', 'B', [([(0, -5), (50, -5), (50, 0), (0, 0)], False)], filled=False, keepout=True)       # a rule area on B.Cu, no net
    return s.build()


C1 = cfg(ANALOG_REFS=frozenset(), ANALOG_FENCE=(), OUTLINE={}, XSENS=('/A0',))


def test_a_rule_area_on_the_bottom_layer_does_not_change_lr1():
    a, b = R.lr1(lr1_with(False), C1), R.lr1(lr1_with(True), C1)
    assert a.ok, a.detail
    assert (a.ok, a.detail, a.figures) == (b.ok, b.detail, b.figures)
    # the arm that can fail: the same board with the rule area read as copper (the flag cleared) is a "bottom zone of no net"
    c = lr1_with(True).replace(z_keepout=np.zeros(2, bool))
    r = R.lr1(c, C1)
    assert not r.ok and 'bottom zone of no net' in r.detail


