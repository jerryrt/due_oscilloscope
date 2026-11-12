"""Vectorised geometry kernels (numpy + scipy only; no pcbnew). Everything works in Due mm, but is unit-free.

Conventions
  segments   float64 array (N, 4): x0, y0, x1, y1 (centre line; widths are the caller's business)
  boxes      float64 array (N, 4): x0, y0, x1, y1 with x0 <= x1, y0 <= y1
  points     float64 array (N, 2)
Memory: every kernel works in blocks of at most BLOCK_PAIRS pair evaluations (about 40 MB of temporaries); the only
thing that grows with the product of the inputs is a returned matrix, and the matrix-returning kernels refuse to
build one larger than MAX_MATRIX_BYTES. For big inputs use `within` (index pairs, bbox-pruned) or `min_dist`
(one number per row of A), which never materialise the matrix.
"""
from __future__ import annotations

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components as _cc

BLOCK_PAIRS = 250_000
MAX_MATRIX_BYTES = 256 * 1024 * 1024


def _segs(S):
    S = np.asarray(S, np.float64)
    if S.ndim != 2 or S.shape[1] != 4:
        raise ValueError(f'segments must be (N, 4), got {S.shape}')
    return S


def _pts(P):
    P = np.asarray(P, np.float64)
    if P.ndim != 2 or P.shape[1] != 2:
        raise ValueError(f'points must be (N, 2), got {P.shape}')
    return P


def _check_matrix(n, m):
    if n * m * 8 > MAX_MATRIX_BYTES:
        raise MemoryError(f'a {n} x {m} float64 matrix is {n * m * 8 / 2**20:.0f} MB (> {MAX_MATRIX_BYTES // 2**20} MB): '
                          'use within() or min_dist(), which do not build it')


def seg_len(S):
    S = _segs(S)
    return np.hypot(S[:, 2] - S[:, 0], S[:, 3] - S[:, 1])


# ------------------------------------------------------------------------------------------------ point - segment
def _pt_seg(px, py, x0, y0, x1, y1):
    """elementwise (broadcasting) distance from points to segments, zero-length segments allowed"""
    dx, dy = x1 - x0, y1 - y0
    l2 = dx * dx + dy * dy
    num = (px - x0) * dx + (py - y0) * dy
    t = np.divide(num, l2, out=np.zeros(np.broadcast(num, l2).shape), where=l2 > 0)
    t = np.clip(t, 0.0, 1.0)
    return np.hypot(px - (x0 + t * dx), py - (y0 + t * dy))


