"""bnc.py IN.kicad_pcb OUT.kicad_pcb REPORT.json   (in the PCB image; run after place_silk.py)

The three BNCs (J101, J201, J301), owner's rule: each designator and its function label ("CH1 IN", "CH2 IN", "AWG OUT") sits OUTSIDE the BNC body (the body
hides what is under it) and at one offset and orientation in each BNC's own frame, equal to 0.05 mm. The three have one rotation on this board, so one board
offset serves all three; the search is a grid of offsets from the footprint origin (0.1 mm, both text orientations), judged for all three BNCs at once:
 designator: on no part's body (F.Fab outline), pad, silk line, board text or other label; within DESIGNATOR_DIST_MAX of its own pads; clear of every courtyard
   but its own BNC's; LR-11's gap to other designators.
 function label: the same, without the distance test (a function label is not a designator).
Only text moves: the BNC's Reference offset and the function label's gr_text position and angle. Ties break to the smallest offset."""
import sys, re, math, json
sys.path.insert(0, '/work/hardware/afe-proto'); sys.path.append('/usr/lib/python3/dist-packages')
import numpy as np
import pcbnew
from pcbtools import boardio, silkread as S
from pcbtools.boards import v2_layout as C
import os
if os.environ.get('RECTS_JSON'): C.OUTLINE = {k: [tuple(r) for r in v] for k, v in json.load(open(os.environ['RECTS_JSON'])).items()}

inp, out, rep = sys.argv[1:4]
txt = open(inp).read(); b = boardio.read_board(inp); pb = pcbnew.LoadBoard(inp); mm = pcbnew.ToMM
silk = S.read_silk(txt)
def footprint_silk(pb):
    """every footprint's F.SilkS graphics as ('seg', x0, y0, x1, y1, width) in Due mm: a line as it is, a rectangle by its four edges, anything else (arc, circle) by its box"""
    out = []
    f_ = lambda v: (pcbnew.ToMM(v.x) - 50.0, 150.0 - pcbnew.ToMM(v.y))
    for f in pb.GetFootprints():
        for g in f.GraphicalItems():
            if g.GetLayer() != pcbnew.F_SilkS or not hasattr(g, 'GetShape'): continue
            w = pcbnew.ToMM(g.GetWidth()); sh = g.GetShape()
            if sh == pcbnew.SHAPE_T_SEGMENT:
                (x0, y0), (x1, y1) = f_(g.GetStart()), f_(g.GetEnd()); out.append(('seg', x0, y0, x1, y1, w))
            else:
                bx = g.GetBoundingBox(); x0, y1 = f_(bx.GetOrigin()); x1, y0 = f_(pcbnew.VECTOR2I(bx.GetRight(), bx.GetBottom()))
                for a, c in (((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))): out.append(('seg', *a, *c, w))
    return out
SILK_CLEAR = 0.2
def on_silk(sb, shapes):
    g = (sb[0] - SILK_CLEAR, sb[1] - SILK_CLEAR, sb[2] + SILK_CLEAR, sb[3] + SILK_CLEAR)
    return any(S._on_shape(g, sh) for sh in shapes)

silk = silk + footprint_silk(pb)
refs = list(b.fp_ref); fi = {r: i for i, r in enumerate(refs)}
row = {int(k): i for i, k in enumerate(b.fp_idx)}
BNC = {'J101': 'CH1 IN', 'J201': 'CH2 IN', 'J301': 'AWG OUT'}
cour = {refs[i]: S._box(b.fp_cx0[i], b.fp_cy0[i], b.fp_cx1[i], b.fp_cy1[i]) for i in range(len(refs)) if int(b.fp_side[i]) == 0 and not np.isnan(b.fp_cx0[i])}
body = {}
for f in pb.GetFootprints():
    bx = pcbnew.BOX2I(); n = 0
    for g in f.GraphicalItems():
        if g.GetLayer() == pcbnew.F_Fab: bx.Merge(g.GetBoundingBox()); n += 1
    body[f.GetReference()] = (mm(bx.GetX()) - 50.0, 150.0 - mm(bx.GetBottom()), mm(bx.GetRight()) - 50.0, 150.0 - mm(bx.GetY())) if n else cour.get(f.GetReference())
