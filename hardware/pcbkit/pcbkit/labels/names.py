"""Block names: one size, each at a corner of its block's first rectangle, the same corner for every block where it fits, otherwise the next.

    place_names(lb, cfg, placed) -> {block: (x, y, size, corner)} (no entry for a block with no room)

Names: BLOCK_NAMES (block -> text), NAME_SIZE (1.2), OUTLINE, NAME_AREA (box the names stay in; default LABEL_AREA), NAME_CLEAR_BODY 0.05, NAME_CLEAR_PAD 0.10, NAME_CLEAR_SILK 0.08,
NAME_REACH (12 mm search distance from the corner), NAME_STEP (0.25)."""
from . import _g as G
from .placer import Cfg, NEEDS, lab_box, clash

CORNERS = ('TL', 'TR', 'BL', 'BR')


def name_box(c, text, x, y):
    L, W = len(text) * c.DESIGNATOR_ADVANCE * c.NAME_SIZE, c.DESIGNATOR_INK_H * c.NAME_SIZE
    return (x - L / 2, y - W / 2, x + L / 2, y + W / 2)


def place_names(lb, cfg, placed):
    c = Cfg(cfg, NEEDS['place_names'])
    rects = {k: [tuple(q) for q in v] for k, v in c.OUTLINE.items()}
    area = c.NAME_AREA or c.LABEL_AREA or lb.edge
    bodies = [p.body for p in lb.parts.values() if p.body]
    pads = [b for p in lb.parts.values() for b in p.pads]
    sink = dict(placed)

    def ok(blk, x, y, inside=True):
        t = name_box(c, c.BLOCK_NAMES[blk], x, y)
        if inside:
            if not G.covered(G.grow(t, c.REGION_MARGIN - c.EPS), rects[blk]):
                return False
        elif any(G.overlap(t, q) for v in rects.values() for q in v) or any(G.in_box(G.centre(t), q) for v in rects.values() for q in v):
            return False                                       # the outside tier: on no block's rectangle at all
        if area and (t[0] < area[0] + c.EDGE_CLEAR or t[2] > area[2] - c.EDGE_CLEAR or t[1] < area[1] + c.EDGE_CLEAR or t[3] > area[3] - c.EDGE_CLEAR):
            return False
        if any(G.near(t, b, c.NAME_CLEAR_BODY) for b in bodies) or any(G.near(t, b, c.NAME_CLEAR_PAD) for b in pads) or any(G.near(t, b, c.NAME_CLEAR_SILK) for b in lb.silk):
            return False
        return not any(clash(c, t, B, True) for B in sink.values())

    def spot(blk, corner):
        rr = rects[blk][0]
        cx = rr[0] if corner[1] == 'L' else rr[2]
        cy = rr[3] if corner[0] == 'T' else rr[1]
        best = None
        n = int(c.NAME_REACH / c.NAME_STEP)
        for i in range(-n, n + 1):
            for j in range(-n, n + 1):
                x, y = cx + i * c.NAME_STEP, cy + j * c.NAME_STEP
                d = abs(x - cx) + abs(y - cy)
                if d > c.NAME_REACH or (best and d >= best[0]):
                    continue
                if ok(blk, x, y):
                    best = (d, x, y)
        return best
    def spot_out(blk, corner):
        """outside tier: the box flush with the corner's side of the rectangle (its edge on the corner's x), clear of the rectangle's side by the first of NAME_OUTSIDE_GAPS that fits"""
        rr = rects[blk][0]
        t0 = name_box(c, c.BLOCK_NAMES[blk], 0.0, 0.0)
        w, h = t0[2] - t0[0], t0[3] - t0[1]
        for g in c.NAME_OUTSIDE_GAPS:
            x = rr[0] + w / 2 if corner[1] == 'L' else rr[2] - w / 2
            y = rr[3] + g + h / 2 if corner[0] == 'T' else rr[1] - g - h / 2
            if ok(blk, x, y, inside=False):
                return (abs(g), x, y)
        return None
    feas = {b: {k: spot(b, k) for k in CORNERS} for b in c.BLOCK_NAMES if b in rects}
    tier = {}
    for b in feas:
        if not any(feas[b].values()):                          # no inside corner is free: just outside a corner
            feas[b] = {k: spot_out(b, k) for k in CORNERS}
            tier[b] = 'outside'
    cnt = {k: sum(1 for b in feas if feas[b][k]) for k in CORNERS}
    best = max(CORNERS, key=lambda k: (cnt[k], -CORNERS.index(k)))
    out = {}
    for b in feas:
        k = next((k for k in [best] + [q for q in CORNERS if q != best] if feas[b][k]), None)
        if k:
            d, x, y = feas[b][k]
            out[b] = (round(float(x), 3), round(float(y), 3), c.NAME_SIZE, k + ('+' if tier.get(b) == 'outside' else ''))
            sink['name_' + b] = name_box(c, c.BLOCK_NAMES[b], x, y)
    return out


