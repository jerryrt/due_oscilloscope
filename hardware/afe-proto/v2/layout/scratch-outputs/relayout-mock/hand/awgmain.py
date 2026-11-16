import sys
sys.path.insert(0,'/work/hardware/afe-proto')
from pcbtools import boardio
import numpy as np
b=boardio.read_board(sys.argv[1])
n=b.nets.index('/AWG_FB')
print([ (b.fp_ref[int(b.p_fp[i])],b.p_pin[i],round(float(b.p_x[i]),3),round(float(b.p_y[i]),3)) for i in range(len(b.p_x)) if b.p_net[i]==n])
L=0
for i in np.flatnonzero(b.s_net==n):
    print((round(float(b.s_x0[i]),3),round(float(b.s_y0[i]),3),round(float(b.s_x1[i]),3),round(float(b.s_y1[i]),3),float(b.s_w[i]),int(b.s_layer[i])))
    L+=np.hypot(b.s_x1[i]-b.s_x0[i],b.s_y1[i]-b.s_y0[i])
print('len',L,'vias',int((b.v_net==n).sum()))
