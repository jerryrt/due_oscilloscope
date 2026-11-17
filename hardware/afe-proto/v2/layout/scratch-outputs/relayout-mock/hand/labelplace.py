"""python3 labelplace.py IN.kicad_pcb OUT.kicad_pcb REF[,REF...]   (in the image)
Silk-only re-placement of the named designators under D30 (silkread.py): horizontal, above and centred (rule 1) when that leaves no finding, otherwise beside, east or west
(rule 2b, the ref is then added to the beside set and printed). Greedy over the whole board's silkread findings, several passes. Writes the property offsets by text splice."""
import sys, re, math, itertools
sys.path.insert(0, '/work/hardware/afe-proto'); sys.path.append('/usr/lib/python3/dist-packages')
import numpy as np, pcbnew
from pcbtools import boardio, silkread
inp, out, refs = sys.argv[1], sys.argv[2], sys.argv[3].split(',')
src = open('/work/hardware/afe-proto/tests/pcbtools/test_silkread.py').read()
BES = set(eval(re.search(r"BESIDE = (\{.*?\})\n", src, re.S).group(1))['v2/layout/integrated/afe-v2-integrated.kicad_pcb'])
EAST = set(eval(re.search(r"EAST_END = (\{.*?\})\n", src, re.S).group(1))['v2/layout/integrated/afe-v2-integrated.kicad_pcb'])
LABELS = {'J101': 'CH1 IN', 'J201': 'CH2 IN', 'J301': 'AWG OUT'}
EDGE = {'J601', 'J602', 'J603', 'J604', 'J605', 'J606', 'J607'}
text = open(inp).read()
b = boardio.read_board(inp)
silk = silkread.read_silk(text)
rows = {b.fp_ref[i]: i for i in range(len(b.fp_ref))}
lab = {}
for j in range(len(b.r_fp)):
    lab[b.fp_ref[list(b.fp_idx).index(int(b.r_fp[j]))] if False else None] = None
# map ref -> label row
idx = {int(k): i for i, k in enumerate(b.fp_idx)}
rowof = {}
for j in range(len(b.r_fp)):
    rowof[b.fp_ref[idx[int(b.r_fp[j])]]] = j
def count(beside):
    return silkread.findings(b, LABELS, edge_headers=EDGE, silk=silk, east_end=EAST, beside=beside)
beside = set(BES)
def cands(r):
    i = rows[r]; c = (b.fp_cx0[i], b.fp_cy0[i], b.fp_cx1[i], b.fp_cy1[i]); w = len(r) * silkread.CHAR_ADV * b.r_w[rowof[r]]; h = b.r_h[rowof[r]]
    cx, cy = (c[0] + c[2]) / 2, (c[1] + c[3]) / 2
    for g in (0.3, 0.45, 0.6, 0.15, 0.0):
        for dx in (0.0, -0.15, 0.15, -0.3, 0.3):
            yield ('above', cx + dx, c[3] + g + h / 2)
    for side in (1, -1):
        for g in (0.3, 0.45, 0.6, 0.15):
            for dy in (0.0, 0.15, -0.15, 0.3, -0.3):
                yield ('beside', (c[2] + g + w / 2) if side > 0 else (c[0] - g - w / 2), cy + dy)
placed = {}
for p in range(3):
    for r in refs:
        j = rowof[r]; best = None
        for kind, x, y in cands(r):
            b.r_x[j], b.r_y[j], b.r_ang[j] = x, y, 0.0
            bs = beside | ({r} if kind == 'beside' else set())
            f = count(bs)
            mine = [s for s in f if s.startswith(r + ':')]
            sc = (len(mine), len(f), 0 if kind == 'above' else 1)
            if best is None or sc < best[0]:
                best = (sc, kind, x, y)
            if sc[0] == 0 and kind == 'above':
                break
        _, kind, x, y = best
        b.r_x[j], b.r_y[j], b.r_ang[j] = x, y, 0.0
        placed[r] = (kind, x, y)
        if kind == 'beside': beside.add(r)
        else: beside.discard(r)
f = count(beside)
print('silkread findings after placement:', len(f))
for s in f[:40]: print('  ', s[:170])
print('beside set grew by', sorted(beside - BES), 'and lost', sorted(BES - beside))
# write: offsets by text splice, verified through pcbnew
mm = pcbnew.ToMM
t = text
for r, (kind, x, y) in placed.items():
    i = t.index('(property "Reference" "%s"' % r); s = t.rfind('\n\t(footprint ', 0, i)
    m = re.compile(r'\(at ([\d.\-]+) ([\d.\-]+)(?: ([\d.\-]+))?\)').search(t, s)
    ox, oy, rot = float(m.group(1)), float(m.group(2)), float(m.group(3) or 0)
    dx, dy = (x + 50) - ox, (150 - y) - oy                    # board frame offset (y down)
    a = math.radians(rot)
    for sign in (1, -1):
        rx = dx * math.cos(sign * a) - dy * math.sin(sign * a); ry = dx * math.sin(sign * a) + dy * math.cos(sign * a)
        pm = re.compile(r'\(property "Reference" "%s"\s+\(at ([\-\d.]+) ([\-\d.]+)' % r).search(t, s)
        t2 = t[:pm.start(1)] + '%.3f %.3f' % (rx, ry) + t[pm.end(2):]
        open('/tmp/lp_chk.kicad_pcb', 'w').write(t2)
        bb = pcbnew.LoadBoard('/tmp/lp_chk.kicad_pcb'); f_ = bb.FindFootprintByReference(r).Reference().GetPosition()
        if abs(mm(f_.x) - (x + 50)) < 0.02 and abs(mm(f_.y) - (150 - y)) < 0.02:
            t = t2; break
    else:
        print('could not place', r)
open(out, 'w').write(t)
