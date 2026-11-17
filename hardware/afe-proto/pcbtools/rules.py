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

import os

import numpy as np
from scipy.spatial import cKDTree

from . import geom, shapes


# the helpers every rule shares, and the Result type, live in pcbkit (hardware/pcbkit); the names are re-exported here unchanged
from pcbkit import rules as _kit                                    # noqa: E402
from pcbkit.rules import (Result, PadTable, pads, nid, net_prefix, segs, length_of, pad_c, pad_net, pad_box, pos, box, has_box,   # noqa: E402,F401
                          sample_points, pt_box_dist, seg_box_dist, _first_true, _CACHE)


# ----------------------------------------------------------------------------------------------------- helpers
def analog_refs(b, cfg):
    """the analog parts that exist on this board and have a courtyard, sorted"""
    return sorted(r for r in cfg.ANALOG_REFS if has_box(b, r))


# ----------------------------------------------------------------------------------------------------- LR-1
def kit_cfg_lr1(cfg):
    """this board configuration's names for pcbkit's ground_plane and bottom_hops: the project names are the AFE's own tables, the
    tunables the AFE sets (HOP_MAX, HOP_MAX_VIAS, ZONE_PAD) are passed, and every other tunable keeps the kit's default (which is the
    value LR-1 always used)"""
    return dict(GND=cfg.GND, PLANE_LAYER='B',
                HOP_FENCES=[rc for blk in cfg.ANALOG_FENCE for rc in cfg.OUTLINE.get(blk, [])], HOP_SENSITIVE=cfg.XSENS,
                HOP_KEEPOUT_PARTS=cfg.ANALOG_REFS, HOP_KEEPOUT_PAD=cfg.ZONE_PAD, HOP_MAX=cfg.HOP_MAX, HOP_MAX_VIAS=cfg.HOP_MAX_VIAS)


def bottom_runs(b, cfg):
    return _kit.bottom_runs(b, kit_cfg_lr1(cfg))


def bottom_crossings(b, cfg):
    return _kit.bottom_crossings(b, kit_cfg_lr1(cfg))


def lr1(b, cfg, report=None):
    """LR-1 = pcbkit.rules.ground_plane + bottom_hops on this board's configuration, in the printed order the goldens fix: layers and
    zones, the hops, then the ground vias. `report`, a list, receives the effective configuration of both rules"""
    kc = kit_cfg_lr1(cfg)
    plane, vias, gfig = _kit.ground_plane_parts(b, kc, report)
    hops, hfig = _kit.bottom_hops_parts(b, kc, report)
    bad = plane + hops + vias
    fig = dict(layers=gfig['layers'], bottom_pieces=gfig['plane_pieces'], bottom_runs=hfig['runs'], max_run_mm=hfig['max_run_mm'],
               max_run_vias=hfig['max_run_vias'], gnd_pads=gfig['gnd_pads'], pads_without_via=gfig['pads_without_via'],
               violations=float(len(bad)))
    return Result(not bad, '; '.join(bad[:6]) or f'2 layers, one bottom plane, {int(hfig["runs"])} bottom runs, {int(gfig["gnd_pads"])} GND pads each with its own via', fig)


# ----------------------------------------------------------------------------------------------------- LR-2
def lr2(b, cfg):
    bad = []
    for ch in cfg.CHANNELS:
        seq = [pad_c(b, *ch['bnc'])[0], pos(b, ch['prot'])[0], pos(b, ch['rnp'])[0], pos(b, ch['opamp'])[0],
               pos(b, ch['riso'])[0], pad_c(b, *ch['adc_pad'])[0]]
        if not all(x > y for x, y in zip(seq, seq[1:])):
            bad.append(f"{ch['name']}: x does not fall {cfg.CH_FLOW_TEXT}: {[round(float(x), 1) for x in seq]}")
        outl = sum(length_of(b, n) for n in ch['out_nets'])
        hiz = sum(length_of(b, n) for n in ch['hiz_nets'])
        if outl <= hiz:
            bad.append(f"{ch['name']}: output run {outl:.1f} mm is not longer than the divider side {hiz:.1f} mm")
    g = pos(b, cfg.GEN[0])
    d5 = float(np.hypot(*(g - pad_c(b, *cfg.FEED_PAD))))
    if d5 > 15:
        bad.append(f'generator {d5:.1f} mm from the 5 V pad')
    dj = {}
    for j in cfg.BNC_REFS:
        dj[j] = float(np.hypot(*(g - pos(b, j))))
        if dj[j] < 50:
            bad.append(f'generator {dj[j]:.0f} mm from {j}')
    dref = {}
    for r in cfg.QUIET_REFS:
        dref[r] = min(float(geom.box_dist(box(b, r), box(b, x))[0, 0]) for x in cfg.GEN)
        if dref[r] < cfg.KEEPOUT:
            bad.append(f'{r} only {dref[r]:.1f} mm from the generator')
    pt = pads(b)
    px, py = b.p_x[pt.rows], b.p_y[pt.rows]
    names = np.array(b.nets)[pt.net] if len(pt.rows) else np.array([])
    P = np.column_stack([px, py])
    G = [P[np.isin(names, list(g)) & (px < cfg.DIVIDER_X_MAX)] for g in cfg.DIVIDER_GROUPS]
    gap = min(float(np.hypot(A[:, None, 0] - B[None, :, 0], A[:, None, 1] - B[None, :, 1]).min())
              for i, A in enumerate(G) for B in G[i + 1:])
    if gap < 5.0:
        bad.append(f"channels' divider pads only {gap:.1f} mm apart")
    fig = dict(divider_gap_mm=gap, generator_to_5v_mm=d5, **{f'generator_to_{j}_mm': v for j, v in dj.items()},
               **{f'{r}_to_generator_mm': v for r, v in dref.items()})
    return Result(not bad, '; '.join(bad[:5]) or f'flow, generator, quiet zone and channel separation hold (closest divider pads {gap:.1f} mm)', fig)


