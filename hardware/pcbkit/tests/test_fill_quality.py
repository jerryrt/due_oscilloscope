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
