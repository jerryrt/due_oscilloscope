import sys, math, json, itertools
sys.path.insert(0, '/work/hardware/afe-proto/v2/layout')
import numpy as np, relayout_place as RP
D, P = RP.load('/work/hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock/dump_all.json')
ux, uy = P['U101']['x'], P['U101']['y']
gu = RP.part_geom(P['U101'])
U_ext = (gu['ext'][0]+ux, gu['ext'][1]+uy, gu['ext'][2]+ux, gu['ext'][3]+uy)
USHIFT = -1
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

padsU = [q['c'] for q in P['U101']['pads'] if q['n'] in ('5', '6', '7', '8')] + [q['c'] for q in P['U101']['pads'] if q['n'] in ('1', '2', '3', '4')]
lineY = sorted({round(c[1], 3) for c in padsU}); lineX = sorted({round(c[0], 3) for c in padsU})
def cand_line(ref, pin, lim, ks, lss, span=False):
    out = []
    for k in ks:
        c, s_ = RP.COS[k], RP.SIN[k]
        pads = [(q['c'][0]-P[ref]['x'], q['c'][1]-P[ref]['y']) for q in P[ref]['pads']]
        pads = [(o[0]*c - o[1]*s_, o[0]*s_ + o[1]*c) for o in pads]
        o1 = pads[[q['n'] for q in P[ref]['pads']].index('1')]
        for ls in lss:
            g = RP.part_geom(P[ref], k, ls)
            pts = [(x, y) for y in lineY for x in np.arange(70, 86, 0.05)] + [(x, y) for x in lineX for y in np.arange(30, 44, 0.05)]
            for x, y in pts:
                if math.hypot(x+o1[0]-pin[0], y+o1[1]-pin[1]) > lim: continue
                if min(math.hypot(x-p[0], y-p[1]) for p in padsU) > 4.0: continue
                if span:
                    xs = [x+o1[0], p6[0], p7[0]]; ys = [y+o1[1], p6[1], p7[1]]
                    if (max(xs)-min(xs)) + (max(ys)-min(ys)) > 4.99 or x >= 82.6: continue
                e = (g['ext'][0]+x, g['ext'][1]+y, g['ext'][2]+x, g['ext'][3]+y)
                z = (g['zone'][0]+x, g['zone'][1]+y, g['zone'][2]+x, g['zone'][3]+y)
                lb = (g['lab'][0]+x, g['lab'][1]+y, g['lab'][2]+x, g['lab'][3]+y)
                if ov(e, U_ext, 0.02) or ov(z, U_ext, 0) or ov(e, Uzone, 0) or ov(lb, Ulab, 0.5) or ov(lb, U_ext, 0.3): continue
                out.append((ref, k, ls, round(float(x), 3), round(float(y), 3), e, z, lb, pads))
    return out

def orient(ref, k): return RP.orient(P[ref], k)
def around(ref, pin, lim, k, ls, pts, span=False):
    out = []
    c, s_ = RP.COS[k], RP.SIN[k]
    pads = [(q['c'][0]-P[ref]['x'], q['c'][1]-P[ref]['y']) for q in P[ref]['pads']]
    pads = [(o[0]*c - o[1]*s_, o[0]*s_ + o[1]*c) for o in pads]
    o1 = pads[[q['n'] for q in P[ref]['pads']].index('1')]
    g = RP.part_geom(P[ref], k, ls)
    for x, y in pts:
        if math.hypot(x+o1[0]-pin[0], y+o1[1]-pin[1]) > lim: continue
        if span:
            xs = [x+o1[0], p6[0], p7[0]]; ys = [y+o1[1], p6[1], p7[1]]
            if (max(xs)-min(xs)) + (max(ys)-min(ys)) > 4.99 or x >= 82.6: continue
        e = (g['ext'][0]+x, g['ext'][1]+y, g['ext'][2]+x, g['ext'][3]+y)
        z = (g['zone'][0]+x, g['zone'][1]+y, g['zone'][2]+x, g['zone'][3]+y)
        lb = (g['lab'][0]+x, g['lab'][1]+y, g['lab'][2]+x, g['lab'][3]+y)
        if ov(e, U_ext, 0.02) or ov(z, U_ext, 0) or ov(e, Uzone, 0) or ov(lb, Ulab, 0.5) or ov(lb, U_ext, 0.3): continue
        out.append((ref, k, ls, round(float(x), 3), round(float(y), 3), e, z, lb, pads))
    return out
def comp(a, b):
    return not (ov(a[5], b[5], 0.02) or ov(a[6], b[5], 0) or ov(b[6], a[5], 0) or ov(a[7], b[7], 0.5))





def lrd(a, pin):
    o1 = a[8][[q['n'] for q in P[a[0]]['pads']].index('1')]
    return math.hypot(a[3]+o1[0]-pin[0], a[4]+o1[1]-pin[1])
C4 = [c for k in range(4) for ls in (0, 2, 4) for c in around('C104', p8, 2.8, k, ls, [(83.235, round(float(y), 2)) for y in np.arange(36.5, 41, 0.05)])]
C5 = [c for k in range(4) for ls in (0, 2, 4) for c in around('C105', p8, 2.8, k, ls, [(80.695, round(float(y), 2)) for y in np.arange(36.5, 42, 0.05)])]
R8 = [c for k in range(4) for ls in (0, 2, 4) for c in around('R108', p7, 5.0, k, ls, [(round(float(x), 2), 35.495) for x in np.arange(72, 79.9, 0.05)], True)]
print('C104 on pin 6 column', len(C4), 'C105 on pin 8 column', len(C5), 'R108 on the pin row', len(R8), flush=True)
best = []
for a in C4:
    for b in C5:
        if not comp(a, b): continue
        for c in R8:
            if comp(a, c) and comp(b, c):
                best.append((lrd(a, p8) + lrd(b, p8) + lrd(c, p7), a[:5], b[:5], c[:5], round(lrd(a, p8), 2), round(lrd(b, p8), 2), round(lrd(c, p7), 2)))
best.sort(key=lambda t: t[0])
print('all three on U101 pad lines:', len(best))
for t in best[:8]: print(t)
