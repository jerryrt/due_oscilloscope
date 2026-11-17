import sys, math, numpy as np
from pcbtools import boardio
b = boardio.read_board(sys.argv[1]); tx, ty, R = float(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4])
# obstacles on top: courtyards of parts (grown 0.1), top tracks (w/2 + 0.25), vias
def courtyard_hit(x0, y0, x1, y1):
    for k in range(len(b.fp_ref)):
        if np.isnan(b.fp_cx0[k]): continue
        if x1 > b.fp_cx0[k] - 0.1 and x0 < b.fp_cx1[k] + 0.1 and y1 > b.fp_cy0[k] - 0.1 and y0 < b.fp_cy1[k] + 0.1: return True
    return False
def trk_hit(x0, y0, x1, y1):
    for k in range(len(b.s_idx)):
        if int(b.s_layer[k]) != 0: continue
        m = b.s_w[k] / 2 + 0.25
        sx0, sx1 = sorted((b.s_x0[k], b.s_x1[k])); sy0, sy1 = sorted((b.s_y0[k], b.s_y1[k]))
        if sx1 + m > x0 and sx0 - m < x1 and sy1 + m > y0 and sy0 - m < y1:
            # segment distance to box centre approx via sampling
            for t in np.linspace(0, 1, 12):
                px = b.s_x0[k] + t * (b.s_x1[k] - b.s_x0[k]); py = b.s_y0[k] + t * (b.s_y1[k] - b.s_y0[k])
                if x0 - m < px < x1 + m and y0 - m < py < y1 + m: return True
    for k in range(len(b.v_x)):
        if x0 - 0.55 < b.v_x[k] < x1 + 0.55 and y0 - 0.55 < b.v_y[k] < y1 + 0.55: return True
    return False
res = []
for dx in np.arange(-R, R + 1e-9, 0.25):
    for dy in np.arange(-R, R + 1e-9, 0.25):
        for rot, (w, h) in ((0, (3.4, 1.45)), (90, (1.45, 3.4))):
            cx, cy = tx + dx, ty + dy
            # label zone above (1.2 mm) must be free of courtyards as well
            x0, y0, x1, y1 = cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2
            if courtyard_hit(x0, y0, x1, y1) or trk_hit(x0, y0, x1, y1): continue
            lab = courtyard_hit(cx - 1.0, y0 - 1.3, cx + 1.0, y0 - 0.1)
            res.append((math.hypot(dx, dy) + (0.6 if lab else 0), round(cx, 2), round(cy, 2), rot, 'label-zone-blocked' if lab else 'label-zone-free'))
res.sort()
for r in res[:4]: print(r)
