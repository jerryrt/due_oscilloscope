import sys
sys.path.insert(0,'/work/hardware/afe-proto')
from pcbtools import boardio
import numpy as np
b=boardio.read_board(sys.argv[1])
G=[('/CH1_N','/CH1_NP','/CH1_IN'),('/CH2_N','/CH2_NP','/CH2_IN')]
P=[[(b.fp_ref[int(b.p_fp[i])]+'.'+b.p_pin[i],float(b.p_x[i]),float(b.p_y[i])) for i in range(len(b.p_x)) if b.nets[int(b.p_net[i])] in g and b.p_x[i]<91.0] for g in G]
best=sorted((np.hypot(a[1]-c[1],a[2]-c[2]),a[0],c[0]) for a in P[0] for c in P[1])[:4]
print([(round(d,4),x,y) for d,x,y in best])
