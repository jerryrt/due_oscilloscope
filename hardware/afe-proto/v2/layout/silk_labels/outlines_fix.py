"""outlines_fix.py IN.kicad_pcb OUT.kicad_pcb RECTS.json    (plain Python, text splice; silk only)

Block outlines as simple closed RECTANGLES from v2/layout/outlines.py RECTS (main's table), with REFCAL's second rectangle cut back so that it no longer
overlaps CH2's. Every board-level F.SilkS gr_line that lies on an edge of the old table's rectangles is removed (the old drawing was dashed: a break is a missing
dash) and each rectangle of the new table is drawn as four solid 0.15 mm lines. RECTS.json receives the new table. Nothing but silk lines changes."""
import sys, re, json, uuid, math, importlib.util

inp, out, rects_out = sys.argv[1:4]
spec = importlib.util.spec_from_file_location('outlines', '/work/_work/outlines_main.py')   # the branch's own table
ol = importlib.util.module_from_spec(spec); spec.loader.exec_module(ol)
old = {k: [tuple(r) for r in v] for k, v in ol.RECTS.items()}
new = {k: [tuple(r) for r in v] for k, v in old.items()}
CH2_W = min(r[0] for r in old['CH2'] if r[0] < 98)                                   # CH2's main rectangle starts here (69.0)
new['REFCAL'] = [r if not (abs(r[0] - 64.6) < 0.01 and abs(r[1] - 18.6) < 0.01) else (r[0], r[1], round(CH2_W - 0.1, 3), r[3]) for r in old['REFCAL']]
txt = open(inp).read()
B = lambda x, y: (x + 50.0, 150.0 - y)
edges_old = []
for rs in old.values():
    for x0, y0, x1, y1 in rs: edges_old += [((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))]


def on_edge(p, q, e, tol=0.06):
    (a, b), (c, d) = e
    if abs(a - c) < 1e-6 and abs(p[0] - a) < tol and abs(q[0] - a) < tol and min(b, d) - tol <= min(p[1], q[1]) and max(p[1], q[1]) <= max(b, d) + tol: return True
    if abs(b - d) < 1e-6 and abs(p[1] - b) < tol and abs(q[1] - b) < tol and min(a, c) - tol <= min(p[0], q[0]) and max(p[0], q[0]) <= max(a, c) + tol: return True
    return False


removed = 0
def drop(m):
    global removed
    body = m.group(0)
    if '(layer "F.SilkS")' not in body: return body
    s = re.search(r'\(start ([-\d.]+) ([-\d.]+)\)', body); e = re.search(r'\(end ([-\d.]+) ([-\d.]+)\)', body)
    p = (float(s.group(1)) - 50.0, 150.0 - float(s.group(2))); q = (float(e.group(1)) - 50.0, 150.0 - float(e.group(2)))
    stub = abs(p[0] - q[0]) + abs(p[1] - q[1]) < 1.2 and any(r[0] - 0.06 <= p[0] <= r[2] + 0.06 and r[1] - 0.06 <= p[1] <= r[3] + 0.06 for rs in old.values() for r in rs)    # an old bracket's stub
    if stub or any(on_edge(p, q, ed) for ed in edges_old): removed += 1; return ''
    return body


txt = re.sub(r'\n\t\(gr_line(?:(?!\n\t\)).)*\n\t\)', drop, txt, flags=re.S)
import numpy as np
sys.path.insert(0, '/work/hardware/afe-proto'); sys.path.append('/usr/lib/python3/dist-packages')
import pcbnew
pb = pcbnew.LoadBoard(inp); mmf = pcbnew.ToMM
due = lambda v: (mmf(v.x) - 50.0, 150.0 - mmf(v.y))
pad_boxes, silk_segs = [], []
for f in pb.GetFootprints():
    for p in f.Pads():
        bb = p.GetBoundingBox(); pad_boxes.append((mmf(bb.GetX()) - 50.0, 150.0 - mmf(bb.GetBottom()), mmf(bb.GetRight()) - 50.0, 150.0 - mmf(bb.GetY())))
    for g in f.GraphicalItems():
        if g.GetLayer() != pcbnew.F_SilkS or not hasattr(g, 'GetShape'): continue
        w = mmf(g.GetWidth())
        if g.GetShape() == pcbnew.SHAPE_T_SEGMENT:
            (x0, y0), (x1, y1) = due(g.GetStart()), due(g.GetEnd()); silk_segs.append((x0, y0, x1, y1, w))
        else:
            bx = g.GetBoundingBox(); x0, y1 = due(bx.GetOrigin()); x1, y0 = due(pcbnew.VECTOR2I(bx.GetRight(), bx.GetBottom()))
            for a_, c_ in (((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))): silk_segs.append((*a_, *c_, w))
CLEAR = 0.2


def seg_dist(px, py, x0, y0, x1, y1):
    dx, dy = x1 - x0, y1 - y0; L = dx * dx + dy * dy
    t = 0.0 if L == 0 else max(0.0, min(1.0, ((px - x0) * dx + (py - y0) * dy) / L))
    return ((px - x0 - t * dx) ** 2 + (py - y0 - t * dy) ** 2) ** 0.5


def blocked(px, py):
    for x0, y0, x1, y1 in pad_boxes:                                        # 0.2 mm clear of a pad, and half the 0.15 mm line
        if x0 - CLEAR - 0.075 <= px <= x1 + CLEAR + 0.075 and y0 - CLEAR - 0.075 <= py <= y1 + CLEAR + 0.075: return True
    for x0, y0, x1, y1, w in silk_segs:
        if seg_dist(px, py, x0, y0, x1, y1) < CLEAR + 0.075 + w / 2: return True
    return False


add = ''; reopened = 0
for blk, rs in new.items():
    for ri, (x0, y0, x1, y1) in enumerate(rs):
        for ei, (p, q) in enumerate((((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0)))):
            n = max(2, int(round(math.hypot(q[0] - p[0], q[1] - p[1]) / 0.05)) + 1)
            pts = [(p[0] + (q[0] - p[0]) * k / (n - 1), p[1] + (q[1] - p[1]) * k / (n - 1)) for k in range(n)]
            free = [not blocked(*pt) for pt in pts]
            k = 0; piece = 0
            while k < n:
                if not free[k]: k += 1; continue
                j = k
                while j + 1 < n and free[j + 1]: j += 1
                if math.hypot(pts[j][0] - pts[k][0], pts[j][1] - pts[k][1]) >= 0.3:
                    (px, py), (qx, qy) = B(*pts[k]), B(*pts[j])
                    add += '\n\t(gr_line\n\t\t(start %s %s)\n\t\t(end %s %s)\n\t\t(stroke\n\t\t\t(width 0.15)\n\t\t\t(type default)\n\t\t)\n\t\t(layer "F.SilkS")\n\t\t(uuid "%s")\n\t)' % (
                        round(px, 4), round(py, 4), round(qx, 4), round(qy, 4), uuid.uuid5(uuid.NAMESPACE_URL, 'outline/%s/%d/%d/%d' % (blk, ri, ei, piece)))
                    piece += 1
                k = j + 1
            if piece != 1 or not all(free): reopened += 1
i = txt.rindex('\n)')
txt = txt[:i] + add + txt[i:]
open(out, 'w').write(txt)
json.dump({k: [list(r) for r in v] for k, v in new.items()}, open(rects_out, 'w'), indent=1)
print('removed', removed, 'old outline segments; rectangles', sum(len(v) for v in new.values()), '; edges reopened at a pad or footprint silk:', reopened, '; REFCAL', new['REFCAL'])
