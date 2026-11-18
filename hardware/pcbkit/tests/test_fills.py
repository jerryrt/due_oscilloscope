"""pcbkit.fills on boards built from numbers: the strips and fingers of a pour that are narrower than a width, which are only thin by being too narrow. Every limit is broken on
purpose by mutate_fills.sh."""
import pytest

from arrays import Arr, rect
from pcbkit import fills

BIG = [(0, 0), (10, 0), (10, 4.85), (12, 4.85), (12, 0), (22, 0), (22, 10), (12, 10), (12, 5.15), (10, 5.15), (10, 10), (0, 10)]     # two 10 mm squares joined by a 2 mm long, 0.3 mm wide strip
FINGER = [(0, 0), (10, 0), (10, 4.85), (12, 4.85), (12, 5.15), (10, 5.15), (10, 10), (0, 10)]                                      # one square with a 2 mm long, 0.3 mm wide finger


def raster(ring, extra=None, **kw):
    a = Arr('GND', 'SIG').z('GND', 0, [(False, ring)])
    if extra:
        extra(a)
    b = a.build()
    return b, fills.net_copper(b, 0, b.nets.index('GND'), **kw)


def test_a_strip_narrower_than_the_width_is_found_with_its_width_and_place():
    _, r = raster(BIG)
    ps, _ = fills.narrow_pieces(r, 0.5)
    assert len(ps) == 1
    p = ps[0]
    assert 0.25 < p.width < 0.4 and 1.9 < p.length < 2.2 and abs(p.x - 11) < 0.2 and abs(p.y - 5) < 0.2


def test_a_strip_as_wide_as_the_width_is_not_found_and_the_width_is_the_limit():
    _, r = raster(BIG)
    assert fills.narrow_pieces(r, 0.28)[0] == []                    # the strip is 0.3 mm: a disc of 0.28 fits
    assert len(fills.narrow_pieces(r, 0.5)[0]) == 1
    wide = [(x, y if abs(y - 4.85) > 1e-9 else 4.5) for x, y in BIG]
    wide = [(x, 5.5 if abs(y - 5.15) < 1e-9 else y) for x, y in wide]
    _, r2 = raster(wide)                                            # the strip now 1.0 mm wide
    assert fills.narrow_pieces(r2, 0.5)[0] == []


def test_the_corner_of_a_wide_region_is_not_a_sliver():
    _, r = raster(rect(0, 0, 10, 10))
    assert fills.narrow_pieces(r, 0.5)[0] == [] and fills.sliver_count(r, 0.5) == (0, 0.0)


def test_a_hole_in_the_pour_is_cleared_and_its_ring_does_not_count_as_copper():
    a = Arr('GND').z('GND', 0, [(False, rect(0, 0, 10, 10)), (True, rect(4, 0.0, 6, 10))])        # a hole cutting the pour in two
    b = a.build()
    r = fills.net_copper(b, 0, 1)
    assert r.mask[int(5 * 40), int(5 * 40)] == False and r.mask[int(5 * 40), int(2 * 40)] == True


def test_the_minimum_area_ignores_a_speck():
    _, r = raster(BIG)
    assert len(fills.narrow_pieces(r, 0.5, min_area=0.02)[0]) == 1
    assert fills.narrow_pieces(r, 0.5, min_area=5.0)[0] == []


def test_a_strip_between_two_regions_is_not_a_dead_end_and_a_finger_is():
    _, r = raster(BIG)
    ps = fills.thin_report(r, 0.2, 0.5)
    assert len(ps) == 1 and ps[0].touches == 2 and not ps[0].dead_end
    _, r = raster(FINGER)
    ps = fills.thin_report(r, 0.2, 0.5)
    assert len(ps) == 1 and ps[0].touches == 1 and ps[0].dead_end


def test_a_finger_that_ends_on_a_pad_or_via_of_the_net_is_not_a_dead_end():
    for add in (lambda a: a.v('GND', 11.8, 5.0), lambda a: a.v('GND', 11.8, 5.0, dia=0.4, drill=0.2), lambda a: a.part('C1', 11.8, 5.0).p('C1', '1', 11.8, 5.0, 'GND', size=0.4),
                lambda a: a.part('C1', 11.8, 5.0).p('C1', '1', 11.8, 5.0, 'GND', size=0.6)):       # an item narrower than the band, and one wider: both are a second end
        _, r = raster(FINGER, add)
        ps = fills.thin_report(r, 0.2, 0.5)
        assert len(ps) == 1 and not ps[0].dead_end, ps
    _, r = raster(FINGER, lambda a: a.v('SIG', 11.8, 5.0))                  # another net's via is no anchor
    assert fills.thin_report(r, 0.2, 0.5)[0].dead_end


