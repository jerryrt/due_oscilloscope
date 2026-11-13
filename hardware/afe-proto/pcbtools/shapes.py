"""Copper as exact outlines, for the rules that measure an EDGE-to-EDGE gap (LR-4's pour keep-back, LR-5's keep-out).

A track is a capsule (its centre segment and half its width), a round or oval pad a capsule too (circle: a point and a radius;
oval: the axis of its long side and half its short side), a rectangular pad a rotated rectangle (four sides, radius 0).
roundrect is treated as the rectangle it is inscribed in (the corner radius is not in the arrays: that overstates the pad by at
most the radius, which is the conservative side for a keep-away rule); a custom pad (`p_shape` 4) is its bounding box.

    pad_copper(b, rows)    -> Copper   (segments C (k, 4), radius r (k,), owner (k,))  pads rows -> shapes
    track_copper(b, rows)  -> Copper   the same for segment rows (and nothing else: arcs are the caller's)
    Copper.gap_to_segments(E)          (n,) edge-to-edge distance of each owner's copper to the segments E (m, 4)
    Copper.gap_to_box(bx)              (n,) the same to a closed rectangle, 0 when they touch or overlap
    Copper.gap_to_fill(xy, off, hole)  (n,) the same to the EDGES of a polygon fill (rings and holes), 0 when the copper lies
                                       on the fill (a point of it inside the fill's area) - the distance the keep-back is
                                       measured by: how far the pour's boundary is from the node, not how far a probe point is
Every distance is exact (segment to segment, minus the radii), never sampled.
"""
from __future__ import annotations

import dataclasses

import numpy as np

from . import geom


@dataclasses.dataclass
class Copper:
    C: np.ndarray          # (k, 4) centre segments (a point is a zero-length segment)
    r: np.ndarray          # (k,) radius to add around each (half track width, pad radius; 0 for a rectangle's sides)
    owner: np.ndarray      # (k,) item index 0..n-1 each row belongs to
    n: int

    def _reduce(self, per_row):
        out = np.full(self.n, np.inf)
        np.minimum.at(out, self.owner, per_row)
        return out

    def gap_to_segments(self, E):
        E = np.asarray(E, np.float64).reshape(-1, 4)
        if not len(E) or not len(self.C):
            return np.full(self.n, np.inf)
        return self._reduce(np.maximum(geom.min_dist(self.C, E) - self.r, 0.0))

    def _ends(self):
        return np.vstack([self.C[:, :2], self.C[:, 2:]]), np.concatenate([self.owner, self.owner])

    def gap_to_box(self, bx):
        bx = np.asarray(bx, np.float64)
        sides = np.array([[bx[0], bx[1], bx[2], bx[1]], [bx[2], bx[1], bx[2], bx[3]], [bx[2], bx[3], bx[0], bx[3]],
                          [bx[0], bx[3], bx[0], bx[1]]])
        d = self.gap_to_segments(sides)
        P, own = self._ends()
        inb = (P[:, 0] >= bx[0]) & (P[:, 0] <= bx[2]) & (P[:, 1] >= bx[1]) & (P[:, 1] <= bx[3])
        d[np.unique(own[inb])] = 0.0
        return d

    def gap_to_fill(self, xy, off, hole):
        """`xy` (V, 2) all vertices, `off` ring offsets into xy (len rings + 1, starting at 0), `hole` a flag per ring"""
        xy = np.asarray(xy, np.float64).reshape(-1, 2)
        off = np.asarray(off, np.int64)
        E = []
        for j in range(len(off) - 1):
            ring = xy[off[j]:off[j + 1]]
            if len(ring) >= 2:
                E.append(np.column_stack([ring, np.roll(ring, -1, axis=0)]))
        if not E:
            return np.full(self.n, np.inf)
        d = self.gap_to_segments(np.vstack(E))
        P, own = self._ends()
        inside = geom.points_in_polys(P, xy, off, hole=hole).any(axis=1)
        d[np.unique(own[inside])] = 0.0
        return d


def _corners(cx, cy, sx, sy, rot):
    a = np.radians(rot)[:, None]
    lx = np.array([-.5, .5, .5, -.5])[None, :] * sx[:, None]
    ly = np.array([-.5, -.5, .5, .5])[None, :] * sy[:, None]
    return (cx[:, None] + lx * np.cos(a) - ly * np.sin(a), cy[:, None] + lx * np.sin(a) + ly * np.cos(a))


def pad_copper(b, rows):
    rows = np.asarray(rows, np.int64).reshape(-1)
    cx, cy = b.p_x[rows], b.p_y[rows]
    sx, sy, rot, shp = b.p_sx[rows], b.p_sy[rows], b.p_rot[rows], b.p_shape[rows]
    C, R, O = [], [], []
    cap = (shp == 0) | (shp == 2)
    # capsule: the long axis of an oval (a circle is a point), radius half the short side
    half = np.maximum(np.abs(sx - sy) / 2, 0.0)
    a = np.radians(rot)
    ux = np.where(sx >= sy, np.cos(a), -np.sin(a)) * half
    uy = np.where(sx >= sy, np.sin(a), np.cos(a)) * half
    ci = np.flatnonzero(cap)
    C.append(np.column_stack([cx[ci] - ux[ci], cy[ci] - uy[ci], cx[ci] + ux[ci], cy[ci] + uy[ci]]))
    R.append(np.minimum(sx, sy)[ci] / 2)
    O.append(ci)
    # rectangle (rect, roundrect): four sides of the rotated rectangle; custom: the bounding box
    ri = np.flatnonzero(shp != 0)
    ri = ri[(shp[ri] == 1) | (shp[ri] == 3)]
    if len(ri):
        X, Y = _corners(cx[ri], cy[ri], sx[ri], sy[ri], rot[ri])
        for k in range(4):
            C.append(np.column_stack([X[:, k], Y[:, k], X[:, (k + 1) % 4], Y[:, (k + 1) % 4]]))
            R.append(np.zeros(len(ri)))
            O.append(ri)
    oi = np.flatnonzero(shp == 4)
    if len(oi):
        x0, y0, x1, y1 = b.p_bx0[rows][oi], b.p_by0[rows][oi], b.p_bx1[rows][oi], b.p_by1[rows][oi]
        X = np.column_stack([x0, x1, x1, x0])
        Y = np.column_stack([y0, y0, y1, y1])
        for k in range(4):
            C.append(np.column_stack([X[:, k], Y[:, k], X[:, (k + 1) % 4], Y[:, (k + 1) % 4]]))
            R.append(np.zeros(len(oi)))
            O.append(oi)
    return Copper(np.vstack(C) if C else np.zeros((0, 4)), np.concatenate(R), np.concatenate(O).astype(np.int64), len(rows))


def track_copper(b, rows):
    rows = np.asarray(rows, np.int64).reshape(-1)
    C = np.column_stack([b.s_x0[rows], b.s_y0[rows], b.s_x1[rows], b.s_y1[rows]]) if len(rows) else np.zeros((0, 4))
    return Copper(C, b.s_w[rows] / 2, np.arange(len(rows), dtype=np.int64), len(rows))


def join(*parts):
    """one Copper whose owners are numbered part by part (so a caller keeps its own index ranges)"""
    n = 0
    C, R, O = [], [], []
    for p in parts:
        C.append(p.C)
        R.append(p.r)
        O.append(p.owner + n)
        n += p.n
    return Copper(np.vstack(C), np.concatenate(R), np.concatenate(O).astype(np.int64), n)
