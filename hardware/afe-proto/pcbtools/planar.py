"""Planarity pre-check for one-layer routing of a block (top copper; the bottom layer is the ground plane).

    check(block_nets, pads, rotation, boundary, protected=(), **opts) -> Result
    from_board(b, cfg, block, ...) -> dict of the keyword inputs of check()    (BoardArrays -> inputs)
    rotation_from_pads(pads) -> {ref: [pin, ...]}                              (pin order around each body)
    boundary_order(points, rects) -> [index, ...]                              (order of edge points around a fence)

WHAT IT ANSWERS, BEFORE ANYTHING IS ROUTED: can the block's nets be drawn on one copper layer without crossing, and if not,
how many nets must be bridged (a 0R part, or a hop) and which one. The planarity test is networkx.check_planarity (the
algorithm is not ours; what this module owns is the GRAPH it is applied to, and the reading of the certificate).

THE GRAPH (one vertex per object, edges are things that cannot be crossed or must be connected):
  * a pad that belongs to a net with >= 2 terminals is a vertex; a net is a HUB vertex joined to each of its pads and to each
    of its fence edge points (a star: any Steiner tree is a subdivision of a star, so the star is the loosest model of "the
    net is one connected piece of copper");
  * a part BODY is an obstacle: its pads are a cycle in pin order (the rotation system) plus a body hub joined to every pad of
    the cycle (a wheel), so nothing can lie inside the body and the pins keep their cyclic order. A 2-pad part is the single
    edge pad-pad; a 1-pad part has no body. A part in `passable` (the 0R bridges) has NO body: a track may pass between its
    pads, which is what a bridge is for;
  * the FENCE is a wheel too: the edge points (where nets leave the block) in order along the boundary, joined to an outer hub.
    The planar embedding therefore has every edge point on one face and everything else in the face the ring bounds.
GND is not a net here (the bottom layer is a plane: every GND pad has its via). A net with fewer than two terminals is dropped.
Optional `roots`/`branches`: a net whose branches must each start at a named pad (a Kelvin star: LR-8's reference), see check().

MINIMUM CROSSINGS: the minimum number of NETS whose removal makes the graph planar. Exact, by a bounded search tree: find a
minimal set of nets that is already non-planar together with the structure (a conflict); any solution removes one net of it;
branch on those, iterating the depth up to `max_k` (default 4); if nothing is found by then the figure is a greedy upper
bound and `Result.exact` is False. A net removed is a net that must be BRIDGED (split by a 0R part so another net may pass
between the two segments). A net that crosses two others may need more than one bridge, so this is the minimum number of
nets, a lower bound on bridges; `bridge_plans` then tries to find, for each suggested net, ONE split of its terminals into two
segments that makes the block planar (so a single bridge is enough), and says so when none exists.
PROTECTED nets (fnmatch patterns: ADC lines, divider nodes, VREF branches) are never suggested; if every way out needs one
the answer says "no allowed bridge".

WHAT THE MODEL CANNOT SEE (kept honest, also in README): pad shapes, track width and clearance (a gap between two pads of a
non-passable part may in fact pass a 0.2 mm track; the model says it cannot), via placement and the bottom layer (a bottom hop
is a crossing here), keep-outs and courtyard overlaps, the real extent of a part's body (only its pads' cycle), and the
MIRROR of a part: the planar embedding fixes each body's pin order up to reflection, so a block that is non-planar only
because of a part's handedness is reported planar (the test is a necessary condition, never sufficient). A fence of several
rectangles is one ring (edge points ordered by angle around the region's centre). Parts outside the block are not in the
graph; what leaves the block is one edge point per crossing.
"""
from __future__ import annotations

import dataclasses
import fnmatch
import itertools
import math

import numpy as np

try:                                            # the tests skip with a reason when it is missing; the CLI fails loudly
    import networkx as nx
except ImportError:                             # pragma: no cover
    nx = None

EDGE = '@edge'                                  # ref of a fence edge-point terminal: (EDGE, label)
GND_DEFAULT = '/GND'
DEFAULT_PROTECTED = ('/A0', '/A1', '/CH?_N', '/CH?_NP', '/CH?_IN', '/VREF*', 'A0', 'A1', 'VREF*', 'CH?_N', 'CH?_NP', 'CH?_IN')


