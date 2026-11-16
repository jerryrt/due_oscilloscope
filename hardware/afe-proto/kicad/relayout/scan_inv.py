import re, sys, json
import numpy as np
from pcbtools import boardio, labelplace as LP, silkread
from pcbtools.boards import v1 as C
b = boardio.read_board('kicad/afe-proto.kicad_pcb')
FENCE = {
 '1': [(64.4, 31.8, 92.0, 48.7)],
 '2': [(70.4, 21.6, 92.0, 31.6)],
 '3': [(70.4, 4.6, 92.0, 21.2)],
 '4': [(17.5, 4.6, 43.6, 33.0)],
 '5': [(45.0, 4.6, 64.2, 40.0)],
}
WALL = [(64.4, 13.0, 70.2, 30.8)]
R412 = [(38.6, 34.5, 45.0, 47.5)]
WALLREFS = {'R309', 'R310', 'R515', 'R516'}
WALLFREE = {'TP101'}
LADDER = {'R503', 'R504', 'R505', 'R506', 'R507', 'R508'}
HAND = {'R508': (52.07, 6.5), 'R506': (57.15, 6.5), 'R504': (62.23, 6.5), 'R507': (54.61, 9.35), 'R505': (59.69, 9.35),
        'R503': (63.05, 10.15), 'J501': (56.54, 14.9), 'C502': (58.6, 26.4), 'D501': (62.4, 28.45), 'R509': (51.0, 38.4),
        'R405': (36.4, 11.2), 'C408': (40.2, 11.4), 'C407': (40.2, 16.25), 'R407': (42.2, 21.1), 'R401': (29.4, 17.3), 'R409': (29.6, 21.1), 'R406': (37.8, 21.1), 'R403': (32.4, 8.3), 'R404': (36.9, 7.55), 
        'TP402': (22.0, 25.5), 'TP403': (27.0, 25.5), 'TP404': (32.0, 25.5), 'TP401': (37.0, 25.5), 'TP405': (42.0, 25.5), 'R408': (23.0, 29.5), 'R410': (29.0, 29.5),  'C402': (36.9, 14.9), 'C403': (33.9, 17.9), 'C401': (29.5, 11.5)}
ANCH = set(C.ANCHORS) | {'R411', 'U101', 'U301', 'U401', 'C402'} | set(HAND)
LOCKX = WALLREFS | {'R110', 'J501'}
NOLAB = ['J601','J602','J603','J604','J605','J606','J607','J101','J201','J301']
refs, rel, target, fence = [], {}, {}, {}
big = [(-1e3, -1e3, 1e3, 1e3)]
for k, r in enumerate(b.fp_ref):
    if np.isnan(b.fp_cx0[k]) or int(b.fp_side[k]) != 0: continue
    refs.append(r)
    ox, oy = float(b.fp_x[k]), float(b.fp_y[k])
    rel[r] = (float(b.fp_cx0[k]) - ox, float(b.fp_cy0[k]) - oy, float(b.fp_cx1[k]) - ox, float(b.fp_cy1[k]) - oy)
    x, y = ox, oy
    m = re.fullmatch(r'[A-Z]+(\d)\d\d', r)
    d = m.group(1) if m else '6'
    if r in ANCH or d == '6':
        fence[r] = big
    elif r == 'J501': fence[r] = FENCE['5']
    elif r in WALLREFS or r in WALLFREE: fence[r] = [(62.2, 12.0, 71.0, 31.4)]
    elif r == 'R110': fence[r] = [(62.2, 32.0, 69.4, 48.7)]
    elif r in ('R412', 'R413'): fence[r] = R412; y = 40.0
    else:
        fence[r] = FENCE[d]
        if d == '4': y = 4.6 + (y - 4.6) * 1.55
    target[r] = HAND.get(r, (x, y))
ANCH |= {r for r in refs if re.fullmatch(r'[A-Z]+6\d\d', r)}
# obstacles: headers' end labels, the identity strip
obst = [(17.5, 34.0, 38.5, 47.0)]
for r in ('J601','J602','J603','J604','J605','J606','J607'):
    k = b.ref_index(r); c = (b.fp_cx0[k], b.fp_cy0[k], b.fp_cx1[k], b.fp_cy1[k]); w = len(r) * 0.9
    cxm = (c[0] + c[2]) / 2
    if (c[2]-c[0]) > (c[3]-c[1]):
        if (c[1] + c[3]) / 2 < 26.67: obst.append((cxm - w / 2, c[3] + 0.2, cxm + w / 2, c[3] + 1.2))      # lower half: above, on the inboard side
        else: obst.append((cxm - w / 2, c[1] - 1.2, cxm + w / 2, c[1] - 0.2))                              # upper half: below
    else: obst.append((cxm - w / 2, c[3] + 0.2, cxm + w / 2, c[3] + 1.2))

