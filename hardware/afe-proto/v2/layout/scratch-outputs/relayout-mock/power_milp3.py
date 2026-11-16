"""POWER block: U401 anchored, every other part from a candidate list (rotation steps, label shifts, grid), labels above, forward-checked DFS.
usage: power_csp.py UX UY CAP_SECONDS [R401_LIM]"""
import sys, math, json, random, time, os, pickle
sys.path.insert(0, '/work/hardware/afe-proto/v2/layout')
import numpy as np, relayout_place as RP
R = '/work/hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock/'
RP.ZONE = float(os.environ.get('ZONE', 0.06))
UX, UY, CAP = float(sys.argv[1]), float(sys.argv[2]), float(sys.argv[3])
R401L = float(sys.argv[4]) if len(sys.argv) > 4 else 3.0
D0, P0 = RP.load(R + 'dump_all.json'); DN, PN = RP.load(R + 'dump_new.json')
reg = RP.REGIONS['POWER']; mext, mlab = RP.Mask(reg, 0.2), RP.Mask(reg, 0.4)
def ov(a, b, g): return min(a[2], b[2]) - max(a[0], b[0]) + g > 1e-6 and min(a[3], b[3]) - max(a[1], b[1]) + g > 1e-6
POW = sorted(r for r in P0 if RP.block_of(r) == 'POWER')
# fixed obstacles: every part of the other blocks and the fixed ones, at their board positions; their labels
fixed_ext, fixed_lab = [], []
for r, p in PN.items():
    if r in POW: continue
    g = RP.part_geom(p); x, y = p['x'], p['y']
    fixed_ext.append((g['ext'][0] + x, g['ext'][1] + y, g['ext'][2] + x, g['ext'][3] + y))
    if r in ('J601', 'J602', 'J603', 'J604', 'J605', 'J606', 'J607'):
        c = RP.header_label(p); w, h = RP.LAB_W * 4, RP.LAB_H
        fixed_lab.append((c[0] - w / 2, c[1] - h / 2, c[0] + w / 2, c[1] + h / 2))
    elif r in ('U101', 'U301'):
        l, z, _ = RP.u101_label_east(PN, None, r); fixed_lab.append(l)
    elif not (r.startswith('MH') or r in ('J101', 'J201', 'J301')):
        w, h = RP.LAB_W * len(r), RP.LAB_H
        if abs((p['tang'] % 180) - 90) < 1: w, h = h, w
        fixed_lab.append((p['tx'] - w / 2, p['ty'] - h / 2, p['tx'] + w / 2, p['ty'] + h / 2))
# U401 anchored
UK = int(sys.argv[10]) if len(sys.argv) > 10 else 0
u = P0['U401']; gU = RP.part_geom(u, UK)
U_ext = (gU['ext'][0] + UX, gU['ext'][1] + UY, gU['ext'][2] + UX, gU['ext'][3] + UY)
U_lab = (gU['lab'][0] + UX, gU['lab'][1] + UY, gU['lab'][2] + UX, gU['lab'][3] + UY)
U_zone = (gU['zone'][0] + UX, gU['zone'][1] + UY, gU['zone'][2] + UX, gU['zone'][3] + UY)
_ul, _uz, _ = RP.u101_label_east(P0, {'U401': (UX, UY)}, 'U401', UK); U_lab, U_zone = _ul, _uz
U_cy = (gU['cy'][0] + UX, gU['cy'][1] + UY, gU['cy'][2] + UX, gU['cy'][3] + UY)
fixed_ext.append(U_cy); fixed_lab.append(U_lab)
fixed_ext.append((17.9, 33.8, 26.0, 37.0))        # the block name stays top-left
assert math.hypot(UX - 38.1, UY - 2.54) <= 14.99, 'U401 more than 15 mm from the 5 V pad'
pinU = {}
for q in u['pads']:
    if q['n']: pinU.setdefault(q['n'], (q['c'][0] - u['x'] + UX, q['c'][1] - u['y'] + UY))
def pad_abs(ref, k, x, y, n):
    c, s_ = RP.COS[k], RP.SIN[k]
    q = [q for q in P0[ref]['pads'] if q['n'] == n][0]
    o = (q['c'][0] - P0[ref]['x'], q['c'][1] - P0[ref]['y']); o = (o[0] * c - o[1] * s_, o[0] * s_ + o[1] * c)
    return (x + o[0], y + o[1])