def validate_names(lb, boxes, cfg, others=None):
    """{block: [failing terms]} for the name boxes `boxes` {block: box}: one size (the box height is the NAME_SIZE ink height), at a corner of the block's first rectangle
    (inside it, or just outside flush with the corner, NAME_OUTSIDE_GAPS), clear of bodies, pads and silk, of the other labels in `others`, and inside the area."""
    c = Cfg(cfg, NEEDS['validate_names'])
    rects = {k: [tuple(q) for q in v] for k, v in c.OUTLINE.items()}
    area = c.NAME_AREA or c.LABEL_AREA or lb.edge
    bodies = [p.body for p in lb.parts.values() if p.body]
    pads = [b for p in lb.parts.values() for b in p.pads]
    out = {}
    e = c.EPS
    for blk, t in boxes.items():
        why = []
        rr = rects[blk][0]
        hh = c.DESIGNATOR_INK_H * c.NAME_SIZE
        if abs((t[3] - t[1]) - hh) > 0.05:
            why.append('size: box height %.3f, one size means %.3f' % (t[3] - t[1], hh))
        inside = G.covered(G.grow(t, c.REGION_MARGIN - e), rects[blk])
        flush_gap = None
        for k in CORNERS:
            x_flush = abs(t[0] - rr[0]) if k[1] == 'L' else abs(t[2] - rr[2])
            vgap = (t[1] - rr[3]) if k[0] == 'T' else (rr[1] - t[3])
            if x_flush <= 0.1 and -e <= vgap <= max(c.NAME_OUTSIDE_GAPS) + 0.1:
                flush_gap = vgap
        if not inside and flush_gap is None:
            why.append('neither inside the rectangle of %s nor flush with a corner just outside it' % blk)
        if inside:                                               # a corner: the nearest rectangle corner is within NAME_CORNER_MAX (manhattan, box corner to corner)
            d = min(abs((t[0] if k[1] == 'L' else t[2]) - (rr[0] if k[1] == 'L' else rr[2])) + abs((t[3] if k[0] == 'T' else t[1]) - (rr[3] if k[0] == 'T' else rr[1])) for k in CORNERS)
            if d > c.NAME_CORNER_MAX:
                why.append('%.2f mm from the nearest corner (at most %.1f)' % (d, c.NAME_CORNER_MAX))
        if area and (t[0] < area[0] + c.EDGE_CLEAR - e or t[2] > area[2] - c.EDGE_CLEAR + e or t[1] < area[1] + c.EDGE_CLEAR - e or t[3] > area[3] - c.EDGE_CLEAR + e):
            why.append('outside the name area')
        for nm, lst, m in (('body', bodies, c.NAME_CLEAR_BODY), ('pad', pads, c.NAME_CLEAR_PAD), ('silk', lb.silk, c.NAME_CLEAR_SILK)):
            for b in lst:
                if G.near(t, b, m - e):
                    why.append('%s %.3f mm (needs %.2f)' % (nm, G.gap(t, b), m))
                    break
        for q, B in (others or {}).items():
            if clash(c, t, B, True):
                why.append('label %s %.3f mm' % (q, G.gap(t, B)))
        if why:
            out[blk] = why
    return out
