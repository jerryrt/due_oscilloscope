"""Cluster keys (D30 1b): where a cluster of parts is held tight on purpose, its designators come off the parts and one outlined key carries
them in the parts' order, rows and columns. Board-agnostic: the board's own config says which clusters (`KEYS`) and the thresholds; nothing
here names a board, a part or a net. No arrow or leader line is ever drawn.

Two places for a key:
  * local: in free area within KEY_ADJOIN_MAX of its cluster, no heading;
  * legend: when no key fits beside its parts, the keys gather in one legend area (one rectangle or an L of several), each under its block's
    name as a heading (one F.SilkS text inside the box; the names are the config's KEY_BLOCKS, e.g. "CH1", "REF / CAL"), packed first-fit from
    the top left so the boxes line up, and every part of a key belongs to its heading's block by its designator's hundreds digit.

    plan(b, text, cfg, name, parts=None)         -> Plan | NoFit            a local key, from the board arrays (pcbnew read, in the image) and its text
    legend(b, text, cfg, items, regions, split=, auto=) -> [Plan] | LegendNoFit    items [(heading, [refs])]; regions [(x0, y0, x1, y1)] Due mm, each wholly free;
                                                 split: cut each block's residue into spatial clusters, one key each (several keys may share a heading);
                                                 auto (min_w, min_h, count): also the biggest free rectangles of the board
    apply(text, plans, cfg)                      -> new text                the keys added and their parts' designators taken off the silk
    python3 -m pcbtools.keys BOARD.kicad_pcb --config v2_layout NAME [--parts R1,R2] [--write OUT]
    python3 -m pcbtools.keys BOARD.kicad_pcb --config v2_layout --legend "CH2=R1,R2;CH1=R3,R4" --region x0,y0,x1,y1 [--region ...] [--write OUT]

The edit is a text splice: each keyed part's Reference field moves from F.SilkS to F.Fab (it stays in the file, for the assembly drawing, and is no
longer on the silkscreen), and a key is one unfilled gr_rect on F.SilkS plus one F.SilkS text per designator (and its heading) at 0 degrees. Nothing
else changes, the project file is not touched, and applying twice changes nothing. A key that finds no place is NoFit (LegendNoFit lists the
needed rectangles against the available ones) and edits nothing.

Layout of a key. Rows are the parts' y groups (top = largest y), columns their x groups; a group's span is at most KEY_ROW_TOL, which is
silkread's ORDER_MIN: two parts further apart than that must have their texts in the same order, never tied. The default is a GRID (every
column one pitch). If a grid does not fit, the key is COMPACT: each x group's texts take the room their row needs and no more, the groups'
centres still strictly increasing left to right, so rows and order are the parts' and columns are staggered. Last, DENSE (legend only): the
parts are placed left to right by x, each text at the least x and then the least row at which it is in silkread's order (right of every text
whose part is more than ORDER_MIN left of it, below every text whose part is higher, ...) and clear of the texts already placed; the order is
kept, the rows and columns are not.

Config (`KEYS = {name: dict(parts=(refs...))}`, `KEY_BLOCKS = {heading: hundreds digit}`, and):
  KEY_TEXT_H            text height, mm (>= the board house's silk minimum)
  KEY_ADVANCE, KEY_INK_H  the stroke font's advance per character and the ink height, as fractions of KEY_TEXT_H (as DESIGNATOR_ADVANCE / DESIGNATOR_INK_H)
  KEY_COL_GAP           clear space between two designators in a row, mm
  KEY_ROW_PITCH         centre to centre of two rows, mm
  KEY_MARGIN            clear space inside the box all round, mm
  KEY_ROW_TOL           parts within this span of each other are one row (or column), mm
  KEY_CLEAR             free area is measured with pads, vias, silk and courtyards grown by this, mm
  KEY_ADJOIN_MAX        a local key's box is at most this far from its cluster's extent (the union of the parts' courtyards), mm
  KEY_GAP               clear space between two keys in a legend, mm
  KEY_SPLIT_GAP         (optional) legend: a block's residue is cut into clusters of parts whose courtyards are within this, each its own key
  KEY_SPLIT_SPAN        (optional) legend: a cluster's part positions span at most this, mm (a number or (width, height)); bounds a cluster in a dense block
  KEY_AVOID_TRACKS      (optional) True counts tracks as taken in the free-area measure; default False: silk over a mask-covered track is allowed
  KEY_WITHIN            (optional) (x0, y0, x1, y1): free rectangles found for a legend lie inside this (the overhang bands stay out of it)
  KEY_EDGE              (optional) free rectangles found for a legend stay this far in from the board's bounding box, mm (default 0.5)
  KEY_STROKE            line width of the box, mm
"""
from __future__ import annotations

import dataclasses
import itertools
import re
import sys
import uuid

import numpy as np

RES = 0.1                    # occupancy grid, mm
STEP = 0.1                   # a legend is scanned for a free place at this step, mm
KEY_UUID_PREFIX = 'ffff0000-'  # the uuid of every item a key writes starts so: the other silk splices (pinlabels, the identity block) skip them when they look for the last or first board text
DELTA = 0.1                  # compact layout: the least step between two groups' text centres, mm


@dataclasses.dataclass
class Plan:
    name: str
    box: tuple               # (x0, y0, x1, y1) Due mm
    texts: dict              # {ref: (x, y)} centre of each designator, Due mm
    rows: list               # [[ref, ...]] top to bottom, each left to right
    gap: float               # key box to the cluster's extent, mm (a legend key: None)
    heading: str | None = None
    heading_at: tuple | None = None
    mode: str = 'grid'


