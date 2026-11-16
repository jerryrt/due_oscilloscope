"""REF/CAL lexicographic MILP. python3 rc_milp.py STAGE KSEL TIME [BESIDE_CAP]   stage 1: fewest beside labels (then displacement); stage 2: beside <= cap, most aligned, then displacement"""
import sys, math, json, pickle, os, random, time
sys.path.insert(0, '/work/hardware/afe-proto/v2/layout')
import numpy as np, relayout_place as RP, scipy.sparse as sp
from scipy.optimize import milp, LinearConstraint, Bounds
R = '/work/hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock/'
RP.ZONE = 0.06
STAGE, K, TL = int(sys.argv[1]), int(sys.argv[2]), float(sys.argv[3]); CAP = int(sys.argv[4]) if len(sys.argv) > 4 else 99
D0, P0 = RP.load(R + 'dump_all.json'); DN, PN = RP.load(R + 'dump_new.json')
C = pickle.load(open(R + 'rc_sel_%s.pkl' % os.environ.get('TAGX', sys.argv[6] if len(sys.argv) > 6 else 'a'), 'rb'))
ICS = ('U501', 'U502')
icp = {}
for r in ICS:
    c = C[r][0]; p0 = P0[r]; cs, sn = RP.COS[c[1]], RP.SIN[c[1]]
    for q in p0['pads']:
        if not q['n']: continue
        o = (q['c'][0] - p0['x'], q['c'][1] - p0['y']); o = (o[0] * cs - o[1] * sn, o[0] * sn + o[1] * cs)
        icp.setdefault((r, q['n']), (c[3] + o[0], c[4] + o[1]))
def padpos(c, n):
    p = P0[c[0]]; cs, sn = RP.COS[c[1]], RP.SIN[c[1]]
    q = [q for q in p['pads'] if q['n'] == n][0]; o = (q['c'][0] - p['x'], q['c'][1] - p['y']); o = (o[0] * cs - o[1] * sn, o[0] * sn + o[1] * cs)
    return (c[3] + o[0], c[4] + o[1])
# tied parts: every pad on a non-GND net shared with a U501/U502 pad; limit = main pad-to-pin + 1.0 (C503 2.8, LR-12 caps below 3.0)
ics0 = {r: P0[r] for r in ICS}
LIM = {}
for r in C:
    if r in ICS: continue
    for q in P0[r]['pads']:
        if q['net'] in ('/GND', '') or 'unconnected' in q['net']: continue
        ds = [(math.hypot(q['c'][0] - w['c'][0], q['c'][1] - w['c'][1]), ic, w['n']) for ic, pic in ics0.items() for w in pic['pads'] if w['net'] == q['net'] and w['n']]
        if ds:
            d = min(ds); LIM.setdefault(r, []).append((q['n'], q['net'], d[0] + 1.0))
for r, v in list(LIM.items()):
    if r == 'C503': LIM[r] = [(n, net, 2.8) for n, net, l in v]
    if r in ('C501', 'C502'): LIM[r] = [(n, net, min(l, 2.99)) for n, net, l in v]
def tie_ok(c):
    for n, net, lim in LIM.get(c[0], []):
        pp = padpos(c, n)
        if min(math.hypot(pp[0] - xy[0], pp[1] - xy[1]) for (ic, pn), xy in icp.items() if any(w['net'] == net and w['n'] == pn for w in ics0[ic]['pads'])) > lim: return False
    return True
DROP = set(sys.argv[5].split(',')) if len(sys.argv) > 5 and sys.argv[5] else set()
parts = sorted(r for r in C if r not in ICS and r not in DROP)
def cur(r):
    p = PN[r]; return (p['x'], p['y'])
def disp(c):
    x, y = cur(c[0]); return math.hypot(c[3] - x, c[4] - y)
def orient_of(c): return RP.orient(P0[c[0]], c[1])
def rowkey(c):
    o = orient_of(c); return (o, int(round((c[4] if o == 0 else c[3]) / 0.05)))
def pinline(c):
    o = orient_of(c)
    return any(math.hypot(c[3] - pp[0], c[4] - pp[1]) <= 4 and ((o == 0 and abs(c[4] - pp[1]) <= 0.05) or (o == 90 and abs(c[3] - pp[0]) <= 0.05)) for pp in icp.values())