@dataclasses.dataclass
class Result:
    planar: bool
    min_crossings: int                          # fewest nets whose removal makes the block planar (any net may be chosen)
    crossings: list                             # [(net_a, net_b)]: the net removed and a net it conflicts with
    suggested_bridges: list                     # nets to bridge, all unprotected; [] if planar or none allowed
    detail: str
    exact: bool = True
    min_sets: list = dataclasses.field(default_factory=list)       # every minimum removal set found (any nets)
    allowed_crossings: int | None = None        # fewest nets when protected ones may not be chosen (None: impossible)
    bridge_plans: dict = dataclasses.field(default_factory=dict)   # net -> ([terminals], [terminals]) or None
    conflict: list = dataclasses.field(default_factory=list)       # a minimal non-planar set of nets


def _need_nx():
    if nx is None:
        raise ImportError('planar.py needs networkx (requirements-pcb.txt)')


# ------------------------------------------------------------------------------------------------ pin order
def rotation_from_pads(pads):
    """{(ref, pin): (x, y)} -> {ref: [pin, ...]} in order around the body: angular order about the centroid of the pads (a
    two-row IC, a quad package and a square pad ring all come out in perimeter order); when the pads are collinear (a header
    row) the order along the line. The direction (cw or ccw) is irrelevant: the planarity test is blind to a mirror."""
    by = {}
    for (ref, pin), xy in pads.items():
        by.setdefault(ref, []).append((pin, float(xy[0]), float(xy[1])))
    out = {}
    for ref, lst in by.items():
        P = np.array([[x, y] for _, x, y in lst])
        c = P.mean(axis=0)
        d = P - c
        if len(lst) >= 3 and np.linalg.svd(d, compute_uv=False)[-1] < 1e-6 * max(1.0, np.abs(d).max()):
            u = np.linalg.svd(d)[2][0]
            key = d @ u
        else:
            key = np.arctan2(d[:, 1], d[:, 0])
        out[ref] = [lst[i][0] for i in np.argsort(key, kind='stable')]
    return out


def boundary_order(points, rects):
    """indices of `points` [(x, y)] in order along the boundary of the fence: the perimeter of the rectangle when there is one
    rect (clockwise from its lower-left corner), else the angle about the centre of the rects (a region with several
    rectangles is treated as one star-shaped ring: see the module docstring)."""
    pts = np.asarray(points, float).reshape(-1, 2)
    if len(rects) == 1:
        x0, y0, x1, y1 = rects[0]
        w, h = x1 - x0, y1 - y0
        key = []
        for x, y in pts:
            d = [abs(y - y0), abs(x - x1), abs(y - y1), abs(x - x0)]       # south, east, north, west edge
            s = int(np.argmin(d))
            key.append([x - x0, w + (y - y0), w + h + (x1 - x), 2 * w + h + (y1 - y)][s])
        return list(np.argsort(key, kind='stable'))
    R = np.asarray(rects, float)
    area = (R[:, 2] - R[:, 0]) * (R[:, 3] - R[:, 1])
    cx = ((R[:, 0] + R[:, 2]) / 2 * area).sum() / area.sum()
    cy = ((R[:, 1] + R[:, 3]) / 2 * area).sum() / area.sum()
    return list(np.argsort(-np.arctan2(pts[:, 1] - cy, pts[:, 0] - cx), kind='stable'))


# ------------------------------------------------------------------------------------------------ graph
def _norm_inputs(block_nets, boundary, gnd, ignore):
    """terminal lists with the fence edge points added; nets with < 2 terminals and GND dropped"""
    nets = {}
    for n, terms in block_nets.items():
        if n == gnd or n in ignore:
            continue
        nets[n] = [tuple(t) for t in terms]
    for label, n in boundary:
        if n in nets:
            nets[n].append((EDGE, label))
    return {n: list(dict.fromkeys(t)) for n, t in nets.items() if len(t) >= 2}


