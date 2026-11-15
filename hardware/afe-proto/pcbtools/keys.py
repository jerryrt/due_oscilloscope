"""Cluster keys (D30 1b): where a cluster of parts is held tight on purpose, its designators come off the parts and one outlined key in the
nearest free area carries them in the same rows and columns as the parts. Board-agnostic: the board's own config says which clusters
(`KEYS`) and the thresholds; nothing here names a board, a part or a net. No arrow or leader line is ever drawn.

    plan(b, text, cfg, name)   -> Plan | NoFit   what the key would be and where, from the board arrays (pcbnew read, in the image) and its text
    apply(text, plan)          -> new text       the board text with the key added and the cluster's own designators taken off the silk
    python3 -m pcbtools.keys BOARD.kicad_pcb --config v2_layout NAME [--write OUT]       (in the PCB image)

The edit is a text splice: each keyed part's Reference field moves from F.SilkS to F.Fab (it stays in the file, for the assembly drawing, and is
no longer on the silkscreen), and the key is one unfilled gr_rect on F.SilkS plus one F.SilkS text per designator, at 0 degrees. Nothing
else changes, the project file is not touched, and applying twice changes nothing. A key that finds no free area adjoining its cluster is
NoFit and edits nothing: the nearest free place for it is reported instead of used.

Config (`KEYS = {name: dict(parts=(refs...))}` and the thresholds). `parts` is the cluster's RESIDUE: the parts the silk-only placer could not
give a designator that meets D30 beside the part; it may be any list (`plan(..., parts=[...])` takes one too, e.g. the placer's output), and the
rows and columns are those of the listed parts only. The cluster's extent, which the key must adjoin, is the union of their courtyards:
  KEY_TEXT_H            text height, mm (>= the board house's silk minimum)
  KEY_ADVANCE, KEY_INK_H  the stroke font's advance per character and the ink height, as fractions of KEY_TEXT_H (as DESIGNATOR_ADVANCE / DESIGNATOR_INK_H)
  KEY_COL_GAP           clear space between two designators in a row, mm
  KEY_ROW_PITCH         centre to centre of two rows, mm
  KEY_MARGIN            clear space inside the box all round, mm
  KEY_ROW_TOL           parts whose y is within this of each other are one row; likewise x for a column, mm
  KEY_CLEAR             free area is measured with pads, vias, silk and courtyards grown by this, mm
  KEY_ADJOIN_MAX        the key box is at most this far from its cluster's extent (the union of the parts' courtyards), mm
  KEY_STROKE            line width of the box, mm
"""
from __future__ import annotations

import dataclasses
import re
import sys

import numpy as np

RES = 0.1                    # occupancy grid, mm


@dataclasses.dataclass
class Plan:
    name: str
    box: tuple               # (x0, y0, x1, y1) Due mm
    texts: dict              # {ref: (x, y)} centre of each designator, Due mm
    rows: list               # [[ref, ...]] top to bottom, each left to right
    gap: float               # key box to the cluster's extent, mm


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


def cluster_1d(values, tol):
    """indices grouped into runs: sorted values start a new group where the step to the previous one exceeds tol -> [[index, ...]] in value order"""
    order = sorted(range(len(values)), key=lambda i: values[i])
    groups = [[order[0]]]
    for i in order[1:]:
        if values[i] - values[groups[-1][-1]] > tol:
            groups.append([])
        groups[-1].append(i)
    return groups


def layout(refs, xy, cfg):
    """(rows, ncols, col_of): rows top (largest y) to bottom, each ref list left to right; col_of {ref: column index}"""
    ys = [xy[r][1] for r in refs]
    xs = [xy[r][0] for r in refs]
    colgroups = cluster_1d(xs, cfg.KEY_COL_TOL if hasattr(cfg, 'KEY_COL_TOL') else cfg.KEY_ROW_TOL)
    col_of = {refs[i]: c for c, g in enumerate(colgroups) for i in g}
    rowgroups = cluster_1d(ys, cfg.KEY_ROW_TOL)[::-1]
    rows = [sorted((refs[i] for i in g), key=lambda r: xy[r][0]) for g in rowgroups]
    return rows, len(colgroups), col_of


def size(refs, ncols, nrows, cfg):
    """(width, height) of the key box: the longest designator sets every column's pitch, so the columns line up"""
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


def plan(b, text, cfg, name, parts=None):
    """`parts` (an arbitrary residue list) overrides the config's KEYS[name]['parts']"""
    refs = list(cfg.KEYS[name]['parts'] if parts is None else parts)
    idx = {r: b.ref_index(r) for r in refs}
    xy = {r: (float(b.fp_x[i]), float(b.fp_y[i])) for r, i in idx.items()}
    ext = (min(b.fp_cx0[i] for i in idx.values()), min(b.fp_cy0[i] for i in idx.values()),
           max(b.fp_cx1[i] for i in idx.values()), max(b.fp_cy1[i] for i in idx.values()))
    rows, ncols, col_of = layout(refs, xy, cfg)
    W, H = size(refs, ncols, len(rows), cfg)
    g = board_grid(b, text, cfg, keyed=set(refs))
    x, y = g.free_positions(W, H)
    gaps = _gap(x, y, W, H, ext) if len(x) else np.array([])
    ok = np.flatnonzero(gaps <= cfg.KEY_ADJOIN_MAX)
    if not len(ok):
        j = int(gaps.argmin()) if len(gaps) else None
        big = (0.0, 0.0)
        for w in np.arange(2, 30, 0.5):
            for h in np.arange(2, 20, 0.5):
                xx, yy = g.free_positions(w, h)
                if len(xx) and (_gap(xx, yy, w, h, ext) <= cfg.KEY_ADJOIN_MAX).any() and w * h > big[0] * big[1]:
                    big = (float(w), float(h))
        return NoFit(name, (W, H), None if j is None else float(gaps[j]), None if j is None else (round(float(x[j]), 1), round(float(y[j]), 1)), big)
    j = ok[int(gaps[ok].argmin())]
    bx, by = round(float(x[j]), 1), round(float(y[j]), 1)
    h = cfg.KEY_TEXT_H
    longest = max(len(r) for r in refs) * cfg.KEY_ADVANCE * h
    texts = {}
    for ri, row in enumerate(rows):
        for r in row:
            cx = bx + cfg.KEY_MARGIN + col_of[r] * (longest + cfg.KEY_COL_GAP) + len(r) * cfg.KEY_ADVANCE * h / 2
            cy = by + H - cfg.KEY_MARGIN - cfg.KEY_INK_H * h / 2 - ri * cfg.KEY_ROW_PITCH
            texts[r] = (round(cx, 3), round(cy, 3))
    return Plan(name, (bx, by, round(bx + W, 3), round(by + H, 3)), texts, rows, float(gaps[j]))


