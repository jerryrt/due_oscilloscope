import sys, importlib
sys.path[:0] = ['hardware/afe-proto', 'hardware/pcbkit']
from pcbtools import fill_clean as fc
from pcbkit import fills
cfg = importlib.import_module('pcbtools.boards.v1_layout')
outl = [tuple(r) for rs in cfg.OUTLINE.values() for r in rs]
path = 'hardware/afe-proto/kicad/afe-proto.kicad_pcb'
tmp = path + '.p.tmp.kicad_pcb'
keeps = fc.derive_keeps(path, 0.2, 0.3, 0.3, 0.3, 1.0, 0.5, outl, 1.0)
r, b, g, rp = fc._fill_to(path, tmp, keeps, 1.0, 0.3, 0.3, 0.3)
tr = []
m = fills.rough_edges(b, rp, 0, g, 0.3, trace=tr)
print('mask px', m.sum())
for k, box in tr:
    if 17 <= box[0] <= 27 and 2 <= box[1] <= 12:
        print('hug', [round(float(v), 2) for v in box])
print('rough mask in region', m[int((rp.y1 - 10) * 40):int((rp.y1 - 3) * 40), int((18 - rp.x0) * 40):int((25 - rp.x0) * 40)].sum())
# items near the region whether other net, and distance to pour
import numpy as np
for i in range(len(b.p_x)):
    if 17 <= b.p_x[i] <= 27 and 2 <= b.p_y[i] <= 12:
        print('pad', b.fp_ref[b.p_fp[i]], b.p_pin[i], round(float(b.p_x[i]), 2), round(float(b.p_y[i]), 2), b.nets[int(b.p_net[i])])
for i in range(len(b.v_x)):
    if 17 <= b.v_x[i] <= 27 and 2 <= b.v_y[i] <= 12:
        print('via', round(float(b.v_x[i]), 2), round(float(b.v_y[i]), 2), b.nets[int(b.v_net[i])])
