import re, sys
import numpy as np
from pcbtools import boardio, silkread
from pcbtools.editor import edit
from pcbtools.boards import v1 as C
path = sys.argv[1]
b = boardio.read_board(path)
SKIP = set(C.BNC_REFS)
HDR = {'J601','J602','J603','J604','J605','J606','J607'}
import json, os
LM = json.load(open('whatif/_scratch/labmode.json')) if os.path.exists('whatif/_scratch/labmode.json') else {}
moves = {}
for k, r in enumerate(b.fp_ref):
    if np.isnan(b.fp_cx0[k]) or int(b.fp_side[k]) != 0 or r in SKIP or r.startswith('MH'): continue
    cx = (b.fp_cx0[k] + b.fp_cx1[k]) / 2
    if r in HDR:
        w, h = b.fp_cx1[k] - b.fp_cx0[k], b.fp_cy1[k] - b.fp_cy0[k]
        cy = (b.fp_cy0[k] + b.fp_cy1[k]) / 2
        if w > h and cy >= 26.67:
            moves[r] = (round(float(cx), 3), round(float(b.fp_cy0[k] - 0.2 - 0.5), 3))
        else:
            moves[r] = (round(float(cx), 3), round(float(b.fp_cy1[k] + 0.2 + 0.5), 3))
    else:
        md = LM.get(r, 'A')
        w_ = len(r) * 0.9
        cyc = (b.fp_cy0[k] + b.fp_cy1[k]) / 2
        if md == 'E':
            moves[r] = (round(float(b.fp_cx1[k] + 0.2 + w_ / 2), 3), round(float(cyc), 3))
        elif md == 'W':
            moves[r] = (round(float(b.fp_cx0[k] - 0.2 - w_ / 2), 3), round(float(cyc), 3))
        else:
            moves[r] = (round(float(cx) + {'C408': 0.3}.get(r, 0.0), 3), round(float(b.fp_cy1[k] + 0.2 + 0.5) + {'C401': float(__import__('os').environ.get('DY401','0'))}.get(r, 0.0), 3))
with edit(path) as e:
    for r, (x, y) in moves.items():
        e.set_ref(r, x, y, h=1.0)
    LAB = {'J101': 'CH1 IN', 'J201': 'CH2 IN', 'J301': 'AWG OUT'}
    for r, word in LAB.items():
        k = b.ref_index(r)
        ox, oy = float(b.fp_x[k]), float(b.fp_y[k])
        tx = e.pcb.PCB_TEXT(e.b)
        tx.SetText(word)
        tx.SetLayer(e.pcb.F_SilkS)
        tx.SetPosition(e._pt(ox - 2.75, oy + 2.4))
        tx.SetTextSize(e.pcb.VECTOR2I(e.pcb.FromMM(1.0), e.pcb.FromMM(1.0)))
        tx.SetTextThickness(e.pcb.FromMM(0.15))
        tx.SetTextAngleDegrees(90)
        e.b.Add(tx)
        e._give(tx)
        ref = e._fp(r).Reference()
        ref.SetLayer(e.pcb.B_SilkS)
        ref.SetMirrored(True)
        ref.SetVisible(True)
        ref.SetTextSize(e.pcb.VECTOR2I(e.pcb.FromMM(1.0), e.pcb.FromMM(1.0)))
        ref.SetTextThickness(e.pcb.FromMM(0.15))
        ref.SetPosition(e._pt(ox + 3.2, oy))
        ref.SetTextAngleDegrees(0)
print(len(moves), 'labels placed')
