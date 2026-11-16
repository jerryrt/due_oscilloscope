"""REF/CAL lexicographic MILP. python3 rc_milp.py STAGE KSEL TIME [BESIDE_CAP]   stage 1: fewest beside labels (then displacement); stage 2: beside <= cap, most aligned, then displacement"""
import sys, math, json, pickle, os, random, time
sys.path.insert(0, '/work/hardware/afe-proto/v2/layout')
import numpy as np, relayout_place as RP, scipy.sparse as sp
from scipy.optimize import milp, LinearConstraint, Bounds
R = '/work/hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock/'
RP.ZONE = 0.06
STAGE, K, TL = int(sys.argv[1]), int(sys.argv[2]), float(sys.argv[3]); CAP = int(sys.argv[4]) if len(sys.argv) > 4 else 99
D0, P0 = RP.load(R + 'dump_all.json'); DN, PN = RP.load(R + 'dump_new.json')
C = pickle.load(open(R + 'ch_sel_%s.pkl' % os.environ.get('TAGX', sys.argv[6] if len(sys.argv) > 6 else 'a'), 'rb'))
ICS = ()
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
for w_ in P0['U101']['pads']:
    if w_['n']: icp[('U101', w_['n'])] = (w_['c'][0], w_['c'][1])
def tie_ok(c):
    for n, net, lim in LIM.get(c[0], []):
        pp = padpos(c, n)
        if min(math.hypot(pp[0] - xy[0], pp[1] - xy[1]) for (ic, pn), xy in icp.items() if any(w['net'] == net and w['n'] == pn for w in ics0[ic]['pads'])) > lim: return False
    return True
DROP = set(sys.argv[5].split(',')) if len(sys.argv) > 5 and sys.argv[5] else set()
parts = sorted(r for r in C if r not in DROP)
def cur(r):
    p = PN[r]; return (p['x'], p['y'])
def disp(c):
    if c[0] in ICS: return 0.0
    x, y = cur(c[0]); return math.hypot(c[3] - x, c[4] - y)
def orient_of(c): return RP.orient(P0[c[0]], c[1])
def rowkey(c):
    o = orient_of(c); return (o, int(round((c[4] if o == 0 else c[3]) / 0.05)))
def pinline(c):
    o = orient_of(c)
    return any(math.hypot(c[3] - pp[0], c[4] - pp[1]) <= 4 and ((o == 0 and abs(c[4] - pp[1]) <= 0.05) or (o == 90 and abs(c[3] - pp[0]) <= 0.05)) for pp in icp.values())
PASRE = RP.PAS
TRIM = int(sys.argv[7]) if len(sys.argv) > 7 else 10**6
sel = {r: C[r][:TRIM] for r in parts}
print('domains', {r: len(v) for r, v in sel.items()}, flush=True)
off = {}; n = 0
for r in parts: off[r] = n; n += len(sel[r])
def OV2(A, B, g): return ((np.minimum(A[:, None, 2], B[None, :, 2]) - np.maximum(A[:, None, 0], B[None, :, 0]) + g) > 1e-6) & ((np.minimum(A[:, None, 3], B[None, :, 3]) - np.maximum(A[:, None, 1], B[None, :, 1]) + g) > 1e-6)
def arr(p, i): return np.array([c[i] for c in sel[p]])
AX, AG0, AG1 = 0.3, 0.0, 0.6
def PLABOVE(LB, CY):
    bx = (LB[:, None, 0] + LB[:, None, 2]) / 2; cx = (CY[None, :, 0] + CY[None, :, 2]) / 2
    return (np.abs(bx - cx) <= AX) & ((LB[:, None, 1] - CY[None, :, 3]) >= AG0 - 1e-9) & ((LB[:, None, 1] - CY[None, :, 3]) <= AG1 + 1e-9)
