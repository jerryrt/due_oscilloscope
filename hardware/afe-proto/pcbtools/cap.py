"""Stray capacitance between chosen nets: a 3-D finite-difference Laplace solve on a window of the board, in numpy/scipy.

    pairs = pair_caps(b, ('/CH1_N', '/CH2_N'), window, pour=False, h=0.2)       -> {(i, j): pF}
    both  = self_cap(b, '/AWG_FB', pad=3.0, h=0.1)                             -> {False: pF, True: pF}
    rep   = report(b, cfg)                                                       the old tool's whole output, as data
    python -m pcbtools.cap BOARD.kicad_pcb|CACHE.npz [--config v2] | selftest    prints the old tool's lines

The model is the old cap.py's (every figure is a *(check)* against an extraction, resolution 0.1 mm for 0.2 mm tracks is good
to a factor of about 1.5):
  * the window is a box of h-mm cells; z: the bottom ground plane at z = 0 (Dirichlet 0), `t_board` of FR4 (er 4.5), the top
    copper at z = t_board, then `t_air` of air closed by a grounded lid (Dirichlet 0); the four sides are Neumann;
  * top-layer (F.Cu) copper is the conductor layer: pads as their bounding boxes, tracks as capsules (arcs as two chords);
    vias and every other layer are not modelled; each net not under study is held at 0 V; part bodies and mask are absent;
  * with `pour`, every cell farther than `pour_clear` from non-GND copper is GND (the top pour), without it only the routed
    copper counts; the mutual capacitance C_ij is the charge on conductor j with conductor i at 1 V and the rest at 0 V.
What differs from the old tool, and why (each is tested in tests/pcbtools/test_cap.py):
  * the grid is rasterised with ragged vectorised arithmetic (no per-cell or per-item loop), the pour keep-back is a disc
    dilation (scipy.ndimage) rather than a roll loop, so it no longer wraps round the window edge;
  * the sparse operator is built once per scenario (CSR over the free cells) and solved with scipy's conjugate gradient and
    a Jacobi preconditioner, relative residual `tol` (default 1e-6, the old tool's); the old tool re-derived a matrix-free
    stencil on every iteration. The system is the same one: harmonic-mean face permittivity, same boundary conditions.
Coordinates: the arrays are in Due mm (y up); the grid is laid out in KiCad mm (`boardio.from_due`) so that its cells fall
where the old tool's did. A capacitance is invariant under the flip; the cell phase is not, and it moves figures by ~1 %.
"""
from __future__ import annotations

import argparse
import dataclasses
import math
import sys

import numpy as np
import scipy.ndimage as ndi
import scipy.sparse as sp
import scipy.sparse.linalg as spla

from . import boardio

E0 = 8.854e-12            # F/m, as the old tool (the figures in the goldens are written with it)
CHUNK = 2_000_000         # cells rasterised at once: bounds the temporary arrays of the ragged expansion


@dataclasses.dataclass(frozen=True)
class Stack:
    """the board stack-up, mm; er is *(check)* (the JLC 1.6 mm 2-layer stack is not given in jlcpcb.md)"""
    er: float = 4.5
    t_board: float = 1.6
    t_air: float = 4.0
    pour_clear: float = 0.3


STACK = Stack()


# ------------------------------------------------------------------------------------------------ copper -> items
def kicad(x, y):
    """Due mm -> KiCad mm rounded to 1e-6 (one nm): bit-for-bit the doubles pcbnew's ToMM gives for the same integers, which
    matters because a 0.2 mm track on a 0.1 mm grid puts cell centres exactly on its edge and a rounding error flips them"""
    kx, ky = boardio.from_due(x, y)
    return np.round(kx, boardio.ND) + 0.0, np.round(ky, boardio.ND) + 0.0


@dataclasses.dataclass
class Copper:
    """F.Cu items in KiCad mm by group: rects[g] (n, 4) = x0 y0 x1 y1, segs[g] (n, 5) = xa ya xb yb width.
    Groups: each requested net, '__other__' (every other net, and no net) and '/GND'."""
    rects: dict
    segs: dict


