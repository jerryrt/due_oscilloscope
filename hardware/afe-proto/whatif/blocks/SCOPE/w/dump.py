import sys
from pcbtools import boardio
b = boardio.read_board(sys.argv[1])
import numpy as np
fx=lambda r: r[0] in '12' and r[1:2].isdigit() or r.startswith(('J1','J2'))
for i,r in enumerate(b.fp_ref):
    if (r[1:2] in ('1','2') and len(r)==4 and r[0] in 'RCDUJ'):
        print(r, round(b.fp_x[i],2), round(b.fp_y[i],2), b.fp_rot[i], b.fp_side[i], b.fp_kind[i].split(':')[-1], 'cy', [round(float(v),2) for v in (b.fp_cx0[i],b.fp_cy0[i],b.fp_cx1[i],b.fp_cy1[i])])
        for j in np.where(b.p_fp==i)[0]:
            print('    pad',b.p_pin[j], round(b.p_x[j],2), round(b.p_y[j],2), b.nets[b.p_net[j]], 'smd' if b.p_smd[j] else 'th', round(b.p_sx[j],2), round(b.p_sy[j],2), b.p_rot[j])
print(len(b.s_x0), 'tracks', len(b.v_x), 'vias')