def _wheel(G, verts, hub):
    """verts in cyclic order: the cycle, plus `hub` joined to all (2 verts: one edge; 1: nothing)"""
    n = len(verts)
    if n < 2:
        return
    if n == 2:
        G.add_edge(verts[0], verts[1])
        return
    for i in range(n):
        G.add_edge(verts[i], verts[(i + 1) % n])
        G.add_edge(verts[i], hub)


def _chains(P, pins):
    """pads (pins, positions P) of a part that is one row or two rows: -> list of chains (pin lists along each row), or None
    when the pads are neither (a square package, a ring of pads)."""
    d = P - P.mean(axis=0)
    sv, vt = np.linalg.svd(d)[1:]
    scale = max(1.0, np.abs(d).max())
    if sv[-1] < 1e-6 * scale:
        return [[pins[i] for i in np.argsort(d @ vt[0], kind='stable')]]
    best = None
    for across, along in ((vt[1], vt[0]), (vt[0], vt[1])):          # rows run along `along`, one row per side of `across`
        c = d @ across
        o = np.argsort(c, kind='stable')
        gaps = np.diff(c[o])
        if len(gaps) == 0:
            continue
        k = int(np.argmax(gaps))
        groups = [o[:k + 1], o[k + 1:]]
        ok = True
        for g in groups:
            sub = d[g] - d[g].mean(axis=0)
            if len(g) >= 3 and np.linalg.svd(sub, compute_uv=False)[-1] > 0.05 * scale:
                ok = False
        if ok and (best is None or gaps[k] > best[0]):
            best = (gaps[k], [[pins[i] for i in g[np.argsort(d[g] @ along, kind='stable')]] for g in groups])
    return None if best is None else best[1]


def _bodies(nets_all, pads, rotation, passable, body, overrides, pass_pitch):
    """{ref: ('wall', [pin order]) | ('rows', [[pin order of a row], ...])} for every part that has a body, over the FULL net
    set (a removed net's pads are still on the body).
      'wall'  the pads are a cycle and nothing can lie inside (the spec's construction: pin order is a rotation system)
      'rows'  pads along a row are a chain (a track cannot pass between neighbours closer than pass_pitch), the inside of the
              part and its ends are open: a SOIC's rows are chains and tracks run under it
      'open'  no body (a bridge; two pads further apart than pass_pitch)
    body='wall' gives every multi-pad part a wall; body='auto' picks from the pad geometry (positions needed): a part of two
    pads, or whose pads are all further apart than pass_pitch, is open; one or two rows are chains; anything else a wall.
    `overrides` {ref: policy} wins; a ref in `passable` is open."""
    present = {}
    for terms in nets_all.values():
        for t in terms:
            if t[0] != EDGE:
                present.setdefault(t[0], set()).add(t[1])
    order = dict(rotation_from_pads(pads) if pads else {})
    if rotation:
        order.update({r: list(p) for r, p in rotation.items()})
    out = {}
    for ref, pins in present.items():
        pol = overrides.get(ref, 'open' if ref in passable else body)
        if pol == 'open' or len(pins) < 2:
            continue
        seq = [p for p in order.get(ref, []) if p in pins]
        seq += sorted(pins - set(seq))
        if pol == 'auto':
            have = all((ref, p) in pads for p in seq)
            if not have:
                pol = 'wall'
            else:
                P = np.array([pads[(ref, p)] for p in seq], float)
                ch = _chains(P, seq) if len(seq) >= 2 else None
                if len(seq) == 2:
                    ch = [seq]
                if ch is None:
                    pol = 'wall'
                else:
                    segs = []
                    for c in ch:
                        cur = [c[0]]
                        for a, b2 in zip(c, c[1:]):
                            if math.dist(pads[(ref, a)], pads[(ref, b2)]) < pass_pitch:
                                cur.append(b2)
                            else:
                                segs.append(cur)
                                cur = [b2]
                        segs.append(cur)
                    segs = [x for x in segs if len(x) >= 2]
                    if segs:
                        out[ref] = ('rows', segs)
                    continue
        if pol == 'rows':
            out[ref] = ('rows', [seq])
        else:
            out[ref] = ('wall', seq)
    return out


