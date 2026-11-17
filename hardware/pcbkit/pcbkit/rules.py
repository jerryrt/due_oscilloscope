"""General layout rules for a two-layer board, each `rule(b, cfg, report=None) -> Result(ok, detail, figures)`.

`b` is a pcbkit.board.BoardArrays, `cfg` a configuration (see config.py: project names raise when missing, tunables have documented
defaults, and `report`, a list, receives the effective configuration as (name, value, source) rows). The names each rule reads are in
its `*_NAMES` table here and in CONFIG.md. A rule never reads a name it does not list.

Rules in this module: ground_plane, bottom_hops. `*_parts` return the same findings as lists, for a caller that must interleave
them with its own (the AFE's LR-1 keeps its printed order that way).
"""
from __future__ import annotations

import dataclasses
import weakref

import numpy as np
from scipy.spatial import cKDTree

from . import geom
from .config import declare, format_report, project, resolve, tunable, check_names


@dataclasses.dataclass
class Result:
    ok: bool
    detail: str
    figures: dict


class PadTable:
    """pads as the old loader saw them: dict keyed (ref, pin), the last pad of a repeated key wins, in first-seen order"""

    def __init__(self, b):
        refs = [b.fp_ref[i] for i in b.p_fp]
        last = {}
        for row, (r, p) in enumerate(zip(refs, b.p_pin)):
            last[(r, p)] = row
        self.keys = list(last)
        self.rows = np.array(list(last.values()), np.int64)
        self.lookup = last
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
    used = np.zeros(len(gv), bool)
    nov = []
    for j in sel:
        r = pt.rows[j]
        d = np.hypot(gv[:, 0] - b.p_x[r], gv[:, 1] - b.p_y[r]) if len(gv) else np.zeros(0)
        d = np.where(used, np.inf, d)
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
    ok_text = f'{int(fig["layers"])} layers, one plane, {int(fig["gnd_pads"])} GND pads each with its own via'
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


# ----------------------------------------------------------------------------------------------------- the effective configuration
RULES = {'ground_plane': GROUND_PLANE_NAMES, 'bottom_hops': BOTTOM_HOPS_NAMES}
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
