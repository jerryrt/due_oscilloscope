import sys
sys.path.insert(0,'/work/hardware/afe-proto')
from pcbtools import boardio
import numpy as np
b=boardio.read_board(sys.argv[1])
for n in ('/CH1_N','/CH1_M1','/CH1_M2','/CH1_M3','/CH1_NP','/CH2_N','/CH2_M1','/CH2_M2','/CH2_M3','/CH2_NP'):
    i=b.nets.index(n); m=b.s_net==i
    L=float(np.hypot(b.s_x1[m]-b.s_x0[m],b.s_y1[m]-b.s_y0[m]).sum())
    pp=[(b.fp_ref[int(b.p_fp[k])]+'.'+b.p_pin[k],round(float(b.p_x[k]),1),round(float(b.p_y[k]),1)) for k in range(len(b.p_x)) if b.p_net[k]==i]
    xs=[p[1] for p in pp]; ys=[p[2] for p in pp]
    print(n,'track',round(L,1),'pads',len(pp),'bbox',round(max(xs)-min(xs),1),'x',round(max(ys)-min(ys),1), 'HPWL',round(max(xs)-min(xs)+max(ys)-min(ys),1))