def PLSIDE(LB, CY):
    ys = (LB[:, None, 1] < CY[None, :, 3]) & (CY[None, :, 1] < LB[:, None, 3])
    e = ys & ((LB[:, None, 0] - CY[None, :, 2]) >= AG0 - 1e-9) & ((LB[:, None, 0] - CY[None, :, 2]) <= AG1 + 1e-9)
    w = ys & ((CY[None, :, 0] - LB[:, None, 2]) >= AG0 - 1e-9) & ((CY[None, :, 0] - LB[:, None, 2]) <= AG1 + 1e-9)
    return e | w
def PLANY(LB, CY): return PLABOVE(LB, CY) | PLSIDE(LB, CY)
rows, cols = [], []; nrow = 0
for i, p in enumerate(parts):
    CY1, Z1, L1, E1 = arr(p, 5), arr(p, 6), arr(p, 7), arr(p, 8)
    for q in parts[i + 1:]:
        CY2, Z2, L2, E2 = arr(q, 5), arr(q, 6), arr(q, 7), arr(q, 8)
        a1 = E1 if p == 'J501' else CY1; a2 = E2 if q == 'J501' else CY2
        # quick reject: bounding windows far apart
        if len(CY1) == 0 or len(CY2) == 0: continue
        if CY1[:, 2].max() < CY2[:, 0].min() or CY2[:, 2].max() < CY1[:, 0].min() or CY1[:, 3].max() < CY2[:, 1].min() or CY2[:, 3].max() < CY1[:, 1].min(): continue
        bad = OV2(a1, a2, 0.0) | OV2(Z1, a2, 0) | OV2(a1, Z2, 0) | OV2(L1, L2, 0.5) | OV2(a1, L2, 0) | OV2(L1, a2, 0)
        b1 = (np.array([c[2] for c in sel[p]]) >= 10)[:, None]; b2 = (np.array([c[2] for c in sel[q]]) >= 10)[None, :]
        bad |= (b1 & (PLANY(L2, CY1).T | PLABOVE(L1, CY2))) | (b2 & (PLANY(L1, CY2) | PLABOVE(L2, CY1).T))
        ii, jj = np.nonzero(bad)
        rows += list(np.repeat(np.arange(nrow, nrow + len(ii)), 2)); cols += [v for a_, b_ in zip(ii, jj) for v in (off[p] + a_, off[q] + b_)]; nrow += len(ii)
print('conflict rows', nrow, flush=True)
globals()['_viol'] = None
passives = [p for p in parts if PASRE.fullmatch(p)]
rowvals = sorted({rowkey(c) for p in passives for c in sel[p]}) if STAGE == 2 else []
zi = {rk: n + i for i, rk in enumerate(rowvals)}; n2 = n + len(rowvals)
wi = {}
if STAGE == 2:
    for p in passives:
        for rk in sorted({rowkey(c) for c in sel[p]}): wi[(p, rk)] = n2; n2 += 1
ai = {p: n2 + i for i, p in enumerate(passives)} if STAGE == 2 else {}; n2 += len(ai)
HIZ = {'CH1': ['/CH1_N', '/CH1_M1', '/CH1_M2', '/CH1_M3', '/CH1_NP'], 'CH2': ['/CH2_N', '/CH2_M1', '/CH2_M2', '/CH2_M3', '/CH2_NP']}[os.environ['BLK']]
HN, HO = float(os.environ.get('HN', 8.0)), float(os.environ.get('HO', 10.0))
netpads = {}
for r_, p_ in P0.items():
    for q_ in p_['pads']:
        if q_['net'] in HIZ: netpads.setdefault(q_['net'], []).append((r_, q_['n']))
hv = {}
for net_ in HIZ:
    hv[net_] = (n2, n2 + 1, n2 + 2, n2 + 3); n2 += 4
CONT = [i for v in hv.values() for i in v]

R_, C_, V_, lo, hi = [], [], [], [], []; nr = 0
def add(coefs, l, h):
    global nr
    for j, v in coefs: R_.append(nr); C_.append(j); V_.append(v)
    lo.append(l); hi.append(h); nr += 1
