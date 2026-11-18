"""General layout rules for a two-layer board, each `rule(b, cfg, report=None) -> Result(ok, detail, figures)`.

`b` is a pcbkit.board.BoardArrays, `cfg` a configuration (see config.py: project names raise when missing, tunables have documented
defaults, and `report`, a list, receives the effective configuration as (name, value, source) rows). The names each rule reads are in
its `*_NAMES` table here and in CONFIG.md. A rule never reads a name it does not list.

Rules in this module: ground_plane, bottom_hops, sensitive_nets, pour_gap, keepout_ring, decoupling, blocks, test_points, designators, track_geometry, fill_quality. `*_parts` return the same findings as lists, for a caller that must interleave
them with its own (the AFE's LR-1 keeps its printed order that way).
"""
from __future__ import annotations

import dataclasses
import math
import weakref

import numpy as np
from scipy.spatial import cKDTree

from . import geom, outlines
from .board import FieldNotRead, require
from .config import EPS_NAME, declare, format_report, project, resolve, tunable, check_names


@dataclasses.dataclass
class Result:
    ok: bool
    detail: str
    figures: dict


class PadTable:
    """every pad of the board in file order, as (part, pin) keys that repeat where a part has several pads of one number (an exposed pad with via-in-pad squares) or unnumbered pads.
    `lookup[(ref, pin)]` is the LAST pad of a key, which is what a single-pad question ('the pad R1.2') gets; it used to be the only one the table held, so a rule judged a partial pad"""

    def __init__(self, b):
        refs = [b.fp_ref[i] for i in b.p_fp]
        self.keys = list(zip(refs, b.p_pin))
        self.rows = np.arange(len(refs), dtype=np.int64)
        self.lookup = {k: row for row, k in enumerate(self.keys)}
        self.net = b.p_net[self.rows] if len(self.rows) else np.zeros(0, np.int32)

    def row(self, ref, pin):
        return self.lookup[(ref, pin)]


_CACHE = weakref.WeakKeyDictionary()


def pads(b):
    t = _CACHE.get(b)
    if t is None:
        t = _CACHE[b] = PadTable(b)
    return t


def nid(b, name):
    """net id of `name`, or -1 when the board has no such net (it then matches nothing)"""
    try:
        return b.net_id(name)
    except KeyError:
        return -1


def net_prefix(b, prefixes):
    """bool over net ids: the net name starts with one of `prefixes`"""
    return np.array([n.startswith(tuple(prefixes)) for n in b.nets], bool)


def segs(b, mask=None):
    S = np.column_stack([b.s_x0, b.s_y0, b.s_x1, b.s_y1]) if len(b.s_idx) else np.zeros((0, 4))
    return S if mask is None else S[mask]


def length_of(b, net, top_only=True):
    m = (b.s_net == nid(b, net)) & ((b.s_layer == 0) if top_only else True)
    return float(geom.seg_len(segs(b, m)).sum())


def pad_c(b, ref, pin):
    r = pads(b).row(ref, pin)
    return np.array([b.p_x[r], b.p_y[r]])


def pad_net(b, ref, pin):
    return b.nets[b.p_net[pads(b).row(ref, pin)]]


def pad_box(b, rows):
    return np.column_stack([b.p_bx0[rows], b.p_by0[rows], b.p_bx1[rows], b.p_by1[rows]])


def pos(b, ref):
    i = b.ref_index(ref)
    return np.array([b.fp_x[i], b.fp_y[i]])


def box(b, ref):
    i = b.ref_index(ref)
    v = np.array([b.fp_cx0[i], b.fp_cy0[i], b.fp_cx1[i], b.fp_cy1[i]])
    if np.isnan(v).any():
        raise KeyError(f'{ref} has no courtyard')
    return v


def has_box(b, ref):
    try:
        i = b.ref_index(ref)
    except KeyError:
        return False
    return not np.isnan(b.fp_cx0[i])


def sample_points(S, step):
    """points along each segment every `step` mm exactly as the old seg_pts: n = max(1, int(len/step)), n+1 points k/n.
    Returns (points (M,2), segment index (M,))."""
    S = np.asarray(S, np.float64).reshape(-1, 4)
    n = np.maximum(1, (geom.seg_len(S) / step).astype(np.int64))
    sid = np.repeat(np.arange(len(S)), n + 1)
    start = np.concatenate([[0], np.cumsum(n + 1)[:-1]])
    k = np.arange(len(sid)) - np.repeat(start, n + 1)
    t = (k / np.repeat(n, n + 1))[:, None]
    return S[sid, :2] + (S[sid, 2:] - S[sid, :2]) * t, sid


def pt_box_dist(P, bx):
    """distance of points (N,2) to one box (4,)"""
    return np.hypot(np.maximum.reduce([bx[0] - P[:, 0], np.zeros(len(P)), P[:, 0] - bx[2]]),
                    np.maximum.reduce([bx[1] - P[:, 1], np.zeros(len(P)), P[:, 1] - bx[3]]))


def seg_box_dist(S, bx):
    """exact distance of each segment (N,4) to a box (4,): 0 when it touches the box, else the nearest box edge"""
    S = np.asarray(S, np.float64).reshape(-1, 4)
    if not len(S):
        return np.zeros(0)
    edges = np.array([[bx[0], bx[1], bx[2], bx[1]], [bx[2], bx[1], bx[2], bx[3]], [bx[2], bx[3], bx[0], bx[3]],
                      [bx[0], bx[3], bx[0], bx[1]]])
    d = geom.seg_seg_dist(S, edges).min(axis=1)
    return np.where(geom.seg_in_box(S, np.asarray(bx, float)), 0.0, d)


def _first_true(M):
    """for each row of a bool matrix: (any, index of the first True)"""
    return M.any(axis=1), M.argmax(axis=1)


# ----------------------------------------------------------------------------------------------------- ground_plane
def _layer_code(v):
    return {'F': 0, 'B': 1, 'F.CU': 0, 'B.CU': 1}[v.upper()] if isinstance(v, str) else int(v)


GROUND_PLANE_NAMES = (
    project('GND', 'net name', 'the ground net'),
    project('PLANE_LAYER', "'F' | 'B' (or 0 | 1)", 'the copper layer that carries the plane'),
    tunable('COPPER_LAYERS', 2, 'count', 'the board must have exactly this many copper layers'),
    tunable('GND_VIA_REACH', 3.0, 'mm', 'an SMD ground pad has a via of its own within this distance'),
)


def _gnd_components(b, gnd, pad_rows, gv, tht_rows):
    """connected-copper component ids of the given GND pads and of the GND vias/plated holes `gv`: pads, vias and top-layer GND tracks that touch (copper to copper) are one component"""
    nv = len(gv)
    allpads = [r for r in range(len(b.p_net)) if b.p_net[r] == gnd]
    P = list(dict.fromkeys(list(pad_rows) + allpads))
    nP = len(P)
    S = np.column_stack([b.s_x0, b.s_y0, b.s_x1, b.s_y1])
    sg = np.flatnonzero((b.s_net == gnd) & (b.s_layer == 0)) if len(b.s_x0) else np.zeros(0, np.int64)
    n = nP + nv + len(sg)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, c):
        parent[find(a)] = find(c)
    cu = geom.pad_copper(b, np.array(P, np.int64)) if nP else None
    vr = np.concatenate([b.v_dia[b.v_net == gnd] / 2, np.array([max(b.p_sx[r], b.p_sy[r]) / 2 for r in tht_rows])]) if nv else np.zeros(0)
    if nP and nv:                                                           # a via or plated hole overlapping a pad
        pts = np.column_stack([gv, gv])
        D = geom.seg_seg_dist(cu.C, pts) - cu.r[:, None]
        M = np.full((nP, nv), np.inf)
        np.minimum.at(M, cu.owner, D)
        for a, c_ in zip(*np.nonzero(M - vr[None, :] <= 1e-6)):
            union(a, nP + c_)
        pa = _pad_arrays(b)                                                 # and one whose centre lies inside the pad's rectangle, however big the pad (the distance above is to its edge)
        pa = {k: (v[np.array(P, np.int64)] if isinstance(v, np.ndarray) else v) for k, v in pa.items()}
        for c_, a in zip(*np.nonzero(_in_pads(gv, pa))):
            union(a, nP + c_)
    if len(sg):
        SG = S[sg]
        W = b.s_w[sg]
        T = geom.seg_seg_dist(SG, SG) - (W[:, None] + W[None, :]) / 2
        for a, c_ in zip(*np.nonzero(np.triu(T <= 1e-6, 1))):
            union(nP + nv + a, nP + nv + c_)
        if nP:
            D = geom.seg_seg_dist(cu.C, SG) - cu.r[:, None] - W[None, :] / 2
            M = np.full((nP, len(sg)), np.inf)
            np.minimum.at(M, cu.owner, D)
            for a, c_ in zip(*np.nonzero(M <= 1e-6)):
                union(a, nP + nv + c_)
        if nv:
            pts = np.column_stack([gv, gv])
            D = geom.seg_seg_dist(pts, SG) - vr[:, None] - W[None, :] / 2
            for a, c_ in zip(*np.nonzero(D <= 1e-6)):
                union(nP + a, nP + nv + c_)
    pos = {r: i for i, r in enumerate(P)}
    return np.array([find(pos[r]) for r in pad_rows], np.int64), np.array([find(nP + i) for i in range(nv)], np.int64)


def ground_plane_parts(b, cfg, report=None):
    """(plane problems, via problems, figures): one plane on PLANE_LAYER, GND, filled, one piece, no other net's zone there; every SMD
    ground pad has a via of its own within GND_VIA_REACH, greedily in (ref, pin) order, each via used once"""
    c = resolve(cfg, GROUND_PLANE_NAMES, 'ground_plane', report)
    L = _layer_code(c.PLANE_LAYER)
    side = 'bottom' if L == 1 else 'top'
    bad = []
    if b.copper_layers != c.COPPER_LAYERS:
        bad.append(f'{b.copper_layers} copper layers')
    gnd = nid(b, c.GND)
    # EVERY zone on the layer: exactly one, it is GND, it is filled and one piece; a zone of another net is a split plane
    bot = np.flatnonzero((b.z_layer == L) & ~b.z_keepout)       # a rule area (keepout) is not copper: it never counts as a plane or a split
    for zi in bot[b.z_net[bot] != gnd]:
        bad.append(f'{side} zone of {b.nets[b.z_net[zi]] or "no net"}: the {side} layer carries the ground plane only')
    bz = bot[b.z_net[bot] == gnd]
    pieces_n = None
    if not len(bz):
        bad.append(f'no {side} GND zone')
    else:
        if len(bz) > 1:
            bad.append(f'{len(bz)} {side} GND zones, not 1')
        for z in bz:
            if not b.z_filled[z]:
                bad.append(f'{side} zone not filled')
        pieces_n = int(sum((b.z_ring_hole[b.z_ring_off[z]:b.z_ring_off[z + 1]] == 0).sum() for z in bz if b.z_filled[z]))
        if pieces_n != 1:
            bad.append(f'{side} plane is {pieces_n} pieces, not 1')
    pt = pads(b)
    sel = [j for j in range(len(pt.keys)) if pt.net[j] == gnd and b.p_smd[pt.rows[j]]]
    sel.sort(key=lambda j: pt.keys[j])
    gv = np.column_stack([b.v_x, b.v_y])[b.v_net == gnd]
    tht = [r for r in range(len(b.p_net)) if b.p_net[r] == gnd and not b.p_smd[r]]       # a plated hole of the same net (a thermal via inside an exposed pad) is a via of its own
    if tht:
        gv = np.vstack([gv.reshape(-1, 2), np.column_stack([b.p_x[tht], b.p_y[tht]])])
    comp_pad, comp_via = _gnd_components(b, gnd, [pt.rows[j] for j in sel], gv, tht)
    used = np.zeros(len(gv), bool)
    nov = []
    for jj, j in enumerate(sel):
        r = pt.rows[j]
        d = np.hypot(gv[:, 0] - b.p_x[r], gv[:, 1] - b.p_y[r]) if len(gv) else np.zeros(0)
        d = np.where(used | (comp_via != comp_pad[jj]), np.inf, d)                     # its own: joined to the pad by copper (its own track, or lying in the pad)
        i = int(np.argmin(d)) if len(d) else -1
        if i >= 0 and d[i] <= c.GND_VIA_REACH:
            used[i] = True
        else:
            nov.append(f'{pt.keys[j][0]}.{pt.keys[j][1]}')
    vias = [f'{len(nov)} SMD ground pads without a via of their own: {nov[:6]}'] if nov else []
    fig = dict(layers=float(b.copper_layers), plane_pieces=float(pieces_n if pieces_n is not None else -1),
               gnd_pads=float(len(sel)), pads_without_via=float(len(nov)))
    return bad, vias, fig


def ground_plane(b, cfg, report=None):
    plane, vias, fig = ground_plane_parts(b, cfg, report)
    bad = plane + vias
    fig['violations'] = float(len(bad))
    ok_text = f'{int(fig["layers"])} layers, one plane, {int(fig["gnd_pads"])} GND pads each with its own via (a plated hole of the pad counts)'
    return Result(not bad, '; '.join(bad[:6]) or ok_text, fig)


# ----------------------------------------------------------------------------------------------------- bottom_hops
BOTTOM_HOPS_NAMES = (
    project('GND', 'net name', 'the ground net: its copper on the plane layer is the plane, not a hop'),
    project('PLANE_LAYER', "'F' | 'B' (or 0 | 1)", 'the layer whose signal copper is judged'),
    project('HOP_FENCES', 'list of (x0, y0, x1, y1), board frame mm', 'areas no hop may enter'),
    project('HOP_SENSITIVE', 'list of net-name prefixes', 'nets (and their pads) no hop may pass under'),
    project('HOP_KEEPOUT_PARTS', 'list of designators', 'parts whose courtyards no hop may lie under; those without a courtyard are skipped'),
    tunable('HOP_MAX', 3.0, 'mm', 'longest connected run of signal copper on the plane layer'),
    tunable('HOP_MAX_VIAS', 2, 'count', 'most vias at the ends of one run'),
    tunable('HOP_KEEPOUT_PAD', 0.0, 'mm', 'margin added around a keep-out part courtyard (and half the track width)'),
    tunable('HOP_JOIN_TOL', 0.01, 'mm', 'two segments of one net closer than this are one run'),
    tunable('HOP_VIA_TOL', 0.05, 'mm', 'a via this close to a run end belongs to the run'),
    tunable('HOP_SENSITIVE_CLEAR', 0.1, 'mm', 'extra clearance (beyond half the two widths) a hop keeps from a sensitive track or pad'),
)


