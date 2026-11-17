"""Block rectangles and block membership: which part belongs to which block, which block's rectangle holds which part.

Pure functions on a pcbkit.board.BoardArrays and resolved configuration values (rules.blocks and rules.test_points read the names; see CONFIG.md).
The lines of an outline are drawn by pcbkit.labels; the checks on them (`check_outline_lines`, `check_name_boxes`), on a label's place against rectangles (`label_region_ok`) are here, and pcbkit.labels calls them.
"""
from __future__ import annotations

import math

import numpy as np


def in_rects(P, rects):
    """bool (N,): the point lies in one of the rects (closed)"""
    R = np.array(rects, float).reshape(-1, 4)
    return ((P[:, None, 0] >= R[None, :, 0]) & (P[:, None, 0] <= R[None, :, 2])
            & (P[:, None, 1] >= R[None, :, 1]) & (P[:, None, 1] <= R[None, :, 3])).any(axis=1)


def block_of_parts(b, block, outline):
    """the block of every footprint (a list in footprint order): the configured block of its designator, else the first outline that holds its
    origin, else None"""
    refs = list(b.fp_ref)
    P = np.column_stack([b.fp_x, b.fp_y])
    inout = {k: in_rects(P, rects) for k, rects in outline.items()}

    def of(i):
        v = block.get(refs[i])
        if v is None:
            v = next((k for k in outline if inout[k][i]), None)
        return v
    return [of(i) for i in range(len(refs))]


def membership_findings(b, block, outline, strays=(), edge_block=None, override=(), shared=None, shared_margin=0.0):
    """one finding per block whose rectangles do not hold exactly its parts: 'BLOCK: outline holds [extra] extra, lacks [missing]'.
    Parts of `edge_block` belong to no outline unless listed in `override`; a part in `shared` (ref -> home block) is a part that straddles
    two rectangles: held to its home block's outline within `shared_margin` and counted in no other; `strays` are named parts allowed outside
    their own block's rectangles, but never inside another's"""
    shared = shared or {}
    blocks = {}
    for r, blk in block.items():
        if blk != edge_block or r in override:
            blocks.setdefault(blk, set()).add(r)
    blocks.pop(edge_block, None)
    refs = list(b.fp_ref)
    P = np.column_stack([b.fp_x, b.fp_y])
    candidate = np.array([(r in block and block[r] != edge_block) or r in override for r in refs], bool)
    bad = []
    for blk, rects in outline.items():
        inside = {refs[i] for i in np.flatnonzero(candidate & in_rects(P, rects))}
        for r, home in shared.items():
            if r in refs:
                i = refs.index(r)
                inside.discard(r)
                if home == blk and in_rects(P[i:i + 1], [(x0 - shared_margin, y0 - shared_margin, x1 + shared_margin, y1 + shared_margin)
                                                         for x0, y0, x1, y1 in rects])[0]:
                    inside.add(r)
        want = blocks.get(blk, set()) - set(strays)
        inside -= set(strays) & blocks.get(blk, set())
        if inside != want:
            bad.append(f'{blk}: outline holds {sorted(inside - want)[:5]} extra, lacks {sorted(want - inside)[:5]}')
    return bad


# ---------------------------------------------------------------------------------------------- boxes: what a label, a name and a line must satisfy (boxes are (x0, y0, x1, y1))
def _grow(a, m):
    return (a[0] - m, a[1] - m, a[2] + m, a[3] + m)


def _gap(a, c):
    return math.hypot(max(c[0] - a[2], 0.0, a[0] - c[2]), max(c[1] - a[3], 0.0, a[1] - c[3]))


def _near(a, c, m):
    return a[0] - m < c[2] and c[0] < a[2] + m and a[1] - m < c[3] and c[1] < a[3] + m


def _in_box(p, a):
    return a[0] <= p[0] <= a[2] and a[1] <= p[1] <= a[3]


def covered(b, rects):
    """is box `b` wholly inside the union of `rects`? Exact: the box is cut on every rectangle edge that crosses it and each cell's centre is tested."""
    xs = sorted({b[0], b[2]} | {v for r in rects for v in (r[0], r[2]) if b[0] < v < b[2]})
    ys = sorted({b[1], b[3]} | {v for r in rects for v in (r[1], r[3]) if b[1] < v < b[3]})
    for i in range(len(xs) - 1):
        for j in range(len(ys) - 1):
            cx, cy = (xs[i] + xs[i + 1]) / 2, (ys[j] + ys[j + 1]) / 2
            if not any(r[0] <= cx <= r[2] and r[1] <= cy <= r[3] for r in rects):
                return False
    return True


def label_region_ok(label, part_xy, block, outline, strays=(), ref=None, margin=0.1, eps=0.0, anchor=False, anchor_outside=False):
    """True when a label's box sits where the owner's rules put it, False with nothing said otherwise; `why` below says what. The rules:
    - a part of no block (`block` not in `outline`, an edge part): its label may lie anywhere when the two-way test passes;
    - a part inside its own block's rectangles: its label is inside them (wholly, `margin` inside the lines), or, for an anchor (`anchor_outside`), in no block's rectangle at all;
    - a part outside its block's rectangles that is a named stray (`ref` in `strays`): its label is inside its own block's rectangles or at least in no other block's;
    - any other part outside its block's rectangles: its label is in no rectangle."""
    return label_region_findings(label, part_xy, block, outline, strays, ref, margin, eps, anchor, anchor_outside) == []


