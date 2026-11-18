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
