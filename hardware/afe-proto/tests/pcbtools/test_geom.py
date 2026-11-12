"""Kernel tests: each pcbtools.geom kernel against a slow scalar reference written here (a different formulation
from the kernel), on random cases, on integer-grid cases that are full of degenerate configurations (zero-length,
parallel, collinear, touching, crossing), and on known answers. No pcbnew."""
import math
import numpy as np
import pytest
from pcbtools import geom

RNG = np.random.default_rng(20261112)


# ----------------------------------------------------------------------------- slow references
def ref_pt_seg(p, s):
    (px, py), (x0, y0, x1, y1) = p, s
    dx, dy = x1 - x0, y1 - y0
    l2 = dx * dx + dy * dy
    t = 0.0 if l2 == 0 else max(0.0, min(1.0, ((px - x0) * dx + (py - y0) * dy) / l2))
    return math.hypot(px - (x0 + t * dx), py - (y0 + t * dy))


def ref_seg_seg(a, b):
    """Ericson, Real-Time Collision Detection 5.1.9 (closest points of two segments): a different route from the kernel"""
    p1, q1, p2, q2 = (a[0], a[1]), (a[2], a[3]), (b[0], b[1]), (b[2], b[3])
    d1 = (q1[0] - p1[0], q1[1] - p1[1]); d2 = (q2[0] - p2[0], q2[1] - p2[1]); r = (p1[0] - p2[0], p1[1] - p2[1])
    dot = lambda u, v: u[0] * v[0] + u[1] * v[1]
    A, E, F = dot(d1, d1), dot(d2, d2), dot(d2, r)
    eps = 1e-18
    if A <= eps and E <= eps:
        return math.dist(p1, p2)
    if A <= eps:
        s, t = 0.0, max(0.0, min(1.0, F / E))
    else:
        c = dot(d1, r)
        if E <= eps:
            t, s = 0.0, max(0.0, min(1.0, -c / A))
        else:
            bb = dot(d1, d2)
            den = A * E - bb * bb
            s = max(0.0, min(1.0, (bb * F - c * E) / den)) if den > eps else 0.0
            t = (bb * s + F) / E
            if t < 0:
                t, s = 0.0, max(0.0, min(1.0, -c / A))
            elif t > 1:
                t, s = 1.0, max(0.0, min(1.0, (bb - c) / A))
    c1 = (p1[0] + d1[0] * s, p1[1] + d1[1] * s)
    c2 = (p2[0] + d2[0] * t, p2[1] + d2[1] * t)
    return math.dist(c1, c2)


def ref_seg_in_box(s, box, pad):
    """sample the segment densely plus the exact endpoints: a different (approximate) method; used with a margin"""
    x0, y0, x1, y1 = s
    for k in range(0, 2001):
        t = k / 2000
        x, y = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
        if box[0] - pad <= x <= box[2] + pad and box[1] - pad <= y <= box[3] + pad:
            return True
    return False


def ref_pip(pt, poly):
    """winding number (not the even-odd crossing count the kernel uses)"""
    wn = 0
    n = len(poly)
    for i in range(n):
        ax, ay = poly[i]; bx, by = poly[(i + 1) % n]
        isl = (bx - ax) * (pt[1] - ay) - (pt[0] - ax) * (by - ay)
        if ay <= pt[1] < by and isl > 0:
            wn += 1
        elif by <= pt[1] < ay and isl < 0:
            wn -= 1
    return wn != 0


def ref_components(n, joins):
    lab = list(range(n))
    changed = True
    for _ in range(n + 1):
        if not changed:
            break
        changed = False
        for a, b in joins:
            m = min(lab[a], lab[b])
            if lab[a] != m or lab[b] != m:
                lab[a] = lab[b] = m
                changed = True
    seen = {}
    return [seen.setdefault(v, len(seen)) for v in lab]