pads = [(x0, y0, x1, y1) for x0, y0, x1, y1 in zip(b.p_bx0, b.p_by0, b.p_bx1, b.p_by1)]
owner = [refs[int(f)] for f in b.p_fp]
tlist = [(t.decode() if isinstance(t, bytes) else t, x, y, h) for t, x, y, h in zip(b.t_text, b.t_x, b.t_y, b.t_h)]
texts = [(lambda L: (x - L / 2, y - L / 2, x + L / 2, y + L / 2))(max(len(t) * 0.95 * h, h)) for t, x, y, h in tlist if t not in BNC.values()]
labels = {}                                                      # other designators on the top silk
for j in range(len(b.r_fp)):
    r = refs[row[int(b.r_fp[j])]]
    if b.r_on_silk[j] and r not in BNC: labels[r] = S.text_box(r, b.r_x[j], b.r_y[j], b.r_w[j], b.r_h[j], b.r_ang[j])
rot = {r: round(float(b.fp_rot[fi[r]]), 3) for r in BNC}
assert len(set(rot.values())) == 1, 'the BNCs have different rotations; the frame offset is not one board offset'
H, ADV_L, H_L = 1.0, C.DESIGNATOR_ADVANCE, C.DESIGNATOR_INK_H


def lgap(a, c):
    return math.hypot(max(c[0] - a[2], 0.0, a[0] - c[2]), max(c[1] - a[3], 0.0, a[1] - c[3]))


RING = [tuple(p) for p in b.outline]
def inside_board(px, py):
    c = False; n = len(RING)
    for i in range(n):
        (x0, y0), (x1, y1) = RING[i], RING[(i + 1) % n]
        if (y0 > py) != (y1 > py) and px < (x1 - x0) * (py - y0) / (y1 - y0) + x0: c = not c
    return c


NEED_INSIDE = True


def ok(text, r, x, y, ang, designator):
    sb = S.text_box(text, x, y, 1.0, H, ang)
    lb = (x - len(text) * ADV_L / 2, y - H_L / 2, x + len(text) * ADV_L / 2, y + H_L / 2) if ang == 0 else (x - H_L / 2, y - len(text) * ADV_L / 2, x + H_L / 2, y + len(text) * ADV_L / 2)
    if NEED_INSIDE:
        rs = C.OUTLINE.get(C.BLOCK.get(r))
        if rs and not any(x0 - 0.005 <= sb[0] and sb[2] <= x1 + 0.005 and y0 - 0.005 <= sb[1] and sb[3] <= y1 + 0.005 for x0, y0, x1, y1 in rs): return False
    if any(S._overlap(sb, bd) for k, bd in body.items() if bd is not None and (k != r or True)): return False
    if any(S._overlap(sb, c) for k, c in cour.items() if k != r): return False
    if any(S._overlap(sb, p) for p in pads): return False
    if on_silk(sb, silk): return False
    if any(lgap(sb, t) < 0.4 for t in texts): return False
    if any(lgap(lb, (l[0] - 0.0, l[1], l[2], l[3])) < (1.0 if designator else 0.5) for l in labels.values()): return False
    if not all(inside_board(px, py) for px, py in ((sb[0] - 0.3, sb[1] - 0.3), (sb[2] + 0.3, sb[1] - 0.3), (sb[2] + 0.3, sb[3] + 0.3), (sb[0] - 0.3, sb[3] + 0.3))): return False
    if designator:
        mine = [p for p, o in zip(pads, owner) if o == r]
        if min(lgap(lb, p) for p in mine) > C.DESIGNATOR_DIST_MAX: return False
    return True


