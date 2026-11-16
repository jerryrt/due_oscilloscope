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
u = P0['U401']; gU = RP.part_geom(u)
U_ext = (gU['ext'][0] + UX, gU['ext'][1] + UY, gU['ext'][2] + UX, gU['ext'][3] + UY)
U_lab = (gU['lab'][0] + UX, gU['lab'][1] + UY, gU['lab'][2] + UX, gU['lab'][3] + UY)
U_zone = (gU['zone'][0] + UX, gU['zone'][1] + UY, gU['zone'][2] + UX, gU['zone'][3] + UY)
_ul, _uz, _ = RP.u101_label_east(P0, {'U401': (UX, UY)}, 'U401'); U_lab, U_zone = _ul, _uz
fixed_ext.append(U_ext); fixed_lab.append(U_lab)
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
NEAR = {'C401': [('1', '3 8 12', 3.0)], 'C402': [('1', '3 8 12', 2.68)], 'C403': [('1', '5', 2.8)], 'C404': [('1', '5', 6.5)], 'C405': [('1', '11', 2.8)], 'C406': [('1', '11', 4.47)],
        'C407': [('1', '6', 2.8)], 'C408': [('1', '6', 7.11)], 'C409': [('1', '10', 2.77), ('2', '9', 4.36)],
        'R402': [('1', '2', 3.69)], 'R401': [('2', '2', 4.53)], 'R405': [('1', '7', 3.51)], 'R404': [('2', '7', 4.76)], 'R403': [('1', '6', 6.47)]}
BES = ('C403', 'C404', 'C405', 'C406', 'C407')
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
                st_ = 0.25 if max(l for _, _, l in NEAR[ref]) > 4 else 0.05
                xs = np.arange(UX - 9, UX + 9, st_); ys = np.arange(UY - 9, UY + 9, st_)
            else:
                xs = np.arange(18.0, 43.6, 0.5); ys = np.arange(4.6, 37.0, 0.5)
            for x in xs:
                for y in ys:
                    x = round(float(x), 3); y = round(float(y), 3)
                    if ref in NEAR and not near_ok(ref, k, x, y): continue
                    e = (gg['ext'][0] + x, gg['ext'][1] + y, gg['ext'][2] + x, gg['ext'][3] + y)
                    if mext.bad(e) > 0: continue
                    lb = (gg['lab'][0] + x, gg['lab'][1] + y, gg['lab'][2] + x, gg['lab'][3] + y)
                    if mlab.bad(lb) > 0: continue
                    z = (gg['zone'][0] + x, gg['zone'][1] + y, gg['zone'][2] + x, gg['zone'][3] + y)
                    if ls >= 10: z = (lb[0] - 0.06, lb[1] - 0.06, lb[2] + 0.06, lb[3] + 0.06)
                    if any(ov(e, f, 0.02) for f in fixed_ext) or any(ov(z, f, 0) for f in fixed_ext) or any(ov(lb, f, 0.5) for f in fixed_lab) or ov(e, U_zone, 0) or ov((lb[0] - 0.3, lb[1] - 0.3, lb[2] + 0.3, lb[3] + 0.3), U_ext, 0): continue
                    out.append((ref, k, ls, x, y, e, z, lb))
    return out
cf = R + 'power_cands_' + '_'.join(str(v) for v in (UX, UY, R401L, RP.ZONE, sys.argv[5:7], sys.argv[9:10])).replace(' ', '').replace("'", '').replace('[', '').replace(']', '') + '.pkl'
if os.path.exists(cf): C = pickle.load(open(cf, 'rb'))
else:
    C = {r: cand(r) for r in POW if r != 'U401'}; pickle.dump(C, open(cf, 'wb'))
print('domains', {r: len(v) for r, v in C.items()}, flush=True)
REST = sorted(C, key=lambda r: len(C[r]))
def OVv(A, b, g):
    return ((np.minimum(A[:, 2], b[2]) - np.maximum(A[:, 0], b[0]) + g) > 1e-6) & ((np.minimum(A[:, 3], b[3]) - np.maximum(A[:, 1], b[1]) + g) > 1e-6)
ARR = {r: (np.array([c[5] for c in v]), np.array([c[6] for c in v]), np.array([c[7] for c in v])) for r, v in C.items() if v}
def filt(r, idx, c):
    E, Z, L = ARR[r]
    bad = OVv(E[idx], c[5], 0.02) | OVv(Z[idx], np.array(c[5]), 0) | OVv(E[idx], np.array(c[6]), 0) | OVv(L[idx], np.array(c[7]), 0.5)
    return idx[~bad]