def test_the_width_band_is_half_open_at_the_lower_limit():
    _, r = raster(BIG)
    assert len(fills.thin_report(r, 0.2, 0.5)) == 1 and fills.thin_report(r, 0.4, 0.5) == []      # the strip's own width is 0.3: below `lo` it is out


def test_covered_items_says_which_pads_and_vias_have_the_pour_under_them():
    a = Arr('GND', 'SIG').z('GND', 0, [(False, rect(0, 0, 10, 10))]).part('C1', 5, 5).p('C1', '1', 5, 5, 'GND').p('C1', '2', 15, 5, 'GND').p('C1', '3', 10.3, 5, 'GND').v('GND', 2, 2).v('GND', 20, 20)
    b = a.build()
    g = b.nets.index('GND')
    r = fills.net_copper(b, 0, g, with_net_items=False)
    got = fills.covered_items(b, r, 0, g)
    assert got == {('pad', 0): True, ('pad', 1): False, ('pad', 2): False, ('via', 0): True, ('via', 1): False}      # pad 2 straddles the edge: 0.1 of it is under the pour


def test_no_filled_zone_of_the_net_is_an_error():
    a = Arr('GND').z('GND', 0, [(False, rect(0, 0, 10, 10))], filled=False)
    with pytest.raises(ValueError):
        fills.net_copper(a.build(), 0, 1)
    with pytest.raises(ValueError):
        fills.net_copper(Arr('GND').z('GND', 0, [(False, rect(0, 0, 10, 10))]).build(), 1, 1)       # the other layer


def test_another_nets_track_or_pad_is_not_an_anchor_of_the_pour():
    _, r = raster(FINGER, lambda a: a.s('SIG', 0, 11.5, 4.0, 11.9, 6.0))
    assert fills.thin_report(r, 0.2, 0.5)[0].dead_end                                  # the SIG track beside the finger tip is not copper of this net
    a = Arr('GND', 'SIG').z('GND', 0, [(False, FINGER)]).part('C1', 11.8, 5.0).p('C1', '1', 11.8, 5.0, 'SIG', size=0.6)
    b = a.build()
    assert fills.thin_report(fills.net_copper(b, 0, b.nets.index('GND')), 0.2, 0.5)[0].dead_end


# ---- keepouts: straight-edged no-pour rectangles over the places a fill cannot stay wide

def test_keepouts_cover_the_narrow_strip_on_the_grid_and_leave_the_squares():
    _, r = raster([(x + 0.13, y + 0.21) for x, y in BIG], ppmm=20)               # off the grid, so the snapping has work to do
    ks = fills.keepouts(r, width=1.0, grid=0.5, join=0.0)
    assert len(ks) >= 1
    assert all(abs(v / 0.5 - round(v / 0.5)) < 1e-6 for k in ks for v in k)                  # every edge on the 0.5 mm grid
    assert any(k[0] <= 10.63 and k[2] >= 11.63 and k[1] <= 5.2 <= k[3] for k in ks)             # the strip is inside one
    assert all(k[2] - k[0] < 6 for k in ks)                                                   # the 10 mm squares are not


def test_keepouts_of_a_pour_with_no_narrow_part_are_none():
    _, r = raster(rect(0, 0, 10, 10), ppmm=20)
    assert fills.keepouts(r, width=1.0) == []


def test_keepouts_edges_move_onto_a_near_block_outline_edge_and_not_a_far_one():
    _, r = raster(BIG, ppmm=20)
    near = fills.keepouts(r, 1.0, 0.5, 0.0, outlines=[(10.2, -1.0, 11.8, 11.0)], snap=1.0)
    assert any(abs(k[0] - 10.2) < 1e-6 and abs(k[2] - 11.8) < 1e-6 for k in near)
    far = fills.keepouts(r, 1.0, 0.5, 0.0, outlines=[(6.1, -1.0, 15.7, 11.0)], snap=1.0)
    assert not any(abs(k[0] - 6.1) < 1e-6 for k in far)