BRIDGES_ = frozenset({'R309','R310','R515','R516','R110','D101','D201','R107','R207','TP101','TP201'})
obst.append((65.7, 4.4, 66.4, 40.0, BRIDGES_))      # the A1 and A0 lines run up the wall: only the parts on them may stand in their columns
obst.append((68.2, 4.4, 68.9, 40.0, BRIDGES_))

# ---- hard constraints from the landed board (LR-4/LR-5/LR-12): critical parts keep their distance to the pin they serve; A0/A1 get no longer
padrel = {}
padpos = {}
for j in range(len(b.p_fp)):
    r = b.fp_ref[int(b.p_fp[j])]
    k = int(b.p_fp[j])
    padrel.setdefault(r, {})[b.p_pin[j]] = (float(b.p_x[j] - b.fp_x[k]), float(b.p_y[j] - b.fp_y[k]), int(b.p_net[j]))
def pr(ref, pin): return padrel[ref][pin][:2]
def landed(ra, pa, rb, pb):
    xa = b.fp_x[b.ref_index(ra)] + PADREL0[ra][pa][:2][0]; ya = b.fp_y[b.ref_index(ra)] + PADREL0[ra][pa][:2][1]
    xb = b.fp_x[b.ref_index(rb)] + PADREL0[rb][pb][:2][0]; yb = b.fp_y[b.ref_index(rb)] + PADREL0[rb][pb][:2][1]
    return float(((xa - xb) ** 2 + (ya - yb) ** 2) ** .5)
import os as _o2
SLK = {kv.split(':')[0]: float(kv.split(':')[1]) for kv in _o2.environ.get('SLACKMAP', '').split(',') if kv}
SLK_DEFAULT = float(_o2.environ.get('SLACKD', '1000'))
import copy, os
PADREL0 = copy.deepcopy(padrel)
ROTOV = json.load(open('whatif/_scratch/rotov.json')) if os.path.exists('whatif/_scratch/rotov.json') else {}
ROT0 = json.load(open('whatif/_scratch/rot.json'))
for r_, new_ in ROTOV.items():
    d_ = (new_ - ROT0[r_]) % 360
    if d_ in (90, 270):
        x0_, y0_, x1_, y1_ = rel[r_]
        rel[r_] = (y0_, x0_, y1_, x1_)
    for pin_, (px_, py_, n_) in list(padrel[r_].items()):
        if d_ == 90: padrel[r_][pin_] = (-py_, px_, n_)
        elif d_ == 270: padrel[r_][pin_] = (py_, -px_, n_)
        elif d_ == 180: padrel[r_][pin_] = (-px_, -py_, n_)
CAPS = []
CRIT = set()
SKIPN = {'', '/GND'}
for ic in ('U101', 'U301', 'U401', 'U501', 'U502'):
    for pin, (dx, dy, net) in padrel[ic].items():
        if b.nets[net] in SKIPN: continue
        for q, pads in padrel.items():
            if q == ic or q[0] not in 'RCD' or q in ANCH and q not in HAND: continue
            for qpin, (qx, qy, qnet) in pads.items():
                if qnet == net:
                    d = landed(q, qpin, ic, pin)
                    if d <= 8.0:
                        CRIT.add(q)
                        CAPS.append((q, (qx, qy), ic, (dx, dy), round(d + SLK.get(q, SLK_DEFAULT), 3)))
LIM = {('C103', 'U101', '8'): 3.0, ('C302', 'U301', '8'): 3.0, ('C303', 'U301', '4'): 3.0, ('C502', 'U502', '8'): 3.0, ('C501', 'U501', '1'): 3.0}
dec = {}
for (cap, ic, pin), L in LIM.items():
    net = padrel[ic][pin][2]
    for qpin, (qx, qy, qnet) in padrel[cap].items():
        if qnet == net:
            d = L - 0.05
            CAPS = [c for c in CAPS if not (c[0] == cap and c[2] == ic and c[1] == (qx, qy))]
            CAPS.append((cap, (qx, qy), ic, pr(ic, pin), round(d, 3)))
for riso, outpin in (('R107', None), ('R207', None)):
    pass
for ch in C.CHANNELS:
    rr = ch['riso']; ic, pin = ch['out_pin']
    d = 4.8
    CAPS.append((rr, pr(rr, '1'), ic, pr(ic, pin), round(d, 3)))