# ----------------------------------------------------------------------------- segment - segment
KNOWN = [  # (a, b, distance, why)
    ((0, 0, 4, 0), (2, -1, 2, 1), 0.0, 'proper crossing'),
    ((0, 0, 4, 0), (4, 0, 8, 3), 0.0, 'touching at endpoints'),
    ((0, 0, 4, 0), (2, 0, 2, 5), 0.0, 'T touch'),
    ((0, 0, 4, 0), (0, 1, 4, 1), 1.0, 'parallel'),
    ((0, 0, 4, 0), (6, 0, 9, 0), 2.0, 'collinear, disjoint'),
    ((0, 0, 4, 0), (2, 0, 9, 0), 0.0, 'collinear, overlapping'),
    ((1, 1, 1, 1), (4, 5, 4, 5), 5.0, 'two points'),
    ((1, 1, 1, 1), (0, 0, 4, 0), 1.0, 'point against segment interior'),
    ((1, 1, 1, 1), (1, 1, 1, 1), 0.0, 'identical points'),
]


def test_known_answers():
    for a, b, d, why in KNOWN:
        got = geom.seg_seg_dist(np.array([a], float), np.array([b], float))[0, 0]
        assert got == pytest.approx(d, abs=1e-12), why
        # symmetric
        got2 = geom.seg_seg_dist(np.array([b], float), np.array([a], float))[0, 0]
        assert got2 == pytest.approx(d, abs=1e-12), why + ' (swapped)'
    # a diagonal pair with a hand-worked answer: (0,0)-(1,1) and (3,0)-(4,1): closest ends (1,1)-(3,0)? no: (1,1)->(3,0) is
    # sqrt(5); (0,0) to the other's start (3,0) is 3; (1,1) to segment (3,0)-(4,1) nearest point is (3,0): sqrt(5)
    got = geom.seg_seg_dist(np.array([[0, 0, 1, 1]], float), np.array([[3, 0, 4, 1]], float))[0, 0]
    assert got == pytest.approx(math.sqrt(5), abs=1e-12)


def test_seg_seg_random_and_grid():
    for lo, hi, integer in ((-10, 10, False), (0, 5, True), (0, 3, True)):
        A = RNG.uniform(lo, hi, (60, 4))
        B = RNG.uniform(lo, hi, (50, 4))
        if integer:
            A, B = np.round(A), np.round(B)
        got = geom.seg_seg_dist(A, B)
        want = np.array([[ref_seg_seg(a, b) for b in B] for a in A])
        assert np.abs(got - want).max() < 1e-9, (lo, hi)
        assert (got >= 0).all()


def test_seg_seg_chunking_is_exact(monkeypatch):
    A = RNG.uniform(0, 10, (37, 4)); B = RNG.uniform(0, 10, (29, 4))
    full = geom.seg_seg_dist(A, B)
    monkeypatch.setattr(geom, 'BLOCK_PAIRS', 7)            # force ragged tiles in both directions
    assert np.array_equal(geom.seg_seg_dist(A, B), full)
    assert np.array_equal(geom.min_dist(A, B), full.min(axis=1))
    i, j = geom.within(A, B, 1.5)
    ri, rj = np.nonzero(full < 1.5)
    assert np.array_equal(i, ri) and np.array_equal(j, rj)


def test_matrix_guard():
    with pytest.raises(MemoryError, match='use within'):         # the guard's own message, not numpy's allocation failure
        geom.seg_seg_dist(np.zeros((20000, 4)), np.zeros((20000, 4)))


def test_min_dist_and_empty():
    A = RNG.uniform(0, 10, (40, 4)); B = RNG.uniform(0, 10, (30, 4))
    want = np.array([min(ref_seg_seg(a, b) for b in B) for a in A])
    assert np.abs(geom.min_dist(A, B) - want).max() < 1e-9
    assert np.isinf(geom.min_dist(A, np.zeros((0, 4)))).all()
    assert geom.min_dist(np.zeros((0, 4)), B).shape == (0,)
    assert geom.seg_seg_dist(np.zeros((0, 4)), B).shape == (0, 30)


