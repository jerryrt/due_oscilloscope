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
        'TP402': (22.0, 25.5), 'TP403': (27.0, 25.5), 'TP404': (32.0, 25.5), 'TP401': (37.0, 25.5), 'TP405': (42.0, 25.5), 'R408': (23.0, 29.5), 'R410': (29.0, 29.5),  'C402': (36.9, 14.9), 'C403': (33.9, 17.9), 'C401': (29.5, 11.5), 'R302': (78.55, 9.25),  'R303': (82.0, 7.5), 'C301': (78.65, 7.5)}
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

obst[3] = (obst[3][0] - 0.35, obst[3][1] - 0.35, obst[3][2] + 0.35, obst[3][3] + 0.35)    # J603's label: 1.0 mm clear of every part body (spec lead)
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
LIM = {('C103', 'U101', '8'): 3.0, ('C302', 'U301', '8'): float(os.environ.get('LIM302', '3.0')), ('C303', 'U301', '4'): float(os.environ.get('LIM302', '3.0')), ('C502', 'U502', '8'): 3.0, ('C501', 'U501', '1'): 3.0}
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
for _a, _pa, _b, _pb, _d in json.loads(os.environ.get('EXTRACAPS', '[]')):
    CAPS.append((_a, padrel[_a][_pa][:2], _b, padrel[_b][_pb][:2], _d))
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

_lmf = os.environ.get('LABMODEFILE', 'whatif/_scratch/labmode.json')
LABMODE = json.load(open(_lmf)) if os.path.exists(_lmf) else {}
LPm.LABMODES.update(LABMODE)
def _setmode(p):
    m = LABMODE.get(p.ref, 'A')
    if m == 'A': return p
    cy = (p.ry0 + p.ry1) / 2
    p.ly0, p.ly1 = cy - 0.5, cy + 0.5
    if m == 'E': p.lx0 = p.rx1 + 0.2; p.lx1 = p.lx0 + p.w
    else: p.lx1 = p.rx0 - 0.2; p.lx0 = p.lx1 - p.w
    return p
parts = [_setmode(_P(r, rel[r], r not in ANCH, r in NOLAB)) for r in refs]
rect = {}
for i, p in enumerate(parts):
    if p.free:
        x, y = pos[p.ref]; bb = LPm._bb(p, x, y); best_ = None
        for q in fence[p.ref]:
            d = max(q[0]-bb[0], 0)+max(bb[2]-q[2], 0)+max(q[1]-bb[1], 0)+max(bb[3]-q[3], 0)
            if best_ is None or d < best_[0]: best_ = (d, q)
        rect[i] = best_[1]

import numpy as np, time, itertools, os
from pcbtools.labelplace import P, CC, LC, LL
GT = float(os.environ.get('GT', '0.2')); G = float(os.environ.get('GRID', '0.1')); TMAX = float(os.environ.get('TMAX', '7.5'))
AWGLOOSE = {'C302','C303','C304','C305','C306','R301','R304','R305','R306','R307','R308'}
CH1ALL = ['C101','C102','C103','C104','C105','R101','R102','R103','R104','R105','R106','R107','R108','R110','R111','R112','R113','D101','TP101']
def _near_set():
    k = 'U101'; px, py = pos[k]
    # U101 courtyard and label zone (label above its courtyard top), tie region of R107: U101's CH1_OUT pads 6 and 7
    from pcbtools.labelplace import _shapes
    P0 = P(k, rel[k], False, False); C0, L0 = _shapes(P0, px, py)
    zone = (min(C0[0], L0[0]) - 3.0, C0[1] - 3.0, max(C0[2], L0[2]) + 3.0, L0[3] + 3.0)
    out = []
    for r in CH1ALL:
        Pr = P(r, rel[r], True, False); Cr, Lr = _shapes(Pr, *pos[r])
        inzone = not (Cr[2] < zone[0] or Cr[0] > zone[2] or Cr[3] < zone[1] or Cr[1] > zone[3])
        pads6 = [(pos[k][0] + padrel[k][p][0], pos[k][1] + padrel[k][p][1]) for p in ('6', '7')]
        near_tie = min(((pos[r][0] - a) ** 2 + (pos[r][1] - b) ** 2) ** .5 for a, b in pads6) <= 6.0
        if inzone or near_tie or r == 'R107': out.append(r)
    return out
