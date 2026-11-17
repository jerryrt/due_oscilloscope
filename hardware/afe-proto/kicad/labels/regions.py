"""regions.py: the block outlines as rectilinear polygons (owner, 2026-11-17).
Each block's region is the union of its members' courtyards grown by a halo, closed along rows and columns across gaps that hold nothing of another block, minus every
foreign courtyard (grown), disjoint from the other blocks' regions with a clear lane between. Members are by the hundreds of the designator (1 CH1, 2 CH2, 3 AWG, 4 POWER, 5 REF/CAL).
Grid 0.1 mm in Due mm. region(b, ...) -> {block: bool mask}, boundary_segments(mask) -> [(x0, y0, x1, y1)]"""
import numpy as np
from scipy import ndimage
RES = 0.1
X0, Y0, X1, Y1 = 16.5, -1.0, 117.0, 55.0
NX = int(round((X1 - X0) / RES)); NY = int(round((Y1 - Y0) / RES))
def ci(x): return int(round((x - X0) / RES))
def cj(y): return int(round((y - Y0) / RES))
def rect_mask(r, grow=0.0):
    m = np.zeros((NX, NY), bool)
    i0, i1 = max(0, ci(r[0] - grow)), min(NX, ci(r[2] + grow)); j0, j1 = max(0, cj(r[1] - grow)), min(NY, cj(r[3] + grow))
    if i1 > i0 and j1 > j0: m[i0:i1, j0:j1] = True
    return m
def union_rects(rects, grow=0.0):
    m = np.zeros((NX, NY), bool)
    for r in rects: m |= rect_mask(r, grow)
    return m
def dist_cheb(mask):          # chessboard distance in mm to the nearest True cell
    return ndimage.distance_transform_cdt(~mask, metric='chessboard') * RES
def fill_runs(m, free, lmax_cells, axis):
    """fill, along rows (axis 0 is x) or columns, the gap between two filled cells when every cell of the gap is free"""
    out = m.copy()
    A = out if axis == 0 else out.T; F = free if axis == 0 else free.T; O = A.copy()
    for j in range(A.shape[1]):
        col = A[:, j]; idx = np.flatnonzero(col)
        if len(idx) < 2: continue
        gaps = np.flatnonzero(np.diff(idx) > 1)
        for g in gaps:
            a, c = idx[g] + 1, idx[g + 1]
            if c - a <= lmax_cells and F[a:c, j].all(): O[a:c, j] = True
    return O if axis == 0 else O.T
def make_regions(members, obstacles, halo=1.2, lane=0.15, lmax=40.0, claims=None, keep=None):
    """members {block: [courtyard rect]}, obstacles {block: [rect already grown]} (foreign things for that block)"""
    blocks = list(members); R = {}; M = {}; D = {}
    for B in blocks:
        M[B] = union_rects(members[B]); D[B] = dist_cheb(M[B])
    for B in blocks:
        free = ~union_rects(obstacles[B]) | M[B]
        g = ndimage.maximum_filter(M[B], size=int(2 * halo / RES) + 1) & free
        g |= M[B]
        if keep and keep.get(B): g |= union_rects(keep[B])
        for _ in range(3):
            g = fill_runs(g, free, int(lmax / RES), 0); g = fill_runs(g, free, int(lmax / RES), 1)
        # bridges that touch only one cell of width are noise: opening by a lane-wide element, members kept
        g = (ndimage.binary_opening(g, structure=np.ones((3, 3), bool)) | M[B] | (union_rects(keep[B]) if keep and keep.get(B) else False))
        R[B] = g
    # disjoint: a contested cell goes to the nearest block's members (or the claiming block)
    stack = np.stack([R[B] for B in blocks]); cnt = stack.sum(0)
    dd = np.stack([np.where(R[B], D[B], 1e9) for B in blocks]); win = dd.argmin(0)
    for k, B in enumerate(blocks):
        R[B] = R[B] & ((cnt <= 1) | (win == k))
    if claims:
        for B, rects in claims.items():
            c = union_rects(rects)
            for O in blocks:
                if O != B: R[O] &= ~c
            R[B] |= c & ~union_rects(obstacles[B])
    # clear lane between two regions: drop non-member cells within `lane` of another region
    for B in blocks:
        other = np.zeros((NX, NY), bool)
        for O in blocks:
            if O != B: other |= R[O]
        near = ndimage.maximum_filter(other, size=int(2 * lane / RES) + 1)
        R[B] = R[B] & (~near | M[B] | (union_rects(keep[B]) if keep and keep.get(B) else False))
    # keep the components that hold a member
    for B in blocks:
        lab, n = ndimage.label(R[B])
        kp = set(np.unique(lab[(M[B] | (union_rects(keep[B]) if keep and keep.get(B) else False)) & R[B]])) - {0}
        R[B] = np.isin(lab, list(kp))
    return R
def boundary_segments(mask):
    """edges between a True cell and a non-True one, merged into maximal collinear segments, Due mm"""
    segs = []
    P = np.pad(mask, 1)
    # vertical edges (between x cells): at x index i (cell boundary i), over cell j
    left = P[1:-1, 1:-1] & ~P[:-2, 1:-1]; right = P[1:-1, 1:-1] & ~P[2:, 1:-1]
    bot = P[1:-1, 1:-1] & ~P[1:-1, :-2]; top = P[1:-1, 1:-1] & ~P[1:-1, 2:]
    def runs(E, vertical, off):
        out = []
        A = E if vertical else E.T
        for k in range(A.shape[0]):
            idx = np.flatnonzero(A[k])
            if not len(idx): continue
            st = idx[0]; pv = idx[0]
            for v in list(idx[1:]) + [None]:
                if v is None or v != pv + 1:
                    out.append((k + off, st, pv + 1)); 
                    if v is not None: st = v
                pv = v if v is not None else pv
        return out
    for i, a, c in runs(left, True, 0): segs.append((X0 + i * RES, Y0 + a * RES, X0 + i * RES, Y0 + c * RES))
    for i, a, c in runs(right, True, 1): segs.append((X0 + i * RES, Y0 + a * RES, X0 + i * RES, Y0 + c * RES))
    for j, a, c in runs(bot, False, 0): segs.append((X0 + a * RES, Y0 + j * RES, X0 + c * RES, Y0 + j * RES))
    for j, a, c in runs(top, False, 1): segs.append((X0 + a * RES, Y0 + j * RES, X0 + c * RES, Y0 + j * RES))
    return segs
