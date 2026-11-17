"""ratio.py BOARD PLAN.json: dry run of the ratio test (own-part distance <= half the nearest other label's distance). Changes nothing."""
import sys, json
sys.path.insert(0, '.'); sys.path.append('/usr/lib/python3/dist-packages')
import numpy as np, pcbnew
from pcbtools import boardio
from pcbtools.boards import v1 as C
b = boardio.read_board(sys.argv[1]); plan = json.load(open(sys.argv[2])); ex = json.load(open(sys.argv[2].replace('.json', '_extra.json')))
refs = list(b.fp_ref); ADV, INK = C.DESIGNATOR_ADVANCE, C.DESIGNATOR_INK_H
cour = {r: (float(b.fp_cx0[i]), float(b.fp_cy0[i]), float(b.fp_cx1[i]), float(b.fp_cy1[i])) for i, r in enumerate(refs) if not np.isnan(b.fp_cx0[i])}
bd = pcbnew.LoadBoard(sys.argv[1]); mm = pcbnew.ToMM
def tobox(bb):
    x0, y0 = boardio.to_due(mm(bb.GetX()), mm(bb.GetY())); x1, y1 = boardio.to_due(mm(bb.GetRight()), mm(bb.GetBottom()))
    return (float(min(x0, x1)), float(min(y0, y1)), float(max(x0, x1)), float(max(y0, y1)))
solid = {}
for fp in bd.GetFootprints():
    bx = [tobox(pd.GetBoundingBox()) for pd in fp.Pads()] + [tobox(it.GetBoundingBox()) for it in fp.GraphicalItems() if it.GetLayer() == pcbnew.F_Fab and it.GetClass() == 'PCB_SHAPE']
    if bx: solid[fp.GetReference()] = (min(q[0] for q in bx), min(q[1] for q in bx), max(q[2] for q in bx), max(q[3] for q in bx))
def box(t, x, y, ang, size=1.0):
    L = len(t) * ADV * size; W = INK * size
    return (x - W / 2, y - L / 2, x + W / 2, y + L / 2) if ang == 90 else (x - L / 2, y - W / 2, x + L / 2, y + W / 2)
def gap(a, c): return float(np.hypot(max(c[0] - a[2], 0, a[0] - c[2]), max(c[1] - a[3], 0, a[1] - c[3])))
labs = {r: box(r, *v) for r, v in plan.items() if v}
others = dict(labs)
for t, v in ex['names'].items():
    if v: others['name:' + t] = box(t, v[0], v[1], 0, v[2])
for t, v in ex['bncfn'].items(): others['fn:' + t] = (v[0], v[1] - INK / 2, v[0] + len(t) * ADV, v[1] + INK / 2)
rows = []
for r, bx in labs.items():
    sol = solid.get(r, cour[r]); own = gap(bx, sol)
    near = min(((gap(bo, sol), q) for q, bo in others.items() if q != r), default=(9e9, ''))
    rows.append((r, own, near[0], near[1]))
bad = [x for x in rows if x[1] * 2 > x[2] + 1e-9]
print('labelled parts', len(rows), 'fail', len(bad))
for r, o, n, q in sorted(bad, key=lambda t: -(t[1] * 2 - t[2])): print('  %-6s own label %.2f   nearest OTHER label %.2f (%s)   needs >= %.2f   short by %.2f' % (r, o, n, q, 2 * o, 2 * o - n))
