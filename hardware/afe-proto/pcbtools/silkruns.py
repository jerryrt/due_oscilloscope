"""Runs: tight rows and columns of like parts, counted by one and labelled once, at their low end (LR-11).

    find_runs(b, cfg)                       -> (runs, grids)       the rows and columns, and the parts that sit in both (a grid: not a run)
    plan(b, cfg, text)                      -> Plan                numbers, label ends and label places for every run
    hidden_members(b)                       -> {ref}               the members of the labelled runs, as silkread reads them (the one statement of the rule)

A RUN is two or more parts of one kind (the designator's letters: R, C, BR ...), turned alike (courtyard aspect), in a straight line (their
centres within RUN_ALIGN of one line, along x for a row, along y for a column) and each neighbour's courtyard within RUN_GAP of the next. A part
in a row AND in a column belongs to a grid, which has no single line to count along; its parts are not part of any run and are reported.

A run is any such row or column and its numbers count by one along its line; an AXIAL run (parts end to end along their own axis) is labelled once and
the rest of this paragraph is its rule: its numbers count by one along its line; only its lowest-numbered part carries a label; that label lies on the run's own
line (centre within RUN_LABEL_ALIGN), just beyond the low end (within RUN_LABEL_GAP of the courtyard), turned as the parts are; the numbers
increase away from it, and the other members' designators are off the silk. Where the reading end (left for a row, top for a column) has no room
for the label the low end is the other one.

Numbers: within a kind and a hundred (a block), the runs and the parts in no run are ordered by the lowest old number of each and numbered
from the block's own set of numbers in that order, a run taking consecutive ones: parts in no run keep their numbers unless a run needs room.
Everything is Due mm, y up. Nothing here names a board: RUN_* are the config's, defaulted below.
"""
from __future__ import annotations

import dataclasses
import math
import re

import numpy as np

RUN_ALIGN = 0.3          # mm: centres of a run's parts within this of one line
RUN_GAP = 1.2            # mm: neighbouring courtyards within this
RUN_LABEL_ALIGN = 0.3    # mm: the label's centre within this of the run's line
RUN_LABEL_GAP = 1.5      # mm: the label's box within this of the low end's courtyard
LABEL_CLEAR = 0.1        # mm: and at least this far from it
PRE = re.compile(r'([A-Z]+)(\d+)$')


def _cfg(cfg, name, default):
    return getattr(cfg, name, default)


def kind_of(ref):
    return PRE.match(ref).group(1)


def number_of(ref):
    return int(PRE.match(ref).group(2))


def group_of(ref):
    """(letters, hundreds digit): the numbering group"""
    m = PRE.match(ref)
    return m.group(1), int(m.group(2)) // 100


@dataclasses.dataclass
class Run:
    kind: str                 # 'row' (along x) or 'col' (along y)
    refs: list                # along the line: a row left to right, a column top to bottom
    line: float               # y of a row, x of a column
    ang: int                  # the labels' turn: 0 for parts wider than high, 90 otherwise

    @property
    def axial(self):
        """parts end to end along their own axis (horizontal parts in a row, vertical parts in a column): the only runs that are labelled once, at their
        starter. Parts side by side (vertical in a row, horizontal in a column) count by one too but each carries its own designator"""
        return (self.kind == 'row') == (self.ang == 0)


@dataclasses.dataclass
class Plan:
    runs: list                # [Run] in the order of their groups
    end: dict                 # id(run) -> 'first' (reading end: left or top) or 'last'
    label: dict               # id(run) -> (x, y, ang) of the low end's label
    order: dict               # id(run) -> refs from the low end up
    new: dict                 # {old ref: new ref}
    grids: list               # [refs]
    blocked: list             # [(Run, why)]


def _parts(b, cfg):
    kinds = set(_cfg(cfg, 'RUN_KINDS', ('R', 'C', 'BR')))
    out = []
    for i, r in enumerate(b.fp_ref):
        m = PRE.match(r)
        if m and m.group(1) in kinds and int(b.fp_side[i]) == 0 and not np.isnan(b.fp_cx0[i]):
            out.append(i)
    return out


def _aspect(b, i):
    return 0 if (b.fp_cx1[i] - b.fp_cx0[i]) >= (b.fp_cy1[i] - b.fp_cy0[i]) else 90


def _gap(a, c):
    return math.hypot(max(c[0] - a[2], a[0] - c[2], 0.0), max(c[1] - a[3], a[1] - c[3], 0.0))