@dataclasses.dataclass
class NoFit:
    name: str
    need: tuple              # (width, height) of the key, mm
    nearest_gap: float       # to the cluster, of the nearest place that is free at all (None: nowhere on the board)
    nearest_at: tuple
    biggest_adjoining: tuple  # (w, h) of the largest free rectangle within KEY_ADJOIN_MAX of the cluster, 0.5 mm steps

    def __str__(self):
        return (f'key {self.name}: no free area adjoining its cluster: it needs {self.need[0]:.1f} x {self.need[1]:.1f} mm; the largest free '
                f'rectangle adjoining is {self.biggest_adjoining[0]:.1f} x {self.biggest_adjoining[1]:.1f} mm; the nearest place it fits is '
                + (f'{self.nearest_gap:.1f} mm away at {self.nearest_at}' if self.nearest_gap is not None else 'nowhere on the board'))


@dataclasses.dataclass
class LegendNoFit:
    needs: list              # [(heading, width, height, mode)] every key as it was tried
    available: list          # [(width, height)] of the regions
    placed: list             # headings that did find a place before one did not
    failed: str              # the heading that did not

    def __str__(self):
        n = ', '.join(f'{h} {w:.1f} x {hh:.1f}' for h, w, hh, _ in self.needs)
        a = ', '.join(f'{w:.1f} x {h:.1f}' for w, h in self.available)
        return f'legend: no place for {self.failed} (placed first: {", ".join(self.placed) or "none"}); the keys need {n}; the regions are {a} mm'


def cluster_1d(values, tol):
    """indices grouped into runs whose whole span is at most tol (a group starts where a value is more than tol past the group's first), so two
    parts of one row or column are never further apart than tol: silkread's order test ties two texts of one row or column, which is right only
    for parts within its ORDER_MIN of each other -> [[index, ...]] in value order"""
    order = sorted(range(len(values)), key=lambda i: values[i])
    groups = [[order[0]]]
    for i in order[1:]:
        if values[i] - values[groups[-1][0]] > tol:
            groups.append([])
        groups[-1].append(i)
    return groups


@dataclasses.dataclass
class Layout:
    refs: list
    rows: list               # [[ref]] top to bottom, left to right (parts only)
    cells: dict              # {ref: (dx, row)}: text centre from the box's left edge, row index counted from the top (a heading is row 0)
    heading: str | None
    heading_dx: float
    W: float
    H: float
    mode: str

    def row_y(self, by, r, cfg):
        """centre y of row r in a box whose bottom edge is by"""
        return by + self.H - cfg.KEY_MARGIN - cfg.KEY_INK_H * cfg.KEY_TEXT_H / 2 - r * cfg.KEY_ROW_PITCH


def build(refs, xy, cfg, heading=None, compact=False, bands=None):
    """the rows, the text offsets and the size of a key for `refs` at positions `xy` {ref: (x, y)} (Due mm). compact: staggered columns; bands=k: dense"""
    if bands:
        return _dense(refs, xy, cfg, heading)
    h = cfg.KEY_TEXT_H
    wid = {r: len(r) * cfg.KEY_ADVANCE * h for r in refs}
    ys = [xy[r][1] for r in refs]
    xs = [xy[r][0] for r in refs]
    rowgroups = cluster_1d(ys, cfg.KEY_ROW_TOL)[::-1]
    row_of = {refs[i]: n for n, g in enumerate(rowgroups) for i in g}
    rows = [sorted((refs[i] for i in g), key=lambda r: xy[r][0]) for g in rowgroups]
    colgroups = cluster_1d(xs, cfg.KEY_ROW_TOL)
    r0 = 1 if heading else 0
    cells = {}
    m = cfg.KEY_MARGIN
    if not compact:
        longest = max(wid.values())
        for c, g in enumerate(colgroups):
            for i in g:
                cells[refs[i]] = (m + c * (longest + cfg.KEY_COL_GAP) + wid[refs[i]] / 2, row_of[refs[i]] + r0)
        width = (len(colgroups) - 1) * (longest + cfg.KEY_COL_GAP) + longest + 2 * m
    else:
        last = {}                                    # row -> right edge of its last text
        prev = None
        width = 2 * m
        for g in colgroups:
            need = max(last.get(row_of[refs[i]], m - cfg.KEY_COL_GAP) + cfg.KEY_COL_GAP + wid[refs[i]] / 2 for i in g)
            X = max(need, (prev + DELTA) if prev is not None else need)
            for i in g:
                cells[refs[i]] = (X, row_of[refs[i]] + r0)
                last[row_of[refs[i]]] = X + wid[refs[i]] / 2
            prev = X
            width = max(width, X + max(wid[refs[i]] for i in g) / 2 + m)
    hw = (len(heading) * cfg.KEY_ADVANCE * h + 2 * m) if heading else 0.0
    W = max(width, hw)
    H = (len(rows) + r0 - 1) * cfg.KEY_ROW_PITCH + cfg.KEY_INK_H * h + 2 * m
    return Layout(list(refs), rows, cells, heading, (m + len(heading) * cfg.KEY_ADVANCE * h / 2) if heading else 0.0, W, H, 'compact' if compact else 'grid')


