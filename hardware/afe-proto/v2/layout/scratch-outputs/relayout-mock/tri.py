import sys, math, json, itertools
sys.path.insert(0, '/work/hardware/afe-proto/v2/layout')
import numpy as np, relayout_place as RP
D, P = RP.load('/work/hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock/dump_all.json')
ux, uy = P['U101']['x'], P['U101']['y']
gu = RP.part_geom(P['U101'])
U_ext = (gu['ext'][0]+ux, gu['ext'][1]+uy, gu['ext'][2]+ux, gu['ext'][3]+uy)
USHIFT = int(sys.argv[1]) if len(sys.argv) > 1 else 0
def ulab(ls, mode):
    g = RP.part_geom(P['U101'], 0, ls)
    return ((g['lab'][0]+ux, g['lab'][1]+uy, g['lab'][2]+ux, g['lab'][3]+uy), (g['zone'][0]+ux, g['zone'][1]+uy, g['zone'][2]+ux, g['zone'][3]+uy))
Ulab, Uzone = ulab(USHIFT, 0)
if USHIFT < 0:                      # step 2: U101's designator horizontal beside its pin-free east end, centred on the body's y
    cxe = U_ext[2] + 0.3 + 1.9; cye = (U_ext[1] + U_ext[3]) / 2
    Ulab = (cxe - 1.9, cye - 0.65, cxe + 1.9, cye + 0.65); Uzone = (Ulab[0] - 0.3, Ulab[1] - 0.3, Ulab[2] + 0.3, Ulab[3] + 0.3)
def ov(a, b, g): return min(a[2], b[2]) - max(a[0], b[0]) + g > 0 and min(a[3], b[3]) - max(a[1], b[1]) + g > 0
p8 = [q['c'] for q in P['U101']['pads'] if q['n'] == '8'][0]; p7 = [q['c'] for q in P['U101']['pads'] if q['n'] == '7'][0]; p6 = [q['c'] for q in P['U101']['pads'] if q['n'] == '6'][0]
def cands(ref, pin, lim, step, ks, lss, xr, yr, extra=None):
    out = []
    for k in ks:
        c, s_ = RP.COS[k], RP.SIN[k]
        pads = [(q['c'][0]-P[ref]['x'], q['c'][1]-P[ref]['y']) for q in P[ref]['pads']]
        pads = [(o[0]*c - o[1]*s_, o[0]*s_ + o[1]*c) for o in pads]
        for ls in lss:
            g = RP.part_geom(P[ref], k, ls)
            for x in np.arange(xr[0], xr[1], step):
                for y in np.arange(yr[0], yr[1], step):
                    o1 = pads[[q['n'] for q in P[ref]['pads']].index('1')]; dmin = math.hypot(x+o1[0]-pin[0], y+o1[1]-pin[1])
                    if dmin > lim: continue
                    e = (g['ext'][0]+x, g['ext'][1]+y, g['ext'][2]+x, g['ext'][3]+y)
                    z = (g['zone'][0]+x, g['zone'][1]+y, g['zone'][2]+x, g['zone'][3]+y)
                    lb = (g['lab'][0]+x, g['lab'][1]+y, g['lab'][2]+x, g['lab'][3]+y)
                    if ov(e, U_ext, 0.02) or ov(z, U_ext, 0) or ov(e, Uzone, 0) or ov(lb, Ulab, 0.5) or ov(lb, U_ext, 0.3): continue
                    out.append((ref, k, ls, round(x, 2), round(y, 2), e, z, lb, pads))
    return out
step = 0.1
C = {}
for ref in ('C104', 'C105'):
    C[ref] = cands(ref, p8, 2.8, step, [0, 1, 2, 3], [0, 2, 4], (70, 81), (30, 42))
R108 = cands('R108', p7, 5.0, step, [0, 1, 2, 3], [0, 2, 4], (70, 82.6), (30, 42))
# R108: pad 1 span and flow x < 82.6
def span_ok(c):
    ref, k, ls, x, y, e, z, lb, pads = c
    n1 = [q['n'] for q in P['R108']['pads']].index('1'); o = pads[n1]
    xs = [x+o[0], p6[0], p7[0]]; ys = [y+o[1], p6[1], p7[1]]
    return (max(xs)-min(xs)) + (max(ys)-min(ys)) <= 4.99 and x < 82.6
R108 = [c for c in R108 if span_ok(c)]
print('candidates C104 %d C105 %d R108 %d' % (len(C['C104']), len(C['C105']), len(R108)))
def comp(a, b):
    return not (ov(a[5], b[5], 0.02) or ov(a[6], b[5], 0) or ov(b[6], a[5], 0) or ov(a[7], b[7], 0.5))
import random
sol = 0; best = None
for a in C['C104']:
    for b in C['C105']:
        if not comp(a, b): continue
        for c in R108:
            if comp(a, c) and comp(b, c):
                sol += 1
                if best is None: best = (a[:5], b[:5], c[:5])
print('triples', sol, best)
pairs = sum(1 for a in C['C104'] for b in C['C105'] if comp(a, b)); print('C104-C105 compatible pairs', pairs)
R2 = [c for c in cands('R108', p7, 5.0, step, [0,1,2,3], [0,2,4], (70, 82.6), (30, 42))]
print('R108 within 5 mm of pin 7 (no span rule):', len(R2))


pp = [(a, b) for a in C['C104'] for b in C['C105'] if comp(a, b)]
R2 = [c for c in R2 if c[3] < 82.6]
n = 0; ex = None
for a, b in pp:
    for c in R2:
        if comp(a, c) and comp(b, c):
            n += 1
            if ex is None: ex = (a[:5], b[:5], c[:5])
print('triples without the span rule:', n, ex)
