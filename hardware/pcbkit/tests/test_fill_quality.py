"""rules.fill_quality on boards built from numbers; every property is broken once on purpose by mutate_geometry.sh."""
import pytest

from arrays import Arr, rect
from pcbkit import rules
from pcbkit.board import FieldNotRead

DUMBBELL = [(0, 0), (10, 0), (10, 4.85), (12, 4.85), (12, 0), (22, 0), (22, 10), (12, 10), (12, 5.15), (10, 5.15), (10, 10), (0, 10)]       # two squares joined by a 0.3 mm strip
FINGER = [(0, 0), (10, 0), (10, 4.85), (12, 4.85), (12, 5.15), (10, 5.15), (10, 10), (0, 10)]
WIDE_FINGER = [(0, 0), (10, 0), (10, 4.4), (12.4, 4.4), (12.4, 5.6), (10, 5.6), (10, 10), (0, 10)]                                          # a 1.2 mm wide, 2.4 mm long finger


def board(ring, layer=0, conn=1, **kw):
    return Arr('GND', 'SIG').z('GND', layer, [(False, ring)], conn=conn, **kw)


def kinds(a, **over):
    parts, _ = rules.fill_quality_parts(a.build(), {**dict(GND='GND', FILL_LAYERS=('F',)), **over})
    return sorted({k for k, *_ in parts})


def test_a_plain_pour_passes_and_says_so():
    r = rules.fill_quality(board(rect(0, 0, 20, 20)).build(), dict(GND='GND', FILL_LAYERS=('F',)))
    assert r.ok and r.figures['violations'] == 0 and r.figures['F_outline_mm'] == 80.0


def test_a_strip_narrower_than_the_minimum_is_found_and_a_wide_one_is_not():
    assert kinds(board(DUMBBELL)) == ['narrow']
    assert kinds(board(DUMBBELL), FILL_MIN_WIDTH=0.2) == []
    parts, _ = rules.fill_quality_parts(board(DUMBBELL).build(), dict(GND='GND', FILL_LAYERS=('F',)))
    assert '0.3' in [p for p in parts if p[0] == 'narrow'][0][1] or '0.4' in [p for p in parts if p[0] == 'narrow'][0][1]


def test_the_minimum_width_is_per_layer_and_a_single_number_applies_to_all():
    both = dict(FILL_LAYERS=('F', 'B'), FILL_THERMAL_LAYERS=(), FILL_SOLID_LAYERS=())
    two = lambda: board(DUMBBELL, 0).z('GND', 1, [(False, DUMBBELL)])
    parts = lambda **o: sorted(p[1][0] for p in rules.fill_quality_parts(two().build(), {**dict(GND='GND'), **both, **o})[0] if p[0] == 'narrow')
    assert parts() == ['B', 'F']                                       # the strip is 0.3: under the top's 0.8, and under the plane's 0.5 as well
    assert parts(FILL_MIN_WIDTH={'F': 0.2, 'B': 0.5}) == ['B'] and parts(FILL_MIN_WIDTH={'F': 0.5, 'B': 0.2}) == ['F']
    assert parts(FILL_MIN_WIDTH=0.2) == [] and parts(FILL_MIN_WIDTH=0.5) == ['B', 'F']


def test_the_pour_itself_is_measured_not_the_pour_with_a_pad_laid_over_it():
    covered = board(DUMBBELL).part('C1', 11, 5).p('C1', '1', 11, 5, 'GND', size=1.0, sy=1.0)          # a GND pad over the whole strip widens the copper, not the pour
    assert 'narrow' in kinds(covered)


def test_the_rounding_of_a_corner_is_not_a_finger_unless_the_length_factor_is_off():
    assert kinds(board(rect(0, 0, 20, 20))) == []
    assert kinds(board(rect(0, 0, 20, 20)), FILL_LENGTH_FACTOR=0.0) != []                              # without the factor every convex corner reads as a tooth


