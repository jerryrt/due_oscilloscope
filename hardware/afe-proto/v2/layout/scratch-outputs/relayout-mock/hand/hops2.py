"""hops2.py BOARD [new|old]   (in the image, cwd /work): for AFE-2, kvm_01's hops.py approach (kicad/relayout/hops.py of the AFE-1 branch, read, not edited): for every open connection
(minimum spanning gaps of each net's copper components, GND excluded) the shortest straight bottom segment between two legal via sites near the loose ends: sites 0.5 mm from foreign
copper and not on a pad, within 1.6 mm of the loose end; the segment not under an analog part's courtyard + 0.45, not inside an analog fence (CH1, CH2, AWG outlines), not within 0.5 mm of
top copper of a sensitive (XSENS) net. Hop-closable when the segment is <= 3.0 mm (2 vias). The outline table is the scratch one ('new', V22) or the committed one ('old'). No router.
Also prints the D24 reading of each bridge-only gap's net and the gap-length distribution."""
import sys, math, importlib.util, types
sys.path.insert(0, '/work/hardware/afe-proto')
import numpy as np
from collections import defaultdict
from pcbtools import boardio
from pcbtools.boards import v2_layout as C0
OUT = {k: list(v) for k, v in C0.OUTLINE.items()}
if len(sys.argv) > 2 and sys.argv[2] == 'new':
    sp = importlib.util.spec_from_file_location('outl_new', '/work/hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock/hand/outlines_new.py'); t = importlib.util.module_from_spec(sp); sp.loader.exec_module(t); OUT = {k: list(v) for k, v in t.RECTS.items()}
b = boardio.read_board(sys.argv[1])
G = 0.1
XS = tuple(C0.XSENS)
NOBRIDGE = {'/AWG_FB': 'inverting node (LR-4)', '/CH1_N': 'inverting node (LR-4)', '/CH2_N': 'inverting node (LR-4)', '/LM_FBP': 'feedback node', '/LM_FBN': 'feedback node', '/LM_FB3M': 'feedback node', '/LM_C1P': 'flying cap node', '/LM_C1N': 'flying cap node', '/LM_CP': 'flying cap node'}
pads = [(b.fp_ref[int(b.p_fp[j])], str(b.p_pin[j]), b.nets[int(b.p_net[j])], float(b.p_bx0[j]), float(b.p_by0[j]), float(b.p_bx1[j]), float(b.p_by1[j]), float(b.p_x[j]), float(b.p_y[j])) for j in range(len(b.p_fp))]
trk = [(b.nets[int(b.s_net[k])], float(b.s_x0[k]), float(b.s_y0[k]), float(b.s_x1[k]), float(b.s_y1[k]), float(b.s_w[k])) for k in range(len(b.s_idx)) if int(b.s_layer[k]) == 0]
via = [(b.nets[int(b.v_net[k])], float(b.v_x[k]), float(b.v_y[k])) for k in range(len(b.v_x))]
court = [(b.fp_ref[k], float(b.fp_cx0[k]), float(b.fp_cy0[k]), float(b.fp_cx1[k]), float(b.fp_cy1[k])) for k in range(len(b.fp_ref)) if not np.isnan(b.fp_cx0[k]) and b.fp_ref[k] in C0.ANALOG_REFS]
fences = [rc for blk in C0.ANALOG_FENCE for rc in OUT.get(blk, [])]
def pseg(p, a, c):
    dx, dy = c[0] - a[0], c[1] - a[1]; L = dx * dx + dy * dy
    t = 0 if L == 0 else max(0, min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L))
    return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)
def in_box(p, bx, m=0.03): return bx[0] - m <= p[0] <= bx[2] + m and bx[1] - m <= p[1] <= bx[3] + m
nets = sorted({p[2] for p in pads if p[2]} - {'/GND'})
def block(x, y):
    for blk in ('AWG', 'REFCAL', 'CH2', 'CH1', 'POWER'):
        for (x0, y0, x1, y1) in OUT.get(blk, []):
            if x0 <= x <= x1 and y0 <= y <= y1: return blk
    return 'OTHER'
