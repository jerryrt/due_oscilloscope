"""AFE-1 relayout step 1 (D30, the owner's convention of 2026-11-15): positions with room for a designator above every part.

    python3 kicad/relayout_rev_a.py FLIPS SEED NSEEDS ANNEAL_ITERS      (in the PCB image; PYTHONPATH=hardware/afe-proto; run from hardware/afe-proto)

Starts from the landed board (kicad/afe-proto.kicad_pcb: origins and courtyards, rotations kept), solves with pcbtools/labelplace.py (a linear programme for
least movement, restarts with jittered targets, a hill-climb and an anneal on the violation count) inside the fence rectangles below, and writes the
origins to kicad/relayout_pos.json. HAND holds the positions chosen by hand (REF/CAL's ladder zone, J501, the wall bridges) and ANCH the parts that
never move. The result goes into kicad/layout.py's RELAID table (rotations from the landed board).
"""
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
LADDER = {'R503', 'R504', 'R505', 'R506', 'R507', 'R508'}
HAND = {'R508': (52.07, 6.5), 'R506': (57.15, 6.5), 'R504': (62.23, 6.5), 'R507': (54.61, 9.35), 'R505': (59.69, 9.35),
        'R503': (63.05, 10.15), 
        'R501': (63.35, 18.5), 'R513': (53.9, 20.8), 'U502': (58.1, 21.3), 'D501': (62.2, 26.6), 'TP501': (51.2, 10.9), 'R502': (62.3, 20.6), 'R207': (79.2, 28.0), 'R107': (80.65, 40.2), 'R302': (76.4, 8.0), 'C502': (60.9, 22.9), 'R514': (53.7, 15.35), 'R520': (51.3, 15.35), 'R515': (66.04, 24.0), 'R516': (68.58, 27.3), 'D201': (72.6, 28.4), 'J501': (56.54, 14.9)}
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
    elif r in WALLREFS: fence[r] = [(62.2, 13.0, 71.0, 30.8)]
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

# ---- hard constraints from the landed board (LR-4/LR-5/LR-12): critical parts keep their distance to the pin they serve; A0/A1 get no longer
padrel = {}
padpos = {}
for j in range(len(b.p_fp)):
    r = b.fp_ref[int(b.p_fp[j])]
    k = int(b.p_fp[j])
    padrel.setdefault(r, {})[b.p_pin[j]] = (float(b.p_x[j] - b.fp_x[k]), float(b.p_y[j] - b.fp_y[k]), int(b.p_net[j]))
def pr(ref, pin): return padrel[ref][pin][:2]
def landed(ra, pa, rb, pb):
    xa = b.fp_x[b.ref_index(ra)] + pr(ra, pa)[0]; ya = b.fp_y[b.ref_index(ra)] + pr(ra, pa)[1]
    xb = b.fp_x[b.ref_index(rb)] + pr(rb, pb)[0]; yb = b.fp_y[b.ref_index(rb)] + pr(rb, pb)[1]
    return float(((xa - xb) ** 2 + (ya - yb) ** 2) ** .5)
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
SPANS = []
for nm in ('/A0', '/A1'):
    nid = b.nets.index(nm)
    mem, xs, ys = [], [], []
    for r, pads in padrel.items():
        for pin, (px, py, n_) in pads.items():
            if n_ == nid and not np.isnan(b.fp_x[b.ref_index(r)]):
                k = b.ref_index(r)
                mem.append((r, (px, py))); xs.append(b.fp_x[k] + px); ys.append(b.fp_y[k] + py)
    SPANS.append((mem, round(max(xs) - min(xs), 3), round(max(ys) - min(ys), 3)))
# the reference to the ladder and the ADS: U501's VREF pad to R508 and U502.4

import os as _os
SC = float(_os.environ.get('CAPSCALE', '1.0'))
if SC != 1.0:
    keep = {(c, i) for (c, i, p_), L in LIM.items()}
    CAPS = [(a_, pa_, b_, pb_, (D if (a_, b_) in keep else round(D * SC, 3))) for (a_, pa_, b_, pb_, D) in CAPS]
    SPANS = [(m, round(wx * SC, 3), round(wy * SC, 3)) for m, wx, wy in SPANS]
