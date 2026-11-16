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
        'R405': (36.5, 10.6), 'C408': (39.9, 15.4), 'C407': (33.1, 18.6), 'R407': (42.2, 21.1), 'R401': (29.4, 17.3), 'R409': (29.6, 21.1), 'R406': (37.8, 21.1), 'R403': (32.4, 8.3), 'R404': (40.3, 8.2), 
        'TP402': (22.0, 25.5), 'TP403': (27.0, 25.5), 'TP404': (32.0, 25.5), 'TP401': (37.0, 25.5), 'TP405': (42.0, 25.5), 'R408': (23.0, 29.5), 'R410': (29.0, 29.5),  'C402': (36.3, 13.6), 'C403': (36.1, 16.4), 'C401': (28.9, 12.6), 'R302': (78.55, 9.1), 'R303': (82.0, 7.35), 'C301': (78.6, 7.35), 'R305': (85.45, 6.95), 'C304': (85.45, 8.9), 'C305': (72.3, 17.55)}
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
bad = LPm.violations(parts, pos, rect, ANCH, obst, CAPS, SPANS)
target = {r: pos[r] for r in refs}
print('parts', len(refs), 'violations', len(bad))
for x in bad[:60]: print(' ', x)
disp = {r: ((pos[r][0]-target[r][0])**2 + (pos[r][1]-target[r][1])**2) ** .5 for r in refs}
print('max displacement from target', max(disp.values()), sorted(disp, key=disp.get)[-5:])
json.dump({r: [*pos[r]] for r in refs}, open('whatif/_scratch/relay_pos.json', 'w'))
from pcbtools.labelplace import P, _shapes, _pen, CC, LC, LL
pp = {r: _setmode(P(r, rel[r], r not in ANCH, r in NOLAB)) for r in refs}
def explain(a, b):
    Ci, Li = _shapes(pp[a], *pos[a]); Cj, Lj = _shapes(pp[b], *pos[b])
    for nm, x, y, m in (('C-C', Ci, Cj, CC), ('Li-Cj', Li, Cj, LC), ('Lj-Ci', Lj, Ci, LC), ('L-L', Li, Lj, LL)):
        px, py = _pen(x, y, m - 0.05)
        if px > 0 and py > 0: print(a, b, nm, [round(v, 2) for v in x], [round(v, 2) for v in y], 'pos', pos[a], pos[b], 'fixed', a in ANCH, b in ANCH)
for v in bad:
    if '/' in v and not v.startswith(('R413',)):
        a, b = v.split('/'); explain(a, b)

import itertools
idx = {r: i for i, r in enumerate(refs)}
def costp(r, p):
    i = idx[r]; n = 0
    for j, o in enumerate(parts):
        if j != i and (parts[i].free or o.free) and LPm._pair_bad(parts[i], *p, o, *pos[o.ref], tol=0.05): n += 1
    for q in obst:
        if LPm._obst_bad(parts[i], *p, q, tol=0.05): n += 1
    if i in rect:
        C_, L_ = LPm._shapes(parts[i], *p); q = rect[i]
        if not (q[0] - 0.01 <= C_[0] and q[1] - 0.01 <= C_[1] and C_[2] <= q[2] + 0.01 and C_[3] <= q[3] + 0.01): n += 1
        if not (LPm.INTERIOR[0] - 0.01 <= L_[0] and L_[2] <= LPm.INTERIOR[2] + 0.01 and L_[3] <= LPm.INTERIOR[3] + 0.01): n += 1
    old = pos[r]; pos[r] = p
    for c in CAPS:
        if r in (c[0], c[2]) and LPm.cap_bad([c], [], pos): n += 1
    for sp in SPANS:
        if any(m[0] == r for m in sp[0]) and LPm.cap_bad([], [sp], pos): n += 1
    pos[r] = old
    return n
import sys as _s
for r in os.environ.get('SCAN', '').split(','):
    if not r: continue
    x0, y0 = pos[r]; best = []
    for dx in np.arange(-8, 8.01, 0.25):
        for dy in np.arange(-8, 8.01, 0.25):
            if r in LOCKX and dx: continue
            p = (round(x0 + dx, 3), round(y0 + dy, 3))
            if costp(r, p) == 0: best.append((abs(dx) + abs(dy), p))
    best.sort()
    print('SCAN', r, 'from', (x0, y0), 'zero-violation places', len(best), best[:4])
