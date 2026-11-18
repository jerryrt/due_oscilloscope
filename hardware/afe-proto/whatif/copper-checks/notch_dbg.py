import sys
sys.path[:0] = ['../../../pcbkit', '../..']
import numpy as np
from scipy import ndimage as ndi
from pcbkit import board as kb, fills, rules
b = kb.read_board(sys.argv[1], {'FRAME': (50.0, 150.0)})
gnd = rules.nid(b, '/GND')
r = fills.net_copper(b, 0, gnd, 40.0, with_net_items=False)
k = r.ppmm
def px(x, y): return int((r.y1 - y) * k), int((x - r.x0) * k)
for (x, y) in [(22.5, 17.1), (22.5, 16.8), (22.5, 17.5), (22.2, 17.2), (22.8, 17.0)]:
    rr, cc = px(x, y)
    print((x, y), 'pour', bool(r.mask[rr, cc]))
rad = int(round(0.48 * k)); yy, xx = np.mgrid[-rad:rad + 1, -rad:rad + 1]; disk = (xx**2 + yy**2) <= rad**2
closed = ndi.binary_closing(np.pad(r.mask, rad + 2), structure=disk)[rad + 2:-(rad + 2), rad + 2:-(rad + 2)]
fc = fills.foreign_copper(b, r, 0, gnd)
d = ndi.distance_transform_edt(~fc) / k
for (x, y) in [(22.5, 17.1), (22.5, 16.8), (22.5, 17.5)]:
    rr, cc = px(x, y); print((x, y), 'closed-fills', bool(closed[rr, cc] and not r.mask[rr, cc]), 'dist to foreign copper %.2f' % d[rr, cc])
print('column x=22.5 pour by y:', ''.join('#' if r.mask[px(22.5, 19 - 0.1 * j)[0], px(22.5, 19)[1]] else '.' for j in range(0, 80)))
print('row y=17.1 pour by x:', ''.join('#' if r.mask[px(0, 17.1)[0], px(19 + 0.1 * j, 17.1)[1]] else '.' for j in range(0, 120)))
print(len(b.z_layer), [ (int(b.z_layer[z]), int(b.z_net[z]), bool(b.z_filled[z]), bool(b.z_keepout[z])) for z in range(len(b.z_layer)) if b.z_layer[z]==0][:6])
gap = closed & ~r.mask
lab, n = ndi.label(gap, structure=np.ones((3, 3)))
for i in range(1, n + 1):
    rr, cc = np.nonzero(lab == i)
    x, y = r.to_mm((int(rr.mean()), int(cc.mean())))
    if 22 < x < 25.5 and 15 < y < 19:
        m = lab == i
        print('gap comp at (%.2f,%.2f) area %.2f mm2, share within clearance+tol of foreign copper %.2f' % (x, y, m.sum() / k / k, (d[m] <= 0.45).mean()))
print('map x 21..28 (cols 0.1mm) y 19..14 (rows)')
for j in range(0, 50, 2):
    y = 19 - 0.1 * j
    print('%.1f ' % y + ''.join('#' if r.mask[px(0, y)[0], px(21 + 0.1 * i, y)[1]] else ('c' if closed[px(0, y)[0], px(21 + 0.1 * i, y)[1]] else '.') for i in range(0, 70)))