for p in parts: add([(off[p] + j, 1) for j in range(len(sel[p]))], 1, 1)
add([(off[p] + j, 1) for p in parts for j, c in enumerate(sel[p]) if c[2] >= 10], 0, CAP)
def padxy(c, n):
    p = P0[c[0]]; cs, sn = RP.COS[c[1]], RP.SIN[c[1]]
    q = [q for q in p['pads'] if q['n'] == n][0]; o = (q['c'][0] - p['x'], q['c'][1] - p['y']); o = (o[0] * cs - o[1] * sn, o[0] * sn + o[1] * cs)
    return (c[3] + o[0], c[4] + o[1])
for net_, (ixa, ixb, iya, iyb) in hv.items():          # xmax, xmin, ymax, ymin
    for (r_, n_) in netpads[net_]:
        if r_ in sel:
            xs_ = [padxy(c, n_) for c in sel[r_]]
            add([(off[r_] + j, v[0]) for j, v in enumerate(xs_)] + [(ixa, -1)], -np.inf, 0); add([(off[r_] + j, -v[0]) for j, v in enumerate(xs_)] + [(ixb, 1)], -np.inf, 0)
            add([(off[r_] + j, v[1]) for j, v in enumerate(xs_)] + [(iya, -1)], -np.inf, 0); add([(off[r_] + j, -v[1]) for j, v in enumerate(xs_)] + [(iyb, 1)], -np.inf, 0)
        else:
            q_ = [q for q in P0[r_]['pads'] if q['n'] == n_][0]; x_, y_ = PN[r_]['x'] + q_['c'][0] - P0[r_]['x'], PN[r_]['y'] + q_['c'][1] - P0[r_]['y']
            add([(ixa, -1)], -np.inf, -x_); add([(ixb, 1)], -np.inf, x_); add([(iya, -1)], -np.inf, -y_); add([(iyb, 1)], -np.inf, y_)
    if STAGE != 0: add([(ixa, 1), (ixb, -1), (iya, 1), (iyb, -1)], -np.inf, HN if net_.endswith('_N') else HO)
if STAGE == 0:
    for net_ in HIZ:
        if not net_.endswith('_N'): ixa, ixb, iya, iyb = hv[net_]; add([(ixa, 1), (ixb, -1), (iya, 1), (iyb, -1)], -np.inf, HO)
# LR-2 flow: x falls R101 > R107 > U101 (fixed) > R108/R208
FLOW = [('R101', 'R107'), ('R201', 'R207')]
def cx_(p): return [c[3] for c in sel[p]]
for a_, b_ in FLOW:
    if a_ in sel and b_ in sel: add([(off[a_] + j, v) for j, v in enumerate(cx_(a_))] + [(off[b_] + j, -v) for j, v in enumerate(cx_(b_))], 0.01, np.inf)
for a_ in ('R107', 'R207'):
    if a_ in sel: add([(off[a_] + j, 1) for j, c in enumerate(sel[a_]) if c[3] > PN['U101']['x'] + 0.01], 1, 1)
for a_ in ('R108', 'R208'):
    if a_ in sel: add([(off[a_] + j, 1) for j, c in enumerate(sel[a_]) if c[3] < PN['U101']['x'] - 0.01], 1, 1)
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
if STAGE == 0:
    for net_ in HIZ:
        if net_.endswith('_N'):
            ixa, ixb, iya, iyb = hv[net_]; cost[ixa] += 100; cost[ixb] -= 100; cost[iya] += 100; cost[iyb] -= 100
INTEG = np.ones(n2); LBv = np.zeros(n2); UBv = np.ones(n2)
for i_ in CONT: INTEG[i_] = 0; UBv[i_] = 200
CURP = {r_: [PN[r_]['x'], PN[r_]['y'], PN[r_]['rot']] for r_ in parts}
xcur = np.zeros(n2); curc = {}
for p in parts:
    hit = [j for j, c in enumerate(sel[p]) if abs(c[3] - CURP[p][0]) < 1e-6 and abs(c[4] - CURP[p][1]) < 1e-6 and ((round(P0[p]['rot']) + 90 * c[1] + 180) % 360) - 180 == ((round(CURP[p][2]) + 180) % 360) - 180]
    hit = [j for j in hit if sel[p][j][2] < 10]
    hit.sort(key=lambda j: math.hypot((sel[p][j][7][0] + sel[p][j][7][2]) / 2 - PN[p]['tx'], (sel[p][j][7][1] + sel[p][j][7][3]) / 2 - PN[p]['ty']))
    assert hit, ('current not a candidate', p)
    xcur[off[p] + hit[0]] = 1; curc[p] = sel[p][hit[0]]