def label_region_findings(label, part_xy, block, outline, strays=(), ref=None, margin=0.1, eps=0.0, anchor=False, anchor_outside=False):
    if not outline or block not in outline:
        return []
    ctr = ((label[0] + label[2]) / 2, (label[1] + label[3]) / 2)
    mine = [tuple(q) for q in outline[block]]
    inside = covered(_grow(label, margin - eps), mine)
    anywhere = any(_in_box(ctr, q) for v in outline.values() for q in v)
    if ref in strays:
        if inside or not any(_in_box(ctr, q) for k, v in outline.items() if k != block for q in v):
            return []
        return ["label of a stray inside another block's rectangle"]
    if any(_in_box(part_xy, q) for q in mine):
        if inside or (anchor_outside and anchor and not anywhere):
            return []
        return ['not inside its block %s rectangle%s' % (block, '' if anchor else ' (a passive has no outside tier)')]
    for k, v in outline.items():
        if any(_in_box(ctr, q) for q in v):
            return ['label centre inside block %s rectangle, the part is in none of its own' % k]
    return []


def check_name_boxes(boxes, outline, area, bodies, pads, silks, others, size_h, edge_clear, region_margin, eps, clear_body, clear_pad, clear_silk, outside_gaps, corner_max, clash):
    """{block: [findings]} for the block-name boxes {block: box}: one size (box height `size_h`, the ink height), at a corner of the block's first rectangle (inside it, within `corner_max` of
    the nearest corner, or flush with a corner just outside it, one of `outside_gaps`), inside `area` by `edge_clear`, clear of bodies, pads and silk, and not clashing (`clash(box, other)`)
    with `others` {key: box}"""
    out = {}
    for blk, t in boxes.items():
        why = []
        rr = outline[blk][0]
        if abs((t[3] - t[1]) - size_h) > 0.05:
            why.append('size: box height %.3f, one size means %.3f' % (t[3] - t[1], size_h))
        inside = covered(_grow(t, region_margin - eps), [tuple(q) for q in outline[blk]])
        corners = ('TL', 'TR', 'BL', 'BR')
        flush = False
        for k in corners:
            x_flush = abs(t[0] - rr[0]) if k[1] == 'L' else abs(t[2] - rr[2])
            vgap = (t[1] - rr[3]) if k[0] == 'T' else (rr[1] - t[3])
            if x_flush <= 0.1 and -eps <= vgap <= max(outside_gaps) + 0.1:
                flush = True
        if not inside and not flush:
            why.append('neither inside the rectangle of %s nor flush with a corner just outside it' % blk)
        if inside:
            d = min(abs((t[0] if k[1] == 'L' else t[2]) - (rr[0] if k[1] == 'L' else rr[2])) + abs((t[3] if k[0] == 'T' else t[1]) - (rr[3] if k[0] == 'T' else rr[1])) for k in corners)
            if d > corner_max:
                why.append('%.2f mm from the nearest corner (at most %.1f)' % (d, corner_max))
        if area and (t[0] < area[0] + edge_clear - eps or t[2] > area[2] - edge_clear + eps or t[1] < area[1] + edge_clear - eps or t[3] > area[3] - edge_clear + eps):
            why.append('outside the name area')
        for nm, lst, m in (('body', bodies, clear_body), ('pad', pads, clear_pad), ('silk', silks, clear_silk)):
            for b in lst:
                if _near(t, b, m - eps):
                    why.append('%s %.3f mm (needs %.2f)' % (nm, _gap(t, b), m))
                    break
        for q, B in (others or {}).items():
            if clash(t, B):
                why.append('label %s %.3f mm' % (q, _gap(t, B)))
        if why:
            out[blk] = why
    return out


def check_outline_lines(drawn, outline, obstacles, line_half, break_clear, ignore=(), tol=0.01):
    """problems with the drawn outline segments `drawn` [(x0, y0, x1, y1)] of the rectangles in `outline` {block: [rects]}: a line off every rectangle edge; two lines drawn over each other; a line across an
    obstacle box (a pad, a footprint's silk, a forced label); an edge closed except where something is: a gap with nothing there, or a break that stops short of `break_clear` clear of what
    it avoids. `ignore` are boxes holding other drawn lines, which are not outline lines."""
    h, bc = line_half, break_clear
    obs = list(obstacles)
    edges = []
    for blk, rs in outline.items():
        for q in rs:
            edges += [('h', q[1], q[0], q[2]), ('h', q[3], q[0], q[2]), ('v', q[0], q[1], q[3]), ('v', q[2], q[1], q[3])]
    probs = []
    segs = [(min(s[0], s[2]), min(s[1], s[3]), max(s[0], s[2]), max(s[1], s[3])) for s in drawn]
    segs = [s for s in segs if not any(q[0] - tol <= s[0] and s[2] <= q[2] + tol and q[1] - tol <= s[1] and s[3] <= q[3] + tol for q in ignore)]
    on = {}
    for s in segs:
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
