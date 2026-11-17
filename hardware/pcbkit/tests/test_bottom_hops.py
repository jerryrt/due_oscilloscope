"""rules.bottom_hops on boards built here from numbers; every property is broken once on purpose by mutate_kit.py."""
import pytest

from arrays import Arr
from pcbkit import rules
from pcbkit.config import ConfigError

CFG = dict(GND='GND', PLANE_LAYER='B', HOP_FENCES=[], HOP_SENSITIVE=['SENS'], HOP_KEEPOUT_PARTS=[])


def run(a, **over):
    return rules.bottom_hops(a.build(), {**CFG, **over})


def test_no_plane_layer_signal_copper_passes():
    assert run(Arr('GND', 'SIG')).ok
    assert run(Arr('GND', 'SIG').s('SIG', 0, 0, 0, 40, 0)).ok               # top copper is not a hop
    assert run(Arr('GND', 'SIG').s('GND', 1, 0, 0, 40, 0)).ok               # ground on the plane layer is the plane


def test_run_length_limit_is_exclusive_and_tunable():
    assert run(Arr('GND', 'SIG').s('SIG', 1, 0, 0, 3.0, 0)).ok
    r = run(Arr('GND', 'SIG').s('SIG', 1, 0, 0, 3.01, 0))
    assert not r.ok and r.detail == 'SIG: bottom run 3.0 mm, 0 vias (limit 3.0 mm, 2)'
    assert run(Arr('GND', 'SIG').s('SIG', 1, 0, 0, 3.01, 0), HOP_MAX=3.5).ok


def test_via_count_limit_counts_vias_of_the_runs_own_net_at_its_ends():
    a = Arr('GND', 'SIG').s('SIG', 1, 0, 0, 2, 0).v('SIG', 0, 0).v('SIG', 2, 0)
    assert run(a).ok
    b = Arr('GND', 'SIG').s('SIG', 1, 0, 0, 2, 0).v('SIG', 0, 0).v('SIG', 2, 0).v('SIG', 2.0, 0.04)
    r = run(b)
    assert not r.ok and '3 vias' in r.detail
    c = Arr('GND', 'SIG').s('SIG', 1, 0, 0, 2, 0).v('SIG', 0, 0).v('SIG', 2, 0).v('GND', 2.0, 0.0)      # another net's via is not counted
    assert run(c).ok
    d = Arr('GND', 'SIG').s('SIG', 1, 0, 0, 2, 0).v('SIG', 0, 0).v('SIG', 2, 0).v('SIG', 2.06, 0)      # 0.06 away: not at the end (default 0.05)
    assert run(d).ok and not run(d, HOP_VIA_TOL=0.1).ok
    assert run(b, HOP_MAX_VIAS=3).ok


def test_segments_join_end_to_end_at_a_t_and_by_crossing_not_by_a_gap_or_another_net():
    two = Arr('GND', 'SIG').s('SIG', 1, 0, 0, 2, 0).s('SIG', 1, 2, 0, 4, 0)
    assert not run(two).ok                                                  # one run of 4 mm
    tee = Arr('GND', 'SIG').s('SIG', 1, 0, 0, 4, 0).s('SIG', 1, 2, 0, 2, 2)  # 4 + 2 = 6 mm
    assert not run(tee).ok
    gap = Arr('GND', 'SIG').s('SIG', 1, 0, 0, 2, 0).s('SIG', 1, 2.02, 0, 4.02, 0)      # 0.02 apart: two 2 mm runs
    assert run(gap).ok and not run(gap, HOP_JOIN_TOL=0.05).ok
    other = Arr('GND', 'SIG', 'AUX').s('SIG', 1, 0, 0, 2, 0).s('AUX', 1, 2, 0, 4, 0)
    assert run(other).ok


def test_a_run_under_a_keepout_part_fails_with_its_margin_and_a_part_without_courtyard_is_skipped():
    a = Arr('GND', 'SIG').part('U1', 10, 10, (8, 8, 12, 12)).s('SIG', 1, 5, 10, 7.85, 10)         # its edge ends 0.05 short of the courtyard
    assert run(a, HOP_KEEPOUT_PARTS=['U1']).ok                              # the track is 0.2 wide (0.1 each side) and the pad margin is 0: clear
    assert not run(a, HOP_KEEPOUT_PARTS=['U1'], HOP_KEEPOUT_PAD=0.1).ok    # the margin reaches the courtyard
    inside = Arr('GND', 'SIG').part('U1', 10, 10, (8, 8, 12, 12)).s('SIG', 1, 9, 10, 11, 10)
    r = run(inside, HOP_KEEPOUT_PARTS=['U1'])
    assert not r.ok and r.detail == "SIG: bottom copper under ['U1']"
    nocourt = Arr('GND', 'SIG').part('U1', 10, 10).s('SIG', 1, 9, 10, 11, 10)
    assert run(nocourt, HOP_KEEPOUT_PARTS=['U1']).ok and run(nocourt, HOP_KEEPOUT_PARTS=['U9']).ok