def _runs(b, c):
    """connected runs of signal segments on the plane layer (same net, touching within HOP_JOIN_TOL: end to end, end on a segment's
    interior, crossing): list of (net name, length, vias at its ends, [keep-out parts it lies under]) plus segment rows and labels"""
    L = _layer_code(c.PLANE_LAYER)
    gnd = nid(b, c.GND)
    rows = np.flatnonzero((b.s_layer == L) & (b.s_net != gnd))
    n = len(rows)
    if not n:
        return [], rows, np.zeros(0, np.int32)
    S = segs(b)[rows]
    net = b.s_net[rows]
    E = np.vstack([S[:, :2], S[:, 2:]])
    tree = cKDTree(E)
    # two segments of one net are one run when they touch: end to end, an end on the INTERIOR of the other (a T), or crossing -
    # exact segment-to-segment distance under the join tolerance (it was end to end only: a hop built as two segments meeting at a T
    # was two short runs and passed)
    i, j = geom.within(S, S, c.HOP_JOIN_TOL)
    keep = (i < j) & (net[i] == net[j])
    joins = np.column_stack([i[keep], j[keep]]) if keep.any() else np.zeros((0, 2), np.int64)
    k, lab = geom.connected_components(n, joins)
    Ln = np.bincount(lab, weights=geom.seg_len(S), minlength=k)
    # vias at the ends of the run: same net, within HOP_VIA_TOL of any end of any segment of the run
    nv = np.zeros(k, np.int64)
    if len(b.v_idx):
        V = np.column_stack([b.v_x, b.v_y])
        d = cKDTree(V).sparse_distance_matrix(tree, c.HOP_VIA_TOL, output_type='ndarray')
        if len(d):
            vi, ei = d['i'], d['j']
            m = (d['v'] < c.HOP_VIA_TOL) & (b.v_net[vi] == net[ei % n])
            key = np.unique(lab[ei[m] % n].astype(np.int64) * len(V) + vi[m])
            nv = np.bincount(key // len(V), minlength=k)
    under = np.zeros((k, 0), bool)
    refs = sorted(r for r in c.HOP_KEEPOUT_PARTS if has_box(b, r))
    if refs:
        boxes = np.array([box(b, r) for r in refs])
        hit = geom.seg_in_box(S, boxes, pad=c.HOP_KEEPOUT_PAD + b.s_w[rows] / 2)
        under = np.zeros((k, len(refs)), bool)
        np.logical_or.at(under, lab, hit)
    runs = [(b.nets[net[np.flatnonzero(lab == r)[0]]], float(Ln[r]), int(nv[r]), [refs[j] for j in np.flatnonzero(under[r])])
            for r in range(k)]
    return runs, rows, lab


def _crossings(b, c):
    L = _layer_code(c.PLANE_LAYER)
    gnd = nid(b, c.GND)
    rows = np.flatnonzero((b.s_layer == L) & (b.s_net != gnd))
    if not len(rows):
        return []
    side = 'bottom' if L == 1 else 'top'
    S = segs(b)[rows]
    w = b.s_w[rows]
    bad = [[] for _ in rows]
    fz = np.array(list(c.HOP_FENCES), float).reshape(-1, 4)
    if len(fz):
        hit = geom.seg_in_box(S, fz, pad=w / 2)
        any_, first = _first_true(hit)
        for i in np.flatnonzero(any_):
            bad[i].append(f'{b.nets[b.s_net[rows[i]]]}: {side} segment inside an analog fence '
                          f'{tuple(round(float(v), 1) for v in fz[first[i]])}')
    sens = net_prefix(b, c.HOP_SENSITIVE)
    trows = np.flatnonzero((b.s_layer == 1 - L) & sens[b.s_net])
    if len(trows):
        T = segs(b)[trows]
        D = geom.seg_seg_dist(S, T)
        close = D < (w[:, None] + b.s_w[trows][None, :]) / 2 + c.HOP_SENSITIVE_CLEAR
        any_, first = _first_true(close)
        for i in np.flatnonzero(any_):
            bad[i].append(f'{b.nets[b.s_net[rows[i]]]}: {side} segment under {b.nets[b.s_net[trows[first[i]]]]} '
                          '(a hop under a sensitive net; bridge it on top)')
    pt = pads(b)
    prow = pt.rows[sens[pt.net]]
    pkeys = [pt.keys[j] for j in np.flatnonzero(sens[pt.net])]
    if len(prow):
        hit = geom.seg_in_box(S, pad_box(b, prow), pad=c.HOP_SENSITIVE_CLEAR + w / 2)
        any_, first = _first_true(hit)
        for i in np.flatnonzero(any_):
            k = pkeys[first[i]]
            bad[i].append(f'{b.nets[b.s_net[rows[i]]]}: {side} segment under pad {k[0]}.{k[1]} of {b.nets[b.p_net[prow[first[i]]]]}')
    return [m for per in bad for m in per]


def bottom_runs(b, cfg, report=None):
    """(runs, segment rows, run label per row): the connected runs of signal copper on the plane layer; a run is (net, length mm,
    vias at its ends, [keep-out parts it lies under])"""
    return _runs(b, resolve(cfg, BOTTOM_HOPS_NAMES, 'bottom_hops', report))


def bottom_crossings(b, cfg, report=None):
    """the findings of copper on the plane layer inside a fence or under a sensitive track or pad"""
    return _crossings(b, resolve(cfg, BOTTOM_HOPS_NAMES, 'bottom_hops', report))


def bottom_hops_parts(b, cfg, report=None):
    """(problems, figures): runs under a keep-out part or longer / with more vias than allowed, in run order, then the crossings
    (inside a fence, under a sensitive track or pad)"""
    c = resolve(cfg, BOTTOM_HOPS_NAMES, 'bottom_hops', report)
    runs, _, _ = _runs(b, c)
    side = 'bottom' if _layer_code(c.PLANE_LAYER) == 1 else 'top'
    bad = []
    for net, Ln, nv, under in runs:
        if under:
            bad.append(f'{net}: {side} copper under {under}')
        if Ln > c.HOP_MAX or nv > c.HOP_MAX_VIAS:
            bad.append(f'{net}: {side} run {Ln:.1f} mm, {nv} vias (limit {c.HOP_MAX} mm, {c.HOP_MAX_VIAS})')
    bad += _crossings(b, c)
    fig = dict(runs=float(len(runs)), max_run_mm=max([r[1] for r in runs], default=0.0),
               max_run_vias=float(max([r[2] for r in runs], default=0)))
    return bad, fig


def bottom_hops(b, cfg, report=None):
    bad, fig = bottom_hops_parts(b, cfg, report)
    fig['violations'] = float(len(bad))
    return Result(not bad, '; '.join(bad[:6]) or f'{int(fig["runs"])} runs on the plane layer, none too long, fenced or under a sensitive net', fig)


# ----------------------------------------------------------------------------------------------------- sensitive_nets
SENSITIVE_NETS_NAMES = (
    project('GND', 'net name', 'copper of this net never counts as a foreign track'),
    project('SENSITIVE_NETS', 'list of dicts', "one per net: 'net' (name), 'no_via' (default True), 'no_bottom' (default False: no copper on the "
            "other layer), 'max_length' (mm of top track, default None = no limit), 'gap' (mm, default None = no neighbour test)"),
)
_ENTRY_KEYS = ('net', 'no_via', 'no_bottom', 'max_length', 'gap')


@dataclasses.dataclass(frozen=True)
class Finding:
    """kind 'via' | 'bottom' | 'length' | 'beside'; net; value (length mm for 'length', the gap for 'beside'); other (the neighbouring net)"""
    kind: str
    net: str
    value: float = 0.0
    other: str = ''


def _entries(c):
    from .config import ConfigError
    out = []
    for e in c.SENSITIVE_NETS:
        bad = sorted(set(e) - set(_ENTRY_KEYS))
        if bad or 'net' not in e:
            raise ConfigError(f"sensitive_nets: an entry of SENSITIVE_NETS needs 'net' and may carry only {_ENTRY_KEYS}; got {sorted(e)}"
                              + (f' (unknown: {bad})' if bad else ''))
        out.append({**dict(no_via=True, no_bottom=False, max_length=None, gap=None), **e})
    return out


def sensitive_nets_parts(b, cfg, report=None):
    """(findings, figures): for each listed net in order a via, copper on the other layer, a length over its limit; then every top
    segment of a net with a gap that has another net's top track (the plane net excluded) nearer than gap + half the two widths"""
    c = resolve(cfg, SENSITIVE_NETS_NAMES, 'sensitive_nets', report)
    ents = _entries(c)
    out = []
    for e in ents:
        n = e['net']
        if e['no_via'] and (b.v_net == nid(b, n)).any():
            out.append(Finding('via', n))
        if e['no_bottom'] and ((b.s_net == nid(b, n)) & (b.s_layer == 1)).any():
            out.append(Finding('bottom', n))
        L = length_of(b, n)
        if e['max_length'] is not None and L > e['max_length']:
            out.append(Finding('length', n, L))
    gap_of = {nid(b, e['net']): e['gap'] for e in ents if e['gap'] is not None}
    hz = np.flatnonzero(np.isin(b.s_net, list(gap_of)) & (b.s_layer == 0)) if gap_of else np.zeros(0, np.int64)
    gnd = nid(b, c.GND)
    ot = np.flatnonzero((b.s_layer == 0) & (b.s_net != gnd))
    nclose = 0
    if len(hz) and len(ot):
        S = segs(b)
        step = 64
        for a in range(0, len(hz), step):
            ia = hz[a:a + step]
            D = geom.seg_seg_dist(S[ia], S[ot])
            g = np.array([gap_of[int(n)] for n in b.s_net[ia]])
            lim = g[:, None] + (b.s_w[ia][:, None] + b.s_w[ot][None, :]) / 2
            close = (D < lim) & (b.s_net[ia][:, None] != b.s_net[ot][None, :])
            any_, first = _first_true(close)
            for i in np.flatnonzero(any_):
                out.append(Finding('beside', b.nets[b.s_net[ia[i]]], float(g[i]), b.nets[b.s_net[ot[first[i]]]]))
                nclose += 1
    longest = max([length_of(b, e['net']) for e in ents], default=0.0)
    return out, dict(nets=float(len(ents)), longest_mm=longest, tracks_too_close=float(nclose))


def _finding_text(f):
    return {'via': lambda: f'{f.net}: a via', 'bottom': lambda: f'{f.net}: bottom copper', 'length': lambda: f'{f.net}: {f.value:.1f} mm of track',
            'beside': lambda: f'{f.net} track within {f.value:g} mm of {f.other} track'}[f.kind]()


def sensitive_nets(b, cfg, report=None):
    fnd, fig = sensitive_nets_parts(b, cfg, report)
    bad = [_finding_text(f) for f in fnd]
    fig['violations'] = float(len(bad))
    return Result(not bad, '; '.join(sorted(set(bad))[:6]) or f'{int(fig["nets"])} sensitive nets: no via, short, no track beside', fig)


# ----------------------------------------------------------------------------------------------------- pour_gap
POUR_GAP_NAMES = (
    project('GND', 'net name', 'the ground net whose top tracks and fills are measured'),
    project('POUR_NODES', 'list of net names', 'nodes judged: ground copper must keep POUR_KEEP_BACK from them'),
    project('POUR_KEEP_BACK', 'mm', 'the design keep-back distance'),
    tunable('POUR_INFO_NODES', (), 'list of net names', 'nodes measured and reported but not judged'),
)


def _node_copper(b, net):
    """top copper of one node as exact outlines: its F.Cu tracks and the pads that reach F.Cu"""
    n_id = nid(b, net)
    rows = np.flatnonzero((b.s_net == n_id) & (b.s_layer == 0))
    pt = pads(b)
    prow = pt.rows[(pt.net == n_id) & ((b.p_layer_mask[pt.rows] & 1) > 0)] if len(pt.rows) else np.zeros(0, np.int64)
    return geom.join(geom.track_copper(b, rows), geom.pad_copper(b, prow))


def _pour_gaps(b, c):
    gnd = nid(b, c.GND)
    gt = np.flatnonzero((b.s_net == gnd) & (b.s_layer == 0))
    zi = [z for z in range(len(b.z_layer)) if b.z_layer[z] == 0 and b.z_net[z] == gnd and b.z_filled[z] and not b.z_keepout[z]]
    out = []
    for net in tuple(c.POUR_NODES) + tuple(c.POUR_INFO_NODES):
        cu = _node_copper(b, net)
        if not len(cu.C):
            out.append((net, math.inf, math.inf))
            continue
        trk = math.inf
        if len(gt):
            G = segs(b)[gt]
            wg = b.s_w[gt] / 2
            for a in range(0, len(gt), 1024):
                D = geom.seg_seg_dist(cu.C, G[a:a + 1024]) - cu.r[:, None] - wg[None, a:a + 1024]
                trk = min(trk, float(np.maximum(D, 0.0).min()))
        pour = math.inf
        for z in zi:
            r0, r1 = b.z_ring_off[z], b.z_ring_off[z + 1]
            off = b.z_vert_off[r0:r1 + 1]
            pour = min(pour, float(cu.gap_to_fill(b.z_xy[off[0]:off[-1]], off - off[0], b.z_ring_hole[r0:r1]).min()))
        out.append((net, trk, pour))
    return out


def pour_gaps(b, cfg, report=None):
    """[(node net, gap to top GND tracks, gap to top GND pour fills)] for every POUR_NODES and POUR_INFO_NODES node: the exact copper-edge to
    copper-edge distance (tracks as capsules, pads by size and rotation), +inf when there is nothing to measure to. A pour is measured to
    the EDGES of its filled outline and hole rings, and is 0 where the node's copper lies on the fill (an even-odd, hole-aware test)."""
    return _pour_gaps(b, resolve(cfg, POUR_GAP_NAMES, 'pour_gap', report))


def pour_gap_parts(b, cfg, report=None):
    """(gaps, near): `gaps` as pour_gaps; `near` lists (node, 'track' | 'pour') for every judged node (POUR_NODES) whose ground track or pour is
    nearer than POUR_KEEP_BACK"""
    c = resolve(cfg, POUR_GAP_NAMES, 'pour_gap', report)
    gaps = _pour_gaps(b, c)
    near = []
    for net, g_trk, g_pour in gaps:
        if net not in c.POUR_NODES:
            continue                                           # reported, not judged (POUR_INFO_NODES)
        if g_trk < c.POUR_KEEP_BACK:
            near.append((net, 'track'))
        if g_pour < c.POUR_KEEP_BACK:
            near.append((net, 'pour'))
    return gaps, near


def pour_gap(b, cfg, report=None):
    c = resolve(cfg, POUR_GAP_NAMES, 'pour_gap', report)
    gaps, near = pour_gap_parts(b, cfg)
    bad = [f'{n}: ground {k} within {c.POUR_KEEP_BACK} mm' for n, k in near]
    fig = {f'gnd_track_gap_{n}_mm': trk for n, trk, _ in gaps}
    fig.update({f'pour_gap_{n}_mm': pour for n, _, pour in gaps})
    fig['violations'] = float(len(bad))
    return Result(not bad, '; '.join(bad[:6]) or f'no ground copper within {c.POUR_KEEP_BACK} mm of {", ".join(c.POUR_NODES)}', fig)


# ----------------------------------------------------------------------------------------------------- keepout_ring
KEEPOUT_RING_NAMES = (
    project('KEEPOUT_PARTS', 'list of designators', 'the parts (their courtyards) that sensitive copper keeps away from'),
    project('KEEPOUT_NETS', 'list of net-name prefixes', 'the sensitive nets'),
    project('KEEPOUT_EXEMPT_PARTS', 'list of designators', 'pads of these parts are not judged (the keep-out parts own block)'),
    project('KEEPOUT_DIST', 'mm', 'the design distance, measured from the copper\'s edge'),
)


def keepout_ring(b, cfg, report=None):
    """sensitive copper keeps KEEPOUT_DIST from the courtyards of KEEPOUT_PARTS, measured from the copper's EDGE: a track as a capsule (centre
    line less half its width), a pad by its size and rotation, to the courtyard box"""
    c = resolve(cfg, KEEPOUT_RING_NAMES, 'keepout_ring', report)
    gen = [box(b, r) for r in c.KEEPOUT_PARTS]
    near, dmin = [], math.inf
    sens = net_prefix(b, c.KEEPOUT_NETS)
    rows = np.flatnonzero((b.s_layer == 0) & sens[b.s_net])
    if len(rows):
        cu = geom.track_copper(b, rows)
        d = np.min([cu.gap_to_box(g) for g in gen], axis=0)
        dmin = min(dmin, float(d.min()))
        for i in np.flatnonzero(d < c.KEEPOUT_DIST):
            near.append(f'{b.nets[b.s_net[rows[i]]]} {d[i]:.1f} mm')
    pt = pads(b)
    js = [j for j in np.flatnonzero(sens[pt.net]) if pt.keys[j][0] not in c.KEEPOUT_EXEMPT_PARTS]
    if js:
        prow = pt.rows[js]
        cu = geom.pad_copper(b, prow)
        d = np.min([cu.gap_to_box(g) for g in gen], axis=0)
        dmin = min(dmin, float(d.min()))
        for i in np.flatnonzero(d < c.KEEPOUT_DIST):
            k = pt.keys[js[i]]
            near.append(f'{b.nets[b.p_net[prow[i]]]} pad {k[0]}.{k[1]} {d[i]:.1f} mm')
    return Result(not near, '; '.join(sorted(set(near))[:6]) or f'sensitive copper >= {c.KEEPOUT_DIST} mm from {"/".join(c.KEEPOUT_PARTS)}',
                  dict(min_distance_mm=dmin, violations=float(len(near))))


# ----------------------------------------------------------------------------------------------------- decoupling
DECOUPLING_NAMES = (
    project('DECOUPLING', 'list of (capacitor, ic, pin)', 'each capacitor must sit near the supply pin it decouples'),
    project('DECOUPLING_MAX', 'mm', 'the design distance, capacitor pad to IC pin'),
)


def decoup_dist(b, cap, ic, pin):
    """distance from the IC pin to the nearer pad of the capacitor that is on the pin's net (pad 1 when neither is)"""
    net = pad_net(b, ic, pin)
    ks = [k for k in ('1', '2') if pad_net(b, cap, k) == net] or ['1']
    return min(float(np.hypot(*(pad_c(b, cap, k) - pad_c(b, ic, pin)))) for k in ks)


def decoupling(b, cfg, report=None):
    c = resolve(cfg, DECOUPLING_NAMES, 'decoupling', report)
    bad, fig, figs = [], [], {}
    for cap, ic, pin in c.DECOUPLING:
        d = decoup_dist(b, cap, ic, pin)
        figs[f'{cap}>{ic}.{pin}'] = d
        fig.append(f'{cap}>{ic}.{pin} {d:.1f}')
        if d > c.DECOUPLING_MAX:
            bad.append(f'{cap} is {d:.1f} mm from {ic} pin {pin} (limit {c.DECOUPLING_MAX})')
    return Result(not bad, '; '.join(bad) or f'{len(c.DECOUPLING)} caps within {c.DECOUPLING_MAX} mm: ' + ', '.join(fig), figs)


# ----------------------------------------------------------------------------------------------------- blocks
BLOCK_NAMES = (
    project('BLOCK', 'dict ref -> block name', 'the block each part belongs to'),
    project('OUTLINE', 'dict block -> list of (x0, y0, x1, y1), frame mm', 'the rectangles of each block'),
    tunable('OUTLINE_STRAYS', (), 'list of designators', 'parts allowed outside their own block\'s rectangles (never inside another\'s)'),
    tunable('EDGE_BLOCK', None, 'block name or None', 'the block whose parts are in no outline (edge connectors), unless listed in BLOCK_OVERRIDE'),
    tunable('BLOCK_OVERRIDE', (), 'list of designators', 'parts of EDGE_BLOCK that are judged anyway'),
    tunable('SHARED_PARTS', {}, 'dict ref -> home block', 'a part that straddles two rectangles: held to its home block\'s outline, counted in no other'),
    tunable('SHARED_MARGIN', 0.0, 'mm', 'how far outside its home rectangle a shared part\'s origin may sit'),
)


def blocks_parts(b, cfg, report=None):
    """the block membership findings (list of text): each block's rectangles hold exactly its parts, named strays excepted"""
    c = resolve(cfg, BLOCK_NAMES, 'blocks', report)
    return outlines.membership_findings(b, c.BLOCK, c.OUTLINE, c.OUTLINE_STRAYS, c.EDGE_BLOCK, c.BLOCK_OVERRIDE, c.SHARED_PARTS, c.SHARED_MARGIN)


def blocks(b, cfg, report=None):
    bad = blocks_parts(b, cfg, report)
    c = resolve(cfg, BLOCK_NAMES, 'blocks')
    return Result(not bad, '; '.join(bad[:8]) or f'{len(c.OUTLINE)} outlines hold exactly their parts',
                  dict(outlines=float(len(c.OUTLINE)), violations=float(len(bad))))


def block_of_parts(b, cfg, report=None):
    """the block of every footprint: its configured block, else the first outline holding its origin, else None"""
    c = resolve(cfg, BLOCK_NAMES[:2], 'blocks', report)
    return outlines.block_of_parts(b, c.BLOCK, c.OUTLINE)


# ----------------------------------------------------------------------------------------------------- test_points
TEST_POINTS_NAMES = (
    project('BLOCK', 'dict ref -> block name', 'as blocks'),
    project('OUTLINE', 'dict block -> list of rectangles', 'as blocks (a part with no block of its own takes the outline that holds it)'),
    project('TEST_BLOCKS', 'list of block names', 'each of these has a test point'),
    project('TP_NETS', 'dict ref -> net name', 'each test point is on its net'),
    project('TP_PREFIX', 'designator prefix', 'what a test point\'s designator starts with'),
    project('TP_PIN', 'pin number', 'the pad of a test point that carries its net'),
)


def test_points_parts(b, cfg, report=None):
    """(block findings, net findings): 'block X has no test point' for each of TEST_BLOCKS without one (sorted), and 'TPn: missing or not on NET'"""
    c = resolve(cfg, TEST_POINTS_NAMES, 'test_points', report)
    refs = list(b.fp_ref)
    bof = outlines.block_of_parts(b, c.BLOCK, c.OUTLINE)
    pt = pads(b)
    have = {bof[i] for i, r in enumerate(refs) if r.startswith(c.TP_PREFIX) and (r, c.TP_PIN) in pt.lookup}
    blk = [f'block {x} has no test point' for x in sorted(set(c.TEST_BLOCKS) - have)]
    net = []
    for r, n in c.TP_NETS.items():
        if (r, c.TP_PIN) not in pt.lookup or pad_net(b, r, c.TP_PIN) != n:
            net.append(f'{r}: missing or not on {n}')
    return blk, net


def test_points(b, cfg, report=None):
    blk, net = test_points_parts(b, cfg, report)
    bad = blk + net
    return Result(not bad, '; '.join(bad[:8]) or 'every listed block has a test point, each on its net', dict(violations=float(len(bad))))


# ----------------------------------------------------------------------------------------------------- designators
SILK_REQUIRED_NAMES = (
    project('SILK_REQUIRED_PREFIXES', 'tuple of designator prefixes, or None', 'parts whose designator must be on silk (None: every part); any other may move it to F.Fab'),
    project('DESIGNATOR_MIN_H', 'mm', 'the least text height a silk designator may have'),
)


def silk_required_parts(b, cfg, report=None):
    """([(ref, anchor)] designators not on silk at DESIGNATOR_MIN_H or more and not (for a part that need not carry one) on F.Fab either, number of
    part designators on F.Fab instead, number of parts)"""
    c = resolve(cfg, SILK_REQUIRED_NAMES, 'designators', report)
    refs = list(b.fp_ref)
    refrow = {int(f): i for i, f in enumerate(b.r_fp)}
    bad, noff = [], 0
    required = c.SILK_REQUIRED_PREFIXES
    for i, r in enumerate(refs):
        k = refrow.get(i)
        on = k is not None and b.r_on_silk[k] and b.r_h[k] >= c.DESIGNATOR_MIN_H
        if on:
            continue
        anchor = required is None or r.rstrip('0123456789') in required
        if not anchor and k is not None and int(b.r_layer[k]) == 2:      # 2: board.R_LAYERS['F.Fab']
            noff += 1
            continue
        bad.append((r, anchor))
    return bad, noff, len(refs)


LEGIBILITY_NAMES = (
    project('BLOCK', 'dict ref -> block name', 'foreign_labels: the part\'s own block'),
    project('OUTLINE', 'dict block -> list of rectangles', 'foreign_labels: the other blocks\' rectangles'),
    project('DESIGNATOR_GAP_MIN', 'mm', 'two designator boxes closer than this are a finding'),
    project('DESIGNATOR_DIST_MAX', 'mm', 'a designator is at most this far from the nearest pad of its own part'),
    tunable('DESIGNATOR_ADVANCE', 0.95, 'fraction of the text height', 'designator box length per character'),
    tunable('DESIGNATOR_INK_H', 1.2, 'fraction of the text height', 'designator box width across the text'),
    tunable('DESIGNATOR_GAP_ONE_LABEL', 0.6, 'mm', 'two designators on one baseline closer than this read as one label'),
    tunable('DESIGNATOR_FOREIGN_WAIVED', {}, 'dict ref -> block', 'designators accepted inside that other block\'s outline'),
    tunable('EDGE_BLOCK', None, 'block name or None', 'foreign_labels: its parts are not judged'),
    tunable('BLOCK_OVERRIDE', (), 'list of designators', 'foreign_labels: parts judged though in EDGE_BLOCK'),
    tunable('SHARED_PARTS', {}, 'dict ref -> home block', 'foreign_labels: shared parts are not judged'),
)


def _box_corners(x, y, length, height, ang):
    """corners (4,2) of a text box of `length` x `height` centred on (x, y), turned by ang degrees (a box is symmetric under 180 degrees,
    so the sign of the angle, which a y flip of the frame reverses, does not matter)"""
    cs, sn = np.cos(np.radians(ang)), np.sin(np.radians(ang))
    u, v = np.array([cs, sn]) * length / 2, np.array([-sn, cs]) * height / 2
    ctr = np.array([x, y])
    return np.array([ctr + u + v, ctr - u + v, ctr - u - v, ctr + u - v])


def _convex_gap(P, Q):
    """edge-to-edge distance of two convex polygons (n,2), (m,2): 0 when they overlap or touch"""
    for poly in (P, Q):                                       # separating axis: a gap along an edge normal of either
        for k in range(len(poly)):
            e = poly[(k + 1) % len(poly)] - poly[k]
            n = np.array([-e[1], e[0]])
            n = n / (np.hypot(*n) or 1.0)
            a, b = P @ n, Q @ n
            if a.max() < b.min() or b.max() < a.min():
                break
        else:
            continue
        break
    else:
        return 0.0

    def pt_seg(p, poly):
        a, b = poly, np.roll(poly, -1, axis=0)
        d = b - a
        t = np.clip(((p - a) * d).sum(1) / np.maximum((d * d).sum(1), 1e-18), 0, 1)
        return np.hypot(*(p - (a + t[:, None] * d)).T).min()
    return min(min(pt_seg(p, Q) for p in P), min(pt_seg(q, P) for q in Q))


def _label_boxes(b, c):
    refs = list(b.fp_ref)
    return {refs[int(b.r_fp[k])]: _box_corners(b.r_x[k], b.r_y[k], len(refs[int(b.r_fp[k])]) * c.DESIGNATOR_ADVANCE * b.r_h[k],
                                              c.DESIGNATOR_INK_H * b.r_h[k], b.r_ang[k])
            for k in range(len(b.r_fp)) if b.r_on_silk[k] and int(b.r_layer[k]) == 0}


def designator_findings(b, cfg, report=None):
    """the visible silk designators judged as boxes: ([(refA, refB, gap)] pairs closer than DESIGNATOR_GAP_MIN, [(ref, other ref)] a box over
    another part's pad, [(ref, distance)] a box farther than DESIGNATOR_DIST_MAX from every pad of its own part, number of designators
    judged). The box is the text's height by len(designator) x DESIGNATOR_ADVANCE x height; text is taken as centred on its position."""
    c = resolve(cfg, LEGIBILITY_NAMES, 'designators', report)
    refs = list(b.fp_ref)
    box = _label_boxes(b, c)
    names = sorted(box)
    close = []
    for i, a in enumerate(names):
        A = box[a]
        for cn in names[i + 1:]:
            Bx = box[cn]
            if A[:, 0].min() - c.DESIGNATOR_GAP_MIN > Bx[:, 0].max() or Bx[:, 0].min() - c.DESIGNATOR_GAP_MIN > A[:, 0].max() \
                    or A[:, 1].min() - c.DESIGNATOR_GAP_MIN > Bx[:, 1].max() or Bx[:, 1].min() - c.DESIGNATOR_GAP_MIN > A[:, 1].max():
                continue
            g = _convex_gap(A, Bx)
            if g < c.DESIGNATOR_GAP_MIN:
                close.append((a, cn, round(float(g), 2)))
    over, far = [], []
    owner = b.p_fp.astype(int)
    for ref, B in box.items():
        fi = refs.index(ref)
        near = np.flatnonzero((b.p_bx1 >= B[:, 0].min() - 1) & (b.p_bx0 <= B[:, 0].max() + 1)
                              & (b.p_by1 >= B[:, 1].min() - 1) & (b.p_by0 <= B[:, 1].max() + 1) & (owner != fi))
        hit = sorted({refs[owner[j]] for j in near if _convex_gap(B, np.array([[b.p_bx0[j], b.p_by0[j]], [b.p_bx1[j], b.p_by0[j]],
                                                                                [b.p_bx1[j], b.p_by1[j]], [b.p_bx0[j], b.p_by1[j]]])) <= 0})
        over += [(ref, h) for h in hit]
        mine = np.flatnonzero(owner == fi)
        if len(mine):
            d = min(_convex_gap(B, np.array([[b.p_bx0[j], b.p_by0[j]], [b.p_bx1[j], b.p_by0[j]], [b.p_bx1[j], b.p_by1[j]],
                                             [b.p_bx0[j], b.p_by1[j]]])) for j in mine)
            if d > c.DESIGNATOR_DIST_MAX:
                far.append((ref, round(float(d), 2)))
    return close, over, far, len(box)


def shares_baseline(ya0, ya1, yb0, yb1):
    """two boxes are on one baseline: their vertical extents overlap by more than half of the smaller (the one-label rule; pcbkit.labels spaces labels by it too)"""
    return min(ya1, yb1) - max(ya0, yb0) > 0.5 * min(ya1 - ya0, yb1 - yb0)


def one_label_pairs(b, cfg, report=None):
    """[(refA, refB, gap)] pairs of visible designators that READ AS ONE LABEL: on a common baseline (the vertical extents of the two boxes overlap
    by more than half of the smaller one) and the horizontal gap under DESIGNATOR_GAP_ONE_LABEL (touching or overlapping included)."""
    c = resolve(cfg, LEGIBILITY_NAMES, 'designators', report)
    box = _label_boxes(b, c)
    lim = c.DESIGNATOR_GAP_ONE_LABEL
    names = sorted(box)
    out = []
    for i, a in enumerate(names):
        A = box[a]
        for cn in names[i + 1:]:
            Bx = box[cn]
            dx = max(0.0, max(Bx[:, 0].min() - A[:, 0].max(), A[:, 0].min() - Bx[:, 0].max()))
            if dx < lim and shares_baseline(A[:, 1].min(), A[:, 1].max(), Bx[:, 1].min(), Bx[:, 1].max()):
                out.append((a, cn, round(float(dx), 2)))
    return out


def foreign_labels(b, cfg, report=None):
    """[(ref, block it sits in)] visible designators whose centre lies inside another block's outline than the one holding their part (a part
    with no block of its own, a shared part and the edge block's parts are not judged)"""
    c = resolve(cfg, LEGIBILITY_NAMES, 'designators', report)
    box = _label_boxes(b, c)
    out = []
    for ref, B in box.items():
        home = c.BLOCK.get(ref)
        if home is None or home == c.EDGE_BLOCK or ref in c.SHARED_PARTS or ref in c.BLOCK_OVERRIDE:
            continue
        ctr = B.mean(axis=0, keepdims=True)
        for blk, rects in c.OUTLINE.items():
            if blk != home and outlines.in_rects(ctr, rects)[0] and c.DESIGNATOR_FOREIGN_WAIVED.get(ref) != blk:
                out.append((ref, blk))
    return sorted(out)


# the two-way nearest test (ported unchanged from the AFE-2 label job's stackcheck.py)
TWO_WAY_NAMES = (
    project('SILK_REQUIRED_PREFIXES', 'tuple of designator prefixes', 'the anchor kinds: a part is of the longest matching prefix, else a passive; an anchor is compared only with parts and labels of its own kind'),
    tunable('READ_MARGIN', 0.15, 'mm', "its own part must be nearer to a label than any other part, and its own label nearer to a part than any other label, by this"),
    tunable('DESIGNATOR_ADVANCE', 0.95, 'fraction of the text height', 'designator box length per character'),
    tunable('DESIGNATOR_INK_H', 1.2, 'fraction of the text height', 'designator box width across the text'),
    tunable('LABEL_TEXTS', {}, 'dict text -> designator', "board silk texts that are part of a part's label (a BNC's function text): the nearer of its designator and these counts"),
    EPS_NAME,
)


def _kind(ref, prefixes):
    best = ''
    for p in prefixes or ():
        if ref.startswith(p) and len(p) > len(best):
            best = p
    return best or 'P'


def _gap(a, c):
    return math.hypot(max(c[0] - a[2], 0.0, a[0] - c[2]), max(c[1] - a[3], 0.0, a[1] - c[3]))


def two_way_test(b, cfg, report=None):
    """the two-way nearest test on every part that has a label. A part's SOLID is its F.Fab body box and each pad box; a designator's box is
    DESIGNATOR_ADVANCE x height per character by DESIGNATOR_INK_H x height (turned with the text); a LABEL_TEXTS text is pcbnew's box.
    1. FROM THE LABEL: for every label of part P, d(label, P) + READ_MARGIN <= d(label, Q) for every other part Q.
    2. FROM THE PART: for every part P with a label, d(P, its label) + READ_MARGIN <= d(P, any other label).
    A distance passes when own + READ_MARGIN <= other + EPS (the package's one tolerance, config.EPS_NAME). An anchor is compared only against parts / labels of its own kind in both steps; a passive against all. Needs the fields of board.read_board
    (fp_fab_*, t_x0..; board.require raises naming one that was not read). Returns {ref: (own distance, step 1 failure, step 2 failure)};
    a failure is (margin shortfall as other - own, other part, own, other) or None."""
    c = resolve(cfg, TWO_WAY_NAMES, 'designators', report)
    require(b, 'fp_fab_x0', 'fp_fab_y0', 'fp_fab_x1', 'fp_fab_y1', 't_x0', 't_y0', 't_x1', 't_y1')
    refs = list(b.fp_ref)
    solid = {}
    for i, r in enumerate(refs):
        items = []
        if not np.isnan(b.fp_fab_x0[i]):
            items.append((float(b.fp_fab_x0[i]), float(b.fp_fab_y0[i]), float(b.fp_fab_x1[i]), float(b.fp_fab_y1[i])))
        for j in np.flatnonzero(b.p_fp == i):
            items.append((float(b.p_bx0[j]), float(b.p_by0[j]), float(b.p_bx1[j]), float(b.p_by1[j])))
        solid[r] = items
    labels = {}
    for k in range(len(b.r_fp)):
        r = refs[int(b.r_fp[k])]
        if b.r_on_silk[k] and int(b.r_layer[k]) == 0:
            L, W = len(r) * c.DESIGNATOR_ADVANCE * float(b.r_h[k]), c.DESIGNATOR_INK_H * float(b.r_h[k])
            x, y = float(b.r_x[k]), float(b.r_y[k])
            labels.setdefault(r, []).append((x - L / 2, y - W / 2, x + L / 2, y + W / 2) if round(float(b.r_ang[k])) % 180 == 0
                                            else (x - W / 2, y - L / 2, x + W / 2, y + L / 2))
    for k, t in enumerate(b.t_text):
        if t in c.LABEL_TEXTS and c.LABEL_TEXTS[t] in solid:
            labels.setdefault(c.LABEL_TEXTS[t], []).append((float(b.t_x0[k]), float(b.t_y0[k]), float(b.t_x1[k]), float(b.t_y1[k])))
    return two_way_core(solid, labels, c.SILK_REQUIRED_PREFIXES, c.READ_MARGIN, c.EPS)


def too_near(d_own, d_other, margin, eps):
    """the one predicate of the two-way test: something at d_other reads as nearer than, or as near as, what is at d_own, because it is not farther by `margin` (less eps of rounding).
    Both steps of the test, the label validation and the placer's search call it."""
    return d_own + margin > d_other + eps


def two_way_all(solid, labels, prefixes, margin, eps):
    """the two-way nearest test on boxes, every offender: `solid` {ref: [boxes]} (a part's body box and its pad boxes), `labels` {ref: [boxes]} (a part's label boxes; a BNC's
    designator and function text are two boxes of one label), `prefixes` the anchor kinds (see _kind). Returns {ref: (own distance, [step 1 failures], [step 2 failures])} for every
    part that has a label; a step 1 failure is (shortfall, part, own, other) of a part nearer to the label than its own, a step 2 failure (shortfall, label owner, own, other) of
    another label nearer to the part than its own. Each list is in the order the candidates were met."""
    m = margin
    kinds = {r: _kind(r, prefixes) for r in set(solid) | set(labels)}

    def dsolid(p, bx):
        return min(_gap(bx, it) for it in solid[p]) if solid.get(p) else 9e9
    out = {}
    for p in sorted(labels):
        own = min(dsolid(p, bx) for bx in labels[p])
        s1 = []
        for q in solid:
            if q == p or (kinds[p] != 'P' and kinds[q] != kinds[p]):
                continue
            dq = min(_gap(bx, it) for bx in labels[p] for it in solid[q]) if solid[q] else 9e9
            dp = min(_gap(bx, it) for bx in labels[p] for it in solid[p]) if solid[p] else 9e9        # (a part with nothing solid: never nearest)
            if too_near(dp, dq, m, eps):
                s1.append((dq - dp, q, dp, dq))
        s2 = []
        for o, bxs in labels.items():
            if o == p or (kinds[p] != 'P' and kinds[o] != kinds[p]):
                continue
            do = min(dsolid(p, bx) for bx in bxs)
            if too_near(own, do, m, eps):
                s2.append((do - own, o, own, do))
        out[p] = (own, s1, s2)
    return out


def two_way_core(solid, labels, prefixes, margin, eps):
    """the nearest offender of each step, see two_way_all: {ref: (own distance, step 1 failure or None, step 2 failure or None)}. `two_way_test` reads the boxes off a board."""
    return {p: (own, min(s1, key=lambda f: f[0]) if s1 else None, min(s2, key=lambda f: f[0]) if s2 else None) for p, (own, s1, s2) in two_way_all(solid, labels, prefixes, margin, eps).items()}


def designators(b, cfg, report=None):
    """every designator that must be on silk is; every other is on silk or on F.Fab; and every silk label reads without doubt (the two-way test)"""
    bad, noff, n = silk_required_parts(b, cfg, report)
    c = resolve(cfg, SILK_REQUIRED_NAMES, 'designators')
    out = [f'{r}: designator not on silk at {c.DESIGNATOR_MIN_H:g} mm or more' + ('' if anchor else ', and not on F.Fab either') for r, anchor in bad]
    tw = two_way_test(b, cfg, report)
    for p, (own, s1, s2) in sorted(tw.items()):
        if s1 or s2:
            out.append(f'{p}: ' + ('; '.join(x for x in (
                s1 and f'from its label, {s1[1]} is at {s1[3]:.2f} mm and its own part at {s1[2]:.2f}',
                s2 and f"from the part, the label of {s2[1]} is at {s2[3]:.2f} mm and its own at {s2[2]:.2f}") if x)))
    return Result(not out, '; '.join(out[:8]) or f'{n} designators, {len(tw)} silk labels pass the two-way test', dict(designators=float(n), labels=float(len(tw)), on_fab=float(noff), violations=float(len(out))))


# ----------------------------------------------------------------------------------------------------- track geometry
TRACK_GEOMETRY_NAMES = (
    tunable('TRACK_ANGLE_STEP', 45.0, 'degrees', 'every segment runs along a multiple of this angle (45: 0, 45, 90, 135 degrees)'),
    tunable('TRACK_ANGLE_TOL', 0.5, 'degrees', 'how far a segment, or a segment entering a pad, may be from the angle it should have'),
    tunable('TRACK_MIN_LEG', 0.6, 'mm', 'the shortest straight run between two bends of a track (a collinear chain is one run); shorter is a jog'),
    tunable('TRACK_FINE_PITCH', 0.65, 'mm', 'a leg that ends on a pad of a part whose pads are at this pitch or finer is a breakout and may be short'),
    tunable('TRACK_MAX_TURN', 180.0, 'degrees', 'a run between its two ends (pads, vias, junctions) changes its heading by this much or more, net, within any TRACK_TURN_WINDOW of its length: a hook or U-turn (a dog-leg is 90, a lane change 0)'),
    tunable('TRACK_STAIR_MAX', 1.5, 'mm', 'a Z of two opposite 90 degree bends with a middle leg shorter than this, where a single 45 degree leg would fit (both legs either side at least half of it), is a stair'),
    tunable('TRACK_KINK_OFFSET', 0.6, 'mm', 'a V kink or bump: bends adding up to 180 degrees in all (45 down, 90 up, 45 level) that come back to the heading they left within this lateral offset of the line they left'),
    tunable('TRACK_TURN_WINDOW', 3.0, 'mm', 'the stretch of a run over which its turning is added up'),
    tunable('TRACK_DETOUR_RATIO', 1.5, 'x', 'a run is no longer than this times the shortest octilinear (0/45/90) path between its two ends'),
    tunable('TRACK_DETOUR_MIN_LEN', 1.0, 'mm', 'runs shorter than this are not judged for detour (a 0.3 mm run has no room to be one)'),
    tunable('TRACK_SPUR_MIN', 0.6, 'mm', 'a spur that ends on the body of another track of its net (a T) is at least this long'),
    tunable('TRACK_SPUR_CLEAR', 0.6, 'mm', 'and its junction is at least this far from a bend, another junction or a pad on the trunk (those read as blobs and bars)'),
    tunable('TRACK_NET_WIDTHS', {}, '{net: mm}', 'the width rule of each net (key "*" for the rest): no segment is wider; a net with no entry and no "*" is not judged'),
    tunable('TRACK_WIDTH_TOL', 0.001, 'mm', 'how far over its width rule a segment may be'),
    tunable('TRACK_BREAKOUT_REACH', 0.0, 'mm', 'a short leg is also a breakout when one of its ends is within this of the centre of a same-net pad of a fine-pitch part (the fan-out out of a 0.5 mm part, where the first leg out of the pad is itself short); 0 limits the exemption to the leg that ends on the pad'),
    tunable('TRACK_ENTRY_EDGE_TOL', 0.001, 'mm', 'how far a track entering a pad may overhang the span of the pad edge it enters (it enters through the edge, not across a corner)'),
    tunable('TRACK_OVERLAP_TOL', 0.001, 'mm', 'a track overlaps a pad when its copper is further than this over the pad edge'),
    tunable('GEOMETRY_EXCEPTIONS', [], '[(rule, net, pad_or_ref, reason)]', 'named exceptions: each waives exactly one finding of that rule on that net at that pad (REF.PIN, REF for any pin of it, or (x, y) within 0.5 mm of the finding for a finding at no pad); an entry that matches no finding, or more than one, fails the check'),
)


def _pad_arrays(b):
    """EVERY pad of the board, not rules.pads()'s one per (part, pin): an exposed pad is several pads of one number (a rectangle, via-in-pad squares) and unnumbered pads share the empty pin, and a track
    can lie over, or enter, any of them"""
    r = np.arange(len(b.p_x))
    return dict(rows=r, cx=b.p_x[r], cy=b.p_y[r], sx=b.p_sx[r], sy=b.p_sy[r], rot=b.p_rot[r], shape=b.p_shape[r], fp=b.p_fp[r], net=b.p_net[r], mask=b.p_layer_mask[r])


def _in_pads(P, pa, tol=0.0):
    """(len(P), npads) bool: the point is in the pad's copper (the rotated rectangle of its size, or the ellipse of a circle or an oval)"""
    a = np.radians(pa['rot'])
    dx = P[:, 0:1] - pa['cx'][None, :]
    dy = P[:, 1:2] - pa['cy'][None, :]
    u = dx * np.cos(a)[None, :] + dy * np.sin(a)[None, :]
    v = -dx * np.sin(a)[None, :] + dy * np.cos(a)[None, :]
    hx, hy = pa['sx'][None, :] / 2 + tol, pa['sy'][None, :] / 2 + tol
    rect = (np.abs(u) <= hx) & (np.abs(v) <= hy)
    ell = (u / np.maximum(hx, 1e-9)) ** 2 + (v / np.maximum(hy, 1e-9)) ** 2 <= 1.0
    return np.where(((pa['shape'] == 0) | (pa['shape'] == 2))[None, :], ell, rect)


def _fp_pitch(b):
    """{footprint index: the smallest distance between two of its pad centres}: its pad pitch (a one-pad part has none)"""
    out = {}
    rows = np.arange(len(b.p_x))
    for f in np.unique(b.p_fp[rows]) if len(rows) else []:
        m = b.p_fp[rows] == f
        P = np.column_stack([b.p_x[rows][m], b.p_y[rows][m]])
        if len(P) >= 2:
            d = np.hypot(P[:, None, 0] - P[None, :, 0], P[:, None, 1] - P[None, :, 1])
            d[d < 1e-6] = np.inf
            out[int(f)] = float(d.min())
    return out


def _dev(angle, step):
    m = angle % step
    return min(m, step - m)


def _geometry_findings(b, c):
    """[(kind, text, x, y)] findings of the track geometry rule, kinds: 'arc' (a curved track), 'angle' (a segment off the angle step), 'jog' (a straight run shorter than
    TRACK_MIN_LEG between bends, unless it breaks out of a fine-pitch pad), 'entry' (the segment into a pad is not perpendicular to the edge it enters, or enters across a corner), 'over_pad' (a track
    crosses the pads of a part it does not end on). Positions are board-frame mm."""
    S = segs(b)
    n = len(S)
    out = []
    if len(b.a_idx):
        for i in range(len(b.a_idx)):
            out.append(('arc', 'a curved track on %s' % b.nets[b.a_net[i]], float(b.a_xm[i]), float(b.a_ym[i])))
    if not n:
        return out
    L = geom.seg_len(S)
    ang = np.degrees(np.arctan2(S[:, 3] - S[:, 1], S[:, 2] - S[:, 0]))
    pa = _pad_arrays(b)
    ends = np.vstack([S[:, :2], S[:, 2:]])
    in_end = _in_pads(ends, pa) if len(pa['rows']) else np.zeros((2 * n, 0), bool)

    def name(i):
        return '%s %s' % ('F' if b.s_layer[i] == 0 else 'B', b.nets[b.s_net[i]])
    for i in range(n):
        if L[i] > 1e-6 and _dev(ang[i], c.TRACK_ANGLE_STEP) > c.TRACK_ANGLE_TOL:
            out.append(('angle', '%s segment %.2f mm at %.1f degrees' % (name(i), L[i], ang[i] % 180), float((S[i, 0] + S[i, 2]) / 2), float((S[i, 1] + S[i, 3]) / 2)))
    # legs: collinear chains of two-segment joints, joined at bends
    key = lambda i, e: (int(b.s_layer[i]), int(b.s_net[i]), int(round(S[i, 2 * e] * 1000)), int(round(S[i, 2 * e + 1] * 1000)))
    at = {}
    for i in range(n):
        if L[i] > 1e-6:
            for e in (0, 1):
                at.setdefault(key(i, e), []).append((i, e))
    parent = list(range(n))
    cparent = list(range(n))                                           # the runs: segments joined at every joint of exactly two, whatever the angle

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def cfind(x):
        while cparent[x] != x:
            cparent[x] = cparent[cparent[x]]
            x = cparent[x]
        return x
    bends = []
    via_xy = np.column_stack([b.v_x, b.v_y]) if len(b.v_x) else np.zeros((0, 2))
    for k, lst in at.items():
        if len(lst) != 2 or lst[0][0] == lst[1][0]:
            continue
        i, ei = lst[0]
        j, ej = lst[1]
        p = np.array([[S[i, 2 * ei], S[i, 2 * ei + 1]]])
        if len(pa['rows']) and (_in_pads(p, pa)[0] & (pa['net'] == b.s_net[i])).any():
            continue                                               # a joint on a pad of the net is a junction, not a bend
        if len(via_xy) and (np.hypot(via_xy[:, 0] - p[0, 0], via_xy[:, 1] - p[0, 1]) <= b.v_dia / 2 + 1e-3).any():
            continue
        cparent[cfind(i)] = cfind(j)
        if _dev(ang[i] - ang[j], 180.0) <= c.TRACK_ANGLE_TOL:
            parent[find(i)] = find(j)
        else:
            bends.append((i, j, p[0]))
    glen, gsegs = {}, {}
    for i in range(n):
        if L[i] > 1e-6:
            r = find(i)
            glen[r] = glen.get(r, 0.0) + float(L[i])
            gsegs.setdefault(r, []).append(i)
    pitch = _fp_pitch(b)
    flagged = set()
    for i, j, p in bends:
        for s in (i, j):
            g = find(s)
            if g in flagged or glen[g] >= c.TRACK_MIN_LEG - 1e-9:
                continue
            cnt = {}
            for q in gsegs[g]:
                for e in (0, 1):
                    kk = key(q, e)
                    cnt[kk] = cnt.get(kk, 0) + 1
            far = [kk for kk, v in cnt.items() if v == 1 and not (abs(kk[2] / 1000 - p[0]) < 2e-3 and abs(kk[3] / 1000 - p[1]) < 2e-3)]
            fine = False
            if far and len(pa['rows']):
                q = np.array([[far[0][2] / 1000, far[0][3] / 1000]])
                hit = np.flatnonzero(_in_pads(q, pa)[0] & (pa['net'] == b.s_net[s]))
                fine = any(pitch.get(int(pa['fp'][h]), math.inf) <= c.TRACK_FINE_PITCH + 1e-9 for h in hit)
            if not fine and c.TRACK_BREAKOUT_REACH > 0 and len(pa['rows']):
                E = np.array([[S[q, 2 * e], S[q, 2 * e + 1]] for q in gsegs[g] for e in (0, 1)])
                for h in np.flatnonzero((pa['net'] == b.s_net[s]) & (np.array([pitch.get(int(f), math.inf) for f in pa['fp']]) <= c.TRACK_FINE_PITCH + 1e-9)):
                    if (np.hypot(E[:, 0] - pa['cx'][h], E[:, 1] - pa['cy'][h]) <= c.TRACK_BREAKOUT_REACH).any():
                        fine = True
                        break
            if fine:
                continue
            flagged.add(g)
            out.append(('jog', '%s leg %.2f mm between bends (needs %.2f)' % (name(s), glen[g], c.TRACK_MIN_LEG), float(p[0]), float(p[1])))
    # the segment into a pad is perpendicular to the pad edge it enters (along either pad axis) and enters through that edge, not across a corner
    if len(pa['rows']):
        for e_i in range(2 * n):
            i = e_i % n
            if L[i] <= 1e-6:
                continue
            for h in np.flatnonzero(in_end[e_i] & (pa['net'] == b.s_net[i]) & ((pa['mask'] & (1 << int(b.s_layer[i]))) > 0)):
                if pa['shape'][h] == 0:
                    continue                                       # a round pad has no edge to enter perpendicular to
                a_pad = math.radians(pa['rot'][h])
                dx, dy = ends[e_i, 0] - pa['cx'][h], ends[e_i, 1] - pa['cy'][h]
                u = dx * math.cos(a_pad) + dy * math.sin(a_pad)         # the end in the pad's own frame
                v = -dx * math.sin(a_pad) + dy * math.cos(a_pad)
                along_x = _dev(ang[i] - pa['rot'][h], 180.0) <= c.TRACK_ANGLE_TOL
                along_y = _dev(ang[i] - pa['rot'][h] - 90.0, 180.0) <= c.TRACK_ANGLE_TOL
                half = b.s_w[i] / 2
                if along_x:
                    through = abs(v) + half <= pa['sy'][h] / 2 + c.TRACK_ENTRY_EDGE_TOL          # moving along x: it meets the edge x = +-sx/2 across its span in y
                elif along_y:
                    through = abs(u) + half <= pa['sx'][h] / 2 + c.TRACK_ENTRY_EDGE_TOL
                else:
                    through = False
                if not through:
                    ref = b.fp_ref[pa['fp'][h]]
                    out.append(('entry', '%s enters %s.%s %s' % (name(i), ref, b.p_pin[pa['rows'][h]],
                                'at %.1f degrees, not along a pad axis (%.1f or %.1f)' % (ang[i] % 180, pa['rot'][h] % 180, (pa['rot'][h] + 90) % 180) if not (along_x or along_y)
                                else 'across the corner, not through the edge'), float(ends[e_i, 0]), float(ends[e_i, 1])))
        # a track over the pads of a part its run does not end on (even of its own net): the run is the segments joined at joints of two, so a track that starts on a pad and turns is still on it
        run_fps = {}
        for i in range(n):
            run_fps.setdefault(cfind(i), set()).update(int(pa['fp'][q]) for q in np.flatnonzero(in_end[i] | in_end[n + i]))
        cu = geom.pad_copper(b, pa['rows'])
        for a0 in range(0, n, 256):
            blk = np.arange(a0, min(n, a0 + 256))
            D = geom.seg_seg_dist(cu.C, S[blk]) - cu.r[:, None] - (b.s_w[blk] / 2)[None, :]
            M = np.full((len(pa['rows']), len(blk)), np.inf)
            np.minimum.at(M, cu.owner, D)
            for h, jj in zip(*np.nonzero((M < -c.TRACK_OVERLAP_TOL) & ((pa['mask'][:, None] & (1 << b.s_layer[blk][None, :].astype(int))) > 0))):
                i = int(blk[jj])
                if L[i] <= 1e-6:
                    continue
                mine = run_fps[cfind(i)]
                if int(pa['fp'][h]) in mine:
                    continue
                out.append(('over_pad', '%s runs over %s.%s' % (name(i), b.fp_ref[pa['fp'][h]], b.p_pin[pa['rows'][h]]), float((S[i, 0] + S[i, 2]) / 2), float((S[i, 1] + S[i, 3]) / 2)))
    return out


def _match(finding, entry):
    kind, text, x, y = finding
    rule, net, where, _ = entry
    t = text.split()
    if kind != rule or len(t) < 2 or t[1].lstrip('/') != str(net).lstrip('/'):
        return False
    if isinstance(where, (tuple, list)):
        return math.hypot(x - where[0], y - where[1]) <= 0.5
    return any(w == where or (w.startswith(where + '.') and '.' not in where) for w in t)


def _octile(dx, dy):
    dx, dy = abs(dx), abs(dy)
    return max(dx, dy) + (math.sqrt(2) - 1) * min(dx, dy)


def _split_at_taps(b, S, L):
    """the segments with every body cut at the places another track of the same net and layer ends on it (a T): (S2, net, layer, width, orig) with `orig` the index of the segment each piece came from.
    An end whose round cap overlaps the other track's copper (a hair off its centre line) counts as a tap and is moved onto the centre line, so the two are one joint"""
    S = S.copy()
    n = len(S)
    cuts = {i: [] for i in range(n)}
    snaps = {}
    for i in range(n):
        if L[i] <= 1e-6:
            continue
        for e in (0, 1):
            p = S[i, 2 * e:2 * e + 2]
            joint = any(j != i and b.s_net[j] == b.s_net[i] and b.s_layer[j] == b.s_layer[i] and L[j] > 1e-6 and
                        min(math.hypot(p[0] - S[j, 0], p[1] - S[j, 1]), math.hypot(p[0] - S[j, 2], p[1] - S[j, 3])) < 0.01 for j in range(n))
            for j in range(n):
                if joint:
                    break                                    # the end already meets another track's end: a joint, never a tap
                if j == i or b.s_net[j] != b.s_net[i] or b.s_layer[j] != b.s_layer[i] or L[j] <= 1e-6:
                    continue
                d = geom.seg_seg_dist(S[j:j + 1], np.array([[p[0], p[1], p[0], p[1]]]))[0, 0]
                if d > b.s_w[i] / 2 + b.s_w[j] / 2 + 1e-9:
                    continue
                if min(math.hypot(p[0] - S[j, 0], p[1] - S[j, 1]), math.hypot(p[0] - S[j, 2], p[1] - S[j, 3])) < 0.01:
                    continue                                 # at an end of j: a joint, not a body tap
                u = ((p[0] - S[j, 0]) * (S[j, 2] - S[j, 0]) + (p[1] - S[j, 1]) * (S[j, 3] - S[j, 1])) / (L[j] ** 2)
                if u <= 0.0 or u >= 1.0:
                    continue                                 # past either end of j: near its end cap, not on its body (snapping there would collapse a short stub onto j's end)
                cuts[j].append(u)
                if d > 0.005:
                    snaps[(i, e)] = (S[j, 0] + u * (S[j, 2] - S[j, 0]), S[j, 1] + u * (S[j, 3] - S[j, 1]))
                break
    for (i, e), q in snaps.items():
        S[i, 2 * e], S[i, 2 * e + 1] = q
    rows = []
    for i in range(n):
        if L[i] <= 1e-6:
            continue
        us = sorted({round(u, 6) for u in cuts[i]})
        us = [0.0] + [u for u in us if 0.0 < u < 1.0] + [1.0]
        for a, c in zip(us, us[1:]):
            rows.append((S[i, 0] + a * (S[i, 2] - S[i, 0]), S[i, 1] + a * (S[i, 3] - S[i, 1]), S[i, 0] + c * (S[i, 2] - S[i, 0]), S[i, 1] + c * (S[i, 3] - S[i, 1]), i))
    A = np.array(rows, float).reshape(-1, 5)
    o = A[:, 4].astype(int)
    return A[:, :4], b.s_net[o], b.s_layer[o], b.s_w[o], o


def _route_findings(b, c):
    """[(kind, text, x, y)]: 'detour' (a run between its two ends turns more than TRACK_MAX_TURN in total, or is longer than TRACK_DETOUR_RATIO times its shortest octilinear path),
    'dangling' (a track end that touches no pad, via or track of its net), 'tspur' (a spur that ends on the body of another track of its net, a T, is shorter than TRACK_SPUR_MIN, joins
    at other than 90 or 45 degrees, or has its junction within TRACK_SPUR_CLEAR of a bend, another junction or a pad on the trunk), 'wide' (a segment wider than its net's width rule).
    A run is the pieces of track joined at joints of exactly two that are on no pad or via, the tracks cut at every T; its ends are the two end points that are not such a joint."""
    S0 = segs(b)
    out = []
    if not len(S0):
        return out
    L0 = geom.seg_len(S0)
    r_all = np.arange(len(b.p_x))                            # every pad: a part may have several pads of one number (an exposed pad with via-in-pad squares)
    pa = dict(rows=r_all, cx=b.p_x, cy=b.p_y, sx=b.p_sx, sy=b.p_sy, rot=b.p_rot, shape=b.p_shape, fp=b.p_fp, net=b.p_net, mask=b.p_layer_mask)
    rules_w = dict(c.TRACK_NET_WIDTHS)
    name0 = lambda i: '%s %s' % ('F' if b.s_layer[i] == 0 else 'B', b.nets[b.s_net[i]])
    if rules_w:
        for i in range(len(S0)):
            nm = b.nets[b.s_net[i]]
            lim = rules_w.get(nm, rules_w.get(nm.lstrip('/'), rules_w.get('*')))
            if lim is not None and b.s_w[i] > lim + c.TRACK_WIDTH_TOL:
                out.append(('wide', '%s segment %.2f mm wide, the net\'s rule is %.2f mm (%.2f mm long)' % (name0(i), b.s_w[i], lim, L0[i]), float((S0[i, 0] + S0[i, 2]) / 2), float((S0[i, 1] + S0[i, 3]) / 2)))
    S, nets, lays, wid, orig = _split_at_taps(b, S0, L0)
    n = len(S)
    L = geom.seg_len(S)
    name = lambda i: '%s %s' % ('F' if lays[i] == 0 else 'B', b.nets[nets[i]])
    key = lambda i, e: (int(lays[i]), int(nets[i]), int(round(S[i, 2 * e] * 1000)), int(round(S[i, 2 * e + 1] * 1000)))
    at = {}
    for i in range(n):
        for e in (0, 1):
            at.setdefault(key(i, e), []).append((i, e))
    via_xy = np.column_stack([b.v_x, b.v_y]) if len(b.v_x) else np.zeros((0, 2))

    def pad_dist(p, h):
        """distance from the point to the pad copper h (a rotated rectangle, or a circle or oval as a capsule), 0 inside"""
        a = math.radians(pa['rot'][h])
        dx, dy = p[0] - pa['cx'][h], p[1] - pa['cy'][h]
        u = dx * math.cos(a) + dy * math.sin(a)
        v = -dx * math.sin(a) + dy * math.cos(a)
        hx, hy = pa['sx'][h] / 2, pa['sy'][h] / 2
        if pa['shape'][h] in (0, 2):
            r = min(hx, hy)
            ax = max(hx - r, 0.0), max(hy - r, 0.0)
            return max(math.hypot(max(abs(u) - ax[0], 0.0), max(abs(v) - ax[1], 0.0)) - r, 0.0)
        return math.hypot(max(abs(u) - hx, 0.0), max(abs(v) - hy, 0.0))

    def on_pad(p, net, layer, w=0.0):                        # the track's round end cap (a disc of width w) overlaps copper of a pad of its net: nothing beyond the cap
        for h in np.flatnonzero((pa['net'] == net) & ((pa['mask'] & (1 << layer)) > 0)):
            if abs(pa['cx'][h] - p[0]) < 5 and abs(pa['cy'][h] - p[1]) < 5 and pad_dist(p, h) <= w / 2 + 1e-9:
                return True
        return False

    def on_via(p, net, w=0.0):
        return bool(len(via_xy) and (np.hypot(via_xy[:, 0] - p[0], via_xy[:, 1] - p[1]) <= b.v_dia / 2 + w / 2 + 1e-9)[b.v_net == net].any())
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for k, lst in at.items():
        if len(lst) != 2 or lst[0][0] == lst[1][0]:
            continue
        p = (k[2] / 1000, k[3] / 1000)
        if on_pad(p, k[1], k[0], wid[lst[0][0]]) or on_via(p, k[1], wid[lst[0][0]]):
            continue
        parent[find(lst[0][0])] = find(lst[1][0])
    def path_of(members):
        """(pts, first end, second end) of a group of pieces joined as one path, or None when it is a loop or branches"""
        cnt = {}
        for i in members:
            for e in (0, 1):
                cnt.setdefault(key(i, e), []).append((i, e))
        ends = [(k, v[0]) for k, v in cnt.items() if len(v) == 1]
        if len(ends) != 2:
            return None
        (k0, (i0, e0)), (k1, (i1, e1)) = ends
        order, cur, e_in, done = [], i0, e0, set()
        while cur is not None and cur not in done:
            done.add(cur)
            order.append((cur, 1 - e_in))
            nxt = [t for t in cnt[key(cur, 1 - e_in)] if t[0] != cur]
            cur, e_in = (nxt[0] if nxt else (None, None))
        pts = [(S[i, 2 * (1 - eo)], S[i, 2 * (1 - eo) + 1]) for i, eo in order] + [(S[order[-1][0], 2 * order[-1][1]], S[order[-1][0], 2 * order[-1][1] + 1])]
        return pts, (k0, i0, e0), (k1, i1, e1)

    def stairs(pts):
        """[(middle leg, leg before, leg after, x, y)]: three consecutive legs of the run where the two bends are 90 degrees (within TRACK_ANGLE_TOL) in opposite senses, the middle leg is shorter than
        TRACK_STAIR_MAX, and both legs either side are at least half of it (so one 45 degree leg could take the step). Collinear pieces are one leg"""
        legs = []                                            # (heading degrees, length, start point)
        for j in range(len(pts) - 1):
            dx, dy = pts[j + 1][0] - pts[j][0], pts[j + 1][1] - pts[j][1]
            ln = math.hypot(dx, dy)
            if ln < 1e-9:
                continue
            h = math.degrees(math.atan2(dy, dx))
            if legs and abs((h - legs[-1][0] + 180.0) % 360.0 - 180.0) < c.TRACK_ANGLE_TOL:
                legs[-1] = (legs[-1][0], legs[-1][1] + ln, legs[-1][2])
            else:
                legs.append((h, ln, pts[j]))
        res = []
        for a, m, d in zip(legs, legs[1:], legs[2:]):
            t1 = (m[0] - a[0] + 180.0) % 360.0 - 180.0
            t2 = (d[0] - m[0] + 180.0) % 360.0 - 180.0
            if abs(abs(t1) - 90.0) <= c.TRACK_ANGLE_TOL and abs(abs(t2) - 90.0) <= c.TRACK_ANGLE_TOL and t1 * t2 < 0 \
                    and m[1] < c.TRACK_STAIR_MAX - 1e-9 and a[1] >= m[1] / 2 - 1e-9 and d[1] >= m[1] / 2 - 1e-9:
                res.append((m[1], a[1], d[1], m[2][0], m[2][1]))
        return res

    def worst_turn(pts):
        """the worst stretch of TRACK_TURN_WINDOW, (kind, bend points) or None: a 'hook' when the heading changes by TRACK_MAX_TURN or more net there, a 'V kink' when the bends add up to 180 degrees in all and
        the track comes back to its heading within TRACK_KINK_OFFSET of the line it left"""
        vecs = [(pts[j + 1][0] - pts[j][0], pts[j + 1][1] - pts[j][1]) for j in range(len(pts) - 1)]
        along = [0.0]
        for v in vecs:
            along.append(along[-1] + math.hypot(*v))
        bends = []                                           # (distance along, signed bend, point, heading before)
        for q, (u, v) in enumerate(zip(vecs, vecs[1:]), 1):
            ang = math.degrees(math.atan2(u[0] * v[1] - u[1] * v[0], u[0] * v[0] + u[1] * v[1]))
            bends.append((along[q], ang, pts[q], u))
        best = None
        for q0 in range(len(bends)):
            sel = [t for t in bends[q0:] if t[0] <= bends[q0][0] + c.TRACK_TURN_WINDOW + 1e-9]
            for q1 in range(len(sel)):
                win = sel[:q1 + 1]
                net = sum(t[1] for t in win)
                tot = sum(abs(t[1]) for t in win)
                at_ = [t[2] for t in win]
                if abs(net) >= c.TRACK_MAX_TURN - c.TRACK_ANGLE_TOL:
                    if best is None or abs(net) > best[2]:
                        best = ('hook', at_, abs(net))
                elif tot >= 180.0 - c.TRACK_ANGLE_TOL and abs(net) < 45.0:
                    u0 = win[0][3]
                    d = (win[-1][2][0] - win[0][2][0], win[-1][2][1] - win[0][2][1])
                    off = abs(u0[0] * d[1] - u0[1] * d[0]) / max(math.hypot(*u0), 1e-9)
                    if off < c.TRACK_KINK_OFFSET and (best is None or best[0] != 'hook'):
                        best = ('V kink', at_, tot)
        return best

    runs = {}
    for i in range(n):
        runs.setdefault(find(i), []).append(i)
    runlen = {}
    for members in runs.values():
        got = path_of(members)
        if got is None:
            continue                                         # a loop, or a joint of three or more: not a path
        pts, (k0, i0, e0), (k1, i1, e1) = got
        net, layer = k0[1], k0[0]
        length = float(sum(L[i] for i in members))
        short = _octile(pts[-1][0] - pts[0][0], pts[-1][1] - pts[0][1])
        if length >= c.TRACK_DETOUR_MIN_LEN and length > c.TRACK_DETOUR_RATIO * short + 1e-6:
            mid = pts[len(pts) // 2]
            out.append(('detour', '%s run of %.2f mm is %.1f times its %.2f mm shortest path' % (name(i0), length, length / max(short, 1e-9), short), float(mid[0]), float(mid[1])))
        for st in stairs(pts):
            out.append(('stair', '%s Z of %.2f mm between two opposite 90 degree bends where a 45 degree leg would do (the legs either side are %.2f and %.2f mm)' % (name(i0), st[0], st[1], st[2]), float(st[3]), float(st[4])))
        runlen[find(i0)] = length
        for k, i, eo in ((k0, i0, e0), (k1, i1, e1)):
            p = (k[2] / 1000, k[3] / 1000)
            if on_pad(p, net, layer, wid[i]) or on_via(p, net, wid[i]):
                continue
            if len(at[k]) < 2:
                for j0 in range(len(S0)):                        # its round end cap overlapping the copper of another track of the net (a tap a hair off the other track's centre line)
                    if j0 == orig[i] or L0[j0] <= 1e-6 or b.s_net[j0] != net or b.s_layer[j0] != layer:
                        continue
                    if geom.seg_seg_dist(S0[j0:j0 + 1], np.array([[p[0], p[1], p[0], p[1]]]))[0, 0] <= wid[i] / 2 + b.s_w[j0] / 2 + 1e-9:
                        break
                else:
                    out.append(('dangling', '%s track end touches no pad, via or track of its net' % name(i), float(p[0]), float(p[1])))
    def reach_along(piece):
        """the distance from the end `piece` = (i, e) rests on, along its track, to the first place that is not a straight-through joint of two collinear pieces"""
        i, e = piece
        dist = float(L[i])
        cur, ef = i, 1 - e
        for _ in range(200):
            k = key(cur, ef)
            p = (k[2] / 1000, k[3] / 1000)
            here = at[k]
            if len(here) != 2 or on_pad(p, k[1], k[0], wid[cur]) or on_via(p, k[1], wid[cur]):
                break
            oi, oe = [t for t in here if t[0] != cur][0] if any(t[0] != cur for t in here) else (None, None)
            if oi is None:
                break
            u = (S[cur, 2 * ef] - S[cur, 2 * (1 - ef)], S[cur, 2 * ef + 1] - S[cur, 2 * (1 - ef) + 1])
            v = (S[oi, 2 * (1 - oe)] - S[oi, 2 * oe], S[oi, 2 * (1 - oe) + 1] - S[oi, 2 * oe + 1])
            cosang = (u[0] * v[0] + u[1] * v[1]) / max(math.hypot(*u) * math.hypot(*v), 1e-12)
            if cosang < math.cos(math.radians(c.TRACK_ANGLE_TOL)):
                break
            dist += float(L[oi])
            cur, ef = oi, 1 - oe
        return dist

    # junctions (three or more pieces at a point on no pad or via): the two collinear pieces are the trunk, any other is a spur
    juncs = {}
    for k, lst in at.items():
        p = (k[2] / 1000, k[3] / 1000)
        if len(lst) >= 3 and not (on_pad(p, k[1], k[0], wid[lst[0][0]]) or on_via(p, k[1], wid[lst[0][0]])):
            juncs[k] = lst
    for k, lst in juncs.items():
        p = (k[2] / 1000, k[3] / 1000)
        dirs = []
        for i, e in lst:
            v = (S[i, 2 * (1 - e)] - S[i, 2 * e], S[i, 2 * (1 - e) + 1] - S[i, 2 * e + 1])
            dirs.append((v[0] / max(L[i], 1e-9), v[1] / max(L[i], 1e-9)))
        trunk = None
        for a in range(len(lst)):
            for bq in range(a + 1, len(lst)):
                if dirs[a][0] * dirs[bq][0] + dirs[a][1] * dirs[bq][1] < -math.cos(math.radians(c.TRACK_ANGLE_TOL)):
                    trunk = (a, bq)
        nm = name(lst[0][0])
        if trunk is None:
            out.append(('tspur', '%s junction at a bend of the trunk (three tracks meet where it turns)' % nm, float(p[0]), float(p[1])))
            continue
        nd = min(reach_along(lst[trunk[0]]), reach_along(lst[trunk[1]]))          # along the trunk to its first real bend, junction, pad, via or end (collinear pieces are one track)
        for idx, (i, e) in enumerate(lst):
            if idx in trunk:
                continue
            why = []
            ln = runlen.get(find(i), L[i])
            if ln < c.TRACK_SPUR_MIN - 1e-9:
                why.append('%.2f mm long (needs %.2f)' % (ln, c.TRACK_SPUR_MIN))
            td = dirs[trunk[0]]
            a = abs(math.degrees(math.atan2(dirs[idx][0] * td[1] - dirs[idx][1] * td[0], dirs[idx][0] * td[0] + dirs[idx][1] * td[1]))) % 180.0
            if min(abs(a - 90.0), abs(a - 45.0), abs(a - 135.0)) > c.TRACK_ANGLE_TOL:
                why.append('joins at %.0f degrees, not 90 or 45' % a)
            if nd < c.TRACK_SPUR_CLEAR - 1e-9:
                why.append('its junction is %.2f mm from a bend, another junction or a pad on the trunk (needs %.2f)' % (nd, c.TRACK_SPUR_CLEAR))
            if why:
                out.append(('tspur', '%s T spur %s' % (nm, '; '.join(why)), float(p[0]), float(p[1])))
    # the turning of a trunk is judged straight through its T junctions (the two collinear pieces of a junction are one track), so a V on a trunk is a detour in its own right
    parent2 = list(parent)

    def find2(x):
        while parent2[x] != x:
            parent2[x] = parent2[parent2[x]]
            x = parent2[x]
        return x
    for k, lst in juncs.items():
        dirs = []
        for i, e in lst:
            v = (S[i, 2 * (1 - e)] - S[i, 2 * e], S[i, 2 * (1 - e) + 1] - S[i, 2 * e + 1])
            dirs.append((v[0] / max(L[i], 1e-9), v[1] / max(L[i], 1e-9)))
        for a_ in range(len(lst)):
            for b_ in range(a_ + 1, len(lst)):
                if dirs[a_][0] * dirs[b_][0] + dirs[a_][1] * dirs[b_][1] < -math.cos(math.radians(c.TRACK_ANGLE_TOL)):
                    parent2[find2(lst[a_][0])] = find2(lst[b_][0])
    groups = {}
    for i in range(n):
        groups.setdefault(find2(i), []).append(i)
    for members in groups.values():
        got = path_of(members)
        if got is None:
            continue
        pts, (k0, i0, _), _ = got
        w = worst_turn(pts)
        if w:
            kind, at_, amount = w
            out.append(('detour', '%s run has a %s: it turns %.0f degrees within %.1f mm' % (name(i0), kind, amount, c.TRACK_TURN_WINDOW), float(np.mean([q[0] for q in at_])), float(np.mean([q[1] for q in at_]))))
    seen, uniq = set(), []
    for f in out:
        k = (f[0], f[1], round(f[2], 3), round(f[3], 3))
        if k not in seen:
            seen.add(k)
            uniq.append(f)
    return uniq


def track_geometry_parts(b, cfg, report=None):
    """[(kind, text, x, y)] findings of the track geometry (see _geometry_findings: arc, angle, jog, entry, over_pad), less those waived by GEOMETRY_EXCEPTIONS, plus a 'stale_exception' finding for
    every entry that matches no finding or more than one, so an exception that no longer applies cannot stay in the configuration. `parts.waived` is the list of (entry, finding) waived."""
    from .config import ConfigError
    c = resolve(cfg, TRACK_GEOMETRY_NAMES, 'track_geometry', report)
    found = _geometry_findings(b, c) + _route_findings(b, c)
    ex = list(c.GEOMETRY_EXCEPTIONS)
    for e in ex:
        if len(e) != 4 or not str(e[3]).strip():
            raise ConfigError('GEOMETRY_EXCEPTIONS entries are (rule, net, pad_or_ref, reason) with a reason; got %r' % (e,))
    waived, gone = [], set()
    out = list(found)
    for e in ex:
        hit = [f for f in found if _match(f, e)]
        if len(hit) != 1:
            out.append(('stale_exception', '%s %s %s matches %d findings, not exactly one (%s)' % (e[0], e[1], e[2], len(hit), e[3]), 0.0, 0.0))
            continue
        gone.add(id(hit[0]))
        waived.append((e, hit[0]))
    out = [f for f in out if id(f) not in gone]
    return WaivedList(out, waived)


class WaivedList(list):
    def __init__(self, items, waived):
        super().__init__(items)
        self.waived = waived


def track_geometry(b, cfg, report=None):
    parts = track_geometry_parts(b, cfg, report)
    kinds = ('arc', 'angle', 'jog', 'entry', 'over_pad', 'detour', 'dangling', 'tspur', 'wide', 'stale_exception')
    fig = {f'{k}': float(sum(1 for p in parts if p[0] == k)) for k in kinds}
    fig['segments'] = float(len(b.s_idx))
    fig['violations'] = float(len(parts))
    fig['waived'] = float(len(parts.waived))
    bad = [f'{p[0]}: {p[1]} at ({p[2]:.2f}, {p[3]:.2f})' for p in parts]
    waived = f', {len(parts.waived)} findings waived by named exceptions' if parts.waived else ''
    return Result(not parts, '; '.join(bad[:6]) or f'{len(b.s_idx)} segments: on the angle step, no jogs, straight into pads, over no foreign pad{waived}', fig)


# ----------------------------------------------------------------------------------------------------- fill quality
FILL_QUALITY_NAMES = (
    project('GND', 'net name', 'the net of the pours measured'),
    tunable('FILL_LAYERS', ('F', 'B'), 'layer letters', 'the copper layers whose pour of GND is measured'),
    tunable('FILL_MIN_WIDTH', {'F': 1.0, 'B': 0.5}, 'mm per layer, or one mm for all', 'no strip, finger or tooth of the pour is narrower than this (the top for its looks, the plane for slivers only)'),
    tunable('FILL_DEAD_END_WIDTH', 1.6, 'mm', 'a part of the pour narrower than this that touches other copper at one end only is a dead-end finger'),
    tunable('FILL_LENGTH_FACTOR', 2.0, 'x half the width', 'a narrow part is a finger or a tooth only when it is longer than this times half the width limit (a shorter one is the rounding of a corner)'),
    tunable('FILL_RASTER', 40.0, 'pixels per mm', 'the resolution the pour is measured at'),
    tunable('FILL_MIN_AREA', 0.02, 'mm2', 'narrow parts smaller than this are ignored'),
    tunable('FILL_ROUGH_LAYERS', ('F',), 'layer letters', 'the layers whose pour edge must not be a row of clearance arcs (two or more pads or vias in a row, of any net, that the edge hugs); one alone may show its arc'),
    tunable('FILL_ROUGH_TOL', 0.15, 'mm', 'an item hugs the pour edge when pour lies within the zone clearance plus this of it'),
    tunable('FILL_ROUGH_LINK', 2.0, 'mm', 'hugging items closer than this (copper to copper) are a row'),
    tunable('FILL_SHELL_PREFIXES', (), 'designator prefixes', 'the connectors (J: the BNC shells and the Due headers) whose through-hole GND pins are never carved out of the top pour: each has pour round it (FILL_SHELL_MIN)'),
    tunable('FILL_GNDPAD_VIA_GAP', 0.05, 'mm', 'a GND via whose annulus is within this of the pad edge is at the edge (no visible stub)'),
    tunable('FILL_GNDPAD_STUB', 0.05, 'mm', 'a pad in the pour whose track to a via of its own lies bare for more than this is a stub (the via belongs at the pad edge, or the track under the pour)'),
    tunable('FILL_GNDPAD_TIE', 0.6, 'mm', 'or the pad is tied by a track whose visible part is at most this long to another pad of its part that has a plated hole or a via in it (an exposed pad)'),
    tunable('FILL_GNDPAD_MIN', 0.2, 'fraction', 'every SMD GND pad of the top layer touches the pour (this part of its ring, from the zone clearance out 0.6 mm further, is pour: a thermal relief) or has its own via touching its edge with no track between them'),
    tunable('FILL_SHELL_EXCEPTIONS', [], '[(ref, pin, reason)]', 'named exceptions: this connector GND pin stays on the bottom plane (a reason is required); each must match exactly one shell finding, or it is a stale_exception finding and the check fails'),
    tunable('FILL_GNDPAD_EXCEPTIONS', [], '[(ref, pin, reason)]', 'named exceptions: this SMD GND pad is neither in the pour nor given a via at its edge (a reason is required); each must match exactly one gndpad finding or it is a stale_exception'),
    tunable('FILL_SHELL_MIN', 0.3, 'fraction', 'the part of the ring from the zone clearance out to 0.6 mm further that is pour, at least, round such a pin'),
    tunable('FILL_THERMAL_LAYERS', ('F',), 'layer letters', 'the layers whose zone must connect SMD GND pads through thermal reliefs'),
    tunable('FILL_SOLID_LAYERS', ('B',), 'layer letters', 'the layers whose zone must connect pads solid (a plane)'),
)
THERMAL, SOLID = 1, 2            # pcbnew's ZONE_CONNECTION_THERMAL and ZONE_CONNECTION_FULL


def _has_hole(b, gnd, j):
    """a plated hole or a GND via lies in the pad j"""
    def inside(x, y):
        return b.p_bx0[j] <= x <= b.p_bx1[j] and b.p_by0[j] <= y <= b.p_by1[j]
    return any(b.p_net[m] == gnd and not b.p_smd[m] and inside(b.p_x[m], b.p_y[m]) for m in range(len(b.p_net))) or any(b.v_net[m] == gnd and inside(b.v_x[m], b.v_y[m]) for m in range(len(b.v_x)))


def _visible_stub(b, gnd, h, r_fill, step=0.05):
    """the length (mm) of top-layer GND track on the chain that runs from SMD pad h to a GND via that is not covered by the pour: pieces end to end (a joint is within 0.01 mm), from a piece with an end inside
    the pad to the first via; each sample of the centre line outside the pad and the via is bare when the pour raster has no pour there. 0 when the pad has no track to a via"""
    segs_ = [k for k in range(len(b.s_x0)) if b.s_net[k] == gnd and b.s_layer[k] == 0]
    if not segs_:
        return 0.0
    ends = {k: ((b.s_x0[k], b.s_y0[k]), (b.s_x1[k], b.s_y1[k])) for k in segs_}

    def in_pad(pt, tol):
        return b.p_bx0[h] - tol <= pt[0] <= b.p_bx1[h] + tol and b.p_by0[h] - tol <= pt[1] <= b.p_by1[h] + tol

    def in_via(pt):
        return any(b.v_net[v] == gnd and math.hypot(pt[0] - b.v_x[v], pt[1] - b.v_y[v]) <= b.v_dia[v] / 2 + 1e-6 for v in range(len(b.v_x)))
    start = [k for k in segs_ if any(in_pad(e, b.s_w[k] / 2) for e in ends[k])]
    best = 0.0
    for k0 in start:
        k, pt = k0, (ends[k0][1] if in_pad(ends[k0][0], b.s_w[k0] / 2) else ends[k0][0])
        pt = ends[k0][0] if pt is ends[k0][1] else ends[k0][1]                      # the end inside the pad, where the walk starts
        seen, bare, reached = [], 0.0, False
        for _ in range(8):
            seen.append(k)
            (xa, ya), (xb, yb) = ends[k]
            if math.hypot(xb - pt[0], yb - pt[1]) < math.hypot(xa - pt[0], ya - pt[1]):
                (xa, ya), (xb, yb) = (xb, yb), (xa, ya)                             # walked from the end nearer `pt`
            ln = math.hypot(xb - xa, yb - ya)
            n = max(int(ln / step), 1)
            for i in range(n):
                t = (i + 0.5) / n
                x, y = xa + t * (xb - xa), ya + t * (yb - ya)
                if in_via((x, y)):
                    reached = True                                                  # the first via on the way: the pad's own
                    break
                if in_pad((x, y), 0.0):
                    continue
                col = int((x - r_fill.x0) * r_fill.ppmm); row = int((r_fill.y1 - y) * r_fill.ppmm)
                if not (0 <= row < r_fill.mask.shape[0] and 0 <= col < r_fill.mask.shape[1]) or not r_fill.mask[row, col]:
                    bare += ln / n
            if reached:
                break
            pt = (xb, yb)
            nxt = [q for q in segs_ if q not in seen and any(math.hypot(e[0] - pt[0], e[1] - pt[1]) < 0.01 for e in ends[q])]
            if len(nxt) != 1:
                break
            k = nxt[0]
        if reached:
            best = max(best, bare)
    return best


def _tied_to_holed_pad(b, gnd, h, reach):
    """the SMD GND pad h is tied by a GND track, visible for at most `reach` mm between the two pads, to another GND pad of its part that has a plated hole or a GND via in it"""
    def box_dist(i, j):
        dx = max(b.p_bx0[i] - b.p_bx1[j], b.p_bx0[j] - b.p_bx1[i], 0.0)
        dy = max(b.p_by0[i] - b.p_by1[j], b.p_by0[j] - b.p_by1[i], 0.0)
        return math.hypot(dx, dy)

    def inside(i, x, y, tol):
        return b.p_bx0[i] - tol <= x <= b.p_bx1[i] + tol and b.p_by0[i] - tol <= y <= b.p_by1[i] + tol
    for k in range(len(b.s_x0)):
        if b.s_net[k] != gnd or b.s_layer[k] != 0:
            continue
        ends = ((b.s_x0[k], b.s_y0[k]), (b.s_x1[k], b.s_y1[k]))
        for (ea, eb) in (ends, ends[::-1]):
            if not inside(h, ea[0], ea[1], b.s_w[k] / 2):
                continue
            for j in range(len(b.p_net)):
                if j == h or b.p_net[j] != gnd or b.p_fp[j] != b.p_fp[h] or not (b.p_layer_mask[j] & 1) or not inside(j, eb[0], eb[1], b.s_w[k] / 2) or box_dist(h, j) > reach:
                    continue
                if _has_hole(b, gnd, j):
                    return True
    return False


def fill_quality_parts(b, cfg, report=None):
    """[(kind, text, x, y)] findings: 'narrow' (a part of the pour narrower than FILL_MIN_WIDTH, and longer than the rounding of a corner), 'dead_end' (a finger narrower than
    FILL_DEAD_END_WIDTH touching other copper at one end only), 'rough' (a row of clearance arcs on a FILL_ROUGH_LAYERS layer), 'thermal' (a zone on a FILL_THERMAL_LAYERS layer does not use thermal reliefs on its SMD GND pads), 'solid'
    (a zone on a FILL_SOLID_LAYERS layer does not connect pads solid). Also returns, as the last element of the tuple pair, the figures: see fill_quality."""
    from . import fills
    require(b, 'z_conn')
    require(b, 'z_clear')
    c = resolve(cfg, FILL_QUALITY_NAMES, 'fill_quality', report)
    gnd = nid(b, c.GND)
    out = []
    figs = {}
    for lay in c.FILL_LAYERS:
        code = _layer_code(lay)
        minw = float(c.FILL_MIN_WIDTH[lay]) if isinstance(c.FILL_MIN_WIDTH, dict) else float(c.FILL_MIN_WIDTH)
        zs = [z for z in range(len(b.z_layer)) if b.z_layer[z] == code and b.z_net[z] == gnd and b.z_filled[z] and not b.z_keepout[z]]
        if not zs:
            continue
        r_fill = fills.net_copper(b, code, gnd, c.FILL_RASTER, with_net_items=False)
        r_all = fills.net_copper(b, code, gnd, c.FILL_RASTER, with_net_items=True)
        nar, _ = fills.narrow_pieces(r_fill, minw, c.FILL_MIN_AREA, c.FILL_LENGTH_FACTOR)
        for p in nar:
            out.append(('narrow', '%s pour %.2f mm wide, %.1f mm long' % (lay, p.width, p.length), p.x, p.y))
        de = [p for p in fills.thin_report(r_all, 0.0, c.FILL_DEAD_END_WIDTH, c.FILL_MIN_AREA, length_factor=c.FILL_LENGTH_FACTOR) if p.dead_end]
        for p in de:
            out.append(('dead_end', '%s pour finger %.2f mm wide, %.1f mm long, touching other copper at one end' % (lay, p.width, p.length), p.x, p.y))
        if lay in c.FILL_ROUGH_LAYERS:
            from scipy import ndimage as _ndi
            rough = fills.rough_edges(b, r_fill, code, gnd, clearance=float(b.z_clear[zs[0]]), tol=c.FILL_ROUGH_TOL, link=c.FILL_ROUGH_LINK, exempt=c.FILL_SHELL_PREFIXES)
            rl, rn = _ndi.label(rough, structure=np.ones((3, 3)))
            for i in range(1, rn + 1):
                rr, cc = np.nonzero(rl == i)
                x, y = r_fill.to_mm((int(rr.mean()), int(cc.mean())))
                out.append(('rough', '%s pour edge is a row of clearance arcs round pads and vias (%.1f mm2 of it)' % (lay, (rl == i).sum() / r_fill.ppmm ** 2), x, y))
            figs[f'{lay}_rough'] = rn
        if lay == 'F' and c.FILL_SHELL_PREFIXES:
            from scipy import ndimage as _ndi2
            clr = float(b.z_clear[zs[0]])
            shells = [h for h in range(len(b.p_net)) if b.p_net[h] == gnd and not b.p_smd[h] and str(b.fp_ref[b.p_fp[h]]).startswith(tuple(c.FILL_SHELL_PREFIXES)) and (b.p_layer_mask[h] & 1)]
            lost = 0
            k = r_fill.ppmm
            for h in shells:
                x0 = int(np.floor((b.p_bx0[h] - 1.5 - r_fill.x0) * k)); x1 = int(np.ceil((b.p_bx1[h] + 1.5 - r_fill.x0) * k))
                y0 = int(np.floor((r_fill.y1 - b.p_by1[h] - 1.5) * k)); y1 = int(np.ceil((r_fill.y1 - b.p_by0[h] + 1.5) * k))
                x0, y0 = max(x0, 0), max(y0, 0)
                y1, x1 = min(y1, r_fill.mask.shape[0]), min(x1, r_fill.mask.shape[1])
                if y1 <= y0 or x1 <= x0:
                    frac = 0.0                                   # the pin is outside the pour's raster: no pour near it
                    if frac < c.FILL_SHELL_MIN:
                        lost += 1
                        out.append(('shell', '%s pin %s (GND) has no pour round it' % (b.fp_ref[b.p_fp[h]], b.p_pin[h]), float(b.p_x[h]), float(b.p_y[h])))
                    continue
                zone = r_fill.mask[y0:y1, x0:x1]
                yy, xx = np.mgrid[y0:y1, x0:x1]
                px = r_fill.x0 + (xx + 0.5) / k
                py = r_fill.y1 - (yy + 0.5) / k
                d = np.hypot(px - b.p_x[h], py - b.p_y[h]) - max(b.p_sx[h], b.p_sy[h]) / 2          # distance from the pad's outline (a circle or oval pin: its larger radius)
                ring = (d > clr + 0.05) & (d <= clr + 0.65)
                frac = float((ring & zone).sum()) / max(1, int(ring.sum()))
                if frac < c.FILL_SHELL_MIN:
                    lost += 1
                    out.append(('shell', '%s pin %s (GND) has pour on %.0f%% of its ring, needs %.0f%%' % (b.fp_ref[b.p_fp[h]], b.p_pin[h], 100 * frac, 100 * c.FILL_SHELL_MIN), float(b.p_x[h]), float(b.p_y[h])))
            figs['F_shell_pins'] = len(shells)
            figs['F_shell_lost'] = lost
        if lay == 'F' and c.FILL_GNDPAD_MIN > 0:
            clr2 = float(b.z_clear[zs[0]])
            k2 = r_fill.ppmm
            bad_pads = 0
            for h in range(len(b.p_net)):
                if b.p_net[h] != gnd or not b.p_smd[h] or not (b.p_layer_mask[h] & 1):
                    continue
                x0 = int(np.floor((b.p_bx0[h] - 1.2 - r_fill.x0) * k2)); x1 = int(np.ceil((b.p_bx1[h] + 1.2 - r_fill.x0) * k2))
                y0 = int(np.floor((r_fill.y1 - b.p_by1[h] - 1.2) * k2)); y1 = int(np.ceil((r_fill.y1 - b.p_by0[h] + 1.2) * k2))
                x0, y0 = max(x0, 0), max(y0, 0)
                y1, x1 = min(y1, r_fill.mask.shape[0]), min(x1, r_fill.mask.shape[1])
                if y1 <= y0 or x1 <= x0:
                    zone = np.zeros((0, 0), bool)
                    yy = xx = np.zeros((0, 0))
                else:
                    zone = r_fill.mask[y0:y1, x0:x1]
                    yy, xx = np.mgrid[y0:y1, x0:x1]
                px = r_fill.x0 + (xx + 0.5) / k2
                py = r_fill.y1 - (yy + 0.5) / k2
                d = np.hypot(np.maximum(np.maximum(b.p_bx0[h] - px, px - b.p_bx1[h]), 0), np.maximum(np.maximum(b.p_by0[h] - py, py - b.p_by1[h]), 0))      # distance from the pad's box
                ring = (d > clr2 + 0.05) & (d <= clr2 + 0.65)
                vis = _visible_stub(b, gnd, h, r_fill)                      # a track to a via of its own that lies bare is a stub, in the pour or not, and a via a hair from the pad edge does not make it one with the pad
                if vis > c.FILL_GNDPAD_STUB and not (_has_hole(b, gnd, h) or _tied_to_holed_pad(b, gnd, h, c.FILL_GNDPAD_TIE)):
                    bad_pads += 1
                    out.append(('gndpad', '%s pin %s (SMD GND) has %.2f mm of bare track to its via, which is not at the pad edge' % (b.fp_ref[b.p_fp[h]], b.p_pin[h], vis), float(b.p_x[h]), float(b.p_y[h])))
                    continue
                if float((ring & zone).sum()) / max(1, int(ring.sum())) >= c.FILL_GNDPAD_MIN:
                    continue
                vd = np.hypot(np.maximum(np.maximum(b.p_bx0[h] - b.v_x, b.v_x - b.p_bx1[h]), 0), np.maximum(np.maximum(b.p_by0[h] - b.v_y, b.v_y - b.p_by1[h]), 0)) - b.v_dia / 2 if len(b.v_x) else np.array([9.0])
                if len(b.v_x) and ((vd <= c.FILL_GNDPAD_VIA_GAP) & (b.v_net == gnd)).any():
                    continue
                if _has_hole(b, gnd, h) or _tied_to_holed_pad(b, gnd, h, c.FILL_GNDPAD_TIE):
                    continue
                bad_pads += 1
                out.append(('gndpad', '%s pin %s (SMD GND) is outside the top pour and has no via at its edge' % (b.fp_ref[b.p_fp[h]], b.p_pin[h]), float(b.p_x[h]), float(b.p_y[h])))
            figs['F_gndpad_lost'] = bad_pads
        figs[f'{lay}_narrow'] = len(nar)
        figs[f'{lay}_dead_end'] = len(de)
        figs[f'{lay}_outline_mm'] = float(sum(
            np.hypot(*(np.roll(b.z_xy[b.z_vert_off[j]:b.z_vert_off[j + 1]], -1, axis=0) - b.z_xy[b.z_vert_off[j]:b.z_vert_off[j + 1]]).T).sum()
            for z in zs for j in range(b.z_ring_off[z], b.z_ring_off[z + 1])))
        smd = [h for h in range(len(b.p_net)) if b.p_net[h] == gnd and b.p_smd[h] and (b.p_layer_mask[h] & (1 << code))]
        for z in zs:
            conn = int(b.z_conn[z])
            if lay in c.FILL_THERMAL_LAYERS and smd and conn != THERMAL:
                out.append(('thermal', '%s zone connects its %d SMD GND pads %s, not by thermal reliefs' % (lay, len(smd), 'solid' if conn == SOLID else 'not at all'), 0.0, 0.0))
            if lay in c.FILL_SOLID_LAYERS and conn != SOLID:
                out.append(('solid', '%s zone does not connect pads solid' % lay, 0.0, 0.0))
    from .config import ConfigError
    waived_shell = 0
    for e in list(c.FILL_SHELL_EXCEPTIONS):
        if len(e) != 3 or not str(e[2]).strip():
            raise ConfigError('FILL_SHELL_EXCEPTIONS entries are (ref, pin, reason) with a reason; got %r' % (e,))
        hit = [f for f in out if f[0] == 'shell' and f[1].startswith('%s pin %s ' % (e[0], e[1]))]
        if len(hit) == 1:
            out.remove(hit[0])
            waived_shell += 1
        else:
            out.append(('stale_exception', '%s.%s matches %d shell findings, not exactly one (%s)' % (e[0], e[1], len(hit), e[2]), 0.0, 0.0))
    waived_pad = 0
    for e in list(c.FILL_GNDPAD_EXCEPTIONS):
        if len(e) != 3 or not str(e[2]).strip():
            raise ConfigError('FILL_GNDPAD_EXCEPTIONS entries are (ref, pin, reason) with a reason; got %r' % (e,))
        hit = [f for f in out if f[0] == 'gndpad' and f[1].startswith('%s pin %s ' % (e[0], e[1]))]
        if len(hit) == 1:
            out.remove(hit[0])
            waived_pad += 1
        else:
            out.append(('stale_exception', '%s.%s matches %d gndpad findings, not exactly one (%s)' % (e[0], e[1], len(hit), e[2]), 0.0, 0.0))
    figs['F_shell_waived'] = waived_shell
    figs['F_gndpad_waived'] = waived_pad
    return out, figs


def fill_quality(b, cfg, report=None):
    parts, figs = fill_quality_parts(b, cfg, report)
    kinds = ('narrow', 'dead_end', 'rough', 'shell', 'gndpad', 'thermal', 'solid', 'stale_exception')
    fig = {k: float(sum(1 for p in parts if p[0] == k)) for k in kinds}
    fig.update({k: float(v) for k, v in figs.items()})
    fig['violations'] = float(len(parts))
    bad = [f'{p[0]}: {p[1]} at ({p[2]:.2f}, {p[3]:.2f})' for p in parts]
    return Result(not parts, '; '.join(bad[:6]) or 'no narrow piece, dead end or row of arcs in the pour, thermal reliefs and solid planes as configured', fig)


# ----------------------------------------------------------------------------------------------------- the effective configuration
RULES = {'ground_plane': GROUND_PLANE_NAMES, 'bottom_hops': BOTTOM_HOPS_NAMES, 'sensitive_nets': SENSITIVE_NETS_NAMES, 'pour_gap': POUR_GAP_NAMES,
         'keepout_ring': KEEPOUT_RING_NAMES, 'decoupling': DECOUPLING_NAMES, 'blocks': BLOCK_NAMES, 'test_points': TEST_POINTS_NAMES,
         'track_geometry': TRACK_GEOMETRY_NAMES, 'fill_quality': FILL_QUALITY_NAMES, 'designators': SILK_REQUIRED_NAMES + LEGIBILITY_NAMES[2:] + TWO_WAY_NAMES[1:]}
for _r, _n in RULES.items():
    declare(_r, _n)


def effective_config(cfg, rule):
    """the effective configuration of one rule as text: every name it reads, where the value came from ("project" or "default") and
    the value. A project name missing from `cfg` raises ConfigError, as running the rule would."""
    rows = []
    resolve(cfg, RULES[rule], rule, rows)
    text = format_report(rows, rule)
    unknown = check_names(cfg)
    if unknown:
        text += f'\nunrecognised (declared by no pcbkit module; informational): {", ".join(unknown)}'
    return text
