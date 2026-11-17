"""Outline lines of the block rectangles, broken where a line would cross a pad, a footprint's silk or a forced label.

    outline_segments(lb, cfg) -> {block: [(x0, y0, x1, y1), ...]}   a shared line is drawn once (by the first block)

Names: OUTLINE, OUTLINE_IGNORE (boxes holding other drawn lines), OUTLINE_BREAK_CLEAR (0.2 mm of break each side of what it avoids), OUTLINE_LINE_HALF (0.075), FORCE (a forced label breaks any line it touches)."""
from .placer import Cfg, NEEDS, lab_box
from .. import outlines


def outline_segments(lb, cfg):
    c = Cfg(cfg, NEEDS['outline_segments'])
    h, bc = c.OUTLINE_LINE_HALF, c.OUTLINE_BREAK_CLEAR
    obs = [b for p in lb.parts.values() for b in p.pads] + list(lb.silk)
    for r, (x, y, a) in c.FORCE.items():
        b = lab_box(c, r, x, y, a)
        obs.append((b[0] + 0.05, b[1] + 0.05, b[2] - 0.05, b[3] - 0.05))      # a forced label may touch a line (the owner's spot); only crossing it breaks the line
    segs = {}
    for blk, rs in c.OUTLINE.items():
        out = []
        for q in rs:
            out += [(q[0], q[1], q[2], q[1]), (q[2], q[1], q[2], q[3]), (q[0], q[3], q[2], q[3]), (q[0], q[1], q[0], q[3])]
        segs[blk] = out
    result, seen = {}, set()
    for blk, sg in segs.items():
        keep = []
        for (a, d, e, f) in sg:
            horiz = abs(d - f) < 1e-9
            lo, hi = (min(a, e), max(a, e)) if horiz else (min(d, f), max(d, f))
            fixed = d if horiz else a
            ivs = []
            for ob in obs:
                if horiz:
                    hit = ob[1] - 0.03 < fixed + h and fixed - h < ob[3] + 0.03 and ob[0] - 0.03 < hi and lo < ob[2] + 0.03
                    iv = (ob[0] - bc, ob[2] + bc)
                else:
                    hit = ob[0] - 0.03 < fixed + h and fixed - h < ob[2] + 0.03 and ob[1] - 0.03 < hi and lo < ob[3] + 0.03
                    iv = (ob[1] - bc, ob[3] + bc)
                if hit:
                    ivs.append(iv)
            ivs.sort()
            cur, pieces = lo, []
            for p0, p1 in ivs:
                if p0 > cur:
                    pieces.append((cur, min(p0, hi)))
                cur = max(cur, p1)
            if cur < hi:
                pieces.append((cur, hi))
            for p0, p1 in pieces:
                if p1 - p0 > 0.05:
                    s = (p0, fixed, p1, fixed) if horiz else (fixed, p0, fixed, p1)
                    k = tuple(round(v, 2) for v in s)
                    if k not in seen:
                        seen.add(k)
                        keep.append(s)
        result[blk] = keep
    return result


def validate_outline(lb, drawn, cfg, tol=0.01):
    """problems with the drawn outline segments `drawn`; the check is pcbkit.outlines.check_outline_lines (a forced label may touch a line, only crossing it counts)"""
    c = Cfg(cfg, NEEDS['validate_outline'])
    obs = [b for p in lb.parts.values() for b in p.pads] + list(lb.silk)
    for r, (x, y, a) in c.FORCE.items():
        b = lab_box(c, r, x, y, a)
        obs.append((b[0] + 0.05, b[1] + 0.05, b[2] - 0.05, b[3] - 0.05))
    return outlines.check_outline_lines(drawn, {k: [tuple(q) for q in v] for k, v in c.OUTLINE.items()}, obs, c.OUTLINE_LINE_HALF, c.OUTLINE_BREAK_CLEAR, c.OUTLINE_IGNORE, tol)
