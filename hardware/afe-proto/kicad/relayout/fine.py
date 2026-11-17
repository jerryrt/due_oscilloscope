import sys, math, os
sys.path.insert(0, 'whatif/_scratch')
import numpy as np
import route_lib as R
from pcbtools.boards import v1 as C
SRC = 'whatif/_scratch/route2/signals3.kicad_pcb'
JOBS = [('/VREF', 'R512', '2', ('R515', '1')), ('/+3V3A', 'C407', '1', ('C408', '1')), ('/VNEG', 'U401', '6', ('C410', '1')), ('/VNEG', 'C409', '1', ('C410', '1')), ('/VREF_P', 'R516', '2', None), ('/SNS_BI', 'D501', '3', None)]
HS = float(os.environ.get('HS', '0.05'))
def window(cx, cy, r):
    R.H = HS; R.X0 = cx - r; R.Y0 = cy - r; R.X1 = cx + r; R.Y1 = cy + r
    R.NX = int((R.X1 - R.X0) / HS) + 1; R.NY = int((R.Y1 - R.Y0) / HS) + 1
    R.GX = R.X0 + HS * np.arange(R.NX); R.GY = R.Y0 + HS * np.arange(R.NY)
for net, ref, pin, tgt in JOBS:
    B = R.Board(SRC); b = B.b
    j = [k for k in range(len(b.p_fp)) if b.fp_ref[int(b.p_fp[k])] == ref and str(b.p_pin[k]) == pin][0]
    nid = b.nets.index(net)
    others = [k for k in range(len(b.p_fp)) if int(b.p_net[k]) == nid and k != j]
    if tgt: others = [k for k in others if (b.fp_ref[int(b.p_fp[k])], str(b.p_pin[k])) == tgt]
    k2 = min(others, key=lambda k: math.hypot(b.p_x[k] - b.p_x[j], b.p_y[k] - b.p_y[j]))
    cx = (b.p_x[j] + b.p_x[k2]) / 2; cy = (b.p_y[j] + b.p_y[k2]) / 2
    r = max(6.0, math.hypot(b.p_x[j] - b.p_x[k2], b.p_y[j] - b.p_y[k2]) / 2 + 3)
    window(cx, cy, r)
    for kw in (dict(width=0.2), dict(width=0.2, vias=True, bottom=True), dict(width=0.2, extra_margin=-0.03), dict(width=0.15), dict(width=0.15, extra_margin=-0.03)):
        segs, vs, fails = B.route(net, pads_subset={j, k2}, tag='fine', **kw)
        print(ref, pin, net, kw, 'ROUTES' if not fails else 'fails', 'len %.1f vias %d' % (sum(math.hypot(s[3][0]-s[2][0], s[3][1]-s[2][1]) for s in segs), len(vs)), flush=True)
        if not fails: break
