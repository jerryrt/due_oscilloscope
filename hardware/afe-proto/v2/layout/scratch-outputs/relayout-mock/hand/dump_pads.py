import sys, json
sys.path.insert(0, '/work/hardware/afe-proto')
from pcbtools import boardio
b = boardio.read_board(sys.argv[1])
out = []
for i in range(len(b.p_x)):
    out.append(dict(ref=b.fp_ref[int(b.p_fp[i])], pin=b.p_pin[i], net=b.nets[int(b.p_net[i])], x=round(float(b.p_x[i]), 3), y=round(float(b.p_y[i]), 3),
                    bb=[round(float(v), 3) for v in (b.p_bx0[i], b.p_by0[i], b.p_bx1[i], b.p_by1[i])], smd=bool(b.p_smd[i])))
json.dump(out, open(sys.argv[2], 'w'))
print(len(out))
