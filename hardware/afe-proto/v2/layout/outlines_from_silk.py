"""Read the block outlines ACTUALLY drawn on a board's F.Silkscreen, as rectangles in Due mm (x right, y up, origin at the Due's
lower-left corner: x - 50, 150 - y of KiCad's sheet coordinates, the transform of pcbtools.boardio.to_due).

    python3 v2/layout/outlines_from_silk.py BOARD.kicad_pcb          print the rectangles found
    python3 v2/layout/outlines_from_silk.py BOARD.kicad_pcb --check  exit 1 unless they equal outlines.RECTS (within TOL)

An outline is drawn as dashed or broken lines (a gap where a part or a label sits), so a rectangle is recovered as four chains:
horizontal and vertical axis-aligned F.Silkscreen segments of the outline stroke width are merged into runs across gaps of at
most GAP mm, and a rectangle is a pair of vertical runs and a pair of horizontal runs of which each side is one run that
reaches to within SLACK mm of both its corners. Candidates that are the same rectangle within a millimetre (a block's edge drawn 0.1 mm off its
neighbour's) are one cluster, the best covered wins; a rectangle that only encloses smaller winners (two BNC outlines that a
merged run would join) is dropped. The text only needs the segments: no part list and no layout script.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..'))
from pcbtools import sexpr  # noqa: E402

STROKE = 0.15          # mm: the outline stroke (arrows and the words are drawn at 0.2 and are not outlines)
GAP = 5.0              # mm: the longest break in a drawn horizontal side (a part or a label sits there)
GAP_V = 1.9            # mm: and in a vertical one, which here has only short breaks; 2.0 mm is the clear space between two BNC outlines
SLACK = 2.0            # mm: a side is drawn as one run reaching to within this of both its corners
MIN_SIDE = 2.1         # mm: no outline is narrower than this (two BNC outlines 2.0 mm apart are not a rectangle between them)
IOU_SAME = 0.75        # two candidates with more overlap than this are one rectangle drawn twice
TOL = 0.15             # mm: --check, and the test, call two rectangles equal within this


def silk_segments(text, layer='F.SilkS', width=STROKE):
    """axis-aligned straight segments of `layer` drawn at `width`: [(x0, y0, x1, y1)] in KiCad sheet mm. Non-axis-aligned ones
    (arrow heads) are not outline sides and are left out."""
    out = []
    for e in sexpr.parse(text):
        if not (isinstance(e, list) and e and e[0] == 'gr_line'):
            continue
        d = {x[0]: x for x in e[1:] if isinstance(x, list) and x}
        if str(sexpr.first(e, 'layer')[1]) != layer:
            continue
        w = float(sexpr.first(sexpr.first(e, 'stroke'), 'width')[1])
        a, b = d['start'], d['end']
        x0, y0, x1, y1 = float(a[1]), float(a[2]), float(b[1]), float(b[2])
        if abs(w - width) < 1e-6 and (abs(x0 - x1) < 1e-6 or abs(y0 - y1) < 1e-6):
            out.append((x0, y0, x1, y1))
    return out


def _merge(iv, gap):
    iv = sorted(iv)
    o = [list(iv[0])]
    for a, b in iv[1:]:
        if a - o[-1][1] <= gap:
            o[-1][1] = max(o[-1][1], b)
        else:
            o.append([a, b])
    return o


def _cover(runs, a, b, slack):
    """(drawn fraction of the side from a to b, how far the runs touching it run on past its corners, as a fraction of it, and whether one run draws it corner to corner within slack)"""
    inside = sum(max(0.0, min(y, b) - max(x, a)) for x, y in runs)
    ok = any(x <= a + slack and y >= b - slack for x, y in runs)
    over = sum((y - x) - max(0.0, min(y, b) - max(x, a)) for x, y in runs if min(y, b) > max(x, a))
    return inside / (b - a), ok, over / (b - a)


def _iou(p, q):
    w = min(p[2], q[2]) - max(p[0], q[0])
    h = min(p[3], q[3]) - max(p[1], q[1])
    if w <= 0 or h <= 0:
        return 0.0
    i = w * h
    return i / ((p[2] - p[0]) * (p[3] - p[1]) + (q[2] - q[0]) * (q[3] - q[1]) - i)


def rects_from_segments(segs, gap=GAP, gap_v=GAP_V, slack=SLACK, min_side=MIN_SIDE):
    """[(x0, y0, x1, y1)] in KiCad sheet mm (y down), sorted: the rectangles the segments outline"""
    H, V = {}, {}
    for x0, y0, x1, y1 in segs:
        if abs(y0 - y1) < 1e-6:
            H.setdefault(round(y0, 3), []).append(tuple(sorted((x0, x1))))
        else:
            V.setdefault(round(x0, 3), []).append(tuple(sorted((y0, y1))))
    H = {k: _merge(v, gap) for k, v in H.items()}
    V = {k: _merge(v, gap_v) for k, v in V.items()}
    xs, ys = sorted(V), sorted(H)
    cand = []
    for i, xa in enumerate(xs):
        for xb in xs[i + 1:]:
            for j, ya in enumerate(ys):
                for yb in ys[j + 1:]:
                    if xb - xa < min_side or yb - ya < min_side:
                        continue
                    c = [_cover(V[xa], ya, yb, slack), _cover(V[xb], ya, yb, slack), _cover(H[ya], xa, xb, slack), _cover(H[yb], xa, xb, slack)]
                    if all(v[1] for v in c):
                        cand.append(((xa, ya, xb, yb), sum(v[0] - 0.5 * min(v[2], 1.0) for v in c) / 4, (xb - xa) * (yb - ya)))
    # within a cluster the best score wins (drawn fraction, less half of how far the sides' runs overshoot the corners), then the
    # smaller one
    cand.sort(key=lambda t: (-round(t[1], 2), t[2]))
    win = []
    for r, _q, _a in cand:
        if all(_iou(r, w) < IOU_SAME for w in win):
            win.append(r)

    def encloses(p, q):
        return p != q and p[0] <= q[0] + 0.01 and p[1] <= q[1] + 0.01 and p[2] >= q[2] - 0.01 and p[3] >= q[3] - 0.01
    win = [r for r in win if not any(encloses(r, w) for w in win)]
    return sorted(win)


def to_due_rect(r):
    """KiCad sheet rectangle (y down) -> Due mm (y up), rounded to 0.01"""
    return (round(r[0] - 50, 2), round(150 - r[3], 2), round(r[2] - 50, 2), round(150 - r[1], 2))


def outlines_in(path):
    with open(path) as f:
        return sorted(to_due_rect(r) for r in rects_from_segments(silk_segments(f.read())))


def same(a, b, tol=TOL):
    """two rectangle lists equal within tol, rectangle for rectangle"""
    a, b = sorted(a), sorted(b)
    return len(a) == len(b) and all(max(abs(p - q) for p, q in zip(r, s)) <= tol for r, s in zip(a, b))


def main(argv):
    path = argv[0]
    found = outlines_in(path)
    for r in found:
        print(r)
    if '--check' in argv:
        sys.path.insert(0, HERE)
        import outlines
        want = outlines.all_rects()
        ok = same(found, want)
        print('MATCH' if ok else f'MISMATCH: table has {len(want)}, silk has {len(found)}')
        return 0 if ok else 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
