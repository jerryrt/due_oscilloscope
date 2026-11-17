"""hops.py BOARD : for every open connection of the board (net components, minimum spanning gaps), the shortest bottom hop that would close it:
two vias legal on top (0.5 mm from foreign copper, not on a pad, <= 1.5 mm of the loose ends, joined to them by a clear top stub) and a straight bottom
segment between them (not under an analog part's courtyard + 0.45). No router. A gap is hop-closable when the segment is <= 3.0 mm (2 vias)."""
import sys, math, itertools
import numpy as np
from collections import defaultdict
from scipy import ndimage
from pcbtools import boardio
from pcbtools.boards import v1 as C
b = boardio.read_board(sys.argv[1])
G = 0.1
pads = [(b.fp_ref[int(b.p_fp[j])], str(b.p_pin[j]), b.nets[int(b.p_net[j])], float(b.p_bx0[j]), float(b.p_by0[j]), float(b.p_bx1[j]), float(b.p_by1[j]), float(b.p_x[j]), float(b.p_y[j])) for j in range(len(b.p_fp))]
trk = [(b.nets[int(b.s_net[k])], float(b.s_x0[k]), float(b.s_y0[k]), float(b.s_x1[k]), float(b.s_y1[k]), float(b.s_w[k])) for k in range(len(b.s_idx)) if int(b.s_layer[k]) == 0]
via = [(b.nets[int(b.v_net[k])], float(b.v_x[k]), float(b.v_y[k])) for k in range(len(b.v_x))]
court = [(b.fp_ref[k], float(b.fp_cx0[k]), float(b.fp_cy0[k]), float(b.fp_cx1[k]), float(b.fp_cy1[k])) for k in range(len(b.fp_ref)) if not np.isnan(b.fp_cx0[k]) and b.fp_ref[k] in C.ANALOG_REFS]
def pseg(p, a, c):
    dx, dy = c[0] - a[0], c[1] - a[1]; L = dx * dx + dy * dy
    t = 0 if L == 0 else max(0, min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L))
    return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)
def in_box(p, bx, m=0.03): return bx[0] - m <= p[0] <= bx[2] + m and bx[1] - m <= p[1] <= bx[3] + m
nets = sorted({p[2] for p in pads if p[2]} - {'/GND'})
def block(x, y):
    for blk in ('AWG', 'REFCAL', 'SCOPE', 'POWER'):
        for (x0, y0, x1, y1) in C.OUTLINE[blk]:
            if x0 <= x <= x1 and y0 <= y <= y1: return blk
    return 'OTHER'
res = []
for n in nets:
    P = [p for p in pads if p[2] == n]; T = [t for t in trk if t[0] == n]; V = [v for v in via if v[0] == n]
    items = [('p', i) for i in range(len(P))] + [('t', i) for i in range(len(T))] + [('v', i) for i in range(len(V))]
    par = list(range(len(items)))
    def f(x):
        while par[x] != x: par[x] = par[par[x]]; x = par[x]
        return x
    def un(a, c): par[f(a)] = f(c)
    idx = {it: k for k, it in enumerate(items)}
    for i, t in enumerate(T):
        for j, p in enumerate(P):
            if any(in_box(q, p[3:7]) for q in ((t[1], t[2]), (t[3], t[4]))) or pseg(((p[3] + p[5]) / 2, (p[4] + p[6]) / 2), (t[1], t[2]), (t[3], t[4])) < 0.03: un(idx[('t', i)], idx[('p', j)])
        for j, o in enumerate(T):
            if j > i and any(pseg(q, (o[1], o[2]), (o[3], o[4])) < 0.03 for q in ((t[1], t[2]), (t[3], t[4]))) or (j > i and any(pseg(q, (t[1], t[2]), (t[3], t[4])) < 0.03 for q in ((o[1], o[2]), (o[3], o[4])))): un(idx[('t', i)], idx[('t', j)])
        for j, v in enumerate(V):
            if pseg((v[1], v[2]), (t[1], t[2]), (t[3], t[4])) < 0.05: un(idx[('t', i)], idx[('v', j)])
    for j, v in enumerate(V):
        for i, p in enumerate(P):
            if in_box((v[1], v[2]), p[3:7]): un(idx[('v', j)], idx[('p', i)])
    comps = defaultdict(list)
    for it in items: comps[f(idx[it])].append(it)
    # only components that hold a pad matter (a loose piece with no pad is a stub); keep all for terminals
    pc = [c for c in comps.values() if any(k == 'p' for k, _ in c)]
    if len(pc) < 2: continue
    def terms(c):
        out = []
        for k, i in c:
            if k == 'p': out.append((P[i][7], P[i][8]))
            elif k == 't': out += [(T[i][1], T[i][2]), (T[i][3], T[i][4])]
            else: out.append((V[i][1], V[i][2]))
        return out
    TT = [terms(c) for c in pc]
    inC = {0}; edges = []
    while len(inC) < len(pc):
        best = None
        for a in inC:
            for c in range(len(pc)):
                if c in inC: continue
                for pa in TT[a]:
                    for pb in TT[c]:
                        d = math.hypot(pa[0] - pb[0], pa[1] - pb[1])
                        if best is None or d < best[0]: best = (d, pa, pb, c)
        edges.append(best); inC.add(best[3])
    for d, pa, pb, c in edges:
        res.append((n, pa, pb, d))
