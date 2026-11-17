"""rules.decoupling on boards built here from numbers; each property broken once on purpose by mutate_kit.py."""
import pytest

from arrays import Arr
from pcbkit import rules
from pcbkit.config import ConfigError

CFG = dict(DECOUPLING=[('C1', 'U1', '8')], DECOUPLING_MAX=3.0)


def board(cx1, cx2=None, c_nets=('VCC', 'GND')):
    a = Arr('VCC', 'GND').part('U1', 0, 0).p('U1', '8', 0, 0, 'VCC').part('C1', 0, 0)
    a.p('C1', '1', cx1, 0, c_nets[0])
    a.p('C1', '2', cx1 + 1.0 if cx2 is None else cx2, 0, c_nets[1])
    return a


def run(a, **over):
    return rules.decoupling(a.build(), {**CFG, **over})


def test_a_near_capacitor_passes_and_the_figure_is_its_distance():
    r = run(board(2.0))
    assert r.ok and r.figures == {'C1>U1.8': 2.0} and r.detail == '1 caps within 3.0 mm: C1>U1.8 2.0'


def test_the_limit_is_exclusive_and_a_far_capacitor_is_named():
    assert run(board(3.0)).ok
    r = run(board(3.01))
    assert not r.ok and r.detail == 'C1 is 3.0 mm from U1 pin 8 (limit 3.0)'
    assert run(board(3.01), DECOUPLING_MAX=3.5).ok


def test_the_capacitor_pad_on_the_pins_net_is_the_one_measured():
    assert run(board(6.0, 2.0, c_nets=('GND', 'VCC'))).ok                   # pad 2 is on VCC and is near; pad 1 (GND) is far
    r = run(board(6.0, 2.0, c_nets=('GND', 'GND')))                           # neither pad on the pin's net: pad 1
    assert not r.ok and r.figures['C1>U1.8'] == 6.0


def test_with_both_pads_on_the_net_the_nearer_one_counts():
    r = run(board(2.0, 3.5, c_nets=('VCC', 'VCC')))
    assert r.ok and r.figures['C1>U1.8'] == 2.0


def test_each_listed_capacitor_is_judged_in_order():
    a = board(2.0).part('C2', 0, 0).p('C2', '1', 5, 0, 'VCC').p('C2', '2', 6, 0, 'GND')
    r = run(a, DECOUPLING=[('C1', 'U1', '8'), ('C2', 'U1', '8')])
    assert not r.ok and r.detail == 'C2 is 5.0 mm from U1 pin 8 (limit 3.0)' and list(r.figures) == ['C1>U1.8', 'C2>U1.8']


def test_project_names_raise_naming_the_key():
    a = board(2.0).build()
    for k in CFG:
        with pytest.raises(ConfigError, match=k):
            rules.decoupling(a, {kk: v for kk, v in CFG.items() if kk != k})