def find_runs(b, cfg):
    align, gap = _cfg(cfg, 'RUN_ALIGN', RUN_ALIGN), _cfg(cfg, 'RUN_GAP', RUN_GAP)
    parts = _parts(b, cfg)
    cour = {i: (b.fp_cx0[i], b.fp_cy0[i], b.fp_cx1[i], b.fp_cy1[i]) for i in parts}
    rel = {'row': {i: set() for i in parts}, 'col': {i: set() for i in parts}}
    for a in parts:
        for c in parts:
            if a >= c or kind_of(b.fp_ref[a]) != kind_of(b.fp_ref[c]) or _aspect(b, a) != _aspect(b, c):
                continue
            if _gap(cour[a], cour[c]) > gap:
                continue
            dx, dy = abs(b.fp_x[a] - b.fp_x[c]), abs(b.fp_y[a] - b.fp_y[c])
            if dy <= align and dx > dy:
                rel['row'][a].add(c)
                rel['row'][c].add(a)
            elif dx <= align and dy > dx:
                rel['col'][a].add(c)
                rel['col'][c].add(a)
    if _cfg(cfg, 'RUN_GRID_ROWS', False):
        # a grid (parts in both a row and a column) counts row by row: a part that has a row neighbour has no column neighbour, each row its own run
        for i in parts:
            if rel['row'][i]:
                for j in list(rel['col'][i]):
                    rel['col'][j].discard(i)
                rel['col'][i] = set()
    comps = []
    for kind in ('row', 'col'):
        seen = set()
        for i in parts:
            if i in seen or not rel[kind][i]:
                continue
            stack, comp = [i], []
            while stack:
                x = stack.pop()
                if x in seen:
                    continue
                seen.add(x)
                comp.append(x)
                stack += list(rel[kind][x])
            comps.append((kind, comp))
    members = {}
    for kind, comp in comps:
        for i in comp:
            members.setdefault(i, set()).add(kind)
    gridparts = {i for i, k in members.items() if len(k) > 1}
    runs, grids = [], []
    for kind, comp in comps:
        if any(i in gridparts for i in comp):
            grids.append(sorted(b.fp_ref[i] for i in comp))
            continue
        comp = sorted(comp, key=(lambda k: b.fp_x[k]) if kind == 'row' else (lambda k: -b.fp_y[k]))
        line = float(np.mean([b.fp_y[k] if kind == 'row' else b.fp_x[k] for k in comp]))
        runs.append(Run(kind, [b.fp_ref[k] for k in comp], line, _aspect(b, comp[0])))
    runs.sort(key=lambda r: (group_of(r.refs[0]), min(number_of(x) for x in r.refs)))
    grids = sorted({tuple(g) for g in grids})
    return runs, [list(g) for g in grids]


# ------------------------------------------------------------------------------------------------ obstacles and label places
def silk_boxes(text, cfg=None):
    """boxes (Due mm) of the board-level F.SilkS lines and words (footprint silk lies inside its courtyard)"""
    adv, ink = _cfg(cfg, 'DESIGNATOR_ADVANCE', 0.95), _cfg(cfg, 'DESIGNATOR_INK_H', 1.2)
    out = []
    for m in re.finditer(r'\n\t\((?:gr_line|gr_rect)\n\t\t\(start ([-\d.]+) ([-\d.]+)\)\n\t\t\(end ([-\d.]+) ([-\d.]+)\)(.*?)\n\t\t\(layer "F\.SilkS"\)', text, re.S):
        a, c, d, e = (float(m.group(i)) for i in (1, 2, 3, 4))
        w = re.search(r'\(width ([\d.]+)\)', m.group(5))
        w = float(w.group(1)) if w else 0.15
        out.append((min(a, d) - 50 - w / 2, 150 - max(c, e) - w / 2, max(a, d) - 50 + w / 2, 150 - min(c, e) + w / 2))
    for m in re.finditer(r'\n\t\(gr_text "([^"]*)"\n\t\t\(at ([-\d.]+) ([-\d.]+)( [-\d.]+)?\)\n\t\t\(layer "F\.SilkS"\)', text):
        L, H = len(m.group(1)) * adv, ink
        if int(round(float(m.group(4) or 0))) % 180 == 90:
            L, H = H, L
        x, y = float(m.group(2)) - 50, 150 - float(m.group(3))
        out.append((x - L / 2, y - H / 2, x + L / 2, y + H / 2))
    return out


