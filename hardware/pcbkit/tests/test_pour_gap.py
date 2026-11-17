"""rules.pour_gap on boards built here from numbers; each property broken once on purpose by mutate_kit.py."""
import math

import pytest

from arrays import Arr, rect
from pcbkit import rules
from pcbkit.config import ConfigError

CFG = dict(GND='GND', POUR_NODES=['NODE'], POUR_KEEP_BACK=0.5)


def run(a, **over):
    return rules.pour_gap(a.build(), {**CFG, **over})


def base():
    return Arr('GND', 'NODE', 'INFO').s('NODE', 0, 0, 0, 4, 0)             # a 0.2 wide node track on top


def test_nothing_to_measure_to_gives_inf_and_passes():
    r = run(base())
    assert r.ok and r.figures['gnd_track_gap_NODE_mm'] == math.inf and r.figures['pour_gap_NODE_mm'] == math.inf
    r = run(Arr('GND', 'NODE'))                                              # no node copper at all
    assert r.ok and r.figures['pour_gap_NODE_mm'] == math.inf


def test_a_ground_track_nearer_than_the_keep_back_is_found_edge_to_edge():
    a = base().s('GND', 0, 0, 0.69, 4, 0.69)                                  # centre lines 0.69 apart, edges 0.49
    r = run(a)
    assert not r.ok and r.detail == 'NODE: ground track within 0.5 mm' and abs(r.figures['gnd_track_gap_NODE_mm'] - 0.49) < 1e-9
    assert run(base().s('GND', 0, 0, 0.71, 4, 0.71)).ok                       # edges 0.51
    assert run(base().s('GND', 1, 0, 0.3, 4, 0.3)).ok                         # a bottom GND track is not top ground copper


def test_a_pour_edge_nearer_than_the_keep_back_is_found_and_a_pour_the_node_lies_on_is_zero():
    a = base().z('GND', 0, [(False, rect(0, 0.59, 10, 5))])                   # fill edge 0.59 from the centre line, 0.49 from the edge
    r = run(a)
    assert not r.ok and r.detail == 'NODE: ground pour within 0.5 mm'
    assert run(base().z('GND', 0, [(False, rect(0, 0.61, 10, 5))])).ok
    on = base().z('GND', 0, [(False, rect(-1, -1, 10, 5))])
    assert run(on).figures['pour_gap_NODE_mm'] == 0.0
    hole = base().z('GND', 0, [(False, rect(-5, -5, 10, 5)), (True, rect(-1, -1, 6, 1))])      # the node sits in a hole of the fill: 0.9 to its edge
    r = run(hole)
    assert r.ok and abs(r.figures['pour_gap_NODE_mm'] - 0.9) < 1e-9


def test_unfilled_keepout_other_net_and_bottom_zones_are_not_ground_pour():
    for z in (lambda a: a.z('GND', 0, [(False, rect(-1, -1, 10, 5))], filled=False), lambda a: a.z('GND', 0, [(False, rect(-1, -1, 10, 5))], keepout=True),
              lambda a: a.z('INFO', 0, [(False, rect(-1, -1, 10, 5))]), lambda a: a.z('GND', 1, [(False, rect(-1, -1, 10, 5))])):
        assert run(z(base())).ok


def test_a_pad_of_the_node_counts_as_node_copper():
    a = Arr('GND', 'NODE').part('R1', 0, 0).p('R1', '1', 0, 0, 'NODE', size=1.0).s('GND', 0, 0, 0.9, 4, 0.9)       # pad edge 0.5, GND track edge 0.8: 0.3
    r = run(a)
    assert not r.ok and abs(r.figures['gnd_track_gap_NODE_mm'] - 0.3) < 1e-9


def test_info_nodes_are_reported_and_not_judged():
    a = base().s('INFO', 0, 0, 3, 4, 3).s('GND', 0, 0, 3.3, 4, 3.3)
    r = run(a, POUR_INFO_NODES=['INFO'])
    assert r.ok and abs(r.figures['gnd_track_gap_INFO_mm'] - 0.1) < 1e-9
    gaps = rules.pour_gaps(a.build(), {**CFG, 'POUR_INFO_NODES': ['INFO']})
    assert [g[0] for g in gaps] == ['NODE', 'INFO']


def test_keep_back_is_a_project_name_and_the_info_list_defaults_to_nothing():
    a = base().build()
    for k in ('GND', 'POUR_NODES', 'POUR_KEEP_BACK'):
        with pytest.raises(ConfigError, match=k):
            rules.pour_gap(a, {kk: v for kk, v in CFG.items() if kk != k})
    rep = []
    rules.pour_gap(a, CFG, rep)
    got = {k: (v, s) for k, v, s in rep}
    assert got['POUR_INFO_NODES'] == ((), 'default') and got['POUR_KEEP_BACK'] == (0.5, 'project')
