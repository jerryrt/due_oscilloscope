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
comp = ~np.pad(r.mask, 1, constant_values=True)[1:-1, 1:-1]
opened, edt = fills._opened(np.pad(comp, 4, constant_values=True), 0.48 * k)
opened = opened[4:-4, 4:-4]
gap = comp & ~opened
fc = fills.foreign_copper(b, r, 0, gnd)
d = ndi.distance_transform_edt(~fc) / k
print('fc pixels', int(fc.sum()))
for j in range(0, 50, 2):
    y = 19 - 0.1 * j
    print('%.1f ' % y + ''.join('#' if r.mask[px(0, y)[0], px(21 + 0.1 * i, y)[1]] else ('g' if gap[px(0, y)[0], px(21 + 0.1 * i, y)[1]] else ('f' if fc[px(0, y)[0], px(21 + 0.1 * i, y)[1]] else '.')) for i in range(0, 70)))
rr, cc = px(23.5, 17.1); print('dist foreign at bite %.2f' % d[rr, cc])
for y in (17.5, 17.3, 17.1, 16.9):
    row = r.mask[px(0, y)[0], :]
    cols = np.flatnonzero(~row[px(0, 0)[1] + int((22.5 - r.x0) * k) - int((0 - r.x0) * k) - 0: ]) if False else None
    rowv = row[px(21, y)[1]:px(26, y)[1]]
    idx = np.flatnonzero(~rowv)
    print('y', y, 'gap px', idx.min() if len(idx) else None, idx.max() if len(idx) else None, 'width mm', (idx.max() - idx.min() + 1) / k if len(idx) else None)
