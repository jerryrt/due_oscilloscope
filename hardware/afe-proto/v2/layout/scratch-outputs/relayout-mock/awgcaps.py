import sys, math, json
sys.path.insert(0, '/work/hardware/afe-proto/v2/layout')
import numpy as np, relayout_place as RP
R = '/work/hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock/'
D0, P0 = RP.load(R + 'dump_all.json'); D1, P1 = RP.load(R + 'dump_new.json')
def ov(a, b, g): return min(a[2], b[2]) - max(a[0], b[0]) + g > 0 and min(a[3], b[3]) - max(a[1], b[1]) + g > 0
ic = 'U301'
gu = RP.part_geom(P0[ic]); ux, uy = P1[ic]['x'], P1[ic]['y']
U_ext = (gu['ext'][0]+ux, gu['ext'][1]+uy, gu['ext'][2]+ux, gu['ext'][3]+uy)
U_zone = (gu['zone'][0]+ux, gu['zone'][1]+uy, gu['zone'][2]+ux, gu['zone'][3]+uy); U_lab = (gu['lab'][0]+ux, gu['lab'][1]+uy, gu['lab'][2]+ux, gu['lab'][3]+uy)
print('U301 at', ux, uy, 'ext', [round(v, 2) for v in U_ext])
reg = RP.REGIONS['AWG']; mext, mlab = RP.Mask(reg, 0.2), RP.Mask(reg, 0.4)
lanes = RP.LANES
def cands(ref, pin_n):
    pin = [q['c'] for q in P1[ic]['pads'] if q['n'] == pin_n][0]
    out = []
    for k in range(4):
        c, s_ = RP.COS[k], RP.SIN[k]
        pads = [(q['c'][0] - P0[ref]['x'], q['c'][1] - P0[ref]['y']) for q in P0[ref]['pads']]
        pads = [(o[0]*c - o[1]*s_, o[0]*s_ + o[1]*c) for o in pads]
        idx = [q['n'] for q in P0[ref]['pads']]
        # the pad on the IC pin's net
        net = [q['net'] for q in P1[ic]['pads'] if q['n'] == pin_n][0]
        on = [i for i, q in enumerate(P0[ref]['pads']) if q['net'] == net] or [0]
        for ls in (0, 2, 4):
            g = RP.part_geom(P0[ref], k, ls)
            padsU = [q['c'] for q in P1[ic]['pads']]
            pts = [(round(float(x), 3), py) for py in sorted({round(p[1], 3) for p in padsU}) for x in np.arange(pin[0] - 3.2, pin[0] + 3.2, 0.05)] + [(px, round(float(y), 3)) for px in sorted({round(p[0], 3) for p in padsU}) for y in np.arange(pin[1] - 3.2, pin[1] + 3.2, 0.05)]
            for (x, y) in pts:
                if True:
                    if min(math.hypot(x + pads[i][0] - pin[0], y + pads[i][1] - pin[1]) for i in on) > 2.79: continue
                    e = (g['ext'][0]+x, g['ext'][1]+y, g['ext'][2]+x, g['ext'][3]+y); z = (g['zone'][0]+x, g['zone'][1]+y, g['zone'][2]+x, g['zone'][3]+y); lb = (g['lab'][0]+x, g['lab'][1]+y, g['lab'][2]+x, g['lab'][3]+y)
                    if mext.bad(e) > 0 or mlab.bad(lb) > 0: continue
                    if ov(e, U_ext, 0.02) or ov(z, U_ext, 0) or ov(e, U_zone, 0) or ov(lb, U_lab, 0.5): continue
                    if any(ov(e, l, 0) or ov(z, l, 0) for l in lanes): continue
                    out.append((ref, k, ls, x, y, e, z, lb))
    return out
C5 = cands('C305', '8'); C6 = cands('C306', '4')
print('C305 (<=2.8 to pin 8):', len(C5), ' C306 (<=2.8 to pin 4):', len(C6))
def comp(a, b): return not (ov(a[5], b[5], 0.02) or ov(a[6], b[5], 0) or ov(b[6], a[5], 0) or ov(a[7], b[7], 0.5))
n = sum(1 for a in C5 for b in C6 if comp(a, b))
print('compatible C305/C306 pairs, both on U301 pad lines:', n)
best = sorted(((math.hypot(a[3]-76.56, a[4]-9.71) + math.hypot(b[3]-76.56, b[4]-9.71), a[:5], b[:5]) for a in C5 for b in C6 if comp(a, b)))[:3]
for b_ in best: print(b_)