def _build(nets, nets_all, bodies, boundary, roots, branches, ordered=()):
    """-> (G, owner): owner maps frozenset({u, v}) of every net edge to its net, and hub vertices to their net"""
    G = nx.Graph()
    owner = {}

    def vt(t):
        return ('t',) + tuple(t)

    for ref, (kind, seq) in bodies.items():
        if kind == 'wall':
            _wheel(G, [vt((ref, p)) for p in seq], ('b', ref))
        else:
            for chain in seq:
                for u, v in zip(chain, chain[1:]):
                    G.add_edge(vt((ref, u)), vt((ref, v)))
    labels = [lab for lab, _ in boundary]
    if len(labels) >= 2:
        _wheel(G, [vt((EDGE, lab)) for lab in labels], ('o',))
    for n, terms in nets.items():
        def link(u, v):
            G.add_edge(u, v)
            owner[frozenset((u, v))] = n
        if n in roots:
            r = vt(roots[n])
            groups = branches.get(n)
            if groups is None:
                for t in terms:
                    if tuple(t) != tuple(roots[n]):
                        link(r, vt(t))
            else:
                seen = {tuple(roots[n])}
                if n in ordered and len(groups) >= 3:                 # the legs leave the pin in this order (a fan)
                    for k in range(len(groups) - 1):             # a path, not a cycle: a pin on a body has a half-plane of legs
                        G.add_edge(('h', n, k), ('h', n, k + 1))
                for k, g in enumerate(groups):
                    h = ('h', n, k)
                    link(r, h)
                    owner[h] = n
                    for t in g:
                        if tuple(t) != tuple(roots[n]):
                            link(h, vt(t))
                            seen.add(tuple(t))
                for t in terms:                  # terminals no branch names sit on the root
                    if tuple(t) not in seen:
                        link(r, vt(t))
        else:
            h = ('h', n)
            owner[h] = n
            for t in terms:
                link(h, vt(t))
    return G, owner


class _Model:
    def __init__(self, block_nets, pads, rotation, boundary, passable, roots, branches, gnd, ignore, body='wall', overrides=None,
                 pass_pitch=1.5, ordered=()):
        self.ordered = set(ordered)
        _need_nx()
        self.boundary = [tuple(x) for x in boundary]
        self.nets = _norm_inputs(block_nets, self.boundary, gnd, ignore)
        keep = {lab for lab, n in self.boundary if n in self.nets}
        self.boundary = [(lab, n) for lab, n in self.boundary if lab in keep]
        self.roots = {n: tuple(r) for n, r in (roots or {}).items() if n in self.nets}
        self.branches = {n: [list(map(tuple, g)) for g in gs] for n, gs in (branches or {}).items() if n in self.nets}
        self.bodies = _bodies(self.nets, pads or {}, rotation or {}, set(passable), body, overrides or {}, pass_pitch)
        self.cache = {}

    def graph(self, active=None):
        act = self.nets if active is None else {n: self.nets[n] for n in active}
        return _build(act, self.nets, self.bodies, self.boundary, self.roots, self.branches, self.ordered)

    def conflict(self, active):
        """a minimal set of nets (within `active`) that is non-planar with the structure, or None when planar"""
        key = frozenset(active)
        if key in self.cache:
            return self.cache[key]
        G, owner = self.graph(sorted(key))
        ok, cert = nx.check_planarity(G, counterexample=True)
        if ok:
            self.cache[key] = None
            return None
        cur = set()
        for u, v in cert.edges():
            for k in (frozenset((u, v)), u, v):
                if k in owner:
                    cur.add(owner[k])
        if not cur:                              # the structure alone is non-planar: cannot happen by construction
            raise RuntimeError('non-planar with no net in the certificate')
        for n in sorted(cur):                    # deletion filter: drop every net the conflict survives without
            trial = cur - {n}
            G2, _ = self.graph(sorted(trial))
            if not nx.check_planarity(G2)[0]:
                cur = trial
        self.cache[key] = sorted(cur)
        return self.cache[key]

    def planar(self, active):
        return self.conflict(active) is None