# ----------------------------------------------------------------------------------------------------- LR-3
def lr3(b, cfg, report=None):
    """LR-3 = pcbkit.rules.sensitive_nets on the divider nets: no via, at most 14 mm of top track, no other net's top track within 0.6 mm"""
    fnd, fig = _kit.sensitive_nets_parts(b, dict(GND=cfg.GND, SENSITIVE_NETS=[dict(net=n, no_via=True, max_length=14, gap=0.6) for n in cfg.HIZ]), report)
    bad = []
    for f in fnd:
        bad.append({'via': f'{f.net}: a via', 'length': f'{f.net}: {f.value:.1f} mm of track',
                    'beside': f'{f.net} track within 0.6 mm of {f.other} track'}[f.kind])
    return Result(not bad, '; '.join(sorted(set(bad))[:6]) or f'{len(cfg.HIZ)} divider nets: no via, short, no track beside',
                  dict(nets=fig['nets'], longest_mm=fig['longest_mm'], tracks_too_close=fig['tracks_too_close']))


# ----------------------------------------------------------------------------------------------------- LR-4
POUR_KEEP_BACK = 0.5      # LR-4: the top ground pour stays at least this far from an inverting node's copper (a design value, afe.md)


def _pour_cfg(cfg):
    return dict(GND=cfg.GND, POUR_NODES=cfg.POUR_NODES, POUR_INFO_NODES=getattr(cfg, 'POUR_INFO_NODES', ()), POUR_KEEP_BACK=POUR_KEEP_BACK)


def pour_gaps(b, cfg):
    """[(node net, gap to top GND tracks, gap to top GND pour fills)] for every cfg.POUR_NODES node (and POUR_INFO_NODES): pcbkit.rules.pour_gaps"""
    return _kit.pour_gaps(b, _pour_cfg(cfg))


def lr4(b, cfg, report=None):
    bad = []
    for f in _kit.sensitive_nets_parts(b, dict(GND=cfg.GND, SENSITIVE_NETS=[dict(net=n, no_via=True, no_bottom=True) for n in cfg.ADC_NETS]), report)[0]:
        bad.append(f'{f.net}: a via' if f.kind == 'via' else f'{f.net}: bottom copper')
    for ch in cfg.CHANNELS:
        if float(np.hypot(*(pad_c(b, ch['riso'], '1') - pad_c(b, *ch['out_pin'])))) > 5:
            bad.append(f"{ch['riso']} not at the output pin")
    for cap, ic, pin in cfg.SUPPLY_CAPS:
        d = float(np.hypot(*(pad_c(b, cap, '1') - pad_c(b, ic, pin))))
        if d > 12:
            bad.append(f'{cap} {d:.0f} mm from its supply pin')
    for f in _kit.sensitive_nets_parts(b, dict(GND=cfg.GND, SENSITIVE_NETS=[dict(net=n, no_via=True, no_bottom=True) for n in cfg.INV_NODES]), report)[0]:
        bad.append(f'{f.net}: inverting node has a via' if f.kind == 'via' else f'{f.net}: inverting node has bottom copper')
    fb_net = cfg.AWG['fb_net']
    L = length_of(b, fb_net)
    if _kit.sensitive_nets_parts(b, dict(GND=cfg.GND, SENSITIVE_NETS=[dict(net=fb_net, no_via=False, max_length=cfg.FB_MAX)]), report)[0]:
        bad.append(f'AWG inverting node {L:.1f} mm of track (limit {cfg.FB_MAX})')
    near, gaps = set(), {}
    pgaps, pnear = _kit.pour_gap_parts(b, _pour_cfg(cfg), report)
    for net, g_trk, g_pour in pgaps:
        gaps[net[1:]] = (g_trk, g_pour)
    for net, kind in pnear:
        tag = '' if net == fb_net else ' ' + net[1:]
        near.add(('GND track' if kind == 'track' else 'top pour') + tag)
    if near:
        bad.append(f'top ground copper within {POUR_KEEP_BACK} mm of the inverting node ({sorted(near)})')
    lens = [length_of(b, n) for n in cfg.ADC_NETS]
    names = '/'.join(n[1:] for n in cfg.ADC_NETS)
    return Result(not bad, '; '.join(bad[:5]) or f'{names} top only, no via (' + '/'.join(f'{x:.0f}' for x in lens) + ' mm); '
                  f'FB node {L:.1f} mm of track; decoupling near; no pour within {POUR_KEEP_BACK} mm of it',
                  dict(**{f'{n[1:].lower()}_mm': x for n, x in zip(cfg.ADC_NETS, lens)}, fb_mm=L, violations=float(len(bad)),
                       **{f'gnd_track_gap_{n}_mm': g[0] for n, g in gaps.items()}, **{f'pour_gap_{n}_mm': g[1] for n, g in gaps.items()}))


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
from pcbkit.rules import decoup_dist                       # noqa: E402,F401  (re-exported)


