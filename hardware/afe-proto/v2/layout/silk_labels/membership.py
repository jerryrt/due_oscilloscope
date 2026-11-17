"""membership.py BOARD RECTS.json : per block rectangle, the parts of the block (designator digit) whose centre is outside (strays), foreign parts inside, parts with a courtyard cut."""
import sys, json, re
sys.path.insert(0, 'hardware/afe-proto'); sys.path.append('/usr/lib/python3/dist-packages')
import numpy as np
from pcbtools import boardio
b = boardio.read_board(sys.argv[1]); refs = list(b.fp_ref)
R = json.load(open(sys.argv[2]))
def blk(r):
    m = re.fullmatch(r'[A-Z]+(\d)\d\d', r)
    return {'1': 'CH1', '2': 'CH2', '3': 'AWG', '4': 'POWER', '5': 'REFCAL'}.get(m.group(1)) if m else None
BNC = {'J101': 'CH1', 'J201': 'CH2', 'J301': 'AWG'}
for B, rs in R.items():
    main = [r for r in rs if r[0] < 98][0]; boxes = [r for r in rs if r is not main and r[0] >= 98]
    x0, y0, x1, y1 = main
    stray, foreign, cut = [], [], []
    for i, r in enumerate(refs):
        if r.startswith('MH') or r in BNC or np.isnan(b.fp_cx0[i]): continue
        cx, cy = float(b.fp_x[i]), float(b.fp_y[i]); B2 = blk(r)
        ins = x0 <= cx <= x1 and y0 <= cy <= y1
        if B2 == B and not ins: stray.append((r, round(cx, 1), round(cy, 1)))
        if B2 != B and ins: foreign.append((r, B2, round(cx, 1), round(cy, 1)))
    print(B, main, 'strays', stray, 'foreign inside', foreign)