NEAR = {'C401': [('1', '3 8 12', 6.41)], 'C402': [('1', '3 8 12', 2.68)], 'C403': [('1', '5', 2.93)], 'C404': [('1', '5', 6.5)], 'C405': [('1', '11', 3.33)], 'C406': [('1', '11', 4.47)],
        'C407': [('1', '6', 4.2)], 'C408': [('1', '6', 7.11)], 'C409': [('1', '10', 2.77), ('2', '9', 4.36)],
        'R402': [('1', '2', 3.69)], 'R401': [('2', '2', 4.53)], 'R405': [('1', '7', 3.51)], 'R404': [('2', '7', 4.76)], 'R403': [('1', '6', 6.47)]}
BES = ('C403', 'C404', 'C405', 'C406', 'C407', 'R401', 'R402', 'R404', 'R405') if (len(sys.argv) > 15 and sys.argv[15] == 'nine') else ('C401', 'C402', 'C403', 'C404', 'C405', 'C406', 'C407', 'C408', 'C409', 'R401', 'R402', 'R403', 'R404', 'R405')
def near_ok(ref, k, x, y):
    for n, pins, lim in NEAR.get(ref, []):
        p = pad_abs(ref, k, x, y, n)
        if min(math.hypot(p[0] - pinU[q][0], p[1] - pinU[q][1]) for q in pins.split()) > lim: return False
    return True
FREE_STEP = 0.25
def cand(ref):
    out = []; p = P0[ref]
    ks = range(4) if ref.startswith(RP.ROTATABLE) else [0]
    lss = (0, 2, 4, 10, 11) if ref in BES else (0, 2, 4)
    for k in ks:
        for ls in lss:
            gg = RP.part_geom(p, k, ls)
            if ref in NEAR:
                st_ = 0.1 if max(l for _, _, l in NEAR[ref]) > 4 else 0.05
                xs = np.arange(UX - 9, UX + 9, st_); ys = np.arange(UY - 9, UY + 9, st_)
            else:
                xs = np.arange(18.0, 43.6, 0.5); ys = np.arange(4.6, 37.0, 0.5)
            for x in xs:
                for y in ys:
                    x = round(float(x), 3); y = round(float(y), 3)
                    if ref in NEAR and not near_ok(ref, k, x, y): continue
                    e = (gg['cy'][0] + x, gg['cy'][1] + y, gg['cy'][2] + x, gg['cy'][3] + y)
                    if mext.bad(e) > 0: continue
                    lb = (gg['lab'][0] + x, gg['lab'][1] + y, gg['lab'][2] + x, gg['lab'][3] + y)
                    if mlab.bad(lb) > 0: continue
                    z = (gg['zone'][0] + x, gg['zone'][1] + y, gg['zone'][2] + x, gg['zone'][3] + y)
                    if ls >= 10: z = (lb[0] - 0.06, lb[1] - 0.06, lb[2] + 0.06, lb[3] + 0.06)
                    if any(ov(e, f, 0.02) for f in fixed_ext) or any(ov(z, f, 0) for f in fixed_ext) or any(ov(lb, f, 0.5) for f in fixed_lab) or ov(e, U_zone, 0) or ov((lb[0] - 0.3, lb[1] - 0.3, lb[2] + 0.3, lb[3] + 0.3), U_ext, 0): continue
                    out.append((ref, k, ls, x, y, e, z, lb))
    return out
cf = R + 'power_cands3_' + '_'.join(str(v) for v in (UK, UX, UY, R401L, RP.ZONE, sys.argv[5:7], sys.argv[9:12], sys.argv[13:14], sys.argv[15:16])).replace(' ', '').replace("'", '').replace('[', '').replace(']', '') + '.pkl'
if os.path.exists(cf): C = pickle.load(open(cf, 'rb'))
else:
    FREE = ('BR401', 'R406', 'R407', 'TP401', 'TP402', 'TP403', 'TP404') if (len(sys.argv) > 13 and sys.argv[13] == 'ties') else ()
    C = {r: cand(r) for r in POW if r != 'U401' and r not in FREE}; pickle.dump(C, open(cf, 'wb'))
print('domains', {r: len(v) for r, v in C.items()}, flush=True)

import scipy.sparse as sp
from scipy.optimize import milp, LinearConstraint, Bounds
K = int(os.environ.get('K', 80)) if False else int(sys.argv[12]) if len(sys.argv) > 12 else 80
TL = float(sys.argv[3])
rs = random.Random(int(sys.argv[8]) if len(sys.argv) > 8 else 1)
parts = sorted(C)
MODE = sys.argv[14] if len(sys.argv) > 14 else 'main'      # main: seed from main (least movement); west: also confine the west strip; free: random only
sel = {}
dx0, dy0 = UX - 31.5, UY - 14.0
def disp(c):
    p = P0[c[0]]; return math.hypot(c[3] - (p['x'] + dx0), c[4] - (p['y'] + dy0))
