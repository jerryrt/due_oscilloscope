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
pcbkit.geom. Figures that came from the closest sample (LR-5's distances) can therefore be smaller by up to the
sample step; verdicts agree on every fixture. tests/pcbtools/test_rules_equivalence.py lists each difference.
"""
from __future__ import annotations

import dataclasses
import math
import weakref

import os

import numpy as np
from scipy.spatial import cKDTree

from pcbkit import geom


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
from pcbkit.rules import _box_corners, _convex_gap, _label_boxes      # noqa: E402,F401  (pinlabels reads them from here)
from pcbkit.outlines import in_rects as _in_rects                      # noqa: E402,F401

_LR11_NAMES = ('BLOCK', 'OUTLINE', 'OUTLINE_STRAYS', 'EDGE_BLOCK', 'BLOCK_OVERRIDE', 'SHARED_PARTS', 'SHARED_MARGIN', 'TEST_BLOCKS', 'TP_NETS',
               'TP_PREFIX', 'TP_PIN', 'DESIGNATOR_MIN_H', 'DESIGNATOR_ADVANCE', 'DESIGNATOR_INK_H', 'DESIGNATOR_GAP_MIN', 'DESIGNATOR_DIST_MAX',
               'DESIGNATOR_GAP_ONE_LABEL', 'DESIGNATOR_FOREIGN_WAIVED')


def kit_cfg_lr11(cfg):
    """this configuration's names for pcbkit's blocks, test_points and designators rules: the names the AFE configuration sets are passed under the
    same names (SILK_REQUIRED_PREFIXES as None when it does not set it: every part must carry a silk designator), and the tunables it
    does not set keep the kit's defaults. The AFE's own LR-11 terms (designator numbers, pin labels, identity, silk words, waivers) stay here."""
    kc = {n: getattr(cfg, n) for n in _LR11_NAMES if hasattr(cfg, n)}
    kc['SILK_REQUIRED_PREFIXES'] = getattr(cfg, 'SILK_REQUIRED_PREFIXES', None)
    return kc


def designator_findings(b, cfg):
    return _kit.designator_findings(b, kit_cfg_lr11(cfg))


def one_label_pairs(b, cfg):
    return _kit.one_label_pairs(b, kit_cfg_lr11(cfg))


def foreign_labels(b, cfg):
    return _kit.foreign_labels(b, kit_cfg_lr11(cfg))


def lr11(b, cfg, report=None):
    kc = kit_cfg_lr11(cfg)
    bad = list(_kit.blocks_parts(b, kc, report))
    refs = list(b.fp_ref)
    bof = _kit.block_of_parts(b, kc)
    for i, r in enumerate(refs):
        digits = ''.join(c for c in r if c.isdigit())
        want = cfg.LR_HUNDREDS.get(digits[:1]) if len(digits) >= 3 else None
        if want != bof[i]:
            bad.append(f'{r}: designator number says {want}, the part is in {bof[i]}')
    tp_blocks, tp_nets = _kit.test_points_parts(b, kc, report)
    bad += tp_blocks
    nwaived = 0
    silk_bad, noff, ndes = _kit.silk_required_parts(b, kc, report)       # D30 (owner, 2026-11-17): only the required prefixes must carry a silk designator;
    for r, anchor in silk_bad:                                           # any other part may move its designator to F.Fab, found through the ibom
        bad.append(f'{r}: designator not on silk at 0.8 mm or more' + ('' if anchor else ', and not on F.Fab either'))
    bad += tp_nets
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