def obstacles(b, cfg, silk=(), pad_clear=0.1, via_clear=0.1):
    """(M, 4) boxes the text lies on none of: pads, vias, every courtyard, board silk (a little grown)"""
    rows = [np.column_stack([b.p_bx0 - pad_clear, b.p_by0 - pad_clear, b.p_bx1 + pad_clear, b.p_by1 + pad_clear]),
            np.column_stack([b.v_x - b.v_dia / 2 - via_clear, b.v_y - b.v_dia / 2 - via_clear, b.v_x + b.v_dia / 2 + via_clear, b.v_y + b.v_dia / 2 + via_clear])]
    ok = ~np.isnan(b.fp_cx0)
    rows.append(np.column_stack([b.fp_cx0, b.fp_cy0, b.fp_cx1, b.fp_cy1])[ok] + [0.02, 0.02, -0.02, -0.02])
    if len(silk):
        rows.append(np.array(silk, float).reshape(-1, 4) + [-0.05, -0.05, 0.05, 0.05])
    return np.vstack(rows)


def label_size(ref, ang, cfg, h=1.0):
    L, W = len(ref) * _cfg(cfg, 'DESIGNATOR_ADVANCE', 0.95) * h, _cfg(cfg, 'DESIGNATOR_INK_H', 1.2) * h
    return (W, L) if ang == 90 else (L, W)


def label_spot(b, cfg, run, end, ref_len, obst, taken=(), edge=None, step=0.05):
    """(x, y, ang) of a label (a designator of ref_len characters) just beyond the run's `end` ('first' or 'last' of run.refs), or None:
    on the run's line within RUN_LABEL_ALIGN, its box LABEL_CLEAR to RUN_LABEL_GAP from the end part's courtyard, on no obstacle, clear of `taken`"""
    la, lg = _cfg(cfg, 'RUN_LABEL_ALIGN', RUN_LABEL_ALIGN), _cfg(cfg, 'RUN_LABEL_GAP', RUN_LABEL_GAP)
    i = b.ref_index(run.refs[0 if end == 'first' else -1])
    c = (b.fp_cx0[i], b.fp_cy0[i], b.fp_cx1[i], b.fp_cy1[i])
    line = float(b.fp_y[i] if run.kind == 'row' else b.fp_x[i])          # the starter's own centre line: the checker measures the label from it
    w, hh = label_size('X' * ref_len, run.ang, cfg)
    own_block = None
    if _cfg(cfg, 'LABEL_IN_BLOCK', False):
        own_block = _cfg(cfg, 'OUTLINE', {}).get(_cfg(cfg, 'BLOCK', {}).get(run.refs[0 if end == 'first' else -1]))
    best = None
    for g in np.arange(LABEL_CLEAR, lg + 1e-9, step):
        for off in np.arange(0.0, la + 1e-9, step):
            for sgn in ((1, -1) if off else (1,)):
                if run.kind == 'row':
                    x = c[0] - g - w / 2 if end == 'first' else c[2] + g + w / 2
                    y = line + sgn * off
                else:
                    y = c[3] + g + hh / 2 if end == 'first' else c[1] - g - hh / 2
                    x = line + sgn * off
                box = (x - w / 2, y - hh / 2, x + w / 2, y + hh / 2)
                if edge is not None and (box[0] < edge[0] or box[1] < edge[1] or box[2] > edge[2] or box[3] > edge[3]):
                    continue
                if own_block and not any(q[0] <= x <= q[2] and q[1] <= y <= q[3] for q in own_block):
                    continue
                if len(obst) and np.any(~((box[2] <= obst[:, 0]) | (obst[:, 2] <= box[0]) | (box[3] <= obst[:, 1]) | (obst[:, 3] <= box[1]))):
                    continue
                if any(not (box[2] + 0.3 <= t[0] or t[2] + 0.3 <= box[0] or box[3] + 0.3 <= t[1] or t[3] + 0.3 <= box[1]) for t in taken):
                    continue
                cost = (g, off)
                if best is None or cost < best[0]:
                    best = (cost, (round(x, 3), round(y, 3), run.ang))
        if best:
            return best[1]
    return None