WEST = ('C403', 'C407', 'R402', 'R401', 'R404')
for r in parts:
    L = C[r]
    if MODE == 'west' and r in WEST:
        L = [c for c in L if c[3] < U_ext[0] - 0.5] or L
    L = sorted(L, key=disp)
    if MODE == 'p2': L = [c for c in L if disp(c) < 0.01]
    def pinline(c):
        o = RP.orient(P0[c[0]], c[1])
        return any(math.hypot(c[3] - pp[0], c[4] - pp[1]) <= 4 and ((o == 0 and abs(c[4] - pp[1]) <= 0.05) or (o == 90 and abs(c[3] - pp[0]) <= 0.05)) for pp in pinU.values())
    PL = [c for c in L if pinline(c)][:80]
    near = (L[:K // 2] if MODE != 'p2' else L)
    rest = L[K // 2:] if MODE != 'p2' else []
    pick = list(dict.fromkeys(near + PL + (rs.sample(rest, min(K // 2, len(rest))) if rest else [])))
    sel[r] = pick
    if MODE == 'p2': print('P2 domain', r, len(pick), flush=True)
print('MILP domains', {r: len(v) for r, v in sel.items()}, flush=True)
off = {}; n = 0
for r in parts: off[r] = n; n += len(sel[r])
def OV2(A, B, g): return ((np.minimum(A[:, None, 2], B[None, :, 2]) - np.maximum(A[:, None, 0], B[None, :, 0]) + g) > 1e-6) & ((np.minimum(A[:, None, 3], B[None, :, 3]) - np.maximum(A[:, None, 1], B[None, :, 1]) + g) > 1e-6)
rows, cols = [], []; nrow = 0
for i, p in enumerate(parts):
    E1 = np.array([c[5] for c in sel[p]]); Z1 = np.array([c[6] for c in sel[p]]); L1 = np.array([c[7] for c in sel[p]])
    for q in parts[i + 1:]:
        E2 = np.array([c[5] for c in sel[q]]); Z2 = np.array([c[6] for c in sel[q]]); L2 = np.array([c[7] for c in sel[q]])
        bad = OV2(E1, E2, 0.02) | OV2(Z1, E2, 0) | OV2(E1, Z2, 0) | OV2(L1, L2, 0.5)
        ii, jj = np.nonzero(bad)
        for a_, b_ in zip(ii, jj):
            rows += [nrow, nrow]; cols += [off[p] + a_, off[q] + b_]; nrow += 1
print('conflict rows', nrow, flush=True)
A_conf = sp.csr_matrix((np.ones(len(rows)), (rows, cols)), shape=(nrow, n))
r2, c2 = [], []
for k_, p in enumerate(parts):
    for j in range(len(sel[p])): r2.append(k_); c2.append(off[p] + j)
A_one = sp.csr_matrix((np.ones(len(r2)), (r2, c2)), shape=(len(parts), n))
cons = [LinearConstraint(A_one, 1, 1), LinearConstraint(A_conf, -np.inf, 1)]
cost = np.zeros(n)
if True:
    for r in parts:
        for j, c in enumerate(sel[r]): cost[off[r] + j] = disp(c) + (100.0 if c[2] >= 10 else 0.0) - (8.0 if pinline(c) else 0.0)
res = milp(cost, constraints=cons, integrality=np.ones(n), bounds=Bounds(0, 1), options=dict(time_limit=TL, disp=False))
print('MILP status', res.status, res.message, flush=True)
if res.x is not None and res.status in (0, 1):
    ch = []
    for p in parts:
        j = int(np.argmax(res.x[off[p]:off[p] + len(sel[p])])); ch.append(sel[p][j])
    print('MILP feasible; beside', [c[0] for c in ch if c[2] >= 10], 'obj', res.fun, flush=True)
    st = {c[0]: [c[3], c[4], ((round(P0[c[0]]['rot']) + 90 * c[1] + 180) % 360) - 180, c[2]] for c in ch}
    st['U401'] = [UX, UY, P0['U401']['rot'], 0]
    json.dump(dict(st=st), open(R + 'power_milp_%s_%s.json' % (UX, UY), 'w')); print(st)
sys.exit(0)
