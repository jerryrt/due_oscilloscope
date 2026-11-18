"""Cluster keys (D30 1b): where a cluster of parts is held tight on purpose, its designators come off the parts and one outlined key carries
them in the parts' order, rows and columns. Board-agnostic: the board's own config says which clusters (`KEYS`) and the thresholds; nothing
here names a board, a part or a net. No arrow or leader line is ever drawn.

Two places for a key:
  * local: in free area within KEY_ADJOIN_MAX of its cluster, no heading;
  * legend: when no key fits beside its parts, the keys gather in one legend area (one rectangle or an L of several), each under its block's
    name as a heading (one F.SilkS text inside the box; the names are the config's KEY_BLOCKS, e.g. "CH1", "REF / CAL"), packed first-fit from
    the top left so the boxes line up, and every part of a key belongs to its heading's block by its designator's hundreds digit.

    plan(b, text, cfg, name, parts=None)         -> Plan | NoFit            a local key, from the board arrays (pcbnew read, in the image) and its text
    legend(b, text, cfg, items, regions)         -> [Plan] | LegendNoFit    items [(heading, [refs])]; regions [(x0, y0, x1, y1)] Due mm, each wholly free
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
centres still strictly increasing left to right, so rows and order are the parts' and columns are staggered.

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
  KEY_STROKE            line width of the box, mm
"""
from __future__ import annotations

import dataclasses
import re
import sys
import uuid

import numpy as np

RES = 0.1                    # occupancy grid, mm
STEP = 0.5                   # a legend is scanned for a free place at this step, mm
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


def build(refs, xy, cfg, heading=None, compact=False):
    """the rows, the text offsets and the size of a key for `refs` at positions `xy` {ref: (x, y)} (Due mm)"""
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


def board_grid(b, text, cfg, keyed=()):
    """the free-area measure: courtyards, pads, vias, every silk line and word, and every designator still on the silk, each grown by KEY_CLEAR;
    `keyed` designators are not counted (they are coming off)"""
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


def legend(b, text, cfg, items, regions, grid=None):
    """the keys of `items` [(heading, [refs])] packed into `regions` [(x0, y0, x1, y1)] (an L of several rectangles is fine; a key lies in one), each
    wholly on free area, first-fit from the top left of the first region that takes it, tallest first, so the boxes line up in rows. Grid layouts
    first; if they do not all fit, compact ones. -> [Plan] in the order of `items`, or LegendNoFit (the last attempt, compact)"""
    blocks = getattr(cfg, 'KEY_BLOCKS', {})
    for head, refs in items:
        if head not in blocks:
            raise ValueError(f'{head!r} is not a block heading of the config (KEY_BLOCKS)')
        bad = [r for r in refs if next((c for c in r if c.isdigit()), None) != blocks[head]]
        if bad:
            raise ValueError(f'{bad} are not in block {head} by their designators')
    allrefs = [r for _, refs in items for r in refs]
    g = grid if grid is not None else board_grid(b, text, cfg, keyed=set(allrefs))
    xy = _positions(b, allrefs)
    last = None
    for compact in (False, True):
        lays = [(h, build(refs, xy, cfg, heading=h, compact=compact)) for h, refs in items]
        order = sorted(range(len(lays)), key=lambda i: (-lays[i][1].H, -lays[i][1].W))
        placed = {}
        boxes = []
        failed = None
        for i in order:
            h, ly = lays[i]
            spot = None
            for (rx0, ry0, rx1, ry1) in regions:
                y = ry1 - ly.H
                while y >= ry0 - 1e-9 and spot is None:
                    x = rx0
                    while x + ly.W <= rx1 + 1e-9:
                        bx = (x, y, x + ly.W, y + ly.H)
                        if g.box_free(*bx) and not any(not (bx[2] + cfg.KEY_GAP <= q[0] or q[2] + cfg.KEY_GAP <= bx[0] or bx[3] + cfg.KEY_GAP <= q[1]
                                                            or q[3] + cfg.KEY_GAP <= bx[1]) for q in boxes):
                            spot = (round(x, 1), round(y, 1))
                            break
                        x += STEP
                    y -= STEP
                if spot:
                    break
            if spot is None:
                failed = h
                break
            boxes.append((spot[0], spot[1], spot[0] + ly.W, spot[1] + ly.H))
            placed[i] = _plan_at(h, ly, spot[0], spot[1], None, cfg, heading=h)
        last = LegendNoFit([(h, ly.W, ly.H, ly.mode) for h, ly in lays], [(r[2] - r[0], r[3] - r[1]) for r in regions],
                           [lays[i][0] for i in order if i in placed], failed)
        if failed is None:
            return [placed[i] for i in range(len(lays))]
    return last


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
            new += body.replace('{u}', str(uuid.uuid5(uuid.NAMESPACE_URL, f'keys {key}')))
    if new:
        i = text.rstrip().rfind(')')
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
    ap.add_argument('--config', default='v2_layout')
    ap.add_argument('--write', help='write the edited board here (default: report only)')
    a = ap.parse_args(argv)
    from pcbkit import board as KB
    from .frame import FRAME
    cfg = importlib.import_module(f'pcbtools.boards.{a.config}')
    with open(a.board) as fh:
        text = fh.read()
    b = KB.read_board(a.board, FRAME)
    if a.legend:
        items = [(h.strip(), r.split(',')) for h, r in (s.split('=') for s in a.legend.split(';'))]
        regions = [tuple(float(v) for v in r.split(',')) for r in a.region]
        res = legend(b, text, cfg, items, regions)
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
