import sys
sys.path[:0] = ["../pcbkit", "."]
import numpy as np
from pcbkit import board as kb
from pcbtools.frame import FRAME
path = sys.argv[1]; x0, y0, x1, y1 = map(float, sys.argv[2:6])      # Due mm window
b = kb.read_board(path, {"FRAME": FRAME})
g = [i for i, n in enumerate(b.nets) if n.lstrip('/') == 'GND'][0]
def inw(a0, b0, a1, b1): return a1 >= x0 and a0 <= x1 and b1 >= y0 and b0 <= y1
print('pads (top):')
for i in range(len(b.p_x)):
    if (b.p_layer_mask[i] & 1) and inw(b.p_bx0[i], b.p_by0[i], b.p_bx1[i], b.p_by1[i]):
        print('  %s.%s net=%s box=(%.2f,%.2f,%.2f,%.2f) %s' % (b.fp_ref[b.p_fp[i]], b.p_pin[i], b.nets[b.p_net[i]], b.p_bx0[i], b.p_by0[i], b.p_bx1[i], b.p_by1[i], 'smd' if b.p_smd[i] else 'th'))
print('tracks (top):')
for k in range(len(b.s_x0)):
    if b.s_layer[k] == 0 and inw(min(b.s_x0[k], b.s_x1[k]), min(b.s_y0[k], b.s_y1[k]), max(b.s_x0[k], b.s_x1[k]), max(b.s_y0[k], b.s_y1[k])):
        print('  %s (%.2f,%.2f)-(%.2f,%.2f) w=%.2f' % (b.nets[b.s_net[k]], b.s_x0[k], b.s_y0[k], b.s_x1[k], b.s_y1[k], b.s_w[k]))
print('vias:')
for i in range(len(b.v_x)):
    if inw(b.v_x[i], b.v_y[i], b.v_x[i], b.v_y[i]):
        print('  %s (%.2f,%.2f) d=%.2f' % (b.nets[b.v_net[i]], b.v_x[i], b.v_y[i], b.v_dia[i]))
