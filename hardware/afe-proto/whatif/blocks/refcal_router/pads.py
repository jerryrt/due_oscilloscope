import sys
from pcbtools import boardio
b = boardio.read_board(sys.argv[1]); want = set(sys.argv[2:])
for j in range(len(b.p_x)):
    r = b.fp_ref[b.p_fp[j]]
    if r in want: print(r, b.p_pin[j], b.nets[b.p_net[j]], 'c=(%.3f,%.3f) bbox x %.3f..%.3f y %.3f..%.3f' % (b.p_x[j], b.p_y[j], b.p_bx0[j], b.p_bx1[j], b.p_by0[j], b.p_by1[j]))
