"""Silk-only designator placement against D30 (docs/afe.md): each top part's designator moves, nothing else does.

    python3 -m pcbtools.silkplace BOARD.kicad_pcb --config v1 [--margin 0.30] [--keep J101 ...] [--write OUT.kicad_pcb]

For every top part (except the ones the config fixes or --keep names) it looks for a place for the text, at 0 or 90 degrees, at the
config's text height, where
  * the text's box lies on no pad, via, courtyard (its own included), board text or another designator, and inside the board;
  * the nearest courtyard to the box is the part's own, by at least --margin (D30 asks 0.25; the default 0.30 leaves room for the
    text-extent estimate, which is the config's DESIGNATOR_ADVANCE x height per character, a little wider than the checker's);
and, of the places that do, takes the one with the smallest gap to its own courtyard, then the one nearest where the text was.
Parts are placed densest first, each against the places already taken. A part with no such place keeps its text and is LISTED: it
needs room (a spread block, D30 1a) or a place in a cluster key (D30 1b), and this tool never decides which.

Not seen by it: a footprint's own silk lines (they lie inside the courtyard, which is avoided) and the board-level silk lines
(block outlines), which are drawn after the designators are placed.

    place(b, cfg, margin=0.30, keep=()) -> (placed {ref: (x, y, angle)}, unplaced [ref])     pure numpy on BoardArrays, Due mm
"""
import argparse
import importlib
import sys

import numpy as np

STEP = 0.1
PAD_CLEAR = 0.1
VIA_CLEAR = 0.1
EDGE_CLEAR = 0.3
HARD_GAP = 0.3           # between two designators' boxes
GAP_MAX = 1.0            # the farthest from its own courtyard a text is looked for


def _fixed(cfg):
    return (set(getattr(cfg, 'BNC_REFS', ())) | set(getattr(cfg, 'BNC_Y', {})) | set(getattr(cfg, 'BNCS', {}))
            | set(getattr(cfg, 'DESIGNATOR_AT', {})) | set(getattr(cfg, 'ANCHORS', ())))


def _gaps(B, C):
    """(n, m) edge-to-edge distance of n boxes B and m boxes C, each (.., 4) x0 y0 x1 y1; 0 where they touch or overlap"""
    dx = np.maximum(np.maximum(C[None, :, 0] - B[:, None, 2], B[:, None, 0] - C[None, :, 2]), 0)
    dy = np.maximum(np.maximum(C[None, :, 1] - B[:, None, 3], B[:, None, 1] - C[None, :, 3]), 0)
    return np.hypot(dx, dy)


def _overlaps(B, C, m=0.0):
    """(n, m) bool: the boxes overlap with m to spare (strictly)"""
    return ~((B[:, None, 2] + m <= C[None, :, 0]) | (C[None, :, 2] + m <= B[:, None, 0])
             | (B[:, None, 3] + m <= C[None, :, 1]) | (C[None, :, 3] + m <= B[:, None, 1]))


def _size(ref, ang, h, cfg):
    l, w = len(ref) * getattr(cfg, 'DESIGNATOR_ADVANCE', 0.95) * h, getattr(cfg, 'DESIGNATOR_INK_H', 1.2) * h
    return (w, l) if ang == 90 else (l, w)


def _cands(c, ref, h, cfg):
    """candidate (cx, cy, ang) for a text around courtyard c = (x0, y0, x1, y1): on each side, sliding along it, GAP_MAX deep"""
    out = []
    for ang in (0, 90):
        w, hh = _size(ref, ang, h, cfg)
        gs = np.arange(0.0, GAP_MAX + 1e-9, STEP)
        xs = np.arange(c[0] - w + STEP, c[2] + w, STEP)
        ys = np.arange(c[1] - hh + STEP, c[3] + hh, STEP)
        for g in gs:
            for y in (c[3] + g + hh / 2, c[1] - g - hh / 2):
                out.append(np.column_stack([xs + w / 2 - w / 2, np.full(len(xs), y), np.full(len(xs), ang)]))
            for x in (c[2] + g + w / 2, c[0] - g - w / 2):
                out.append(np.column_stack([np.full(len(ys), x), ys, np.full(len(ys), ang)]))
    return np.round(np.vstack(out), 2)