def test_a_finger_touching_other_copper_at_one_end_is_a_dead_end_and_a_strip_between_regions_is_not():
    assert 'dead_end' in kinds(board(FINGER)) and 'dead_end' not in kinds(board(DUMBBELL))
    assert 'dead_end' in kinds(board(WIDE_FINGER)) and 'narrow' not in kinds(board(WIDE_FINGER))          # 1.2 mm is wide enough, and still a dead end under FILL_DEAD_END_WIDTH
    assert 'dead_end' not in kinds(board(WIDE_FINGER), FILL_DEAD_END_WIDTH=1.0)
    with_via = board(FINGER).v('GND', 11.8, 5.0, dia=0.4, drill=0.2)
    assert 'dead_end' not in kinds(with_via)                                                            # the via is its second end


def test_the_smd_gnd_pads_of_the_top_zone_need_thermal_reliefs_and_the_bottom_plane_must_be_solid():
    def a(conn_top, conn_bot):
        b = board(rect(0, 0, 20, 20), 0, conn_top).z('GND', 1, [(False, rect(0, 0, 20, 20))], conn=conn_bot).part('C1', 5, 5).p('C1', '1', 5, 5, 'GND')
        return b
    both = dict(FILL_LAYERS=('F', 'B'))
    assert kinds(a(1, 2), **both) == []
    assert kinds(a(2, 2), **both) == ['thermal'] and kinds(a(0, 2), **both) == ['thermal']
    assert kinds(a(1, 1), **both) == ['solid']
    nopad = board(rect(0, 0, 20, 20), 0, 2).part('C1', 5, 5).p('C1', '1', 5, 5, 'SIG')
    assert kinds(nopad, **both) == []                                                                   # no SMD GND pad on the top: nothing to relieve
    thru = board(rect(0, 0, 20, 20), 0, 2).part('J1', 5, 5).p('J1', '1', 5, 5, 'GND', smd=False)
    assert kinds(thru, **both) == []                                                                    # a through-hole pad is not an SMD pad
    assert kinds(a(2, 2), FILL_THERMAL_LAYERS=(), FILL_SOLID_LAYERS=(), **both) == []


def test_a_board_read_before_the_zone_fields_is_refused_not_passed():
    b = board(rect(0, 0, 20, 20)).build()
    import dataclasses
    old = b.replace(read_fields=frozenset()) if hasattr(b, 'replace') else None
    if old is not None:
        with pytest.raises(FieldNotRead):
            rules.fill_quality_parts(old, dict(GND='GND'))


def _hugged(ys, x=20.9):
    a = board(rect(0, 0, 20, 20)).part('U1', 30, 30)
    for n, y in enumerate(ys):
        a.p('U1', str(n + 1), x, y, 'SIG', size=1.0)
    return a


def test_a_row_of_pads_the_pour_edge_hugs_is_rough_and_a_single_pad_or_a_disabled_layer_is_not():
    assert 'rough' in kinds(_hugged([5, 7, 9]))
    assert 'rough' not in kinds(_hugged([7]))
    assert 'rough' not in kinds(_hugged([5, 7, 9], x=24.0))
    assert 'rough' not in kinds(_hugged([5, 7, 9]), FILL_ROUGH_LAYERS=())
    assert 'rough' not in kinds(_hugged([5, 7, 9]), FILL_ROUGH_TOL=0.0)                      # 0.4 mm from the edge is not within the 0.3 clearance
    assert 'rough' not in kinds(_hugged([5, 7, 9]), FILL_ROUGH_LINK=0.2)                    # the row link distance is the limit
    r = rules.fill_quality(_hugged([5, 7, 9]).build(), dict(GND='GND', FILL_LAYERS=('F',)))
    assert not r.ok and r.figures['rough'] == 1.0 and r.figures['F_rough'] == 1.0


# ---- connector ground pins and SMD ground pads of the top pour

