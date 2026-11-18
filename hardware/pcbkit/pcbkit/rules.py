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
    tunable('TRACK_ENTRY_EDGE_TOL', 0.001, 'mm', 'how far a track entering a pad may overhang the span of the pad edge it enters (it enters through the edge, not across a corner)'),
    tunable('TRACK_OVERLAP_TOL', 0.001, 'mm', 'a track overlaps a pad when its copper is further than this over the pad edge'),
)


def _pad_arrays(b):
    pt = pads(b)
    r = pt.rows
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
    pt = pads(b)
    for f in np.unique(b.p_fp[pt.rows]) if len(pt.rows) else []:
        m = b.p_fp[pt.rows] == f
        P = np.column_stack([b.p_x[pt.rows][m], b.p_y[pt.rows][m]])
        if len(P) >= 2:
            d = np.hypot(P[:, None, 0] - P[None, :, 0], P[:, None, 1] - P[None, :, 1])
            d[d < 1e-6] = np.inf
            out[int(f)] = float(d.min())
    return out


def _dev(angle, step):
    m = angle % step
    return min(m, step - m)


def track_geometry_parts(b, cfg, report=None):
    """[(kind, text, x, y)] findings of the track geometry rule, kinds: 'arc' (a curved track), 'angle' (a segment off the angle step), 'jog' (a straight run shorter than
    TRACK_MIN_LEG between bends, unless it breaks out of a fine-pitch pad), 'entry' (the segment into a pad is not perpendicular to the edge it enters, or enters across a corner), 'over_pad' (a track
    crosses the pads of a part it does not end on). Positions are board-frame mm."""
    c = resolve(cfg, TRACK_GEOMETRY_NAMES, 'track_geometry', report)
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


def track_geometry(b, cfg, report=None):
    parts = track_geometry_parts(b, cfg, report)
    kinds = ('arc', 'angle', 'jog', 'entry', 'over_pad')
    fig = {f'{k}': float(sum(1 for p in parts if p[0] == k)) for k in kinds}
    fig['segments'] = float(len(b.s_idx))
    fig['violations'] = float(len(parts))
    bad = [f'{p[0]}: {p[1]} at ({p[2]:.2f}, {p[3]:.2f})' for p in parts]
    return Result(not parts, '; '.join(bad[:6]) or f'{len(b.s_idx)} segments: on the angle step, no jogs, straight into pads, over no foreign pad', fig)


# ----------------------------------------------------------------------------------------------------- fill quality
FILL_QUALITY_NAMES = (
    project('GND', 'net name', 'the net of the pours measured'),
    tunable('FILL_LAYERS', ('F', 'B'), 'layer letters', 'the copper layers whose pour of GND is measured'),
    tunable('FILL_MIN_WIDTH', {'F': 0.8, 'B': 0.5}, 'mm per layer, or one mm for all', 'no strip, finger or tooth of the pour is narrower than this (the top for its looks, the plane for slivers only)'),
    tunable('FILL_DEAD_END_WIDTH', 1.6, 'mm', 'a part of the pour narrower than this that touches other copper at one end only is a dead-end finger'),
    tunable('FILL_LENGTH_FACTOR', 2.0, 'x half the width', 'a narrow part is a finger or a tooth only when it is longer than this times half the width limit (a shorter one is the rounding of a corner)'),
    tunable('FILL_RASTER', 40.0, 'pixels per mm', 'the resolution the pour is measured at'),
    tunable('FILL_MIN_AREA', 0.02, 'mm2', 'narrow parts smaller than this are ignored'),
    tunable('FILL_THERMAL_LAYERS', ('F',), 'layer letters', 'the layers whose zone must connect SMD GND pads through thermal reliefs'),
    tunable('FILL_SOLID_LAYERS', ('B',), 'layer letters', 'the layers whose zone must connect pads solid (a plane)'),
)
THERMAL, SOLID = 1, 2            # pcbnew's ZONE_CONNECTION_THERMAL and ZONE_CONNECTION_FULL


def fill_quality_parts(b, cfg, report=None):
    """[(kind, text, x, y)] findings: 'narrow' (a part of the pour narrower than FILL_MIN_WIDTH, and longer than the rounding of a corner), 'dead_end' (a finger narrower than
    FILL_DEAD_END_WIDTH touching other copper at one end only), 'thermal' (a zone on a FILL_THERMAL_LAYERS layer does not use thermal reliefs on its SMD GND pads), 'solid'
    (a zone on a FILL_SOLID_LAYERS layer does not connect pads solid). Also returns, as the last element of the tuple pair, the figures: see fill_quality."""
    from . import fills
    require(b, 'z_conn')
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
    return out, figs


def fill_quality(b, cfg, report=None):
    parts, figs = fill_quality_parts(b, cfg, report)
    kinds = ('narrow', 'dead_end', 'thermal', 'solid')
    fig = {k: float(sum(1 for p in parts if p[0] == k)) for k in kinds}
    fig.update({k: float(v) for k, v in figs.items()})
    fig['violations'] = float(len(parts))
    bad = [f'{p[0]}: {p[1]} at ({p[2]:.2f}, {p[3]:.2f})' for p in parts]
    return Result(not parts, '; '.join(bad[:6]) or 'no narrow or dead-end pour, thermal reliefs and solid planes as configured', fig)


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
