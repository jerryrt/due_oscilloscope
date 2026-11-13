import sys
from pcbtools import boardio
b = boardio.read_board(sys.argv[1])
for i in range(len(b.s_x0)):
    if b.s_x0[i]>92 or b.s_x1[i]>92: print(b.nets[b.s_net[i]], b.s_x0[i],b.s_y0[i],b.s_x1[i],b.s_y1[i],b.s_w[i],b.s_layer[i])
print(len(b.s_x0),len(b.v_x))
for k in ('s_w',): 
    import numpy as np; print(sorted(set(b.s_w.tolist())), sorted(set(b.v_dia.tolist())))
