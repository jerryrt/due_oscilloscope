import sys, numpy as np
sys.path[:0] = ['../pcbkit', '.']
from pcbkit import board as kb
from pcbtools.frame import FRAME
from pcbtools.boards import v1_layout, v2_layout
path, cfg = sys.argv[1], sys.argv[2]
rects = {'v1': v1_layout, 'v2': v2_layout}[cfg].TOP_POUR_RECTS
b = kb.read_board(path, {'FRAME': FRAME})
g = [i for i, n in enumerate(b.nets) if n.lstrip('/') == 'GND'][0]
for k in range(len(b.z_layer)):
    if b.z_layer[k] == 0 and b.z_net[k] == g and not b.z_keepout[k]:
        rings = [b.z_xy[b.z_vert_off[j]:b.z_vert_off[j + 1]] for j in range(b.z_ring_off[k], b.z_ring_off[k + 1])]
        print('zone', k, 'filled', b.z_filled[k], 'rings', len(rings), 'verts', [len(r) for r in rings][:8], 'bbox', rings[0].min(0).round(3), rings[0].max(0).round(3))
for r in rects:
    x0, y0, x1, y1 = r[0] - 50, 150 - r[3], r[2] - 50, 150 - r[1]
    v = [(round(float(b.v_x[i]), 2), round(float(b.v_y[i]), 2)) for i in range(len(b.v_x)) if b.v_net[i] == g and x0 <= b.v_x[i] <= x1 and y0 <= b.v_y[i] <= y1]
    print('rect', r, 'GND vias inside', len(v))
