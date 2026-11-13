import sys, numpy as np
from pcbtools import boardio
from pcbtools.boards import v1
b = boardio.read_board(sys.argv[1])
F = v1.FENCES['REFCAL'][0]
print('fence', F)
def inF(x,y): return F[0]<=x<=F[2] and F[1]<=y<=F[3]
print('--parts')
for i,r in enumerate(b.fp_ref):
    d=''.join(c for c in r if c.isdigit())
    if d.startswith('5') and len(d)==3: print(r, round(b.fp_x[i],2), round(b.fp_y[i],2), b.fp_rot[i], b.fp_side[i])
print('--tracks in fence')
for i in range(len(b.s_idx)):
    if inF(b.s_x0[i],b.s_y0[i]) or inF(b.s_x1[i],b.s_y1[i]):
        print(b.nets[b.s_net[i]], b.s_layer[i], round(b.s_x0[i],3),round(b.s_y0[i],3),round(b.s_x1[i],3),round(b.s_y1[i],3), b.s_w[i])
print('--vias in fence')
for i in range(len(b.v_idx)):
    if inF(b.v_x[i],b.v_y[i]): print(b.nets[b.v_net[i]], b.v_x[i], b.v_y[i])