def copper(b, nets) -> Copper:
    code = np.full(len(b.nets), len(nets), np.int64)                 # default group: other (net '' included)
    for k, n in enumerate(nets):
        code[b.net_id(n)] = k
    if '/GND' in b.nets:
        code[b.net_id('/GND')] = len(nets) + 1                       # ground is ground even if asked for, as the old tool had it
    names = list(nets) + ['__other__', '/GND']
    top = (b.p_layer_mask & 1).astype(bool)
    px0, py1 = kicad(b.p_bx0, b.p_by0)                    # y flips: Due y0 becomes KiCad y1
    px1, py0 = kicad(b.p_bx1, b.p_by1)
    prect = np.column_stack([px0, py0, px1, py1])[top]
    pg = code[b.p_net][top]
    top_s = b.s_layer == 0
    xa, ya = kicad(b.s_x0, b.s_y0)
    xb, yb = kicad(b.s_x1, b.s_y1)
    seg = np.column_stack([xa, ya, xb, yb, b.s_w])[top_s]
    sg = code[b.s_net][top_s]
    top_a = b.a_layer == 0                                           # an arc is two chords, start-mid and mid-end
    if top_a.any():
        a0x, a0y = kicad(b.a_x0, b.a_y0)
        amx, amy = kicad(b.a_xm, b.a_ym)
        a1x, a1y = kicad(b.a_x1, b.a_y1)
        c1 = np.column_stack([a0x, a0y, amx, amy, b.a_w])[top_a]
        c2 = np.column_stack([amx, amy, a1x, a1y, b.a_w])[top_a]
        seg = np.vstack([seg, c1, c2])
        sg = np.concatenate([sg, code[b.a_net][top_a], code[b.a_net][top_a]])
    return Copper({n: prect[pg == k] for k, n in enumerate(names)}, {n: seg[sg == k] for k, n in enumerate(names)})


def window(b, nets, pad):
    """the old window: the nets' pad centres and track end points (any layer), grown by pad -> (x0, y0, x1, y1) in KiCad mm"""
    ids = [b.net_id(n) for n in nets]
    pm = np.isin(b.p_net, ids)
    sm = np.isin(b.s_net, ids)
    xs = np.concatenate([b.p_x[pm], b.s_x0[sm], b.s_x1[sm]])
    ys = np.concatenate([b.p_y[pm], b.s_y0[sm], b.s_y1[sm]])
    if not len(xs):
        raise ValueError(f'no copper on nets {nets}')
    kx, ky = kicad(xs, ys)
    return kx.min() - pad, ky.min() - pad, kx.max() + pad, ky.max() + pad


# ------------------------------------------------------------------------------------------------- rasterisation
def _ranges(lo, hi, o, nn, h):
    """candidate cell index range [i0, i1] of the cells whose centre o + (i + .5) h can lie in [lo, hi], clipped to the
    window and one cell wider each side than the arithmetic says: the caller makes the exact comparison, so a rounding
    tie at a cell edge is decided by the same float expression the old tool used and not by this prefilter"""
    i0 = np.maximum(np.floor((lo - o) / h - 0.5) - 1, 0).astype(np.int64)
    i1 = np.minimum(np.ceil((hi - o) / h - 0.5) + 1, nn - 1).astype(np.int64)
    return i0, i1