a, b_ = pp['R305'], pp['C203']
print('R305 rel', rel['R305'], 'C203 rel', rel['C203'], 'pairbad', LPm._pair_bad(a, *pos['R305'], b_, *pos['C203'], tol=0.05), 'free', a.free, b_.free)
print([round(v, 2) for v in LPm._shapes(a, *pos['R305'])[1]], [round(v, 2) for v in LPm._shapes(b_, *pos['C203'])[0]])

if os.environ.get('AUTOFIX'):
    for it in range(20):
        bad = LPm.violations(parts, pos, rect, ANCH, obst, CAPS, SPANS)
        print('autofix round', it, len(bad), bad[:6])
        if not bad: break
        only = set(os.environ.get('ONLY', '').split(',')) - {''}
        names = {nm.strip().split(' ')[0] for v in bad for nm in v.replace(':', '/').split('/')[:2] if nm.strip().split(' ')[0] in idx}
        for v in bad:
            if v.startswith('span '):
                names |= {m[0] for m in SPANS[int(v.split(':')[0].split()[1])][0]}
            if v.startswith('cap '):
                names |= set(v.split(':')[0].replace('cap ', '').split('-'))
        if only: names &= only
        done = False
        for r in sorted(names):
            if not parts[idx[r]].free: continue
            x0, y0 = pos[r]; best = None
            for dx in np.arange(-10, 10.01, 0.25):
                for dy in np.arange(-10, 10.01, 0.25):
                    if r in LOCKX and dx: continue
                    p = (round(x0 + dx, 3), round(y0 + dy, 3))
                    d = abs(dx) + abs(dy)
                    if best is not None and d >= best[0]: continue
                    if costp(r, p) == 0: best = (d, p)
            if best and best[0] > 0:
                print('  move', r, (x0, y0), '->', best[1]); pos[r] = best[1]; done = True; break
        if not done: break
    json.dump({r: [*pos[r]] for r in refs}, open('whatif/_scratch/relay_pos.json', 'w'))
    bad = LPm.violations(parts, pos, rect, ANCH, obst, CAPS, SPANS); print('FINAL', len(bad), bad)

for k, (mem, wx, wy) in enumerate(SPANS):
    print('SPAN', k, [(r, round(pos[r][1] + pd[1], 2), round(pos[r][0] + pd[0], 2)) for r, pd in mem], 'landed', wx, wy)

if os.environ.get('MAP'):
    x0, y0, x1, y1 = map(float, os.environ['MAP'].split(','))
    for r in refs:
        C_, L_ = LPm._shapes(pp[r], *pos[r])
        if C_[2] > x0 and C_[0] < x1 and C_[3] > y0 and C_[1] < y1:
            print('MAP', r, 'pos', pos[r], 'C', [round(v, 2) for v in C_], 'L', [round(v, 2) for v in L_], 'ANCH' if r in ANCH else '')

