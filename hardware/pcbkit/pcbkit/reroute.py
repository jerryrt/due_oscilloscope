"""Re-route a run of top-layer track between its two ends so that it passes pcbkit.rules.track_geometry: a grid search with the geometry rules built into its moves.

    chains(b, layer=0) -> [Chain]                the tracks of a layer as runs between ends (a pad, a via, a junction or a free end), each through points of degree two
    route(b, chain, ...) -> [(x, y), ...] | None  a new centre line for the chain from end to end, or None

The search (`route`) is an A* over cells of `res` mm in a window around the chain, in eight directions. A leg must be at least `min_leg` long before the path may turn, and a turn is 45
or 90 degrees, so every segment is on the 45 degree step and no leg is a jog. An end on a pad starts or finishes inside the pad, along one of the pad's axes, with the track's whole width
inside the edge it crosses (the rule `entry`); an end on a junction finishes on the copper of the net that is left (a track overlapping it connects). Everything else is blocked: the copper of
other nets and its clearance, the pads of its own net that it does not end on (it would run over them), the via and the board edge. The copper of its own net that stays is not.
Positions are board-frame mm; nothing here imports pcbnew or a project."""
from __future__ import annotations

import dataclasses
import heapq
import math

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage as ndi

from . import rules

LAST_NECKS = []                                    # the pad ends of the last route() that are entered at the minimum width: [('start' | 'goal', pad index)]
MIN_WIDTH = 0.2                                   # the narrowest track, mm
LAST_WHY = ['']                                   # why the last route() returned None, for a report
DIRS = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)]       # in grid cells; row index grows downward, so the rows are drawn with y flipped by the caller


@dataclasses.dataclass
class End:
    kind: str                  # 'pad', 'via', 'junction' or 'free'
    x: float
    y: float
    pad: int = -1              # for a pad: the index into rules._pad_arrays(b)
    via: int = -1


@dataclasses.dataclass
class Chain:
    net: int
    layer: int
    segs: list                 # row numbers of b's segment arrays, in order along the chain
    ends: tuple                # (End, End)
    width: float


def _key(layer, net, x, y):
    return (int(layer), int(net), int(round(x * 1000)), int(round(y * 1000)))


def chains(b, layer=0):
    """the runs of track on `layer`: from an end (a pad or via of the net under it, a point where other than two segments meet, a free end) along points of degree two to the next end"""
    S = rules.segs(b)
    L = np.hypot(S[:, 2] - S[:, 0], S[:, 3] - S[:, 1]) if len(S) else np.zeros(0)
    pa = rules._pad_arrays(b)
    at = {}
    for i in range(len(S)):
        if b.s_layer[i] != layer or L[i] <= 1e-6:
            continue
        for e in (0, 1):
            at.setdefault(_key(layer, b.s_net[i], S[i, 2 * e], S[i, 2 * e + 1]), []).append((i, e))

    def terminal(k):
        net, x, y = k[1], k[2] / 1000, k[3] / 1000
        p = np.array([[x, y]])
        hit = np.flatnonzero(rules._in_pads(p, pa)[0] & (pa['net'] == net) & ((pa['mask'] & (1 << layer)) > 0)) if len(pa['rows']) else []
        if len(hit):
            return End('pad', x, y, pad=int(hit[0]))
        for v in range(len(b.v_x)):
            if b.v_net[v] == net and math.hypot(b.v_x[v] - x, b.v_y[v] - y) <= b.v_dia[v] / 2 + 1e-3:
                return End('via', x, y, via=v)
        n = len(at[k])
        if n == 1:                                                     # an end resting on the body of another track of the net is a tap there
            for q in range(len(S)):
                if b.s_layer[q] != layer or b.s_net[q] != net or L[q] <= 1e-6 or q == at[k][0][0]:
                    continue
                x0, y0, x1, y1 = S[q]
                t = max(0.0, min(1.0, ((x - x0) * (x1 - x0) + (y - y0) * (y1 - y0)) / (L[q] * L[q])))
                if math.hypot(x - (x0 + t * (x1 - x0)), y - (y0 + t * (y1 - y0))) <= b.s_w[q] / 2 + 1e-3:
                    return End('junction', x, y)
        return End('junction' if n >= 3 else 'free', x, y) if n != 2 else None
    ends = {k: terminal(k) for k in at}
    seen, out = set(), []
    for k, e in ends.items():
        if e is None:
            continue
        for i, ei in at[k]:
            if i in seen:
                continue
            segs, cur, kk, prev = [i], i, k, None
            seen.add(i)
            while True:
                far = (S[cur, 2], S[cur, 3]) if _key(layer, b.s_net[cur], S[cur, 0], S[cur, 1]) == kk else (S[cur, 0], S[cur, 1])
                kn = _key(layer, b.s_net[cur], far[0], far[1])
                if ends[kn] is not None:
                    break
                nxt = [q for q, _ in at[kn] if q != cur]
                if not nxt or nxt[0] in seen:
                    kn = None
                    break
                cur, kk = nxt[0], kn
                segs.append(cur)
                seen.add(cur)
            if kn is None:
                continue
            out.append(Chain(int(b.s_net[i]), layer, segs, (e, ends[kn]), float(np.median(b.s_w[segs]))))
    return out


