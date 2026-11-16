import sys, math, json
sys.path.insert(0, '/work/hardware/afe-proto/v2/layout')
import numpy as np, relayout_place as RP
D, P = RP.load('/work/hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock/dump_all.json')
ux, uy = P['U101']['x'], P['U101']['y']
ge = RP.part_geom(P['U101'])
U_ext = (ge['ext'][0]+ux, ge['ext'][1]+uy, ge['ext'][2]+ux, ge['ext'][3]+uy)
def ov(a, b, g): return min(a[2], b[2]) - max(a[0], b[0]) + g > 0 and min(a[3], b[3]) - max(a[1], b[1]) + g > 0
pad = lambda r, n: [q['c'] for q in P[r]['pads'] if q['n'] == n][0]
# R108 alone: every rotation, every U101 label shift, position grid 0.05 within +-8 mm of pin 7
p7 = pad('U101', '7'); p6 = pad('U101', '6')
cnt = {}
for k in range(4):
    g = RP.part_geom(P['R108'], k, 0)
    o = [q for q in P['R108']['pads'] if q['n'] == '1'][0]['c']; o = (o[0] - P['R108']['x'], o[1] - P['R108']['y'])
    c, s_ = RP.COS[k], RP.SIN[k]; o = (o[0]*c - o[1]*s_, o[0]*s_ + o[1]*c)
    for uls in range(6):
        gu = RP.part_geom(P['U101'], 0, uls)
        Ulab = (gu['lab'][0]+ux, gu['lab'][1]+uy, gu['lab'][2]+ux, gu['lab'][3]+uy); Uzone = (gu['zone'][0]+ux, gu['zone'][1]+uy, gu['zone'][2]+ux, gu['zone'][3]+uy)
        n = 0
        for x in np.arange(70, 95, 0.05):
            if x >= 82.6: break
            for y in np.arange(30, 46, 0.05):
                pp = (x + o[0], y + o[1])
                if math.hypot(pp[0]-p7[0], pp[1]-p7[1]) > 5.0: continue
                xs = [pp[0], p6[0], p7[0]]; ys = [pp[1], p6[1], p7[1]]
                if (max(xs)-min(xs)) + (max(ys)-min(ys)) > 5.0: continue
                e = (g['ext'][0]+x, g['ext'][1]+y, g['ext'][2]+x, g['ext'][3]+y)
                z = (g['zone'][0]+x, g['zone'][1]+y, g['zone'][2]+x, g['zone'][3]+y)
                lb = (g['lab'][0]+x, g['lab'][1]+y, g['lab'][2]+x, g['lab'][3]+y)
                if ov(e, U_ext, 0.02) or ov(z, U_ext, 0) or ov(e, Uzone, 0) or ov(lb, Ulab, 0.5) or ov(lb, U_ext, 0.3): continue
                n += 1
        cnt[(k, uls)] = n
print('R108 feasible positions (rot, U101 label shift):', {k: v for k, v in cnt.items() if v})
print('total', sum(cnt.values()))