def silk_boxes(text, cfg):
    """boxes (Due mm) of the board-level F.SilkS lines and words; footprint silk lies inside its courtyard, which is counted already"""
    out = []
    for m in re.finditer(r'\n\t\(gr_line\n\t\t\(start ([-\d.]+) ([-\d.]+)\)\n\t\t\(end ([-\d.]+) ([-\d.]+)\)(.*?)\n\t\t\(layer "F\.SilkS"\)', text, re.S):
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


def apply(text, p, cfg):
    """the board text with the key of plan `p` in it and its parts' Reference fields on F.Fab; idempotent"""
    for ref in p.texts:
        s, e = _fp_span(text, ref)
        blk = text[s:e]
        pat = re.compile(r'(\(property "Reference" "%s"\n\t\t\t\(at [^)]*\)\n\t\t\t\(layer ")F\.SilkS(")' % re.escape(ref))
        if pat.search(blk):
            text = text[:s] + pat.sub(r'\1F.Fab\2', blk, count=1) + text[e:]
    x0, y0, x1, y1 = p.box
    items = []
    stroke = cfg.KEY_STROKE
    sa, sb, sc, sd = x0 + 50.0, 150.0 - y1, x1 + 50.0, 150.0 - y0                   # sheet mm: top-left and bottom-right corners
    items.append((('gr_rect', sa, sb, sc, sd), f'\t(gr_rect\n\t\t(start {_fmt(sa)} {_fmt(sb)})\n\t\t(end {_fmt(sc)} {_fmt(sd)})\n\t\t(stroke\n\t\t\t(width {stroke:g})\n'
                  f'\t\t\t(type default)\n\t\t)\n\t\t(fill no)\n\t\t(layer "F.SilkS")\n\t\t(uuid "{{u}}")\n\t)\n'))
    for ref, (x, y) in sorted(p.texts.items()):
        sx, sy = x + 50.0, 150.0 - y
        items.append((('gr_text', ref, sx, sy), f'\t(gr_text "{ref}"\n\t\t(at {_fmt(sx)} {_fmt(sy)} 0)\n\t\t(layer "F.SilkS")\n\t\t(uuid "{{u}}")\n\t\t(effects\n\t\t\t(font\n'
                      f'\t\t\t\t(size {cfg.KEY_TEXT_H:g} {cfg.KEY_TEXT_H:g})\n\t\t\t\t(thickness {cfg.KEY_STROKE:g})\n\t\t\t)\n\t\t)\n\t)\n'))
    new = ''
    import uuid
    for key, body in items:
        if key[0] == 'gr_text':
            have = re.search(r'\n\t\(gr_text "%s"\n\t\t\(at %s %s 0\)' % (re.escape(key[1]), re.escape(_fmt(key[2])), re.escape(_fmt(key[3]))), text)
        else:
            a, b_, c, d = key[1:]
            have = f'\n\t(gr_rect\n\t\t(start {_fmt(a)} {_fmt(b_)})\n\t\t(end {_fmt(c)} {_fmt(d)})' in text
        if not have:
            new += body.replace('{u}', str(uuid.uuid5(uuid.NAMESPACE_URL, f'keys {p.name} {key}')))
    if new:
        i = text.rstrip().rfind(')')
        text = text[:i] + new + text[i:]
    return text


def main(argv=None):
    import argparse
    import importlib
    ap = argparse.ArgumentParser(prog='python3 -m pcbtools.keys', description=__doc__.split('\n\n')[0])
    ap.add_argument('board')
    ap.add_argument('name', help='the key, a name in the config\'s KEYS')
    ap.add_argument('--parts', help='comma separated residue list (e.g. the placer\'s output), instead of the config\'s KEYS[name][\'parts\']')
    ap.add_argument('--config', default='v2_layout')
    ap.add_argument('--write', help='write the edited board here (default: report only)')
    a = ap.parse_args(argv)
    from . import boardio
    cfg = importlib.import_module(f'pcbtools.boards.{a.config}')
    with open(a.board) as fh:
        text = fh.read()
    p = plan(boardio.read_board(a.board), text, cfg, a.name, a.parts.split(',') if a.parts else None)
    if isinstance(p, NoFit):
        print(p)
        return 1
    print(f'key {p.name}: box {p.box}, {sum(len(r) for r in p.rows)} designators in {len(p.rows)} rows, {p.gap:.2f} mm from its cluster')
    for row in p.rows:
        print('  ', ' '.join(row))
    if a.write:
        with open(a.write, 'w') as fh:
            fh.write(apply(text, p, cfg))
    return 0


if __name__ == '__main__':
    sys.exit(main())