def _dense(refs, xy, cfg, heading, target=None):
    """the order-keeping sweep: parts are placed left to right by x; each text takes the least x, then the least row, at which it is in the order
    silkread asks for (strictly right of every text whose part is more than ORDER_MIN left of it, strictly below every text whose part is more
    than ORDER_MIN higher, and the other way) and clear of every placed text. Rows are fractional (the step between two orders is DELTA).
    `target` (width, height) is the room the key is for: of the places in order, the one that grows the box least relative to it is taken."""
    tw, th = target or (28.0, 17.0)
    h = cfg.KEY_TEXT_H
    wid = {r: len(r) * cfg.KEY_ADVANCE * h for r in refs}
    m = cfg.KEY_MARGIN
    o = cfg.KEY_ROW_TOL                                  # silkread's ORDER_MIN
    d = DELTA / cfg.KEY_ROW_PITCH                        # the least row step between two ordered texts
    r0 = 1 if heading else 0
    placed = {}                                          # ref -> (X centre from the box's left, row)
    for r in sorted(refs, key=lambda q: (xy[q][0], -xy[q][1], q)):
        xmin = m + wid[r] / 2
        lo, hi = r0, float('inf')
        for q, (X, ry) in placed.items():
            if xy[r][0] - xy[q][0] > o:
                xmin = max(xmin, X + DELTA)
            if xy[q][1] - xy[r][1] > o:
                lo = max(lo, ry + d)
            elif xy[r][1] - xy[q][1] > o:
                hi = min(hi, ry - d)
        xs = sorted({xmin} | {max(xmin, X + (wid[q] + wid[r]) / 2 + cfg.KEY_COL_GAP) for q, (X, _) in placed.items()})
        rys = sorted({lo} | {ry + 1.0 for _, ry in placed.values()} | {ry - 1.0 for _, ry in placed.values()})
        done, best = None, None
        for X in xs:
            for ry in rys:
                if ry < lo - 1e-9 or ry > hi + 1e-9:
                    continue
                if all(abs(X - Xq) >= (wid[r] + wid[q]) / 2 + cfg.KEY_COL_GAP - 1e-9 or abs(ry - yq) >= 1.0 - 1e-9 for q, (Xq, yq) in placed.items()):
                    gw = max([X + wid[r] / 2] + [Xq + wid[q] / 2 for q, (Xq, _) in placed.items()]) + m
                    gh = max([ry] + [yq for _, yq in placed.values()]) * cfg.KEY_ROW_PITCH + cfg.KEY_INK_H * h + 2 * m
                    cost = (max(gw / tw, gh / th), X, ry)
                    if best is None or cost < best:
                        best, done = cost, (X, ry)
        if done is None:                                     # no place within the order: stack it under everything
            done = (xmin, max([ry for _, ry in placed.values()] + [lo]) + 1.0)
        placed[r] = done
    ncell = placed
    W = max(max(X + wid[r] / 2 for r, (X, _) in ncell.items()) + m, (len(heading) * cfg.KEY_ADVANCE * h + 2 * m) if heading else 0.0)
    H = max(ry for _, ry in ncell.values()) * cfg.KEY_ROW_PITCH + cfg.KEY_INK_H * h + 2 * m
    rows = [sorted(refs, key=lambda q: (ncell[q][1], ncell[q][0]))]
    return Layout(list(refs), rows, dict(ncell), heading, (m + len(heading) * cfg.KEY_ADVANCE * h / 2) if heading else 0.0, W, H, 'dense')


def order_ok(ly, xy, cfg):
    """silkread's order test on a layout: two parts further apart than KEY_ROW_TOL along x or y have their texts in the same order along it (a tie is
    an error); text y is down the key, so the part's y runs the other way"""
    pos = {r: (dx, -row) for r, (dx, row) in ly.cells.items()}
    for a in ly.refs:
        for c in ly.refs:
            for ax in (0, 1):
                dp = xy[c][ax] - xy[a][ax]
                dt = pos[c][ax] - pos[a][ax]
                if abs(dp) > cfg.KEY_ROW_TOL and np.sign(dp) != np.sign(dt):
                    return False
    return True


def dense_options(refs, xy, cfg, heading=None, target=None):
    """[Layout]: the order-keeping sweep, if it found every text a place in the order (it can paint itself into a corner; then there is none)"""
    ly = _dense(refs, xy, cfg, heading, target)
    return [ly] if order_ok(ly, xy, cfg) else []


def layout(refs, xy, cfg):
    """(rows, ncols, col_of) of the grid layout, for callers that want the structure: rows top to bottom, each left to right"""
    ly = build(refs, xy, cfg)
    cols = sorted({round(c[0] - len(r) * cfg.KEY_ADVANCE * cfg.KEY_TEXT_H / 2, 3) for r, c in ly.cells.items()})
    col_of = {r: cols.index(round(c[0] - len(r) * cfg.KEY_ADVANCE * cfg.KEY_TEXT_H / 2, 3)) for r, c in ly.cells.items()}
    return ly.rows, len(cols), col_of


def size(refs, ncols, nrows, cfg):
    """(width, height) of a grid key box of ncols columns and nrows rows: the longest designator sets every column's pitch, so the columns line up"""
    h = cfg.KEY_TEXT_H
    longest = max(len(r) for r in refs) * cfg.KEY_ADVANCE * h
    w = (ncols - 1) * (longest + cfg.KEY_COL_GAP) + longest + 2 * cfg.KEY_MARGIN
    hh = (nrows - 1) * cfg.KEY_ROW_PITCH + cfg.KEY_INK_H * h + 2 * cfg.KEY_MARGIN
    return w, hh


class Grid:
    """occupancy of the board top in Due mm: True = taken"""

    def __init__(self, rect):
        self.x0, self.y0, x1, y1 = rect
        self.nx, self.ny = int(round((x1 - self.x0) / RES)), int(round((y1 - self.y0) / RES))
        self.occ = np.zeros((self.ny, self.nx), bool)

    def mark(self, x0, y0, x1, y1, grow=0.0):
        ix0 = max(0, int(np.floor((x0 - grow - self.x0) / RES)))
        ix1 = min(self.nx, int(np.ceil((x1 + grow - self.x0) / RES)))
        iy0 = max(0, int(np.floor((y0 - grow - self.y0) / RES)))
        iy1 = min(self.ny, int(np.ceil((y1 + grow - self.y0) / RES)))
        if ix1 > ix0 and iy1 > iy0:
            self.occ[iy0:iy1, ix0:ix1] = True

    def box_free(self, x0, y0, x1, y1):
        ix0, ix1 = int(round((x0 - self.x0) / RES)), int(round((x1 - self.x0) / RES))
        iy0, iy1 = int(round((y0 - self.y0) / RES)), int(round((y1 - self.y0) / RES))
        if ix0 < 0 or iy0 < 0 or ix1 > self.nx or iy1 > self.ny:
            return False
        return not self.occ[iy0:iy1, ix0:ix1].any()

    def free_positions(self, W, H):
        """lower-left corners (x, y) of every W x H rectangle wholly free"""
        S = np.zeros((self.ny + 1, self.nx + 1), np.int64)
        S[1:, 1:] = self.occ.cumsum(0).cumsum(1)
        w, h = int(round(W / RES)), int(round(H / RES))
        if w >= self.nx or h >= self.ny:
            return np.array([]), np.array([])
        sums = S[h:, w:] - S[:-h, w:] - S[h:, :-w] + S[:-h, :-w]
        iy, ix = np.nonzero(sums == 0)
        return ix * RES + self.x0, iy * RES + self.y0


