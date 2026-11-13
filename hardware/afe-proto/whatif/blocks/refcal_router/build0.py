"""stage 0: merge4 + REFCAL part poses from a given pose board"""
import sys
from pcbtools import boardio
from pcbtools.editor import edit
src, poses, out = sys.argv[1:4]
p = boardio.read_board(poses)
skip = {'R515', 'R516'}
with edit(src, out) as e:
    for i, r in enumerate(p.fp_ref):
        d = ''.join(c for c in r if c.isdigit())
        if len(d) == 3 and d[0] == '5' and r not in skip:
            e.move(r, float(p.fp_x[i]), float(p.fp_y[i]), float(p.fp_rot[i]))
print('ok')