# ------------------------------------------------------------------------------------------------ the plan
def plan(b, cfg, text=''):
    runs, grids = find_runs(b, cfg)
    obst = obstacles(b, cfg, silk_boxes(text, cfg))
    ox, oy = b.outline[:, 0], b.outline[:, 1]
    margin = _cfg(cfg, 'RUN_EDGE', 0.3)
    edge = (ox.min() + margin, oy.min() + margin, ox.max() - margin, oy.max() - margin)
    end, label, order, blocked, taken = {}, {}, {}, [], []
    for r in runs:
        n = len(r.refs[0])
        nums = [number_of(x) for x in r.refs]
        counting = counts_by_one(nums)
        if not r.axial:
            # no label to place: a run that already counts by one keeps its numbers, else they count up in the reading order (left to right, top to bottom)
            end[id(r)] = 'first'
            order[id(r)] = sorted(r.refs, key=number_of) if counting else list(r.refs)
            continue
        spot = None
        for e in ('first', 'last'):
            spot = label_spot(b, cfg, r, e, n, obst, taken, edge)
            if spot:
                break
        if spot is None:
            blocked.append((r, 'no room for a label at either end'))
            end[id(r)] = 'first'
            order[id(r)] = sorted(r.refs, key=number_of) if counting else list(r.refs)
            continue
        end[id(r)] = e
        label[id(r)] = spot
        order[id(r)] = list(r.refs) if e == 'first' else list(reversed(r.refs))
        w, hh = label_size('X' * n, spot[2], cfg)
        taken.append((spot[0] - w / 2, spot[1] - hh / 2, spot[0] + w / 2, spot[1] + hh / 2))
    if _cfg(cfg, 'RENUMBER_LABELLED_ONLY', False):
        # only a run that carries a starter label is renumbered (spec lead, AFE-1): the rest keep their numbers and fall back to beside-labels
        runs = [r for r in runs if id(r) in label]
    inrun = {x for r in runs for x in r.refs}
    groups = {}
    for ref in b.fp_ref:
        m = PRE.match(ref)
        if m and m.group(1) in set(_cfg(cfg, 'RUN_KINDS', ('R', 'C', 'BR'))):
            groups.setdefault(group_of(ref), []).append(ref)
    new = {}
    for g, refs in groups.items():
        nums = sorted(number_of(x) for x in refs)
        items = []
        for r in runs:
            if group_of(r.refs[0]) == g:
                items.append((min(number_of(x) for x in r.refs), 'run', r))
        for x in refs:
            if x not in inrun:
                items.append((number_of(x), 'one', x))
        items.sort(key=lambda t: (t[0], t[1]))
        k = 0
        for _, what, obj in items:
            if what == 'run':
                for x in order[id(obj)]:
                    new[x] = f'{g[0]}{nums[k]:03d}'
                    k += 1
            else:
                new[obj] = f'{g[0]}{nums[k]:03d}'
                k += 1
    new = {a: c for a, c in new.items() if a != c}
    return Plan(runs, end, label, order, new, grids, blocked)


def describe(b, cfg, p):
    lines = []
    for r in p.runs:
        lines.append(f'{r.kind} {r.refs} at {r.line:.2f} ang {r.ang}: label at {p.end[id(r)]} end {p.label.get(id(r))}; low to high {p.order[id(r)]}')
    for r, why in p.blocked:
        lines.append(f'BLOCKED {r.refs}: {why}')
    for g in p.grids:
        lines.append(f'GRID (no single line) {g}')
    lines.append('renames: ' + ', '.join(f'{a}->{c}' for a, c in sorted(p.new.items())))
    return '\n'.join(lines)


def main(argv=None):
    import argparse
    import importlib
    ap = argparse.ArgumentParser(prog='python3 -m pcbtools.silkruns', description=__doc__.split('\n')[0])
    ap.add_argument('board')
    ap.add_argument('--config', default='v2_layout')
    ap.add_argument('--write', help='write the renamed and run-labelled board here (the text splice: renames, schematic paths, run labels, hidden members)')
    ap.add_argument('--no-labels', action='store_true', help='with --write: only the renaming (and the schematic paths), no run labels')
    ap.add_argument('--map-json', help='write the rename map {old: new} here')
    a = ap.parse_args(argv)
    from . import boardio
    cfg = importlib.import_module(f'pcbtools.boards.{a.config}')
    with open(a.board) as fh:
        text = fh.read()
    b = boardio.read_board(a.board)
    p = plan(b, cfg, text)
    print(describe(b, cfg, p))
    if a.map_json:
        import json
        with open(a.map_json, 'w') as fh:
            json.dump(p.new, fh, indent=1, sort_keys=True)
    if a.write:
        from .schematic import make_uid
        ns = cfg.SCH_NS
        out = rename(text, p.new, lambda ref: make_uid(ns, 'sym', ref, 1))
        placed, hidden = {}, []
        if not a.no_labels:
            out, placed, hidden = label_runs(out, p)
        with open(a.write, 'w') as fh:
            fh.write(out)
        print(f'{len(p.new)} renamed, {len(placed)} run labels, {len(hidden)} designators off the silk')
    return 0