def _gap(x, y, W, H, ext):
    dx = np.maximum(0, np.maximum(ext[0] - (x + W), x - ext[2]))
    dy = np.maximum(0, np.maximum(ext[1] - (y + H), y - ext[3]))
    return np.hypot(dx, dy)


def silk_boxes(text, cfg):
    """boxes (Due mm) of the board-level F.SilkS lines and words; footprint silk lies inside its courtyard, which is counted already"""
    out = []
    for m in re.finditer(r'\n\t\((?:gr_line|gr_rect)\n\t\t\(start ([-\d.]+) ([-\d.]+)\)\n\t\t\(end ([-\d.]+) ([-\d.]+)\)(.*?)\n\t\t\(layer "F\.SilkS"\)', text, re.S):
        a, b, c, d = (float(m.group(i)) for i in (1, 2, 3, 4))
        w = re.search(r'\(width ([\d.]+)\)', m.group(5))
        w = float(w.group(1)) if w else 0.15
        out.append((min(a, c) - 50 - w / 2, 150 - max(b, d) - w / 2, max(a, c) - 50 + w / 2, 150 - min(b, d) + w / 2))
    for m in re.finditer(r'\n\t\(gr_text "([^"]*)"\n\t\t\(at ([-\d.]+) ([-\d.]+)( [-\d.]+)?\)\n\t\t\(layer "F\.SilkS"\)', text):
        L, H = len(m.group(1)) * cfg.KEY_ADVANCE, cfg.KEY_INK_H
        if int(round(float(m.group(4) or 0))) % 180 == 90:
            L, H = H, L
        x, y = float(m.group(2)) - 50, 150 - float(m.group(3))
        out.append((x - L / 2, y - H / 2, x + L / 2, y + H / 2))
    return out


def board_grid(b, text, cfg, keyed=(), tracks=None):
    """the free-area measure: courtyards, pads, vias, every silk line and word, and every designator still on the silk, each grown by KEY_CLEAR;
    `keyed` designators are not counted (they are coming off). Tracks are NOT taken by default: silk over a mask-covered track is allowed, so a
    free area may lie over copper. `tracks=True` (or the config's KEY_AVOID_TRACKS) counts them too, for a board whose tracks are bare."""
    x0, y0, x1, y1 = (float(b.outline[:, 0].min()), float(b.outline[:, 1].min()), float(b.outline[:, 0].max()), float(b.outline[:, 1].max()))
    g = Grid((x0, y0, x1, y1))
    c = cfg.KEY_CLEAR
    for i in range(len(b.fp_ref)):
        if not np.isnan(b.fp_cx0[i]):
            g.mark(b.fp_cx0[i], b.fp_cy0[i], b.fp_cx1[i], b.fp_cy1[i], c)
    for k in range(len(b.p_x)):
        g.mark(b.p_bx0[k], b.p_by0[k], b.p_bx1[k], b.p_by1[k], c)
    for k in range(len(b.v_x)):
        r = b.v_dia[k] / 2 + c
        g.mark(b.v_x[k] - r, b.v_y[k] - r, b.v_x[k] + r, b.v_y[k] + r)
    if tracks if tracks is not None else getattr(cfg, 'KEY_AVOID_TRACKS', False):
        for k in range(len(b.s_x0)):                      # a segment as the boxes along it, so a long diagonal does not take its whole bounding box
            n = max(1, int(np.hypot(b.s_x1[k] - b.s_x0[k], b.s_y1[k] - b.s_y0[k]) / 0.5))
            for j in range(n + 1):
                x, y = b.s_x0[k] + (b.s_x1[k] - b.s_x0[k]) * j / n, b.s_y0[k] + (b.s_y1[k] - b.s_y0[k]) * j / n
                g.mark(x, y, x, y, b.s_w[k] / 2 + c)
        for k in range(len(b.a_x0)):
            for pts in (((b.a_x0[k], b.a_y0[k]), (b.a_xm[k], b.a_ym[k])), ((b.a_xm[k], b.a_ym[k]), (b.a_x1[k], b.a_y1[k]))):
                (xa, ya), (xb, yb) = pts
                n = max(1, int(np.hypot(xb - xa, yb - ya) / 0.5))
                for j in range(n + 1):
                    g.mark(xa + (xb - xa) * j / n, ya + (yb - ya) * j / n, xa + (xb - xa) * j / n, ya + (yb - ya) * j / n, b.a_w[k] / 2 + c)
    for k in range(len(b.r_x)):
        ref = b.fp_ref[int(b.r_fp[k])]
        if not b.r_on_silk[k] or ref in keyed:
            continue
        L, H = len(ref) * cfg.KEY_ADVANCE * b.r_h[k], cfg.KEY_INK_H * b.r_h[k]
        if int(round(b.r_ang[k])) % 180 == 90:
            L, H = H, L
        g.mark(b.r_x[k] - L / 2, b.r_y[k] - H / 2, b.r_x[k] + L / 2, b.r_y[k] + H / 2, c)
    for (bx0, by0, bx1, by1) in silk_boxes(text, cfg):
        g.mark(bx0, by0, bx1, by1, c)
    return g


def _positions(b, refs):
    return {r: (float(b.fp_x[b.ref_index(r)]), float(b.fp_y[b.ref_index(r)])) for r in refs}


def _plan_at(name, ly, bx, by, gap, cfg, heading=None):
    texts = {r: (round(bx + dx, 3), round(ly.row_y(by, row, cfg), 3)) for r, (dx, row) in ly.cells.items()}
    hat = (round(bx + ly.heading_dx, 3), round(ly.row_y(by, 0, cfg), 3)) if heading else None
    return Plan(name, (bx, by, round(bx + ly.W, 3), round(by + ly.H, 3)), texts, ly.rows, gap, heading, hat, ly.mode)


