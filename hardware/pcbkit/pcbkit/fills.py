"""Copper pour slivers: the narrow strips and fingers a zone fill leaves between tracks and pads, found on a raster of the fill.

    net_copper(b, layer, net, ppmm=40, with_net_items=True) -> Raster    the fill of every filled copper zone of `net` on `layer`, plus (default) that net's own
                                                                        pads, vias and tracks on the layer; `Raster.mask` is the copper, `.anchors` labels the net's own items
    narrow_pieces(r, width, min_area=0.02) -> [Piece]                    the parts of the copper where no disc of diameter `width` fits (a morphological opening by that disc)
    thin_report(r, lo=0.5, hi=0.8, min_area=0.02) -> [Piece]              pieces whose widest point is in [lo, hi), each with `dead_end` set when it touches copper at one end only
    covered_items(b, r, layer, net, frac=0.5)                            which of the net's pads and vias have the pour under them (compare two boards: a pad that was and is not has lost it)

A Piece is a connected part of the copper narrower than the opening disc. Its `width` is twice the largest distance to the edge of the copper inside it (so a 0.3 mm strip
reads 0.3, to a pixel or two: 0.025 mm at the default raster), its `length` the longer side of its bounding box, `dead_end` is True when it touches at most one other piece of copper (a thick region, a pad, a via or a track of the net)
and so ends in nothing at the other end, the shape an antenna has. Positions are board-frame mm (the arrays' own frame). The raster is `ppmm` pixels per mm (default 40, 0.025 mm).

Nothing here reads a configuration: the net and layer are arguments and every limit is a documented default of a function. pcbnew is not imported.
"""
from __future__ import annotations

import dataclasses

import numpy as np
from scipy import ndimage as ndi
from PIL import Image, ImageDraw

from . import geom


@dataclasses.dataclass
class Raster:
    mask: np.ndarray           # bool (rows, cols): copper; row 0 is the highest y
    anchors: np.ndarray        # int32, 0 = none, k > 0 = the k-th pad, via or track of the net
    x0: float                  # board-frame x of the left edge of column 0
    y1: float                  # board-frame y of the top edge of row 0
    ppmm: float

    def to_mm(self, rc):
        r, c = rc
        return (self.x0 + (c + 0.5) / self.ppmm, self.y1 - (r + 0.5) / self.ppmm)


@dataclasses.dataclass
class Piece:
    area: float                # mm2
    width: float               # mm, twice the widest inscribed radius
    length: float              # mm, longer side of the bounding box
    x: float                   # centre, board-frame mm
    y: float
    box: tuple                 # (x0, y0, x1, y1), board-frame mm
    touches: int = 0           # how many other pieces of copper it touches
    dead_end: bool = False


