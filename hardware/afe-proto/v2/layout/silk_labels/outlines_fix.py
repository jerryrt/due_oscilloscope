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
# AFE-1 way (afe1-labels kicad/labels/rects.py): ONE plain rectangle per block around its main group, and no extra small boxes; the strays sit outside. So REFCAL's second
# rectangle (64.6, 18.6, 68.9, 26.0) and CH1's small box (60.4, 34.6, 64.0, 36.8) are dropped; the three BNC boxes stay.
new['REFCAL'] = [r for r in old['REFCAL'] if not (abs(r[0] - 64.6) < 0.01 and abs(r[1] - 18.6) < 0.01)]
new['CH1'] = [r for r in old['CH1'] if not (abs(r[0] - 60.4) < 0.01 and abs(r[1] - 34.6) < 0.01)]
import os
if os.environ.get('MAINRECTS'):                      # AFE-1's rects.py (descent + grow) result for the main rectangle of each block; the BNC boxes are handled below
    mr = json.load(open(os.environ['MAINRECTS']))
    for k, v in mr.items(): new[k] = [tuple(round(float(c), 3) for c in v)] + [r for r in new[k] if r[0] >= 98.0]
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
BREAKS = []
for f in pb.GetFootprints():
    for p in f.Pads():
        bb = p.GetBoundingBox(); pad_boxes.append((mmf(bb.GetX()) - 50.0, 150.0 - mmf(bb.GetBottom()), mmf(bb.GetRight()) - 50.0, 150.0 - mmf(bb.GetY()), f.GetReference()))
    for g in f.GraphicalItems():
        if g.GetLayer() != pcbnew.F_SilkS or not hasattr(g, 'GetShape'): continue
        w = mmf(g.GetWidth())
        if g.GetShape() == pcbnew.SHAPE_T_SEGMENT:
            (x0, y0), (x1, y1) = due(g.GetStart()), due(g.GetEnd()); silk_segs.append((x0, y0, x1, y1, w, f.GetReference()))
        else:
            bx = g.GetBoundingBox(); x0, y1 = due(bx.GetOrigin()); x1, y0 = due(pcbnew.VECTOR2I(bx.GetRight(), bx.GetBottom()))
            for a_, c_ in (((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))): silk_segs.append((*a_, *c_, w, f.GetReference()))
# ---- the BNC boxes, as AFE-1's round 11 (afe1-labels a49fe27f, kicad/labels/place3.py) draws them: ONE margin m on all four sides of every box, measured line centre to the BNC's own footprint
# silk rectangle, m = (input pitch - silk height) / 2, so the J101 and J201 boxes share one line; the J301 box stands apart
BNCS = {'J101': 'CH1', 'J201': 'CH2', 'J301': 'AWG'}
sb_ = {}; org = {}; bd_ = {}
for f in pb.GetFootprints():
    if f.GetReference() in BNCS:
        sx = pcbnew.BOX2I(); bx = pcbnew.BOX2I()
        for g in f.GraphicalItems():
            if g.GetLayer() == pcbnew.F_SilkS: sx.Merge(g.GetBoundingBox())
            if g.GetLayer() == pcbnew.F_Fab: bx.Merge(g.GetBoundingBox())
        sb_[f.GetReference()] = (mmf(sx.GetX()) - 50.0, 150.0 - mmf(sx.GetBottom()), mmf(sx.GetRight()) - 50.0, 150.0 - mmf(sx.GetY())); org[f.GetReference()] = 150.0 - mmf(f.GetPosition().y)
        bd_[f.GetReference()] = (mmf(bx.GetX()) - 50.0, 150.0 - mmf(bx.GetBottom()), mmf(bx.GetRight()) - 50.0, 150.0 - mmf(bx.GetY()))