def lr12(b, cfg, report=None):
    """LR-12 = pcbkit.rules.decoupling on the AFE's DECOUP table"""
    return _kit.decoupling(b, dict(DECOUPLING=cfg.DECOUP, DECOUPLING_MAX=cfg.DECOUP_MAX), report)


# ----------------------------------------------------------------------------------------------------- LR-5
def lr5(b, cfg, report=None):
    """LR-5 = pcbkit.rules.keepout_ring: sensitive copper keeps cfg.KEEPOUT from the generator's courtyards"""
    return _kit.keepout_ring(b, dict(KEEPOUT_PARTS=cfg.GEN, KEEPOUT_NETS=cfg.SENSITIVE, KEEPOUT_EXEMPT_PARTS=cfg.GENERATOR_BLOCK,
                                     KEEPOUT_DIST=cfg.KEEPOUT), report)


# ----------------------------------------------------------------------------------------------------- pieces of copper
def family(cfg, net):
    """the nets that are ONE electrical net with `net`: the nets joined through the 0 ohm bridge parts (cfg.BRIDGES, (ref, net a,
    net b)), transitively. A supply rail is split by its bridges into `+3V3A`, `+3V3A_K`, `+3V3A_S`, `+3V3A_U`, `+3V3A_R` and a
    rule about the rail's copper must see them as one, or a consumer behind a bridge is on no net it can be found on."""
    br = [(a, c) for _, a, c in getattr(cfg, 'BRIDGES', ())]
    fam = {net}
    grow = True
    while grow:
        grow = False
        for a, c in br:
            if (a in fam) != (c in fam):
                fam |= {a, c}
                grow = True
    return fam


