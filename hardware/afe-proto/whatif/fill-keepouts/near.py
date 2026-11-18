import sys, math
sys.path[:0] = ['hardware/pcbkit']
import numpy as np
from pcbkit import board as kb
b = kb.read_board(sys.argv[1], {'FRAME': (50.0, 150.0)})
pins = np.array(b.p_pin)
pts = [tuple(map(float, a.split(','))) for a in sys.argv[2:]]
for (x, y) in pts:
    best = []
    for i in range(len(b.p_x)):
        dx = max(b.p_bx0[i] - x, x - b.p_bx1[i], 0); dy = max(b.p_by0[i] - y, y - b.p_by1[i], 0)
        best.append((math.hypot(dx, dy), '%s.%s %s' % (b.fp_ref[b.p_fp[i]], pins[i], b.nets[int(b.p_net[i])])))
    best.sort()
    segs = []
    for k in range(len(b.s_x0)):
        if math.hypot(b.s_x0[k] - x, b.s_y0[k] - y) < 0.01 or math.hypot(b.s_x1[k] - x, b.s_y1[k] - y) < 0.01:
            segs.append('seg %d %s (%.2f,%.2f)-(%.2f,%.2f) w%.2f' % (int(b.s_idx[k]), b.nets[int(b.s_net[k])], b.s_x0[k], b.s_y0[k], b.s_x1[k], b.s_y1[k], b.s_w[k]))
    print((x, y), best[:2], segs)
