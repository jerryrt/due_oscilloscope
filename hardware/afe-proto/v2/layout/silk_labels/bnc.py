"""bnc.py IN.kicad_pcb OUT.kicad_pcb RECTS_IN.json RECTS_OUT.json REPORT.json   (in the PCB image; run after place_silk.py)

The three BNCs (J101, J201, J301): each gets its own RECTANGLE on the silk holding its designator and its function label ("CH1 IN", "CH2 IN", "AWG OUT"), at one frame
offset and one text orientation for all three (the BNCs share one rotation on this board, so one board offset is that). The rectangle is outside every part's body and
courtyard, 0.3 mm clear of every pad, silk line, outline rectangle and board text, 0.8 mm clear of every other designator, inside the board outline, and the three
do not touch. The smallest offset from the footprint origin wins; both text orientations are tried. The rectangle joins the BNC's block in RECTS (so the labels sit
inside an outline of their block). Only silk changes: the Reference offset, the function label's gr_text, four gr_lines per rectangle."""
import sys, re, math, json, uuid
sys.path.insert(0, '/work/hardware/afe-proto'); sys.path.append('/usr/lib/python3/dist-packages')
import numpy as np
import pcbnew
from pcbtools import boardio, silkread as S

inp, out, rects_in, rects_out, rep = sys.argv[1:6]
txt = open(inp).read(); b = boardio.read_board(inp); pb = pcbnew.LoadBoard(inp); mm = pcbnew.ToMM
RECTS = json.load(open(rects_in)); refs = list(b.fp_ref); fi = {r: i for i, r in enumerate(refs)}; row = {int(k): i for i, k in enumerate(b.fp_idx)}
BNC = {'J101': ('CH1 IN', 'CH1'), 'J201': ('CH2 IN', 'CH2'), 'J301': ('AWG OUT', 'AWG')}
silk = S.read_silk(txt)
RING = [tuple(p) for p in b.outline]


def inside_board(px, py):
    c = False; n = len(RING)
    for i in range(n):
        (x0, y0), (x1, y1) = RING[i], RING[(i + 1) % n]
        if (y0 > py) != (y1 > py) and px < (x1 - x0) * (py - y0) / (y1 - y0) + x0: c = not c
    return c


obst = []                                                         # (x0, y0, x1, y1, margin)
for i in range(len(refs)):
    if int(b.fp_side[i]) == 0 and not np.isnan(b.fp_cx0[i]): obst.append((min(b.fp_cx0[i], b.fp_cx1[i]), min(b.fp_cy0[i], b.fp_cy1[i]), max(b.fp_cx0[i], b.fp_cx1[i]), max(b.fp_cy0[i], b.fp_cy1[i]), 0.1))
for f in pb.GetFootprints():
    bx = pcbnew.BOX2I(); n = 0
    for g in f.GraphicalItems():
        if g.GetLayer() == pcbnew.F_Fab: bx.Merge(g.GetBoundingBox()); n += 1
    if n: obst.append((mm(bx.GetX()) - 50.0, 150.0 - mm(bx.GetBottom()), mm(bx.GetRight()) - 50.0, 150.0 - mm(bx.GetY()), 0.3))
    for g in f.GraphicalItems():
        if g.GetLayer() == pcbnew.F_SilkS and hasattr(g, 'GetShape'):
            bb = g.GetBoundingBox(); obst.append((mm(bb.GetX()) - 50.0, 150.0 - mm(bb.GetBottom()), mm(bb.GetRight()) - 50.0, 150.0 - mm(bb.GetY()), 0.3))
for x0, y0, x1, y1 in zip(b.p_bx0, b.p_by0, b.p_bx1, b.p_by1): obst.append((x0, y0, x1, y1, 0.3))
for sh in silk:
    if sh[0] == 'seg': obst.append((min(sh[1], sh[3]), min(sh[2], sh[4]), max(sh[1], sh[3]), max(sh[2], sh[4]), 0.3 + sh[5] / 2))
    else: obst.append((sh[1], sh[2], sh[3], sh[4], 0.3))
for rs in RECTS.values():                                         # outline rectangles: not inside or across any
    for x0, y0, x1, y1 in rs: obst.append((x0, y0, x1, y1, 0.3))
for t, x, y, h in zip(b.t_text, b.t_x, b.t_y, b.t_h):
    t = t.decode() if isinstance(t, bytes) else t
    if t in [v[0] for v in BNC.values()]: continue
    L = max(len(t) * 0.95 * h, h); obst.append((x - L / 2, y - L / 2, x + L / 2, y + L / 2, 0.4))
for j in range(len(b.r_fp)):
    r = refs[row[int(b.r_fp[j])]]
    if b.r_on_silk[j] and r not in BNC:
        bx = S.text_box(r, b.r_x[j], b.r_y[j], b.r_w[j], b.r_h[j], b.r_ang[j]); obst.append((bx[0], bx[1], bx[2], bx[3], 0.8))