def _graph(b, cfg, net, cut=()):
    """Connectivity of the copper of one electrical net (`family(cfg, net)`), every copper layer: tracks and arcs (chords) on F.Cu
    and B.Cu, vias, pads, and the fill of every filled zone of the net. The pads in `cut` are removed. Returns
    (count, labels, pad keys, label of each pad key's node)."""
    fam = family(cfg, net)
    ids = [i for i in (nid(b, n) for n in fam) if i >= 0]
    srow = np.flatnonzero(np.isin(b.s_net, ids) & (b.s_layer < 2))
    S = segs(b)[srow]
    SL = b.s_layer[srow].astype(np.int64)
    arow = np.flatnonzero(np.isin(b.a_net, ids) & (b.a_layer < 2)) if len(b.a_idx) else np.zeros(0, np.int64)
    if len(arow):                                          # an arc is the two chords start-mid and mid-end
        A = np.column_stack([b.a_x0, b.a_y0, b.a_xm, b.a_ym, b.a_x1, b.a_y1])[arow]
        S = np.vstack([S, A[:, :4], A[:, 2:]])
        SL = np.concatenate([SL, b.a_layer[arow], b.a_layer[arow]]).astype(np.int64)
    vrow = np.flatnonzero(np.isin(b.v_net, ids))
    pt = pads(b)
    cutset = set(cut)
    pj = [j for j in np.flatnonzero(np.isin(pt.net, ids)) if pt.keys[j] not in cutset]
    prow = pt.rows[pj]
    pkeys = [pt.keys[j] for j in pj]
    ns, nv, npd = len(S), len(vrow), len(prow)
    V = np.column_stack([b.v_x[vrow], b.v_y[vrow]])
    PB = pad_box(b, prow)
    PM = b.p_layer_mask[prow].astype(np.int64)
    J = []
    if ns:
        P0, P1 = S[:, :2], S[:, 2:]
        D0, D1 = geom.point_seg_dist(P0, S), geom.point_seg_dist(P1, S)       # [a, b]: end of a to the line of b
        e = np.minimum.reduce([np.hypot(P0[:, None, 0] - P0[None, :, 0], P0[:, None, 1] - P0[None, :, 1]),
                               np.hypot(P0[:, None, 0] - P1[None, :, 0], P0[:, None, 1] - P1[None, :, 1]),
                               np.hypot(P1[:, None, 0] - P0[None, :, 0], P1[:, None, 1] - P0[None, :, 1]),
                               np.hypot(P1[:, None, 0] - P1[None, :, 0], P1[:, None, 1] - P1[None, :, 1])])
        T = ((e < 0.02) | (D0 < 0.05) | (D1 < 0.05) | (D0.T < 0.05) | (D1.T < 0.05)) & (SL[:, None] == SL[None, :])
        a, c = np.nonzero(np.triu(T, 1))
        J.append(np.column_stack([a, c]))
        if nv:
            a, c = np.nonzero(geom.point_seg_dist(V, S) < 0.05)                # a via spans every layer
            J.append(np.column_stack([c, ns + a]))
        if npd:
            hit = geom.seg_in_box(S, PB, pad=0.02) & (((PM[None, :] >> SL[:, None]) & 1) > 0)    # the pad must reach the track's layer
            a, c = np.nonzero(hit)
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
    # zone fills: one node per outline ring (a fractured pour is several pieces); an item joins the node when one of its points
    # (a track's ends and middle, a via's centre, a pad's centre) lies in the fill, even-odd and hole-aware, on the zone's layer
    nzn = 0
    zs = [z for z in range(len(b.z_layer)) if b.z_filled[z] and not b.z_keepout[z] and b.z_net[z] in ids and b.z_layer[z] < 2]
    if zs:
        pts = np.vstack([S[:, :2], S[:, 2:], (S[:, :2] + S[:, 2:]) / 2, V, np.column_stack([b.p_x[prow], b.p_y[prow]])]) if (ns or nv or npd) \
            else np.zeros((0, 2))
        item = np.concatenate([np.tile(np.arange(ns), 3), ns + np.arange(nv), ns + nv + np.arange(npd)]).astype(np.int64)
        layer_ok = np.concatenate([np.tile(SL, 3), np.full(nv, -1), np.full(npd, -1)])
        for z in zs:
            r0, r1 = b.z_ring_off[z], b.z_ring_off[z + 1]
            off = b.z_vert_off[r0:r1 + 1]
            inside = geom.points_in_polys(pts, b.z_xy[off[0]:off[-1]], off - off[0], hole=b.z_ring_hole[r0:r1]) if len(pts) \
                else np.zeros((0, int((b.z_ring_hole[r0:r1] == 0).sum())), bool)
            for col in range(inside.shape[1]):
                node = ns + nv + npd + nzn
                nzn += 1
                m = inside[:, col]
                m &= (layer_ok == b.z_layer[z]) | (layer_ok == -1)
                if npd:                                      # a pad joins a zone it reaches: its layer mask has the zone's layer
                    pm = np.zeros(len(pts), bool)
                    pm[ns * 3 + nv:] = ((PM >> int(b.z_layer[z])) & 1) > 0
                    m &= np.where(np.arange(len(pts)) >= ns * 3 + nv, pm, True)
                if m.any():
                    J.append(np.column_stack([item[m], np.full(int(m.sum()), node)]))
                else:
                    J.append(np.zeros((0, 2), np.int64))
    for (ra, pa, rb, pb) in list(cfg.BRIDGE_PADS) + [(r, '1', r, '2') for r, _, _ in getattr(cfg, 'BRIDGES', ())]:
        ia = [i for i, k in enumerate(pkeys) if k == (ra, pa)]
        ib = [i for i, k in enumerate(pkeys) if k == (rb, pb)]
        if ia and ib:
            J.append(np.array([[ns + nv + ia[0], ns + nv + ib[0]]]))
    n = ns + nv + npd + nzn
    if not n:
        return 0, np.zeros(0, np.int32), pkeys, np.zeros(0, np.int32)
    k, lab = geom.connected_components(n, np.vstack(J) if J else np.zeros((0, 2), np.int64))
    return k, lab, pkeys, lab[ns + nv:ns + nv + npd]


def pieces_keys(b, cfg, net, cut=()):
    """connected pieces of one electrical net's copper (see `_graph`): a list of sets of pad keys (ref, pin), one per piece in
    order of first member, pad-less pieces (a track and nothing else) included as empty sets"""
    k, _, pkeys, plab = _graph(b, cfg, net, cut)
    groups = [set() for _ in range(k)]
    for key, lb in zip(pkeys, plab):
        groups[lb].add(key)
    return groups