def _min_sets(model, allowed, kmax, limit=64, budget=400):
    """-> (k, [sets]) the smallest k <= kmax with removal sets (nets from `allowed` only), or (None, []); the search stops
    after `budget` conflict extractions (then None: the caller falls back to a greedy bound and says it is not exact)"""
    allnets = list(model.nets)
    spent = [0]

    def dfs(removed, depth, out):
        spent[0] += 1
        if spent[0] > budget:
            return
        c = model.conflict([n for n in allnets if n not in removed])
        if c is None:
            out.add(frozenset(removed))
            return
        if depth == 0:
            return
        for n in c:
            if n in allowed and len(out) < limit:
                dfs(removed | {n}, depth - 1, out)
    for k in range(0, kmax + 1):
        out = set()
        dfs(frozenset(), k, out)
        # keep only sets of exactly the minimal size (supersets reached via a shorter branch are never minimal)
        out = {s for s in out if not any(t < s for t in out)}
        if out:
            return k, sorted(sorted(s) for s in out)
    return None, []


def _greedy(model, allowed):
    removed = []
    while True:
        c = model.conflict([n for n in model.nets if n not in removed])
        if c is None:
            return removed
        cand = [n for n in c if n in allowed]
        if not cand:
            return None
        removed.append(cand[0])


def _is_protected(net, protected):
    net = net.split('~')[0]
    base = net[1:] if net.startswith('/') else net
    return any(fnmatch.fnmatchcase(net, p) or fnmatch.fnmatchcase(base, p) for p in protected)


def _bridge_plan(model, net, others, cap=256):
    """one split of net's terminals into two segments (two nets, no part between them) that makes the block planar with
    `others` active, or None. Rooted nets are not split."""
    if net in model.roots:
        return None
    T = model.nets[net]
    if len(T) < 2:
        return None
    k = len(T)
    masks = [m for m in range(1, 2 ** (k - 1))]              # terminal 0 stays in group A, group B = the set bits of m+...
    masks.sort(key=lambda m: min(bin(m).count('1'), k - bin(m).count('1')))
    base = {n: model.nets[n] for n in others}
    for m in masks[:cap]:
        B = [T[i + 1] for i in range(k - 1) if m >> i & 1]
        A = [T[0]] + [T[i + 1] for i in range(k - 1) if not m >> i & 1]
        if not B:
            continue
        nets = dict(base)
        nets[net + '#1'] = A
        nets[net + '#2'] = B
        sub = _Model.__new__(_Model)
        sub.__dict__.update(model.__dict__)
        sub.nets = {**nets, **{n: model.nets[n] for n in ()}}
        sub.cache = {}
        # the full net set must keep every pad on its body: both halves are in it, so bodies stay as built
        sub.roots = {n: r for n, r in model.roots.items() if n in nets}
        sub.branches = {n: g for n, g in model.branches.items() if n in nets}
        if sub.planar(list(nets)):
            return A, B
    return None