def padname(n, pt):
    best = min(((math.hypot(p[7] - pt[0], p[8] - pt[1]), p[0] + '.' + p[1]) for p in pads if p[2] == n), default=(9, '?'))
    return best[1] if best[0] < 0.4 else '(track end)'
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
            if j > i and (any(pseg(q, (o[1], o[2]), (o[3], o[4])) < 0.03 for q in ((t[1], t[2]), (t[3], t[4]))) or any(pseg(q, (t[1], t[2]), (t[3], t[4])) < 0.03 for q in ((o[1], o[2]), (o[3], o[4])))): un(idx[('t', i)], idx[('t', j)])
        for j, v in enumerate(V):
            if pseg((v[1], v[2]), (t[1], t[2]), (t[3], t[4])) < 0.05: un(idx[('t', i)], idx[('v', j)])
    for j, v in enumerate(V):
        for i, p in enumerate(P):
            if in_box((v[1], v[2]), p[3:7]): un(idx[('v', j)], idx[('p', i)])
    comps = defaultdict(list)
    for it in items: comps[f(idx[it])].append(it)
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
    for d, pa, pb, c in edges: res.append((n, pa, pb, d))
sens_trk = [t for t in trk if t[0].startswith(XS)]
sens_pad = [p for p in pads if p[2].startswith(XS)]
def legal_sites(n, pt, win=1.6):
    xs = np.arange(pt[0] - win, pt[0] + win + 1e-9, G); ys = np.arange(pt[1] - win, pt[1] + win + 1e-9, G)
    GX, GY = np.meshgrid(xs, ys, indexing='ij')
    ok = np.hypot(GX - pt[0], GY - pt[1]) <= win - 0.1
    for p in pads:
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
            px, py = t[1] + s * (t[3] - t[1]), t[2] + s * (t[4] - t[2]); ok &= np.hypot(GX - px, GY - py) >= m
    for v in via:
        if v[0] != n: ok &= np.hypot(GX - v[1], GY - v[2]) >= 0.8
    return [(float(xs[i]), float(ys[k])) for i in range(len(xs)) for k in range(len(ys)) if ok[i, k]]
def blocked(a, c, n):
    for s in np.linspace(0, 1, 30):
        px, py = a[0] + s * (c[0] - a[0]), a[1] + s * (c[1] - a[1])
        for ref, x0, y0, x1, y1 in court:
            if x0 - 0.45 <= px <= x1 + 0.45 and y0 - 0.45 <= py <= y1 + 0.45: return 'under ' + ref
        for (x0, y0, x1, y1) in fences:
            if x0 <= px <= x1 and y0 <= py <= y1: return 'inside an analog fence'
        for t in sens_trk:
            if t[0] != n and pseg((px, py), (t[1], t[2]), (t[3], t[4])) < 0.5: return 'under ' + t[0]
        for p in sens_pad:
            if p[2] != n and in_box((px, py), p[3:7], 0.5): return 'under pad %s.%s' % (p[0], p[1])
    return None