def point_seg_dist(P, S):
    """(len(P), len(S)) distances from each point to each segment"""
    P, S = _pts(P), _segs(S)
    n, m = len(P), len(S)
    _check_matrix(n, m)
    out = np.empty((n, m))
    step = max(1, BLOCK_PAIRS // max(m, 1))
    for a in range(0, n, step):
        p = P[a:a + step]
        out[a:a + step] = _pt_seg(p[:, 0:1], p[:, 1:2], S[None, :, 0], S[None, :, 1], S[None, :, 2], S[None, :, 3])
    return out


# ------------------------------------------------------------------------------------------------ segment - segment
def _cross(ox, oy, ax, ay, bx, by):
    return (ax - ox) * (by - oy) - (ay - oy) * (bx - ox)


def _seg_seg(a, b):
    """a, b: tuples (x0, y0, x1, y1) of broadcastable arrays -> exact minimum distance between the segments.
    Zero if they properly cross; otherwise the minimum of the four endpoint-to-segment distances (which is exact, and
    also covers touching, collinear overlap and zero-length segments)."""
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    d1 = _cross(ax0, ay0, ax1, ay1, bx0, by0)
    d2 = _cross(ax0, ay0, ax1, ay1, bx1, by1)
    d3 = _cross(bx0, by0, bx1, by1, ax0, ay0)
    d4 = _cross(bx0, by0, bx1, by1, ax1, ay1)
    crossing = (d1 * d2 < 0) & (d3 * d4 < 0)
    d = np.minimum(np.minimum(_pt_seg(ax0, ay0, bx0, by0, bx1, by1), _pt_seg(ax1, ay1, bx0, by0, bx1, by1)),
                   np.minimum(_pt_seg(bx0, by0, ax0, ay0, ax1, ay1), _pt_seg(bx1, by1, ax0, ay0, ax1, ay1)))
    return np.where(crossing, 0.0, d)


def _rows(A, B, a0, a1, b0, b1):
    """distance block for A[a0:a1] x B[b0:b1]"""
    return _seg_seg(tuple(A[a0:a1, k:k + 1] for k in range(4)), tuple(B[None, b0:b1, k] for k in range(4)))


def _blocks(n, m):
    """yield (a0, a1, b0, b1) tiles of at most BLOCK_PAIRS pairs"""
    if n == 0 or m == 0:
        return
    bm = min(m, BLOCK_PAIRS)
    an = max(1, BLOCK_PAIRS // bm)
    for a in range(0, n, an):
        for b in range(0, m, bm):
            yield a, min(a + an, n), b, min(b + bm, m)


def seg_seg_dist(A, B):
    """(len(A), len(B)) exact minimum distance between segments (centre lines)"""
    A, B = _segs(A), _segs(B)
    _check_matrix(len(A), len(B))
    out = np.empty((len(A), len(B)))
    for a0, a1, b0, b1 in _blocks(len(A), len(B)):
        out[a0:a1, b0:b1] = _rows(A, B, a0, a1, b0, b1)
    return out


def min_dist(A, B):
    """(len(A),) minimum distance from each segment of A to any segment of B (inf if B is empty); no matrix"""
    A, B = _segs(A), _segs(B)
    out = np.full(len(A), np.inf)
    for a0, a1, b0, b1 in _blocks(len(A), len(B)):
        np.minimum(out[a0:a1], _rows(A, B, a0, a1, b0, b1).min(axis=1), out=out[a0:a1])
    return out


def within(A, B, d, return_dist=False):
    """Index pairs (i, j), sorted lexicographically, with dist(A[i], B[j]) < d (strict), without the full matrix.
    Bounding boxes (grown by d) are sorted by x and pruned block-wise before the exact test."""
    A, B = _segs(A), _segs(B)
    n, m = len(A), len(B)
    empty = (np.zeros(0, np.int64), np.zeros(0, np.int64))
    if n == 0 or m == 0 or not d > 0:
        return (*empty, np.zeros(0)) if return_dist else empty
    bxlo, bxhi = np.minimum(B[:, 0], B[:, 2]), np.maximum(B[:, 0], B[:, 2])
    bylo, byhi = np.minimum(B[:, 1], B[:, 3]), np.maximum(B[:, 1], B[:, 3])
    axlo, axhi = np.minimum(A[:, 0], A[:, 2]), np.maximum(A[:, 0], A[:, 2])
    aylo, ayhi = np.minimum(A[:, 1], A[:, 3]), np.maximum(A[:, 1], A[:, 3])
    ob = np.argsort(bxlo, kind='stable')
    oa = np.argsort(axlo, kind='stable')
    sbx = bxlo[ob]
    I, J, D = [], [], []
    tile = 256
    for s in range(0, n, tile):
        ia = oa[s:s + tile]
        lim = np.searchsorted(sbx, axhi[ia].max() + d, side='left')          # B whose xmin < block xmax + d
        cand = ob[:lim]
        keep = ((bxhi[cand] > axlo[ia].min() - d) & (byhi[cand] > aylo[ia].min() - d) & (bylo[cand] < ayhi[ia].max() + d))
        cand = cand[keep]
        if not len(cand):
            continue
        Ab, Bc = A[ia], B[cand]
        for a0, a1, b0, b1 in _blocks(len(ia), len(cand)):
            dist = _rows(Ab, Bc, a0, a1, b0, b1)
            r, c = np.nonzero(dist < d)
            if len(r):
                I.append(ia[a0 + r]); J.append(cand[b0 + c]); D.append(dist[r, c])
    if not I:
        return (*empty, np.zeros(0)) if return_dist else empty
    I, J, D = np.concatenate(I), np.concatenate(J), np.concatenate(D)
    o = np.lexsort((J, I))
    return (I[o], J[o], D[o]) if return_dist else (I[o], J[o])


# ------------------------------------------------------------------------------------------------ boxes
def _boxes(B):
    B = np.asarray(B, np.float64)
    if B.ndim == 1:
        B = B[None, :]
    if B.ndim != 2 or B.shape[1] != 4:
        raise ValueError(f'boxes must be (N, 4), got {B.shape}')
    return B


def box_overlap(A, B, strict=True):
    """(len(A), len(B)) bool. strict: the boxes share positive area (touching edges do not overlap); else closed
    intersection (touching counts)."""
    A, B = _boxes(A), _boxes(B)
    _check_matrix(len(A), len(B))
    ox = np.minimum(A[:, None, 2], B[None, :, 2]) - np.maximum(A[:, None, 0], B[None, :, 0])
    oy = np.minimum(A[:, None, 3], B[None, :, 3]) - np.maximum(A[:, None, 1], B[None, :, 1])
    return (ox > 0) & (oy > 0) if strict else (ox >= 0) & (oy >= 0)


def box_dist(A, B):
    """(len(A), len(B)) euclidean gap between boxes (0 when they touch or overlap)"""
    A, B = _boxes(A), _boxes(B)
    _check_matrix(len(A), len(B))
    gx = np.maximum(np.maximum(A[:, None, 0] - B[None, :, 2], B[None, :, 0] - A[:, None, 2]), 0.0)
    gy = np.maximum(np.maximum(A[:, None, 1] - B[None, :, 3], B[None, :, 1] - A[:, None, 3]), 0.0)
    return np.hypot(gx, gy)


def seg_in_box(S, box, pad=0.0):
    """Does the segment touch the box grown by `pad` (closed)? Exact slab (Liang-Barsky) test, not a point sample.
    box (4,) -> bool (N,); box (M, 4) -> bool (N, M). `pad` may be a scalar or an array (N,) (e.g. half track width)."""
    S = _segs(S)
    box = np.asarray(box, np.float64)
    single = box.ndim == 1
    box = _boxes(box)
    pad = np.broadcast_to(np.asarray(pad, np.float64), (len(S),))[:, None]
    _check_matrix(len(S), len(box))
    x0, y0, dx, dy = S[:, 0:1], S[:, 1:2], S[:, 2:3] - S[:, 0:1], S[:, 3:4] - S[:, 1:2]
    t0 = np.zeros((len(S), len(box)))
    t1 = np.ones((len(S), len(box)))
    ok = np.ones((len(S), len(box)), bool)
    for o, dd, lo, hi in ((x0, dx, box[None, :, 0] - pad, box[None, :, 2] + pad), (y0, dy, box[None, :, 1] - pad, box[None, :, 3] + pad)):
        par = dd == 0
        ok &= ~par | ((o >= lo) & (o <= hi))
        with np.errstate(divide='ignore', invalid='ignore'):
            ta, tb = (lo - o) / dd, (hi - o) / dd
        tn, tf = np.minimum(ta, tb), np.maximum(ta, tb)
        t0 = np.where(par, t0, np.maximum(t0, tn))
        t1 = np.where(par, t1, np.minimum(t1, tf))
    res = ok & (t0 <= t1)
    return res[:, 0] if single else res


# ------------------------------------------------------------------------------------------------ polygons
def points_in_polys(P, polys, off=None):
    """(len(P), npoly) bool: point inside polygon (even-odd rule; a point exactly on an edge may go either way).
    `polys` is a list of (V, 2) vertex arrays, or, with `off`, one flat (V, 2) array plus int offsets as in
    BoardArrays (polygon j owns polys[off[j]:off[j+1]]). Rings are closed implicitly."""
    P = _pts(P)
    if off is not None:
        xy = np.asarray(polys, np.float64)
        polys = [xy[off[j]:off[j + 1]] for j in range(len(off) - 1)]
    out = np.zeros((len(P), len(polys)), bool)
    for j, poly in enumerate(polys):
        poly = np.asarray(poly, np.float64)
        if len(poly) < 3:
            continue
        x0, y0 = poly[:, 0], poly[:, 1]
        x1, y1 = np.roll(x0, -1), np.roll(y0, -1)
        step = max(1, BLOCK_PAIRS // len(poly))
        for a in range(0, len(P), step):
            px, py = P[a:a + step, 0:1], P[a:a + step, 1:2]
            straddle = (y0[None, :] > py) != (y1[None, :] > py)
            with np.errstate(divide='ignore', invalid='ignore'):
                xi = x0[None, :] + (py - y0[None, :]) * (x1 - x0)[None, :] / (y1 - y0)[None, :]
            out[a:a + step, j] = ((straddle & (px < xi)).sum(axis=1) % 2) == 1
    return out


# ------------------------------------------------------------------------------------------------ connectivity
def connected_components(n, joins):
    """Component labels (int32, length n) of n items given `joins`, an (E, 2) array of index pairs that touch.
    Labels are numbered in order of first appearance, so item 0 is always in component 0. Returns (count, labels)."""
    n = int(n if np.ndim(n) == 0 else len(n))
    J = np.asarray(joins, np.int64).reshape(-1, 2)
    if len(J) and (J.min() < 0 or J.max() >= n):
        raise ValueError('join index out of range')
    g = coo_matrix((np.ones(len(J), np.int8), (J[:, 0], J[:, 1])), shape=(n, n))
    k, lab = _cc(g, directed=False)
    _, first, inv = np.unique(lab, return_index=True, return_inverse=True)
    order = np.argsort(np.argsort(first))
    return int(k), order[inv].astype(np.int32)
