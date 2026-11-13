import sys
from pcbtools import boardio
b = boardio.read_board(sys.argv[1])
byref = {}
for j in range(len(b.p_x)):
    r = b.fp_ref[b.p_fp[j]]; d=''.join(c for c in r if c.isdigit())
    if len(d)==3 and d[0]=='5':
        byref.setdefault(r, []).append((b.p_pin[j], b.nets[b.p_net[j]], round(b.p_x[j],2), round(b.p_y[j],2)))
for r in sorted(byref): print(r, b.fp_kind[b.fp_idx.tolist().index(b.fp_idx[list(b.fp_ref).index(r)])] , byref[r])
