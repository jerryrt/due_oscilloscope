import sys, math, os
sys.path.insert(0, 'whatif/_scratch')
import numpy as np
import route_lib as R
SRC = 'whatif/_scratch/route2/signals3.kicad_pcb'
JOBS = [('/VREF_P', 'R516', '2', ('R204', '2')), ('/CH2_IN', 'R202', '1', None)]
B = R.Board(SRC); b = B.b
B.relax = {'hiz'}
H0 = (R.H, R.X0, R.Y0, R.X1, R.Y1, R.NX, R.NY, R.GX, R.GY)
for net, ref, pin, tgt in JOBS:
    j = [k for k in range(len(b.p_fp)) if b.fp_ref[int(b.p_fp[k])] == ref and str(b.p_pin[k]) == pin][0]
    nid = b.nets.index(net)
    others = [k for k in range(len(b.p_fp)) if int(b.p_net[k]) == nid and k != j]
    if tgt: others = [k for k in others if (b.fp_ref[int(b.p_fp[k])], str(b.p_pin[k])) == tgt]
    k2 = min(others, key=lambda k: math.hypot(b.p_x[k] - b.p_x[j], b.p_y[k] - b.p_y[j]))
    cx = (b.p_x[j] + b.p_x[k2]) / 2; cy = (b.p_y[j] + b.p_y[k2]) / 2; r = max(6.0, math.hypot(b.p_x[j] - b.p_x[k2], b.p_y[j] - b.p_y[k2]) / 2 + 3)
    R.H = 0.05; R.X0 = cx - r; R.Y0 = cy - r; R.X1 = cx + r; R.Y1 = cy + r
    R.NX = int((R.X1 - R.X0) / .05) + 1; R.NY = int((R.Y1 - R.Y0) / .05) + 1; R.GX = R.X0 + .05 * np.arange(R.NX); R.GY = R.Y0 + .05 * np.arange(R.NY)
    segs, vs, fails = B.route(net, pads_subset={j, k2}, width=0.2, tag='fine')
    (R.H, R.X0, R.Y0, R.X1, R.Y1, R.NX, R.NY, R.GX, R.GY) = H0
    print(ref, pin, '->', 'ROUTES len %.1f' % sum(math.hypot(s[3][0]-s[2][0], s[3][1]-s[2][1]) for s in segs) if not fails else 'fails', flush=True)
    if not fails: B.add(segs, vs)
B.save('whatif/_scratch/route2/c.kicad_pcb')