def plan(b, text, cfg, name, parts=None):
    """a local key. `parts` (an arbitrary residue list) overrides the config's KEYS[name]['parts']. Grid first, then compact."""
    refs = list(cfg.KEYS[name]['parts'] if parts is None else parts)
    xy = _positions(b, refs)
    idx = [b.ref_index(r) for r in refs]
    ext = (min(b.fp_cx0[i] for i in idx), min(b.fp_cy0[i] for i in idx), max(b.fp_cx1[i] for i in idx), max(b.fp_cy1[i] for i in idx))
    g = board_grid(b, text, cfg, keyed=set(refs))
    first = None
    for compact in (False, True):
        ly = build(refs, xy, cfg, compact=compact)
        first = first or ly
        x, y = g.free_positions(ly.W, ly.H)
        gaps = _gap(x, y, ly.W, ly.H, ext) if len(x) else np.array([])
        ok = np.flatnonzero(gaps <= cfg.KEY_ADJOIN_MAX)
        if len(ok):
            j = ok[int(gaps[ok].argmin())]
            return _plan_at(name, ly, round(float(x[j]), 1), round(float(y[j]), 1), float(gaps[j]), cfg)
    ly = first
    x, y = g.free_positions(ly.W, ly.H)
    gaps = _gap(x, y, ly.W, ly.H, ext) if len(x) else np.array([])
    j = int(gaps.argmin()) if len(gaps) else None
    big = (0.0, 0.0)
    for w in np.arange(2, 30, 0.5):
        for h in np.arange(2, 20, 0.5):
            xx, yy = g.free_positions(w, h)
            if len(xx) and (_gap(xx, yy, w, h, ext) <= cfg.KEY_ADJOIN_MAX).any() and w * h > big[0] * big[1]:
                big = (float(w), float(h))
    return NoFit(name, (ly.W, ly.H), None if j is None else float(gaps[j]), None if j is None else (round(float(x[j]), 1), round(float(y[j]), 1)), big)


def _cour(b, r):
    i = b.ref_index(r)
    return (float(b.fp_cx0[i]), float(b.fp_cy0[i]), float(b.fp_cx1[i]), float(b.fp_cy1[i]))


def _cgap(a, c):
    return float(np.hypot(max(c[0] - a[2], a[0] - c[2], 0.0), max(c[1] - a[3], a[1] - c[3], 0.0)))


def split_items(b, items, gap, span=None):
    """each block's residue cut into spatial clusters, one key each under the block's heading (several keys may share a heading). Agglomerative:
    every part starts alone, and the two clusters whose courtyards are nearest, if within `gap` mm and if the part positions of the merged cluster
    span at most `span` (a (width, height) in mm, or one number for both; None = no limit), are merged, until none can be. With no span that is
    plain chaining by courtyard distance. A key needs two designators, so a cluster of one part joins the cluster nearest to it (span or not); a
    block whose parts are all alone stays one key. -> [(heading, [refs])] in the items' order, a cluster's parts in theirs"""
    sw, sh = (span, span) if isinstance(span, (int, float)) else (span or (None, None))
    out = []
    for head, refs in items:
        cour = {r: _cour(b, r) for r in refs}
        ctr = {r: ((cour[r][0] + cour[r][2]) / 2, (cour[r][1] + cour[r][3]) / 2) for r in refs}
        clusters = [[r] for r in refs]

        def merged_ok(a, c):
            pts = [ctr[r] for r in a + c]
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            return (sw is None or max(xs) - min(xs) <= sw) and (sh is None or max(ys) - min(ys) <= sh)
        while True:
            best = None
            for i in range(len(clusters)):
                for j in range(i + 1, len(clusters)):
                    d = min(_cgap(cour[p], cour[q]) for p in clusters[i] for q in clusters[j])
                    if d <= gap and merged_ok(clusters[i], clusters[j]) and (best is None or d < best[0]):
                        best = (d, i, j)
            if best is None:
                break
            _, i, j = best
            clusters[i] = clusters[i] + clusters[j]
            del clusters[j]
        big = [c for c in clusters if len(c) > 1]
        if not big:
            out.append((head, list(refs)))
            continue
        for c in [c for c in clusters if len(c) == 1]:
            near = min(big, key=lambda k: min(_cgap(cour[c[0]], cour[q]) for q in k))
            near.append(c[0])
        for c in big:
            out.append((head, [r for r in refs if r in c]))
    return out


def free_rectangles(g, min_w, min_h, count, edge=0.0, gap=0.0, within=None):
    """up to `count` rectangles (Due mm) wholly free on grid `g`, each at least min_w x min_h, taken greedily: the one of the largest area, then the next
    in what is left (`gap` mm kept clear of the earlier ones), `edge` mm in from the board's bounding box, and only inside `within` (x0, y0, x1, y1) if
    given (a board with bands the legend must stay out of). -> [(x0, y0, x1, y1)]"""
    free = ~g.occ
    if within is not None:
        wx0, wy0, wx1, wy1 = (int(round((within[0] - g.x0) / RES)), int(round((within[1] - g.y0) / RES)), int(round((within[2] - g.x0) / RES)), int(round((within[3] - g.y0) / RES)))
        keep = np.zeros_like(free)
        keep[max(0, wy0):wy1, max(0, wx0):wx1] = True
        free &= keep
    e = int(round(edge / RES))
    if e:
        free[:e, :] = False
        free[-e:, :] = False
        free[:, :e] = False
        free[:, -e:] = False
    out = []
    gcells = int(round(gap / RES))
    for _ in range(count):
        best = (0, 0, 0, 0, 0)
        hts = np.zeros(g.nx, np.int64)
        for iy in range(g.ny):
            hts = np.where(free[iy], hts + 1, 0)
            stack = []                                       # (start column, height): the classic histogram scan
            for ix in range(g.nx + 1):
                h = int(hts[ix]) if ix < g.nx else 0
                start = ix
                while stack and stack[-1][1] >= h:
                    s, sh = stack.pop()
                    area = (ix - s) * sh
                    if area > best[0] and (ix - s) * RES >= min_w - 1e-9 and sh * RES >= min_h - 1e-9:       # a maximal rectangle that is big enough both ways
                        best = (area, s, iy - sh + 1, ix, iy + 1)
                    start = s
                stack.append((start, h))
        area, ix0, iy0, ix1, iy1 = best
        if (ix1 - ix0) * RES < min_w or (iy1 - iy0) * RES < min_h:
            break
        out.append((round(g.x0 + ix0 * RES, 2), round(g.y0 + iy0 * RES, 2), round(g.x0 + ix1 * RES, 2), round(g.y0 + iy1 * RES, 2)))
        free[max(0, iy0 - gcells):iy1 + gcells, max(0, ix0 - gcells):ix1 + gcells] = False
    return out