class _Win:
    def __init__(self, x0, y0, x1, y1, res):
        self.res, self.x0, self.y1 = res, x0, y1
        self.W, self.H = int(math.ceil((x1 - x0) / res)) + 1, int(math.ceil((y1 - y0) / res)) + 1

    def cell(self, x, y):
        return int(round((self.y1 - y) / self.res)), int(round((x - self.x0) / self.res))

    def xy(self, r, c):
        return self.x0 + c * self.res, self.y1 - r * self.res

    def px(self, x, y):
        return (x - self.x0) / self.res, (self.y1 - y) / self.res


def _draw_items(win, items):
    im = Image.new('L', (win.W, win.H), 0)
    d = ImageDraw.Draw(im)
    for kind, v in items:
        if kind == 'poly':
            d.polygon([win.px(x, y) for x, y in v], fill=1)
        elif kind == 'line':
            (x0, y0, x1, y1), w = v
            a, c = win.px(x0, y0), win.px(x1, y1)
            d.line([a, c], fill=1, width=max(1, int(round(w / win.res))))
            for p in (a, c):
                r = w / win.res / 2
                d.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], fill=1)
        elif kind == 'disc':
            (x, y), r = v
            p, rr = win.px(x, y), r / win.res
            d.ellipse([p[0] - rr, p[1] - rr, p[0] + rr, p[1] + rr], fill=1)
    return np.asarray(im, bool)


def _pad_poly(pa, h, m):
    a = math.radians(pa['rot'][h])
    hx, hy = pa['sx'][h] / 2 + m, pa['sy'][h] / 2 + m
    c, s = math.cos(a), math.sin(a)
    return [(pa['cx'][h] + u * c - v * s, pa['cy'][h] + u * s + v * c) for u, v in ((-hx, -hy), (hx, -hy), (hx, hy), (-hx, hy))]


def _items(b, layer, pa, net, skip_segs, own_pads, m_other, m_own, include_own):
    """copper to draw: other nets inflated by `m_other` (clearance plus half the track), the net's own pads that are not ends inflated by `m_own`; with `include_own` the net's copper that stays, uninflated"""
    items = []
    for i in range(len(b.s_x0)):
        if b.s_layer[i] != layer or i in skip_segs:
            continue
        own = b.s_net[i] == net
        if own and not include_own:
            continue
        if include_own != own and include_own:
            continue
        m = (m_own if own else m_other)
        items.append(('line', ((b.s_x0[i], b.s_y0[i], b.s_x1[i], b.s_y1[i]), b.s_w[i] + 2 * m)))
    for h in range(len(pa['rows'])):
        if not (pa['mask'][h] & (1 << layer)):
            continue
        own = pa['net'][h] == net
        if include_own:
            if own and h not in own_pads:                      # the pad a spur starts from is not what it finishes on
                items.append(('poly', _pad_poly(pa, h, 0.0)))
            continue
        if h in own_pads:
            continue
        items.append(('poly', _pad_poly(pa, h, m_own if own else m_other)))
    for v in range(len(b.v_x)):
        own = b.v_net[v] == net
        if include_own:
            if own:
                items.append(('disc', ((b.v_x[v], b.v_y[v]), b.v_dia[v] / 2)))
            continue
        items.append(('disc', ((b.v_x[v], b.v_y[v]), b.v_dia[v] / 2 + (m_own if own else m_other))))
    return items


