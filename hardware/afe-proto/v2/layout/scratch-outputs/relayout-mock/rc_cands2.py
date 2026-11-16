"""REF/CAL candidates: every part (U501, U502 fixed at their board positions), vectorised obstacle checks. python3 rc_cands.py"""
import sys, math, json, pickle, os, random
sys.path.insert(0, '/work/hardware/afe-proto/v2/layout')
import numpy as np, relayout_place as RP
R = '/work/hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock/'
RP.ZONE = 0.06
D0, P0 = RP.load(R + 'dump_all.json'); DN, PN = RP.load(R + 'dump_new.json')
BLK = 'REFCAL'
reg = RP.REGIONS[BLK]; mext, mlab = RP.Mask(reg, 0.2), RP.Mask(reg, 0.4)
PART = sorted(r for r in P0 if RP.block_of(r) == BLK)
ICS = ('U501', 'U502')
STEP, RAD = 0.1, float(os.environ.get('RAD', 3.0))
def vbad(mask, B):          # vectorised Mask.bad for boxes B (n,4)
    i0 = np.maximum(np.floor((B[:, 0] - mask.x0) / RP.RES + 1e-6).astype(int), 0); i1 = np.minimum(np.ceil((B[:, 2] - mask.x0) / RP.RES - 1e-6).astype(int), mask.nx)
    j0 = np.maximum(np.floor((B[:, 1] - mask.y0) / RP.RES + 1e-6).astype(int), 0); j1 = np.minimum(np.ceil((B[:, 3] - mask.y0) / RP.RES - 1e-6).astype(int), mask.ny)
    ok = (i1 > i0) & (j1 > j0)
    i1 = np.where(ok, i1, i0); j1 = np.where(ok, j1, j0)
    S = mask.S
    n = S[i1, j1] - S[i0, j1] - S[i1, j0] + S[i0, j0]
    out = (np.maximum(0, -(B[:, 0] - mask.x0)) + np.maximum(0, (B[:, 2] - mask.x0) - mask.nx * RP.RES) + np.maximum(0, -(B[:, 1] - mask.y0)) + np.maximum(0, (B[:, 3] - mask.y0) - mask.ny * RP.RES))
    return np.where(ok, n * RP.RES * RP.RES * 4 + out * 10, 1e3)
def OVm(A, B, g):           # (n,4) x (m,4) -> (n,m) bool
    return ((np.minimum(A[:, None, 2], B[None, :, 2]) - np.maximum(A[:, None, 0], B[None, :, 0]) + g) > 1e-6) & ((np.minimum(A[:, None, 3], B[None, :, 3]) - np.maximum(A[:, None, 1], B[None, :, 1]) + g) > 1e-6)
# obstacles: parts of every other block (courtyard, extent with silk) and their labels, at board positions

AX, AG0, AG1 = 0.3, 0.0, 0.6
def pl_above(LB, CY):
    bx = (LB[:, None, 0] + LB[:, None, 2]) / 2; cx = (CY[None, :, 0] + CY[None, :, 2]) / 2
    return (np.abs(bx - cx) <= AX) & ((LB[:, None, 1] - CY[None, :, 3]) >= AG0 - 1e-9) & ((LB[:, None, 1] - CY[None, :, 3]) <= AG1 + 1e-9)
def pl_side(LB, CY):
    ys = (LB[:, None, 1] < CY[None, :, 3]) & (CY[None, :, 1] < LB[:, None, 3])
    e = ys & ((LB[:, None, 0] - CY[None, :, 2]) >= AG0 - 1e-9) & ((LB[:, None, 0] - CY[None, :, 2]) <= AG1 + 1e-9)
    w = ys & ((CY[None, :, 0] - LB[:, None, 2]) >= AG0 - 1e-9) & ((CY[None, :, 0] - LB[:, None, 2]) <= AG1 + 1e-9)
    return e | w
def pl_any(LB, CY): return pl_above(LB, CY) | pl_side(LB, CY)
BESIDE_FIX = {'R304', 'C301', 'C306', 'C402', 'C403', 'C405', 'C406', 'C407', 'C408', 'R402', 'R403', 'R404', 'R405'}

f_cy, f_ext, f_lab = [], [], []
f_bcy = []
def add_part(r, p):
    g = RP.part_geom(p); x, y = p['x'], p['y']
    f_cy.append((g['cy'][0] + x, g['cy'][1] + y, g['cy'][2] + x, g['cy'][3] + y)); f_ext.append((g['ext'][0] + x, g['ext'][1] + y, g['ext'][2] + x, g['ext'][3] + y))