def check(block_nets, pads, rotation, boundary, protected=(), *, passable=(), roots=None, branches=None, gnd=GND_DEFAULT,
          ignore=(), max_k=4, body='wall', body_overrides=None, pass_pitch=1.5, ordered_branches=()):
    """block_nets {net: [(ref, pin), ...]}; pads {(ref, pin): (x, y)} (pin order is taken from them where `rotation` is silent);
    rotation {ref: [pin, ...]} order around the body, or None; boundary [(label, net), ...] the edge points in order along the
    fence (a net with an edge point leaves the block there); protected: fnmatch patterns of nets never to be suggested;
    passable: refs of parts a track may pass between (0R bridges); roots {net: (ref, pin)} and branches {net: [[terminals]]}:
    a net starred at that pad (LR-8's Kelvin legs); gnd: the plane net, ignored; max_k: depth of the exact search;
    body 'wall' (default: the spec's construction) or 'auto' (from pad geometry), body_overrides {ref: 'wall'|'rows'|'open'},
    ordered_branches: nets whose `branches` leave the root pad in the order listed (a cyclic order at the pin);
    pass_pitch: mm, pads closer than this on a part block a track passing between them (see _bodies)."""
    m = _Model(block_nets, pads, rotation, boundary, passable, roots, branches, gnd, set(ignore), body, body_overrides, pass_pitch, ordered_branches)
    allnets = list(m.nets)
    c0 = m.conflict(allnets)
    if c0 is None:
        return Result(True, 0, [], [], f'planar: {len(allnets)} nets route on one layer without a crossing')
    everyone = set(allnets)
    allowed = {n for n in allnets if not _is_protected(n, protected)}
    k, sets = _min_sets(m, everyone, max_k)
    exact = k is not None
    if not exact:
        g = _greedy(m, everyone)
        k, sets = len(g), [sorted(g)]
    ka, sets_a = _min_sets(m, allowed, max_k)
    if ka is None:
        g = _greedy(m, allowed)
        if g is not None:
            ka, sets_a, exact = len(g), [sorted(g)], False
    if ka is None:
        pick, sugg = (sets[0], [])
    else:
        pick, sugg = sets_a[0], list(sets_a[0])
    crossings = []
    for x in pick:
        rest = [n for n in allnets if n not in pick or n == x]
        cx = m.conflict(rest) or []
        for y in cx:
            if y != x:
                crossings.append((x, y))
    plans = {}
    for x in sugg:
        plans[x] = _bridge_plan(m, x, [n for n in allnets if n not in pick])
    msg = [f'NOT planar: at least {k} net(s) must be bridged ({"exact" if exact else "greedy upper bound"})']
    msg.append('minimal conflict: ' + ', '.join(c0))
    msg.append('minimum removal sets: ' + '; '.join('{' + ', '.join(s) + '}' for s in sets))
    if ka is None:
        msg.append('no allowed bridge: every way out needs a protected net (' + ', '.join(sorted(everyone - allowed)) + ')')
    else:
        msg.append(f'suggested bridges (unprotected): {", ".join(sugg)}')
        for x, p in plans.items():
            msg.append(f'  {x}: ' + ('split ' + str([_t(t) for t in p[0]]) + ' | ' + str([_t(t) for t in p[1]]) if p
                                    else 'no single two-segment split makes the block planar (needs more than one bridge, or a rooted net)'))
    return Result(False, k, crossings, sugg, '\n'.join(msg), exact, [list(s) for s in sets], ka, plans, list(c0))


def _t(t):
    return f'{t[0]}.{t[1]}'


# ------------------------------------------------------------------------------------------------ BoardArrays -> inputs
def _clip(seg, rect):
    """parameters t in [0,1] where the segment crosses the boundary of rect"""
    (x0, y0), (x1, y1) = seg
    rx0, ry0, rx1, ry1 = rect
    ts = []
    for coord, a, b, lo, hi in ((0, x0, x1, rx0, rx1), (1, y0, y1, ry0, ry1)):
        for edge in (lo, hi):
            if a != b and min(a, b) <= edge <= max(a, b):
                t = (edge - a) / (b - a)
                px = x0 + t * (x1 - x0)
                py = y0 + t * (y1 - y0)
                if rx0 - 1e-9 <= px <= rx1 + 1e-9 and ry0 - 1e-9 <= py <= ry1 + 1e-9:
                    ts.append(t)
    return ts


def edge_points_from_tracks(b, rects, gnd, gap=3.5):
    """[(net_name, (x, y))] where top-copper tracks cross the boundary of the region (the rects dilated by gap/2 so rectangles
    nearer than `gap` are one region); a crossing inside another rectangle is internal and not listed. Vias and the bottom
    layer are ignored."""
    g = gap / 2
    R = [(x0 - g, y0 - g, x1 + g, y1 + g) for x0, y0, x1, y1 in rects]
    pts = []
    m = (b.s_layer == 0)
    for i in np.flatnonzero(m):
        net = b.nets[b.s_net[i]]
        if not net or net == gnd:
            continue
        seg = ((b.s_x0[i], b.s_y0[i]), (b.s_x1[i], b.s_y1[i]))
        for k, r in enumerate(R):
            for t in _clip(seg, r):
                q = (seg[0][0] + t * (seg[1][0] - seg[0][0]), seg[0][1] + t * (seg[1][1] - seg[0][1]))
                if any(j != k and R[j][0] + 1e-6 < q[0] < R[j][2] - 1e-6 and R[j][1] + 1e-6 < q[1] < R[j][3] - 1e-6 for j in range(len(R))):
                    continue
                if not any(n == net and math.hypot(q[0] - p[0], q[1] - p[1]) < 0.05 for n, p in pts):
                    pts.append((net, (round(float(q[0]), 3), round(float(q[1]), 3))))
    return pts, R