def net_copper(b, layer, net, ppmm=40.0, with_net_items=True, pad=1.0, frame=None):
    """The raster of the pour on `layer` (0 = F.Cu, 1 = B.Cu) of net code `net`: the filled polygons of every filled copper zone of that net and layer (outline rings
    drawn, hole rings cleared), and, with `with_net_items`, the net's pads on that layer, vias and tracks. `pad` is the margin of the raster beyond the zones, mm."""
    zs = [z for z in range(len(b.z_layer)) if b.z_layer[z] == layer and b.z_net[z] == net and b.z_filled[z] and not b.z_keepout[z]]
    if not zs:
        raise ValueError('no filled copper zone of net %r on layer %r' % (net, layer))
    rings = []
    for z in zs:
        for j in range(b.z_ring_off[z], b.z_ring_off[z + 1]):
            rings.append((z, j))
    allp = np.vstack([b.z_xy[b.z_vert_off[j]:b.z_vert_off[j + 1]] for _, j in rings])
    x0, x1 = allp[:, 0].min() - pad, allp[:, 0].max() + pad
    y0, y1 = allp[:, 1].min() - pad, allp[:, 1].max() + pad
    if frame is not None:                                   # a fixed window (x0, y0, x1, y1), so rasters of two fills of one board have one shape
        x0, y0, x1, y1 = frame
    k = float(ppmm)
    W, H = int(np.ceil((x1 - x0) * k)) + 1, int(np.ceil((y1 - y0) * k)) + 1

    def draw(shapes, value):
        im = Image.new('L', (W, H), 0)
        d = ImageDraw.Draw(im)
        for kind, v in shapes:
            if kind == 'poly':
                d.polygon([(float(px), float(py)) for px, py in v], fill=value)
            elif kind == 'line':
                d.line(v[0], fill=value, width=max(1, int(round(v[1]))))
            elif kind == 'disc':
                (cx, cy), rr = v
                d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=value)
        return np.asarray(im)

    mask = np.zeros((H, W), bool)
    for z in zs:                                            # zone by zone: the outline rings OR-ed, then the zone's own holes cleared, so overlapping zones union
        outl, hol = [], []
        for j in range(b.z_ring_off[z], b.z_ring_off[z + 1]):
            p = b.z_xy[b.z_vert_off[j]:b.z_vert_off[j + 1]]
            xs, ys = (p[:, 0] - x0) * k, (y1 - p[:, 1]) * k
            (hol if b.z_ring_hole[j] else outl).append(('poly', np.column_stack([xs, ys])))
        zm = draw(outl, 1).astype(bool) & ~draw(hol, 1).astype(bool) if hol else draw(outl, 1).astype(bool)
        mask |= zm
    anchors = np.zeros((H, W), np.int32)
    if with_net_items:
        n = 0
        items = []
        rows = np.flatnonzero(b.p_net == net) if len(b.p_net) else np.zeros(0, np.int64)
        rows = rows[(b.p_layer_mask[rows] & (1 << layer)) != 0] if len(rows) and len(b.p_layer_mask) else rows
        cu = geom.pad_copper(b, rows) if len(rows) else None
        if cu is not None:
            for i in range(len(rows)):                     # a pad is a union of capsules (circle, oval) or four sides of a rectangle: draw its bounding polygon
                m = cu.owner == i
                C, R = cu.C[m], cu.r[m]
                if len(C) == 4 and np.all(R == 0):          # rotated rectangle: the four corners
                    poly = [((C[q][0] - x0) * k, (y1 - C[q][1]) * k) for q in range(4)]
                    items.append(('poly', poly))
                else:
                    for (ax, ay, bx, by), rr in zip(C, R):
                        items.append(('line', (((ax - x0) * k, (y1 - ay) * k, (bx - x0) * k, (y1 - by) * k), 2 * rr * k)))
                        items.append(('disc', (((ax - x0) * k, (y1 - ay) * k), rr * k)))
                        items.append(('disc', (((bx - x0) * k, (y1 - by) * k), rr * k)))
        for i in np.flatnonzero(b.v_net == net) if len(b.v_net) else []:
            items.append(('disc', (((b.v_x[i] - x0) * k, (y1 - b.v_y[i]) * k), b.v_dia[i] / 2 * k)))
        for i in np.flatnonzero((b.s_net == net) & (b.s_layer == layer)) if len(b.s_net) else []:
            items.append(('line', (((b.s_x0[i] - x0) * k, (y1 - b.s_y0[i]) * k, (b.s_x1[i] - x0) * k, (y1 - b.s_y1[i]) * k), b.s_w[i] * k)))
        for it in items:
            n += 1
            one = draw([it], 1).astype(bool)
            anchors[one & (anchors == 0)] = n
        mask |= anchors > 0
    return Raster(mask, anchors, float(x0), float(y1), k)


def _opened(mask, r_px):
    """the opening of `mask` by a disc of radius r_px, by distance transforms: the centres of the discs that fit, grown back by the radius"""
    edt = ndi.distance_transform_edt(mask)
    core = edt >= r_px
    grown = ndi.distance_transform_edt(~core) <= r_px
    return grown & mask, edt


def narrow_pieces(r, width, min_area=0.02, length_factor=0.0):
    """Pieces of the copper narrower than `width` mm: the copper minus its opening by a disc of that diameter, in connected parts of at least `min_area` mm2
    (the rounded corner of a wide region leaves specks far below that), and, with `length_factor`, only those longer than that times half of `width`: the rounding of a corner
    of the copper reaches half the width along each side and no further, a finger or a tooth is longer."""
    k = r.ppmm
    opened, edt = _opened(r.mask, width * k / 2)
    res = r.mask & ~opened
    lab, n = ndi.label(res, structure=np.ones((3, 3)))
    out = []
    if n == 0:
        return out, opened
    objs = ndi.find_objects(lab)
    areas = ndi.sum(res, lab, index=np.arange(1, n + 1)) / (k * k)
    for i in np.flatnonzero(areas >= min_area):
        sl = objs[i]
        m = lab[sl] == i + 1
        wmax = 2 * float(edt[sl][m].max()) / k
        rr, cc = np.nonzero(m)
        r0, c0 = sl[0].start, sl[1].start
        xa, ya = r.to_mm((r0 + rr.min(), c0 + cc.min()))
        xb, yb = r.to_mm((r0 + rr.max(), c0 + cc.max()))
        box = (min(xa, xb), min(ya, yb), max(xa, xb), max(ya, yb))
        length = max(box[2] - box[0], box[3] - box[1]) + 1 / k
        if length <= length_factor * width / 2:
            continue
        out.append(Piece(float(areas[i]), wmax, length, (box[0] + box[2]) / 2, (box[1] + box[3]) / 2, box))
        out[-1]._sl = sl
        out[-1]._lab = i + 1
    return out, opened


