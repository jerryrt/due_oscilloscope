"""D30 (docs/afe.md): every part can be found from its designator, because every designator sits in one place against it.

    findings(b, bnc_labels=None, edge_headers=(), silk=(), east_end=(), beside=())  -> [str]   the reasons it cannot (empty = it can)
    read_silk(txt)                                           -> [shape] the board-level F.SilkS lines and rectangles

The owner's convention (2026-11-15), on the top side (the board has no bottom parts):

1. Above its part. Every top part's designator is visible on F.SilkS, horizontal (0 degrees, reading left to right,
   whatever way the part is turned), centred over the part (its centre within ABOVE_X of the courtyard's centre in x),
   and just above it (from ABOVE_GAP_MIN to ABOVE_GAP_MAX between the courtyard's top and the text's bottom).
   A mounting hole (MH followed by digits) is not an assembled part and needs no designator.
2. Edge headers (`edge_headers`, the Due's socket rows; owner, 2026-11-15). A header lying along x carries its designator
   horizontal, centred along its length, on its inboard side: just below it when the header is in the upper half of the
   board, just above it in the lower half (the halves split at the centre of the board outline, or of the parts'
   courtyards when the arrays carry no outline). One lying along y carries it horizontal just above its top end, centred
   over it. Same gaps as rule 1.
2a. Beside the pin-free end (`east_end`, named parts only; owner's order of 2026-11-16, electrical rules before labels).
   An IC whose pin row faces parts the electrical rules tie to its pins, so that no label above it leaves them a legal
   place, carries its designator horizontal just east of its courtyard instead: from touching to ABOVE_GAP_MAX between
   the courtyard's east edge and the text's west edge, centred on the courtyard in y to ABOVE_X. The board names each
   such part and D30 records why; nothing else may use it.
2b. Beside (`beside`, named parts only, same order). A part that an electrical rule ties to an IC's pins so closely that
   its label above would lie on that IC's courtyard carries its designator horizontal just east or just west of it
   instead, centred on it in y to ABOVE_X, with rule 1's gaps measured from the courtyard's side. Named by the board,
   recorded in D30.
3. Legible. No designator lies on any courtyard (its own included), pad, via drill or board-level silk line or rectangle
   (`silk`, from read_silk: the block outlines and the S/N box), and two designators are at least LABEL_GAP apart, box to
   box, so that two never read as one.
4. BNCs (`bnc_labels`, {ref: function label}). Each carries its function label on the top silk, clear of every courtyard,
   and on no `silk` line, and its designator on the bottom silk beside its pins (mirrored there by the layout; this module does not read
   mirroring), none on top, each at one offset in its own frame across all of them, to BNC_TOL. A bottom designator
   counts as shown when it is on B.SilkS: the board arrays carry no visibility for the bottom.

Text extents are estimated, not read: a stroke-font character is CHAR_ADV of its width wide *(check: 0.9 matches the
1.0 mm designators in the AFE-2 render to within a pixel at 13.5 px/mm; other fonts or sizes are unmeasured)*.
Everything is in Due mm, y up (boardio's frame), so "above" is larger y.
"""
import re

import numpy as np

from pcbtools import boardio

ABOVE_X = 0.3          # mm: label centre to courtyard centre, across
ABOVE_GAP_MIN = 0.0    # mm: courtyard top to text bottom (touching the courtyard line is allowed, overlapping is not)
ABOVE_GAP_MAX = 0.6    # mm
LABEL_GAP = 0.5        # mm
BNC_TOL = 0.05         # mm
VIA_CLEAR = 0.1        # mm: text box to a via's drill edge
CHAR_ADV = 0.9         # see the module text


def _box(x0, y0, x1, y1):
    return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


def _gap(a, c):
    dx = max(c[0] - a[2], 0.0, a[0] - c[2])
    dy = max(c[1] - a[3], 0.0, a[1] - c[3])
    return float(np.hypot(dx, dy))


def _overlap(a, c):
    return a[0] < c[2] and c[0] < a[2] and a[1] < c[3] and c[1] < a[3]


def text_box(s, x, y, w, h, ang=0.0):
    """the box of a centred one-line text"""
    tw = len(s) * CHAR_ADV * w
    if abs((ang % 180.0) - 90.0) < 1.0:
        tw, h = h, tw
    return (x - tw / 2, y - h / 2, x + tw / 2, y + h / 2)


