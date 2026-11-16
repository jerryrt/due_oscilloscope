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
f_cy, f_ext, f_lab = [], [], []
def add_part(r, p):
    g = RP.part_geom(p); x, y = p['x'], p['y']
    f_cy.append((g['cy'][0] + x, g['cy'][1] + y, g['cy'][2] + x, g['cy'][3] + y)); f_ext.append((g['ext'][0] + x, g['ext'][1] + y, g['ext'][2] + x, g['ext'][3] + y))
for r, p in PN.items():
    if r in PART: continue
    add_part(r, p)
    if r in ('J601', 'J602', 'J603', 'J604', 'J605', 'J606', 'J607'):
        c = RP.header_label(p); w, h = RP.LAB_W * 4, RP.LAB_H; f_lab.append((c[0] - w / 2, c[1] - h / 2, c[0] + w / 2, c[1] + h / 2))
    elif r in ('U101', 'U301', 'U401'):
        l, z, _ = RP.u101_label_east(PN, None, r); f_lab.append(l)
    elif not (r.startswith('MH') or r in ('J101', 'J201', 'J301')):
        w, h = RP.LAB_W * len(r), RP.LAB_H
        if abs((p['tang'] % 180) - 90) < 1: w, h = h, w
        f_lab.append((p['tx'] - w / 2, p['ty'] - h / 2, p['tx'] + w / 2, p['ty'] + h / 2))
f_ext.append((35.5, 45.2, 44.2, 46.9)); f_cy.append((35.5, 45.2, 44.2, 46.9))      # the block name stays top-left
f_cy = np.array(f_cy); f_ext = np.array(f_ext); f_lab = np.array(f_lab)
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
                for j in np.nonzero(~bad)[0]:
                    q = ii[j]; out.append((r, k, ls, float(X[q]), float(Y[q]), tuple(CYB[q]), tuple(ZB[q]), tuple(LB[q]), tuple(E[q])))
    return out
if __name__ == '__main__':
    C = {}
    for r in ICS:
        p = PN[r]; k = int(round((p['rot'] - P0[r]['rot']) / 90.0)) % 4
        C[r] = cands_for(r, (p['x'], p['y']), [k], [0], 0.0, 1.0)[:1]
        print(r, 'fixed', len(C[r]), flush=True)
        c = C[r][0]
        f_cy = np.vstack([f_cy, [c[5]]]); f_ext = np.vstack([f_ext, [c[8]]]); f_lab = np.vstack([f_lab, [c[7]]])
    for r in PART:
        if r in ICS: continue
        p = PN[r]
        ks = range(4) if r.startswith(RP.ROTATABLE) else [0]
        C[r] = cands_for(r, (p['x'], p['y']), ks, (0, 2, 4, 10, 11), RAD, STEP)
        # tied parts: also a window around the IC pin they are tied to
        for q in P0[r]['pads']:
            if q['net'] in ('/GND', '') or 'unconnected' in q['net']: continue
            ds = [(math.hypot(q['c'][0] - w['c'][0], q['c'][1] - w['c'][1]), ic, w['n']) for ic in ICS for w in P0[ic]['pads'] if w['net'] == q['net'] and w['n']]
            if not ds: continue
            d, ic, pn = min(ds); c0 = C[ic][0]; cs, sn = RP.COS[c0[1]], RP.SIN[c0[1]]
            wp = [w for w in P0[ic]['pads'] if w['n'] == pn][0]; o = (wp['c'][0] - P0[ic]['x'], wp['c'][1] - P0[ic]['y']); o = (o[0] * cs - o[1] * sn, o[0] * sn + o[1] * cs)
            C[r] += cands_for(r, (c0[3] + o[0], c0[4] + o[1]), ks, (0, 2, 4, 10, 11), min(d + 1.5, 6.0), STEP)
        print(r, len(C[r]), flush=True)
    pickle.dump(C, open(R + 'rc_cands.pkl', 'wb'))