def test_within():
    for hi, integer in ((20.0, False), (6.0, True)):
        A = RNG.uniform(0, hi, (150, 4)); B = RNG.uniform(0, hi, (120, 4))
        if integer:
            A, B = np.round(A), np.round(B)
        for d in (0.5, 2.0):
            i, j, dd = geom.within(A, B, d, return_dist=True)
            want = np.array([[ref_seg_seg(a, b) for b in B] for a in A])
            ri, rj = np.nonzero(want < d - 1e-12)
            got = set(zip(i.tolist(), j.tolist()))
            exact = set(zip(ri.tolist(), rj.tolist()))
            # a pair at distance within 1e-9 of d may land either side; everything else must match exactly
            edge = {(a, b) for a, b in zip(*np.nonzero(np.abs(want - d) < 1e-9))}
            assert got - edge == exact - edge, (hi, d)
            assert np.allclose(dd, want[i, j], atol=1e-9)
            assert (np.diff(i) >= 0).all()
    assert geom.within(A, B, 0.0)[0].size == 0
    assert geom.within(np.zeros((0, 4)), B, 1.0)[0].size == 0


def test_within_prunes_by_x_and_y_not_only_x():
    # B far away in y but overlapping in x: must not be returned; B just inside d in y must be
    A = np.array([[0, 0, 10, 0]], float)
    B = np.array([[0, 100, 10, 100], [0, 0.4, 10, 0.4], [0, 0.6, 10, 0.6], [20, 0, 30, 0]], float)
    i, j = geom.within(A, B, 0.5)
    assert j.tolist() == [1]


# ----------------------------------------------------------------------------- point - segment
def test_point_seg():
    for integer in (False, True):
        P = RNG.uniform(-3, 8, (40, 2)); S = RNG.uniform(-3, 8, (30, 4))
        if integer:
            P, S = np.round(P), np.round(S)
        got = geom.point_seg_dist(P, S)
        want = np.array([[ref_pt_seg(p, s) for s in S] for p in P])
        assert np.abs(got - want).max() < 1e-12
    assert geom.point_seg_dist(np.array([[1., 1.]]), np.array([[1., 1., 1., 1.]]))[0, 0] == 0.0     # zero-length, on it
    assert geom.point_seg_dist(np.array([[4., 5.]]), np.array([[1., 1., 1., 1.]]))[0, 0] == 5.0     # zero-length, off it
    assert geom.point_seg_dist(np.array([[9., 3.]]), np.array([[0., 0., 4., 0.]]))[0, 0] == math.hypot(5, 3)   # beyond the end


def test_seg_len():
    assert geom.seg_len(np.array([[0, 0, 3, 4], [1, 1, 1, 1]], float)).tolist() == [5.0, 0.0]


# ----------------------------------------------------------------------------- boxes
def rand_boxes(n, span=10):
    p = RNG.uniform(0, span, (n, 4))
    return np.column_stack([np.minimum(p[:, 0], p[:, 2]), np.minimum(p[:, 1], p[:, 3]), np.maximum(p[:, 0], p[:, 2]), np.maximum(p[:, 1], p[:, 3])])


def test_box_overlap_and_dist():
    A, B = rand_boxes(30), rand_boxes(25)
    for strict in (True, False):
        got = geom.box_overlap(A, B, strict=strict)
        for i, a in enumerate(A):
            for j, b in enumerate(B):
                ox = min(a[2], b[2]) - max(a[0], b[0]); oy = min(a[3], b[3]) - max(a[1], b[1])
                assert got[i, j] == ((ox > 0 and oy > 0) if strict else (ox >= 0 and oy >= 0))
    d = geom.box_dist(A, B)
    for i, a in enumerate(A):
        for j, b in enumerate(B):
            gx = max(a[0] - b[2], b[0] - a[2], 0); gy = max(a[1] - b[3], b[1] - a[3], 0)
            assert d[i, j] == pytest.approx(math.hypot(gx, gy), abs=1e-12)
    # touching edges: no strict overlap, closed overlap, zero distance; corner-to-corner 3-4-5
    a, b = np.array([[0, 0, 1, 1]], float), np.array([[1, 0, 2, 1]], float)
    assert not geom.box_overlap(a, b)[0, 0] and geom.box_overlap(a, b, strict=False)[0, 0] and geom.box_dist(a, b)[0, 0] == 0
    assert geom.box_dist(a, np.array([[4, 5, 6, 7]], float))[0, 0] == pytest.approx(5.0)