def _expand(i0, i1, j0, j1):
    """ragged cross product of index ranges (item k owns cells i0[k]..i1[k] x j0[k]..j1[k]) in chunks of <= CHUNK cells:
    yields (item, i, j) integer arrays. A loop over chunks, never over items or cells."""
    ni, nj = np.maximum(i1 - i0 + 1, 0), np.maximum(j1 - j0 + 1, 0)
    cnt = ni * nj
    cum = np.cumsum(cnt)
    start = 0
    while start < len(cnt):
        base = cum[start - 1] if start else 0
        stop = max(int(np.searchsorted(cum, base + CHUNK, side='right')), start + 1)
        c = cnt[start:stop]
        tot = int(c.sum())
        if tot:
            item = np.repeat(np.arange(start, stop), c)
            local = np.arange(tot) - np.repeat(np.cumsum(c) - c, c)
            w = nj[item]
            yield item, i0[item] + local // w, j0[item] + local % w
        start = stop


def raster_rects(rects, x0, y0, nx, ny, h):
    """bool (ny, nx): cells whose centre lies inside any rect (x0 y0 x1 y1), closed"""
    m = np.zeros((ny, nx), bool)
    if len(rects):
        ix0, ix1 = _ranges(rects[:, 0], rects[:, 2], x0, nx, h)
        iy0, iy1 = _ranges(rects[:, 1], rects[:, 3], y0, ny, h)
        for k, jy, jx in _expand(iy0, iy1, ix0, ix1):
            X, Y = x0 + (jx + 0.5) * h, y0 + (jy + 0.5) * h
            ok = (X >= rects[k, 0]) & (X <= rects[k, 2]) & (Y >= rects[k, 1]) & (Y <= rects[k, 3])
            m[jy[ok], jx[ok]] = True
    return m


def raster_segs(segs, x0, y0, nx, ny, h):
    """bool (ny, nx): cells whose centre lies within w/2 of any segment (xa ya xb yb w): capsules"""
    m = np.zeros((ny, nx), bool)
    if len(segs):
        xa, ya, xb, yb, w = segs.T
        r = w / 2
        ix0, ix1 = _ranges(np.minimum(xa, xb) - r, np.maximum(xa, xb) + r, x0, nx, h)
        iy0, iy1 = _ranges(np.minimum(ya, yb) - r, np.maximum(ya, yb) + r, y0, ny, h)
        for k, jy, jx in _expand(iy0, iy1, ix0, ix1):
            X, Y = x0 + (jx + 0.5) * h, y0 + (jy + 0.5) * h
            dx, dy = (xb - xa)[k], (yb - ya)[k]
            L2 = dx * dx + dy * dy
            t = np.clip(((X - xa[k]) * dx + (Y - ya[k]) * dy) / np.where(L2 > 0, L2, 1.0), 0, 1)
            d2 = (X - (xa[k] + t * dx)) ** 2 + (Y - (ya[k] + t * dy)) ** 2
            ok = d2 <= r[k] ** 2
            m[jy[ok], jx[ok]] = True
    return m


def raster(cu, group, x0, y0, nx, ny, h):
    return raster_rects(cu.rects[group], x0, y0, nx, ny, h) | raster_segs(cu.segs[group], x0, y0, nx, ny, h)


def keep_back(occupied, clear, h):
    """cells within `clear` mm of occupied cells: a disc dilation of radius round(clear / h) cells (no wrap-around)"""
    k = int(round(clear / h))
    yy, xx = np.mgrid[-k:k + 1, -k:k + 1]
    return ndi.binary_dilation(occupied, structure=(xx * xx + yy * yy <= k * k)) if k else occupied.copy()