PASRE = RP.PAS
def orient(c): return RP.orient(P0[c[0]], c[1])
def lonely(chs):
    pas = [c for c in chs if PASRE.fullmatch(c[0])]; bad = 0
    for a in pas:
        o = orient(a); ok = False
        for b in pas:
            if b is a or orient(b) != o: continue
            if math.hypot(a[3] - b[3], a[4] - b[4]) <= 8 and ((o == 0 and abs(a[4] - b[4]) <= 0.05) or (o == 90 and abs(a[3] - b[3]) <= 0.05)): ok = True; break
        if not ok:
            for n, pp in pinU.items():
                if math.hypot(a[3] - pp[0], a[4] - pp[1]) <= 4 and ((o == 0 and abs(a[4] - pp[1]) <= 0.05) or (o == 90 and abs(a[3] - pp[0]) <= 0.05)): ok = True; break
        if not ok: bad += 1
    return bad
ORDER = ['C409', 'C402', 'C401', 'R405', 'C405', 'C406', 'R402', 'R404', 'C407', 'R401', 'R403', 'C403', 'C404', 'C408', 'R406', 'R407', 'BR401', 'TP401', 'TP402', 'TP403', 'TP404']
t0 = time.time(); best = [None, 99]; stat = {'deep': 0, 'empt': {}}; nodes = [0]; rnd = random.Random(int(sys.argv[8]) if len(sys.argv) > 8 else 1); BR = int(sys.argv[7]) if len(sys.argv) > 7 else 6
def dfs(idx, ch):
    nodes[0] += 1
    if time.time() - t0 > CAP or best[1] == 0: return
    if not idx:
        m = lonely(ch)
        if m < best[1]: best[0], best[1] = list(ch), m; print('sol lonely', m, 'nodes', nodes[0], flush=True)
        return
    r = [q for q in ORDER if q in idx][0]
    cs = idx[r]
    if len(ch) > stat['deep']: stat['deep'] = len(ch); print('depth', len(ch), r, len(cs), flush=True)
    pas = [c for c in ch if PASRE.fullmatch(c[0])]
    pool = [int(i) for i in (cs if len(cs) <= 250 else rnd.sample(list(cs), 250))]
    scored = []
    for i in pool:
        c = C[r][i]; tot = 0.0; ok = True
        for q in idx:
            if q == r: continue
            n = len(filt(q, idx[q], c))
            if n == 0: ok = False; stat['empt'][(r, q)] = stat['empt'].get((r, q), 0) + 1; break
            tot += math.log(n)
        if ok:
            o = orient(c)
            share = sum(1 for p in pas if orient(p) == o and ((o == 0 and abs(c[4] - p[4]) <= 0.05) or (o == 90 and abs(c[3] - p[3]) <= 0.05)))
            pin = any(((o == 0 and abs(c[4] - pp[1]) <= 0.05) or (o == 90 and abs(c[3] - pp[0]) <= 0.05)) and math.hypot(c[3] - pp[0], c[4] - pp[1]) <= 4 for pp in pinU.values()) if PASRE.fullmatch(r) else False
            scored.append((-tot - 3.0 * share - (3.0 if pin else 0.0) + rnd.random() * 0.5, i))
    for _, i in sorted(scored)[:BR]:
        c = C[r][i]; nidx = {q: filt(q, v, c) for q, v in idx.items() if q != r}
        dfs(nidx, ch + [c])
        if best[1] == 0 or time.time() - t0 > CAP: return
dfs({r: np.arange(len(C[r])) for r in REST}, [])
print('nodes', nodes[0], 'deepest', stat['deep'], 'empt', stat['empt'], 'best lonely', best[1], flush=True)
if best[0]:
    st = {c[0]: [c[3], c[4], ((round(P0[c[0]]['rot']) + 90 * c[1] + 180) % 360) - 180, c[2]] for c in best[0]}
    st['U401'] = [UX, UY, P0['U401']['rot'], 0]
    json.dump(dict(st=st), open(R + 'power_result_%s_%s_%s.json' % (UX, UY, sys.argv[8] if len(sys.argv) > 8 else 1), 'w')); print(st)