def test_seg_in_box():
    S = RNG.uniform(-2, 12, (150, 4)); box = np.array([3., 3., 7., 6.])
    for pad in (0.0, 0.5):
        got = geom.seg_in_box(S, box, pad)
        for k, s in enumerate(S):
            want = ref_seg_in_box(s, box, pad)
            if got[k] != want:       # the sampled reference can only miss a sliver: the exact test then says yes, and
                assert got[k] and not want          # shrinking the box by 0.05 flips it to no (a marginal case)
                assert not geom.seg_in_box(S[k:k + 1], box + np.array([.05, .05, -.05, -.05]), pad)[0]
    # known cases: crossing a box with both ends outside; inside; parallel outside; touching a corner; vertical on an edge
    K = np.array([[0, 5, 10, 5], [4, 4, 5, 5], [0, 0, 10, 0], [0, 2, 3, 3], [3, 0, 3, 9], [3, 9, 3, 9], [5, 4.5, 5, 4.5]], float)
    assert geom.seg_in_box(K, box).tolist() == [True, True, False, True, True, False, True]
    assert geom.seg_in_box(np.array([[0, 2.5, 2.4, 2.5]], float), box, 0.6)[0]          # pad reaches it
    assert not geom.seg_in_box(np.array([[0, 2.5, 2.4, 2.5]], float), box, 0.5)[0]
    assert geom.seg_in_box(np.array([[0, 2.5, 2.4, 2.5]], float), box, np.array([0.6]))[0]
    assert geom.seg_in_box(S, np.array([box, box + 20])).shape == (150, 2)


# ----------------------------------------------------------------------------- polygons
def test_points_in_polys():
    sq = np.array([[0, 0], [4, 0], [4, 4], [0, 4]], float)
    L = np.array([[0, 0], [6, 0], [6, 2], [2, 2], [2, 6], [0, 6]], float)          # concave L
    star = np.array([[math.cos(2 * math.pi * k / 10) * (3 if k % 2 == 0 else 1.2), math.sin(2 * math.pi * k / 10) * (3 if k % 2 == 0 else 1.2)] for k in range(10)])
    P = RNG.uniform(-4, 8, (400, 2)) + 0.0013          # off the lattice: no point on an edge
    got = geom.points_in_polys(P, [sq, L, star])
    for j, poly in enumerate([sq, L, star]):
        want = np.array([ref_pip(p, poly) for p in P])
        assert (got[:, j] == want).all(), j
    assert geom.points_in_polys(np.array([[1., 1.], [5., 5.], [4., 1.], [1., 4.]]), [L]).ravel().tolist() == [True, False, True, True]
    # flat vertex array + offsets, the BoardArrays layout
    flat = np.vstack([sq, L]); off = np.array([0, 4, 10])
    assert (geom.points_in_polys(P, flat, off) == got[:, :2]).all()
    assert geom.points_in_polys(P, []).shape == (400, 0)
    assert not geom.points_in_polys(P, [np.array([[0, 0], [1, 1]], float)]).any()          # degenerate polygon