# POWER relaxations (spec lead): FB-divider ties, absolute caps for the VIN decoupling caps, pads exempt from the tie
ABSM = {}
for kv in os.environ.get('ABSMAP', '').split(','):
    if kv:
        a_, d_ = kv.split(':'); ABSM[tuple(a_.split('@'))] = float(d_)
IGN = {tuple(kv.split('@')) for kv in os.environ.get('IGNORE', '').split(',') if kv}
def _pin_of(ic, off):
    for pin_, (px_, py_, n_) in padrel[ic].items():
        if abs(px_ - off[0]) < 1e-6 and abs(py_ - off[1]) < 1e-6: return pin_
newcaps = []
for c in CAPS:
    q, qoff, ic, icoff, D = c
    qpin = None
    for pin_, (px_, py_, n_) in padrel[q].items():
        if abs(px_ - qoff[0]) < 1e-6 and abs(py_ - qoff[1]) < 1e-6: qpin = pin_
    if (q, qpin) in IGN: continue
    absrefs = {k[0] for k in ABSM}
    if ic == 'U401' and q in absrefs:
        pin = _pin_of(ic, icoff)
        if (q, pin) in ABSM:
            c = (q, qoff, ic, icoff, ABSM[(q, pin)])
        else:
            continue
    newcaps.append(c)
CAPS = newcaps
SPANS = []
for nm in ('/A0', '/A1', '/AWG_INV'):
    nid = b.nets.index(nm)
    mem, xs, ys = [], [], []
    for r, pads in padrel.items():
        for pin, (px, py, n_) in pads.items():
            if n_ == nid and not np.isnan(b.fp_x[b.ref_index(r)]):
                k = b.ref_index(r)
                mem.append((r, (px, py))); xs.append(b.fp_x[k] + px); ys.append(b.fp_y[k] + py)
    SPANS.append((mem, round(max(xs) - min(xs) + (0.4 if nm == '/AWG_INV' else 0), 3), round(max(ys) - min(ys) + (0.4 if nm == '/AWG_INV' else 0), 3)))
# the reference to the ladder and the ADS: U501's VREF pad to R508 and U502.4

import os as _os
SC = float(_os.environ.get('CAPSCALE', '1.0'))
if SC != 1.0:
    keep = {(c, i) for (c, i, p_), L in LIM.items()}
    CAPS = [(a_, pa_, b_, pb_, (D if (a_, b_) in keep else round(D * SC, 3))) for (a_, pa_, b_, pb_, D) in CAPS]
    SPANS = [(m, round(wx * SC, 3), round(wy * SC, 3)) for m, wx, wy in SPANS]
XMIN = {}
print('critical', len(CRIT), sorted(CRIT)[:60])
print('caps', len(CAPS), 'spans', [(len(m), wx, wy) for m, wx, wy in SPANS])

import os
from pcbtools import labelplace as LPm
J = json.load(open('whatif/_scratch/relay_pos.json'))
pos = {r: tuple(J[r]) for r in refs}
ov = json.load(open('whatif/_scratch/override.json')) if os.path.exists('whatif/_scratch/override.json') else {}
for r, v in ov.items(): pos[r] = tuple(v)
for r_, v_ in HAND.items(): pos[r_] = v_
pos['R411'] = (48.275, 3.1)
from pcbtools.labelplace import P as _P
parts = [_P(r, rel[r], r not in ANCH, r in NOLAB) for r in refs]
rect = {}
for i, p in enumerate(parts):
    if p.free:
        x, y = pos[p.ref]; bb = LPm._bb(p, x, y); best_ = None
        for q in fence[p.ref]:
            d = max(q[0]-bb[0], 0)+max(bb[2]-q[2], 0)+max(q[1]-bb[1], 0)+max(bb[3]-q[3], 0)
            if best_ is None or d < best_[0]: best_ = (d, q)
        rect[i] = best_[1]

