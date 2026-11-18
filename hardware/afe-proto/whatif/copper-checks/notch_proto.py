import sys
sys.path[:0] = ['../../../pcbkit', '../..']
import numpy as np
from scipy import ndimage as ndi
from pcbkit import board as kb, fills, rules
b = kb.read_board(sys.argv[1], {'FRAME': (50.0, 150.0)})
gnd = rules.nid(b, '/GND')
r = fills.net_copper(b, 0, gnd, 40.0, with_net_items=False)
lab, n = fills.notches(b, r, 0, gnd, float(sys.argv[2]) if len(sys.argv) > 2 else 1.05, 0.3, 0.15, 0.1)
print('notches', n)
for i in range(1, n + 1):
    rr, cc = np.nonzero(lab == i)
    x, y = r.to_mm((int(rr.mean()), int(cc.mean())))
    print('  at (%.2f, %.2f) area %.2f mm2' % (x, y, (lab == i).sum() / r.ppmm ** 2))
