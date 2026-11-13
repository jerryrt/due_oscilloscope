"""fin_b.py IN OUT : hand-route the north exits (SCL1, SDA1, AREF, P33_RN) inside the fence, own via for D501.1 / D502.1"""
import sys
import numpy as np
from pcbtools import boardio
from pcbtools.editor import edit
src, out = sys.argv[1:3]
F = (44.5, 4.6, 64.5, 36.0)
b = boardio.read_board(src)
kill = []
for i in range(len(b.s_idx)):
    n = b.nets[b.s_net[i]].lstrip('/')
    y0, y1 = b.s_y0[i], b.s_y1[i]
    if n in ('SCL1', 'SDA1', 'AREF', 'P33_RN') and max(y0, y1) <= F[3] + 1e-6 and min(b.s_x0[i], b.s_x1[i]) >= F[0] - 1e-6:
        kill.append(int(b.s_idx[i]))
print('removing', len(kill), 'tracks of the four north nets')
with edit(src, out) as e:
    e.remove_tracks(kill)
    W = 0.2
    def poly(net, w, pts):
        for a, c in zip(pts, pts[1:]):
            e.add_tracks(net, 'F', a[0], a[1], c[0], c[1], w)
    poly('SCL1', W, [(54.0, 29.22), (54.0, 30.4), (53.4, 31.0), (47.0, 31.0), (46.4, 31.6), (46.4, 36.0)])
    poly('SDA1', W, [(55.6, 29.22), (55.6, 31.4), (54.4, 32.6), (48.0, 32.6), (47.4, 33.2), (47.4, 36.0)])
    poly('AREF', W, [(57.3, 30.05), (57.3, 33.6), (56.7, 34.2), (49.0, 34.2), (48.4, 34.8), (48.4, 36.0)])
    poly('P33_RN', 0.3, [(56.0, 36.0), (56.0, 35.2), (58.0, 35.2), (59.2, 34.0), (59.2, 29.6)])
print('done')