def thin_report(r, lo=0.5, hi=0.8, min_area=0.02, reach=3, length_factor=0.0):
    """Pieces whose widest point is in [lo, hi) mm (narrower than `hi`, not narrower than `lo`), each with how many other parts of the copper it touches: a thick region (wider
    than `hi`), a pad, a via or a track of the net. `dead_end` is True at one or none; `reach` is how many pixels the touch test looks beyond the piece."""
    pieces, opened = narrow_pieces(r, hi, min_area, length_factor)
    thick, _ = ndi.label(opened, structure=np.ones((3, 3)))
    res = r.mask & ~opened
    lab, _ = ndi.label(res, structure=np.ones((3, 3)))
    counted = set(np.unique(r.anchors[opened])) - {0}            # an item inside a thick region is that region, counted once
    out = []
    for p in pieces:
        if p.width < lo - 1e-9:
            continue
        sl = tuple(slice(max(0, s.start - reach - 1), s.stop + reach + 1) for s in p._sl)
        m = lab[sl] == p._lab
        near = ndi.binary_dilation(m, structure=np.ones((3, 3)), iterations=reach)
        ids = set(np.unique(thick[sl][near & opened[sl]])) - {0}
        a = set(np.unique(r.anchors[sl][near])) - {0} - counted
        ids = {('t', int(i)) for i in ids}
        ids.update(('a', int(i)) for i in a)
        p.touches = len(ids)
        p.dead_end = len(ids) <= 1
        out.append(p)
    return out


def sliver_count(r, width=0.5, min_area=0.02):
    ps, _ = narrow_pieces(r, width, min_area)
    return len(ps), float(sum(p.area for p in ps))


def covered_items(b, r, layer, net, frac=0.5):
    """{('pad', row) or ('via', row): True} for each of the net's pads on `layer` and vias whose own footprint has at least `frac` of its area under the fill of the raster
    `r` built WITHOUT the net's own items (with_net_items=False), the connection the pour makes to it."""
    k = r.ppmm
    out = {}
    rows = np.flatnonzero(b.p_net == net) if len(b.p_net) else []
    for i in rows:
        if not (b.p_layer_mask[i] & (1 << layer)):
            continue
        x0 = int(np.floor((b.p_bx0[i] - r.x0) * k)); x1 = int(np.ceil((b.p_bx1[i] - r.x0) * k))
        y0 = int(np.floor((r.y1 - b.p_by1[i]) * k)); y1 = int(np.ceil((r.y1 - b.p_by0[i]) * k))
        sub = r.mask[max(y0, 0):y1, max(x0, 0):x1]
        out[('pad', int(i))] = bool(sub.size and sub.mean() >= frac)
    for i in np.flatnonzero(b.v_net == net) if len(b.v_net) else []:
        cx, cy = int(round((b.v_x[i] - r.x0) * k)), int(round((r.y1 - b.v_y[i]) * k))
        rr = max(1, int(round(b.v_dia[i] / 2 * k)))
        sub = r.mask[max(cy - rr, 0):cy + rr + 1, max(cx - rr, 0):cx + rr + 1]
        out[('via', int(i))] = bool(sub.size and sub.mean() >= frac)
    return out