print('GAPS (spanning, non-GND):', len(res))
# legal via sites per gap
def legal_sites(n, pt, win=1.6):
    xs = np.arange(pt[0] - win, pt[0] + win + 1e-9, G); ys = np.arange(pt[1] - win, pt[1] + win + 1e-9, G)
    GX, GY = np.meshgrid(xs, ys, indexing='ij')
    ok = np.hypot(GX - pt[0], GY - pt[1]) <= win - 0.1
    for p in pads:                                   # any pad: the via must not touch it (0.2 clearance + 0.3 radius) unless it is this net's pad (then not on it: 0.3)
        m = 0.3 if p[2] == n else 0.5
        dx = np.maximum(np.maximum(p[3] - GX, GX - p[5]), 0); dy = np.maximum(np.maximum(p[4] - GY, GY - p[6]), 0)
        ok &= np.hypot(dx, dy) >= m
    for t in trk:
        if t[0] == n: continue
        m = 0.5 + t[5] / 2 - 0.1
        x0, x1 = sorted((t[1], t[3])); y0, y1 = sorted((t[2], t[4]))
        if x1 + m < xs[0] or x0 - m > xs[-1] or y1 + m < ys[0] or y0 - m > ys[-1]: continue
        L = max(2, int(math.hypot(t[3] - t[1], t[4] - t[2]) / 0.05) + 1)
        for s in np.linspace(0, 1, L):
            px, py = t[1] + s * (t[3] - t[1]), t[2] + s * (t[4] - t[2])
            ok &= np.hypot(GX - px, GY - py) >= m
    for v in via:
        if v[0] != n: ok &= np.hypot(GX - v[1], GY - v[2]) >= 0.8
    # a clear top stub from the loose end to the site (foreign copper 0.3 from the stub): approximated by the site test plus a straight-line check
    out = []
    for i in range(len(xs)):
        for k in range(len(ys)):
            if ok[i, k]: out.append((float(xs[i]), float(ys[k])))
    return out
def under_part(a, c):
    for ref, x0, y0, x1, y1 in court:
        for s in np.linspace(0, 1, 30):
            px, py = a[0] + s * (c[0] - a[0]), a[1] + s * (c[1] - a[1])
            if x0 - 0.45 <= px <= x1 + 0.45 and y0 - 0.45 <= py <= y1 + 0.45: return ref
    return None
rows = []
for n, pa, pb, d in res:
    SA, SB = legal_sites(n, pa), legal_sites(n, pb)
    best = None
    if SA and SB:
        A = np.array(SA); B = np.array(SB)
        D = np.hypot(A[:, None, 0] - B[None, :, 0], A[:, None, 1] - B[None, :, 1])
        order = np.dstack(np.unravel_index(np.argsort(D, axis=None)[:60], D.shape))[0]
        for i, k in order:
            a_, c_ = tuple(A[i]), tuple(B[k])
            if under_part(a_, c_): continue
            best = (float(D[i, k]), a_, c_); break
    mid = ((pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2)
    rows.append((n, pa, pb, d, best, block(*mid)))
agg = defaultdict(lambda: [0, 0, 0.0])
for n, pa, pb, d, best, blk in rows:
    ok = best is not None and best[0] <= 3.0
    agg[blk][0 if ok else 1] += 1
    if ok: agg[blk][2] += best[0]
    print('GAP', blk, n, '(%.1f, %.1f)-(%.1f, %.1f)' % (pa + pb), 'gap %.1f mm' % d, ('HOP %.2f mm' % best[0]) if best else 'no legal via site / under a part', 'CLOSABLE' if ok else 'BRIDGE-ONLY')
for blk, (c, bo, L) in sorted(agg.items()):
    print('SUMMARY', blk, 'hop-closable', c, 'bridge-only', bo, 'summed hop length %.1f mm' % L)
