import sys
sys.path[:0] = ['hardware/pcbkit']
import numpy as np
from pcbkit import board as kb
for label, path in (('before', sys.argv[1]), ('after', sys.argv[2])):
    b = kb.read_board(path, {'FRAME': (50.0, 150.0)})
    pins = np.array(b.p_pin)
    rows = []
    for k in range(len(b.s_x0)):
        net = b.nets[int(b.s_net[k])].lstrip('/')
        if net in ('+5V_F', '+3V3A', 'VNEG', '+5V_DUE') and b.s_w[k] < 0.25 and b.s_layer[k] == 0:
            L = float(np.hypot(b.s_x1[k] - b.s_x0[k], b.s_y1[k] - b.s_y0[k]))
            pad = ''
            for e in ((b.s_x0[k], b.s_y0[k]), (b.s_x1[k], b.s_y1[k])):
                for i in range(len(b.p_x)):
                    if int(b.p_net[i]) == int(b.s_net[k]) and abs(e[0] - b.p_x[i]) <= b.p_sx[i] / 2 + 0.3 and abs(e[1] - b.p_y[i]) <= b.p_sy[i] / 2 + 0.3 and (b.p_layer_mask[i] & 1):
                        pad = '%s.%s' % (b.fp_ref[b.p_fp[i]], pins[i])
            rows.append((net, pad, round(L, 2), round(float(b.s_x0[k]), 2), round(float(b.s_y0[k]), 2)))
    print(label, len(rows))
    for r in sorted(rows):
        print('  ', r)