WR, HR = 7.5, 3.4
step = 0.1
ox = np.arange(-30.0, 30.0 + 1e-9, step); oy = np.arange(-24.0, 24.0 + 1e-9, step); OX, OY = np.meshgrid(ox, oy, indexing='ij')
res = {}
for orient in ('h', 'v'):
    w, h = (WR, HR) if orient == 'h' else (HR, WR)
    ok = np.ones(OX.shape, bool)
    for r in BNC:
        bx0, by0 = float(b.fp_x[fi[r]]), float(b.fp_y[fi[r]])
        rx0, ry0 = bx0 + OX, by0 + OY; rx1, ry1 = rx0 + w, ry0 + h        # the rectangle at offset (OX, OY): its lower-left corner relative to the origin
        for (x0, y0, x1, y1, m) in obst:
            ok &= ~((rx1 + m > x0) & (rx0 - m < x1) & (ry1 + m > y0) & (ry0 - m < y1))
    cand = np.argwhere(ok); best = None
    for i, j in sorted(cand.tolist(), key=lambda p: math.hypot(ox[p[0]], oy[p[1]])):
        good = True
        for r in BNC:
            bx0, by0 = float(b.fp_x[fi[r]]) + ox[i], float(b.fp_y[fi[r]]) + oy[j]
            if not all(inside_board(px, py) for px, py in ((bx0 - 0.3, by0 - 0.3), (bx0 + w + 0.3, by0 - 0.3), (bx0 + w + 0.3, by0 + h + 0.3), (bx0 - 0.3, by0 + h + 0.3))): good = False; break
        if good:
            rs = [(float(b.fp_x[fi[r]]) + ox[i], float(b.fp_y[fi[r]]) + oy[j], float(b.fp_x[fi[r]]) + ox[i] + w, float(b.fp_y[fi[r]]) + oy[j] + h) for r in BNC]
            if all(not (a[0] - 0.5 < c[2] and c[0] - 0.5 < a[2] and a[1] - 0.5 < c[3] and c[1] - 0.5 < a[3]) for a in rs for c in rs if a is not c):
                best = (round(float(ox[i]), 2), round(float(oy[j]), 2)); break
    res[orient] = best
print('offsets', res)
json.dump({'offsets': res, 'size': (WR, HR)}, open(rep, 'w'))
pick = min((o for o in res if res[o]), key=lambda o: math.hypot(*res[o]), default=None)
if not pick:
    print('NO RECTANGLE OFFSET FITS ALL THREE BNCs'); sys.exit(0)
dx, dy = res[pick]; w, h = (WR, HR) if pick == 'h' else (HR, WR)
new_rects = {}; add = ''
for r, (lab, blk) in BNC.items():
    x0, y0 = float(b.fp_x[fi[r]]) + dx, float(b.fp_y[fi[r]]) + dy; x1, y1 = x0 + w, y0 + h
    RECTS[blk].append([round(x0, 3), round(y0, 3), round(x1, 3), round(y1, 3)])
    for ei, (p, q) in enumerate((((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0)))):
        add += '\n\t(gr_line\n\t\t(start %.4f %.4f)\n\t\t(end %.4f %.4f)\n\t\t(stroke\n\t\t\t(width 0.15)\n\t\t\t(type default)\n\t\t)\n\t\t(layer "F.SilkS")\n\t\t(uuid "%s")\n\t)' % (
            p[0] + 50.0, 150.0 - p[1], q[0] + 50.0, 150.0 - q[1], uuid.uuid5(uuid.NAMESPACE_URL, 'bncbox/%s/%d' % (r, ei)))
    if pick == 'h': des_at = ((x0 + x1) / 2, y1 - 0.9, 0.0); fun_at = ((x0 + x1) / 2, y0 + 0.9, 0.0)
    else: des_at = (x0 + 0.9, (y0 + y1) / 2, 90.0); fun_at = (x1 - 0.9, (y0 + y1) / 2, 90.0)
    new_rects[r] = (des_at, fun_at)
for f in pb.GetFootprints():
    r = f.GetReference()
    if r in BNC:
        d = new_rects[r][0]; rf = f.Reference(); rf.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(float(d[0]) + 50.0), pcbnew.FromMM(150.0 - float(d[1])))); rf.SetTextAngleDegrees(d[2]); rf.SetVisible(True)
pcbnew.SaveBoard('/tmp/scratch_bnc.kicad_pcb', pb)
sc = open('/tmp/scratch_bnc.kicad_pcb').read(); t = txt
for r, (lab, blk) in BNC.items():
    i = t.index('(property "Reference" "%s"' % r); m = re.compile(r'\(at ([\-\d.]+) ([\-\d.]+)(?: ([\-\d.]+))?\)').search(t, i)
    j = sc.index('(property "Reference" "%s"' % r); ms = re.compile(r'\(at ([\-\d.]+) ([\-\d.]+)(?: ([\-\d.]+))?\)').search(sc, j)
    t = t[:m.start()] + '(at %s %s %s)' % (ms.group(1), ms.group(2), ms.group(3) or '0') + t[m.end():]
    g = re.search(r'\(gr_text "%s"\s+\(at ([\-\d.]+) ([\-\d.]+)(?: ([\-\d.]+))?\)' % re.escape(lab), t)
    f_ = new_rects[r][1]
    t = t[:g.start(1)] + '%.3f %.3f %g' % (f_[0] + 50.0, 150.0 - f_[1], f_[2]) + t[g.end(0) - 1:]
i = t.rindex('\n)'); t = t[:i] + add + t[i:]
open(out, 'w').write(t)
json.dump({k: [list(r) for r in v] for k, v in RECTS.items()}, open(rects_out, 'w'), indent=1)
print('orientation', pick, 'offset', dx, dy, 'rectangle', w, 'x', h, 'wrote', out)