def pieces(b, cfg, net, cut=()):
    """connected pieces of one electrical net's copper, the pads in `cut` removed: a list of sets of refs, one per piece, in
    order of first member.

    The net is `family(cfg, net)`: the nets the 0 ohm bridges join are one. Copper is tracks on BOTH layers, vias, pads and
    the fill of the net's filled zones; a track and a pad touch only on a layer the pad has; a pad of cfg.BRIDGE_PADS and the two
    pads of every bridge part are joined.

    Touch rules, as the old tool, exact instead of sampled: two tracks of one layer touch when an end of one is within 0.02 of
    an end of the other or within 0.05 of the other's centre line; a track and a via when the via centre is within 0.05 of the
    centre line; a track and a pad when the centre line enters the pad's box grown by 0.02; two vias within 0.05; a via and a
    pad when the via centre lies in the pad's box grown by 0.02; two pads never (a part does not join its pads, except the
    bridges). Track widths are not used."""
    return [{key[0] for key in g} for g in pieces_keys(b, cfg, net, cut)]


def _reached(b, cfg, net, targets, cut=()):
    """{pad key: True when its piece also holds one of `targets`} over the pads of the net's family, nothing cut by default"""
    k, lab, pkeys, plab = _graph(b, cfg, net, cut)
    tl = {int(lb) for key, lb in zip(pkeys, plab) if key in targets}
    return {key: int(lb) in tl for key, lb in zip(pkeys, plab)}


def _names(keys, n=4):
    ks = [f'{k[0]}.{k[1]}' for k in sorted(keys)]
    return ', '.join(ks[:n]) + (f' (+{len(ks) - n})' if len(ks) > n else '')


# ----------------------------------------------------------------------------------------------------- LR-6
def lr6(b, cfg):
    """Each rail's supply copper is a star. Two things are checked on the rail's ELECTRICAL net (the nets its 0 ohm bridges
    join): every present consumer group's supply pads reach a star pad through copper (an unrouted branch is not a star
    leg), and with the star pads cut no piece of copper serves two groups."""
    bad, npieces, reached, absent = [], 0, 0, 0
    pt = pads(b)
    refs_on_board = set(b.fp_ref)
    for net, groups in cfg.GROUPS.items():
        cut = list(cfg.STAR[net])
        have = {pt.keys[j] for j in np.flatnonzero(pt.net == nid(b, net))}
        missing = [f'{k[0]}.{k[1]}' for k in cut if k not in have]
        if missing:
            bad.append(f'{net}: star pads {missing} are not on the net')
        else:
            fam = [i for i in (nid(b, n) for n in family(cfg, net)) if i >= 0]
            famkeys = [pt.keys[j] for j in np.flatnonzero(np.isin(pt.net, fam))]
            ok = _reached(b, cfg, net, set(cut))
            for g, refs in groups.items():
                if not refs & refs_on_board:
                    absent += 1                                  # the group's parts are not on this board: nothing to reach
                    continue
                gk = [k for k in famkeys if k[0] in refs]
                lost = [k for k in gk if not ok[k]]
                if not gk:
                    bad.append(f'{net}: consumer group {g} has no supply pad on the rail')
                elif lost:
                    bad.append(f'{net}: consumer group {g} is not connected to the star: {_names(lost)} unreachable by copper')
                else:
                    reached += 1
        for pc in pieces(b, cfg, net, cut):
            npieces += 1
            hit = sorted(g for g, refs in groups.items() if pc & refs)
            if len(hit) > 1:
                bad.append(f'{net}: one piece of copper serves {hit}')
    return Result(not bad, '; '.join(bad[:5]) or '+3V3A and VNEG: one piece per consumer group after cutting the star pads',
                  dict(pieces=float(npieces), groups_reached=float(reached), groups_absent=float(absent), violations=float(len(bad))))


# ----------------------------------------------------------------------------------------------------- LR-7
def lr7(b, cfg):
    awg = cfg.AWG
    dac = awg['dac_net'][1:]
    bad = []
    L = length_of(b, awg['dac_net'])
    if L > 12:
        bad.append(f'{dac} {L:.1f} mm of track')
    dr = {}
    for r in awg['back_term']:
        dr[r] = float(np.hypot(*(pos(b, r) - pos(b, awg['bnc']))))
        if dr[r] > 16:
            bad.append(f"{r} {dr[r]:.0f} mm from {awg['bnc']}")
    j = b.ref_index(awg['bnc'])
    shell = int(((b.p_fp == j) & (np.asarray(b.p_pin, dtype=object) == awg['shell_pin']) & (b.p_net == nid(b, cfg.GND))).sum())
    if shell < 3:
        bad.append(f'{shell} BNC shell pads on ground')
    return Result(not bad, '; '.join(bad) or f'{dac} {L:.1f} mm; back-termination at the BNC; shell pads on ground',
                  dict(**{f'{dac.lower()}_mm': L}, shell_pads=float(shell), **{f"{r}_to_{awg['bnc']}_mm": v for r, v in dr.items()}))