def _pins(pour, pins, **over):
    a = board(pour).part('J1', 30, 30).part('U1', 40, 40)
    for n, (ref, x, y, smd) in enumerate(pins):
        a.p(ref, str(n + 1), x, y, 'GND', smd=smd, size=1.0, mask=1 if smd else 3)
    return a


def test_a_connector_ground_pin_carved_out_of_the_top_pour_is_a_shell_finding():
    pour = rect(0, 0, 20, 20)
    ok = _pins(pour, [('J1', 10, 10, False)])
    assert 'shell' not in kinds(ok, FILL_SHELL_PREFIXES=('J',))
    carved = _pins(rect(0, 0, 5, 20), [('J1', 10, 10, False)])                                   # no pour near the pin
    assert 'shell' in kinds(carved, FILL_SHELL_PREFIXES=('J',))
    assert 'shell' not in kinds(carved)                                                          # not asked for
    assert 'shell' not in kinds(carved, FILL_SHELL_PREFIXES=('K',))                              # another prefix
    other = _pins(rect(0, 0, 5, 20), [('U1', 10, 10, False)])
    assert 'shell' not in kinds(other, FILL_SHELL_PREFIXES=('J',))                               # a part that is not a connector
    smd = _pins(rect(0, 0, 5, 20), [('J1', 10, 10, True)])
    assert 'shell' not in kinds(smd, FILL_SHELL_PREFIXES=('J',))                                 # only through-hole pins
    part = _pins(rect(0, 0, 10.0, 20), [('J1', 10, 10, False)])                                  # pour on one side only: partly round it
    assert 'shell' in kinds(part, FILL_SHELL_PREFIXES=('J',), FILL_SHELL_MIN=0.9) and 'shell' not in kinds(part, FILL_SHELL_PREFIXES=('J',), FILL_SHELL_MIN=0.1)


def test_an_smd_ground_pad_outside_the_pour_needs_a_via_at_its_edge():
    out = _pins(rect(0, 0, 5, 20), [('U1', 10, 10, True)])
    assert 'gndpad' in kinds(out, FILL_GNDPAD_MIN=0.2)
    inside = _pins(rect(0, 0, 20, 20), [('U1', 10, 10, True)])
    assert 'gndpad' not in kinds(inside, FILL_GNDPAD_MIN=0.2)
    near = _pins(rect(0, 0, 5, 20), [('U1', 10, 10, True)]).v('GND', 10, 10.8)                    # a via whose annulus touches the pad's edge
    assert 'gndpad' not in kinds(near)
    far = _pins(rect(0, 0, 5, 20), [('U1', 10, 10, True)]).v('GND', 10, 11.5)                     # a stub's length away
    assert 'gndpad' in kinds(far)
    other = _pins(rect(0, 0, 5, 20), [('U1', 10, 10, True)]).v('SIG', 10, 10.8)
    assert 'gndpad' in kinds(other)                                                               # a via of another net does not count
    assert 'gndpad' not in kinds(out, FILL_GNDPAD_MIN=0.0)                                         # switched off
    th = _pins(rect(0, 0, 5, 20), [('U1', 10, 10, False)])
    assert 'gndpad' not in kinds(th)                                                              # a through-hole pin is the shell's business


def test_a_named_shell_or_gndpad_exception_waives_exactly_one_finding_and_a_stale_one_fails():
    import pytest
    from pcbkit.config import ConfigError
    carved = _pins(rect(0, 0, 5, 20), [('J1', 10, 10, False)])
    assert 'shell' in kinds(carved, FILL_SHELL_PREFIXES=('J',))
    assert kinds(carved, FILL_SHELL_PREFIXES=('J',), FILL_SHELL_EXCEPTIONS=[('J1', '1', 'a header row')]) == []
    assert kinds(carved, FILL_SHELL_PREFIXES=('J',), FILL_SHELL_EXCEPTIONS=[('J1', '9', 'x')]) == ['shell', 'stale_exception']
    assert kinds(carved, FILL_SHELL_PREFIXES=('J',), FILL_SHELL_EXCEPTIONS=[('J1', '1', 'a'), ('J1', '1', 'b')]) == ['stale_exception']        # the second finds nothing left
    out = _pins(rect(0, 0, 5, 20), [('U1', 10, 10, True)])
    assert 'gndpad' in kinds(out) and 'gndpad' not in kinds(out, FILL_GNDPAD_EXCEPTIONS=[('U1', '1', 'no room')])
    assert kinds(out, FILL_GNDPAD_EXCEPTIONS=[('U1', '2', 'x')]) == ['gndpad', 'stale_exception']
    with pytest.raises(ConfigError):
        kinds(carved, FILL_SHELL_PREFIXES=('J',), FILL_SHELL_EXCEPTIONS=[('J1', '1', '')])
    with pytest.raises(ConfigError):
        kinds(out, FILL_GNDPAD_EXCEPTIONS=[('U1', '1')])