CSP = set(os.environ.get('CSPSET', '').split(',')) if os.environ.get('CSPSET') else set(_near_set())
print('CH1 FREE', sorted(CSP))
FENCE = tuple(float(v) for v in os.environ.get('FENCEBOX', '64.4,31.8,92.0,48.7').split(','))
pin6 = (pos['U301'][0] + padrel['U301']['6'][0], pos['U301'][1] + padrel['U301']['6'][1])
pin5 = (pos['U301'][0] + padrel['U301']['5'][0], pos['U301'][1] + padrel['U301']['5'][1])
j603_5 = (b.fp_x[b.ref_index('J603')] + padrel['J603']['5'][0], b.fp_y[b.ref_index('J603')] + padrel['J603']['5'][1])
print('pin6', pin6, 'pin5', pin5, 'J603.5', j603_5)
def rot_pad(px, py, d):
    if d == 90: return -py, px
    if d == 270: return py, -px
    if d == 180: return -px, -py
    return px, py
def setlabel(p, mode):
    if mode == 0: return p
    cy = (p.ry0 + p.ry1) / 2
    p.ly0, p.ly1 = cy - 0.5, cy + 0.5
    if mode == 1: p.lx0 = p.rx1 + 0.2; p.lx1 = p.lx0 + p.w
    else: p.lx1 = p.rx0 - 0.2; p.lx0 = p.lx1 - p.w
    return p
def variant(ref, d, mode):
    x0, y0, x1, y1 = rel[ref]
    if d in (90, 270): x0, y0, x1, y1 = y0, x0, y1, x1
    return setlabel(P(ref, (x0, y0, x1, y1), True, False), mode)
def padoff(ref, pin, d): return rot_pad(padrel[ref][pin][0], padrel[ref][pin][1], d)
def shp(p, x, y): return (x + p.rx0, y + p.ry0, x + p.rx1, y + p.ry1), (x + p.lx0, y + p.ly0, x + p.lx1, y + p.ly1)
def conf_np(Ca, La, Cb, Lb, tol=0.05):
    bad = np.zeros(np.broadcast(Ca[0], Cb[0]).shape, bool)
    for a, b_, m in ((Ca, Cb, CC), (La, Cb, LC), (Lb, Ca, LC), (La, Lb, LL)):
        px = np.minimum(a[2] + (m - tol) - b_[0], b_[2] + (m - tol) - a[0])
        py = np.minimum(a[3] + (m - tol) - b_[1], b_[3] + (m - tol) - a[1])
        bad |= (px > 0) & (py > 0)
    return bad
static = [(r, pos[r]) for r in refs if r not in CSP]
sp = {r: P(r, rel[r], r not in ANCH, r in NOLAB) for r, _ in static}
sp['U301'] = setlabel(sp['U301'], 1)
def single(ref, d, mode, xs, ys, keep=None):
    p = variant(ref, d, mode)
    X, Y = np.meshgrid(xs, ys); X = X.ravel(); Y = Y.ravel()
    C, L = shp(p, X, Y)
    ok = (C[0] >= FENCE[0] - 0.01) & (C[1] >= FENCE[1] - 0.01) & (C[2] <= FENCE[2] + 0.01) & (C[3] <= FENCE[3] + 0.01)
    ok &= (L[2] <= FENCE[2] + 0.01) & (L[3] <= FENCE[3] + 0.01) & (L[0] >= FENCE[0] - 0.01)
    for r_, (sx, sy) in static:
        if abs(sx - FENCE_CX) > 30 or abs(sy - FENCE_CY) > 30: continue
        Cs, Ls = shp(sp[r_], sx, sy)
        ok &= ~conf_np(C, L, Cs, Ls)
    for q in obst:
        if len(q) > 4 and ref in q[4]: continue
        for a in (C, L):
            px = np.minimum(a[2] + (LC - 0.05) - q[0], q[2] + (LC - 0.05) - a[0]); py = np.minimum(a[3] + (LC - 0.05) - q[1], q[3] + (LC - 0.05) - a[1])
            ok &= ~((px > 0) & (py > 0))
    return p, X[ok], Y[ok]
