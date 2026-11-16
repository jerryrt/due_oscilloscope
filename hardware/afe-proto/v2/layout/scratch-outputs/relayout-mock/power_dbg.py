"""POWER block: U401 anchored, every other part from a candidate list (rotation steps, label shifts, grid), labels above, forward-checked DFS.
usage: power_csp.py UX UY CAP_SECONDS [R401_LIM]"""
import sys, math, json, random, time, os, pickle
sys.path.insert(0, '/work/hardware/afe-proto/v2/layout')
import numpy as np, relayout_place as RP
R = '/work/hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock/'
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
u = P0['U401']; gU = RP.part_geom(u)
U_ext = (gU['ext'][0] + UX, gU['ext'][1] + UY, gU['ext'][2] + UX, gU['ext'][3] + UY)
U_lab = (gU['lab'][0] + UX, gU['lab'][1] + UY, gU['lab'][2] + UX, gU['lab'][3] + UY)
U_zone = (gU['zone'][0] + UX, gU['zone'][1] + UY, gU['zone'][2] + UX, gU['zone'][3] + UY)
fixed_ext.append(U_ext); fixed_lab.append(U_lab)
pinU = {}
for q in u['pads']:
    if q['n']: pinU.setdefault(q['n'], (q['c'][0] - u['x'] + UX, q['c'][1] - u['y'] + UY))
def pad_abs(ref, k, x, y, n):
    c, s_ = RP.COS[k], RP.SIN[k]
    q = [q for q in P0[ref]['pads'] if q['n'] == n][0]
    o = (q['c'][0] - P0[ref]['x'], q['c'][1] - P0[ref]['y']); o = (o[0] * c - o[1] * s_, o[0] * s_ + o[1] * c)
    return (x + o[0], y + o[1])
NEAR = {'C401': [('1', '3 8 12', 2.8)], 'C402': [('1', '3 8 12', 2.8)], 'C403': [('1', '5', 2.8)], 'C404': [('1', '5', 2.8)], 'C405': [('1', '11', 2.8)], 'C406': [('1', '11', 2.8)],
        'C407': [('1', '6', 2.8)], 'C408': [('1', '6', 2.8)], 'C409': [('1', '10', 2.8), ('2', '9', 2.8)], 'R402': [('1', '2', 2.8)], 'R401': [('2', '2', R401L)],
        'R404': [('2', '7', 3.76)], 'R405': [('1', '7', 2.51)], 'R403': [('1', '6', 5.47)], 'R406': [('2', '3 8 12', 8.28)]}
def near_ok(ref, k, x, y):
    for n, pins, lim in NEAR.get(ref, []):
        p = pad_abs(ref, k, x, y, n)
        if min(math.hypot(p[0] - pinU[q][0], p[1] - pinU[q][1]) for q in pins.split()) > lim: return False
    return True
FREE_STEP = 0.25
def cand(ref):
    out = []; p = P0[ref]
    ks = range(4) if ref.startswith(RP.ROTATABLE) else [0]
    lss = (0, 2, 4)
    for k in ks:
        for ls in lss:
            gg = RP.part_geom(p, k, ls)
            if ref in NEAR:
                xs = np.arange(UX - 6, UX + 6, 0.05); ys = np.arange(UY - 6, UY + 6, 0.05)
            else:
                xs = np.arange(18.0, 43.6, FREE_STEP); ys = np.arange(4.6, 37.0, FREE_STEP)
            for x in xs:
                for y in ys:
                    x = round(float(x), 3); y = round(float(y), 3)
                    if ref in NEAR and not near_ok(ref, k, x, y): continue
                    e = (gg['ext'][0] + x, gg['ext'][1] + y, gg['ext'][2] + x, gg['ext'][3] + y)
                    if mext.bad(e) > 0: continue
                    lb = (gg['lab'][0] + x, gg['lab'][1] + y, gg['lab'][2] + x, gg['lab'][3] + y)
                    if mlab.bad(lb) > 0: continue
                    z = (gg['zone'][0] + x, gg['zone'][1] + y, gg['zone'][2] + x, gg['zone'][3] + y)
                    if any(ov(e, f, 0.02) for f in fixed_ext) or any(ov(z, f, 0) for f in fixed_ext) or any(ov(lb, f, 0.5) for f in fixed_lab) or ov(e, U_zone, 0): continue
                    out.append((ref, k, ls, x, y, e, z, lb))
    return out

ref = 'C409'; n_near = 0; why = {}
for k in range(4):
    gg = RP.part_geom(P0[ref], k, 0)
    for x in np.arange(UX - 6, UX + 6, 0.05):
        for y in np.arange(UY - 6, UY + 6, 0.05):
            x = round(float(x), 3); y = round(float(y), 3)
            if not near_ok(ref, k, x, y): continue
            n_near += 1
            e = (gg['ext'][0] + x, gg['ext'][1] + y, gg['ext'][2] + x, gg['ext'][3] + y)
            r_ = []
            if mext.bad(e) > 0: r_.append('mext')
            if any(ov(e, f, 0.02) for f in fixed_ext): r_.append('ext')
            lb = (gg['lab'][0] + x, gg['lab'][1] + y, gg['lab'][2] + x, gg['lab'][3] + y); z = (gg['zone'][0] + x, gg['zone'][1] + y, gg['zone'][2] + x, gg['zone'][3] + y)
            if mlab.bad(lb) > 0: r_.append('mlab')
            if any(ov(z, f, 0) for f in fixed_ext): r_.append('zone')
            if any(ov(lb, f, 0.5) for f in fixed_lab): r_.append('lab')
            if ov(e, U_zone, 0): r_.append('Uzone')
            why[tuple(r_)] = why.get(tuple(r_), 0) + 1
print('C409 near-ok', n_near, sorted(why.items(), key=lambda t: -t[1])[:8])
print('U_ext', U_ext, 'pins 9 10', pinU['9'], pinU['10'])