pitch = abs(org['J101'] - org['J201']); silk_h = sb_['J101'][3] - sb_['J101'][1]
M = round((pitch - silk_h) / 2, 3)
box_report = {'input pitch (J101 origin to J201 origin)': round(pitch, 3), 'silk rectangle height (the BNC footprint silk, along the pitch axis)': round(silk_h, 3), 'margin m = (pitch - silk height)/2, on all four sides': M, 'boxes': {}}
for r, blk in BNCS.items():
    sx0, sy0, sx1, sy1 = sb_[r]
    old_ = [q for q in new[blk] if q[0] >= 98.0 and q[1] <= org[r] <= q[3]][0]
    nb = (round(sx0 - M, 3), round(sy0 - M, 3), round(sx1 + M, 3), round(sy1 + M, 3))
    new[blk] = [nb if q == old_ else q for q in new[blk]]
    box_report['boxes'][r] = {'old': list(old_), 'new': list(nb), 'footprint silk rectangle': [round(v, 3) for v in sb_[r]], 'body (F.Fab)': [round(v, 3) for v in bd_[r]],
                              'margins to the silk rectangle left/right/bottom/top': [round(sx0 - nb[0], 3), round(nb[2] - sx1, 3), round(sy0 - nb[1], 3), round(nb[3] - sy1, 3)],
                              'right edge to the board edge (x 117.05)': round(117.05 - nb[2], 3), 'clear width in the left margin (line edge 0.075 to the silk edge)': round(sx0 - (nb[0] + 0.075), 3)}
ob = sorted(box_report['boxes'], key=lambda r: box_report['boxes'][r]['new'][1])
box_report['gaps between neighbouring boxes (top line of the lower to bottom line of the upper; 0 = one shared line)'] = {'%s-%s' % (a_, b_): round(box_report['boxes'][b_]['new'][1] - box_report['boxes'][a_]['new'][3], 3) for a_, b_ in zip(ob, ob[1:])}
json.dump(box_report, open(rects_out.replace('.json', '_boxes.json'), 'w'), indent=1)
CLEAR = 0.2


def seg_dist(px, py, x0, y0, x1, y1):
    dx, dy = x1 - x0, y1 - y0; L = dx * dx + dy * dy
    t = 0.0 if L == 0 else max(0.0, min(1.0, ((px - x0) * dx + (py - y0) * dy) / L))
    return ((px - x0 - t * dx) ** 2 + (py - y0 - t * dy) ** 2) ** 0.5


def blocked(px, py):
    for x0, y0, x1, y1, rf in pad_boxes:                                    # 0.2 mm clear of a pad, and half the 0.15 mm line
        if x0 - CLEAR - 0.075 <= px <= x1 + CLEAR + 0.075 and y0 - CLEAR - 0.075 <= py <= y1 + CLEAR + 0.075: return 'pad of ' + rf
    for x0, y0, x1, y1, w, rf in silk_segs:
        if seg_dist(px, py, x0, y0, x1, y1) < CLEAR + 0.075 + w / 2: return 'silk of ' + rf
    return None


add = ''; reopened = 0; drawn_ = set()
for blk, rs in new.items():
    for ri, (x0, y0, x1, y1) in enumerate(rs):
        for ei, (p, q) in enumerate((((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0)))):
            n = max(2, int(round(math.hypot(q[0] - p[0], q[1] - p[1]) / 0.05)) + 1)
            pts = [(p[0] + (q[0] - p[0]) * k / (n - 1), p[1] + (q[1] - p[1]) * k / (n - 1)) for k in range(n)]
            cause = [blocked(*pt) for pt in pts]; free = [c_ is None for c_ in cause]
            k = 0; piece = 0
            if not all(free):
                kk = 0
                while kk < n:                                   # the gaps of this edge: where, how long, and why
                    if free[kk]: kk += 1; continue
                    jj = kk
                    while jj + 1 < n and not free[jj + 1]: jj += 1
                    BREAKS.append({'block': blk, 'rect': ri, 'edge': ['S', 'E', 'N', 'W'][ei], 'from': [round(pts[kk][0], 2), round(pts[kk][1], 2)], 'to': [round(pts[jj][0], 2), round(pts[jj][1], 2)], 'because': sorted(set(cause[kk:jj + 1]))})
                    kk = jj + 1
            while k < n:
                if not free[k]: k += 1; continue
                j = k
                while j + 1 < n and free[j + 1]: j += 1
                key_ = (round(pts[k][0], 3), round(pts[k][1], 3), round(pts[j][0], 3), round(pts[j][1], 3))
                key_ = key_ if key_[:2] <= key_[2:] else key_[2:] + key_[:2]
                if math.hypot(pts[j][0] - pts[k][0], pts[j][1] - pts[k][1]) >= 0.3 and key_ not in drawn_:
                    drawn_.add(key_)
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
json.dump(BREAKS, open(rects_out.replace('.json', '_breaks.json'), 'w'), indent=1)
print('removed', removed, 'old outline segments; rectangles', sum(len(v) for v in new.values()), '; edges reopened at a pad or footprint silk:', reopened, '; REFCAL', new['REFCAL'])