def test_keepouts_are_clipped_to_the_bounds():
    _, r = raster(BIG, ppmm=20)
    ks = fills.keepouts(r, 1.0, 0.5, 0.0, bounds=(0, 0, 11.0, 10))
    assert ks and all(k[2] <= 11.0 + 1e-9 for k in ks)


def test_a_diagonal_run_of_pieces_is_a_staircase_and_not_one_bounding_box():
    import numpy as np
    _, r = raster(rect(0, 0, 40, 40), ppmm=20)
    extra = np.zeros_like(r.mask)
    for i in range(0, 700, 2):                                                                  # a 1 px thick diagonal across the pour
        extra[i:i + 20, i:i + 20] = True
    ks = fills.keepouts(r, 1.0, 0.5, 0.0, extra=extra)
    assert len(ks) > 3 and max((k[2] - k[0]) * (k[3] - k[1]) for k in ks) < 0.2 * 35 * 35


def test_leftovers_find_a_blob_on_a_neck_and_a_dead_end_finger_and_not_a_big_pour():
    _, r = raster(BIG, ppmm=20)
    assert not fills.leftovers(r, neck=0.2, small=1.0).any()                                    # nothing small hangs by a neck under 0.2 mm
    BLOB = [(0, 0), (20, 0), (20, 20), (0, 20), (0, 10.6), (-2, 10.6), (-2, 11.5), (-5, 11.5), (-5, 8.5), (-2, 8.5), (-2, 9.4), (0, 9.4)]       # a 20 mm square, a 1.2 mm neck, a 3 x 3 blob
    _, rb = raster(BLOB, ppmm=20)
    lo = fills.leftovers(rb, neck=1.5, small=12.0)
    assert lo.sum() > 0 and lo[:, :200].any() and not lo[:, 300:].any()                         # the blob and its neck, none of the square
    assert not fills.leftovers(rb, neck=1.5, small=5.0, dead_width=0.5).any()                  # a blob of 9 mm2 is not small under 5 mm2


# ---- keepout_polygons: one octilinear polygon per cluster

def _octi(poly):
    n = len(poly)
    for i in range(n):
        dx, dy = poly[(i + 1) % n][0] - poly[i][0], poly[(i + 1) % n][1] - poly[i][1]
        if not (abs(dx) < 1e-6 or abs(dy) < 1e-6 or abs(abs(dx) - abs(dy)) < 1e-6):
            return False
    return True