if os.environ.get('CLIMB'):
    import random
    random.seed(int(os.environ.get('SEED', '1')))
    JIT = float(os.environ.get('JITTER', '0'))
    if JIT:
        b0 = [v for v in LPm.violations(parts, pos, rect, ANCH, obst, CAPS, SPANS) if 'outside' not in v]
        for v in b0:
            for nm in v.replace(':', '/').split('/')[:2]:
                nm = nm.strip().split(' ')[0]
                if nm in idx and nm not in ('U101', 'U301', 'U401', 'J501') and nm not in LOCKX and not nm.startswith(('J', 'MH')) and (not os.environ.get('ONLYC') or nm in os.environ['ONLYC'].split(',')):
                    pos[nm] = (round(pos[nm][0] + random.gauss(0, JIT), 2), round(pos[nm][1] + random.gauss(0, JIT), 2))
    for rnd in range(int(os.environ['CLIMB'])):
        bad = LPm.violations(parts, pos, rect, ANCH, obst, CAPS, SPANS)
        bad = [v for v in bad if 'outside its fence' not in v and 'label outside' not in v]
        print('climb', rnd, len(bad), bad[:8])
        if not bad: break
        names = set()
        for v in bad:
            for nm in v.replace(':', '/').split('/')[:2]:
                nm = nm.strip().split(' ')[0]
                if nm in idx: names.add(nm)
            if v.startswith('cap '): names |= set(v.split(':')[0].replace('cap ', '').split('-'))
        names = [n for n in names if n not in ('U101', 'U301', 'U401', 'J501')]
        _only = set(os.environ.get('ONLYC', '').split(',')) - {''}
        if _only: names = [n for n in names if n in _only]
        random.shuffle(names)
        improved = False
        for r in names:
            x0, y0 = pos[r]; c0 = costp(r, pos[r]); best = (c0, 0.0, pos[r])
            for dx in np.arange(-6, 6.01, 0.25):
                for dy in np.arange(-6, 6.01, 0.25):
                    if r in LOCKX and dx: continue
                    p = (round(x0 + dx, 3), round(y0 + dy, 3)); c = costp(r, p); d = abs(dx) + abs(dy)
                    if c < best[0] or (c == best[0] and c < c0 and d < best[1]): best = (c, d, p)
            if best[0] < c0:
                print('  climb', r, c0, '->', best[0], pos[r], best[2]); pos[r] = best[2]; improved = True
        if not improved: break
    bad = LPm.violations(parts, pos, rect, ANCH, obst, CAPS, SPANS); print('CLIMB FINAL', len(bad), bad)
    json.dump({r: [*pos[r]] for r in refs}, open(os.environ.get('OUTJ', 'whatif/_scratch/relay_pos.json'), 'w'))

if os.environ.get('PADS'):
    for r in os.environ['PADS'].split(','):
        print('PADS', r, {pin: (round(v[0], 2), round(v[1], 2), boardio.read_board('kicad/afe-proto.kicad_pcb').nets[v[2]]) for pin, v in padrel[r].items()})

_B0 = boardio.read_board('kicad/afe-proto.kicad_pcb')
NETS = []
_B1 = boardio.read_board('kicad/afe-proto.kicad_pcb')
_sub = set(os.environ.get('ANNEALSUB', '').split(','))
_byn = {}
for r_, pads_ in padrel.items():
    for pin_, (px_, py_, n_) in pads_.items():
        _byn.setdefault(n_, []).append((r_, (px_, py_)))
for n_, mem_ in _byn.items():
    nm_ = _B1.nets[n_]
    if nm_ in ('', '/GND') or len(mem_) < 2 or len(mem_) > 8: continue
    if not any(m[0] in _sub for m in mem_): continue
    NETS.append((mem_, 1.0))
print('nets', len(NETS))
ROT = {**json.load(open('whatif/_scratch/rot.json')), **ROTOV}
PAS = re.compile(r'(?:R|C|BR|L|FB)(\d)\d\d$')
ALIGN = {'passives': {r_: (PAS.fullmatch(r_).group(1), round(ROT[r_] % 180)) for r_ in refs if PAS.fullmatch(r_)},
         'pads': {r_: [(v[0], v[1]) for v in padrel[r_].values()] for r_ in refs if not PAS.fullmatch(r_) and r_ in padrel and not r_.startswith('MH')}}