def existing_keys(text):
    """{heading-or-None: [set of the words inside]} for each unfilled F.SilkS gr_rect of the board text, from the texts whose centre is inside it"""
    words = [(m.group(1), float(m.group(2)) - 50, 150 - float(m.group(3))) for m in re.finditer(
        r'\(gr_text "([^"]*)"\n\t\t\(at ([-\d.]+) ([-\d.]+)[^)]*\)\n\t\t\(layer "F\.SilkS"\)', text)]
    out = []
    for m in re.finditer(r'\(gr_rect\n\t\t\(start ([-\d.]+) ([-\d.]+)\)\n\t\t\(end ([-\d.]+) ([-\d.]+)\)(.*?)\n\t\)', text, re.S):
        if '(fill yes)' in m.group(5) or '(layer "F.SilkS")' not in m.group(5):
            continue
        x0, x1 = sorted((float(m.group(1)) - 50, float(m.group(3)) - 50))
        y0, y1 = sorted((150 - float(m.group(2)), 150 - float(m.group(4))))
        out.append({w for w, x, y in words if x0 < x < x1 and y0 < y < y1})
    return out


def legend(b, text, cfg, items, regions, grid=None, split=None, auto=None, span=None):
    """the keys of `items` [(heading, [refs])] packed into `regions` [(x0, y0, x1, y1)] (an L of several rectangles is fine; a key lies in one), each
    wholly on free area, first-fit from the top left of the first region that takes it, tallest first, so the boxes line up in rows. Grid layouts
    first; if they do not all fit, compact ones. -> [Plan] in the order of `items`, or LegendNoFit (the last attempt, each key in its smallest layout)"""
    blocks = getattr(cfg, 'KEY_BLOCKS', {})
    for head, refs in items:
        if head not in blocks:
            raise ValueError(f'{head!r} is not a block heading of the config (KEY_BLOCKS)')
        bad = [r for r in refs if next((c for c in r if c.isdigit()), None) != blocks[head]]
        if bad:
            raise ValueError(f'{bad} are not in block {head} by their designators')
    split = split if split is not None else getattr(cfg, 'KEY_SPLIT_GAP', None)
    span = span if span is not None else getattr(cfg, 'KEY_SPLIT_SPAN', None)
    if split is not None or span is not None:
        items = split_items(b, items, split if split is not None else float('inf'), span)
    have = existing_keys(text)
    items = [(h, refs) for h, refs in items if not any(h in w and set(refs) <= w for w in have)]       # a key already on the board is left as it is
    if not items:
        return []
    allrefs = [r for _, refs in items for r in refs]
    g = grid if grid is not None else board_grid(b, text, cfg, keyed=set(allrefs))
    regions = list(regions)
    if auto:                                                  # more regions: the biggest free rectangles of the board (what the given regions leave free is among them)
        regions += free_rectangles(g, auto[0], auto[1], auto[2], edge=getattr(cfg, 'KEY_EDGE', 0.5), within=getattr(cfg, 'KEY_WITHIN', None))
    xy = _positions(b, allrefs)
    last = None
    maxw, maxh = max(r[2] - r[0] for r in regions), max(r[3] - r[1] for r in regions)
    for mode in ('grid', 'compact', 'dense', 'best'):
        if mode in ('dense', 'best'):
            lays = []
            for h, refs in items:
                opts = dense_options(refs, xy, cfg, h, (maxw, maxh))
                if mode == 'best':
                    opts += [build(refs, xy, cfg, heading=h), build(refs, xy, cfg, heading=h, compact=True)]
                if not opts:
                    lays = None
                    break
                fit = [o for o in opts if o.W <= maxw and o.H <= maxh] or opts
                lays.append((h, min(fit, key=lambda o: (o.W * o.H, max(o.W, o.H)))))
        else:
            lays = [(h, build(refs, xy, cfg, heading=h, compact=(mode == 'compact'))) for h, refs in items]
        if lays is None:
            continue
        cache = {}
        base = sorted(range(len(lays)), key=lambda i: (-lays[i][1].H, -lays[i][1].W))
        for order in itertools.chain([tuple(base)], itertools.islice((o for o in itertools.permutations(range(len(lays))) if list(o) != base), 200)):
            placed, failed = _pack(lays, order, regions, g, cfg, cache)
            if failed is None:
                return [placed[i] for i in range(len(lays))]
        last = LegendNoFit([(h, ly.W, ly.H, ly.mode) for h, ly in lays], [(r[2] - r[0], r[3] - r[1]) for r in regions],
                           [lays[i][0] for i in base if i in _pack(lays, tuple(base), regions, g, cfg, cache)[0]], _pack(lays, tuple(base), regions, g, cfg, cache)[1])
    return last