def keepouts(r, width=1.0, grid=0.5, join=1.0, min_area=0.05, outlines=(), snap=1.0, bounds=None, hole_area=4.0, fill_ratio=1.0, extra=None):
    """Straight-edged no-pour rectangles over the dense places of a pour, from `r` = the raster of a LOOSE fill (the pour at its narrowest minimum width, thermal
    reliefs on, with the net's own items): the parts of the copper where no disc of diameter `width` fits are where a fill of minimum width `width` would leave a ragged
    edge, a tooth or a dead-end finger. Those pieces (at least `min_area` mm2) closer than `join` mm are one cluster; a cluster's bounding rectangle is grown outward to the `grid`,
    rectangles that touch or overlap are merged until none does, an edge within `snap` mm of an edge of a rectangle of `outlines` (block outlines, (x0, y0, x1, y1)) moves onto
    it, and `bounds` (x0, y0, x1, y1) clips the result. Returns [(x0, y0, x1, y1)] in the raster's frame, sorted. Nothing here reads a configuration."""
    k = r.ppmm
    pieces, opened = narrow_pieces(r, width, min_area)
    res = np.zeros_like(r.mask)
    lab0 = _lab_of(r, opened)
    for p in pieces:
        res[p._sl] |= (lab0[p._sl] == p._lab)
    if extra is not None:
        res = res | extra
    if not res.any():
        return []
    # the cells of the grid that hold a piece, closed over `join` mm so near pieces are one region, small holes filled, then cut into rectangles (a long diagonal run of pieces
    # is a staircase of rectangles, never one big bounding box)
    cell = max(1, int(round(grid * k)))
    H, W = res.shape
    hc, wc = -(-H // cell), -(-W // cell)
    pad = np.zeros((hc * cell, wc * cell), bool)
    pad[:H, :W] = res
    cells = pad.reshape(hc, cell, wc, cell).any(axis=(1, 3))
    it = int(round(join / grid / 2))
    if it:
        cells = ndi.binary_closing(np.pad(cells, it + 1), structure=np.ones((3, 3)), iterations=it)[it + 1:-(it + 1), it + 1:-(it + 1)]
    holes = ndi.binary_fill_holes(cells) & ~cells
    hl, hn = ndi.label(holes)
    for i in range(1, hn + 1):
        if (hl == i).sum() * grid * grid <= hole_area:
            cells |= hl == i
    rects, open_ = [], {}
    for row in range(hc + 1):
        runs = set()
        if row < hc:
            c = 0
            while c < wc:
                if cells[row, c]:
                    c0 = c
                    while c < wc and cells[row, c]:
                        c += 1
                    runs.add((c0, c))
                else:
                    c += 1
        for run_ in list(open_):
            if run_ not in runs:
                r0 = open_.pop(run_)
                rects.append((run_[0], r0, run_[1], row))
        for run_ in runs:
            open_.setdefault(run_, row)
    rects = [[r.x0 + c0 * cell / k, r.y1 - r1 * cell / k, r.x0 + c1 * cell / k, r.y1 - r0 * cell / k] for c0, r0, c1, r1 in rects]
    def sn(v, lo=True):
        return (np.floor(v / grid + 1e-9) if lo else np.ceil(v / grid - 1e-9)) * grid
    rects = [[sn(a, True), sn(b, True), sn(c, False), sn(d, False)] for a, b, c, d in rects]
    def merge(rs):
        rs = [list(x) for x in rs]
        again = True
        while again:
            again = False
            for i in range(len(rs)):
                for j in range(i + 1, len(rs)):
                    a, c = rs[i], rs[j]
                    if a[0] <= c[2] and c[0] <= a[2] and a[1] <= c[3] and c[1] <= a[3]:
                        u = [min(a[0], c[0]), min(a[1], c[1]), max(a[2], c[2]), max(a[3], c[3])]
                        ov = max(0.0, min(a[2], c[2]) - max(a[0], c[0])) * max(0.0, min(a[3], c[3]) - max(a[1], c[1]))
                        have = (a[2] - a[0]) * (a[3] - a[1]) + (c[2] - c[0]) * (c[3] - c[1]) - ov
                        if (u[2] - u[0]) * (u[3] - u[1]) > fill_ratio * have + 1e-9:        # only a union that is nearly the rectangles themselves: a staircase stays a staircase
                            continue
                        rs[i] = u
                        del rs[j]
                        again = True
                        break
                if again:
                    break
        return rs
    rects = merge(rects)
    xs = sorted({o[0] for o in outlines} | {o[2] for o in outlines})
    ys = sorted({o[1] for o in outlines} | {o[3] for o in outlines})
    def near(v, cand):
        c = [t for t in cand if abs(t - v) <= snap]
        return min(c, key=lambda t: abs(t - v)) if c else v
    rects = [[near(a, xs), near(b, ys), near(c, xs), near(d, ys)] for a, b, c, d in rects]
    rects = merge(rects)
    if bounds is not None:
        rects = [[max(a, bounds[0]), max(b, bounds[1]), min(c, bounds[2]), min(d, bounds[3])] for a, b, c, d in rects]
        rects = [x for x in rects if x[2] > x[0] and x[3] > x[1]]
    return sorted((round(a, 3), round(b, 3), round(c, 3), round(d, 3)) for a, b, c, d in rects)


def _lab_of(r, opened):
    res = r.mask & ~opened
    lab, _ = ndi.label(res, structure=np.ones((3, 3)))
    return lab


def leftovers(r, neck=1.5, small=12.0, dead_width=1.6, lo=1.0, min_area=0.05):
    """What a fill leaves that is not worth keeping, as a mask on the raster of that fill `r` (the pour with the net's items): parts of the pour that hang by a neck narrower than
    `neck` mm and hold less than `small` mm2 (a blob), and fingers of width `lo` to `dead_width` that touch copper at one end only (a dead end). Feed it to keepouts(extra=...)."""
    k = r.ppmm
    out = np.zeros_like(r.mask)
    opened, _ = _opened(r.mask, neck * k / 2)
    lab, n = ndi.label(opened, structure=np.ones((3, 3)))
    grown = ndi.distance_transform_edt(~opened) <= neck * k / 2
    for i, sl in enumerate(ndi.find_objects(lab), 1):
        if (lab[sl] == i).sum() / (k * k) < small:
            comp = lab == i
            out |= r.mask & (ndi.distance_transform_edt(~comp) <= neck * k / 2)
    pieces, op = narrow_pieces(r, dead_width, min_area)
    lab0 = _lab_of(r, op)
    for p in thin_report(r, lo, dead_width, min_area):
        if p.dead_end:
            out[p._sl] |= lab0[p._sl] == p._lab
    return out


# ---------------------------------------------------------------------------------------------------- keep-out polygons (octilinear, one per cluster)

def _decompose(cells):
    """the cell mask cut into rectangles (c0, r0, c1, r1), a run of cells per row joined with the identical run below"""
    hc, wc = cells.shape
    rects, open_ = [], {}
    for row in range(hc + 1):
        runs = set()
        if row < hc:
            c = 0
            while c < wc:
                if cells[row, c]:
                    c0 = c
                    while c < wc and cells[row, c]:
                        c += 1
                    runs.add((c0, c))
                else:
                    c += 1
        for run_ in list(open_):
            if run_ not in runs:
                rects.append((run_[0], open_.pop(run_), run_[1], row))
        for run_ in runs:
            open_.setdefault(run_, row)
    return rects


def _loops(cells):
    """the boundary loops of a cell mask, each a list of corner points (c, r) (r grows downward), clockwise around a filled part and counter-clockwise around a hole; collinear
    corners are dropped"""
    hc, wc = cells.shape
    P = np.pad(cells, 1)
    nxt = {}
    for r, c in zip(*np.nonzero(cells)):
        r1, c1 = r + 1, c + 1
        if not P[r1 - 1, c1]:
            nxt.setdefault((c, r), []).append((c + 1, r))
        if not P[r1, c1 + 1]:
            nxt.setdefault((c + 1, r), []).append((c + 1, r + 1))
        if not P[r1 + 1, c1]:
            nxt.setdefault((c + 1, r + 1), []).append((c, r + 1))
        if not P[r1, c1 - 1]:
            nxt.setdefault((c, r + 1), []).append((c, r))
    loops = []
    while nxt:
        start = next(iter(nxt))
        loop, cur, prev = [start], start, None
        while True:
            outs = nxt[cur]
            if len(outs) > 1 and prev is not None:             # a corner two parts share: turn right (clockwise), so parts touching at a corner stay apart
                d = (cur[0] - prev[0], cur[1] - prev[1])
                outs.sort(key=lambda o: -(d[0] * (o[1] - cur[1]) - d[1] * (o[0] - cur[0])))
            n = outs.pop(0)
            if not outs:
                del nxt[cur]
            prev, cur = cur, n
            if cur == start and start not in nxt:
                break
            loop.append(cur)
            if cur == start:
                break
        if loop[-1] == loop[0] and len(loop) > 1:
            loop.pop()
        loops.append(_collinear(loop))
    return loops


def _collinear(loop):
    out = []
    n = len(loop)
    for i in range(n):
        a, b, c = loop[i - 1], loop[i], loop[(i + 1) % n]
        if (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]) != 0:
            out.append(b)
    return out


