"""rules.keepout_ring on boards built here from numbers; each property broken once on purpose by mutate_kit.py."""
import pytest

from arrays import Arr
from pcbkit import rules
from pcbkit.config import ConfigError

CFG = dict(KEEPOUT_PARTS=['G1'], KEEPOUT_NETS=['SENS'], KEEPOUT_EXEMPT_PARTS=['G1'], KEEPOUT_DIST=10.0)


def base():
    return Arr('GND', 'SENS', 'OTHER').part('G1', 0, 0, (-2, -2, 2, 2))


def run(a, **over):
    return rules.keepout_ring(a.build(), {**CFG, **over})


def test_far_copper_passes_and_says_so():
    r = run(base().s('SENS', 0, 20, 0, 30, 0))
    assert r.ok and r.detail == 'sensitive copper >= 10.0 mm from G1' and r.figures['min_distance_mm'] == pytest.approx(17.9)


def test_a_track_is_measured_from_its_edge_to_the_courtyard():
    r = run(base().s('SENS', 0, 11.9, -1, 11.9, 1))                           # centre 9.9 from the courtyard edge at 2, edge at 9.8
    assert not r.ok and r.detail == 'SENS 9.8 mm' and r.figures['min_distance_mm'] == pytest.approx(9.8)
    assert run(base().s('SENS', 0, 12.11, -1, 12.11, 1)).ok                    # edge 10.01
    assert run(base().s('SENS', 0, 12.3, -1, 12.3, 1), KEEPOUT_DIST=5.0).ok and not run(base().s('SENS', 0, 12.3, -1, 12.3, 1), KEEPOUT_DIST=20.0).ok


def test_only_top_copper_of_the_sensitive_nets_counts():
    assert run(base().s('SENS', 1, 5, 0, 6, 0)).ok                            # bottom
    assert run(base().s('OTHER', 0, 5, 0, 6, 0)).ok                           # another net
    assert not run(base().s('SENS', 0, 5, 0, 6, 0)).ok
    assert not run(Arr('GND', 'SENSX').part('G1', 0, 0, (-2, -2, 2, 2)).s('SENSX', 0, 5, 0, 6, 0)).ok        # prefix match


def test_a_pad_is_judged_unless_its_part_is_exempt_and_is_measured_by_its_size():
    a = base().part('R1', 8, 0).p('R1', '1', 8, 0, 'SENS', size=1.0)            # pad edge 7.5 from the centre, 5.5 from the courtyard
    r = run(a)
    assert not r.ok and r.detail == 'SENS pad R1.1 5.5 mm'
    assert run(a, KEEPOUT_EXEMPT_PARTS=['R1']).ok
    b = base().p('G1', '1', 1, 0, 'SENS')                                       # the keep-out part's own pad is exempt by listing it
    assert run(b).ok and not run(b, KEEPOUT_EXEMPT_PARTS=[]).ok


def test_the_nearest_of_several_parts_counts_and_findings_are_sorted_and_unique():
    a = Arr('GND', 'SENS').part('G1', 0, 0, (-2, -2, 2, 2)).part('G2', 30, 0, (28, -2, 32, 2)).s('SENS', 0, 20, 0, 26.5, 0).s('SENS', 0, 5, 5, 6, 5)
    r = run(a, KEEPOUT_PARTS=['G1', 'G2'])
    assert not r.ok and r.detail == 'SENS 1.4 mm; SENS 4.1 mm'                  # the first track is nearest G2 (1.4), the second G1's corner (4.1)
    assert r.figures['violations'] == 2.0 and r.figures['min_distance_mm'] == pytest.approx(1.4)


def test_a_pad_is_judged_against_the_nearest_part_too():
    a = Arr('GND', 'SENS').part('G1', 0, 0, (-2, -2, 2, 2)).part('G2', 30, 0, (28, -2, 32, 2)).part('R1', 26, 0).p('R1', '1', 26, 0, 'SENS')
    r = run(a, KEEPOUT_PARTS=['G1', 'G2'], KEEPOUT_EXEMPT_PARTS=[])
    assert not r.ok and r.detail == 'SENS pad R1.1 1.6 mm'


def test_project_names_raise_naming_the_key():
    a = base().build()
    for k in CFG:
        with pytest.raises(ConfigError, match=k):
            rules.keepout_ring(a, {kk: v for kk, v in CFG.items() if kk != k})
