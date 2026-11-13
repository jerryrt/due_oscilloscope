import sys
from pcbtools import boardio
b = boardio.read_board(sys.argv[1])
for i in range(len(b.s_x0)):
    n=b.nets[b.s_net[i]]
    if n in sys.argv[2:]: print(n, b.s_x0[i],b.s_y0[i],b.s_x1[i],b.s_y1[i],b.s_w[i])