# ---------------------------------------------------------------------------------------------------- the solver
class Field:
    """The discrete Laplace problem on a grid of cells with permittivity `eps` (nz, ny, nx), `fixed` cells Dirichlet.
    K is the weighted graph Laplacian (face weight = harmonic mean of the two cells' permittivity, equal cell sizes, so the
    cell size cancels and C = E0 * h * q); the sides have no faces (Neumann). Built once, solved for any Dirichlet values."""

    def __init__(self, eps, fixed, tol=1e-6, maxiter=20000):
        self.shape = eps.shape
        self.tol, self.maxiter = tol, maxiter
        n = eps.size
        idx = np.arange(n, dtype=np.int32).reshape(eps.shape)
        r, c, w = [], [], []
        for a, b in ((np.s_[:, :, :-1], np.s_[:, :, 1:]), (np.s_[:, :-1, :], np.s_[:, 1:, :]), (np.s_[:-1, :, :], np.s_[1:, :, :])):
            ea, eb = eps[a], eps[b]
            r.append(idx[a].ravel())
            c.append(idx[b].ravel())
            w.append((2 * ea * eb / (ea + eb)).ravel())
        r, c, w = np.concatenate(r), np.concatenate(c), np.concatenate(w)
        diag = np.bincount(r, w, n) + np.bincount(c, w, n)
        self.K = (sp.coo_matrix((np.concatenate([-w, -w]), (np.concatenate([r, c]), np.concatenate([c, r]))), shape=(n, n)).tocsr()
                  + sp.diags(diag)).tocsr()
        self.fixed = fixed.ravel().copy()
        self.free = np.flatnonzero(~self.fixed)
        self.Kff = self.K[self.free][:, self.free].tocsr()
        self.M = sp.diags(1.0 / np.maximum(self.Kff.diagonal(), 1e-12))                          # Jacobi
        self.iterations = 0

    def solve(self, v_fixed):
        """V (nz, ny, nx) with V = v_fixed on the fixed cells (v_fixed: any array of that shape, read where fixed)"""
        v0 = np.where(self.fixed, np.asarray(v_fixed, np.float64).ravel(), 0.0)
        rhs = -(self.K @ v0)[self.free]
        count = [0]
        x, info = spla.cg(self.Kff, rhs, rtol=self.tol, atol=0.0, maxiter=self.maxiter, M=self.M,
                          callback=lambda xk: count.__setitem__(0, count[0] + 1))
        if info != 0:
            raise RuntimeError(f'cg did not converge to {self.tol} in {self.maxiter} iterations (info {info})')
        self.iterations = count[0]
        v = v0.copy()
        v[self.free] = x
        return v.reshape(self.shape)

    def charge(self, V, mask):
        """flux into the cells of `mask` from their neighbours, in E0 * h units: (K V) summed over the mask (positive on a
        conductor held at the higher potential, negative on a grounded one near it)"""
        return float((self.K @ V.ravel()).reshape(self.shape)[mask].sum())


def to_pF(q, h):
    return q * h * 1e-3 * E0 * 1e12


def _grid(h, stack):
    nzb = int(round(stack.t_board / h))
    nza = int(round(stack.t_air / h))
    return nzb, nzb + 1 + nza + 1


def _eps(shape, nzb, stack):
    eps = np.ones(shape)
    eps[:nzb + 1] = stack.er
    eps[nzb] = (stack.er + 1) / 2                      # the top copper layer sits half in the board, half in air
    return eps


def _fixed(cond, nzb):
    fixed = cond.copy()
    fixed[0] = True                                    # ground plane
    fixed[-1] = True                                   # lid
    return fixed


# ------------------------------------------------------------------------------------------------- the figures
def pair_caps(b, nets, win, pour, h=0.1, stack=STACK, tol=1e-6):
    """{(i, j): pF}: charge on conductor j with conductor i at 1 V, for every ordered pair of `nets`; `win` in KiCad mm"""
    cu = copper(b, tuple(nets))
    x0, y0, x1, y1 = win
    nx, ny = int(round((x1 - x0) / h)), int(round((y1 - y0) / h))
    nzb, nz = _grid(h, stack)
    eps = _eps((nz, ny, nx), nzb, stack)
    masks = {n: raster(cu, n, x0, y0, nx, ny, h) for n in nets}
    other = raster(cu, '__other__', x0, y0, nx, ny, h)
    gnd = raster(cu, '/GND', x0, y0, nx, ny, h)
    if pour:
        occ = other.copy()
        for m in masks.values():
            occ |= m
        gnd |= ~keep_back(occ, stack.pour_clear, h)
    cond = np.zeros(eps.shape, bool)
    cond[nzb] = gnd | other
    for m in masks.values():
        cond[nzb] |= m
    field = Field(eps, _fixed(cond, nzb), tol)
    res = {}
    for i in nets:
        v = np.zeros(eps.shape)
        v[nzb][masks[i]] = 1.0
        V = field.solve(v)
        for j in nets:
            if j != i:
                res[(i, j)] = -to_pF(field.charge(V, _at(nzb, masks[j], eps.shape)), h)     # K V is minus the old "A(V)"
    return res