def _copper_components(b, refs, R, gnd):
    """the as-built contract: connected pieces of top copper inside the region R (rects, already dilated). Returns
    (pad_comp {(ref, pin): (net, k)}, seg_ep [(net, k, (x, y))]) where k numbers the pieces of a net inside the region. A piece
    is segments that touch each other, and the pads they touch (same net); the crossing of a segment with the region boundary is
    an edge point of its piece. Bottom copper is not followed: a bottom hop leaves a net in two pieces, which is what a bridge
    does."""
    from . import geom
    inside = lambda x, y: any(r[0] <= x <= r[2] and r[1] <= y <= r[3] for r in R)
    seg = np.flatnonzero((b.s_layer == 0) & (b.s_net > 0))
    seg = np.array([i for i in seg if b.nets[b.s_net[i]] != gnd and (inside(b.s_x0[i], b.s_y0[i]) or inside(b.s_x1[i], b.s_y1[i])
                                                                      or any(_clip(((b.s_x0[i], b.s_y0[i]), (b.s_x1[i], b.s_y1[i])), r) for r in R))], int)
    pidx = [i for i in range(len(b.p_pin)) if b.fp_ref[int(b.p_fp[i])] in refs and int(b.p_net[i]) > 0 and b.nets[int(b.p_net[i])] != gnd]
    ns, npd = len(seg), len(pidx)
    S = np.column_stack([b.s_x0[seg], b.s_y0[seg], b.s_x1[seg], b.s_y1[seg]]) if ns else np.zeros((0, 4))
    P = np.column_stack([b.p_x[pidx], b.p_y[pidx], b.p_x[pidx], b.p_y[pidx]]) if npd else np.zeros((0, 4))
    snet = b.s_net[seg]
    pnet = np.array([b.p_net[i] for i in pidx], int)
    joins = []
    if ns:
        ii, jj = geom.within(S, S, 2e-3)
        joins += [(i, j) for i, j in zip(ii, jj) if i < j and snet[i] == snet[j]]
    if ns and npd:
        half = np.array([0.5 * max(b.p_sx[i], b.p_sy[i]) for i in pidx])
        pi, sj = geom.within(P, S, half.max() + 1e-6)
        for i, j in zip(pi, sj):
            if pnet[i] == snet[j]:
                d = geom.seg_seg_dist(P[i:i + 1], S[j:j + 1])[0, 0]
                if d <= half[i] + 1e-6:
                    joins.append((ns + i, j))
    k, lab = geom.connected_components(ns + npd, joins) if ns + npd else (0, np.zeros(0, int))
    # number the pieces per net
    num, piece = {}, {}
    for it in range(ns + npd):
        net = int(snet[it]) if it < ns else int(pnet[it - ns])
        key = (net, int(lab[it]))
        if key not in num:
            num[key] = sum(1 for kk in num if kk[0] == net)
        piece[it] = (b.nets[net], num[key])
    pad_comp = {(b.fp_ref[int(b.p_fp[i])], b.p_pin[i]): piece[ns + n] for n, i in enumerate(pidx)}
    eps = []
    for it in range(ns):
        x0, y0, x1, y1 = S[it]
        for r in R:
            for t in _clip(((x0, y0), (x1, y1)), r):
                q = (x0 + t * (x1 - x0), y0 + t * (y1 - y0))
                if any(rr is not r and rr[0] + 1e-6 < q[0] < rr[2] - 1e-6 and rr[1] + 1e-6 < q[1] < rr[3] - 1e-6 for rr in R):
                    continue
                e = piece[it] + ((round(float(q[0]), 3), round(float(q[1]), 3)),)
                if not any(e[:2] == f[:2] and math.hypot(e[2][0] - f[2][0], e[2][1] - f[2][1]) < 0.05 for f in eps):
                    eps.append(e)
    return pad_comp, eps


