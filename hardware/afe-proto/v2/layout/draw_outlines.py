"""Draw the outlines of v2/layout/outlines.py that a board's F.Silkscreen lacks, and nothing else.

    python3 v2/layout/draw_outlines.py BOARD.kicad_pcb [--write OUT.kicad_pcb]     list what is missing; with --write, add it

The table (outlines.py) is the one source: the main areas' dashed outlines were drawn by the block scripts and
outlines_from_silk.py reads them back; a rectangle of the table that the silk does not hold (the AWG's BNC outline, which the
board had only as a bracket) is added here as plain 0.15 mm F.Silkscreen lines, minus the parts of its sides that are already
drawn. Silk only: no copper, no part, no designator is touched. Pure text editing, no KiCad needed.
"""
import os
import sys
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', '..'))
import outlines  # noqa: E402
import outlines_from_silk as ofs  # noqa: E402

TOL = ofs.TOL


def missing(table_rects, found_rects, tol=TOL):
    """the table rectangles (Due mm) with no found rectangle equal within tol"""
    return [r for r in table_rects if not any(max(abs(p - q) for p, q in zip(r, f)) <= tol for f in found_rects)]


def _uncovered(a, b, drawn):
    """[a, b] minus the (lo, hi) intervals drawn, as the intervals left (pieces shorter than 0.2 mm dropped)"""
    out, lo = [], a
    for x, y in sorted(drawn):
        if y <= lo or x >= b:
            continue
        if x > lo:
            out.append((lo, x))
        lo = max(lo, y)
    if lo < b:
        out.append((lo, b))
    return [(x, y) for x, y in out if y - x >= 0.2]


def rect_segments(rect_due, existing):
    """[(x0, y0, x1, y1)] KiCad sheet mm: the four sides of the rectangle (given in Due mm) less what `existing` (sheet-mm
    axis-aligned segments) already draws on the same lines"""
    x0, y1 = rect_due[0] + 50, 150 - rect_due[1]
    x1, y0 = rect_due[2] + 50, 150 - rect_due[3]
    segs = []
    for (a, b, c, d) in ((x0, y0, x1, y0), (x0, y1, x1, y1), (x0, y0, x0, y1), (x1, y0, x1, y1)):
        horiz = abs(b - d) < 1e-9
        line = b if horiz else a
        lo, hi = (min(a, c), max(a, c)) if horiz else (min(b, d), max(b, d))
        drawn = [(min(s[0], s[2]), max(s[0], s[2])) if horiz else (min(s[1], s[3]), max(s[1], s[3]))
                 for s in existing if (abs(s[1] - line) < 0.05 and abs(s[3] - line) < 0.05 if horiz else abs(s[0] - line) < 0.05 and abs(s[2] - line) < 0.05)]
        for u, v in _uncovered(lo, hi, drawn):
            segs.append((u, line, v, line) if horiz else (line, u, line, v))
    return segs


def gr_line(seg):
    x0, y0, x1, y1 = seg
    return (f'\t(gr_line\n\t\t(start {x0:.4f} {y0:.4f})\n\t\t(end {x1:.4f} {y1:.4f})\n\t\t(stroke\n\t\t\t(width {ofs.STROKE:g})\n'
            f'\t\t\t(type default)\n\t\t)\n\t\t(layer "F.SilkS")\n\t\t(uuid "{uuid.uuid4()}")\n\t)\n')


def _drawn_fraction(edges, segs, tol=0.02):
    """fraction of the length of `edges` (Due mm) that `segs` (Due mm) draw"""
    tot = cov = 0.0
    for ex0, ey0, ex1, ey1 in edges:
        horiz = abs(ey0 - ey1) < tol
        lo, hi = (min(ex0, ex1), max(ex0, ex1)) if horiz else (min(ey0, ey1), max(ey0, ey1))
        tot += hi - lo
        iv = sorted((max(lo, min(a, c)), min(hi, max(a, c))) if horiz else (max(lo, min(b, d)), min(hi, max(b, d)))
                    for a, b, c, d in segs if (horiz and abs(b - d) < tol and abs(b - ey0) < tol) or ((not horiz) and abs(a - c) < tol and abs(a - ex0) < tol))
        end = lo
        for a, b in iv:
            if b > end and b > a:
                cov += b - max(a, end)
                end = b
    return cov / tot if tot else 1.0


def missing_polygons(text, tol=0.02):
    """table rectangles (Due mm) whose own sides, where they lie on the boundary of their block's union, are drawn less than a third: the outlines are solid
    polygons (a side two rectangles of a block share is not drawn, and a side stops short of other silk), so 'present' is a fraction, not an exact match"""
    segs = [(a - 50, 150 - b, c - 50, 150 - d) for a, b, c, d in ofs.silk_segments(text)]
    out = []
    for blk, rects in outlines.RECTS.items():
        bnd = outlines.boundary([tuple(r) for r in rects])
        for r in rects:
            mine = [e for e in bnd if r[0] - tol <= min(e[0], e[2]) and max(e[0], e[2]) <= r[2] + tol and r[1] - tol <= min(e[1], e[3]) and max(e[1], e[3]) <= r[3] + tol]
            mine = outlines.clip_boxes(mine, outlines.GAP_BOXES)                              # where no outline is drawn by design (round U101) is not missing
            if mine and _drawn_fraction(mine, segs) < 0.33:
                out.append(tuple(r))
    return out


def draw(text, table=None):
    """(new text, [rectangles added]). With no table: the polygons of outlines.RECTS, a rectangle being added when its own sides are drawn less than a third"""
    if table is None:
        add = missing_polygons(text)
    else:
        found = sorted(ofs.to_due_rect(r) for r in ofs.rects_from_segments(ofs.silk_segments(text)))
        add = missing(table, found)
    existing = ofs.silk_segments(text)
    new = ''.join(gr_line(s) for r in add for s in rect_segments(r, existing))
    if not new:
        return text, []
    i = text.rstrip().rfind(')')
    return text[:i] + new + text[i:], add


def main(argv):
    path = argv[0]
    text = open(path).read()
    new, add = draw(text)
    print('missing from the silk:', add or 'nothing')
    if '--write' in argv and add:
        with open(argv[argv.index('--write') + 1], 'w') as f:
            f.write(new)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