def test_a_hop_inside_a_fence_fails():
    a = Arr('GND', 'SIG').s('SIG', 1, 5, 5, 6, 5)
    r = run(a, HOP_FENCES=[(0, 0, 10, 10)])
    assert not r.ok and r.detail == 'SIG: bottom segment inside an analog fence (0.0, 0.0, 10.0, 10.0)'
    assert run(a, HOP_FENCES=[(20, 20, 30, 30)]).ok
    assert not run(Arr('GND', 'SIG').s('SIG', 1, 10.1, 5, 12, 5), HOP_FENCES=[(0, 0, 10, 10)]).ok     # within half the track width of the edge
    assert run(Arr('GND', 'SIG').s('SIG', 1, 10.11, 5, 12, 5), HOP_FENCES=[(0, 0, 10, 10)]).ok


def test_a_hop_under_a_sensitive_track_or_pad_fails_with_the_clearance_tunable():
    near = Arr('GND', 'SIG', 'SENS1').s('SIG', 1, 0, 0, 2, 0).s('SENS1', 0, 0, 0.29, 2, 0.29)           # 0.29 apart, widths 0.2: edge gap 0.09 < 0.1
    r = run(near)
    assert not r.ok and r.detail == 'SIG: bottom segment under SENS1 (a hop under a sensitive net; bridge it on top)'
    far = Arr('GND', 'SIG', 'SENS1').s('SIG', 1, 0, 0, 2, 0).s('SENS1', 0, 0, 0.31, 2, 0.31)
    assert run(far).ok and not run(far, HOP_SENSITIVE_CLEAR=0.2).ok
    pad = Arr('GND', 'SIG', 'SENS1').part('R1', 1, 0.5).p('R1', '1', 1, 0.5, 'SENS1').s('SIG', 1, 0, 0, 2, 0)
    r = run(pad)
    assert not r.ok and r.detail == 'SIG: bottom segment under pad R1.1 of SENS1'
    off = Arr('GND', 'SIG', 'SENS1').part('R1', 1, 0.58).p('R1', '1', 1, 0.58, 'SENS1').s('SIG', 1, 0, 0, 2, 0)      # pad edge 0.18 from the track's centre line
    assert not run(off).ok and run(off, HOP_SENSITIVE_CLEAR=0.05).ok
    nonsens = Arr('GND', 'SIG', 'OTHER').s('SIG', 1, 0, 0, 2, 0).s('OTHER', 0, 0, 0, 2, 0)
    assert run(nonsens).ok
    assert run(Arr('GND', 'SIG', 'SENS1').s('SIG', 1, 0, 0, 2, 0).s('SENS1', 1, 0, 0.1, 2, 0.1)).ok      # a sensitive track on the plane layer itself is not 'under'


def test_project_names_raise_naming_the_key_tunables_default_and_are_reported():
    a = Arr('GND', 'SIG').build()
    for key in ('GND', 'PLANE_LAYER', 'HOP_FENCES', 'HOP_SENSITIVE', 'HOP_KEEPOUT_PARTS'):
        cfg = {k: v for k, v in CFG.items() if k != key}
        with pytest.raises(ConfigError, match=key):
            rules.bottom_hops(a, cfg)
    rep = []
    rules.bottom_hops(a, {**CFG, 'HOP_MAX': 4.0}, rep)
    got = {k: (v, s) for k, v, s in rep}
    assert got['HOP_MAX'] == (4.0, 'project') and got['HOP_MAX_VIAS'] == (2, 'default') and got['HOP_JOIN_TOL'] == (0.01, 'default')
    assert got['GND'] == ('GND', 'project') and len(rep) == 11


def test_effective_config_text_lists_every_name_with_its_source():
    t = rules.effective_config({**CFG, 'HOP_MAX': 4.0}, 'bottom_hops')
    lines = t.splitlines()
    assert lines[0] == 'effective configuration of bottom_hops' and len(lines) == 12
    assert any(l.startswith('HOP_MAX ') and 'project' in l and l.rstrip().endswith('4.0') for l in lines)
    assert any(l.startswith('HOP_JOIN_TOL') and 'default' in l and l.rstrip().endswith('0.01') for l in lines)
    with pytest.raises(ConfigError, match='HOP_FENCES'):
        rules.effective_config({k: v for k, v in CFG.items() if k != 'HOP_FENCES'}, 'bottom_hops')