def test_points_in_polys_holes():
    """ring-with-a-hole fixture: outline 0..10 square, hole 4..6 square, then a second outline 20..24 with no hole"""
    outer = np.array([[0, 0], [10, 0], [10, 10], [0, 10]], float)
    hole = np.array([[4, 4], [6, 4], [6, 6], [4, 6]], float)
    other = np.array([[20, 0], [24, 0], [24, 4], [20, 4]], float)
    P = np.array([[1., 1.], [5., 5.], [12., 5.], [22., 2.], [5., 3.9], [3.9, 5.]])
    got = geom.points_in_polys(P, [outer, hole, other], hole=[0, 1, 0])
    assert got.shape == (6, 2)
    # in the ring, in the hole, outside, in the second outline, just outside the hole (in the ring) twice
    assert got[:, 0].tolist() == [True, False, False, False, True, True]
    assert got[:, 1].tolist() == [False, False, False, True, False, False]
    # the flat BoardArrays layout gives the same
    flat = np.vstack([outer, hole, other]); off = np.array([0, 4, 8, 12])
    assert (geom.points_in_polys(P, flat, off, hole=[0, 1, 0]) == got).all()
    # a hole belongs to the nearest outline BEFORE it, not to the first one: other, outer, hole
    g2 = geom.points_in_polys(P, [other, outer, hole], hole=[0, 0, 1])
    assert g2[:, 0].tolist() == [False, False, False, True, False, False]
    assert g2[:, 1].tolist() == [True, False, False, False, True, True]
    # without the flags a hole is its own polygon: the point in the hole is inside two rings
    assert geom.points_in_polys(P, [outer, hole, other])[1].tolist() == [True, True, False]
    with pytest.raises(ValueError):
        geom.points_in_polys(P, [hole, outer], hole=[1, 0])
    with pytest.raises(ValueError):
        geom.points_in_polys(P, [outer, hole], hole=[0])


# ----------------------------------------------------------------------------- connectivity
def test_connected_components():
    for n, e in ((1, 0), (10, 0), (12, 6), (50, 40), (200, 150)):
        J = RNG.integers(0, n, (e, 2))
        k, lab = geom.connected_components(n, J)
        want = ref_components(n, J.tolist())
        assert lab.tolist() == want and k == max(want) + 1
    k, lab = geom.connected_components(5, [[0, 4], [4, 2]])
    assert lab.tolist() == [0, 1, 0, 2, 0] and k == 3          # first-appearance numbering
    k, lab = geom.connected_components(np.arange(3), np.zeros((0, 2), int))
    assert lab.tolist() == [0, 1, 2]
    k, lab = geom.connected_components(0, [])
    assert k == 0 and len(lab) == 0
    with pytest.raises(ValueError):
        geom.connected_components(3, [[0, 3]])
    k, lab = geom.connected_components(4, [[1, 1], [0, 1], [1, 0]])          # self-join and duplicates
    assert lab.tolist() == [0, 0, 1, 2]


# ----------------------------------------------------------------------------- added: strictness and chunking of the rest
def test_within_is_strictly_less_than_d():
    A = np.array([[0, 0, 4, 0]], float); B = np.array([[0, 2, 4, 2]], float)
    assert geom.within(A, B, 2.0)[0].size == 0                 # exactly d is not "closer than d"
    assert geom.within(A, B, 2.0000001)[0].size == 1


def test_chunking_other_kernels(monkeypatch):
    P = RNG.uniform(-3, 8, (53, 2)); S = RNG.uniform(-3, 8, (31, 4))
    poly = [np.array([[0, 0], [6, 0], [6, 2], [2, 2], [2, 6], [0, 6]], float)]
    p0, q0 = geom.point_seg_dist(P, S), geom.points_in_polys(P, poly)
    monkeypatch.setattr(geom, 'BLOCK_PAIRS', 5)
    assert np.array_equal(geom.point_seg_dist(P, S), p0)
    assert np.array_equal(geom.points_in_polys(P, poly), q0)


def test_within_strict_when_bbox_does_not_decide():
    A = np.array([[0, 0, 0, 0]], float); B = np.array([[3, 4, 3, 4]], float)     # distance exactly 5, bbox gaps 3 and 4
    assert geom.within(A, B, 5.0)[0].size == 0
    assert geom.within(A, B, 5.0001)[0].size == 1