def route(b, chain, res=0.05, min_leg=0.6, clear=0.2, edge_clear=0.45, margin=4.0, bend_cost=0.4, fine_pitch=0.65, max_expand=1500000, entry_tol=0.001, goal=True, safety=0.02, width=None):
    """A new centre line for `chain`: [(x, y), ...] from one end to the other, on the 45 degree step with legs of at least `min_leg` (a leg out of a pad of a part at `fine_pitch` or finer may be
    shorter), or None. `margin` is how far outside the chain's bounding box the search may go. With `goal=False` the chain's second end is not a place but the net: the path finishes on any
    copper of the net that stays (a spur from a pad to the track it was running over); the chain is then (pad end, any), its segments are not removed from the obstacles but are not
    obstacles either (they are the net's)."""
    pa = rules._pad_arrays(b)
    hw = (width if width is not None else chain.width) / 2
    real = [e for e in chain.ends if e.kind != 'free']
    xs = [e.x for e in real] + [b.s_x0[i] for i in chain.segs] + [b.s_x1[i] for i in chain.segs]
    ys = [e.y for e in real] + [b.s_y0[i] for i in chain.segs] + [b.s_y1[i] for i in chain.segs]
    if not goal:
        margin = max(margin, 8.0)
    x0w, y0w, x1w, y1w = min(xs) - margin, min(ys) - margin, max(xs) + margin, max(ys) + margin
    anchor = next((e for e in reversed(chain.ends) if e.kind in ('junction', 'free') and (goal or e is chain.ends[0])), None) if goal else None
    if anchor is None and chain.ends[0].kind in ('junction',):
        anchor = chain.ends[0]
    win = _Win(x0w, y0w, x1w, y1w, res)
    if anchor is not None:                                      # a grid node on the junction, so that the track ends exactly where the other copper does
        win.x0 = anchor.x - math.ceil((anchor.x - x0w) / res) * res
        win.y1 = anchor.y + math.ceil((y1w - anchor.y) / res) * res
        win.W, win.H = int(math.ceil((x1w - win.x0) / res)) + 1, int(math.ceil((win.y1 - y0w) / res)) + 1
    skip = set(chain.segs)
    own_pads = {e.pad for e in chain.ends if e.kind == 'pad'}
    blocked = _draw_items(win, _items(b, chain.layer, pa, chain.net, skip, own_pads, clear + safety + hw, hw + 0.05, False))
    # the board edge: the copper-to-edge clearance from the outline
    if len(b.outline) >= 3:
        inside = _draw_items(win, [('poly', [tuple(p) for p in b.outline])])
        blocked |= ndi.distance_transform_edt(inside) * res < edge_clear + hw
    own = _draw_items(win, _items(b, chain.layer, pa, chain.net, skip, own_pads, 0, 0, True))
    N = max(1, int(math.ceil(min_leg / res - 1e-9)))
    pitch = rules._fp_pitch(b)
    H, W = blocked.shape

    def pad_cells(h, hwx=None):
        """{direction index: bool grid} of the cells a track may start or finish in on pad h with that direction: inside the pad, along a pad axis, the whole width inside the edge it crosses"""
        hwx = hw if hwx is None else hwx
        a = math.radians(pa['rot'][h])
        rr, cc = np.mgrid[0:H, 0:W]
        x = win.x0 + cc * res
        y = win.y1 - rr * res
        dx, dy = x - pa['cx'][h], y - pa['cy'][h]
        u = dx * math.cos(a) + dy * math.sin(a)
        v = -dx * math.sin(a) + dy * math.cos(a)
        sx2, sy2 = pa['sx'][h] / 2, pa['sy'][h] / 2
        out = {}
        for d, (di, dj) in enumerate(DIRS):
            ang = math.degrees(math.atan2(-di, dj))                 # row down is y down
            if rules._dev(ang - pa['rot'][h], 180.0) <= 0.01:       # along the pad's x axis
                ok = (np.abs(u) <= sx2 - hwx + 1e-9) & (np.abs(v) + hwx <= sy2 + entry_tol)
            elif rules._dev(ang - pa['rot'][h] - 90.0, 180.0) <= 0.01:
                ok = (np.abs(v) <= sy2 - hwx + 1e-9) & (np.abs(u) + hwx <= sx2 + entry_tol)
            else:
                continue
            if pa['shape'][h] in (0, 2):                              # a round or oval pad: the end must be in the ellipse, not only in its bounding rectangle
                ok = ok & ((u / max(sx2 - 0.05, 1e-6)) ** 2 + (v / max(sy2 - 0.05, 1e-6)) ** 2 <= 1.0)
            out[d] = ok
        return out

    def near_cells(x, y, rad):
        r0, c0 = win.cell(x, y)
        k = int(math.ceil(rad / res)) + 1
        m = np.zeros((H, W), bool)
        for r in range(max(0, r0 - k), min(H, r0 + k + 1)):
            for c in range(max(0, c0 - k), min(W, c0 + k + 1)):
                if math.hypot(*(np.array(win.xy(r, c)) - (x, y))) <= rad + 1e-9:
                    m[r, c] = True
        return m

    del LAST_NECKS[:]

    def end_spec(e, which):
        """(per-direction goal/start masks, leg exemption); a pad the track is too wide for is entered at the minimum width (a neck-down), which is noted in LAST_NECKS"""
        if e.kind == 'pad':
            exempt = pitch.get(int(pa['fp'][e.pad]), math.inf) <= fine_pitch + 1e-9
            m = pad_cells(e.pad)
            if not any(v.any() for v in m.values()) and hw > MIN_WIDTH / 2 + 1e-9:
                m = pad_cells(e.pad, MIN_WIDTH / 2)
                LAST_NECKS.append((which, e.pad))
            return m, exempt
        if e.kind in ('junction', 'free'):
            m = np.zeros((H, W), bool)
            r0, c0 = win.cell(e.x, e.y)
            if 0 <= r0 < H and 0 <= c0 < W:
                m[r0, c0] = True
        else:
            m = near_cells(e.x, e.y, hw)
        return {d: m for d in range(8)}, True

    start_masks, start_exempt = end_spec(chain.ends[0], 'start')
    if goal:
        goal_masks, goal_exempt = end_spec(chain.ends[1], 'goal')
    else:
        goal_masks, goal_exempt = {d: own for d in range(8)}, False       # the end point inside the copper of the net: that is what connects
    goal_any = np.zeros((H, W), bool)
    for m in goal_masks.values():
        goal_any |= m
    if not goal_any.any() or not any(m.any() for m in start_masks.values()):
        LAST_WHY[0] = 'no place to start or finish (the end is outside the window)'
        return None
    if not (goal_any & ~blocked).any() or not any((m & ~blocked).any() for m in start_masks.values()):
        LAST_WHY[0] = 'the end is blocked by other copper or the board edge'
        return None
    gr, gc = np.nonzero(goal_any)
    gx, gy = win.xy(int(gr.mean()), int(gc.mean()))
    heap, best, par = [], {}, {}
    for d, m in start_masks.items():
        for r, c in zip(*np.nonzero(m & ~blocked)):
            st = (int(r), int(c), d, 0, True)                       # (row, column, direction, run along it capped at N, no bend yet)
            best[st] = 0.0
            par[st] = None
            x, y = win.xy(r, c)
            heapq.heappush(heap, (math.hypot(x - gx, y - gy), 0.0, st))
    sq2 = math.sqrt(2.0)
    expanded = 0
    while heap and expanded < max_expand:
        f, g, st = heapq.heappop(heap)
        if g > best.get(st, math.inf) + 1e-12:
            continue
        expanded += 1
        r, c, d, run, first = st
        gm = goal_masks.get(d)
        if gm is not None and gm[r, c] and (first or run >= N or goal_exempt):
            path = []
            cur = st
            while cur is not None:
                path.append(cur)
                cur = par[cur]
            path.reverse()
            return _polyline(win, path)
        for nd in range(8):
            di, dj = DIRS[nd]
            if nd != d:
                if min((nd - d) % 8, (d - nd) % 8) > 2:
                    continue                                       # no turn sharper than 90 degrees
                if run < (1 if (first and start_exempt) else N):
                    continue                                       # the leg is not long enough to bend after
            nr, nc = r + di, c + dj
            if not (0 <= nr < H and 0 <= nc < W) or blocked[nr, nc]:
                continue
            if di != 0 and dj != 0 and blocked[r + di, c] and blocked[r, c + dj]:
                continue                                           # a diagonal does not squeeze between two blocked cells
            step = res * (sq2 if (di != 0 and dj != 0) else 1.0)
            ng = g + step + (bend_cost if nd != d else 0.0)
            ns = (nr, nc, nd, min(N, (run + 1) if nd == d else 1), first and nd == d)
            if ng < best.get(ns, math.inf) - 1e-12:
                best[ns] = ng
                par[ns] = st
                x, y = win.xy(nr, nc)
                heapq.heappush(heap, (ng + math.hypot(x - gx, y - gy) * 0.9, ng, ns))
    LAST_WHY[0] = 'search limit reached' if heap else 'no path in the window'
    return None


