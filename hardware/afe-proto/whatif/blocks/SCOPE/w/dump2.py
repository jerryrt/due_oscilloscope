import sys
from pcbtools import boardio
import numpy as np
b = boardio.read_board(sys.argv[1])
for i,r in enumerate(b.fp_ref):
    if r in sys.argv[2:]:
        print(r, round(b.fp_x[i],2), round(b.fp_y[i],2), b.fp_rot[i], b.fp_kind[i].split(':')[-1], [round(float(v),2) for v in (b.fp_cx0[i],b.fp_cy0[i],b.fp_cx1[i],b.fp_cy1[i])])
        for j in np.where(b.p_fp==i)[0]:
            if r!='J607' or j%7==0: print('    pad',b.p_pin[j], round(b.p_x[j],2), round(b.p_y[j],2), b.nets[b.p_net[j]], round(b.p_sx[j],2), round(b.p_sy[j],2))
