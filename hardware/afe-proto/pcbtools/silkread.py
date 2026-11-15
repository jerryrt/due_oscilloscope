"""D30 (docs/afe.md): can a technician with only the board find a part from its designator?

    findings(b, keys, bnc_labels, exempt={})  -> [str]     the reasons it cannot (empty = it can)
    read_keys(txt)                              -> [Key]     the cluster keys drawn in a .kicad_pcb text

Three properties, each on the top side (the board has no bottom parts):

1. Own designator. A top part's visible silk designator is beside its own part: the gap from the text's box to its own courtyard
   is at least OWN_MARGIN smaller than the gap to any other top courtyard, the box covers no pad and no other part's courtyard,
   and the text reads at 0 or 90 degrees.
2. Or a cluster key. A part whose designator is hidden is named exactly once, in exactly one key. A key is an unfilled
   rectangle on F.SilkS holding at least two board texts, every one of them a designator. Its texts keep their parts' order
   (a pair of parts more than ORDER_MIN apart along x or y has its two texts in the same order along that axis), it lies on no
   top courtyard or pad, and it is no further than KEY_GAP_MAX from the box around its parts' courtyards.
3. One BNC frame. Each connector named in `bnc_labels` ({ref: function label}) carries its designator and its function label
   at the same offset in its own frame as the first one does, to BNC_TOL.

A part may be exempted by name, with its reason (`exempt`); the reason is the board's gate-3 notes' to give, not this module's.

Text extents are estimated, not read: a stroke-font character is CHAR_ADV of its width wide *(check: 0.9 matches the
1.0 mm designators in the AFE-2 render to within a pixel at 13.5 px/mm; other fonts or sizes are unmeasured)*.
Everything is in Due mm, y up (boardio's frame).
"""
import dataclasses
import re

import numpy as np

from pcbtools import boardio

OWN_MARGIN = 0.25      # mm, D30
BNC_TOL = 0.05         # mm, D30
KEY_GAP_MAX = 2.0      # mm: "adjoins its cluster's extent"
ORDER_MIN = 0.5        # mm: parts closer than this along an axis are in one row (or column) along it
CHAR_ADV = 0.9         # see the module text


@dataclasses.dataclass(frozen=True)
class Key:
    box: tuple          # (x0, y0, x1, y1), Due mm
    texts: tuple        # ((text, x, y), ...), Due mm


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


def read_keys(txt):
    """the unfilled F.SilkS rectangles of a board text, with the board texts inside each; designator-ness is judged later"""
    texts = []
    for m in re.finditer(r'\(gr_text "([^"]*)"\s*\(at ([-\d.]+) ([-\d.]+)[^)]*\)\s*\(layer "F\.SilkS"\)', txt):
        x, y = boardio.to_due(float(m.group(2)), float(m.group(3)))
        texts.append((m.group(1), x, y))
    keys = []
    for m in re.finditer(r'\(gr_rect(.*?)\n\t\)', txt, re.S):
        body = m.group(1)
        if '(layer "F.SilkS")' not in body or '(fill yes)' in body:
            continue
        s = re.search(r'\(start ([-\d.]+) ([-\d.]+)\)', body)
        e = re.search(r'\(end ([-\d.]+) ([-\d.]+)\)', body)
        x0, y0 = boardio.to_due(float(s.group(1)), float(s.group(2)))
        x1, y1 = boardio.to_due(float(e.group(1)), float(e.group(2)))
        box = _box(x0, y0, x1, y1)
        inside = tuple(t for t in texts if box[0] < t[1] < box[2] and box[1] < t[2] < box[3])
        keys.append(Key(box, inside))
    return keys


