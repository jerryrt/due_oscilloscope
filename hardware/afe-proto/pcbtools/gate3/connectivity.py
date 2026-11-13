"""Copper connectivity of ONE net, built from the board arrays alone (numpy, no pcbnew): the proof behind the gate-3 package's
connectivity section (pcbtools.gate3).

    g = copper_graph(b, net)                   # tracks, vias, pads and the net's own zone fills, as one graph
    g['pad_comp']                              # 'REF.PIN' -> component id
    join_path(g, 'REF.PIN', 'REF.PIN')         # the copper items from one pad to the other, with coordinates

What joins what (all on the one net; a foreign net's copper never joins anything, a no-net item never does):
  track - track   same layer, the two capsules (centre line +- half width) touch or cross
  track - via     the via's annulus (diameter / 2) reaches the track capsule; a via is on both layers
  track - pad     the pad reaches that layer (p_layer_mask) and its bounding box is within half the track width
  via - pad       the via annulus reaches the pad's box on a layer the pad has
  pad - pad       boxes touch on a common layer
  zone fill       a filled zone of the SAME net on a layer: an item on that layer with a sample point inside the fill polygon (even-odd over
                  the zone's rings) is joined to it, and so to everything else the fill touches. Keep-out rule areas are not copper.
Arcs are not modelled; `copper_graph` reports how many arcs the net has (a caller can refuse a net that has any).
A pad's box is its bounding box (a thermal-relief pad in a pour is reached only if a sample point of the box lies in the fill, which a
relief gap prevents: not exercised by the first board this was written for, whose proved net has no zone; ground pours are not this function's subject).
"""
from __future__ import annotations

import numpy as np

TOL = 1e-3
LAYER = ('F.Cu', 'B.Cu')


def _pt_seg(px, py, x0, y0, x1, y1):
    dx, dy = x1 - x0, y1 - y0
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - x0) * dx + (py - y0) * dy) / L2))
    return float(np.hypot(px - (x0 + t * dx), py - (y0 + t * dy)))


def _cross(ax, ay, bx, by, cx, cy):
    return (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)


def seg_seg(a, c):
    """distance between two segments a = (x0, y0, x1, y1), c likewise (0 when they cross)"""
    d1, d2 = _cross(*a, c[0], c[1]), _cross(*a, c[2], c[3])
    d3, d4 = _cross(*c, a[0], a[1]), _cross(*c, a[2], a[3])
    if d1 * d2 < 0 and d3 * d4 < 0:
        return 0.0
    return min(_pt_seg(a[0], a[1], *c), _pt_seg(a[2], a[3], *c), _pt_seg(c[0], c[1], *a), _pt_seg(c[2], c[3], *a))


def pt_box(px, py, box):
    x0, y0, x1, y1 = box
    return float(np.hypot(max(x0 - px, 0.0, px - x1), max(y0 - py, 0.0, py - y1)))


def seg_box(s, box):
    """distance from segment s to an axis-aligned box (0 when it enters it): Liang-Barsky clip, else the nearest corner or end"""
    x0, y0, x1, y1 = s
    bx0, by0, bx1, by1 = box
    t0, t1 = 0.0, 1.0
    for p, q in ((-(x1 - x0), x0 - bx0), (x1 - x0, bx1 - x0), (-(y1 - y0), y0 - by0), (y1 - y0, by1 - y0)):
        if p == 0:
            if q < 0:
                break
        else:
            r = q / p
            if p < 0:
                t0 = max(t0, r)
            else:
                t1 = min(t1, r)
            if t0 > t1:
                break
    else:
        return 0.0
    return min(pt_box(x0, y0, box), pt_box(x1, y1, box),
               *[_pt_seg(cx, cy, *s) for cx, cy in ((bx0, by0), (bx0, by1), (bx1, by0), (bx1, by1))])


def box_box(a, c):
    return float(np.hypot(max(a[0] - c[2], 0.0, c[0] - a[2]), max(a[1] - c[3], 0.0, c[1] - a[3])))