def _polyline(win, states):
    """cell states -> corner points"""
    pts = [win.xy(states[0][0], states[0][1])]
    for k in range(1, len(states) - 1):
        if states[k][2] != states[k + 1][2]:
            pts.append(win.xy(states[k][0], states[k][1]))
    pts.append(win.xy(states[-1][0], states[-1][1]))
    out = [pts[0]]
    for p in pts[1:]:
        if math.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) > 1e-9:
            out.append(p)
    return out


def overlapped_pads(b, chain):
    """the pads of the chain's net, other than its two end pads, that its copper lies over: they were connected by the track running across them, and a re-route that goes round must reach them"""
    pa = rules._pad_arrays(b)
    if not len(pa['rows']):
        return []
    hw = chain.width / 2
    skip = {e.pad for e in chain.ends if e.kind == 'pad'}
    hits = set()
    for i in chain.segs:
        L = math.hypot(b.s_x1[i] - b.s_x0[i], b.s_y1[i] - b.s_y0[i])
        k = max(2, int(L / 0.02) + 1)
        t = np.linspace(0.0, 1.0, k)
        P = np.column_stack([b.s_x0[i] + t * (b.s_x1[i] - b.s_x0[i]), b.s_y0[i] + t * (b.s_y1[i] - b.s_y0[i])])
        inside = rules._in_pads(P, pa, tol=hw - 1e-6).any(axis=0)
        for h in np.flatnonzero(inside & (pa['net'] == chain.net) & ((pa['mask'] & (1 << chain.layer)) > 0)):
            if int(h) not in skip:
                hits.add(int(h))
    return sorted(hits)


