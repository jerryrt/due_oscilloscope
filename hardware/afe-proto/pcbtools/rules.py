"""The layout rules LR-1 .. LR-9, LR-11, LR-12 and the INV_MAX row (docs/afe.md section 11.1), on BoardArrays, in numpy.

    rule(b: BoardArrays, cfg) -> Result(ok, detail, figures)

`cfg` is a board configuration (pcbtools.boards.v2, or any object with the same module-level names). `detail` is written
to match the old lr_check.py's printed text (same wording, same order, same rounding); `figures` holds the numbers as
floats. LR-10 (DRC) is pcbtools.drc, not here: it needs kicad-cli.

What the old tool did and this port keeps, on purpose, because the goldens depend on it:
  * a pad is identified by (ref, pin) and when a footprint repeats a pin (shield pads) the LAST pad wins (`PadTable`);
  * a footprint is "placed" at its origin (fp_x, fp_y) and has a courtyard box only if the courtyard exists;
  * "bottom" = B.Cu, "top" = F.Cu; track lengths of one net are the plain sum of segment lengths;
  * connectivity (LR-6, LR-8) is by geometry, see `pieces`.
What differs, and why (the old tool sampled points, this one is exact): every segment test (inside a box, near a segment,
distance to a box) was `any(sample point ...)` with samples 0.05-0.5 mm apart; here it is the exact segment test of
pcbtools.geom. Figures that came from the closest sample (LR-5's distances) can therefore be smaller by up to the
sample step; verdicts agree on every fixture. tests/pcbtools/test_rules_equivalence.py lists each difference.
"""
from __future__ import annotations

import dataclasses
import math
import weakref

import numpy as np
from scipy.spatial import cKDTree

from . import geom


@dataclasses.dataclass
class Result:
    ok: bool
    detail: str
    figures: dict


# ----------------------------------------------------------------------------------------------------- helpers
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


def analog_refs(b, cfg):
    """the analog parts that exist on this board and have a courtyard, sorted"""
    return sorted(r for r in cfg.ANALOG_REFS if has_box(b, r))


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


