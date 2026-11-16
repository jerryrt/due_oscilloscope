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


def c3b(Ca, La, ba, Cb, Lb, bb):
    bad = np.zeros(np.broadcast(Ca[0], Cb[0]).shape, bool)
    for k in KINDS:
        bad |= ba & reads_a(Lb, Ca, k)
        bad |= bb & reads_a(La, Cb, k)
    bad |= ba & reads_a(La, Cb, 'above')
    bad |= bb & reads_a(Lb, Ca, 'above')
    return bad
import itertools
CH = os.environ.get('CHAN', '1')
if CH == '1':
    LEFT = ['C102', 'R104', 'C101']; RIGHT = ['R106', 'R103', 'R105']; NET = '/CH1_N'; WIN = (66.0, 36.0, 91.0, 47.5)
else:
    LEFT = ['C202', 'R204', 'C201']; RIGHT = ['R206', 'R203', 'R205']; NET = '/CH2_N'; WIN = (66.0, 21.5, 91.0, 31.5)
PITCH_X, PITCH_Y = 3.3, 1.8
def npin(ref):
    for r_, p_ in HNET[NET]:
        if r_ == ref: return p_
def rot_for(ref, want_sign):
    pn = npin(ref)
    for d in (0, 180):
        ox, oy = padoff(ref, pn, d)
        if (ox > 0) == (want_sign > 0): return d
results = []
for flip, swap in itertools.product((False, True), (False, True)):
    L, R_ = (RIGHT, LEFT) if swap else (LEFT, RIGHT)
    if flip: L, R_ = L[::-1], R_[::-1]
    spec = []   # (ref, dx, dy, d, mode)
    for k, ref in enumerate(L): spec.append((ref, 0.0, k * PITCH_Y, rot_for(ref, +1), 2))
    for k, ref in enumerate(R_): spec.append((ref, PITCH_X, k * PITCH_Y, rot_for(ref, -1), 1))
    xs = np.arange(WIN[0], WIN[2], 0.05); ys = np.arange(WIN[1], WIN[3], 0.05)
    TX, TY = np.meshgrid(xs, ys); TX = TX.ravel(); TY = TY.ravel()
    ok = np.ones(len(TX), bool)
    shapes_ = {}
    for ref, dx, dy, d, mode in spec:
        p, X, Y = single(ref, d, mode, np.unique(np.round(TX + dx, 3)), np.unique(np.round(TY + dy, 3)))
        good = set(zip(np.round(X, 3), np.round(Y, 3)))
        ok &= np.array([(round(a + dx, 3), round(b_ + dy, 3)) in good for a, b_ in zip(TX, TY)])
        # ties
        for pad, ic_, pin, lim in TIES.get(ref, []):
            ox, oy = padoff(ref, pad, d)
            ok &= np.hypot(TX + dx + ox - u_all[(ic_, pin)][0], TY + dy + oy - u_all[(ic_, pin)][1]) <= lim + 1e-9
    # the six among themselves (translation invariant): courtyard / label conflicts and 3b
    bad_inner = False
    for (r1, x1, y1, d1, m1), (r2, x2, y2, d2, m2) in itertools.combinations(spec, 2):
        P1 = variant(r1, d1, m1); P2 = variant(r2, d2, m2)
        C1, L1 = shp(P1, np.array([x1]), np.array([y1])); C2, L2 = shp(P2, np.array([x2]), np.array([y2]))
        if conf_np(C1, L1, C2, L2).any() or c3b(C1, L1, np.array([m1 != 0]), C2, L2, np.array([m2 != 0])).any(): bad_inner = True
    # HPWL of the N net (and of nets whose pads are all in the six)
    hp = []
    for (ref, dx, dy, d, mode) in spec:
        pass
    pts = [(dx + padoff(ref, npin(ref), d)[0], dy + padoff(ref, npin(ref), d)[1]) for ref, dx, dy, d, mode in spec]
    hpn = (max(p[0] for p in pts) - min(p[0] for p in pts)) + (max(p[1] for p in pts) - min(p[1] for p in pts))
    print('VARIANT flip', flip, 'swap', swap, 'rows', [(r[0], r[3], r[4]) for r in spec], 'inner conflict', bad_inner, 'N HPWL', round(hpn, 2), 'legal translations', int(ok.sum()))
    if not bad_inner and ok.any():
        idx = np.nonzero(ok)[0]
        # NP net: R106.2 with U101.5 within the limit
        for t in idx[::max(1, len(idx) // 12)]:
            results.append((flip, swap, round(float(TX[t]), 2), round(float(TY[t]), 2), spec))
print('RESULTS', len(results))
for fl, sw, tx, ty, spec in results[:40]:
    print('RES', fl, sw, tx, ty, [(r, round(tx + dx, 2), round(ty + dy, 2), d, m) for r, dx, dy, d, m in spec])
