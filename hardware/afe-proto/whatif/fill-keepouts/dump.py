"""dump.py BOARD X0 Y0 X1 Y1: pads (centre, size, rotation, net), vias and F.Cu segments (with indices) in a Due-mm window"""
import sys
sys.path[:0] = ['hardware/pcbkit']
import numpy as np
from pcbkit import board as kb
b = kb.read_board(sys.argv[1], {'FRAME': (50.0, 150.0)})
x0, y0, x1, y1 = map(float, sys.argv[2:6])
pins = np.array(b.p_pin)
for i in range(len(b.p_x)):
    if x0 <= b.p_x[i] <= x1 and y0 <= b.p_y[i] <= y1 and b.p_layer_mask[i] & 1:
        print('pad  %-5s %-3s (%.3f, %.3f) %.2fx%.2f rot %g %s' % (b.fp_ref[b.p_fp[i]], pins[i], b.p_x[i], b.p_y[i], b.p_sx[i], b.p_sy[i], b.p_rot[i], b.nets[int(b.p_net[i])]))
for i in range(len(b.v_x)):
    if x0 <= b.v_x[i] <= x1 and y0 <= b.v_y[i] <= y1:
        print('via  (%.3f, %.3f) %s' % (b.v_x[i], b.v_y[i], b.nets[int(b.v_net[i])]))
for k in range(len(b.s_x0)):
    if b.s_layer[k] == 0 and ((x0 <= b.s_x0[k] <= x1 and y0 <= b.s_y0[k] <= y1) or (x0 <= b.s_x1[k] <= x1 and y0 <= b.s_y1[k] <= y1)):
        print('seg %4d %-8s (%.3f, %.3f)-(%.3f, %.3f) w%.2f' % (int(b.s_idx[k]), b.nets[int(b.s_net[k])], b.s_x0[k], b.s_y0[k], b.s_x1[k], b.s_y1[k], b.s_w[k]))
