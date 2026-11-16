import sys, math, json
sys.path.insert(0, '/work/hardware/afe-proto/v2/layout')
import numpy as np, relayout_place as RP
R = '/work/hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock/'
D0, P0 = RP.load(R + 'dump_all.json'); D1, P1 = RP.load(R + 'dump_new.json')
ref, ic, pin = 'C503', 'U502', '8'
def ov(a, b, g): return min(a[2], b[2]) - max(a[0], b[0]) + g > 0 and min(a[3], b[3]) - max(a[1], b[1]) + g > 0
obs_e, obs_l, obs_z = [], [], []
for r, p in P1.items():
    if r == ref: continue
    e = list(p['cy']) if p['cy'] else None
    if e is None: continue
    if p['silk']: e = [min(e[0], p['silk'][0]), min(e[1], p['silk'][1]), max(e[2], p['silk'][2]), max(e[3], p['silk'][3])]
    obs_e.append(tuple(e))
    w, h = RP.LAB_W * len(r), RP.LAB_H
    if abs((p['tang'] % 180) - 90) < 1: w, h = h, w
    lb = (p['tx'] - w / 2, p['ty'] - h / 2, p['tx'] + w / 2, p['ty'] + h / 2)
    obs_l.append(lb); obs_z.append((lb[0] - 0.3, lb[1] - 0.3, lb[2] + 0.3, lb[3] + 0.3))
pin8 = [q['c'] for q in P1[ic]['pads'] if q['n'] == pin][0]
pads_all = [q['c'] for q in P1[ic]['pads']]
cur = (P1[ref]['x'], P1[ref]['y'])
print('now', cur, 'rot', P1[ref]['rot'], 'pin8', pin8)
res = []
reg = [rc for rc in RP.REGIONS['REFCAL']]
mext, mlab = RP.Mask(reg, 0.2), RP.Mask(reg, 0.4)
for k in range(4):
    c, s_ = RP.COS[k], RP.SIN[k]
    pads = [(q['c'][0] - P0[ref]['x'], q['c'][1] - P0[ref]['y']) for q in P0[ref]['pads']]
    pads = [(o[0]*c - o[1]*s_, o[0]*s_ + o[1]*c) for o in pads]
    o1 = pads[[q['n'] for q in P0[ref]['pads']].index('1')]
    for ls in (0, 2, 4):
        g = RP.part_geom(P0[ref], k, ls)
        for x in np.arange(cur[0] - 6, cur[0] + 6, 0.05):
            for y in np.arange(cur[1] - 6, cur[1] + 6, 0.05):
                x = round(float(x), 2); y = round(float(y), 2)
                d = math.hypot(x + o1[0] - pin8[0], y + o1[1] - pin8[1])
                if d > 2.79: continue
                online = any(abs(x - px) < 0.026 or abs(y - py) < 0.026 for px, py in pads_all) and min(math.hypot(x - px, y - py) for px, py in pads_all) <= 4.0
                e = (g['ext'][0]+x, g['ext'][1]+y, g['ext'][2]+x, g['ext'][3]+y); z = (g['zone'][0]+x, g['zone'][1]+y, g['zone'][2]+x, g['zone'][3]+y); lb = (g['lab'][0]+x, g['lab'][1]+y, g['lab'][2]+x, g['lab'][3]+y)
                if mext.bad(e) > 0 or mlab.bad(lb) > 0: continue
                if any(ov(e, o, 0.02) for o in obs_e) or any(ov(z, o, 0) for o in obs_e) or any(ov(lb, o, 0.5) for o in obs_l) or any(ov(e, o, 0.0) for o in obs_z): continue
                res.append((0 if online else 1, d, ref, k, ls, x, y))
res.sort()
print(len(res)); print(res[:8])