for r, p in PN.items():
    if r in PART: continue
    add_part(r, p)
    if r in BESIDE_FIX: f_bcy.append(f_cy[-1])
    if r in ('J601', 'J602', 'J603', 'J604', 'J605', 'J606', 'J607'):
        c = RP.header_label(p); w, h = RP.LAB_W * 4, RP.LAB_H; f_lab.append((c[0] - w / 2, c[1] - h / 2, c[0] + w / 2, c[1] + h / 2))
    elif r in ('U101', 'U301', 'U401'):
        l, z, _ = RP.u101_label_east(PN, None, r); f_lab.append(l)
    elif not (r.startswith('MH') or r in ('J101', 'J201', 'J301')):
        w, h = RP.LAB_W * len(r), RP.LAB_H
        if abs((p['tang'] % 180) - 90) < 1: w, h = h, w
        f_lab.append((p['tx'] - w / 2, p['ty'] - h / 2, p['tx'] + w / 2, p['ty'] + h / 2))
f_ext.append((35.5, 45.2, 44.2, 46.9)); f_cy.append((35.5, 45.2, 44.2, 46.9))      # the block name stays top-left
f_cy = np.array(f_cy); f_ext = np.array(f_ext); f_lab = np.array(f_lab); f_bcy = np.array(f_bcy)

def cands_for(r, center, ks, lss, rad, step):
    p = P0[r]; out = []
    cx, cy_ = center
    xs = np.arange(cx - rad, cx + rad + 1e-9, step); ys = np.arange(cy_ - rad, cy_ + rad + 1e-9, step)
    X, Y = np.meshgrid(np.round(xs, 3), np.round(ys, 3)); X = X.ravel(); Y = Y.ravel()
    for k in ks:
        for ls in lss:
            gg = RP.part_geom(p, k, ls)
            def box(b): return np.stack([X + b[0], Y + b[1], X + b[2], Y + b[3]], 1)
            E = box(gg['ext']); CYB = box(gg['cy']); LB = box(gg['lab'])
            ZB = box((gg['lab'][0] - 0.06, gg['lab'][1] - 0.06, gg['lab'][2] + 0.06, gg['lab'][3] + 0.06)) if ls >= 10 else box(gg['zone'])
            ok = (vbad(mext, E) <= 0) & (vbad(mlab, LB) <= 0)
            idx = np.nonzero(ok)[0]
            if not len(idx): continue
            for c0 in range(0, len(idx), 2000):
                ii = idx[c0:c0 + 2000]
                bad = OVm(CYB[ii], f_cy, 0.0).any(1) | OVm(ZB[ii], f_cy, 0).any(1) | OVm(LB[ii], f_lab, 0.5).any(1) | OVm(CYB[ii], f_lab, 0).any(1)
                infl = LB[ii] + np.array([-0.3, -0.3, 0.3, 0.3])
                bad |= OVm(infl, f_ext, 0).any(1)
                bad |= pl_any(LB[ii], f_bcy).any(1)
                if ls >= 10: bad |= pl_above(LB[ii], f_cy).any(1) | pl_any(f_lab, CYB[ii]).any(0)
                for j in np.nonzero(~bad)[0]:
                    q = ii[j]; out.append((r, k, ls, float(X[q]), float(Y[q]), tuple(CYB[q]), tuple(ZB[q]), tuple(LB[q]), tuple(E[q])))
    return out

KSEL = 100
TAG = sys.argv[1] if len(sys.argv) > 1 else 'a'
TIEDSET = set(os.environ.get('TIEDSET', 'C501,C502,C503').split(','))
OFFS = {'U501': (float(sys.argv[2]), float(sys.argv[3])), 'U502': (float(sys.argv[4]), float(sys.argv[5]))} if len(sys.argv) > 5 else {'U501': (0, 0), 'U502': (0, 0)}
ics0 = {r: P0[r] for r in ICS}
LIM = {}
for r in PART:
    if r in ICS: continue
    for q in P0[r]['pads']:
        if q['net'] in ('/GND', '') or 'unconnected' in q['net']: continue
        ds = [(math.hypot(q['c'][0] - w['c'][0], q['c'][1] - w['c'][1]), ic, w['n']) for ic, pic in ics0.items() for w in pic['pads'] if w['net'] == q['net'] and w['n']]
        if ds:
            d = min(ds); LIM.setdefault(r, []).append((q['n'], q['net'], d[0] + 1.0, d[1], d[2]))