def in_fill(px, py, rings):
    """even-odd point-in-polygon over a zone's rings (outline rings and hole rings alike)"""
    inside = False
    for r in rings:
        x, y = r[:, 0], r[:, 1]
        xn, yn = np.roll(x, -1), np.roll(y, -1)
        with np.errstate(divide='ignore', invalid='ignore'):
            xi = x + (py - y) * (xn - x) / (yn - y)
        hit = ((y > py) != (yn > py)) & (px < xi)
        if hit.sum() % 2:
            inside = not inside
    return inside


def zone_rings(b):
    """per zone: its fill as a list of islands, each island a list of rings (the outline ring first, then its hole rings), Due mm. A fill that
    a slot or a clearance cuts in two is two islands, and copper in different islands is not joined by the fill. Empty for a board with no fill."""
    out = []
    if not len(getattr(b, 'z_net', ())):
        return out
    for z in range(len(b.z_net)):
        isl = []
        for r in range(int(b.z_ring_off[z]), int(b.z_ring_off[z + 1])):
            ring = np.asarray(b.z_xy[int(b.z_vert_off[r]):int(b.z_vert_off[r + 1])], float)
            if int(b.z_ring_hole[r]) == 0 or not isl:
                isl.append([ring])
            else:
                isl[-1].append(ring)
        out.append(isl)
    return out