# ----------------------------------------------------------------------------------------------------- LR-1
def bottom_runs(b, cfg):
    """connected runs of non-GND bottom segments (same net, endpoints within 0.01 mm): list of
    (net name, length, vias at its ends, [analog refs it lies under]) plus the segment rows and their labels"""
    gnd = nid(b, '/GND')
    rows = np.flatnonzero((b.s_layer == 1) & (b.s_net != gnd))
    n = len(rows)
    if not n:
        return [], rows, np.zeros(0, np.int32)
    S = segs(b)[rows]
    net = b.s_net[rows]
    E = np.vstack([S[:, :2], S[:, 2:]])
    tree = cKDTree(E)
    pr = tree.query_pairs(0.01, output_type='ndarray')
    if len(pr):
        ok = (np.hypot(*(E[pr[:, 0]] - E[pr[:, 1]]).T) < 0.01) & (net[pr[:, 0] % n] == net[pr[:, 1] % n])
        joins = np.column_stack([pr[ok, 0] % n, pr[ok, 1] % n])
    else:
        joins = np.zeros((0, 2), np.int64)
    k, lab = geom.connected_components(n, joins)
    L = np.bincount(lab, weights=geom.seg_len(S), minlength=k)
    # vias at the ends of the run: same net, within 0.05 of any end of any segment of the run
    nv = np.zeros(k, np.int64)
    if len(b.v_idx):
        V = np.column_stack([b.v_x, b.v_y])
        d = cKDTree(V).sparse_distance_matrix(tree, 0.05, output_type='ndarray')
        if len(d):
            vi, ei = d['i'], d['j']
            m = (d['v'] < 0.05) & (b.v_net[vi] == net[ei % n])
            key = np.unique(lab[ei[m] % n].astype(np.int64) * len(V) + vi[m])
            nv = np.bincount(key // len(V), minlength=k)
    under = np.zeros((k, 0), bool)
    refs = analog_refs(b, cfg)
    if refs:
        boxes = np.array([box(b, r) for r in refs])
        hit = geom.seg_in_box(S, boxes, pad=cfg.ZONE_PAD + b.s_w[rows] / 2)
        under = np.zeros((k, len(refs)), bool)
        np.logical_or.at(under, lab, hit)
    runs = [(b.nets[net[np.flatnonzero(lab == r)[0]]], float(L[r]), int(nv[r]), [refs[j] for j in np.flatnonzero(under[r])])
            for r in range(k)]
    return runs, rows, lab


def bottom_crossings(b, cfg):
    gnd = nid(b, '/GND')
    rows = np.flatnonzero((b.s_layer == 1) & (b.s_net != gnd))
    if not len(rows):
        return []
    S = segs(b)[rows]
    w = b.s_w[rows]
    bad = [[] for _ in rows]
    fz = np.array([rc for blk in cfg.ANALOG_FENCE for rc in cfg.OUTLINE.get(blk, [])], float).reshape(-1, 4)
    if len(fz):
        hit = geom.seg_in_box(S, fz, pad=w / 2)
        any_, first = _first_true(hit)
        for i in np.flatnonzero(any_):
            bad[i].append(f'{b.nets[b.s_net[rows[i]]]}: bottom segment inside an analog fence '
                          f'{tuple(round(float(v), 1) for v in fz[first[i]])}')
    sens = net_prefix(b, cfg.XSENS)
    trows = np.flatnonzero((b.s_layer == 0) & sens[b.s_net])
    if len(trows):
        T = segs(b)[trows]
        D = geom.seg_seg_dist(S, T)
        close = D < (w[:, None] + b.s_w[trows][None, :]) / 2 + 0.1
        any_, first = _first_true(close)
        for i in np.flatnonzero(any_):
            bad[i].append(f'{b.nets[b.s_net[rows[i]]]}: bottom segment under {b.nets[b.s_net[trows[first[i]]]]} '
                          '(a hop under a sensitive net; bridge it on top)')
    pt = pads(b)
    prow = pt.rows[sens[pt.net]]
    pkeys = [pt.keys[j] for j in np.flatnonzero(sens[pt.net])]
    if len(prow):
        hit = geom.seg_in_box(S, pad_box(b, prow), pad=0.1 + w / 2)
        any_, first = _first_true(hit)
        for i in np.flatnonzero(any_):
            k = pkeys[first[i]]
            bad[i].append(f'{b.nets[b.s_net[rows[i]]]}: bottom segment under pad {k[0]}.{k[1]} of {b.nets[b.p_net[prow[first[i]]]]}')
    return [m for per in bad for m in per]


def lr1(b, cfg):
    bad = []
    if b.copper_layers != 2:
        bad.append(f'{b.copper_layers} copper layers')
    gnd = nid(b, '/GND')
    bz = np.flatnonzero((b.z_layer == 1) & (b.z_net == gnd))
    pieces_n = None
    if not len(bz):
        bad.append('no bottom GND zone')
    else:
        z = bz[0]
        if not b.z_filled[z]:
            bad.append('bottom zone not filled')
        pieces_n = int((b.z_ring_hole[b.z_ring_off[z]:b.z_ring_off[z + 1]] == 0).sum()) if b.z_filled[z] else 0
        if pieces_n != 1:
            bad.append(f'bottom plane is {pieces_n} pieces, not 1')
    runs, _, _ = bottom_runs(b, cfg)
    for net, L, nv, under in runs:
        if under:
            bad.append(f'{net}: bottom copper under {under}')
        if L > cfg.HOP_MAX or nv > cfg.HOP_MAX_VIAS:
            bad.append(f'{net}: bottom run {L:.1f} mm, {nv} vias (limit {cfg.HOP_MAX} mm, {cfg.HOP_MAX_VIAS})')
    bad += bottom_crossings(b, cfg)
    # every SMD GND pad has a via of its own within 3 mm: greedy in (ref, pin) order, each via used once
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
        if i >= 0 and d[i] <= 3.0:
            used[i] = True
        else:
            nov.append(f'{pt.keys[j][0]}.{pt.keys[j][1]}')
    if nov:
        bad.append(f'{len(nov)} SMD ground pads without a via of their own: {nov[:6]}')
    fig = dict(layers=float(b.copper_layers), bottom_pieces=float(pieces_n if pieces_n is not None else -1),
               bottom_runs=float(len(runs)), max_run_mm=max([r[1] for r in runs], default=0.0),
               max_run_vias=float(max([r[2] for r in runs], default=0)), gnd_pads=float(len(sel)), pads_without_via=float(len(nov)),
               violations=float(len(bad)))
    return Result(not bad, '; '.join(bad[:6]) or f'2 layers, one bottom plane, {len(runs)} bottom runs, {len(sel)} GND pads each with its own via', fig)


# ----------------------------------------------------------------------------------------------------- LR-2
def lr2(b, cfg):
    bad = []
    for ch, base, bnc, adc in cfg.CHANNELS:
        seq = [pad_c(b, bnc, '1')[0], pos(b, f'R{base + 1}')[0], pos(b, f'R{base + 7}')[0], pos(b, 'U101')[0],
               pos(b, f'R{base + 8}')[0], pad_c(b, 'J602', adc)[0]]
        if not all(x > y for x, y in zip(seq, seq[1:])):
            bad.append(f'CH{ch}: x does not fall BNC > R1 > Rnp > U101 > Riso > ADC pad: {[round(float(x), 1) for x in seq]}')
        outl = length_of(b, '/A1' if ch == 1 else '/A0') + length_of(b, f'/CH{ch}_OUT') + (length_of(b, '/CH2_RISO') if ch == 2 else 0)
        hiz = sum(length_of(b, f'/CH{ch}_{n}') for n in ('N', 'M1', 'M2', 'M3', 'NP'))
        if outl <= hiz:
            bad.append(f'CH{ch}: output run {outl:.1f} mm is not longer than the divider side {hiz:.1f} mm')
    g = pos(b, cfg.GEN[0])
    d5 = float(np.hypot(*(g - pad_c(b, 'J601', '5'))))
    if d5 > 15:
        bad.append(f'generator {d5:.1f} mm from the 5 V pad')
    dj = {}
    for j in ('J101', 'J201', 'J301'):
        dj[j] = float(np.hypot(*(g - pos(b, j))))
        if dj[j] < 50:
            bad.append(f'generator {dj[j]:.0f} mm from {j}')
    dref = {}
    for r in ('U501', 'U502', 'R501', 'R506'):
        dref[r] = min(float(geom.box_dist(box(b, r), box(b, x))[0, 0]) for x in cfg.GEN)
        if dref[r] < cfg.KEEPOUT:
            bad.append(f'{r} only {dref[r]:.1f} mm from the generator')
    pt = pads(b)
    px, py = b.p_x[pt.rows], b.p_y[pt.rows]
    names = np.array(b.nets)[pt.net] if len(pt.rows) else np.array([])
    A = np.column_stack([px, py])[np.isin(names, ['/CH1_N', '/CH1_NP', '/CH1_IN']) & (px < cfg.DIVIDER_X_MAX)]
    B = np.column_stack([px, py])[np.isin(names, ['/CH2_N', '/CH2_NP', '/CH2_IN']) & (px < cfg.DIVIDER_X_MAX)]
    gap = float(np.hypot(A[:, None, 0] - B[None, :, 0], A[:, None, 1] - B[None, :, 1]).min())
    if gap < 5.0:
        bad.append(f"channels' divider pads only {gap:.1f} mm apart")
    fig = dict(divider_gap_mm=gap, generator_to_5v_mm=d5, **{f'generator_to_{j}_mm': v for j, v in dj.items()},
               **{f'{r}_to_generator_mm': v for r, v in dref.items()})
    return Result(not bad, '; '.join(bad[:5]) or f'flow, generator, quiet zone and channel separation hold (closest divider pads {gap:.1f} mm)', fig)


# ----------------------------------------------------------------------------------------------------- LR-3
def lr3(b, cfg):
    bad = []
    for n in cfg.HIZ:
        net = '/' + n
        if (b.v_net == nid(b, net)).any():
            bad.append(f'{net}: a via')
        L = length_of(b, net)
        if L > 14:
            bad.append(f'{net}: {L:.1f} mm of track')
    ids = [nid(b, '/' + n) for n in cfg.HIZ]
    hz = np.flatnonzero(np.isin(b.s_net, ids) & (b.s_layer == 0))
    gnd = nid(b, '/GND')
    ot = np.flatnonzero((b.s_layer == 0) & (b.s_net != gnd))
    nclose = 0
    if len(hz) and len(ot):
        S = segs(b)
        step = 64
        for a in range(0, len(hz), step):
            ia = hz[a:a + step]
            D = geom.seg_seg_dist(S[ia], S[ot])
            lim = 0.6 + (b.s_w[ia][:, None] + b.s_w[ot][None, :]) / 2
            close = (D < lim) & (b.s_net[ia][:, None] != b.s_net[ot][None, :])
            any_, first = _first_true(close)
            for i in np.flatnonzero(any_):
                bad.append(f'{b.nets[b.s_net[ia[i]]]} track within 0.6 mm of {b.nets[b.s_net[ot[first[i]]]]} track')
                nclose += 1
    longest = max([length_of(b, '/' + n) for n in cfg.HIZ], default=0.0)
    return Result(not bad, '; '.join(sorted(set(bad))[:6]) or f'{len(cfg.HIZ)} divider nets: no via, short, no track beside',
                  dict(nets=float(len(cfg.HIZ)), longest_mm=longest, tracks_too_close=float(nclose)))


# ----------------------------------------------------------------------------------------------------- LR-4
def _has_via(b, net):
    return bool((b.v_net == nid(b, net)).any())


def _has_bottom(b, net):
    return bool(((b.s_net == nid(b, net)) & (b.s_layer == 1)).any())


def lr4(b, cfg):
    bad = []
    for net in ('/A0', '/A1'):
        if _has_via(b, net):
            bad.append(f'{net}: a via')
        if _has_bottom(b, net):
            bad.append(f'{net}: bottom copper')
    for r, pinpad in (('R108', ('U101', '7')), ('R208', ('U101', '1'))):
        if float(np.hypot(*(pad_c(b, r, '1') - pad_c(b, *pinpad)))) > 5:
            bad.append(f'{r} not at the output pin')
    for cap, pad in (('C104', ('U101', '8')), ('C305', ('U301', '8')), ('C306', ('U301', '4'))):
        d = float(np.hypot(*(pad_c(b, cap, '1') - pad_c(b, *pad))))
        if d > 12:
            bad.append(f'{cap} {d:.0f} mm from its supply pin')
    for net in cfg.INV_NODES:
        if _has_via(b, net):
            bad.append(f'{net}: inverting node has a via')
        if _has_bottom(b, net):
            bad.append(f'{net}: inverting node has bottom copper')
    L = length_of(b, '/AWG_FB')
    if L > cfg.FB_MAX:
        bad.append(f'AWG inverting node {L:.1f} mm of track (limit {cfg.FB_MAX})')
    near = set()
    fbn, gnd = nid(b, '/AWG_FB'), nid(b, '/GND')
    fb = np.flatnonzero((b.s_net == fbn) & (b.s_layer == 0))
    pt = pads(b)
    fbp = pt.rows[pt.net == fbn]
    P = np.vstack([sample_points(segs(b)[fb], 0.5)[0], np.column_stack([b.p_x[fbp], b.p_y[fbp]])]) if (len(fb) or len(fbp)) else np.zeros((0, 2))
    gt = np.flatnonzero((b.s_net == gnd) & (b.s_layer == 0))
    if len(P) and len(gt):
        G = segs(b)[gt]
        # top GND track within 0.5 mm of the node: distance from the node's sample points to the track's centre line,
        # less the track's half width (as the old tool; the track side is exact here, it was sampled every 0.25 mm)
        D = geom.point_seg_dist(P, G) - b.s_w[gt][None, :] / 2
        if (D < 0.5).any():
            near.add('GND track')
    zi = [z for z in range(len(b.z_layer)) if b.z_layer[z] == 0 and b.z_net[z] == gnd and b.z_filled[z]]
    if len(P) and zi:
        Q = np.vstack([P + [dx, dy] for dx, dy in ((0.5, 0), (-0.5, 0), (0, 0.5), (0, -0.5))])
        for z in zi:
            r0, r1 = b.z_ring_off[z], b.z_ring_off[z + 1]
            ring_off = b.z_vert_off[r0:r1 + 1]
            xy = b.z_xy[ring_off[0]:ring_off[-1]]
            inside = geom.points_in_polys(Q, xy, ring_off - ring_off[0], hole=b.z_ring_hole[r0:r1])
            if inside.any():
                near.add('top pour')
    if near:
        bad.append(f'top ground copper within 0.5 mm of the inverting node ({sorted(near)})')
    a0, a1 = length_of(b, '/A0'), length_of(b, '/A1')
    return Result(not bad, '; '.join(bad[:5]) or f'A0/A1 top only, no via ({a0:.0f}/{a1:.0f} mm); '
                  f'FB node {L:.1f} mm of track; decoupling near; no pour within 0.5 mm of it',
                  dict(a0_mm=a0, a1_mm=a1, fb_mm=L, violations=float(len(bad))))


def lr4_inv(b, cfg):
    bad, fig, figs = [], [], {}
    for net in cfg.INV_LEN_NODES:
        L = length_of(b, net, top_only=False)
        figs[net[1:]] = L
        fig.append(f'{net[1:]} {L:.1f} mm')
        if L > cfg.INV_MAX:
            bad.append(f'{net[1:]} {L:.1f} mm of track exceeds INV_MAX {cfg.INV_MAX} mm')
    return Result(not bad, '; '.join(bad) + (' [' + ', '.join(fig) + ']' if bad else '') or f'{", ".join(fig)} (<= {cfg.INV_MAX})', figs)


# ----------------------------------------------------------------------------------------------------- LR-12
def decoup_dist(b, cfg, cap):
    ic, pin = cfg.DECOUP[cap]
    net = pad_net(b, ic, pin)
    ks = [k for k in ('1', '2') if pad_net(b, cap, k) == net] or ['1']
    return min(float(np.hypot(*(pad_c(b, cap, k) - pad_c(b, ic, pin)))) for k in ks)


def lr12(b, cfg):
    bad, fig, figs = [], [], {}
    for cap, (ic, pin) in cfg.DECOUP.items():
        d = decoup_dist(b, cfg, cap)
        figs[f'{cap}>{ic}.{pin}'] = d
        fig.append(f'{cap}>{ic}.{pin} {d:.1f}')
        if d > cfg.DECOUP_MAX:
            bad.append(f'{cap} is {d:.1f} mm from {ic} pin {pin} (limit {cfg.DECOUP_MAX})')
    return Result(not bad, '; '.join(bad) or f'{len(cfg.DECOUP)} caps within {cfg.DECOUP_MAX} mm: ' + ', '.join(fig), figs)


# ----------------------------------------------------------------------------------------------------- LR-5
def lr5(b, cfg):
    gen = [box(b, r) for r in cfg.GEN]
    near, dmin = [], math.inf
    sens = net_prefix(b, cfg.SENSITIVE)
    rows = np.flatnonzero((b.s_layer == 0) & sens[b.s_net])
    if len(rows):
        S = segs(b)[rows]
        d = np.min([seg_box_dist(S, g) for g in gen], axis=0)
        dmin = min(dmin, float(d.min()))
        for i in np.flatnonzero(d < cfg.KEEPOUT):
            near.append(f'{b.nets[b.s_net[rows[i]]]} {d[i]:.1f} mm')
    pt = pads(b)
    for j in np.flatnonzero(sens[pt.net]):
        k = pt.keys[j]
        if k[0] in cfg.GENERATOR_BLOCK:
            continue
        r = pt.rows[j]
        c = np.array([[b.p_x[r], b.p_y[r]]])
        d = min(float(pt_box_dist(c, g)[0]) for g in gen)
        dmin = min(dmin, d)
        if d < cfg.KEEPOUT:
            near.append(f'{b.nets[b.p_net[r]]} pad {k[0]}.{k[1]} {d:.1f} mm')
    return Result(not near, '; '.join(sorted(set(near))[:6]) or f'sensitive copper >= {cfg.KEEPOUT} mm from {"/".join(cfg.GEN)}',
                  dict(min_distance_mm=dmin, violations=float(len(near))))


# ----------------------------------------------------------------------------------------------------- pieces of copper
def pieces(b, cfg, net, cut=()):
    """connected pieces of one net's top copper (tracks, vias, pads), the pads in `cut` removed; the pads of
    cfg.BRIDGE_PADS are joined. Returns a list of sets of refs, one per piece, in order of first member.

    Touch rules, as the old tool, exact instead of sampled: two tracks touch when an end of one is within 0.02 of an end
    of the other or within 0.05 of the other's centre line; a track and a via when the via centre is within 0.05 of the
    centre line; a track and a pad when the centre line enters the pad's box grown by 0.02; two vias within 0.05; a via
    and a pad when the via centre lies in the pad's box grown by 0.02; two pads never (a part does not join its pads,
    except the cfg.BRIDGE_PADS pairs). Track widths are not used."""
    n_id = nid(b, net)
    srow = np.flatnonzero((b.s_net == n_id) & (b.s_layer == 0))
    vrow = np.flatnonzero(b.v_net == n_id)
    pt = pads(b)
    cutset = set(cut)
    pj = [j for j in np.flatnonzero(pt.net == n_id) if pt.keys[j] not in cutset]
    prow = pt.rows[pj]
    pkeys = [pt.keys[j] for j in pj]
    ns, nv, npd = len(srow), len(vrow), len(prow)
    S = segs(b)[srow]
    V = np.column_stack([b.v_x[vrow], b.v_y[vrow]])
    PB = pad_box(b, prow)
    J = []
    if ns:
        P0, P1 = S[:, :2], S[:, 2:]
        D0, D1 = geom.point_seg_dist(P0, S), geom.point_seg_dist(P1, S)       # [a, b]: end of a to the line of b
        e = np.minimum.reduce([np.hypot(P0[:, None, 0] - P0[None, :, 0], P0[:, None, 1] - P0[None, :, 1]),
                               np.hypot(P0[:, None, 0] - P1[None, :, 0], P0[:, None, 1] - P1[None, :, 1]),
                               np.hypot(P1[:, None, 0] - P0[None, :, 0], P1[:, None, 1] - P0[None, :, 1]),
                               np.hypot(P1[:, None, 0] - P1[None, :, 0], P1[:, None, 1] - P1[None, :, 1])])
        T = (e < 0.02) | (D0 < 0.05) | (D1 < 0.05) | (D0.T < 0.05) | (D1.T < 0.05)
        a, c = np.nonzero(np.triu(T, 1))
        J.append(np.column_stack([a, c]))
        if nv:
            a, c = np.nonzero(geom.point_seg_dist(V, S) < 0.05)
            J.append(np.column_stack([c, ns + a]))
        if npd:
            a, c = np.nonzero(geom.seg_in_box(S, PB, pad=0.02))
            J.append(np.column_stack([a, ns + nv + c]))
    if nv:
        dv = np.hypot(V[:, None, 0] - V[None, :, 0], V[:, None, 1] - V[None, :, 1])
        a, c = np.nonzero(np.triu(dv < 0.05, 1))
        J.append(np.column_stack([ns + a, ns + c]))
        if npd:
            inb = ((V[:, None, 0] >= PB[None, :, 0] - 0.02) & (V[:, None, 0] <= PB[None, :, 2] + 0.02)
                   & (V[:, None, 1] >= PB[None, :, 1] - 0.02) & (V[:, None, 1] <= PB[None, :, 3] + 0.02))
            a, c = np.nonzero(inb)
            J.append(np.column_stack([ns + a, ns + nv + c]))
    for (ra, pa, rb, pb) in cfg.BRIDGE_PADS:
        ia = [i for i, k in enumerate(pkeys) if k == (ra, pa)]
        ib = [i for i, k in enumerate(pkeys) if k == (rb, pb)]
        if ia and ib:
            J.append(np.array([[ns + nv + ia[0], ns + nv + ib[0]]]))
    n = ns + nv + npd
    if not n:
        return []
    k, lab = geom.connected_components(n, np.vstack(J) if J else np.zeros((0, 2), np.int64))
    groups = [set() for _ in range(k)]
    for i, key in enumerate(pkeys):
        groups[lab[ns + nv + i]].add(key[0])
    return groups


# ----------------------------------------------------------------------------------------------------- LR-6
def lr6(b, cfg):
    bad, npieces = [], 0
    for net, groups in cfg.GROUPS.items():
        cut = list(cfg.STAR[net])
        pt = pads(b)
        have = {pt.keys[j] for j in np.flatnonzero(pt.net == nid(b, net))}
        missing = [f'{k[0]}.{k[1]}' for k in cut if k not in have]
        if missing:
            bad.append(f'{net}: star pads {missing} are not on the net')
        for pc in pieces(b, cfg, net, cut):
            npieces += 1
            hit = sorted(g for g, refs in groups.items() if pc & refs)
            if len(hit) > 1:
                bad.append(f'{net}: one piece of copper serves {hit}')
    return Result(not bad, '; '.join(bad[:5]) or '+3V3A and VNEG: one piece per consumer group after cutting the star pads',
                  dict(pieces=float(npieces), violations=float(len(bad))))


# ----------------------------------------------------------------------------------------------------- LR-7
def lr7(b, cfg):
    bad = []
    L = length_of(b, '/DAC0')
    if L > 12:
        bad.append(f'DAC0 {L:.1f} mm of track')
    dr = {}
    for r in ('R301', 'R302'):
        dr[r] = float(np.hypot(*(pos(b, r) - pos(b, 'J301'))))
        if dr[r] > 16:
            bad.append(f'{r} {dr[r]:.0f} mm from J301')
    j = b.ref_index('J301')
    shell = int(((b.p_fp == j) & (np.asarray(b.p_pin, dtype=object) == '2') & (b.p_net == nid(b, '/GND'))).sum())
    if shell < 3:
        bad.append(f'{shell} BNC shell pads on ground')
    return Result(not bad, '; '.join(bad) or f'DAC0 {L:.1f} mm; back-termination at the BNC; shell pads on ground',
                  dict(dac0_mm=L, shell_pads=float(shell), **{f'{r}_to_J301_mm': v for r, v in dr.items()}))


# ----------------------------------------------------------------------------------------------------- LR-8
def lr8(b, cfg):
    cut = {tuple(s.split('.')) for s in cfg.VREF_SOURCE}
    refs_of = [{tuple(s.split('.'))[0] for s in g} for g in cfg.VREF_BRANCHES]
    bad = []
    for pc in pieces(b, cfg, '/VREF', cut):
        hit = sorted(k for k, g in enumerate(refs_of) if pc & g)
        if len(hit) > 1:
            bad.append(f'VREF: branches {hit} share copper ({sorted(pc)[:6]})')
    return Result(not bad, '; '.join(bad[:4]) or f'VREF: {len(cfg.VREF_BRANCHES)} branches each on its own copper',
                  dict(branches=float(len(cfg.VREF_BRANCHES)), violations=float(len(bad))))


# ----------------------------------------------------------------------------------------------------- LR-9
def lr9(b, cfg):
    refs = analog_refs(b, cfg)
    ids = [nid(b, n) for n in cfg.DIGITAL]
    rows = np.flatnonzero(np.isin(b.s_net, ids))
    bad = []
    if len(rows) and refs:
        boxes = np.array([box(b, r) for r in refs])
        hit = geom.seg_in_box(segs(b)[rows], boxes, pad=cfg.ZONE_PAD + b.s_w[rows] / 2)
        pt = pads(b)
        on = {}
        for j, k in enumerate(pt.keys):
            on.setdefault(pt.net[j], set()).add(k[0])
        own = np.array([[r in on.get(b.s_net[s], ()) for r in refs] for s in rows], bool)
        hit &= ~own
        for i, jx in zip(*np.nonzero(hit)):
            bad.append(f'{b.nets[b.s_net[rows[i]]]} through {refs[jx]}')
    return Result(not bad, '; '.join(sorted(set(bad))[:6]) or 'SDA / SCL outside every analog courtyard but their own parts',
                  dict(digital_segments=float(len(rows)), violations=float(len(bad))))


# ----------------------------------------------------------------------------------------------------- LR-11
def _in_rects(P, rects):
    """bool (N,): the point lies in one of the rects (closed)"""
    R = np.array(rects, float).reshape(-1, 4)
    return ((P[:, None, 0] >= R[None, :, 0]) & (P[:, None, 0] <= R[None, :, 2])
            & (P[:, None, 1] >= R[None, :, 1]) & (P[:, None, 1] <= R[None, :, 3])).any(axis=1)


def lr11(b, cfg):
    bad = []
    blocks = {}
    for r, blk in cfg.BLOCK.items():
        if blk != 'EDGE' or r in cfg.BLOCK_OVERRIDE:
            blocks.setdefault(blk, set()).add(r)
    blocks.pop('EDGE', None)
    refs = list(b.fp_ref)
    P = np.column_stack([b.fp_x, b.fp_y])
    candidate = np.array([(r in cfg.BLOCK and cfg.BLOCK[r] != 'EDGE') or r in cfg.BLOCK_OVERRIDE for r in refs], bool)
    for blk, rects in cfg.OUTLINE.items():
        inside = {refs[i] for i in np.flatnonzero(candidate & _in_rects(P, rects))}
        want = blocks.get(blk, set())
        if inside != want:
            bad.append(f'{blk}: outline holds {sorted(inside - want)[:5]} extra, lacks {sorted(want - inside)[:5]}')
    inout = {k: _in_rects(P, rects) for k, rects in cfg.OUTLINE.items()}

    def block_of(i):
        r = refs[i]
        v = cfg.BLOCK.get(r)
        if v is None:
            v = next((k for k in cfg.OUTLINE if inout[k][i]), None)
        return v
    bof = [block_of(i) for i in range(len(refs))]
    for i, r in enumerate(refs):
        digits = ''.join(c for c in r if c.isdigit())
        want = cfg.LR_HUNDREDS.get(digits[:1]) if len(digits) >= 3 else None
        if want != bof[i]:
            bad.append(f'{r}: designator number says {want}, the part is in {bof[i]}')
    pt = pads(b)
    have = {bof[i] for i, r in enumerate(refs) if r.startswith('TP') and (r, '1') in pt.lookup}
    for blk in sorted(set(cfg.TEST_BLOCKS) - have):
        bad.append(f'block {blk} has no test point')
    refrow = {int(f): i for i, f in enumerate(b.r_fp)}
    ndes = 0
    for i, r in enumerate(refs):
        ndes += 1
        k = refrow.get(i)
        if k is None or not b.r_on_silk[k] or b.r_h[k] < cfg.DESIGNATOR_MIN_H:
            bad.append(f'{r}: designator not on silk at 0.8 mm or more')
    for r, n in cfg.TP_NETS.items():
        if (r, '1') not in pt.lookup or pad_net(b, r, '1') != n:
            bad.append(f'{r}: missing or not on {n}')
    names = set(b.t_text)
    for w in cfg.SILK_WORDS:
        if w not in names:
            bad.append(f'silk word {w!r} missing')
    return Result(not bad, '; '.join(bad[:6]) or f'{len(cfg.OUTLINE)} outlines hold exactly their parts, {ndes} designators, 8 test points',
                  dict(outlines=float(len(cfg.OUTLINE)), designators=float(ndes), violations=float(len(bad))))


ROWS = [('LR-1', lr1), ('LR-2', lr2), ('LR-3', lr3), ('LR-4', lr4), ('LR-4 INV_MAX', lr4_inv), ('LR-12 DECOUP_MAX', lr12),
        ('LR-5', lr5), ('LR-6', lr6), ('LR-7', lr7), ('LR-8', lr8), ('LR-9', lr9), ('LR-11', lr11)]
