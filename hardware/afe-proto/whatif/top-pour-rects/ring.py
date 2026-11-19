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
            q = p[(p[:, 0] >= x0) & (p[:, 0] <= x1) & (p[:, 1] >= y0) & (p[:, 1] <= y1)]
            if len(q): print('zone', z, 'hole' if b.z_ring_hole[j] else 'outer', len(p), 'verts in window:', len(q)); print(np.round(q[:40], 3).tolist())