def read_silk(txt):
    """the board-level F.SilkS graphics of a .kicad_pcb text, in Due mm: ('seg', x0, y0, x1, y1, width) for a line or an
    unfilled rectangle's edge, ('box', x0, y0, x1, y1) for a filled rectangle"""
    out = []
    for m in re.finditer(r'\n\t\((gr_line|gr_rect)(.*?)\n\t\)', txt, re.S):
        body = m.group(2)
        if '(layer "F.SilkS")' not in body:
            continue
        s = re.search(r'\(start ([-\d.]+) ([-\d.]+)\)', body)
        e = re.search(r'\(end ([-\d.]+) ([-\d.]+)\)', body)
        w = re.search(r'\(width ([-\d.]+)\)', body)
        w = float(w.group(1)) if w else 0.0
        x0, y0 = boardio.to_due(float(s.group(1)), float(s.group(2)))
        x1, y1 = boardio.to_due(float(e.group(1)), float(e.group(2)))
        if m.group(1) == 'gr_line':
            out.append(('seg', x0, y0, x1, y1, w))
        elif '(fill yes)' in body:
            out.append(('box', *_box(x0, y0, x1, y1)))
        else:
            for a, c in (((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))):
                out.append(('seg', *a, *c, w))
    return out


def _on_shape(box, shape):
    """does a text box touch a silk shape (a segment counts with its stroke width)"""
    if shape[0] == 'box':
        return _overlap(box, shape[1:])
    _, x0, y0, x1, y1, w = shape
    bx0, by0, bx1, by1 = box[0] - w / 2, box[1] - w / 2, box[2] + w / 2, box[3] + w / 2
    t0, t1, dx, dy = 0.0, 1.0, x1 - x0, y1 - y0           # Liang-Barsky clip of the segment to the grown box
    for p, q in ((-dx, x0 - bx0), (dx, bx1 - x0), (-dy, y0 - by0), (dy, by1 - y0)):
        if p == 0:
            if q <= 0:
                return False
        else:
            r = q / p
            if p < 0:
                t0 = max(t0, r)
            else:
                t1 = min(t1, r)
            if t0 >= t1:
                return False
    return True