# ----------------------------------------------------------------------------------------------------- LR-8
def lr8(b, cfg):
    """The reference is routed by Kelvin: on its electrical net (through the bridges) every branch's pads reach a source pad
    (a branch with no copper to the source is not routed), and with the source pads cut no piece serves two branches."""
    src = [tuple(k) for k in cfg.VREF_SOURCE]
    cut = set(src)
    refs_of = [{k[0] for k in g} for g in cfg.VREF_BRANCHES]
    bad, reached, skipped = [], 0, 0
    pt = pads(b)
    refs_on_board = set(b.fp_ref)
    if {k[0] for k in src} & refs_on_board:
        fam = [i for i in (nid(b, n) for n in family(cfg, cfg.VREF_NET)) if i >= 0]
        onnet = {pt.keys[j] for j in np.flatnonzero(np.isin(pt.net, fam))}
        gone = [f'{k[0]}.{k[1]}' for k in src if k not in onnet]
        if gone:
            bad.append(f'VREF: source pads {gone} are not on the net')
        else:
            ok = _reached(b, cfg, cfg.VREF_NET, cut)
            for i, g in enumerate(cfg.VREF_BRANCHES):
                ks = [tuple(k) for k in g if tuple(k) in onnet]
                lost = [k for k in ks if not ok[k]]
                if not ks:
                    skipped += 1
                elif lost:
                    bad.append(f'VREF: branch {i} ({_names(lost)}) is not connected to the source {_names(src)} by copper')
                else:
                    reached += 1
    else:
        skipped = len(cfg.VREF_BRANCHES)                       # the source is not on this board
    for pc in pieces(b, cfg, cfg.VREF_NET, cut):
        hit = sorted(k for k, g in enumerate(refs_of) if pc & g)
        if len(hit) > 1:
            bad.append(f'VREF: branches {hit} share copper ({sorted(pc)[:6]})')
    return Result(not bad, '; '.join(bad[:4]) or f'VREF: {len(cfg.VREF_BRANCHES)} branches each on its own copper',
                  dict(branches=float(len(cfg.VREF_BRANCHES)), branches_reached=float(reached), branches_unchecked=float(skipped),
                       violations=float(len(bad))))


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


def _box_corners(x, y, length, height, ang):
    """corners (4,2) of a text box of `length` x `height` centred on (x, y), turned by ang degrees (a box is symmetric under
    180 degrees, so the sign of the angle, which the y flip of the Due frame reverses, does not matter)"""
    c, s_ = np.cos(np.radians(ang)), np.sin(np.radians(ang))
    u, v = np.array([c, s_]) * length / 2, np.array([-s_, c]) * height / 2
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


def designator_findings(b, cfg):
    """the visible silk designators judged as boxes (LR-11, legibility): ([(refA, refB, gap)] pairs closer than
    DESIGNATOR_GAP_MIN, [(ref, other ref)] a box over another part's pad, [(ref, distance)] a box farther than
    DESIGNATOR_DIST_MAX from every pad of its own part, number of designators judged). The box is the text's height by
    len(designator) x DESIGNATOR_ADVANCE x height (the stroke font's character advance is an assumption, marked (check) in the
    config); text is taken as centred on its position."""
    rows = [k for k in range(len(b.r_fp)) if b.r_on_silk[k] and int(b.r_layer[k]) == 0]
    refs = list(b.fp_ref)
    box = {}
    for k in rows:
        ref = refs[int(b.r_fp[k])]
        box[ref] = _box_corners(b.r_x[k], b.r_y[k], len(ref) * cfg.DESIGNATOR_ADVANCE * b.r_h[k], cfg.DESIGNATOR_INK_H * b.r_h[k], b.r_ang[k])
    names = sorted(box)
    close = []
    for i, a in enumerate(names):
        A = box[a]
        for c in names[i + 1:]:
            Bx = box[c]
            if A[:, 0].min() - cfg.DESIGNATOR_GAP_MIN > Bx[:, 0].max() or Bx[:, 0].min() - cfg.DESIGNATOR_GAP_MIN > A[:, 0].max() \
                    or A[:, 1].min() - cfg.DESIGNATOR_GAP_MIN > Bx[:, 1].max() or Bx[:, 1].min() - cfg.DESIGNATOR_GAP_MIN > A[:, 1].max():
                continue
            g = _convex_gap(A, Bx)
            if g < cfg.DESIGNATOR_GAP_MIN:
                close.append((a, c, round(float(g), 2)))
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
            if d > cfg.DESIGNATOR_DIST_MAX:
                far.append((ref, round(float(d), 2)))
    return close, over, far, len(box)


def _label_boxes(b, cfg):
    refs = list(b.fp_ref)
    return {refs[int(b.r_fp[k])]: _box_corners(b.r_x[k], b.r_y[k], len(refs[int(b.r_fp[k])]) * cfg.DESIGNATOR_ADVANCE * b.r_h[k],
                                              cfg.DESIGNATOR_INK_H * b.r_h[k], b.r_ang[k])
            for k in range(len(b.r_fp)) if b.r_on_silk[k] and int(b.r_layer[k]) == 0}