def _at(nzb, m2, shape):
    m = np.zeros(shape, bool)
    m[nzb] = m2
    return m


def self_cap(b, net, pad=3.0, h=0.1, stack=STACK, tol=1e-6):
    """{False: pF, True: pF}: capacitance of one net's top copper to everything else (held at 0 V), without and with the
    top pour (kept `pour_clear` off the copper); the window is the net's own items grown by `pad`"""
    cu = copper(b, (net,))
    r, s = cu.rects[net], cu.segs[net]
    xs = np.concatenate([r[:, [0, 2]].ravel(), s[:, [0, 2]].ravel()])
    ys = np.concatenate([r[:, [1, 3]].ravel(), s[:, [1, 3]].ravel()])
    if not len(xs):
        raise ValueError(f'no top copper on {net}')
    x0, y0, x1, y1 = xs.min() - pad, ys.min() - pad, xs.max() + pad, ys.max() + pad
    nx, ny = int(round((x1 - x0) / h)), int(round((y1 - y0) / h))
    nzb, nz = _grid(h, stack)
    eps = _eps((nz, ny, nx), nzb, stack)
    m = raster(cu, net, x0, y0, nx, ny, h)
    other = raster(cu, '__other__', x0, y0, nx, ny, h)
    gnd = raster(cu, '/GND', x0, y0, nx, ny, h)
    out = {}
    for pour in (False, True):
        g = gnd | other
        if pour:
            g = g | ~keep_back(m | other, stack.pour_clear, h)
        cond = np.zeros(eps.shape, bool)
        cond[nzb] = m | g
        field = Field(eps, _fixed(cond, nzb), tol)
        v = np.zeros(eps.shape)
        v[nzb][m] = 1.0
        out[pour] = abs(to_pF(field.charge(field.solve(v), _at(nzb, m, eps.shape)), h))
    return out


@dataclasses.dataclass
class Report:
    pairs: dict        # (label, pour) -> {'c': pF, 'reverse': pF, 'window': (w, h) mm, 'cell': mm}
    selfs: dict        # net -> {False: pF, True: pF}

    def lines(self):
        """the old tool's printed lines"""
        out = [f'{lab:20s} pour={pour!s:5s} window {d["window"][0]:.0f}x{d["window"][1]:.0f} mm  C = {d["c"] * 1e3:.2f} fF '
               f'(reverse {d["reverse"] * 1e3:.2f} fF)' for (lab, pour), d in self.pairs.items()]
        out += [f'{n} self capacitance to everything else (tracks and pads, no package): no pour {r[False]:.3f} pF, '
                f'with the top pour (kept 0.3 mm off) {r[True]:.3f} pF' for n, r in self.selfs.items()]
        return out


def report(b, cfg, stack=STACK, tol=1e-6, h_override=None):
    """the old main(): every CAP_PAIRS entry without and with the pour, every CAP_SELF net; `h_override` replaces all cell sizes"""
    pairs, selfs = {}, {}
    for label, nets, pad, h in cfg.CAP_PAIRS:
        h = h_override or h
        w = window(b, nets, pad)
        for pour in (False, True):
            r = pair_caps(b, list(nets), w, pour, h, stack, tol)
            pairs[(label, pour)] = dict(c=r[(nets[0], nets[1])], reverse=r[(nets[1], nets[0])], window=(w[2] - w[0], w[3] - w[1]), cell=h)
    for net, pad, h in cfg.CAP_SELF:
        selfs[net] = self_cap(b, net, pad, h_override or h, stack, tol)
    return Report(pairs, selfs)