TARGET0 = {r: (float(_B0.fp_x[_B0.ref_index(r)]), float(_B0.fp_y[_B0.ref_index(r)])) for r in refs}
if os.environ.get('ANNEALSUB'):
    sub = set(os.environ['ANNEALSUB'].split(',')) if os.environ['ANNEALSUB'] != 'ALL' else {r for r in refs if r not in ('U101','U301','U401','C402','J501','R411') and r not in HAND and not r.startswith(('J','MH'))}
    ANCH2 = set(ANCH) - sub
    fence2 = dict(fence)
    for r in sub:
        if fence[r] is big or fence[r] == big:
            dd = re.fullmatch(r'[A-Z]+(\d)\d\d', r).group(1)
            fence2[r] = WALL if r in WALLREFS else FENCE[dd]
        else:
            fence2[r] = fence[r]
    best = None
    for sd in range(int(os.environ.get('SEEDB', '0')), int(os.environ.get('SEEDB', '0')) + int(os.environ.get('SEEDS', '6'))):
        p0 = dict(pos)
        if os.environ.get('START') == 'LANDED':
            p0 = dict(TARGET0)
            for r_, v_ in HAND.items():
                p0[r_] = v_
            for r_ in ANCH:
                if r_ not in HAND: p0[r_] = pos[r_]
        pos2, bad2 = LPm.anneal(refs, rel, p0, dict(TARGET0), fence2, ANCH2, LOCKX, obst, nolabel=set(NOLAB), iters=int(os.environ.get('ITERS', '40000')), seed=sd, caps=CAPS, spans=SPANS, t0=float(os.environ.get('T0', '0.25')), w_disp=float(os.environ.get('WDISP', '0.15')), weights={r: 3.0 for r in CRIT}, xmin=XMIN, nets=NETS, w_net=float(os.environ.get('WNET', '0.0')), align=ALIGN, w_align=float(os.environ.get('WALIGN', '0.0')), p_snap=float(os.environ.get('PSNAP', '0.0')))
        bad2 = [v for v in bad2 if not v.startswith(('J607/MH', 'U401/C402', 'J602/R411', 'J601/R411', 'MH602/J605'))]
        print('anneal seed', sd, len(bad2), flush=True)
        if best is None or len(bad2) < len(best[1]): best = (pos2, bad2)
    pos, bad2 = best
    print('ANNEALSUB FINAL', len(bad2), bad2)
    json.dump({r: [*pos[r]] for r in refs}, open(os.environ.get('OUTJ', 'whatif/_scratch/relay_pos.json'), 'w'))

if os.environ.get('CORR'):
    BR = {'R309','R310','R515','R516','R110','D101','D201','R107','R207','TP101','TP201','J602'}
    for xl, xr, nm in ((65.7, 66.4, 'A1'), (68.2, 68.9, 'A0')):
        hit = []
        for r in refs:
            if r in BR: continue
            C_, L_ = LPm._shapes(pp[r], *pos[r])
            if C_[2] > xl and C_[0] < xr and C_[3] > 4.4 and C_[1] < 40: hit.append((r, round(C_[1], 1)))
        print('CORR', nm, hit)

if os.environ.get('EVAL'):
    PW = {r for r in refs if re.fullmatch(r'[A-Z]+4\d\d', r)}
    for c in CAPS:
        if c[0] in PW or c[2] in PW:
            dx = pos[c[0]][0] + c[1][0] - pos[c[2]][0] - c[3][0]; dy = pos[c[0]][1] + c[1][1] - pos[c[2]][1] - c[3][1]
            d = (dx * dx + dy * dy) ** .5
            print('EVALCAP', c[0], '->', c[2], round(d, 2), 'limit', c[4], 'OK' if d <= c[4] + 0.05 else 'OVER')
    for v in LPm.violations(parts, pos, rect, ANCH, obst, [], []):
        a_, _, b_ = v.partition('/')
        if re.match(r'[A-Z]+4\d\d', v) and ('/' not in v or re.match(r'[A-Z]+4\d\d', b_)): print('EVALVIOL', v)

if os.environ.get('EXPLAIN'):
    from pcbtools.labelplace import _pen, CC, LC, LL
    for pr_ in os.environ['EXPLAIN'].split(','):
        a_, b_ = pr_.split('/')
        Ci, Li = LPm._shapes(pp[a_], *pos[a_]); Cj, Lj = LPm._shapes(pp[b_], *pos[b_])
        for nm, x, y, m in (('C-C', Ci, Cj, CC), ('Li-Cj', Li, Cj, LC), ('Lj-Ci', Lj, Ci, LC), ('L-L', Li, Lj, LL)):
            px, py = _pen(x, y, m - 0.05)
            if px > 0 and py > 0: print('EXPLAIN', a_, b_, nm, [round(v, 2) for v in x], [round(v, 2) for v in y], 'pos', pos[a_], pos[b_])