for net_, (ixa, ixb, iya, iyb) in hv.items():
    pts_ = []
    for (r_, n_) in netpads[net_]:
        if r_ in curc: pts_.append(padxy(curc[r_], n_))
        else:
            q_ = [q for q in P0[r_]['pads'] if q['n'] == n_][0]; pts_.append((PN[r_]['x'] + q_['c'][0] - P0[r_]['x'], PN[r_]['y'] + q_['c'][1] - P0[r_]['y']))
    xcur[ixa] = max(p[0] for p in pts_); xcur[ixb] = min(p[0] for p in pts_); xcur[iya] = max(p[1] for p in pts_); xcur[iyb] = min(p[1] for p in pts_)
    print('POSITIVE CONTROL', net_, 'HPWL now', round(xcur[ixa] - xcur[ixb] + xcur[iya] - xcur[iyb], 2), flush=True)
Ar = A_rest @ xcur
viol = np.flatnonzero((Ar < np.array(lo) - 1e-9) | (Ar > np.array(hi) + 1e-9))
_v = np.flatnonzero(np.asarray(A_conf @ xcur).ravel() > 1.5)
_rows_arr = np.array(rows); _cols_arr = np.array(cols)
_owner = {}
for p_ in parts:
    for j_ in range(len(sel[p_])): _owner[off[p_] + j_] = (p_, j_)
for rr_ in _v[:12]:
    cc_ = _cols_arr[_rows_arr == rr_]; print('CONFLICT in current:', [(_owner[c_][0], sel[_owner[c_][0]][_owner[c_][1]][2], sel[_owner[c_][0]][_owner[c_][1]][3:5]) for c_ in cc_], flush=True)
print('POSITIVE CONTROL: conflict max', float((A_conf @ xcur).max()), 'rest rows violated', len(viol), '(the HPWL rows are expected)', flush=True)
CUT = os.environ.get('CUTOFF') == '1'
cons = [LinearConstraint(A_rest, lo, hi), LinearConstraint(A_conf, -np.inf, 1)]

res = milp(cost, constraints=cons, integrality=INTEG, bounds=Bounds(LBv, UBv), options=dict(time_limit=TL, disp=False, mip_rel_gap=0.0))
print('MILP status', res.status, res.message, 'gap', getattr(res, 'mip_gap', None), 'bound', getattr(res, 'mip_dual_bound', None), 'obj', res.fun, flush=True)
if res.x is not None:
    print('max conflict-row sum', float((A_conf @ res.x).max()), flush=True)
    ch = []
    for p in parts:
        j = int(np.argmax(res.x[off[p]:off[p] + len(sel[p])])); ch.append(sel[p][j])
    print('MILP feasible; beside', [c[0] for c in ch if c[2] >= 10], 'aligned', int(round(sum(res.x[ai[p]] for p in passives))) if ai else None, flush=True)
    st = {c[0]: [c[3], c[4], ((round(P0[c[0]]['rot']) + 90 * c[1] + 180) % 360) - 180, c[2]] for c in ch}
    for net_, (ixa, ixb, iya, iyb) in hv.items(): print('SOLUTION', net_, 'HPWL', round(res.x[ixa] - res.x[ixb] + res.x[iya] - res.x[iyb], 2), flush=True)
    json.dump(dict(st=st), open(R + 'ch_milp_stage%d_%s_t%dn.json' % (STAGE, sys.argv[6] if len(sys.argv) > 6 else 'a', TRIM), 'w')); print(st)