def _area2(loop):
    return sum(loop[i][0] * loop[(i + 1) % len(loop)][1] - loop[(i + 1) % len(loop)][0] * loop[i][1] for i in range(len(loop)))


def _diagonalise(loop):
    """a staircase of equal steps (two or more steps, every edge the same length, turns alternating) becomes the straight 45 degree line through its outer corners: the polygon only
    grows, and every edge is along 0, 45 or 90 degrees. `loop` is clockwise (image coordinates)."""
    n = len(loop)
    if n < 6:
        return loop
    E = [(loop[(i + 1) % n][0] - loop[i][0], loop[(i + 1) % n][1] - loop[i][1]) for i in range(n)]
    L = [abs(e[0]) + abs(e[1]) for e in E]
    turn = [E[i - 1][0] * E[i][1] - E[i - 1][1] * E[i][0] for i in range(n)]       # at vertex i, between edge i-1 and edge i: > 0 turns clockwise on screen (convex for a clockwise loop)
    drop = [False] * n
    keepv = [False] * n
    i = 0
    seen = 0
    while seen < n:
        # a run starts at edge j and holds edges j..j+m-1 all of length L[j], with the turn at each inner vertex alternating in sign
        j = i % n
        m = 1
        while m < n and L[(j + m) % n] == L[j] and turn[(j + m) % n] * turn[(j + m - 1) % n] < 0 and (m == 1 or True):
            m += 1
        if m >= 4:                                              # at least two full steps
            inner = [(j + t) % n for t in range(1, m)]       # vertices between consecutive edges of the run
            convex = [v for v in inner if turn[v] > 0]
            for v in inner:
                drop[v] = True
            if convex:
                keepv[convex[0]] = True
                keepv[convex[-1]] = True
            i += m
            seen += m
        else:
            i += 1
            seen += 1
    out = [loop[v] for v in range(n) if not drop[v] or keepv[v]]
    return _collinear(out) if len(out) >= 3 else loop