def legend_fit(b, text, cfg, items, regions, grid=None, split=None, auto=None, span=None):
    """as legend(), but when not every key fits, the keys that do: ([Plan], [(heading, refs, W, H)] left over). Each key (a cluster, if split) in its smallest
    layout; of three orders (as given, smallest first, largest first) the one that keys the most parts wins, ties to the first. Every Plan is a complete
    key, so a board with some of its keys placed is as valid as one with all of them"""
    res = legend(b, text, cfg, items, regions, grid=grid, split=split, auto=auto, span=span)
    if isinstance(res, list):
        return res, []
    split = split if split is not None else getattr(cfg, 'KEY_SPLIT_GAP', None)
    span = span if span is not None else getattr(cfg, 'KEY_SPLIT_SPAN', None)
    if split is not None or span is not None:
        items = split_items(b, items, split if split is not None else float('inf'), span)
    have = existing_keys(text)
    items = [(h, refs) for h, refs in items if not any(h in w and set(refs) <= w for w in have)]
    allrefs = [r for _, refs in items for r in refs]
    g = grid if grid is not None else board_grid(b, text, cfg, keyed=set(allrefs))
    regions = list(regions)
    if auto:
        regions += free_rectangles(g, auto[0], auto[1], auto[2], edge=getattr(cfg, 'KEY_EDGE', 0.5), within=getattr(cfg, 'KEY_WITHIN', None))
    xy = _positions(b, allrefs)
    maxw, maxh = max(r[2] - r[0] for r in regions), max(r[3] - r[1] for r in regions)
    lays = []
    for h, refs in items:
        opts = dense_options(refs, xy, cfg, h, (maxw, maxh)) + [build(refs, xy, cfg, heading=h), build(refs, xy, cfg, heading=h, compact=True)]
        lays.append((h, min(opts, key=lambda o: (o.W * o.H, max(o.W, o.H)))))
    cache = {}
    orders = [list(range(len(lays))), sorted(range(len(lays)), key=lambda i: lays[i][1].W * lays[i][1].H),
              sorted(range(len(lays)), key=lambda i: -lays[i][1].W * lays[i][1].H)]
    best = None
    for order in orders:
        placed, boxes = {}, np.zeros((0, 4))
        for i in order:
            h, ly = lays[i]
            c = _candidates(ly, regions, g, cache)
            ok = np.ones(len(c), bool)
            if len(boxes) and len(c):
                gp = cfg.KEY_GAP
                ok = np.all((c[:, None, 0] + ly.W + gp <= boxes[None, :, 0]) | (boxes[None, :, 2] + gp <= c[:, None, 0])
                            | (c[:, None, 1] + ly.H + gp <= boxes[None, :, 1]) | (boxes[None, :, 3] + gp <= c[:, None, 1]), axis=1)
            idx = np.flatnonzero(ok)
            if len(idx):
                x, y = (round(float(v), 1) for v in c[idx[0]])
                boxes = np.vstack([boxes, [x, y, x + ly.W, y + ly.H]])
                placed[i] = _plan_at(h, ly, x, y, None, cfg, heading=h)
        n = sum(len(lays[i][1].refs) for i in placed)
        if best is None or n > best[0]:
            best = (n, placed)
    placed = best[1]
    left = [(lays[i][0], lays[i][1].refs, lays[i][1].W, lays[i][1].H) for i in range(len(lays)) if i not in placed]
    return [placed[i] for i in sorted(placed)], left


def _candidates(ly, regions, g, cache):
    """lower-left corners (x, y) where a W x H box is wholly free and wholly in one region: region by region (the given order), top row first, left to right"""
    key = (round(ly.W, 3), round(ly.H, 3))
    if key not in cache:
        xs, ys = g.free_positions(ly.W, ly.H)
        out = []
        for (rx0, ry0, rx1, ry1) in regions:
            m = (xs >= rx0 - 1e-6) & (ys >= ry0 - 1e-6) & (xs + ly.W <= rx1 + 1e-6) & (ys + ly.H <= ry1 + 1e-6)
            sel = np.flatnonzero(m)
            sel = sel[np.lexsort((xs[sel], -ys[sel]))]
            out.append(np.column_stack([xs[sel], ys[sel]]))
        cache[key] = np.vstack(out) if out else np.zeros((0, 2))
    return cache[key]


def _pack(lays, order, regions, g, cfg, cache=None):
    """first-fit of the layouts in `order`: ({index: Plan}, the heading that found no place or None)"""
    cache = {} if cache is None else cache
    placed = {}
    boxes = np.zeros((0, 4))
    for i in order:
        h, ly = lays[i]
        c = _candidates(ly, regions, g, cache)
        ok = np.ones(len(c), bool)
        if len(boxes) and len(c):
            gap = cfg.KEY_GAP
            ok = np.all((c[:, None, 0] + ly.W + gap <= boxes[None, :, 0]) | (boxes[None, :, 2] + gap <= c[:, None, 0])
                        | (c[:, None, 1] + ly.H + gap <= boxes[None, :, 1]) | (boxes[None, :, 3] + gap <= c[:, None, 1]), axis=1)
        idx = np.flatnonzero(ok)
        if not len(idx):
            return placed, h
        x, y = (round(float(v), 1) for v in c[idx[0]])
        boxes = np.vstack([boxes, [x, y, x + ly.W, y + ly.H]])
        placed[i] = _plan_at(h, ly, x, y, None, cfg, heading=h)
    return placed, None


# ---------------------------------------------------------------------------------------------------- the text splice
def _fp_span(text, ref):
    for m in re.finditer(r'\n\t\(footprint "[^"]*"\n', text):
        end = text.find('\n\t(footprint ', m.end())
        end = len(text) if end < 0 else end
        if re.search(r'\(property "Reference" "%s"' % re.escape(ref), text[m.start():end]):
            return m.start(), end
    raise KeyError(ref)


def _fmt(v):
    return ('%.4f' % v).rstrip('0').rstrip('.')


def _text_item(label, x, y, cfg, key):
    sx, sy = x + 50.0, 150.0 - y
    body = (f'\t(gr_text "{label}"\n\t\t(at {_fmt(sx)} {_fmt(sy)} 0)\n\t\t(layer "F.SilkS")\n\t\t(uuid "{{u}}")\n\t\t(effects\n\t\t\t(font\n'
            f'\t\t\t\t(size {cfg.KEY_TEXT_H:g} {cfg.KEY_TEXT_H:g})\n\t\t\t\t(thickness {cfg.KEY_STROKE:g})\n\t\t\t)\n\t\t)\n\t)\n')
    return (('gr_text', label, _fmt(sx), _fmt(sy)), body)