XMIN = {}
_gen = [b.ref_index(g) for g in ('U401', 'C402')]
_gx1 = max(float(b.fp_cx1[k]) for k in _gen); _gy0 = min(float(b.fp_cy0[k]) for k in _gen); _gy1 = max(float(b.fp_cy1[k]) for k in _gen)
_pref = tuple(n[1:] if n.startswith('/') else n for n in C.SENSITIVE)
for r, pads in padrel.items():
    if r in ANCH or r[0] not in 'RCDU' or re.fullmatch(r'[A-Z]+4\d\d', r): continue
    k = b.ref_index(r)
    for j in range(len(b.p_fp)):
        if b.fp_ref[int(b.p_fp[j])] == r and b.nets[int(b.p_net[j])].startswith(tuple(C.SENSITIVE)):
            if float(b.p_by1[j]) > _gy0 - 10.5 and float(b.p_by0[j]) < _gy1 + 10.5:
                XMIN[r] = max(XMIN.get(r, 0), _gx1 + 10.5 - (float(b.p_bx0[j]) - float(b.fp_x[k])))
print('xmin', {r: round(v, 1) for r, v in XMIN.items()})
print('critical', len(CRIT), sorted(CRIT)[:60])
print('caps', len(CAPS), 'spans', [(len(m), wx, wy) for m, wx, wy in SPANS])

best = None
rng = np.random.default_rng(int(sys.argv[2]) if len(sys.argv) > 2 else 0)
T0 = dict(target)
for seed in range(int(sys.argv[3]) if len(sys.argv) > 3 else 1):
    target = {r: ((T0[r][0] + (rng.normal(0, 0.4) if seed and r not in ANCH else 0) * (r not in LOCKX), T0[r][1] + (rng.normal(0, 0.4) if seed and r not in ANCH else 0))) for r in refs}
    pos, bad = LP.solve(refs, rel, target, fence, ANCH, LOCKX, obst, verbose=False, nolabel=set(NOLAB), caps=CAPS, spans=SPANS, weights={r: 4.0 for r in CRIT}, xmin=XMIN, flips=int(sys.argv[1]) if len(sys.argv) > 1 else 25)
    if best is None or len(bad) < len(best[1]): best = (pos, bad, dict(target))
    print('seed', seed, len(bad), flush=True)
pos, bad, target = best
print('before polish', len(bad))
pos, bad = LP.polish(refs, rel, pos, fence, ANCH, LOCKX, obst, nolabel=set(NOLAB), rounds=12, caps=CAPS, spans=SPANS)
print('after polish', len(bad))
pos, bad = LP.anneal(refs, rel, pos, target, fence, ANCH, LOCKX, obst, nolabel=set(NOLAB), caps=CAPS, spans=SPANS, iters=int(sys.argv[4]) if len(sys.argv) > 4 else 30000)
print('parts', len(refs), 'violations', len(bad))
for x in bad[:60]: print(' ', x)
disp = {r: ((pos[r][0]-target[r][0])**2 + (pos[r][1]-target[r][1])**2) ** .5 for r in refs}
print('max displacement from target', max(disp.values()), sorted(disp, key=disp.get)[-5:])
json.dump({r: [*pos[r]] for r in refs}, open('kicad/relayout_pos%s.json' % _os.environ.get('SUFFIX', ''), 'w'))
from pcbtools.labelplace import P, _shapes, _pen, CC, LC, LL
pp = {r: P(r, rel[r], r not in ANCH, r in NOLAB) for r in refs}
def explain(a, b):
    Ci, Li = _shapes(pp[a], *pos[a]); Cj, Lj = _shapes(pp[b], *pos[b])
    for nm, x, y, m in (('C-C', Ci, Cj, CC), ('Li-Cj', Li, Cj, LC), ('Lj-Ci', Lj, Ci, LC), ('L-L', Li, Lj, LL)):
        px, py = _pen(x, y, m - 0.05)
        if px > 0 and py > 0: print(a, b, nm, [round(v, 2) for v in x], [round(v, 2) for v in y], 'pos', pos[a], pos[b], 'fixed', a in ANCH, b in ANCH)
for v in bad:
    if '/' in v and not v.startswith(('R413',)):
        a, b = v.split('/'); explain(a, b)
