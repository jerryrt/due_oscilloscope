"""A LabelBoard from `pcbkit.board`: every box the placer reads comes from the arrays the reader fills (the F.Fab body, the footprint silk, the board silk, the text boxes),
through the accessors that call `board.require` first, so a board that was not read by `pcbkit.board.read_board` raises `FieldNotRead` instead of giving the placer an empty silk.

    lb = from_board.read(path, cfg, fixed_text_owner={'CH1 IN': 'J101'}, block_names={'POWER', ...})     cfg carries FRAME
    lb = from_board.from_board(b, ...)                                                                    b a BoardArrays from read_board

`fixed_text_owner` maps the text of a board text that is a part's function label to that part; `block_names` are the board texts that are block names. Both become fixed labels (obstacles that
stay), a block name measured by its ink box. A block-outline line is a board-level F.SilkS line: its segment is its box without the stroke along the line's own direction (an outline line
is axis-aligned), its box is kept as an obstacle."""
import numpy as np
from .. import board as _board
from . import _g as G
from .model import Part, LabelBoard

ADV, INK = 0.95, 1.2          # a block name's ink box, fractions of its text height (the labels' own DESIGNATOR_ADVANCE / DESIGNATOR_INK_H)


def read(path, cfg, fixed_text_owner=None, block_names=(), advance=ADV, ink_h=INK):
    return from_board(_board.read_board(path, cfg), fixed_text_owner, block_names, advance, ink_h)


def _box(r):
    return (float(r[0]), float(r[1]), float(r[2]), float(r[3]))


def from_board(b, fixed_text_owner=None, block_names=(), advance=ADV, ink_h=INK):
    """a part's body is the box of its F.Fab shapes (`fp_fab_*`; step 1c makes it shapes-only: F.Fab text is not printed and is not part of the part); a part with none is judged by its pads"""
    _board.require(b, 'r_hide', 't_ang')
    fab = _board.fab_boxes(b)
    fsfp, fsbox, fskind = _board.footprint_silk(b)
    gbox, gkind = _board.board_silk_graphics(b)
    tbox = _board.text_boxes(b)
    refs = [str(r) for r in b.fp_ref]
    pads = {i: [] for i in range(len(refs))}
    for j in range(len(b.p_fp)):
        pads[int(b.p_fp[j])].append((float(b.p_bx0[j]), float(b.p_by0[j]), float(b.p_bx1[j]), float(b.p_by1[j])))
    fsb = {i: [] for i in range(len(refs))}
    for k in range(len(fsfp)):
        fsb[int(fsfp[k])].append(_box(fsbox[k]))
    parts = {}
    for i, r in enumerate(refs):
        cour = None if np.isnan(b.fp_cx0[i]) else (float(b.fp_cx0[i]), float(b.fp_cy0[i]), float(b.fp_cx1[i]), float(b.fp_cy1[i]))
        body = None if np.isnan(fab[i, 0]) else _box(fab[i])
        sb = fsb[i]
        silk = (min(q[0] for q in sb), min(q[1] for q in sb), max(q[2] for q in sb), max(q[3] for q in sb)) if sb else None
        parts[r] = Part(r, float(b.fp_x[i]), float(b.fp_y[i]), cour, body, pads[i], float(b.fp_rot[i]), int(b.fp_side[i]) == 0, silk)
    silk_all = [q for i in range(len(refs)) for q in fsb[i]]
    vias = [(float(x - d / 2), float(y - d / 2), float(x + d / 2), float(y + d / 2)) for x, y, d in zip(b.v_x, b.v_y, b.v_dia)]
    outline_lines, outline_silk = [], []
    for k in range(len(gkind)):
        x0, y0, x1, y1 = _box(gbox[k])
        if gkind[k] == 'line':
            w = min(x1 - x0, y1 - y0)                                       # the stroke width of an axis-aligned line
            yc, xc = (y0 + y1) / 2, (x0 + x1) / 2
            outline_lines.append((x0 + w / 2, yc, x1 - w / 2, yc) if (x1 - x0) >= (y1 - y0) else (xc, y0 + w / 2, xc, y1 - w / 2))
            outline_silk.append((x0, y0, x1, y1))
        elif x1 - x0 > 0.4 and y1 - y0 > 0.4:
            w = 0.075
            outline_silk += [(x0, y0, x1, y0 + 2 * w), (x0, y1 - 2 * w, x1, y1), (x0, y0, x0 + 2 * w, y1), (x1 - 2 * w, y0, x1, y1)]
        else:
            outline_silk.append((x0, y0, x1, y1))
    fto, names = fixed_text_owner or {}, set(block_names)
    texts, fixed = [], {}
    for k, t in enumerate(b.t_text):
        t = str(t)
        bx = _box(tbox[k])
        if t in fto:
            fixed['fn_' + fto[t]] = bx
        elif t in names:
            cx, cy, hh = (bx[0] + bx[2]) / 2, (bx[1] + bx[3]) / 2, float(b.t_h[k])
            L2, W2 = len(t) * advance * hh / 2, ink_h * hh / 2                # a block name is measured by its ink box, as a designator is
            fixed['name_' + t] = (cx - L2, cy - W2, cx + L2, cy + W2) if round(float(b.t_ang[k])) % 180 == 0 else (cx - W2, cy - L2, cx + W2, cy + L2)
        else:
            texts.append(bx)
    labels = {}
    for j in range(len(b.r_fp)):
        vis = bool(b.r_on_silk[j]) and int(b.r_layer[j]) == 0 and not bool(b.r_hide[j])
        labels[refs[int(b.r_fp[j])]] = (float(b.r_x[j]), float(b.r_y[j]), float(b.r_ang[j]), vis)
    o = np.asarray(b.outline, float)
    edge = (float(o[:, 0].min()), float(o[:, 1].min()), float(o[:, 0].max()), float(o[:, 1].max())) if len(o) else None
    return LabelBoard(parts, vias, silk_all, outline_lines, outline_silk, texts, fixed, edge, labels)
