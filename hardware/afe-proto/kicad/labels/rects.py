"""rects.py BOARD OUT.json: one rectangle per block around its main group, by coordinate descent on its four edges.
Cost: 1000 per pad an edge crosses (0.1 clear), 300 per footprint-silk item an edge crosses, 20 per member whose centre is outside (a stray), 60 per foreign part whose centre is inside,
5 per member courtyard an edge cuts, a lane of 0.4 mm to the blocks already placed, and 0.02 per mm2 so the rectangle stays tight."""
import sys, json, re, os
sys.path.insert(0, '.'); sys.path.append('/usr/lib/python3/dist-packages')
import numpy as np
import pcbnew
from pcbtools import boardio
path, out = sys.argv[1], sys.argv[2]
b = boardio.read_board(path); refs = list(b.fp_ref); bd = pcbnew.LoadBoard(path); mm = pcbnew.ToMM
def tobox(bb):
    x0, y0 = boardio.to_due(mm(bb.GetX()), mm(bb.GetY())); x1, y1 = boardio.to_due(mm(bb.GetRight()), mm(bb.GetBottom()))
    return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
pads = np.array([tobox(pd.GetBoundingBox()) for fp in bd.GetFootprints() for pd in fp.Pads()]).reshape(-1, 4)
silk = np.array([tobox(it.GetBoundingBox()) for fp in bd.GetFootprints() for it in fp.GraphicalItems() if it.GetLayer() == pcbnew.F_SilkS] +
                [tobox(d.GetBoundingBox()) for d in bd.GetDrawings() if d.GetLayer() == pcbnew.F_SilkS and d.GetClass() == 'PCB_TEXT' and d.GetText() not in ('CH1', 'CH2', 'AWG', 'POWER', 'REF/CAL')]).reshape(-1, 4)
def blk(r):
    m = re.fullmatch(r'[A-Z]+(\d)\d\d', r)
    return {'1': 'CH1', '2': 'CH2', '3': 'AWG', '4': 'POWER', '5': 'REFCAL'}.get(m.group(1)) if m else None
BNC = ('J101', 'J201', 'J301')
import os.path
ejp = os.environ.get('EDGEJSON', 'kicad/labels/edge.json')
if os.path.exists(ejp):                       # the edge connectors' labels are in place first: a rectangle edge may not cross them (they count as pads) nor grow over them
    ADV, INK = 0.95, 1.2
    for r, v in json.load(open(ejp)).items():
        if v:
            L = len(r) * ADV; hw, hh = (INK / 2, L / 2) if v[2] == 90 else (L / 2, INK / 2)
            pads = np.vstack([pads, [[v[0] - hw - 0.2, v[1] - hh - 0.2, v[0] + hw + 0.2, v[1] + hh + 0.2]]])
cour = {r: (float(b.fp_cx0[i]), float(b.fp_cy0[i]), float(b.fp_cx1[i]), float(b.fp_cy1[i]), float(b.fp_x[i]), float(b.fp_y[i])) for i, r in enumerate(refs) if not np.isnan(b.fp_cx0[i])}
parts = [(r, blk(r), c) for r, c in cour.items() if r not in BNC and not r.startswith('MH')]
CORE = {'POWER': (18.0, 4.6, 44.0, 22.0), 'REFCAL': (44.5, 4.6, 64.5, 36.0), 'AWG': (69.8, 4.4, 92.0, 19.4), 'CH2': (69.4, 19.9, 92.0, 33.0), 'CH1': (64.8, 33.5, 92.0, 50.3)}
def ovl_any(a, A, m): return bool(((a[0] - m < A[:, 2]) & (A[:, 0] - m < a[2]) & (a[1] - m < A[:, 3]) & (A[:, 1] - m < a[3])).any()) if len(A) else False
def count_ovl(a, A, m): return int(((a[0] - m < A[:, 2]) & (A[:, 0] - m < a[2]) & (a[1] - m < A[:, 3]) & (A[:, 1] - m < a[3])).sum()) if len(A) else 0
def cost(B, q, placed):
    x0, y0, x1, y1 = q
    if x1 - x0 < 3 or y1 - y0 < 3 or x0 < 17.5 or x1 > 98.0 or y0 < 0.6 or y1 > 52.6: return 1e9
    edges = [(x0, y0, x0, y1), (x1, y0, x1, y1), (x0, y0, x1, y0), (x0, y1, x1, y1)]
    c = 0.0
    for e in edges:
        sb = (min(e[0], e[2]) - 0.075, min(e[1], e[3]) - 0.075, max(e[0], e[2]) + 0.075, max(e[1], e[3]) + 0.075)
        c += 1000 * count_ovl(sb, pads, 0.1) + 200 * count_ovl(sb, silk, 0.05)
    for r, B2, cc in parts:
        inside = x0 <= cc[4] <= x1 and y0 <= cc[5] <= y1
        if B2 == B and not inside: c += 40
        if B2 != B and inside: c += 120
        if B2 == B and inside:
            cut = (cc[0] < x0 < cc[2] or cc[0] < x1 < cc[2]) and cc[1] < y1 and cc[3] > y0 or (cc[1] < y0 < cc[3] or cc[1] < y1 < cc[3]) and cc[0] < x1 and cc[2] > x0
            if cut: c += 5
    for q2 in placed:
        if q[0] - 0.4 < q2[2] and q2[0] < q[2] + 0.4 and q[1] - 0.4 < q2[3] and q2[1] < q[3] + 0.4: c += 5000
    return c + 0.02 * (x1 - x0) * (y1 - y0)