def one_label_pairs(b, cfg):
    """[(refA, refB, gap)] pairs of visible designators that READ AS ONE LABEL: on a common baseline (the vertical extents of the
    two boxes overlap by more than half of the smaller one) and the horizontal gap under cfg.DESIGNATOR_GAP_ONE_LABEL (touching or
    overlapping included). The waiver list cannot cover them: whatever DRC says, 'C401C402' is one word to a reader."""
    box = _label_boxes(b, cfg)
    lim = cfg.DESIGNATOR_GAP_ONE_LABEL
    names = sorted(box)
    out = []
    for i, a in enumerate(names):
        A = box[a]
        for c in names[i + 1:]:
            Bx = box[c]
            dx = max(0.0, max(Bx[:, 0].min() - A[:, 0].max(), A[:, 0].min() - Bx[:, 0].max()))
            ov = min(A[:, 1].max(), Bx[:, 1].max()) - max(A[:, 1].min(), Bx[:, 1].min())
            if dx < lim and ov > 0.5 * min(np.ptp(A[:, 1]), np.ptp(Bx[:, 1])):
                out.append((a, c, round(float(dx), 2)))
    return out


def foreign_labels(b, cfg):
    """[(ref, block it sits in)] visible designators whose centre lies inside another block's outline than the one holding their part
    (a part with no block of its own, a shared part and the edge block's parts are not judged)"""
    box = _label_boxes(b, cfg)
    shared = getattr(cfg, 'SHARED_PARTS', {})
    out = []
    for ref, B in box.items():
        home = cfg.BLOCK.get(ref)
        if home is None or home == cfg.EDGE_BLOCK or ref in shared or ref in cfg.BLOCK_OVERRIDE:
            continue
        ctr = B.mean(axis=0, keepdims=True)
        for blk, rects in cfg.OUTLINE.items():
            if blk != home and _in_rects(ctr, rects)[0] and getattr(cfg, 'DESIGNATOR_FOREIGN_WAIVED', {}).get(ref) != blk:
                out.append((ref, blk))
    return sorted(out)