# --------------------------------------------------------------------------------------------------- selftests
def plates(layers, nxy=20, h=0.1, tol=1e-6):
    """Full-width parallel plates, the lower plate on cell 1, the upper on cell sum(n) + 1 (the lid, at 1 V); `layers` is
    ((cells, er), ...) from the bottom. -> (FD pF, discrete-exact pF, continuum pF). The discrete answer is the series of
    face conductances (each interface a harmonic mean) and the solver must reproduce it to its tolerance; the continuum
    answer differs by the half-cell uncertainty of where an interface sits."""
    nzc = sum(n for n, _ in layers)
    eps = np.ones((nzc + 2, nxy, nxy))
    k = 1
    for n, er in layers:
        eps[k:k + n] = er
        k += n
    eps[nzc + 1] = layers[-1][1]
    cond = np.zeros(eps.shape, bool)
    cond[1] = cond[nzc + 1] = True
    field = Field(eps, _fixed(cond, 1), tol)
    v = np.zeros(eps.shape)
    v[nzc + 1] = 1.0
    V = field.solve(v)
    m = np.zeros(eps.shape, bool)
    m[1] = True
    fd = abs(to_pF(field.charge(V, m), h))
    col = eps[1:nzc + 2, 0, 0]
    faces = 2 * col[:-1] * col[1:] / (col[:-1] + col[1:])
    area = (nxy * h * 1e-3) ** 2
    discrete = E0 * area / (h * 1e-3 * (1 / faces).sum()) * 1e12
    cont = E0 * area / (sum(n * h * 1e-3 / er for n, er in layers)) * 1e12
    return fd, discrete, cont


def hammerstad_jensen(u, er):
    """single microstrip, no lid: (effective permittivity, characteristic impedance)"""
    a = 1 + math.log((u ** 4 + (u / 52) ** 2) / (u ** 4 + 0.432)) / 49 + math.log(1 + (u / 18.1) ** 3) / 18.7
    bb = 0.564 * ((er - 0.9) / (er + 3)) ** 0.053
    ee = (er + 1) / 2 + (er - 1) / 2 * (1 + 10 / u) ** (-a * bb)
    F = 6 + (2 * math.pi - 6) * math.exp(-(30.666 / u) ** 0.7528)
    z0 = 376.73 / (2 * math.pi * math.sqrt(ee)) * math.log(F / u + math.sqrt(1 + (2 / u) ** 2))
    return ee, z0


def garg_bahl_mutual(w, h_sub, s, er, c_single):
    """mutual capacitance per metre of two coupled microstrips, pF/m, from the even and odd mode (from memory: *(check)*)"""
    e0 = E0 * 1e12
    u, g = w / h_sub, s / h_sub
    cp = e0 * er * u
    cf = 0.5 * (c_single - cp)
    A = math.exp(-0.1 * math.exp(2.33 - 2.53 * u))
    cfp = cf / (1 + A / g * math.tanh(8 * g))
    ce = cp + cf + cfp

    def K(k):
        a_, b_ = 1.0, math.sqrt(1 - k * k)
        for _ in range(30):
            a_, b_ = (a_ + b_) / 2, math.sqrt(a_ * b_)
        return math.pi / (2 * a_)
    k = g / (g + 2 * u)
    kp = math.sqrt(1 - k * k)
    cga = e0 * K(kp) / K(k)
    cgd = e0 * er / math.pi * math.log(1 / math.tanh(math.pi * g / 4)) + 0.65 * cf * (0.02 * math.sqrt(er) / g + 1 - 1 / er ** 2)
    return (cp + cf + cga + cgd - ce) / 2, ce, cp + cf + cga + cgd