def search(designator):
    best = []
    for ang in (0, 90):
        for ox in np.arange(-14.0, 22.0, 0.1):
            for oy in np.arange(-10.0, 10.0, 0.1):
                good = True
                for r, lab in BNC.items():
                    text = r if designator else lab
                    x, y = b.fp_x[fi[r]] + ox, b.fp_y[fi[r]] + oy
                    if not ok(text, r, float(x), float(y), ang, designator): good = False; break
                if good: best.append((math.hypot(ox, oy), round(float(ox), 2), round(float(oy), 2), ang))
    return sorted(best)


des = search(True); fun = search(False)
inside_note = 'inside own block outline'
if not des or not fun:
    NEED_INSIDE = False; inside_note = 'NOT inside own block outline (no common offset sits inside the three BNC boxes)'
    des = search(True); fun = search(False)
rep_ = {'designator_offsets_found': len(des), 'function_offsets_found': len(fun), 'designator': des[:3], 'function': fun[:3]}
print(rep_)
json.dump(rep_, open(rep, 'w'), indent=1)
if not des or not fun: sys.exit(0)
def boxes(des_o, fun_o):
    d = {r: (S.text_box(r, b.fp_x[fi[r]] + des_o[1], b.fp_y[fi[r]] + des_o[2], 1.0, H, des_o[3])) for r in BNC}
    f = {r: (S.text_box(lab, b.fp_x[fi[r]] + fun_o[1], b.fp_y[fi[r]] + fun_o[2], 1.0, H, fun_o[3])) for r, lab in BNC.items()}
    return d, f


def cross_ok(des_o, fun_o):
    d, f = boxes(des_o, fun_o)
    for r1 in BNC:
        for r2 in BNC:
            if r1 < r2 and lgap(d[r1], d[r2]) < 1.0: return False       # LR-11: designators 1.0 mm apart
            if r1 < r2 and lgap(f[r1], f[r2]) < 0.5: return False
            if lgap(d[r1], f[r2]) < 0.5: return False
    return True


pair = next(((d_, f_) for d_ in des for f_ in fun if cross_ok(d_, f_)), None)
if not pair: print('no designator and function offsets clear each other across the three BNCs'); sys.exit(0)
(dox, doy, dang), (fox, foy, fang) = pair[0][1:], pair[1][1:]
print('designator offset', dox, doy, dang, '; function label offset', fox, foy, fang, '; ', inside_note)
for f in pb.GetFootprints():
    r = f.GetReference()
    if r in BNC:
        rf = f.Reference(); rf.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(float(b.fp_x[fi[r]] + dox) + 50.0), pcbnew.FromMM(150.0 - float(b.fp_y[fi[r]] + doy)))); rf.SetTextAngleDegrees(float(dang)); rf.SetVisible(True)
pcbnew.SaveBoard('/tmp/scratch_bnc.kicad_pcb', pb)
sc = open('/tmp/scratch_bnc.kicad_pcb').read(); t = txt
for r, lab in BNC.items():
    i = t.index('(property "Reference" "%s"' % r); m = re.compile(r'\(at ([\-\d.]+) ([\-\d.]+)(?: ([\-\d.]+))?\)').search(t, i)
    j = sc.index('(property "Reference" "%s"' % r); ms = re.compile(r'\(at ([\-\d.]+) ([\-\d.]+)(?: ([\-\d.]+))?\)').search(sc, j)
    t = t[:m.start()] + '(at %s %s %s)' % (ms.group(1), ms.group(2), ms.group(3) or '0') + t[m.end():]
    g = re.search(r'\(gr_text "%s"\s+\(at ([\-\d.]+) ([\-\d.]+)(?: ([\-\d.]+))?\)' % re.escape(lab), t)
    nx, ny = b.fp_x[fi[r]] + fox + 50.0, 150.0 - (b.fp_y[fi[r]] + foy)
    t = t[:g.start(1)] + '%.3f %.3f %g' % (nx, ny, fang) + t[g.end(0) - 1:]
open(out, 'w').write(t)
print('wrote', out)
