"""Outline lines of the block rectangles, broken where a line would cross a pad, a footprint's silk or a forced label.

    outline_segments(lb, cfg) -> {block: [(x0, y0, x1, y1), ...]}   a shared line is drawn once (by the first block)

Names: OUTLINE, OUTLINE_IGNORE (boxes holding other drawn lines), OUTLINE_BREAK_CLEAR (0.2 mm of break each side of what it avoids), OUTLINE_LINE_HALF (0.075), FORCE (a forced label breaks any line it touches)."""
from .placer import Cfg, NEEDS, lab_box


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
    """problems with the drawn outline segments `drawn` [(x0, y0, x1, y1)]: a line off every rectangle edge; two lines drawn over each other; a line across a pad, a footprint's silk or a forced label;
    an edge closed except where something is: a gap with nothing there, or a break that stops short of 0.2 mm clear (OUTLINE_BREAK_CLEAR) on a side."""
    c = Cfg(cfg, NEEDS['validate_outline'])
    h, bc = c.OUTLINE_LINE_HALF, c.OUTLINE_BREAK_CLEAR
    obs = [b for p in lb.parts.values() for b in p.pads] + list(lb.silk)
    for r, (x, y, a) in c.FORCE.items():
        b = lab_box(c, r, x, y, a)
        obs.append((b[0] + 0.05, b[1] + 0.05, b[2] - 0.05, b[3] - 0.05))
    edges = []
    for blk, rs in c.OUTLINE.items():
        for q in rs:
            edges += [('h', q[1], q[0], q[2]), ('h', q[3], q[0], q[2]), ('v', q[0], q[1], q[3]), ('v', q[2], q[1], q[3])]
    probs = []
    segs = [(min(s[0], s[2]), min(s[1], s[3]), max(s[0], s[2]), max(s[1], s[3])) for s in drawn]
    segs = [s for s in segs if not any(q[0] - tol <= s[0] and s[2] <= q[2] + tol and q[1] - tol <= s[1] and s[3] <= q[3] + tol for q in c.OUTLINE_IGNORE)]      # other drawings that are not outline lines
    on = {}
    for i, s in enumerate(segs):
        horiz = abs(s[1] - s[3]) < tol
        e = next((k for k, (o, f, a, b) in enumerate(edges) if (o == 'h') == horiz and abs((s[1] if horiz else s[0]) - f) < tol and s[(0 if horiz else 1)] >= a - tol and s[(2 if horiz else 3)] <= b + tol), None)
        if e is None:
            probs.append('segment %s lies on no rectangle edge' % (tuple(round(v, 3) for v in s),))
            continue
        on.setdefault(e, []).append((s[0], s[2]) if horiz else (s[1], s[3]))
        for ob in obs:
            hit = (ob[1] - 0.03 < s[3] + h and s[1] - h < ob[3] + 0.03 and ob[0] - 0.03 < s[2] and s[0] < ob[2] + 0.03) if horiz else (ob[0] - 0.03 < s[2] + h and s[0] - h < ob[2] + 0.03 and ob[1] - 0.03 < s[3] and s[1] < ob[3] + 0.03)
            if hit:
                probs.append('segment %s crosses something at %s' % (tuple(round(v, 3) for v in s), tuple(round(v, 3) for v in ob)))
                break
    for k, (o, f, a, b) in enumerate(edges):
        iv = sorted(on.get(k, []))
        for (p0, p1), (q0, q1) in zip(iv, iv[1:]):
            if q0 < p1 - tol:
                probs.append('edge %s %.3f: two lines drawn over each other' % (o, f))
        # uncovered intervals of the edge
        cur, gaps = a, []
        for p0, p1 in iv:
            if p0 > cur + tol:
                gaps.append((cur, p0))
            cur = max(cur, p1)
        if cur < b - tol:
            gaps.append((cur, b))
        shared = any(j != k and edges[j][0] == o and abs(edges[j][1] - f) < tol and edges[j][2] < b and a < edges[j][3] and on.get(j) for j in range(len(edges)))
        for g0, g1 in gaps:
            near = []
            for ob in obs:
                lo, hi = (ob[0], ob[2]) if o == 'h' else (ob[1], ob[3])
                ok_band = (ob[1] - 0.03 < f + h and f - h < ob[3] + 0.03) if o == 'h' else (ob[0] - 0.03 < f + h and f - h < ob[2] + 0.03)
                if ok_band and lo < g1 + bc and g0 - bc < hi:
                    near.append((lo, hi))
            if not near:
                if not shared:
                    probs.append('edge %s %.3f open from %.3f to %.3f with nothing there' % (o, f, g0, g1))
                continue
            lo_min, hi_max = min(lo for lo, hi in near), max(hi for lo, hi in near)
            if g0 > a + tol and g0 > lo_min - bc + tol:
                probs.append('edge %s %.3f: the break starts at %.3f, %.3f clear of what it avoids (needs %.1f)' % (o, f, g0, lo_min - g0, bc))
            if g1 < b - tol and g1 < hi_max + bc - tol:
                probs.append('edge %s %.3f: the break ends at %.3f, %.3f clear of what it avoids (needs %.1f)' % (o, f, g1, g1 - hi_max, bc))
    return probs