# ------------------------------------------------------------------------------------------------ writing it into a board text
def _footprint_spans(text):
    for m in re.finditer(r'\n\t\(footprint "[^"]*"\n', text):
        end = text.find('\n\t(footprint ', m.end())
        yield m.start(), (len(text) if end < 0 else end)


def rename(text, mapping, sym_uid):
    """the board text with every designator of `mapping` renamed (whole words, one pass), and each renamed footprint's schematic path pointing at the
    symbol its new name has (sym_uid(ref) -> the uuid string of the schematic symbol of `ref`)"""
    from .renumber import rewrite
    out, last = [], 0
    for s, e in _footprint_spans(text):
        blk = text[s:e]
        m = re.search(r'\(property "Reference" "([^"]*)"', blk)
        out.append(text[last:s])
        if m and m.group(1) in mapping:
            blk = re.sub(r'(\(path "/[0-9a-f-]+/)[0-9a-f-]+("\))', lambda q: q.group(1) + sym_uid(mapping[m.group(1)]) + q.group(2), blk, count=1)
        out.append(blk)
        last = e
    out.append(text[last:])
    return rewrite(''.join(out), mapping)


def hide(text, refs):
    """the Reference field of each part in `refs` moved from F.SilkS to F.Fab (it stays in the file; the silk no longer carries it)"""
    for ref in refs:
        for s, e in _footprint_spans(text):
            blk = text[s:e]
            if re.search(r'\(property "Reference" "%s"' % re.escape(ref), blk):
                pat = re.compile(r'(\(property "Reference" "%s"\n\t\t\t\(at [^)]*\)\n\t\t\t\(layer ")F\.SilkS(")' % re.escape(ref))
                text = text[:s] + pat.sub(r'\1F.Fab\2', blk, count=1) + text[e:]
                break
    return text


def show(text, refs):
    """the inverse of hide: the Reference field of each part in `refs` back from F.Fab to F.SilkS (its place is where it was left)"""
    for ref in refs:
        for s, e in _footprint_spans(text):
            blk = text[s:e]
            if re.search(r'\(property "Reference" "%s"' % re.escape(ref), blk):
                pat = re.compile(r'(\(property "Reference" "%s"\n\t\t\t\(at [^)]*\)\n\t\t\t\(layer ")F\.Fab(")' % re.escape(ref))
                text = text[:s] + pat.sub(r'\1F.SilkS\2', blk, count=1) + text[e:]
                break
    return text


def label_runs(text, p):
    """run labels: the lowest-numbered part of each run (its name AFTER the renaming `p.new`) gets the planned place and angle, the rest of the run is
    taken off the silk. -> (new text, {ref: (x, y, ang)}, [hidden refs])"""
    from . import silkapply
    new = lambda x: p.new.get(x, x)      # noqa: E731
    placed, hidden = {}, []
    for r in p.runs:
        if id(r) not in p.label:
            continue
        low, *rest = [new(x) for x in p.order[id(r)]]
        placed[low] = p.label[id(r)]
        hidden += rest
    text, _ = silkapply.apply_moves(text, None, placed)
    return hide(text, hidden), placed, hidden



# ------------------------------------------------------------------------------------------------ the check
def _visible(b):
    """{ref: (x, y, ang, h)} of the designators on the top silk"""
    out = {}
    for k in range(len(b.r_fp)):
        if b.r_on_silk[k] and int(b.r_layer[k]) == 0:
            out[b.fp_ref[int(b.r_fp[k])]] = (float(b.r_x[k]), float(b.r_y[k]), float(b.r_ang[k]), float(b.r_h[k]))
    return out


def counts_by_one(nums):
    s = sorted(nums)
    return s == list(range(s[0], s[0] + len(s))) and (list(nums) == s or list(nums) == s[::-1])


def hidden_members(b, cfg=None):
    """{ref} of the parts whose designator may be off the top silk: the members of the board's labelled runs, by the checker's own reading
    (silkread.runs), the BNCs (designator on the bottom silk, function label on top) and the parts the config leaves to the BOM (SILK_TO_BOM)"""
    from . import silkread
    return {x for members in silkread.runs(b).values() for x in members} | set(getattr(cfg, 'BNC_LABELS', {})) | set(getattr(cfg, 'SILK_TO_BOM', {}))


if __name__ == '__main__':
    raise SystemExit(main())
