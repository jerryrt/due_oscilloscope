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


def draw(text, table=None):
    """(new text, [rectangles added]) """
    table = outlines.all_rects() if table is None else table
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