# ---- exhaustive placement of R302, R303, C301 around U301.6, labels above, to minimise the /AWG_INV pad tree
import numpy as np, time, itertools
G = float(os.environ.get('GRID', '0.3')); RMAX = float(os.environ.get('RMAX', '6.0'))
from pcbtools.labelplace import P, CC, LC, LL
TRIO = {'R302': '1', 'R303': '2', 'C301': '2'}
AWGLOOSE = {'C302','C303','C304','C305','C306','R301','R304','R305','R306','R307','R308'}
FENCE = (70.4, 4.6, 92.0, 21.2)
pin6 = (pos['U301'][0] + padrel['U301']['6'][0], pos['U301'][1] + padrel['U301']['6'][1])
print('pin6', pin6)
BF = set(os.environ.get('BESIDEFOR', 'R302,R303,C301' if os.environ.get('BESIDE') else '').split(','))
def MODES_OF(ref): return (0, 1, 2) if ref in BF else (0,)
MODES = (0, 1, 2)
WIN = {kv.split(':')[0]: tuple(float(v) for v in kv.split(':')[1].split(',')) for kv in os.environ.get('WIN', '').split(';') if kv}
WH = float(os.environ.get('WH', '0.4'))
def setlabel(p, mode):
    if mode == 0: return p
    cy = (p.ry0 + p.ry1) / 2
    p.ly0, p.ly1 = cy - 0.5, cy + 0.5
    if mode == 1: p.lx0 = p.rx1 + 0.2; p.lx1 = p.lx0 + p.w
    else: p.lx1 = p.rx0 - 0.2; p.lx0 = p.lx1 - p.w
    return p
def variant(ref, d, mode=0):
    x0, y0, x1, y1 = rel[ref]
    if d in (90, 270): x0, y0, x1, y1 = y0, x0, y1, x1
    px, py, _ = padrel[ref][TRIO[ref]]
    if d == 90: px, py = -py, px
    elif d == 270: px, py = py, -px
    elif d == 180: px, py = -px, -py
    return setlabel(P(ref, (x0, y0, x1, y1), True, False), mode), (px, py)
def shp(p, x, y):
    C = (x + p.rx0, y + p.ry0, x + p.rx1, y + p.ry1); L = (x + p.lx0, y + p.ly0, x + p.lx1, y + p.ly1)
    return C, L
def conf_np(Ca, La, Cb, Lb, tol=0.05):
    bad = np.zeros(np.broadcast(Ca[0], Cb[0]).shape, bool)
    for a, b, m in ((Ca, Cb, CC), (La, Cb, LC), (Lb, Ca, LC), (La, Lb, LL)):
        px = np.minimum(a[2] + (m - tol) - b[0], b[2] + (m - tol) - a[0])
        py = np.minimum(a[3] + (m - tol) - b[1], b[3] + (m - tol) - a[1])
        bad |= (px > 0) & (py > 0)
    return bad
static = [(r, pos[r]) for r in refs if r not in TRIO and r not in AWGLOOSE]
sp = {r: P(r, rel[r], r not in ANCH, r in NOLAB) for r, _ in static}
if os.environ.get('EAST'): sp['U301'] = setlabel(sp['U301'], 1)
cands = {}
for ref in TRIO:
    out = []
    for d, mode in itertools.product((0, 90, 180, 270), MODES_OF(ref)):
        p, (ox, oy) = variant(ref, d, mode)
        xs = np.arange(FENCE[0], FENCE[2] + 1e-9, G); ys = np.arange(FENCE[1], FENCE[3] + 1e-9, G)
        if ref in WIN:
            xs = np.arange(WIN[ref][0] - WH, WIN[ref][0] + WH + 1e-9, G); ys = np.arange(WIN[ref][1] - WH, WIN[ref][1] + WH + 1e-9, G)
        X, Y = np.meshgrid(xs, ys); X = X.ravel(); Y = Y.ravel()
        m = (np.abs(X + ox - pin6[0]) + np.abs(Y + oy - pin6[1])) <= RMAX
        X, Y = X[m], Y[m]
        C, L = shp(p, X, Y)
        ok = (C[0] >= FENCE[0] - 0.01) & (C[1] >= FENCE[1] - 0.01) & (C[2] <= FENCE[2] + 0.01) & (C[3] <= FENCE[3] + 0.01)
        ok &= (L[0] >= INT[0] - 0.01) if False else True
        ok &= (L[2] <= FENCE[2] + 0.01) & (L[3] <= FENCE[3] + 0.01) & (L[0] >= FENCE[0] - 0.01)
        for r_, (sx, sy) in static:
            if abs(sx - pin6[0]) > 14 or abs(sy - pin6[1]) > 14: continue
            Cs, Ls = shp(sp[r_], sx, sy)
            ok &= ~conf_np(C, L, Cs, Ls)
        for q in obst:
            if len(q) > 4 and ref in q[4]: continue
            for a in (C, L):
                px = np.minimum(a[2] + (LC - 0.05) - q[0], q[2] + (LC - 0.05) - a[0]); py = np.minimum(a[3] + (LC - 0.05) - q[1], q[3] + (LC - 0.05) - a[1])
                ok &= ~((px > 0) & (py > 0))
        X, Y = X[ok], Y[ok]
        for i in range(len(X)):
            out.append((d, X[i], Y[i], X[i] + ox, Y[i] + oy, mode))
    arr = np.array(out) if out else np.zeros((0, 6))
    cands[ref] = arr
    print(ref, 'feasible single placements', len(arr), 'by mode', {md: int((arr[:, 5] == md).sum()) for md in MODES})
