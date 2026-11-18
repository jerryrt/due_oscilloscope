import sys
sys.path[:0] = ['hardware/pcbkit']
import numpy as np
from pcbkit import board as kb, fills
b = kb.read_board(sys.argv[1], {'FRAME': (50.0, 150.0)})
g = [i for i, n in enumerate(b.nets) if n.lstrip('/') == 'GND'][0]
rp = fills.net_copper(b, 0, g, 40.0, with_net_items=False, frame=(17.0, -4.5, 117.0, 57.84))
x0, y0, x1, y1 = [float(v) for v in sys.argv[2:6]]
pins = np.array(b.p_pin)
for i in range(len(b.p_x)):
    if x0 <= b.p_x[i] <= x1 and y0 <= b.p_y[i] <= y1 and b.p_layer_mask[i] & 1:
        print('pad', b.fp_ref[b.p_fp[i]], pins[i], round(float(b.p_x[i]), 3), round(float(b.p_y[i]), 3), round(float(b.p_sx[i]), 2), round(float(b.p_sy[i]), 2), b.nets[int(b.p_net[i])])
for i in range(len(b.v_x)):
    if x0 <= b.v_x[i] <= x1 and y0 <= b.v_y[i] <= y1:
        print('via', round(float(b.v_x[i]), 3), round(float(b.v_y[i]), 3), b.nets[int(b.v_net[i])])
tr = []
m = fills.rough_edges(b, rp, 0, g, 0.3, trace=tr)
for t in tr:
    k, box = t[0], t[1]
    if x0 <= box[0] <= x1 and y0 <= box[1] <= y1:
        print(k, [round(float(v), 2) for v in box], t[2:] )
print('mask px in window', m[int((rp.y1 - y1) * 40):int((rp.y1 - y0) * 40), int((x0 - rp.x0) * 40):int((x1 - rp.x0) * 40)].sum())
