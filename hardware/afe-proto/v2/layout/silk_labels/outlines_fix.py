"""outlines_fix.py IN.kicad_pcb OUT.kicad_pcb RECTS.json    (plain Python, text splice; silk only)

Block outlines as simple closed RECTANGLES from v2/layout/outlines.py RECTS (main's table), with REFCAL's second rectangle cut back so that it no longer
overlaps CH2's. Every board-level F.SilkS gr_line that lies on an edge of the old table's rectangles is removed (the old drawing was dashed: a break is a missing
dash) and each rectangle of the new table is drawn as four solid 0.15 mm lines. RECTS.json receives the new table. Nothing but silk lines changes."""
import sys, re, json, uuid, importlib.util

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
add = ''
for blk, rs in new.items():
    for ri, (x0, y0, x1, y1) in enumerate(rs):
        for ei, (p, q) in enumerate((((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0)))):
            (px, py), (qx, qy) = B(*p), B(*q)
            add += '\n\t(gr_line\n\t\t(start %s %s)\n\t\t(end %s %s)\n\t\t(stroke\n\t\t\t(width 0.15)\n\t\t\t(type default)\n\t\t)\n\t\t(layer "F.SilkS")\n\t\t(uuid "%s")\n\t)' % (
                round(px, 4), round(py, 4), round(qx, 4), round(qy, 4), uuid.uuid5(uuid.NAMESPACE_URL, 'outline/%s/%d/%d' % (blk, ri, ei)))
i = txt.rindex('\n)')
txt = txt[:i] + add + txt[i:]
open(out, 'w').write(txt)
json.dump({k: [list(r) for r in v] for k, v in new.items()}, open(rects_out, 'w'), indent=1)
print('removed', removed, 'old outline segments; drew', sum(len(v) for v in new.values()), 'closed rectangles; REFCAL', new['REFCAL'])
