"""rules.sensitive_nets on boards built here from numbers; each property broken once on purpose by mutate_kit.py."""
import pytest

from arrays import Arr
from pcbkit import rules
from pcbkit.config import ConfigError


def run(a, entries, **over):
    return rules.sensitive_nets(a.build(), dict(GND='GND', SENSITIVE_NETS=entries, **over))


def parts(a, entries):
    return rules.sensitive_nets_parts(a.build(), dict(GND='GND', SENSITIVE_NETS=entries))


def test_a_clean_board_passes():
    a = Arr('GND', 'SENS').s('SENS', 0, 0, 0, 5, 0)
    r = run(a, [dict(net='SENS')])
    assert r.ok and r.figures['nets'] == 1 and r.figures['longest_mm'] == 5.0 and r.detail == '1 sensitive nets: no via, short, no track beside'


def test_a_via_on_a_listed_net_is_found_and_no_via_false_allows_it():
    a = Arr('GND', 'SENS', 'OTHER').v('SENS', 1, 1).v('OTHER', 5, 5)
    r = run(a, [dict(net='SENS')])
    assert not r.ok and r.detail == 'SENS: a via'
    assert run(a, [dict(net='SENS', no_via=False)]).ok
    assert run(Arr('GND', 'SENS', 'OTHER').v('OTHER', 5, 5), [dict(net='SENS')]).ok          # a via of another net is not a finding


def test_copper_on_the_other_layer_only_when_asked():
    a = Arr('GND', 'SENS').s('SENS', 1, 0, 0, 2, 0)
    assert run(a, [dict(net='SENS')]).ok
    r = run(a, [dict(net='SENS', no_bottom=True)])
    assert not r.ok and r.detail == 'SENS: bottom copper'
    assert run(Arr('GND', 'SENS').s('SENS', 0, 0, 0, 2, 0), [dict(net='SENS', no_bottom=True)]).ok


def test_length_limit_is_exclusive_and_counts_top_track_only():
    assert run(Arr('GND', 'SENS').s('SENS', 0, 0, 0, 14.0, 0), [dict(net='SENS', max_length=14)]).ok
    r = run(Arr('GND', 'SENS').s('SENS', 0, 0, 0, 14.01, 0), [dict(net='SENS', max_length=14)])
    assert not r.ok and r.detail == 'SENS: 14.0 mm of track'
    assert run(Arr('GND', 'SENS').s('SENS', 0, 0, 0, 10, 0).s('SENS', 1, 0, 1, 10, 1), [dict(net='SENS', max_length=14)]).ok
    assert run(Arr('GND', 'SENS').s('SENS', 0, 0, 0, 20, 0), [dict(net='SENS')]).ok          # no limit given: none applied


def test_a_foreign_top_track_within_the_gap_is_found_with_the_widths_in_the_boundary():
    # the gap is measured from the copper edge: centre-line distance < gap + (w1 + w2) / 2 = 0.6 + 0.2
    near = Arr('GND', 'SENS', 'AGG').s('SENS', 0, 0, 0, 2, 0).s('AGG', 0, 0, 0.79, 2, 0.79)
    r = run(near, [dict(net='SENS', gap=0.6)])
    assert not r.ok and r.detail == 'SENS track within 0.6 mm of AGG track' and r.figures['tracks_too_close'] == 1.0
    far = Arr('GND', 'SENS', 'AGG').s('SENS', 0, 0, 0, 2, 0).s('AGG', 0, 0, 0.81, 2, 0.81)
    assert run(far, [dict(net='SENS', gap=0.6)]).ok


@pytest.mark.parametrize('what,build', [
    ('the plane net', lambda: Arr('GND', 'SENS').s('SENS', 0, 0, 0, 2, 0).s('GND', 0, 0, 0.3, 2, 0.3)),
    ('the same net', lambda: Arr('GND', 'SENS').s('SENS', 0, 0, 0, 2, 0).s('SENS', 0, 0, 0.3, 2, 0.3)),
    ('another layer', lambda: Arr('GND', 'SENS', 'AGG').s('SENS', 0, 0, 0, 2, 0).s('AGG', 1, 0, 0.3, 2, 0.3)),
])
def test_these_are_not_foreign_tracks(what, build):
    assert run(build(), [dict(net='SENS', gap=0.6)]).ok, what


def test_two_listed_nets_beside_each_other_are_found_and_each_net_uses_its_own_gap():
    a = Arr('GND', 'S1', 'S2').s('S1', 0, 0, 0, 2, 0).s('S2', 0, 0, 0.5, 2, 0.5)
    assert not run(a, [dict(net='S1', gap=0.6), dict(net='S2', gap=0.6)]).ok
    r = run(a, [dict(net='S1', gap=0.1), dict(net='S2', gap=0.6)])                      # S2's segment sees S1 at 0.5 < 0.6 + 0.2
    assert not r.ok and r.detail == 'S2 track within 0.6 mm of S1 track'
    assert run(a, [dict(net='S1', gap=0.1), dict(net='S2', gap=0.1)]).ok


def test_findings_come_in_net_order_via_bottom_length_then_the_neighbours():
    a = Arr('GND', 'S1', 'S2', 'AGG').v('S1', 0, 0).s('S1', 1, 0, 0, 1, 0).s('S2', 0, 0, 5, 20, 5).s('S1', 0, 0, 9, 1, 9).s('AGG', 0, 0, 9.3, 1, 9.3)
    f, _ = parts(a, [dict(net='S1', no_bottom=True, gap=0.6), dict(net='S2', max_length=14)])
    assert [(x.kind, x.net) for x in f] == [('via', 'S1'), ('bottom', 'S1'), ('length', 'S2'), ('beside', 'S1')]
    assert f[3].other == 'AGG' and f[3].value == 0.6


def test_entries_are_checked_and_project_names_raise():
    a = Arr('GND', 'SENS').build()
    with pytest.raises(ConfigError, match='max_lenght'):
        rules.sensitive_nets(a, dict(GND='GND', SENSITIVE_NETS=[dict(net='SENS', max_lenght=3)]))
    with pytest.raises(ConfigError, match="'net'"):
        rules.sensitive_nets(a, dict(GND='GND', SENSITIVE_NETS=[dict(gap=3)]))
    for k in ('GND', 'SENSITIVE_NETS'):
        cfg = {kk: v for kk, v in dict(GND='GND', SENSITIVE_NETS=[]).items() if kk != k}
        with pytest.raises(ConfigError, match=k):
            rules.sensitive_nets(a, cfg)
    assert 'SENSITIVE_NETS' in rules.effective_config(dict(GND='GND', SENSITIVE_NETS=[]), 'sensitive_nets')
