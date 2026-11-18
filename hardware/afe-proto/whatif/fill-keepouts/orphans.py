import sys
sys.path[:0] = ['hardware/pcbkit']
import numpy as np
from pcbkit import board as kb
for path in sys.argv[1:]:
    b = kb.read_board(path, {'FRAME': (50.0, 150.0)})
    n = 0
    for i in range(len(b.v_x)):
        x, y, r = b.v_x[i], b.v_y[i], b.v_dia[i] / 2
        tr = np.any(((np.hypot(b.s_x0 - x, b.s_y0 - y) <= r + b.s_w / 2 + 0.01) | (np.hypot(b.s_x1 - x, b.s_y1 - y) <= r + b.s_w / 2 + 0.01)))
        pd = np.any((b.p_bx0 - r <= x) & (x <= b.p_bx1 + r) & (b.p_by0 - r <= y) & (y <= b.p_by1 + r))
        if not tr and not pd:
            n += 1
    print(path, 'vias', len(b.v_x), 'orphans', n)
