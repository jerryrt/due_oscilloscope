"""stage2_gnd.py IN OUT: one GND via of its own within 3.0 mm of every SMD GND pad (LR-1), joined by a short top track; GND via 0.6/0.3."""
import sys, math, heapq
sys.path.insert(0, 'whatif/_scratch')
import numpy as np
from scipy import ndimage
import route_lib as R
from pcbtools.boards import v1 as C
src, dst = sys.argv[1], sys.argv[2]
B = R.Board(src); b = B.b
gid = b.nets.index('/GND')
pads = [j for j in range(len(b.p_fp)) if int(b.p_net[j]) == gid and bool(b.p_smd[j])]
pads.sort(key=lambda j: (b.fp_ref[int(b.p_fp[j])], str(b.p_pin[j])))
print('SMD GND pads', len(pads), flush=True)
H = R.H; fails = []
DIRS = [(1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0), (1, 1, 1.414), (1, -1, 1.414), (-1, 1, 1.414), (-1, -1, 1.414)]
for n, j in enumerate(pads):
    masks = B.copper_masks(gid, B.tracks, B.vias, tag=None, pad_subset={j})
    d0 = ndimage.distance_transform_edt(~masks[0]) * H
    d1 = ndimage.distance_transform_edt(~masks[1]) * H
    trk_ok = d0 >= R.CLR + 0.1 + 0.03
    via_ok = (d0 >= R.CLR + R.VIA_D / 2 + 0.03) & (d1 >= R.CLR + R.VIA_D / 2 + 0.03)
    # no bottom keep-outs are needed for a GND via, but keep vias out of analog-part courtyard bottoms? (a via is not a bottom track: LR-1 counts tracks)
    px, py = float(b.p_x[j]), float(b.p_y[j])
    pc = [(int(round((px - R.X0) / H)), int(round((py - R.Y0) / H)))]
    x0, y0, x1, y1 = b.p_bx0[j], b.p_by0[j], b.p_bx1[j], b.p_by1[j]
    start = [(i, k) for i in range(max(0, int((x0 - R.X0) / H)), min(R.NX, int((x1 - R.X0) / H) + 2)) for k in range(max(0, int((y0 - R.Y0) / H)), min(R.NY, int((y1 - R.Y0) / H) + 2)) if x0 <= R.GX[i] <= x1 and y0 <= R.GY[k] <= y1] or pc
    best = {s: 0.0 for s in start}; prev = {}; pq = [(0.0, s) for s in start]; heapq.heapify(pq); goal = None
    while pq:
        g, c = heapq.heappop(pq)
        if g > best.get(c, 1e18) + 1e-9: continue
        if c not in start and via_ok[c] and math.hypot(R.GX[c[0]] - px, R.GY[c[1]] - py) <= 2.98:
            goal = c; break
        if g > 4.0: break
        for di, dk, w in DIRS:
            nb = (c[0] + di, c[1] + dk)
            if not (0 <= nb[0] < R.NX and 0 <= nb[1] < R.NY): continue
            if not trk_ok[nb] and nb not in start: continue
            ng = g + w * H
            if ng < best.get(nb, 1e18) - 1e-9:
                best[nb] = ng; prev[nb] = c; heapq.heappush(pq, (ng, nb))
    ref = '%s.%s' % (b.fp_ref[int(b.p_fp[j])], b.p_pin[j])
    if goal is None:
        fails.append(ref); print('GNDVIA none', ref, flush=True); continue
    path = [goal]
    while path[-1] in prev: path.append(prev[path[-1]])
    pts = [(float(R.GX[i]), float(R.GY[k])) for i, k in path[::-1]]
    # simplify collinear
    out = [pts[0]]
    for a, c, d in zip(pts, pts[1:], pts[2:]):
        if abs((c[0] - a[0]) * (d[1] - c[1]) - (c[1] - a[1]) * (d[0] - c[0])) > 1e-9: out.append(c)
    out.append(pts[-1])
    segs = [('/GND', 0, a, c, 0.2, 'gnd') for a, c in zip(out, out[1:]) if a != c]
    B.add(segs, [('/GND', pts[-1][0], pts[-1][1], 'gnd')])
print('GND vias placed', len(pads) - len(fails), 'failed', fails)
B.save(dst)