def rng(c, h, g): return np.arange(c - h, c + h + 1e-9, g)


def reads_a(L, C, kind):
    """widened rule 3b (see check3b.py)"""
    if kind == 'above':
        return (np.abs((L[0] + L[2]) / 2 - (C[0] + C[2]) / 2) <= 0.3) & (L[1] - C[3] >= -1e-6) & (L[1] - C[3] <= 0.6 + 1e-6)
    yov = (L[1] < C[3] - 1e-6) & (L[3] > C[1] + 1e-6)
    if kind == 'east':
        return yov & (L[0] - C[2] >= -1e-6) & (L[0] - C[2] <= 0.6 + 1e-6)
    return yov & (C[0] - L[2] >= -1e-6) & (C[0] - L[2] <= 0.6 + 1e-6)
KINDS = ('above', 'east', 'west')
RULE3B = not os.environ.get('NO3B')
for _r in CSP: LPm.LABMODES.pop(_r, None)
BESIDE_STATIC = {r: m for r, m in LABMODE.items() if m in ('E', 'W') and r not in CSP}
FENCE_CX = (FENCE[0] + FENCE[2]) / 2; FENCE_CY = (FENCE[1] + FENCE[3]) / 2
G = float(os.environ.get('GRID', '0.2')); BF = set(os.environ.get('BF', '').split(','))
u = {p: (pos['U401'][0] + padrel['U401'][p][0], pos['U401'][1] + padrel['U401'][p][1]) for p in padrel['U401'] if p in '123456789' or p in ('10', '11', '12')}
# (ref, own pad, U401 pin, limit)
TIES = {}
u_all = {(ic, p): (pos[ic][0] + padrel[ic][p][0], pos[ic][1] + padrel[ic][p][1]) for ic in ('U101', 'U301', 'U401', 'U501', 'U502') for p in padrel[ic]}
def _pin_of_off(ref, off):
    for pn, (px, py, nn) in padrel[ref].items():
        if abs(px - off[0]) < 1e-6 and abs(py - off[1]) < 1e-6: return pn
for _r in CSP:
    TIES[_r] = []
    for (q, qoff, ic, icoff, D) in CAPS:
        if q == _r: TIES[_r].append((_pin_of_off(q, qoff), ic, _pin_of_off(ic, icoff), D))
    print('TIES', _r, TIES[_r])

