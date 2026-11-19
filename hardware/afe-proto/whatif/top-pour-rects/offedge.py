import sys
sys.path[:0] = ["../pcbkit", "."]
import numpy as np
from pcbkit import board as kb
from pcbtools.frame import FRAME
b = kb.read_board(sys.argv[1], {"FRAME": FRAME})
x0, y0, x1, y1 = map(float, sys.argv[2:6])
g = [i for i, n in enumerate(b.nets) if n.lstrip('/') == 'GND'][0]
for z in range(len(b.z_layer)):
    if b.z_layer[z] == 0 and b.z_net[z] == g and not b.z_keepout[z]:
        for j in range(b.z_ring_off[z], b.z_ring_off[z + 1]):
            p = b.z_xy[b.z_vert_off[j]:b.z_vert_off[j + 1]]
            if p[:, 0].min() > x0 - .1 and p[:, 0].max() < x1 + .1 and not b.z_ring_hole[j] and p[:, 1].max() > y1 - 1:
                off = ~((abs(p[:, 0] - x0) < .01) | (abs(p[:, 0] - x1) < .01) | (abs(p[:, 1] - y0) < .01) | (abs(p[:, 1] - y1) < .01))
                print('ring', j, len(p), 'off-edge', int(off.sum()), 'area', abs(np.dot(p[:,0], np.roll(p[:,1],-1)) - np.dot(p[:,1], np.roll(p[:,0],-1)))/2)
                o = p[off]
                # cluster by y rounding
                print(sorted({(round(float(a)/2)*2, round(float(c)/2)*2) for a, c in o})[:40])