def test_an_smd_gnd_pad_with_a_plated_hole_in_it_or_tied_shortly_to_one_that_has_is_not_outside_the_pour():
    def ep(tie, hole=True, gap=0.3):
        a = board(rect(0, 0, 5, 20)).part('U1', 10, 10)
        a.p('U1', '1', 10, 10, 'GND', smd=True, size=0.5)                                   # a pin
        a.p('U1', '2', 10.6 + gap, 10, 'GND', smd=True, size=1.0)                           # the exposed pad, `gap` from the pin's edge
        if hole:
            a.p('U1', '2', 10.6 + gap, 10, 'GND', smd=False, size=0.4, mask=3)              # its plated hole
        if tie:
            a.s('GND', 0, 10, 10, 10.6 + gap, 10, 0.2)
        return a
    assert 'gndpad' not in [k for k in kinds(ep(True))]                                    # the pin is tied to the holed pad, the pad has its hole
    assert 'gndpad' in kinds(ep(False))                                                    # not tied: the pin is outside the pour
    assert 'gndpad' in kinds(ep(True, hole=False))                                         # tied, but the pad has no hole
    assert 'gndpad' in kinds(ep(True, gap=1.5))                                            # a tie longer than FILL_GNDPAD_TIE
    assert 'gndpad' not in kinds(ep(True, gap=1.5), FILL_GNDPAD_TIE=2.0)
    near = _pins(rect(0, 0, 5, 20), [('U1', 10, 10, True)]).v('GND', 10, 11.05)               # annulus 0.25 from the pad edge
    assert 'gndpad' in kinds(near) and 'gndpad' not in kinds(near, FILL_GNDPAD_VIA_GAP=0.3)


def test_a_through_hole_pin_of_another_net_is_not_a_shell():
    a = board(rect(0, 0, 5, 20)).part('J1', 30, 30).p('J1', '1', 10, 10, 'SIG', smd=False, size=1.0, mask=3)
    assert 'shell' not in kinds(a, FILL_SHELL_PREFIXES=('J',))


def _stub(pour, via_xy=(10.74, 9.26)):
    a = _pins(pour, [('U1', 10, 10, True)]).v('GND', *via_xy)
    return a.s('GND', 0, 10, 10, 10, via_xy[1], 0.2).s('GND', 0, 10, via_xy[1], via_xy[0], via_xy[1], 0.2)           # down 0.74 mm, then across to the via


def test_a_bare_track_from_a_pad_to_a_via_a_hair_off_its_corner_is_a_stub_and_one_under_the_pour_is_not():
    out = _stub(rect(0, 0, 5, 20))                                                                  # the via is 0.04 mm from the pad's box: 'at the edge' by distance, with 0.7 mm of visible track
    assert 'gndpad' in kinds(out)
    assert 'gndpad' not in kinds(out, FILL_GNDPAD_STUB=1.0)                                         # the length is the limit
    hidden = _stub(rect(0, 0, 20, 20))                                                              # the same copper under a pour
    assert 'gndpad' not in kinds(hidden)
    touching = _pins(rect(0, 0, 5, 20), [('U1', 10, 10, True)]).v('GND', 10, 10.8)
    assert 'gndpad' not in kinds(touching)                                                          # a via at the edge, no track at all


