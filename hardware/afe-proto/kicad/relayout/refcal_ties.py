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
HAND = {'R508': (52.07, 6.5), 'R506': (57.15, 6.5), 'R504': (62.23, 6.5), 'R507': (54.61, 9.35), 'R505': (61.6, 18.8),
        'R503': (63.05, 10.15), 'J501': (56.54, 14.9), 'C502': (55.7, 28.1), 'D501': (62.361, 27.661), 'R509': (62.4, 23.4),
        'R405': (36.5, 10.6), 'C408': (39.9, 15.4), 'C407': (33.1, 18.6), 'R407': (42.2, 21.1), 'R401': (29.4, 17.3), 'R409': (29.6, 21.1), 'R406': (37.8, 21.1), 'R403': (32.4, 8.3), 'R404': (40.3, 8.2), 
        'TP402': (22.0, 25.5), 'TP403': (27.0, 25.5), 'TP404': (32.0, 25.5), 'TP401': (37.0, 25.5), 'TP405': (42.0, 25.5), 'R408': (23.0, 29.5), 'R410': (29.0, 29.5),  'C402': (36.3, 13.6), 'C403': (36.1, 16.4), 'C401': (28.5, 14.2), 'R302': (78.55, 7.5), 'R303': (78.55, 9.25), 'C301': (78.6, 5.75), 'R305': (83.85, 6.8), 'C304': (84.65, 8.6), 'C305': (72.3, 17.55)}
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

import re as _re
def _pn(ref, off):
    for pn,(px,py,nn) in padrel[ref].items():
        if abs(px-off[0])<1e-6 and abs(py-off[1])<1e-6: return pn
print('REFCAL ties (own pad -> ic pin: limit, current):')
for (q,qoff,ic,icoff,D) in CAPS:
    if _re.fullmatch(r'[RCD]5\d\d|TP5\d\d', q):
        ax=pos[q][0]+qoff[0]; ay=pos[q][1]+qoff[1]; bx=pos[ic][0]+icoff[0]; by=pos[ic][1]+icoff[1]
        d=((ax-bx)**2+(ay-by)**2)**.5
        print('TIE', q, _pn(q,qoff), ic, _pn(ic,icoff), 'limit', round(D,2), 'now', round(d,2), 'VIOL' if d>D+1e-6 else '', 'ANCH' if q in ANCH else '', 'HAND' if q in HAND else '')
for k,(mem,wx,wy) in enumerate(SPANS): print('SPAN',k,[m[0] for m in mem],wx,wy)