def findings(b, bnc_labels=None, edge_headers=(), silk=(), east_end=(), beside=()):
    bnc_labels = dict(bnc_labels or {})
    east_end = set(east_end)
    beside = set(beside)
    edge_headers = set(edge_headers)
    refs = list(b.fp_ref)
    row = {int(k): i for i, k in enumerate(b.fp_idx)}
    top = [int(s) == 0 for s in b.fp_side]
    cour = [_box(*c) if not np.isnan(c).any() else None for c in zip(b.fp_cx0, b.fp_cy0, b.fp_cx1, b.fp_cy1)]
    parts = [i for i in range(len(refs)) if top[i] and cour[i] is not None]
    pads = [(x0, y0, x1, y1) for x0, y0, x1, y1 in zip(b.p_bx0, b.p_by0, b.p_bx1, b.p_by1)]
    vias = [(x - d / 2 - VIA_CLEAR, y - d / 2 - VIA_CLEAR, x + d / 2 + VIA_CLEAR, y + d / 2 + VIA_CLEAR)
            for x, y, d in zip(b.v_x, b.v_y, b.v_drill)]
    if len(b.outline):
        mid_y = (float(np.min(b.outline[:, 1])) + float(np.max(b.outline[:, 1]))) / 2
    else:
        cs = [cour[i] for i in parts]
        mid_y = (min(c[1] for c in cs) + max(c[3] for c in cs)) / 2 if cs else 0.0
    shown = {}                                   # ref -> (box, angle) of its visible top designator
    for j in range(len(b.r_fp)):
        i = row[int(b.r_fp[j])]
        if top[i] and b.r_on_silk[j] and int(b.r_layer[j]) == boardio.R_LAYERS['F.SilkS']:
            shown[refs[i]] = (text_box(refs[i], b.r_x[j], b.r_y[j], b.r_w[j], b.r_h[j], b.r_ang[j]), float(b.r_ang[j]))
    bad = []

    for i in parts:
        r = refs[i]
        if r in bnc_labels or re.fullmatch(r'MH\d+', r):
            continue
        if r not in shown:
            bad.append(f'{r}: no designator on the top silk')
            continue
        box, ang = shown[r]
        c = cour[i]
        if min(ang % 360.0, 360.0 - ang % 360.0) > 0.5:
            bad.append(f'{r}: designator at {ang:g} degrees, not horizontal')
        across = abs((box[0] + box[2]) / 2 - (c[0] + c[2]) / 2)
        if r in east_end:                                              # rule 2a
            across = abs((box[1] + box[3]) / 2 - (c[1] + c[3]) / 2)
            gap = box[0] - c[2]
            where = 'beside its east end'
        elif r in beside:                                              # rule 2b: whichever side the text is on
            across = abs((box[1] + box[3]) / 2 - (c[1] + c[3]) / 2)
            gap = box[0] - c[2] if (box[0] + box[2]) / 2 > (c[0] + c[2]) / 2 else c[0] - box[2]
            where = 'beside it'
        elif r in edge_headers and (c[2] - c[0]) >= (c[3] - c[1]) and (c[1] + c[3]) / 2 > mid_y:   # along x, upper half
            gap = c[1] - box[3]
            where = 'below it, on its inboard side'
        elif r in edge_headers and (c[2] - c[0]) >= (c[3] - c[1]):                               # along x, lower half
            gap = box[1] - c[3]
            where = 'above it, on its inboard side'
        else:                                                          # every other part, and a header along y: above
            gap = box[1] - c[3]
            where = 'above it'
        if across > ABOVE_X or not (ABOVE_GAP_MIN <= gap <= ABOVE_GAP_MAX):
            bad.append(f'{r}: designator not centred {where} (off centre {across:.2f} mm, gap {gap:.2f} mm)')
        hits = sorted({refs[k] for k in parts if _overlap(box, cour[k])})
        if hits:
            bad.append(f'{r}: designator lies on the courtyard of {", ".join(hits)}')
        if any(_overlap(box, p) for p in pads):
            bad.append(f'{r}: designator lies on a pad')
        if any(_overlap(box, v) for v in vias):
            bad.append(f'{r}: designator lies on a via')
        if any(_on_shape(box, sh) for sh in silk):
            bad.append(f'{r}: designator lies on a silk line')

    L = sorted((r, v[0]) for r, v in shown.items())
    for a in range(len(L)):
        for c in range(a + 1, len(L)):
            g = _gap(L[a][1], L[c][1])
            if g < LABEL_GAP:
                bad.append(f"{L[a][0]}: designator {g:.2f} mm from {L[c][0]}'s, under {LABEL_GAP}")

    frames = {}
    for r, label in bnc_labels.items():
        if r not in refs:
            bad.append(f'{r}: no such connector')
            continue
        i = refs.index(r)
        tops = [j for j in range(len(b.r_fp)) if row[int(b.r_fp[j])] == i and b.r_on_silk[j]]
        bot = [j for j in range(len(b.r_fp)) if row[int(b.r_fp[j])] == i and int(b.r_layer[j]) == boardio.R_LAYERS['B.SilkS']]
        ls = [n for n, t in enumerate(b.t_text) if t == label]
        if len(ls) != 1 or len(bot) != 1 or tops:
            bad.append(f'{r}: {len(ls)} "{label}" labels on top, {len(bot)} designators on the bottom and {len(tops)} on top; '
                       f'wanted one label, one bottom designator, none on top')
            continue
        lb = text_box(label, b.t_x[ls[0]], b.t_y[ls[0]], b.t_h[ls[0]], b.t_h[ls[0]],
                      90.0 if abs((b.fp_rot[i] % 180.0) - 90.0) < 1.0 else 0.0)
        hidden = sorted({refs[k] for k in parts if _overlap(lb, cour[k])})
        if hidden:
            bad.append(f'{r}: "{label}" lies on the courtyard of {", ".join(hidden)}, whose body hides it')
        if any(_on_shape(lb, sh) for sh in silk):
            bad.append(f'{r}: "{label}" lies on a silk line')
        a = np.radians(b.fp_rot[i])
        R = np.array([[np.cos(a), np.sin(a)], [-np.sin(a), np.cos(a)]])     # board -> the part's own frame (y up, ccw angles)
        o = np.array([b.fp_x[i], b.fp_y[i]])
        frames[r] = (label, R @ (np.array([b.t_x[ls[0]], b.t_y[ls[0]]]) - o), R @ (np.array([b.r_x[bot[0]], b.r_y[bot[0]]]) - o))
    if frames:
        r0, (_, lab0, des0) = next(iter(frames.items()))
        for r, (label, lab, des) in list(frames.items())[1:]:
            if np.abs(lab - lab0).max() > BNC_TOL:
                bad.append(f'{r}: "{label}" at ({lab[0]:.2f}, {lab[1]:.2f}) in its frame, {r0} has its label at ({lab0[0]:.2f}, {lab0[1]:.2f})')
            if np.abs(des - des0).max() > BNC_TOL:
                bad.append(f'{r}: bottom designator at ({des[0]:.2f}, {des[1]:.2f}) in its frame, {r0} has it at ({des0[0]:.2f}, {des0[1]:.2f})')
    return bad