FREED = []
BESIDEOK = set(v for v in os.environ.get('BESIDEOK', '').split(',') if v)
BF = BESIDEOK
BESIDEONLY = set(v for v in os.environ.get('BESIDEONLY', '').split(',') if v)
ROTS = {r: (0, 90, 180, 270) for r in CSP}
cands = {}
for ref in sorted(CSP):
    rows = []
    _modes = ((1, 2) if ref in BESIDEONLY else (0,)) if BESIDEONLY else ((0, 1, 2) if ref in BF else (0,))
    for d, mode in itertools.product((0, 90, 180, 270), _modes):
        if os.environ.get('PIN') and ref in FREED and d != 0: continue
        if os.environ.get('PIN') and ref in FREED:
            p, X, Y = single(ref, d, mode, np.array([pos[ref][0]]), np.array([pos[ref][1]]))
        else:
            _w = float(os.environ.get('UNTIEDW', '0')) if not TIES.get(ref) else 0
            if _w:
                _wc = tuple(float(v) for v in os.environ['WINC'].split(',')) if os.environ.get('WINC') else pos[ref]
                p, X, Y = single(ref, d, mode, np.arange(max(FENCE[0], _wc[0] - _w), min(FENCE[2], _wc[0] + _w) + 1e-9, G), np.arange(max(FENCE[1], _wc[1] - _w), min(FENCE[3], _wc[1] + _w) + 1e-9, G))
            elif TIES.get(ref) and os.environ.get('GTIED') and min(t[3] for t in TIES[ref]) <= float(os.environ.get('TIGHT', '4.5')):
                _g = float(os.environ['GTIED'])
                x0_ = max(FENCE[0], max(u_all[(ic_, pin)][0] - lim - 2.5 for pad, ic_, pin, lim in TIES[ref])); x1_ = min(FENCE[2], min(u_all[(ic_, pin)][0] + lim + 2.5 for pad, ic_, pin, lim in TIES[ref]))
                y0_ = max(FENCE[1], max(u_all[(ic_, pin)][1] - lim - 2.5 for pad, ic_, pin, lim in TIES[ref])); y1_ = min(FENCE[3], min(u_all[(ic_, pin)][1] + lim + 2.5 for pad, ic_, pin, lim in TIES[ref]))
                p, X, Y = single(ref, d, mode, np.arange(x0_, x1_ + 1e-9, _g), np.arange(y0_, y1_ + 1e-9, _g))
            else:
                p, X, Y = single(ref, d, mode, np.arange(FENCE[0], FENCE[2], G), np.arange(FENCE[1], FENCE[3], G))
        ok = np.ones(len(X), bool)
        for pad, ic_, pin, lim in TIES[ref]:
            ox, oy = padoff(ref, pad, d)
            ok &= np.hypot(X + ox - u_all[(ic_, pin)][0], Y + oy - u_all[(ic_, pin)][1]) <= lim + 1e-9
        if ref == 'R107': print('R107 d', d, 'after tie+statics+fence+obst:', int(ok.sum()), '(before span, 3b)')
        for mem_, wx_, wy_ in SPANS:
            ours = [m for m in mem_ if m[0] == ref]
            if not ours or any(m[0] in CSP and m[0] != ref for m in mem_): continue
            oth = [(pos[m[0]][0] + m[1][0], pos[m[0]][1] + m[1][1]) for m in mem_ if m[0] != ref]
            px_, py_ = rot_pad(ours[0][1][0], ours[0][1][1], d)
            xs_ = np.array([o[0] for o in oth]); ys_ = np.array([o[1] for o in oth])
            ok &= (np.maximum(xs_.max(), X + px_) - np.minimum(xs_.min(), X + px_) <= wx_ + 1e-6) & (np.maximum(ys_.max(), Y + py_) - np.minimum(ys_.min(), Y + py_) <= wy_ + 1e-6)
        if ref == 'R107': print('R107 d', d, 'after span:', int(ok.sum()))
        if RULE3B and len(X):
            pv = variant(ref, d, mode); C_, L_ = shp(pv, X, Y)
            for r_, (sx, sy) in static:
                if sp[r_].w == 0 or abs(sx - 31) > 25 or abs(sy - 19) > 22: continue
                Cs, Ls = shp(sp[r_], sx, sy)
                bad3 = np.zeros(len(X), bool)
                if mode != 0:
                    for k in KINDS: bad3 |= reads_a(Ls, C_, k)
                    bad3 |= reads_a(L_, Cs, 'above')
                if r_ == 'U101' or r_ in BESIDE_STATIC:
                    bad3 |= reads_a(Ls, C_, 'above')
                if r_ in BESIDE_STATIC:
                    for k in KINDS: bad3 |= reads_a(L_, Cs, k)
                ok &= ~bad3
        for x, y in zip(X[ok], Y[ok]): rows.append((d, mode, x, y))
    cands[ref] = np.array(rows) if rows else np.zeros((0, 4))
    if ref == 'C405': print('CTRL C405 at (28.6..28.8,10.6) west label present:', int(((np.abs(cands[ref][:,2]-28.7)<0.11)&(np.abs(cands[ref][:,3]-10.6)<0.11)&(cands[ref][:,1]==2)).sum()) if len(cands[ref]) else 0)
    print('CSP', ref, len(rows))
names = sorted(CSP, key=lambda r: len(cands[r]))
def shapes(ref):
    rows = cands[ref]; C = np.zeros((4, len(rows))); L = np.zeros((4, len(rows)))
    for d, md in itertools.product((0, 90, 180, 270), (0, 1, 2)):
        m = (rows[:, 0] == d) & (rows[:, 1] == md)
        if m.any():
            c, l = shp(variant(ref, d, md), rows[m, 2], rows[m, 3]); C[:, m] = np.array(c); L[:, m] = np.array(l)
    return C, L