PASRE = RP.PAS
sel = {r: C[r] for r in parts}
print('domains', {r: len(v) for r, v in sel.items()}, flush=True)
off = {}; n = 0
for r in parts: off[r] = n; n += len(sel[r])
def OV2(A, B, g): return ((np.minimum(A[:, None, 2], B[None, :, 2]) - np.maximum(A[:, None, 0], B[None, :, 0]) + g) > 1e-6) & ((np.minimum(A[:, None, 3], B[None, :, 3]) - np.maximum(A[:, None, 1], B[None, :, 1]) + g) > 1e-6)
def arr(p, i): return np.array([c[i] for c in sel[p]])
rows, cols = [], []; nrow = 0
for i, p in enumerate(parts):
    CY1, Z1, L1, E1 = arr(p, 5), arr(p, 6), arr(p, 7), arr(p, 8)
    for q in parts[i + 1:]:
        CY2, Z2, L2, E2 = arr(q, 5), arr(q, 6), arr(q, 7), arr(q, 8)
        a1 = E1 if p == 'J501' else CY1; a2 = E2 if q == 'J501' else CY2
        # quick reject: bounding windows far apart
        if len(CY1) == 0 or len(CY2) == 0: continue
        if CY1[:, 2].min() + 9 < CY2[:, 0].min() or CY2[:, 2].min() + 9 < CY1[:, 0].min() or CY1[:, 3].min() + 9 < CY2[:, 1].min() or CY2[:, 3].min() + 9 < CY1[:, 1].min(): continue
        bad = OV2(a1, a2, 0.02) | OV2(Z1, a2, 0) | OV2(a1, Z2, 0) | OV2(L1, L2, 0.5)
        ii, jj = np.nonzero(bad)
        rows += list(np.repeat(np.arange(nrow, nrow + len(ii)), 2)); cols += [v for a_, b_ in zip(ii, jj) for v in (off[p] + a_, off[q] + b_)]; nrow += len(ii)
print('conflict rows', nrow, flush=True)
passives = [p for p in parts if PASRE.fullmatch(p)]
rowvals = sorted({rowkey(c) for p in passives for c in sel[p]}) if STAGE == 2 else []
zi = {rk: n + i for i, rk in enumerate(rowvals)}; n2 = n + len(rowvals)
wi = {}
if STAGE == 2:
    for p in passives:
        for rk in sorted({rowkey(c) for c in sel[p]}): wi[(p, rk)] = n2; n2 += 1
ai = {p: n2 + i for i, p in enumerate(passives)} if STAGE == 2 else {}; n2 += len(ai)
R_, C_, V_, lo, hi = [], [], [], [], []; nr = 0
def add(coefs, l, h):
    global nr
    for j, v in coefs: R_.append(nr); C_.append(j); V_.append(v)
    lo.append(l); hi.append(h); nr += 1
for p in parts: add([(off[p] + j, 1) for j in range(len(sel[p]))], 1, 1)
add([(off[p] + j, 1) for p in parts for j, c in enumerate(sel[p]) if c[2] >= 10], 0, CAP)
if STAGE == 2:
    byrow = {}
    for p in passives:
        for j, c in enumerate(sel[p]): byrow.setdefault(rowkey(c), []).append((off[p] + j, -1))
    for rk in rowvals: add([(zi[rk], 2)] + byrow[rk], -np.inf, 0)
    for (p, rk), w in wi.items():
        add([(w, 1)] + [(off[p] + j, -1) for j, c in enumerate(sel[p]) if rowkey(c) == rk], -np.inf, 0); add([(w, 1), (zi[rk], -1)], -np.inf, 0)
    for p in passives: add([(ai[p], 1)] + [(off[p] + j, -1) for j, c in enumerate(sel[p]) if pinline(c)] + [(w, -1) for (q, rk), w in wi.items() if q == p], -np.inf, 0)
A_conf = sp.csr_matrix((np.ones(len(rows)), (rows, cols)), shape=(nrow, n2)); A_rest = sp.csr_matrix((V_, (R_, C_)), shape=(nr, n2))
cost = np.zeros(n2)
for p in parts:
    for j, c in enumerate(sel[p]): cost[off[p] + j] = disp(c) + (100.0 if (STAGE == 1 and c[2] >= 10) else 0.0)
for p in ai: cost[ai[p]] = -1000.0
res = milp(cost, constraints=[LinearConstraint(A_rest, lo, hi), LinearConstraint(A_conf, -np.inf, 1)], integrality=np.ones(n2), bounds=Bounds(0, 1), options=dict(time_limit=TL, disp=False, mip_rel_gap=0.0))
print('MILP status', res.status, res.message, 'gap', getattr(res, 'mip_gap', None), 'bound', getattr(res, 'mip_dual_bound', None), 'obj', res.fun, flush=True)
if res.x is not None:
    ch = []
    for p in parts:
        j = int(np.argmax(res.x[off[p]:off[p] + len(sel[p])])); ch.append(sel[p][j])
    print('MILP feasible; beside', [c[0] for c in ch if c[2] >= 10], 'aligned', int(round(sum(res.x[ai[p]] for p in passives))) if ai else None, flush=True)
    st = {c[0]: [c[3], c[4], ((round(P0[c[0]]['rot']) + 90 * c[1] + 180) % 360) - 180, c[2]] for c in ch}
    for r in ICS:
        c = C[r][0]; st[r] = [c[3], c[4], ((round(P0[r]['rot']) + 90 * c[1] + 180) % 360) - 180, 0]
    json.dump(dict(st=st), open(R + 'rc_milp_stage%d_%s.json' % (STAGE, sys.argv[6] if len(sys.argv) > 6 else 'a'), 'w')); print(st)