def microstrip(w=1.6, h_sub=1.6, s=0.8, er=4.5, h=0.1, ny=40, pad=6.0, t_air=4.0, tol=1e-6):
    """two long strips w wide, s apart, on a board h_sub thick (lid t_air above, Neumann sides, extruded ny cells)
    -> dict: c11 (one strip alone, pF/m), c21 (mutual, pF/m), and the two formulas' values and the deviations"""
    nzb = int(round(h_sub / h))
    nza = int(round(t_air / h))
    nz = nzb + 1 + nza + 1
    nx = int(round((2 * w + s + 2 * pad) / h))
    eps = np.ones((nz, ny, nx))
    eps[:nzb + 1] = er
    eps[nzb] = (er + 1) / 2
    xs = (np.arange(nx) + 0.5) * h
    m1 = np.zeros((ny, nx), bool)
    m2 = np.zeros((ny, nx), bool)
    m1[:, (xs >= pad) & (xs < pad + w)] = True
    m2[:, (xs >= pad + w + s) & (xs < pad + 2 * w + s)] = True
    per_m = h * 1e-3 * E0 * 1e12 / (ny * h * 1e-3)

    def solve(cond2d):
        cond = np.zeros(eps.shape, bool)
        cond[nzb] = cond2d
        field = Field(eps, _fixed(cond, nzb), tol)
        v = np.zeros(eps.shape)
        v[nzb][m1] = 1.0
        return field, field.solve(v)

    f, V = solve(m1 | m2)
    c21 = -f.charge(V, _at(nzb, m2, eps.shape)) * per_m
    f, V = solve(m1)
    c11 = abs(f.charge(V, _at(nzb, m1, eps.shape))) * per_m
    ee, z0 = hammerstad_jensen(w / h_sub, er)
    c_single = math.sqrt(ee) / (299792458 * z0) * 1e12
    c12, ce, co = garg_bahl_mutual(w, h_sub, s, er, c_single)
    return dict(c11=c11, hj=c_single, c11_dev=c11 / c_single - 1, c21=c21, gb=c12, gb_even=ce, gb_odd=co, c21_dev=c21 / c12 - 1)


# ------------------------------------------------------------------------------------------------------ command line
def main(argv=None):
    import importlib
    from . import check
    ap = argparse.ArgumentParser(prog='pcbtools.cap', description=__doc__.split('\n\n')[0])
    ap.add_argument('board', help="BOARD.kicad_pcb, CACHE.npz, or 'selftest'")
    ap.add_argument('--config', default='v2')
    ap.add_argument('--tol', type=float, default=1e-6)
    a = ap.parse_args(argv)
    if a.board == 'selftest':
        worst = 0.0
        for layers in (((12, 1.0), (6, 4.5)), ((8, 4.5), (4, 1.0)), ((10, 2.0),)):
            fd, disc, cont = plates(layers, tol=a.tol)
            print(f'selftest plates {layers}: FD {fd * 1e3:.3f} fF, discrete {disc * 1e3:.3f} fF, continuum {cont * 1e3:.3f} fF '
                  f'(error against the continuum {abs(fd / cont - 1) * 100:.3f} %)')
            worst = max(worst, abs(fd / cont - 1))
        r = microstrip(tol=a.tol)
        print(f'microstrip w/h = 1.00, er 4.5: single line  FD {r["c11"]:.1f} pF/m, Hammerstad-Jensen {r["hj"]:.1f} pF/m ({r["c11_dev"] * 100:+.1f} %)')
        print(f'coupled, gap s/h = 0.50: mutual FD {r["c21"]:.2f} pF/m, Garg-Bahl (even {r["gb_even"]:.1f}, odd {r["gb_odd"]:.1f}) '
              f'{r["gb"]:.2f} pF/m ({r["c21_dev"] * 100:+.1f} %)')
        return 0 if worst < 0.08 else 1
    cfg = importlib.import_module(f'pcbtools.boards.{a.config}')
    for ln in report(check.load(a.board), cfg, tol=a.tol).lines():
        print(ln, flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