def place(b, cfg, margin=0.30, keep=()):
    refs = list(b.fp_ref)
    top = [int(s) == 0 for s in b.fp_side]
    cour = {r: (b.fp_cx0[i], b.fp_cy0[i], b.fp_cx1[i], b.fp_cy1[i]) for i, r in enumerate(refs)
            if top[i] and not np.isnan(b.fp_cx0[i])}
    names = list(cour)
    CB = np.array([cour[r] for r in names])
    pads = np.column_stack([b.p_bx0, b.p_by0, b.p_bx1, b.p_by1])
    pads = np.vstack([pads - [PAD_CLEAR, PAD_CLEAR, -PAD_CLEAR, -PAD_CLEAR]])
    vias = np.column_stack([b.v_x - b.v_dia / 2, b.v_y - b.v_dia / 2, b.v_x + b.v_dia / 2, b.v_y + b.v_dia / 2]) \
        + [-VIA_CLEAR, -VIA_CLEAR, VIA_CLEAR, VIA_CLEAR]
    texts = []
    for t, x, y, h in zip(b.t_text, b.t_x, b.t_y, b.t_h):
        s = len(t) * getattr(cfg, 'DESIGNATOR_ADVANCE', 0.95) * h / 2              # the label's turn is not read: its square hull
        texts.append((x - s, y - s, x + s, y + s))
    texts = np.array(texts).reshape(-1, 4)
    ox, oy = b.outline[:, 0], b.outline[:, 1]
    edge = (ox.min() + EDGE_CLEAR, oy.min() + EDGE_CLEAR, ox.max() - EDGE_CLEAR, oy.max() - EDGE_CLEAR)
    cur = {}
    for j in range(len(b.r_fp)):
        if b.r_on_silk[j] and int(b.r_layer[j]) == 0 and top[int(b.r_fp[j])]:
            cur[refs[int(b.r_fp[j])]] = (float(b.r_x[j]), float(b.r_y[j]), float(b.r_ang[j]), float(b.r_h[j]))
    fixed = _fixed(cfg) | set(keep)
    todo = [r for r in names if r in cur and r not in fixed]
    taken = {}
    for r, (x, y, a, h) in cur.items():
        if r not in todo:
            w, hh = _size(r, int(round(a)) % 180, h, cfg)
            taken[r] = (x - w / 2, y - hh / 2, x + w / 2, y + hh / 2)
    # the densest parts first: fewest other courtyards within 1.5 mm of theirs are placed last
    near = lambda r: -int((_gaps(np.array([cour[r]]), CB)[0] < 1.5).sum())   # noqa: E731
    todo.sort(key=near)
    placed, unplaced = {}, []
    inner = CB + [0.02, 0.02, -0.02, -0.02]
    for r in todo:
        x0, y0, a0, h = cur[r]
        C = _cands(cour[r], r, h, cfg)
        sz = np.array([_size(r, int(a), h, cfg) for a in (0, 90)])
        w = sz[(C[:, 2] == 90).astype(int), 0]
        hh = sz[(C[:, 2] == 90).astype(int), 1]
        B = np.column_stack([C[:, 0] - w / 2, C[:, 1] - hh / 2, C[:, 0] + w / 2, C[:, 1] + hh / 2])
        ok = (B[:, 0] >= edge[0]) & (B[:, 1] >= edge[1]) & (B[:, 2] <= edge[2]) & (B[:, 3] <= edge[3])
        for obst in (pads, vias, inner, texts):
            if len(obst) and ok.any():
                ok &= ~_overlaps(B, obst).any(axis=1)
        if taken and ok.any():
            T = np.array(list(taken.values()))
            ok &= (_gaps(B, T) >= HARD_GAP).all(axis=1)
        if not ok.any():
            unplaced.append(r)
            continue
        i = names.index(r)
        G = _gaps(B[ok], CB)
        own = G[:, i].copy()
        G[:, i] = np.inf
        good = (G.min(axis=1) - own) >= margin
        if not good.any():
            unplaced.append(r)
            continue
        idx = np.flatnonzero(ok)[good]
        own = own[good]
        move = (C[idx, 0] - x0) ** 2 + (C[idx, 1] - y0) ** 2
        k = np.lexsort((move, np.round(own, 1)))[0]
        placed[r] = (float(C[idx[k], 0]), float(C[idx[k], 1]), int(C[idx[k], 2]))
        taken[r] = tuple(B[idx[k]])
    return placed, sorted(unplaced)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('board')
    ap.add_argument('--config', default='v1')
    ap.add_argument('--margin', type=float, default=0.30)
    ap.add_argument('--keep', nargs='*', default=[])
    ap.add_argument('--write', help='write the placed board here (editor.edit: pcbnew, run it in the image)')
    a = ap.parse_args(argv)
    from . import boardio
    cfg = importlib.import_module(f'pcbtools.boards.{a.config}')
    b = boardio.read_board(a.board)
    placed, unplaced = place(b, cfg, a.margin, a.keep)
    print(f'placed {len(placed)}, unplaced {len(unplaced)}: {" ".join(unplaced)}')
    if a.write:
        import shutil
        from .editor import edit
        if a.write != a.board:
            shutil.copy(a.board, a.write)
        with edit(a.write) as e:
            for r, (x, y, ang) in placed.items():
                e.set_ref_pose(r, x, y, ang)
        print('wrote', a.write)
    return 0


if __name__ == '__main__':
    sys.exit(main())