def test_a_via_on_the_way_ends_the_stub_and_a_through_hole_in_the_pad_has_none():
    a = _stub(rect(0, 0, 5, 20))
    a.s('GND', 0, 10.74, 9.26, 14.0, 9.26, 0.2)                                                      # a bar that goes on past the via: not the pad's stub
    assert 'gndpad' in kinds(a) and len([1 for k in kinds(a) if k == 'gndpad']) == 1
    long_bar = _pins(rect(0, 0, 5, 20), [('U1', 10, 10, True)]).v('GND', 10, 10.8).s('GND', 0, 10, 10, 10, 13.0, 0.2)
    assert 'gndpad' not in kinds(long_bar)                                                          # the via is at the edge and the bar beyond it is somebody else's track


def test_a_tie_to_a_holed_pad_of_another_part_is_not_the_exposed_pad_case():
    a = board(rect(0, 0, 5, 20)).part('U1', 10, 10).part('U2', 11, 10)
    a.p('U1', '1', 10, 10, 'GND', smd=True, size=0.5)
    a.p('U2', '1', 10.9, 10, 'GND', smd=True, size=1.0).p('U2', '1', 10.9, 10, 'GND', smd=False, size=0.4, mask=3)       # a holed pad, but of the neighbouring part
    a.s('GND', 0, 10, 10, 10.9, 10, 0.2)
    assert 'gndpad' in kinds(a)


BITE = [(0, 0), (20, 0), (20, 10), (10.5, 10), (10.5, 6), (9.5, 6), (9.5, 10), (0, 10)]                  # a 1.0 mm wide, 4 mm deep slot into the top of the pour


def test_a_bare_inlet_no_wider_than_the_minimum_is_a_notch_unless_a_clearance_ring_or_nothing_asks_for_it():
    assert 'notch' in kinds(board(BITE), FILL_NOTCH_WIDTH=1.05)
    assert 'notch' not in kinds(board(BITE))                                                         # not asked for
    assert 'notch' not in kinds(board(BITE), FILL_NOTCH_WIDTH=0.9)                                    # wider than the limit
    wide = [(0, 0), (20, 0), (20, 10), (11, 10), (11, 6), (9, 6), (9, 6.0), (9, 10), (0, 10)]
    assert 'notch' not in kinds(board(wide), FILL_NOTCH_WIDTH=1.05)                                   # 2.0 mm wide: a bay, not an inlet
    short = [(0, 0), (20, 0), (20, 10), (10.5, 10), (10.5, 9.9), (9.5, 9.9), (9.5, 10), (0, 10)]
    assert 'notch' not in kinds(board(short), FILL_NOTCH_WIDTH=1.05)                                  # 0.1 mm deep: under the area floor
    ring = board(BITE).part('U1', 0, 0).p('U1', '1', 10, 7.0, 'SIG', size=0.9, mask=1)               # another net's pad in the slot: its clearance ring is the gap
    assert 'notch' in kinds(ring, FILL_NOTCH_WIDTH=1.05)                                              # the far end of the slot is still bare
    full = [(0, 0), (20, 0), (20, 10), (10.5, 10), (10.5, 8.6), (9.5, 8.6), (9.5, 10), (0, 10)]
    ex = board(full).part('U1', 0, 0).p('U1', '1', 10, 9.5, 'SIG', size=0.9, mask=1)
    assert 'notch' not in kinds(ex, FILL_NOTCH_WIDTH=1.05)                                            # a pad filling a short slot: nothing bare is left


def test_the_notch_count_is_a_figure_and_a_verdict():
    r = rules.fill_quality(board(BITE).build(), dict(GND='GND', FILL_LAYERS=('F',), FILL_NOTCH_WIDTH=1.05))
    assert not r.ok and r.figures['notch'] == 1.0 and 'inlet' in r.detail