START = {'POWER': [18.1, 4.15, 44.2, 22.9], 'REFCAL': [44.6, 4.8, 64.55, 31.3], 'AWG': [69.8, 4.15, 92.0, 19.4], 'CH2': [75.7, 22.4, 92.0, 30.4], 'CH1': [64.3, 38.2, 92.0, 46.4]}
res = {}; placed = []
for B in ('CH2', 'CH1', 'AWG', 'REFCAL', 'POWER'):
    mem = [cc for r, B2, cc in parts if B2 == B and CORE[B][0] <= cc[4] <= CORE[B][2] and CORE[B][1] <= cc[5] <= CORE[B][3]]
    rng = np.random.default_rng(1); core = CORE[B]; samples = []
    for _ in range(int(os.environ.get('NS', '15000'))):
        qq = [round(core[0] + rng.uniform(-3, 3), 1), round(core[1] + rng.uniform(-3, 3), 1), round(core[2] + rng.uniform(-6, 3), 1), round(core[3] + rng.uniform(-6, 3), 1)]
        samples.append((cost(B, qq, placed), qq))
    samples.sort(key=lambda t: t[0]); q = list(samples[0][1])
    best = cost(B, q, placed)
    for it in range(6):
        ch = False
        for e in (0, 1, 2, 3):
            for d in np.arange(-3.0, 3.01, 0.05):
                q2 = list(q); q2[e] = round(q[e] + d, 2); cst = cost(B, q2, placed)
                if cst < best - 1e-9: best, q, ch = cst, q2, True
        if not ch: break
    res[B] = [round(v, 2) for v in q]; placed.append(q)
    inside_out = [r for r, B2, cc in parts if B2 == B and not (q[0] <= cc[4] <= q[2] and q[1] <= cc[5] <= q[3])]
    foreign = [r for r, B2, cc in parts if B2 != B and q[0] <= cc[4] <= q[2] and q[1] <= cc[5] <= q[3]]
    print('RECT', B, res[B], 'cost %.1f' % best, 'strays', inside_out, 'foreign inside', foreign)
# room for the labels: grow every edge outward (up to GROW mm) while it crosses no more pads or silk, takes in no foreign part and keeps the lane to the other rectangles
def pen(B, q, others):
    x0, y0, x1, y1 = q
    if x1 - x0 < 3 or y1 - y0 < 3 or x0 < 17.5 or x1 > 98.0 or y0 < 0.6 or y1 > 52.6: return 1e9
    c = 0
    for e in [(x0, y0, x0, y1), (x1, y0, x1, y1), (x0, y0, x1, y0), (x0, y1, x1, y1)]:
        sb = (min(e[0], e[2]) - 0.075, min(e[1], e[3]) - 0.075, max(e[0], e[2]) + 0.075, max(e[1], e[3]) + 0.075)
        c += 1000 * count_ovl(sb, pads, 0.1) + 200 * count_ovl(sb, silk, 0.05)
    c += sum(120 for r, B2, cc in parts if B2 != B and x0 <= cc[4] <= x1 and y0 <= cc[5] <= y1)
    for q2 in others:
        if q[0] - 0.4 < q2[2] and q2[0] < q[2] + 0.4 and q[1] - 0.4 < q2[3] and q2[1] < q[3] + 0.4: c += 5000
    return c
GROWMAX = float(os.environ.get('GROW', '2.0'))
order = ['POWER', 'REFCAL', 'AWG', 'CH2', 'CH1']
for rnd in range(3):
    for B in order:
        q = res[B]; others = [res[o] for o in res if o != B]; p0 = pen(B, q, others)
        for e in (0, 1, 2, 3):
            sgn = -1 if e in (0, 1) else 1; bestd = 0
            for k in range(1, int(GROWMAX / 0.1) + 1):
                q2 = list(q); q2[e] = round(q[e] + sgn * 0.1 * k, 2)
                if pen(B, q2, others) <= p0: bestd = k
                else: break
            q[e] = round(q[e] + sgn * 0.1 * bestd, 2)
        res[B] = q
for B in res: print('GROWN', B, res[B])
json.dump({B: [float(v) for v in q] for B, q in res.items()}, open(out, 'w'))