def apply(text, plans, cfg):
    """the board text with the key(s) of `plans` (one Plan or a list) in it and their parts' Reference fields on F.Fab; idempotent"""
    plans = [plans] if isinstance(plans, Plan) else list(plans)
    for p in plans:
        for ref in p.texts:
            s, e = _fp_span(text, ref)
            blk = text[s:e]
            pat = re.compile(r'(\(property "Reference" "%s"\n\t\t\t\(at [^)]*\)\n\t\t\t\(layer ")F\.SilkS(")' % re.escape(ref))
            if pat.search(blk):
                text = text[:s] + pat.sub(r'\1F.Fab\2', blk, count=1) + text[e:]
    items = []
    for p in plans:
        x0, y0, x1, y1 = p.box
        sa, sb, sc, sd = x0 + 50.0, 150.0 - y1, x1 + 50.0, 150.0 - y0                   # sheet mm: top-left and bottom-right corners
        items.append((('gr_rect', _fmt(sa), _fmt(sb), _fmt(sc), _fmt(sd)),
                      f'\t(gr_rect\n\t\t(start {_fmt(sa)} {_fmt(sb)})\n\t\t(end {_fmt(sc)} {_fmt(sd)})\n\t\t(stroke\n\t\t\t(width {cfg.KEY_STROKE:g})\n'
                      f'\t\t\t(type default)\n\t\t)\n\t\t(fill no)\n\t\t(layer "F.SilkS")\n\t\t(uuid "{{u}}")\n\t)\n'))
        if p.heading:
            items.append(_text_item(p.heading, p.heading_at[0], p.heading_at[1], cfg, p.name))
        for ref, (x, y) in sorted(p.texts.items()):
            items.append(_text_item(ref, x, y, cfg, p.name))
    new = ''
    for key, body in items:
        if key[0] == 'gr_text':
            have = re.search(r'\n\t\(gr_text "%s"\n\t\t\(at %s %s 0\)' % (re.escape(key[1]), re.escape(key[2]), re.escape(key[3])), text)
        else:
            have = f'\n\t(gr_rect\n\t\t(start {key[1]} {key[2]})\n\t\t(end {key[3]} {key[4]})' in text
        if not have:
            new += body.replace('{u}', KEY_UUID_PREFIX + str(uuid.uuid5(uuid.NAMESPACE_URL, f'keys {key}'))[len(KEY_UUID_PREFIX):])
    if new:
        i = text.rstrip().rfind(')')                        # the end of the file; the splices of the pin labels and the identity block skip KEY_UUID_PREFIX items
        text = text[:i] + new + text[i:]
    return text


def main(argv=None):
    import argparse
    import importlib
    ap = argparse.ArgumentParser(prog='python3 -m pcbtools.keys', description=__doc__.split('\n\n')[0])
    ap.add_argument('board')
    ap.add_argument('name', nargs='?', help='a local key: a name in the config\'s KEYS')
    ap.add_argument('--parts', help='comma separated residue list instead of the config\'s KEYS[name][\'parts\']')
    ap.add_argument('--legend', help='"HEADING=R1,R2;HEADING=R3,R4": keys gathered in the legend --region(s)')
    ap.add_argument('--region', action='append', default=[], help='x0,y0,x1,y1 in Due mm; repeat for an L')
    ap.add_argument('--split', type=float, help='cut each block\'s residue into clusters whose courtyards are within this many mm (default: the config\'s KEY_SPLIT_GAP, else one key per block)')
    ap.add_argument('--span', help='W,H (or one number): a cluster span at most this wide and high (default: the config KEY_SPLIT_SPAN)')
    ap.add_argument('--auto', help='MIN_W,MIN_H,COUNT: also use the biggest free rectangles of the board (silk over tracks allowed unless KEY_AVOID_TRACKS)')
    ap.add_argument('--fit', action='store_true', help='with --legend: place the keys that fit and list the rest, instead of all or none')
    ap.add_argument('--config', default='v2_layout')
    ap.add_argument('--write', help='write the edited board here (default: report only)')
    a = ap.parse_args(argv)
    from . import boardio
    cfg = importlib.import_module(f'pcbtools.boards.{a.config}')
    with open(a.board) as fh:
        text = fh.read()
    b = boardio.read_board(a.board)
    if a.legend:
        items = [(h.strip(), r.split(',')) for h, r in (s.split('=') for s in a.legend.split(';'))]
        regions = [tuple(float(v) for v in r.split(',')) for r in a.region]
        auto = tuple(float(v) for v in a.auto.split(',')) if a.auto else None
        if auto:
            auto = (auto[0], auto[1], int(auto[2]))
        span = tuple(float(v) for v in a.span.split(',')) if a.span else None
        if span and len(span) == 1:
            span = span[0]
        if a.fit:
            res, left = legend_fit(b, text, cfg, items, regions, split=a.split, auto=auto, span=span)
            for h, refs, w, hh in left:
                print(f'NOT PLACED {h} {w:.1f} x {hh:.1f}: {" ".join(refs)}')
        else:
            res = legend(b, text, cfg, items, regions, split=a.split, auto=auto, span=span)
            if isinstance(res, LegendNoFit):
                print(res)
                return 1
        for p in res:
            print(f'key {p.heading} ({p.mode}): box {p.box}, {len(p.texts)} designators in {len(p.rows)} rows')
        plans = res
    else:
        p = plan(b, text, cfg, a.name, a.parts.split(',') if a.parts else None)
        if isinstance(p, NoFit):
            print(p)
            return 1
        print(f'key {p.name} ({p.mode}): box {p.box}, {sum(len(r) for r in p.rows)} designators in {len(p.rows)} rows, {p.gap:.2f} mm from its cluster')
        plans = [p]
    if a.write:
        with open(a.write, 'w') as fh:
            fh.write(apply(text, plans, cfg))
    return 0


if __name__ == '__main__':
    sys.exit(main())