vp = {(ref, d, m): variant(ref, d, m)[0] for ref in TRIO for d in (0, 90, 180, 270) for m in MODES}
def shp_arr(ref, arr):
    outC, outL = [], []
    for d in (0, 90, 180, 270):
        pass
    C = np.zeros((4, len(arr))); L = np.zeros((4, len(arr)))
    for d, md in itertools.product((0, 90, 180, 270), MODES):
        m = (arr[:, 0] == d) & (arr[:, 5] == md)
        if m.any():
            c, l = shp(vp[(ref, d, md)], arr[m, 1], arr[m, 2])
            C[:, m] = np.array(c); L[:, m] = np.array(l)
    return C, L
S = {r: shp_arr(r, cands[r]) for r in TRIO}
def pairok(r1, r2):
    C1, L1 = S[r1]; C2, L2 = S[r2]
    return ~conf_np([c[:, None] for c in C1], [l[:, None] for l in L1], [c[None, :] for c in C2], [l[None, :] for l in L2])
t0 = time.time()
OK = {('R302', 'R303'): pairok('R302', 'R303'), ('R302', 'C301'): pairok('R302', 'C301'), ('R303', 'C301'): pairok('R303', 'C301')}
print('pair matrices', time.time() - t0)
pa = {r: cands[r][:, 3:5] for r in TRIO}
def man(a, b): return np.abs(a[..., 0] - b[..., 0]) + np.abs(a[..., 1] - b[..., 1])
def euc(a, b): return np.hypot(a[..., 0] - b[..., 0], a[..., 1] - b[..., 1])
metric = man if os.environ.get('METRIC', 'man') == 'man' else euc
dp = {r: metric(pa[r], np.array(pin6)) for r in TRIO}
best = (1e9, None); found = []
na = len(cands['R302'])
for i in range(na):
    mb = OK[('R302', 'R303')][i]; mc = OK[('R302', 'C301')][i]
    bi = np.nonzero(mb)[0]; ci = np.nonzero(mc)[0]
    if len(bi) == 0 or len(ci) == 0: continue
    ok2 = OK[('R303', 'C301')][np.ix_(bi, ci)]
    pA = pa['R302'][i]
    dab = metric(pA, pa['R303'][bi])[:, None]; dac = metric(pA, pa['C301'][ci])[None, :]
    dbc = metric(pa['R303'][bi][:, None, :], pa['C301'][ci][None, :, :])
    dpa = dp['R302'][i]; dpb = dp['R303'][bi][:, None]; dpc = dp['C301'][ci][None, :]
    # the 16 spanning trees of K4 on {p,a,b,c}
    E = {'pa': dpa + 0 * dab, 'pb': dpb + 0 * dbc, 'pc': dpc + 0 * dbc, 'ab': dab + 0 * dbc, 'ac': dac + 0 * dbc, 'bc': dbc}
    names = list(E)
    tot = None
    for tr in itertools.combinations(names, 3):
        vs = {'p', 'a', 'b', 'c'}
        # a tree iff connected: use union-find on 4 nodes
        par = {v: v for v in vs}
        def f(v):
            while par[v] != v: v = par[v]
            return v
        okt = True
        for e in tr:
            u, w = f(e[0]), f(e[1])
            if u == w: okt = False; break
            par[u] = w
        if not okt: continue
        s = E[tr[0]] + E[tr[1]] + E[tr[2]]
        tot = s if tot is None else np.minimum(tot, s)
    tot = np.where(ok2, tot, 1e9)
    k = np.unravel_index(np.argmin(tot), tot.shape)
    v = tot[k]
    if v < best[0] + 0.5:
        found.append((float(v), i, int(bi[k[0]]), int(ci[k[1]])))
    if v < best[0]: best = (float(v), (i, int(bi[k[0]]), int(ci[k[1]])))
found.sort()
print('metric', os.environ.get('METRIC', 'man'), 'grid', G, 'best tree', round(best[0], 3), 'time', round(time.time() - t0))
for v, i, j, k in found[:8]:
    print(round(v, 3), 'R302', cands['R302'][i][[0,1,2,5]].round(2).tolist(), 'R303', cands['R303'][j][[0,1,2,5]].round(2).tolist(), 'C301', cands['C301'][k][[0,1,2,5]].round(2).tolist())
