import numpy as np
from pcbtools.labelplace import P, _pair_bad
# R305: courtyard 3.04 x 1.54, pads at +-0.825 (pad 1 DAC0 on +x at rot 180 of main: x=83.82 is right); C304: 3.05 x 1.55, pads +-0.775
def mk(rot):
    out = []
    for ref, w, h, pd in (('R305', 3.04, 1.54, 0.825), ('C304', 3.05, 1.55, 0.775)):
        if rot in (90, 270): box = (-h / 2, -w / 2, h / 2, w / 2)
        else: box = (-w / 2, -h / 2, w / 2, h / 2)
        out.append((P(ref, box, True, False), pd))
    return out
best = {}
for rot in (0, 90, 180, 270):
    (pa, da), (pc, dc) = mk(rot)
    # pad 1 (DAC0) and pad 2 (AWG_BIN) offsets for this rotation (landed rot 180: pad1 at +x)
    def off(d):
        ang = {0: (-1, 0), 180: (1, 0), 90: (0, -1), 270: (0, 1)}[rot]
        return (ang[0] * d, ang[1] * d), (-ang[0] * d, -ang[1] * d)
    n = 0; mind = 99
    for dx in np.arange(-6, 6.001, 0.05):
        for dy in np.arange(-6, 6.001, 0.05):
            if _pair_bad(pa, 0, 0, pc, round(dx, 3), round(dy, 3), tol=0.05): continue
            a1, a2 = off(da); c1, c2 = off(dc)
            d1 = np.hypot(c1[0] + dx - a1[0], c1[1] + dy - a1[1]); d2 = np.hypot(c2[0] + dx - a2[0], c2[1] + dy - a2[1])
            mind = min(mind, max(d1, d2))
            if max(d1, d2) <= 2.0: n += 1
    print('rot', rot, 'legal pair placements with both pad pairs within 2.0 mm:', n, ' smallest achievable max(pad1-pad1, pad2-pad2):', round(mind, 2))