rows = []
for n, pa, pb, d in res:
    SA, SB = legal_sites(n, pa), legal_sites(n, pb); best = None; why = 'no legal via site near an end'
    if SA and SB:
        A = np.array(SA); B = np.array(SB)
        D = np.hypot(A[:, None, 0] - B[None, :, 0], A[:, None, 1] - B[None, :, 1])
        order = np.dstack(np.unravel_index(np.argsort(D, axis=None)[:80], D.shape))[0]; why = 'no clear segment'
        for i, k in order:
            a_, c_ = tuple(A[i]), tuple(B[k]); w = blocked(a_, c_, n)
            if w: why = w; continue
            best = (float(D[i, k]), a_, c_); break
    rows.append((n, pa, pb, d, best, why, block((pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2)))
agg = defaultdict(lambda: [0, 0]); lens = defaultdict(int); bo = []
for n, pa, pb, d, best, why, blk in rows:
    ok = best is not None and best[0] <= 3.0
    agg[blk][0 if ok else 1] += 1
    lens['<3' if d < 3 else '3-11' if d < 11 else '11-33' if d < 33 else '>33'] += 1
    print('GAP', blk, n, padname(n, pa), '->', padname(n, pb), 'gap %.1f mm' % d, ('hop %.2f mm' % best[0]) if best else why, 'CLOSABLE' if ok else 'BRIDGE-ONLY')
    if not ok: bo.append((blk, n, NOBRIDGE.get(n, 'can take a bridge'), round(d, 1)))
print('GAPS (spanning, non-GND):', len(rows))
for blk, (c, x) in sorted(agg.items()): print('SUMMARY', blk, 'hop-closable', c, 'bridge-only', x)
print('TOTAL hop-closable', sum(v[0] for v in agg.values()), 'bridge-only', sum(v[1] for v in agg.values()), 'against a budget of 13')
print('LENGTHS', dict(lens))
print('BRIDGE-ONLY nets that cannot take a bridge:', [x for x in bo if x[2] != 'can take a bridge'])
# ---- step-1 analysis: wall crossings per net and gaps inside each fence block (the straight line between the two loose ends)
WALL = (65.2, 2.54, 69.4, 38.0)
def seg_hits(a, c, r):
    t0, t1 = 0.0, 1.0
    for ax, cx, lo, hi in ((a[0], c[0], r[0], r[2]), (a[1], c[1], r[1], r[3])):
        d = cx - ax
        if abs(d) < 1e-12:
            if ax < lo or ax > hi: return False
        else:
            u, v = (lo - ax) / d, (hi - ax) / d
            if u > v: u, v = v, u
            t0, t1 = max(t0, u), min(t1, v)
            if t0 > t1: return False
    return True
def inside(p, r): return r[0] <= p[0] <= r[2] and r[1] <= p[1] <= r[3]
wallx = defaultdict(int); fcross = defaultdict(lambda: defaultdict(int)); inblk = defaultdict(lambda: [0, 0, 0])
for n, pa, pb, d, best, why, blk in rows:
    ok = best is not None and best[0] <= 3.0
    if seg_hits(pa, pb, WALL) and not (inside(pa, WALL) and inside(pb, WALL)) and (pa[0] < WALL[0] or pb[0] < WALL[0]) and (pa[0] > WALL[2] or pb[0] > WALL[2]): wallx[n] += 1
    for fb in ('CH1', 'CH2', 'AWG'):
        rs = OUT.get(fb, [])
        ia = any(inside(pa, r) for r in rs); ib = any(inside(pb, r) for r in rs)
        if ia != ib or (not ia and not ib and any(seg_hits(pa, pb, r) for r in rs)): fcross[n][fb] += 1
        if ia and ib:
            e = inblk[fb]; e[0] += 1; e[1 if ok else 2] += 1
print('WALL A0/A1 crossings by net:', dict(wallx), 'total', sum(wallx.values()))
print('FENCE-WALL crossings by net:', {n: dict(v) for n, v in fcross.items()})
print('FENCE-WALL crossings total:', {fb: sum(v.get(fb, 0) for v in fcross.values()) for fb in ('CH1', 'CH2', 'AWG')})
for fb in ('CH1', 'CH2', 'AWG'):
    e = inblk[fb]; sh = [d for n, pa, pb, d, best, why, blk in rows if any(inside(pa, r) for r in OUT.get(fb, [])) and any(inside(pb, r) for r in OUT.get(fb, []))]
    print('INSIDE', fb, 'gaps between its own parts', e[0], 'hop-closable', e[1], 'bridge-only', e[2], 'lengths', sorted(round(x, 1) for x in sh))