def expand(poly, width, necks, neck_len=1.0):
    """[(p, q, width)] for a route() polyline: the track's width throughout, and the minimum width for the last `neck_len` mm into each pad in `necks` (route()'s LAST_NECKS as ('start' | 'goal', pad));
    the whole leg when it is shorter: a neck-down at the pin, as a person makes it"""
    n = len(poly) - 1
    start_neck = any(k[0] == 'start' for k in necks)
    goal_neck = any(k[0] == 'goal' for k in necks)
    out = []
    for i in range(n):
        p, q = poly[i], poly[i + 1]
        L = math.hypot(q[0] - p[0], q[1] - p[1])
        cuts = {0.0, L}
        if i == 0 and start_neck:
            cuts.add(min(neck_len, L))
        if i == n - 1 and goal_neck:
            cuts.add(max(L - neck_len, 0.0))
        cuts = sorted(cuts)
        at = lambda t: (p[0] + (q[0] - p[0]) * t / L, p[1] + (q[1] - p[1]) * t / L)
        for a0, b0 in zip(cuts[:-1], cuts[1:]):
            mid = (a0 + b0) / 2
            narrow = (i == 0 and start_neck and mid <= neck_len) or (i == n - 1 and goal_neck and mid >= L - neck_len)
            out.append((at(a0), at(b0), MIN_WIDTH if narrow else width))
    return out