def _diag_extra(r, steps=60, size=10):
    import numpy as np
    e = np.zeros_like(r.mask)
    for i in range(steps):
        e[i * size // 2:i * size // 2 + size, i * size // 2:i * size // 2 + size] = True
    return e


def test_a_diagonal_cluster_is_one_polygon_with_45_degree_edges():
    _, r = raster(rect(0, 0, 40, 40), ppmm=20)
    ps = fills.keepout_polygons(r, 1.0, 0.5, 0.0, extra=_diag_extra(r))
    assert len(ps) == 1 and len(ps[0]) <= 8 and _octi(ps[0])
    assert any(abs(abs(ps[0][(i + 1) % len(ps[0])][0] - ps[0][i][0]) - abs(ps[0][(i + 1) % len(ps[0])][1] - ps[0][i][1])) < 1e-6 and abs(ps[0][(i + 1) % len(ps[0])][0] - ps[0][i][0]) > 5 for i in range(len(ps[0])))


def test_polygon_vertices_are_on_the_grid_and_the_pieces_are_inside_the_polygon():
    _, r = raster([(x + 0.13, y + 0.21) for x, y in BIG], ppmm=20)
    ps = fills.keepout_polygons(r, 1.0, 0.5, 0.0)
    assert ps and all(abs(v / 0.5 - round(v / 0.5)) < 1e-6 for p in ps for q in p for v in q)
    assert any(min(x for x, _ in p) <= 10.9 and max(x for x, _ in p) >= 11.2 for p in ps)


def test_a_cluster_around_pour_is_cut_into_rectangles_not_one_polygon_covering_it():
    import numpy as np
    _, r = raster(rect(0, 0, 40, 40), ppmm=20)
    e = np.zeros_like(r.mask)
    e[100:500, 100:140] = e[100:500, 460:500] = e[100:140, 100:500] = e[460:500, 100:500] = True      # a square ring of cells, a 20 x 20 mm hole inside
    ps = fills.keepout_polygons(r, 1.0, 0.5, 0.0, extra=e, hole_area=4.0)
    assert len(ps) >= 4 and all(len(p) == 4 for p in ps)


def test_polygon_snap_to_outline_moves_straight_edges_and_never_bends_a_diagonal():
    import numpy as np
    _, r = raster(rect(0, 0, 40, 40), ppmm=20)
    box = np.zeros_like(r.mask)
    box[300:400, 200:300] = True                                                                 # a block of pieces, x 9..14, y 21..26
    free = fills.keepout_polygons(r, 1.0, 0.5, 0.0, extra=box)[0]
    snapped = fills.keepout_polygons(r, 1.0, 0.5, 0.0, extra=box, outlines=[(8.7, 20.6, 14.4, 26.3)], snap=1.0)[0]
    assert snapped != free and {round(x, 3) for x, _ in snapped} == {8.7, 14.4} and {round(y, 3) for _, y in snapped} == {20.6, 26.3}
    e = _diag_extra(r)
    d_free = fills.keepout_polygons(r, 1.0, 0.5, 0.0, extra=e)[0]
    d_snap = fills.keepout_polygons(r, 1.0, 0.5, 0.0, extra=e, outlines=[(0.3, 0.3, 39.8, 39.8)], snap=1.0)[0]
    assert _octi(d_snap) and d_snap == d_free


def test_polygon_covers_its_pieces_when_the_raster_is_off_the_grid():
    import numpy as np
    _, r = raster([(x + 0.37, y + 0.29) for x, y in rect(0, 0, 40, 40)], ppmm=20)
    box = np.zeros_like(r.mask)
    box[300:400, 200:300] = True                                                                 # pixel columns 200..300 are x = r.x0 + 10 .. r.x0 + 15
    p = fills.keepout_polygons(r, 1.0, 0.5, 0.0, extra=box)[0]
    x0, x1 = r.x0 + 10.0, r.x0 + 15.0
    y1, y0 = r.y1 - 15.0, r.y1 - 20.0
    assert min(x for x, _ in p) <= x0 + 1e-6 and max(x for x, _ in p) >= x1 - 1e-6 and min(y for _, y in p) <= y0 + 1e-6 and max(y for _, y in p) >= y1 - 1e-6


# ---- rough_edges: a pour edge that is a run of clearance arcs

def _hugged(ys, x=20.9):
    a = Arr('GND', 'SIG').z('GND', 0, [(False, rect(0, 0, 20, 20))])
    a.part('U1', 30, 30)
    for n, y in enumerate(ys):
        a.p('U1', str(n + 1), x, y, 'SIG', size=1.0)
    b = a.build()
    return b, fills.net_copper(b, 0, b.nets.index("GND"), ppmm=20, with_net_items=False, frame=(-2, -2, 30, 30))


def test_a_run_of_pads_along_the_pour_edge_is_rough_and_a_single_pad_is_not():
    b, rp = _hugged([5, 7, 9])
    m = fills.rough_edges(b, rp, 0, b.nets.index('GND'), clearance=0.3)
    r, c = int((rp.y1 - 7) * 20), int((20 - rp.x0) * 20)
    assert m[r, c] and not m[int((rp.y1 - 16) * 20), c]
    b1, rp1 = _hugged([7])
    assert not fills.rough_edges(b1, rp1, 0, b1.nets.index('GND'), clearance=0.3).any()


def test_pads_that_do_not_touch_the_pour_or_are_far_apart_are_not_a_run():
    b, rp = _hugged([5, 7, 9], x=24.0)
    assert not fills.rough_edges(b, rp, 0, b.nets.index('GND'), clearance=0.3).any()        # 3 mm from the pour: not hugging
    b, rp = _hugged([3, 9, 15])
    assert not fills.rough_edges(b, rp, 0, b.nets.index('GND'), clearance=0.3).any()        # 5 mm apart: three single pads
    b, rp = _hugged([3, 9, 15])
    assert fills.rough_edges(b, rp, 0, b.nets.index('GND'), clearance=0.3, link=6.0).any()  # the link distance is the limit


def _own_vias(pts):
    a = Arr('GND', 'SIG').z('GND', 0, [(False, rect(0, 0, 20, 20))])
    for x, y in pts:
        a.v('GND', x, y)
    b = a.build()
    return b, fills.net_copper(b, 0, b.nets.index('GND'), ppmm=20, with_net_items=False, frame=(-2, -2, 30, 30))


def test_a_row_of_the_nets_own_vias_standing_at_the_pour_edge_is_rough_and_one_or_buried_ones_are_not():
    g = lambda pts: fills.rough_edges(*_own_vias(pts)[:1], _own_vias(pts)[1], 0, 1, clearance=0.3)
    assert g([(20.0, 5), (20.0, 7), (20.0, 9)]).any()                      # three vias half out of the pour
    assert not g([(20.0, 7)]).any()                                         # one alone may show its arc
    assert not g([(10.0, 5), (10.0, 7), (10.0, 9)]).any()                   # buried in the pour: the edge is not theirs
    assert not g([(26.0, 5), (26.0, 7), (26.0, 9)]).any()                   # away from the pour altogether


def _thermal_pads(xs, ys):
    """a 20 mm pour with a hole round each own-net pad (its thermal gap: no pour within 0.45 mm of the pad), the pads at the given places"""
    a = Arr('GND', 'SIG').z('GND', 0, [(False, rect(0, 0, 20, 20))] + [(True, rect(x - 0.7, y - 0.7, x + 0.7, y + 0.7)) for x, y in zip(xs, ys)])
    a.part('U1', 30, 30)
    for n, (x, y) in enumerate(zip(xs, ys)):
        a.p('U1', str(n + 1), x, y, 'GND', size=1.0)
    b = a.build()
    return b, fills.net_copper(b, 0, b.nets.index('GND'), ppmm=20, with_net_items=False, frame=(-2, -2, 30, 30))


def test_own_pads_with_a_thermal_gap_at_the_pour_edge_are_rough_and_buried_ones_are_not():
    run = lambda xs, ys: fills.rough_edges(*_thermal_pads(xs, ys)[:1], _thermal_pads(xs, ys)[1], 0, 1, clearance=0.3)
    assert run([19.5, 19.5, 19.5], [5, 7.2, 9.4]).any()                    # three pads whose gaps open to the edge
    assert not run([19.5], [5]).any()                                       # one alone
    assert not run([10, 10, 10], [5, 7.2, 9.4]).any()                       # buried: pour all round their gaps


# ---- protected cells: a connector's ground pins are never part of a keep-out

def test_protected_cells_are_never_in_a_keep_out_and_a_diagonal_does_not_cover_them():
    import numpy as np
    _, r = raster(rect(0, 0, 40, 40), ppmm=20)
    e = _diag_extra(r)
    free = fills.keepout_polygons(r, 1.0, 0.5, 0.0, extra=e)
    assert len(free) == 1
    prot = np.zeros_like(r.mask)
    k = 20
    prot[int((r.y1 - 35.0) * k):int((r.y1 - 33.0) * k), int((5.0 - r.x0) * k):int((7.0 - r.x0) * k)] = True        # a 2 mm square on the diagonal (the band runs from (-1, 41) to (14, 26))
    got = fills.keepout_polygons(r, 1.0, 0.5, 0.0, extra=e, protect=prot)
    def covers(polys, x, y):
        def inside(poly):
            c = False
            for (x0, y0), (x1, y1) in zip(poly, poly[1:] + poly[:1]):
                if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
                    c = not c
            return c
        return any(inside(p) for p in polys)
    assert covers(free, 6.0, 34.0) and not covers(got, 6.0, 34.0)
    assert not covers(got, 5.2, 34.8) and not covers(got, 6.8, 33.2)


def test_pin_protect_marks_the_box_of_a_through_hole_ground_pad_of_a_listed_part_only():
    a = Arr('GND', 'SIG').z('GND', 0, [(False, rect(0, 0, 40, 40))]).part('J1', 30, 30).part('U1', 30, 30)
    a.p('J1', '1', 10, 10, 'GND', smd=False, size=1.0, mask=3).p('J1', '2', 20, 10, 'SIG', smd=False, size=1.0, mask=3).p('J1', '3', 30, 10, 'GND', smd=True, size=1.0)
    a.p('U1', '1', 10, 30, 'GND', smd=False, size=1.0, mask=3)
    b = a.build()
    r = fills.net_copper(b, 0, b.nets.index('GND'), ppmm=10, with_net_items=False)
    m = fills.pin_protect(b, r, b.nets.index('GND'), ('J',), reach=1.0)
    px = lambda x, y: m[int((r.y1 - y) * 10), int((x - r.x0) * 10)]
    assert px(10, 10) and px(10.9, 10) and not px(12.0, 10)                                      # the pad's box grown by `reach`
    assert not px(20, 10) and not px(30, 10) and not px(10, 30)                                   # another net, an SMD pad, a part not listed
