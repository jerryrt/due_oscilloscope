"""python3 redo_outlines.py IN.kicad_pcb OUT.kicad_pcb 'REFCAL=x0,y0,x1,y1;...' 'AWG=x0,y0,x1,y1;x0,...'   (in the image)
Scratch: replace the outline rectangles of the named blocks. Deletes the F.SilkS 0.15 axis-aligned gr_lines that lie on an old boundary edge of those blocks and not on any other
block's boundary, then draws the new polygons (draw_outlines.rect_segments, minus what is already drawn). Prints the new table."""
import sys, re
sys.path.insert(0, '/work/hardware/afe-proto/v2/layout'); sys.path.insert(0, '/work/hardware/afe-proto')
import outlines, draw_outlines as D, outlines_from_silk as ofs
inp, out, *specs = sys.argv[1:]
new = {}
for sp in specs:
    blk, rs = sp.split('=')
    new[blk] = [tuple(float(v) for v in r.split(',')) for r in rs.split(';')]
old = {k: [tuple(r) for r in v] for k, v in outlines.RECTS.items()}
def edges(blks):
    e = []
    for b in blks:
        e += outlines.boundary(old[b])
    return e
mine, others = edges(list(new)), edges([b for b in old if b not in new])
def on(seg, es, tol=0.06):
    x0, y0, x1, y1 = seg
    for ex0, ey0, ex1, ey1 in es:
        if abs(y0 - y1) < tol and abs(ey0 - ey1) < tol and abs(y0 - ey0) < tol and min(x0, x1) >= min(ex0, ex1) - tol and max(x0, x1) <= max(ex0, ex1) + tol: return True
        if abs(x0 - x1) < tol and abs(ex0 - ex1) < tol and abs(x0 - ex0) < tol and min(y0, y1) >= min(ey0, ey1) - tol and max(y0, y1) <= max(ey0, ey1) + tol: return True
    return False
text = open(inp).read()
n = 0
def kill(m):
    global n
    blk = m.group(0)
    if '"F.SilkS"' not in blk or '(width 0.15)' not in blk: return blk
    a = re.search(r'\(start ([\d.\-]+) ([\d.\-]+)\)\s*\(end ([\d.\-]+) ([\d.\-]+)\)', blk)
    x0, y0, x1, y1 = (float(v) for v in a.groups())
    if abs(x0 - x1) > 0.01 and abs(y0 - y1) > 0.01: return blk
    seg = (x0 - 50, 150 - y0, x1 - 50, 150 - y1)
    if on(seg, mine) and not on(seg, others):
        n += 1; return ''
    return blk
text = re.sub(r'\n\t\(gr_line\n.*?\n\t\)', lambda m: kill(m), text, flags=re.S)
print('removed', n, 'outline lines')
for k, v in new.items(): outlines.RECTS[k] = v
text, add = D.draw(text)
print('added rectangles', add)
open(out, 'w').write(text)
import json; json.dump({k: [list(r) for r in v] for k, v in outlines.RECTS.items()}, open(out.replace('.kicad_pcb', '_rects.json'), 'w'))