def copper_graph(b, net, zones=True, drop=()):
    """the copper graph of `net` (a name in b.nets). `zones=False` leaves every zone fill out; `drop` is a set of segment indices
    (positions in the b.s_* arrays) removed, the broken-once arm. Returns dict(nodes, comp, pad_comp, edges, ...)."""
    n = b.nets.index(net)
    drop = set(int(k) for k in drop)
    nodes = []          # (kind, index, label, layers-set, detail)

    def add(kind, i, label, layers, detail):
        nodes.append(dict(kind=kind, i=int(i), label=label, layers=layers, detail=detail))
        return len(nodes) - 1
    segs = [k for k in np.flatnonzero(b.s_net == n) if int(k) not in drop]
    vias = list(np.flatnonzero(b.v_net == n)) if len(b.v_idx) else []
    pads = list(np.flatnonzero(b.p_net == n))
    S, V, P = {}, {}, {}
    for k in segs:
        L = int(b.s_layer[k])
        S[int(k)] = add('track', k, f'track {LAYER[L]} ({b.s_x0[k]:.3f},{b.s_y0[k]:.3f})-({b.s_x1[k]:.3f},{b.s_y1[k]:.3f}) w {b.s_w[k]:.2f}', {L},
                        (float(b.s_x0[k]), float(b.s_y0[k]), float(b.s_x1[k]), float(b.s_y1[k]), float(b.s_w[k])))
    for q in vias:
        V[int(q)] = add('via', q, f'via ({b.v_x[q]:.3f},{b.v_y[q]:.3f}) dia {b.v_dia[q]:.2f}', {0, 1}, (float(b.v_x[q]), float(b.v_y[q]), float(b.v_dia[q])))
    for j in pads:
        m = int(b.p_layer_mask[j])
        lay = {0} if m == 1 else {1} if m == 2 else {0, 1}
        P[int(j)] = add('pad', j, f'{b.fp_ref[b.p_fp[j]]}.{b.p_pin[j]}', lay,
                        (float(b.p_bx0[j]), float(b.p_by0[j]), float(b.p_bx1[j]), float(b.p_by1[j]), float(b.p_x[j]), float(b.p_y[j])))
    edges = []

    def link(i, j, why):
        edges.append((i, j, why))
    ks = list(S)
    for a in range(len(ks)):
        for c in range(a):
            i, j = ks[a], ks[c]
            if b.s_layer[i] != b.s_layer[j]:
                continue
            d = seg_seg((b.s_x0[i], b.s_y0[i], b.s_x1[i], b.s_y1[i]), (b.s_x0[j], b.s_y0[j], b.s_x1[j], b.s_y1[j]))
            if d <= (b.s_w[i] + b.s_w[j]) / 2 + TOL:
                link(S[i], S[j], 'track end meets track')
    for q, vq in V.items():
        r = b.v_dia[q] / 2
        for k, sk in S.items():
            if _pt_seg(b.v_x[q], b.v_y[q], b.s_x0[k], b.s_y0[k], b.s_x1[k], b.s_y1[k]) <= r + b.s_w[k] / 2 + TOL:
                link(vq, sk, 'track reaches via')
        for j, pj in P.items():
            if pt_box(b.v_x[q], b.v_y[q], (b.p_bx0[j], b.p_by0[j], b.p_bx1[j], b.p_by1[j])) <= r + TOL:
                link(vq, pj, 'via inside pad')
    for k, sk in S.items():
        for j, pj in P.items():
            if int(b.s_layer[k]) not in nodes[pj]['layers']:
                continue
            if seg_box((b.s_x0[k], b.s_y0[k], b.s_x1[k], b.s_y1[k]), (b.p_bx0[j], b.p_by0[j], b.p_bx1[j], b.p_by1[j])) <= b.s_w[k] / 2 + TOL:
                link(sk, pj, 'track reaches pad')
    pk = list(P)
    for a in range(len(pk)):
        for c in range(a):
            i, j = pk[a], pk[c]
            if nodes[P[i]]['layers'] & nodes[P[j]]['layers'] and box_box((b.p_bx0[i], b.p_by0[i], b.p_bx1[i], b.p_by1[i]), (b.p_bx0[j], b.p_by0[j], b.p_bx1[j], b.p_by1[j])) <= TOL:
                link(P[i], P[j], 'pad touches pad')
    zl = []
    if zones and len(getattr(b, 'z_net', ())):
        rings = zone_rings(b)
        for z in range(len(b.z_net)):
            if int(b.z_net[z]) != n or not bool(b.z_filled[z]) or bool(b.z_keepout[z]) or not rings[z]:
                continue
            L = int(b.z_layer[z])
            for k, rs in enumerate(rings[z]):
                zi = add('zone', z, f'zone fill {LAYER[L]} net {net} island {k} ({len(rs)} rings)', {L}, ())
                zl.append(zi)
                for kk, sk in S.items():
                    if int(b.s_layer[kk]) == L and any(in_fill(b.s_x0[kk] + u * (b.s_x1[kk] - b.s_x0[kk]), b.s_y0[kk] + u * (b.s_y1[kk] - b.s_y0[kk]), rs) for u in (0, .5, 1)):
                        link(sk, zi, 'track inside fill')
                for q, vq in V.items():
                    if in_fill(b.v_x[q], b.v_y[q], rs):
                        link(vq, zi, 'via inside fill')
                for j, pj in P.items():
                    if L not in nodes[pj]['layers']:
                        continue
                    x0, y0, x1, y1 = b.p_bx0[j], b.p_by0[j], b.p_bx1[j], b.p_by1[j]
                    pts = [(x, y) for x in (x0, (x0 + x1) / 2, x1) for y in (y0, (y0 + y1) / 2, y1)]
                    if any(in_fill(x, y, rs) for x, y in pts):
                        link(pj, zi, 'pad inside fill')
    parent = list(range(len(nodes)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for i, j, _ in edges:
        parent[find(i)] = find(j)
    comp = np.array([find(i) for i in range(len(nodes))], int)
    pad_comp = {nd['label']: int(comp[i]) for i, nd in enumerate(nodes) if nd['kind'] == 'pad'}
    return dict(net=net, nodes=nodes, edges=edges, comp=comp, pad_comp=pad_comp, zones=zl,
                arcs=int((b.a_net == n).sum()) if len(getattr(b, 'a_idx', ())) else 0,
                counts=dict(tracks=len(S), vias=len(V), pads=len(P), zone_fills=len(zl)))


def components(g):
    """connected components as lists of pad labels (sorted), pad-less pieces (a stub) listed with an empty pad list"""
    out = {}
    for i, nd in enumerate(g['nodes']):
        out.setdefault(int(g['comp'][i]), [])
        if nd['kind'] == 'pad':
            out[int(g['comp'][i])].append(nd['label'])
    return sorted((sorted(v) for v in out.values()), key=lambda v: (len(v) == 0, v))


def join_path(g, a, c):
    """shortest chain of copper items from pad `a` to pad `c` (labels like 'REF.PIN'), as (node label, link reason) pairs; None when not joined"""
    ids = {nd['label']: i for i, nd in enumerate(g['nodes']) if nd['kind'] == 'pad'}
    if a not in ids or c not in ids or g['pad_comp'][a] != g['pad_comp'][c]:
        return None
    adj = {}
    for i, j, why in g['edges']:
        adj.setdefault(i, []).append((j, why))
        adj.setdefault(j, []).append((i, why))
    prev = {ids[a]: None}
    q = [ids[a]]
    while q:
        i = q.pop(0)
        if i == ids[c]:
            break
        for j, why in adj.get(i, ()):
            if j not in prev:
                prev[j] = (i, why)
                q.append(j)
    path, i = [], ids[c]
    while i is not None:
        p = prev[i]
        path.append((g['nodes'][i]['label'], p[1] if p else 'start', i))
        i = p[0] if p else None
    return path[::-1]


# ---------------------------------------------------------------------------------------------------- board text (no pcbnew)
import re

_SEG = re.compile(r'\n\t\(segment\n(?:\t\t[^\n]*\n)+?\t\)')


def board_zones(text):
    """every top-level zone of a .kicad_pcb text: name, net ('' for a rule area), layers, keep-out (rule area) or copper, priority (0 when
    the file carries none) and the outline's vertex count"""
    out = []
    for z in re.split(r'\n\t\(zone\n', text)[1:]:
        z = z.split('\n\t)\n')[0]
        net = re.search(r'\(net "([^"]*)"\)', z)
        lay = re.search(r'\(layers? ((?:"[^"]*"\s*)+)\)', z)
        nm = re.search(r'\(name "([^"]*)"\)', z)
        pr = re.search(r'\(priority (\d+)\)', z)
        pts = re.search(r'\(polygon\s*\(pts(.*?)\)\s*\)', z, re.S)
        out.append(dict(name=nm.group(1) if nm else '', net=net.group(1) if net else '', layers=re.findall(r'"([^"]*)"', lay.group(1)) if lay else [],
                        keepout='(keepout' in z, priority=int(pr.group(1)) if pr else 0, vertices=len(re.findall(r'\(xy ', pts.group(1))) if pts else 0))
    return out


def cut_segment_text(text, seg, ox=50.0, oy=150.0, tol=1e-3):
    """the board text with ONE track removed: seg = (x0, y0, x1, y1) in Due mm (KiCad x = ox + x, y = oy - y); either end order. Returns
    (new_text, n_removed); n_removed is 1 when exactly that track was found"""
    x0, y0, x1, y1 = ox + seg[0], oy - seg[1], ox + seg[2], oy - seg[3]
    hit = []
    for m in _SEG.finditer(text):
        s = re.search(r'\(start ([-\d.]+) ([-\d.]+)\)', m.group(0))
        e = re.search(r'\(end ([-\d.]+) ([-\d.]+)\)', m.group(0))
        a, c = (float(s.group(1)), float(s.group(2))), (float(e.group(1)), float(e.group(2)))
        for p, q in (((x0, y0), (x1, y1)), ((x1, y1), (x0, y0))):
            if abs(a[0] - p[0]) < tol and abs(a[1] - p[1]) < tol and abs(c[0] - q[0]) < tol and abs(c[1] - q[1]) < tol:
                hit.append(m)
                break
    if len(hit) != 1:
        return text, len(hit)
    m = hit[0]
    return text[:m.start()] + text[m.end():], 1