for r, v in list(LIM.items()):
    if r == 'C503': LIM[r] = [(n, net, 2.8, ic, pn) for n, net, l, ic, pn in v]
    if r in ('C501', 'C502'): LIM[r] = [(n, net, min(l, 2.99), ic, pn) for n, net, l, ic, pn in v]
LIM = {r: v for r, v in LIM.items() if r in TIEDSET}
icp = {}
def padpos(c, n):
    p = P0[c[0]]; cs, sn = RP.COS[c[1]], RP.SIN[c[1]]
    q = [q for q in p['pads'] if q['n'] == n][0]; o = (q['c'][0] - p['x'], q['c'][1] - p['y']); o = (o[0] * cs - o[1] * sn, o[0] * sn + o[1] * cs)
    return (c[3] + o[0], c[4] + o[1])
def tie_ok(c):
    for n, net, lim, ic, pn in LIM.get(c[0], []):
        pp = padpos(c, n); xy = icp[(ic, pn)]
        if math.hypot(pp[0] - xy[0], pp[1] - xy[1]) > lim: return False
    return True
def gen(r):
    p = PN[r]; ks = range(4) if r.startswith(RP.ROTATABLE) else [0]
    L = cands_for(r, (p['x'], p['y']), ks, (0, 2, 4, 10, 11), RAD, STEP)
    pm = P0[r]
    L += cands_for(r, (pm['x'], pm['y']), ks, (0, 2, 4, 10, 11), 9.0 if r == 'J501' else 4.0, STEP)
    L += cands_for(r, (53.1, 26.75), ks, (0, 2, 4, 10, 11), 22.5, 0.25)
    L = list({(c[0], c[1], c[2], c[3], c[4]): c for c in L}.values())
    for (n, net, lim, ic, pn) in LIM.get(r, []):
        xy = icp[(ic, pn)]
        L += cands_for(r, xy, ks, (0, 2, 4, 10, 11), min(lim + 0.5, 6.0), STEP)
    if r in ('R501', 'R502', 'R503', 'R504', 'R505'): L = [c for c in L if c[4] <= 27.7]
    return [c for c in L if tie_ok(c)]
def disp(c):
    p = PN[c[0]]; return math.hypot(c[3] - p['x'], c[4] - p['y'])
def orient_of(c): return RP.orient(P0[c[0]], c[1])
def rowkey(c):
    o = orient_of(c); return (o, int(round((c[4] if o == 0 else c[3]) / 0.05)))
def pinline(c):
    o = orient_of(c)
    return any(math.hypot(c[3] - pp[0], c[4] - pp[1]) <= 4 and ((o == 0 and abs(c[4] - pp[1]) <= 0.05) or (o == 90 and abs(c[3] - pp[0]) <= 0.05)) for pp in icp.values())
if __name__ == '__main__':
    C = {}
    for r in ICS:
        p = P0[r]; off_ = OFFS[r]
        C[r] = cands_for(r, (p['x'] + off_[0], p['y'] + off_[1]), [0], (0, 2, 4, 10, 11), 0.0, 1.0)
        print(r, 'label modes legal at the fixed position:', len(C[r]), flush=True)
        c = C[r][0]
        for w in P0[r]['pads']:
            if w['n']: icp.setdefault((r, w['n']), (c[3] + w['c'][0] - P0[r]['x'], c[4] + w['c'][1] - P0[r]['y']))
        f_cy = np.vstack([f_cy, [c[5]]]); f_ext = np.vstack([f_ext, [c[8]]])
    others = [r for r in PART if r not in ICS]
    near, hist = {}, {}
    for r in others:
        L = gen(r); L.sort(key=disp); near[r] = L[:KSEL // 3]
        for c in near[r] + [c for c in L if pinline(c)][:30]: hist[rowkey(c)] = hist.get(rowkey(c), 0) + 1
        print('pass1', r, len(L), flush=True)
    topset = set(sorted(hist, key=lambda k_: -hist[k_])[:80]); rs = random.Random(1)
    for r in others:
        L = gen(r); L.sort(key=disp); pl = [c for c in L if pinline(c)][:40]; rowc = []; cnt = {}
        for c in L:
            k_ = rowkey(c)
            if k_ in topset and cnt.get(k_, 0) < 2: rowc.append(c); cnt[k_] = cnt.get(k_, 0) + 1
        rest = L[KSEL // 3:]
        C[r] = list(dict.fromkeys(near[r] + pl + rowc[:100] + (rs.sample(rest, min(KSEL // 3, len(rest))) if rest else [])))
        print('pass2', r, len(C[r]), flush=True)
    pickle.dump(C, open(R + 'rc_sel_%s.pkl' % TAG, 'wb'))
    print('done', flush=True)