def _octilinear(loop):
    ok = True
    n = len(loop)
    for i in range(n):
        dx, dy = loop[(i + 1) % n][0] - loop[i][0], loop[(i + 1) % n][1] - loop[i][1]
        if not (dx == 0 or dy == 0 or abs(dx) == abs(dy)):
            ok = False
    return ok


def keepout_polygons(r, width=1.0, grid=0.5, join=1.0, min_area=0.05, outlines=(), snap=1.0, bounds=None, hole_area=4.0, extra=None):
    """The same no-pour areas as `keepouts`, one polygon per cluster instead of rectangles: the cells (a `grid` mm grid on multiples of `grid` mm) that hold a piece too narrow for
    `width`, closed over `join` mm, traced round, and every staircase of equal steps drawn as one 45 degree edge (the polygon only grows). A cluster that encloses pour (a hole
    over `hole_area` mm2) is cut into rectangles instead, since a rule area has no holes. An edge or vertex line within `snap` mm of a block outline's edge moves onto it unless a
    diagonal edge would bend. `bounds` clips (a vertex outside moves to it). Returns [[(x, y), ...]] in the raster's frame, every edge along 0, 45 or 90 degrees."""
    k = r.ppmm
    pieces, opened = narrow_pieces(r, width, min_area)
    res = np.zeros_like(r.mask)
    lab0 = _lab_of(r, opened)
    for p in pieces:
        res[p._sl] |= (lab0[p._sl] == p._lab)
    if extra is not None:
        res = res | extra
    if not res.any():
        return []
    cell = int(round(grid * k))
    if abs(cell - grid * k) > 1e-6:
        raise ValueError('grid %r mm is not a whole number of pixels at %r px/mm' % (grid, k))
    xo, yo = np.floor(r.x0 / grid) * grid, np.ceil(r.y1 / grid) * grid
    ox, oy = int(round((r.x0 - xo) * k)), int(round((yo - r.y1) * k))
    H, W = res.shape
    hc, wc = -(-(H + oy) // cell), -(-(W + ox) // cell)
    pad = np.zeros((hc * cell, wc * cell), bool)
    pad[oy:oy + H, ox:ox + W] = res
    cells = pad.reshape(hc, cell, wc, cell).any(axis=(1, 3))
    it = int(round(join / grid / 2))
    if it:
        cells = ndi.binary_closing(np.pad(cells, it + 1), structure=np.ones((3, 3)), iterations=it)[it + 1:-(it + 1), it + 1:-(it + 1)]
    holes = ndi.binary_fill_holes(cells) & ~cells
    hl, hn = ndi.label(holes)
    for i in range(1, hn + 1):
        if (hl == i).sum() * grid * grid <= hole_area:
            cells |= hl == i
    lab, n = ndi.label(cells, structure=np.ones((3, 3)))
    polys = []
    def mm(p):
        return (float(xo + p[0] * grid), float(yo - p[1] * grid))
    for i in range(1, n + 1):
        comp = lab == i
        loops = _loops(comp)
        outer = [lp for lp in loops if _area2(lp) > 0]
        if len(loops) == 1 and len(outer) == 1:
            lp = _diagonalise(outer[0])
            polys.append([mm(p) for p in lp])
        else:
            for c0, r0, c1, r1 in _decompose(comp):
                polys.append([mm(p) for p in ((c0, r0), (c1, r0), (c1, r1), (c0, r1))])
    xs = sorted({o[0] for o in outlines} | {o[2] for o in outlines})
    ys = sorted({o[1] for o in outlines} | {o[3] for o in outlines})
    out = []
    for poly in polys:
        poly = _snap_poly(poly, xs, ys, snap)
        if bounds is not None:
            poly = [(min(max(x, bounds[0]), bounds[2]), min(max(y, bounds[1]), bounds[3])) for x, y in poly]
            poly = _dedupe(poly)
            if len(poly) < 3 or abs(_area2(poly)) < 1e-6:
                continue
        out.append([(round(x, 3), round(y, 3)) for x, y in poly])
    return sorted(out)


def _dedupe(poly):
    out = []
    for p in poly:
        if not out or p != out[-1]:
            out.append(p)
    if len(out) > 1 and out[0] == out[-1]:
        out.pop()
    return _collinear(out) if len(out) >= 3 else out


def _snap_poly(poly, xs, ys, snap):
    """move each line of vertices (all those at one x, or one y) onto a block outline's edge within `snap` mm, when no diagonal edge touches the line"""
    n = len(poly)
    def diag(i):
        a, b = poly[i], poly[(i + 1) % n]
        return abs(a[0] - b[0]) > 1e-9 and abs(a[1] - b[1]) > 1e-9
    for axis, cand in ((0, xs), (1, ys)):
        for v in sorted({round(p[axis], 6) for p in poly}):
            near = [t for t in cand if abs(t - v) <= snap]
            if not near:
                continue
            t = min(near, key=lambda q: abs(q - v))
            idx = [i for i in range(n) if abs(poly[i][axis] - v) < 1e-6]
            if any(diag(i) or diag((i - 1) % n) for i in idx):
                continue
            for i in idx:
                p = list(poly[i])
                p[axis] = t
                poly[i] = tuple(p)
    return poly


def rough_edges(b, rp, layer, net, clearance=0.3, tol=0.15, link=2.0, margin=0.25, trace=None):
    """The places where the pour edge is a run of clearance arcs, as a mask on the raster `rp` of the pour (built WITHOUT the net's own items). An item (a pad or a via of another net on
    `layer`) hugs the pour when pour copper lies within `clearance` + `tol` of it. Hugging items whose copper is within `link` mm of each other are one cluster; a cluster of two or more
    is rough (one alone may show its round clearance), and its mask is every item grown by clearance + tol + `margin` and closed over `link` mm, so a keep-out over it leaves a straight edge
    instead of the arcs. Feed it to keepout_polygons(extra=...)."""
    k = rp.ppmm
    reach = clearance + tol
    items = []                                              # (mask window, (r0, c0)) per item, in raster pixels
    rows = np.flatnonzero((b.p_layer_mask & (1 << layer)) != 0) if len(b.p_net) else np.zeros(0, np.int64)
    cu = geom.pad_copper(b, rows) if len(rows) else None
    wpx = int(np.ceil((reach + link + margin + 0.2) * k))
    def window(x0, y0, x1, y1):
        c0 = int(np.floor((x0 - rp.x0) * k)) - wpx
        c1 = int(np.ceil((x1 - rp.x0) * k)) + wpx
        r0 = int(np.floor((rp.y1 - y1) * k)) - wpx
        r1 = int(np.ceil((rp.y1 - y0) * k)) + wpx
        return max(r0, 0), max(c0, 0), min(r1, rp.mask.shape[0]), min(c1, rp.mask.shape[1])
    def draw(shapes, win):
        r0, c0, r1, c1 = win
        im = Image.new('L', (c1 - c0, r1 - r0), 0)
        d = ImageDraw.Draw(im)
        for kind, v in shapes:
            if kind == 'poly':
                d.polygon([(px - c0, py - r0) for px, py in v], fill=1)
            elif kind == 'line':
                (ax, ay, bx, by), w = v
                d.line((ax - c0, ay - r0, bx - c0, by - r0), fill=1, width=max(1, int(round(w))))
            else:
                (cx, cy), rr = v
                d.ellipse([cx - c0 - rr, cy - r0 - rr, cx - c0 + rr, cy - r0 + rr], fill=1)
        return np.asarray(im).astype(bool)
    def px(x, y):
        return ((x - rp.x0) * k, (rp.y1 - y) * k)
    for n_, i in enumerate(rows):
        m = cu.owner == n_
        C, R = cu.C[m], cu.r[m]
        shapes = []
        if len(C) == 4 and np.all(R == 0):
            shapes.append(('poly', [px(*C[q][:2]) for q in range(4)]))
        else:
            for (ax, ay, bx, by), rr in zip(C, R):
                shapes.append(('line', ((*px(ax, ay), *px(bx, by)), 2 * rr * k)))
                shapes.append(('disc', (px(ax, ay), rr * k)))
                shapes.append(('disc', (px(bx, by), rr * k)))
        items.append((shapes, window(b.p_bx0[i], b.p_by0[i], b.p_bx1[i], b.p_by1[i]), (b.p_bx0[i], b.p_by0[i], b.p_bx1[i], b.p_by1[i]), int(b.p_net[i]) == net))
    for i in range(len(b.v_net)):
        r_ = b.v_dia[i] / 2
        items.append(([('disc', (px(b.v_x[i], b.v_y[i]), r_ * k))], window(b.v_x[i] - r_, b.v_y[i] - r_, b.v_x[i] + r_, b.v_y[i] + r_), (b.v_x[i] - r_, b.v_y[i] - r_, b.v_x[i] + r_, b.v_y[i] + r_), int(b.v_net[i]) == net))
    hug = []
    for shapes, win, box, mine in items:
        m = draw(shapes, win)
        if not m.any():
            continue
        zone = rp.mask[win[0]:win[2], win[1]:win[3]]
        ring = ndi.distance_transform_edt(~m) <= reach * k
        if not mine:
            ok = (ring & zone).any()                          # another net's item with pour within its clearance
        else:                                                 # the net's own item stands at the edge when the pour round it is cut off on some side but not all
            around = ring & ~m
            frac = (around & zone).sum() / max(1, around.sum())
            ok = 0.1 < frac < 0.9
        if ok:
            hug.append((shapes, win, box))
    if trace is not None:
        trace.extend(('hug', h[2]) for h in hug)
    parent = list(range(len(hug)))
    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    for a in range(len(hug)):
        for c in range(a + 1, len(hug)):
            A, B = hug[a][2], hug[c][2]
            if np.hypot(max(A[0] - B[2], B[0] - A[2], 0), max(A[1] - B[3], B[1] - A[3], 0)) <= link:
                parent[find(a)] = find(c)
    groups = {}
    for a in range(len(hug)):
        groups.setdefault(find(a), []).append(a)
    out = np.zeros_like(rp.mask)
    grow = (reach + margin) * k
    for g in groups.values():
        if len(g) < 2:
            continue
        r0 = min(hug[a][1][0] for a in g); c0 = min(hug[a][1][1] for a in g)
        r1 = max(hug[a][1][2] for a in g); c1 = max(hug[a][1][3] for a in g)
        win = (r0, c0, r1, c1)
        m = np.zeros((r1 - r0, c1 - c0), bool)
        for a in g:
            m |= draw(hug[a][0], win)
        grown = ndi.distance_transform_edt(~m) <= grow
        pad_ = int(np.ceil(link * k / 2)) + 2
        G = np.pad(grown, pad_)
        d1 = ndi.distance_transform_edt(~G) <= link * k / 2
        closed = ndi.distance_transform_edt(d1) > link * k / 2
        closed = (closed | G)[pad_:-pad_, pad_:-pad_]
        out[r0:r1, c0:c1] |= closed
    return out