SH = {r: shapes(r) for r in names}
def compat(a, b):
    Ca, La = SH[a]; Cb, Lb = SH[b]
    A = lambda arr: [c[:, None] for c in arr]; B = lambda arr: [c[None, :] for c in arr]
    ok_ = ~conf_np(A(Ca), A(La), B(Cb), B(Lb))
    if RULE3B:
        bA = (cands[a][:, 1] != 0)[:, None]; bB = (cands[b][:, 1] != 0)[None, :]
        for k in KINDS:
            ok_ &= ~(bA & reads_a(B(Lb), A(Ca), k))
            ok_ &= ~(bB & reads_a(A(La), B(Cb), k))
        ok_ &= ~(bA & reads_a(A(La), B(Cb), 'above'))
        ok_ &= ~(bB & reads_a(B(Lb), A(Ca), 'above'))
    return ok_
CM = {}
for i, a in enumerate(names):
    for b in names[i + 1:]:
        CM[(a, b)] = compat(a, b)
        CM[(b, a)] = CM[(a, b)].T
print('PAIRS (compatible candidate pairs):')
for i, a in enumerate(names):
    print('PAIR', a, {b: int(CM[(a, b)].sum()) for b in names if b != a})


from pcbtools.boards import v1 as _C
HIZL = {n: (8.0 if n.endswith('_N') else 10.0) for n in _C.HIZ}
from pcbtools import boardio as _bio
_NETS = _bio.read_board('kicad/afe-proto.kicad_pcb').nets
HNET = {}   # net -> [(ref, pin)]
for _r, _pads in padrel.items():
    for _pin, (_px, _py, _nn) in _pads.items():
        _nm = _NETS[_nn]
        if _nm in HIZL: HNET.setdefault(_nm, []).append((_r, _pin))
print('HIZ nets', {k: [f"{a}.{c}" for a, c in v] for k, v in HNET.items() if any(a in CSP for a, c in v)})
def hpwl_ok(assign):
    for nm, mem in HNET.items():
        pts = []; free_in = False
        for (r_, pin_) in mem:
            if r_ in CSP:
                if r_ not in assign: continue
                row = cands[r_][assign[r_]]
                ox, oy = padoff(r_, pin_, int(row[0])); pts.append((row[2] + ox, row[3] + oy)); free_in = True
            else:
                pts.append((pos[r_][0] + padrel[r_][pin_][0], pos[r_][1] + padrel[r_][pin_][1]))
        if free_in and len(pts) > 1:
            xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
            if (max(xs) - min(xs)) + (max(ys) - min(ys)) > HIZL[nm] + 1e-9: return False
    return True
import time as _t
ISB = {r: (cands[r][:, 1] != 0) for r in names}
T0 = _t.time(); DEADLINE = float(os.environ.get('DEADLINE', '2700'))
class Out(Exception): pass
def run_k(K):
    sol = []; count = [0]
    def dfs(assign, masks, nb):
        if _t.time() - T0 > DEADLINE: raise Out()
        if len(assign) == len(names):
            sol.append(dict(assign)); return len(sol) >= 3
        rest = [r for r in names if r not in assign]
        if nb >= K:
            masks = {q: masks[q] & ~ISB[q] for q in rest}
        r = min(rest, key=lambda q: masks[q].sum())
        idx = np.nonzero(masks[r])[0]
        count[0] += 1
        for i in idx:
            m2 = {q: masks[q] & CM[(r, q)][i] for q in rest if q != r}
            if any(not v.any() for v in m2.values()): continue
            assign[r] = i
            if not hpwl_ok(assign):
                del assign[r]; continue
            if dfs(assign, m2, nb + int(ISB[r][i])): return True
            del assign[r]
        return False
    masks = {r: np.ones(len(cands[r]), bool) for r in names}
    dfs({}, masks, 0)
    return sol, count[0]
try:
    for K in range(int(os.environ.get('KMIN', '0')), int(os.environ.get('KMAX', '4')) + 1):
        sol, nodes = run_k(K)
        print('BESIDE_BUDGET', K, 'SOLUTIONS', len(sol), 'nodes', nodes, 'elapsed', round(_t.time() - T0), flush=True)
        for s_ in sol:
            print('SOL', {r: [float(v) for v in cands[r][i][[0, 1, 2, 3]]] for r, i in s_.items()})
        if sol: break
except Out:
    print('OVER BUDGET after', round(_t.time() - T0), 's at K', K)
