import sys, collections
sys.path[:0] = ['hardware/pcbkit']
import numpy as np
from pcbkit import board as kb
b = kb.read_board(sys.argv[1], {'FRAME': (50.0, 150.0)})
L = np.hypot(b.s_x1 - b.s_x0, b.s_y1 - b.s_y0)
per = collections.defaultdict(lambda: collections.Counter())
for k in range(len(L)):
    per[b.nets[int(b.s_net[k])].lstrip('/')][round(float(b.s_w[k]), 3)] += float(L[k])
rule, wide = {}, []
for n, c in sorted(per.items()):
    mode = c.most_common(1)[0][0]
    rule[n] = mode
    for w in c:
        if w > mode + 1e-3:
            wide.append((n, w, round(c[w], 2)))
print('RULE', {k: v for k, v in rule.items() if abs(v - 0.2) > 1e-3})
print('WIDER', wide)