def findings(b, keys=(), bnc_labels=None, exempt=None):
    bad = []
    exempt = dict(exempt or {})
    refs = list(b.fp_ref)
    row = {int(k): i for i, k in enumerate(b.fp_idx)}
    top = [int(s) == 0 for s in b.fp_side]
    cour = [_box(*c) if not np.isnan(c).any() else None for c in zip(b.fp_cx0, b.fp_cy0, b.fp_cx1, b.fp_cy1)]
    pads = [(int(f), (x0, y0, x1, y1)) for f, x0, y0, x1, y1 in zip(b.p_fp, b.p_bx0, b.p_by0, b.p_bx1, b.p_by1)]
    others = [i for i in range(len(refs)) if top[i] and cour[i] is not None]

    # 1. own designators
    shown = set()
    for j in range(len(b.r_fp)):
        i = row[int(b.r_fp[j])]
        if not top[i] or not b.r_on_silk[j] or int(b.r_layer[j]) != boardio.R_LAYERS['F.SilkS']:
            continue
        r = refs[i]
        shown.add(r)
        if r in exempt:
            continue
        t = text_box(r, b.r_x[j], b.r_y[j], b.r_w[j], b.r_h[j], b.r_ang[j])
        if min(abs(b.r_ang[j] % 360.0 - a) for a in (0.0, 90.0, 360.0)) > 0.5:
            bad.append(f'{r}: designator at {b.r_ang[j]:g} degrees, not 0 or 90')
        if cour[i] is None:
            bad.append(f'{r}: no courtyard to be beside')
            continue
        own = _gap(t, cour[i])
        near = min(((_gap(t, cour[k]), refs[k]) for k in others if k != i), default=(np.inf, ''))
        if near[0] - own < OWN_MARGIN:
            bad.append(f'{r}: designator {own:.2f} mm from its part and {near[0]:.2f} mm from {near[1]}, margin under {OWN_MARGIN}')
        hits = sorted({refs[k] for k in others if k != i and _overlap(t, cour[k])})
        if hits:
            bad.append(f'{r}: designator lies on the courtyard of {", ".join(hits)}')
        if any(_overlap(t, p) for f, p in pads):
            bad.append(f'{r}: designator lies on a pad')

    # 2. cluster keys
    named = {}
    for n, k in enumerate(keys):
        ts = [t for t in k.texts if t[0] in refs]
        if len(k.texts) < 2 or len(ts) != len(k.texts):
            continue                                    # a rectangle that is not a key (a block outline, a box with a word in it)
        where = f'key {n} at ({k.box[0]:.1f}, {k.box[1]:.1f})'
        for s, x, y in ts:
            named.setdefault(s, []).append(where)
        for i in others:
            if _overlap(k.box, cour[i]):
                bad.append(f'{where}: lies on the courtyard of {refs[i]}')
        if any(_overlap(k.box, p) for f, p in pads):
            bad.append(f'{where}: lies on a pad')
        idx = [refs.index(s) for s, _, _ in ts]
        ext = (min(cour[i][0] for i in idx if cour[i]), min(cour[i][1] for i in idx if cour[i]),
               max(cour[i][2] for i in idx if cour[i]), max(cour[i][3] for i in idx if cour[i]))
        if _gap(k.box, ext) > KEY_GAP_MAX:
            bad.append(f'{where}: {_gap(k.box, ext):.2f} mm from its parts, more than {KEY_GAP_MAX}')
        for a in range(len(ts)):
            for c in range(a + 1, len(ts)):
                pa, pc = idx[a], idx[c]
                for ax, name in ((1, 'x'), (2, 'y')):
                    dp = (b.fp_x[pc] - b.fp_x[pa]) if ax == 1 else (b.fp_y[pc] - b.fp_y[pa])
                    dt = ts[c][ax] - ts[a][ax]
                    if abs(dp) > ORDER_MIN and np.sign(dp) != np.sign(dt):
                        bad.append(f'{where}: {ts[a][0]} and {ts[c][0]} are out of order along {name}')
    for i in others:
        r = refs[i]
        if r in shown or r in exempt:
            if r in named and r in shown:
                bad.append(f'{r}: has its own designator and a place in {named[r][0]}')
            continue
        if r not in named:
            bad.append(f'{r}: no designator and in no key')
        elif len(named[r]) > 1:
            bad.append(f'{r}: named {len(named[r])} times in keys')

    # 3. BNC frames
    first = None
    for r, label in (bnc_labels or {}).items():
        if r not in refs:
            bad.append(f'{r}: no such connector')
            continue
        i = refs.index(r)
        js = [j for j in range(len(b.r_fp)) if row[int(b.r_fp[j])] == i and b.r_on_silk[j]]
        ls = [n for n, t in enumerate(b.t_text) if t == label]
        if len(js) != 1 or len(ls) != 1:
            bad.append(f'{r}: {len(js)} designators and {len(ls)} "{label}" labels, wanted one each')
            continue
        a = np.radians(b.fp_rot[i])
        R = np.array([[np.cos(a), np.sin(a)], [-np.sin(a), np.cos(a)]])     # board -> the part's own frame (y up, ccw angles)
        o = np.array([b.fp_x[i], b.fp_y[i]])
        here = (R @ (np.array([b.r_x[js[0]], b.r_y[js[0]]]) - o), R @ (np.array([b.t_x[ls[0]], b.t_y[ls[0]]]) - o))
        if first is None:
            first = (r, here)
            continue
        for what, p, q in (('designator', here[0], first[1][0]), (f'"{label}"', here[1], first[1][1])):
            if np.abs(p - q).max() > BNC_TOL:
                bad.append(f'{r}: {what} at ({p[0]:.2f}, {p[1]:.2f}) in its frame, {first[0]} has it at ({q[0]:.2f}, {q[1]:.2f})')
    return bad