def lr11(b, cfg):
    bad = []
    blocks = {}
    for r, blk in cfg.BLOCK.items():
        if blk != cfg.EDGE_BLOCK or r in cfg.BLOCK_OVERRIDE:
            blocks.setdefault(blk, set()).add(r)
    blocks.pop(cfg.EDGE_BLOCK, None)
    refs = list(b.fp_ref)
    P = np.column_stack([b.fp_x, b.fp_y])
    candidate = np.array([(r in cfg.BLOCK and cfg.BLOCK[r] != cfg.EDGE_BLOCK) or r in cfg.BLOCK_OVERRIDE for r in refs], bool)
    shared = getattr(cfg, 'SHARED_PARTS', {})          # ref -> the block whose outline holds a part that straddles two
    margin = getattr(cfg, 'SHARED_MARGIN', 0.0)
    for blk, rects in cfg.OUTLINE.items():
        inside = {refs[i] for i in np.flatnonzero(candidate & _in_rects(P, rects))}
        for r, home in shared.items():                 # a shared part is held to its home outline (within the margin: its
            if r in refs:                              # centre sits on the edge) and is no extra part in any other
                i = refs.index(r)
                inside.discard(r)
                if home == blk and _in_rects(P[i:i + 1], [(x0 - margin, y0 - margin, x1 + margin, y1 + margin)
                                                          for x0, y0, x1, y1 in rects])[0]:
                    inside.add(r)
        want = blocks.get(blk, set()) - set(getattr(cfg, 'OUTLINE_STRAYS', ()))   # D30 (1c): named parts may sit outside their own
        inside -= set(getattr(cfg, 'OUTLINE_STRAYS', ())) & blocks.get(blk, set())  # block's rectangle; never inside another's
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
    have = {bof[i] for i, r in enumerate(refs) if r.startswith(cfg.TP_PREFIX) and (r, cfg.TP_PIN) in pt.lookup}
    for blk in sorted(set(cfg.TEST_BLOCKS) - have):
        bad.append(f'block {blk} has no test point')
    refrow = {int(f): i for i, f in enumerate(b.r_fp)}
    ndes = 0
    nwaived = 0
    noff = 0
    required = getattr(cfg, 'SILK_REQUIRED_PREFIXES', None)   # D30 (owner, 2026-11-17): only these must carry a silk designator;
    for i, r in enumerate(refs):                              # any other part may move its designator to F.Fab, found through the ibom
        ndes += 1
        k = refrow.get(i)
        on = k is not None and b.r_on_silk[k] and b.r_h[k] >= cfg.DESIGNATOR_MIN_H
        if on:
            continue
        anchor = required is None or r.rstrip('0123456789') in required
        if not anchor and k is not None and int(b.r_layer[k]) == 2:      # 2: boardio.R_LAYERS['F.Fab']
            noff += 1
            continue
        bad.append(f'{r}: designator not on silk at 0.8 mm or more'
                   + ('' if anchor else ', and not on F.Fab either'))
    for r, n in cfg.TP_NETS.items():
        if (r, cfg.TP_PIN) not in pt.lookup or pad_net(b, r, cfg.TP_PIN) != n:
            bad.append(f'{r}: missing or not on {n}')
    if hasattr(cfg, 'DESIGNATOR_GAP_MIN'):                 # legibility: only a config that sets the thresholds is held to it
        close, over, far, njudged = designator_findings(b, cfg)
        waived = getattr(cfg, 'DESIGNATOR_GAP_WAIVED', {})   # {(refA, refB): the least gap accepted for that pair}: pairs the room
        kept = [t for t in close if not (t[2] >= waived.get((t[0], t[1]), 9e9))]       # does not allow, each with its recorded floor
        nwaived = len(close) - len(kept)
        close = kept
        one = one_label_pairs(b, cfg) if hasattr(cfg, 'DESIGNATOR_GAP_ONE_LABEL') else []
        if one:
            bad.append(f'{len(one)} designator pairs read as one label (same baseline, under {cfg.DESIGNATOR_GAP_ONE_LABEL} mm, no waiver): '
                       + ', '.join(f'{a}/{c} {g}' for a, c, g in one[:12]) + (' ...' if len(one) > 12 else ''))
        foreign = foreign_labels(b, cfg)
        if foreign:
            bad.append('designator inside another block\'s outline: ' + ', '.join(f'{a} in {c}' for a, c in foreign[:12]))
        if close:
            bad.append(f'{len(close)} designator pairs closer than {cfg.DESIGNATOR_GAP_MIN} mm: '
                       + ', '.join(f'{a}/{c} {g}' for a, c, g in close[:12]) + (' ...' if len(close) > 12 else ''))
        if over:
            bad.append('designator over another part\'s pad: ' + ', '.join(f'{a} on {c}' for a, c in over[:12]))
        if far:
            bad.append(f'designator more than {cfg.DESIGNATOR_DIST_MAX} mm from its part: ' + ', '.join(f'{a} {d}' for a, d in far[:12]))
    npin = 0
    if hasattr(cfg, 'EDGE_SOCKETS'):                       # the Due's pin names in the bands (pcbtools/pinlabels.py): only a config that names its edge sockets
        from . import pinlabels
        pin_bad = pinlabels.findings(b, cfg)
        bad += pin_bad
        _pl = pinlabels.plan_labels(b, cfg)
        npin = len(_pl)
        pinsize = f' ({_pl[0].h} x {_pl[0].w} mm, overhang {cfg.OVERHANG} mm)' if _pl else ''
    nid = ''
    if getattr(cfg, 'IDENTITY_CHECK', False):                              # the name / model / revision / serial box / order-number text (pcbtools/identity.py), and no arrow heads
        from . import identity, silkarrows
        _path = getattr(b, 'path', '')
        if _path and str(_path).endswith('.kicad_pcb') and os.path.isfile(_path):
            _txt = open(_path).read()
            bad += identity.findings(_txt, cfg)
            bad += [f'silk arrow head: {h}' for h in silkarrows.arrowheads(silkarrows.silk_segments(_txt))[:4]]
        if getattr(cfg, 'ARROWS', None):
            bad.append(f'{len(cfg.ARROWS)} arrows in the config: board silk carries no arrows')
        nid = ', identity silk'
    names = set(b.t_text)
    for w in cfg.SILK_WORDS:
        if w not in names:
            bad.append(f'silk word {w!r} missing')
    note = f', {nwaived} designator pairs under the gap on their recorded floors' if nwaived else ''
    if noff:
        note += f', {noff} passive designators on F.Fab (found through the ibom)'
    return Result(not bad, '; '.join(bad[:8]) or f'{len(cfg.OUTLINE)} outlines hold exactly their parts, {ndes} designators, 8 test points{note}' + (f', {npin} pin labels{pinsize}' if npin else '') + nid,
                  dict(outlines=float(len(cfg.OUTLINE)), designators=float(ndes), violations=float(len(bad)), waived_pairs=float(nwaived)))


ROWS = [('LR-1', lr1), ('LR-2', lr2), ('LR-3', lr3), ('LR-4', lr4), ('LR-4 INV_MAX', lr4_inv), ('LR-12 DECOUP_MAX', lr12),
        ('LR-5', lr5), ('LR-6', lr6), ('LR-7', lr7), ('LR-8', lr8), ('LR-9', lr9), ('LR-11', lr11)]