def from_board(b, cfg, block, *, edge_points=None, exclude_refs=(), merge_bridges=False, passable=None, gap=3.5, body='auto'):
    """inputs of check() for one block of a BoardArrays: the pads of the parts cfg's owner_of assigns to it, their positions,
    the edge points and the protected patterns.
    edge_points: [(net, (x, y))] from a CONTRACT: each net is then one hub (the pre-route question). None reads the AS-BUILT
    contract off the top copper: every net is split into the pieces of copper it has inside the region (a net that leaves and
    comes back through a corridor is two pieces: the outside joins them) and the edge points are where the tracks cross the
    region boundary (the rects dilated by gap/2). A bridged net is two nets either way.
    merge_bridges: remove the cfg.BRIDGES parts and join what each one joined (the block as if every bridge were a plain wire:
    how many crossings was it hiding?). Returns a dict for check(**d)."""
    from . import fence
    gnd = getattr(cfg, 'GND', GND_DEFAULT)
    bridges = list(getattr(cfg, 'BRIDGES', []) or [])
    bridge_refs = {t[0] for t in bridges}
    rects = cfg.FENCES[block]
    refs = {r for r in b.fp_ref if fence.owner_of(r, cfg) == block} - set(exclude_refs)
    pads, pin_net = {}, {}
    for i in range(len(b.p_pin)):
        ref = b.fp_ref[int(b.p_fp[i])]
        if ref not in refs or int(b.p_net[i]) == 0:
            continue
        pads[(ref, b.p_pin[i])] = (float(b.p_x[i]), float(b.p_y[i]))
        pin_net[(ref, b.p_pin[i])] = b.nets[int(b.p_net[i])]
    nets, boundary = {}, []
    if edge_points is None:
        g = gap / 2 if len(rects) > 1 else 0.0          # only rectangles that must be joined are dilated
        R = [(x0 - g, y0 - g, x1 + g, y1 + g) for x0, y0, x1, y1 in rects]
        pad_comp, eps = _copper_components(b, refs, R, gnd)
        name = lambda net, k: net
        for key, (net, k) in pad_comp.items():
            nets.setdefault((net, k), []).append(key)
        for net, k, q in eps:
            nets.setdefault((net, k), [])
        order = boundary_order([q for *_, q in eps], R) if eps else []
        ep_list = [(f'e{j}:{eps[i][0]}~{eps[i][1]}@{eps[i][2][0]},{eps[i][2][1]}', (eps[i][0], eps[i][1])) for j, i in enumerate(order)]
        count = {}
        for (n, k) in nets:
            count[n] = count.get(n, 0) + 1
        label = lambda nk: nk[0] if count[nk[0]] == 1 else f'{nk[0]}~{nk[1]}'
        boundary = [(lab, label(nk)) for lab, nk in ep_list]
        nets = {label(nk): v for nk, v in nets.items()}
    else:
        for key, net in pin_net.items():
            nets.setdefault(net, []).append(key)
        for n, _ in edge_points:
            nets.setdefault(n, [])
        order = boundary_order([p for _, p in edge_points], rects) if edge_points else []
        boundary = [(f'e{k}:{edge_points[i][0]}', edge_points[i][0]) for k, i in enumerate(order)]
    if merge_bridges:
        parent = {}

        def find(a):
            while parent.get(a, a) != a:
                a = parent[a]
            return a
        owner_net = {}
        for n, ts in nets.items():
            for t in ts:
                owner_net[t] = n
        for ref, na, nb in bridges:
            pa, pb = [owner_net.get((ref, pin)) for pin in ('1', '2')]
            if pa is not None and pb is not None and pa != pb:
                ra, rb = find(pa), find(pb)
                keep, drop = sorted((ra, rb), key=lambda x: (len(x), x))
                parent[drop] = keep
        for ref in bridge_refs:
            for key in [k for k in pads if k[0] == ref]:
                del pads[key]
        merged = {}
        for n, ts in nets.items():
            merged.setdefault(find(n), []).extend(t for t in ts if t[0] not in bridge_refs)
        nets = merged
        boundary = [(lab, find(n)) for lab, n in boundary]
    prot = tuple(getattr(cfg, 'PROTECTED_NETS', DEFAULT_PROTECTED))
    return dict(block_nets=nets, pads=pads, rotation=None, boundary=boundary, protected=prot,
                passable=tuple(bridge_refs & refs) if passable is None else tuple(passable), gnd=gnd, body=body)
