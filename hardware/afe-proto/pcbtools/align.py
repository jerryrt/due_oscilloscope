"""D31 (docs/afe.md): a technician reads a block as rows and columns of parts, not as a scatter.

    findings(b) -> [str]   the parts that break the pattern (empty = none do)

The owner's ruling (2026-11-16): the electrical rules come first, the designator rule (D30, silkread) second, and within
both, parts are lined up so the board can be read. On the top side, for every two-pin passive (R, C, BR, L, FB followed by
three digits; the hundreds digit is its block):

1. In line. It shares its centre's y (a row) or its centre's x (a column) with another two-pin passive of the same block
   and the same orientation, to ALIGN_TOL, whose centre is no further than REACH away; or it is on a pin line: its centre
   shares x or y, to ALIGN_TOL, with the centre of a pad of a part that is not a two-pin passive (an IC, a connector), no
   further than PIN_REACH away. The pin line is the way out for a part the electrical rules tie to a pin (LR-4, LR-12).
2. One label line per row. Two passives in one row (rule 1's sense) carry their top designators at one y, to ALIGN_TOL,
   so the labels read as a line too.

Orientation is the part's rotation modulo 180; two parts at 0 and 180 are one orientation. Everything is in Due mm, y up.
"""
import re

import numpy as np

from pcbtools import boardio

ALIGN_TOL = 0.05     # mm
REACH = 8.0          # mm, centre to centre: further than this two parts are not read as one row
PIN_REACH = 4.0      # mm, part centre to pad centre
PASSIVE = re.compile(r'(?:R|C|BR|L|FB)(\d)\d\d$')


def _orient(rot):
    return round(float(rot) % 180.0) % 180


def findings(b):
    refs = list(b.fp_ref)
    top = [int(s) == 0 for s in b.fp_side]
    blk = {i: m.group(1) for i, r in enumerate(refs) if top[i] and (m := PASSIVE.fullmatch(r))}
    xs, ys = np.asarray(b.fp_x, float), np.asarray(b.fp_y, float)
    pins = [(float(x), float(y)) for f, x, y in zip(b.p_fp, b.p_x, b.p_y)
            if top[int(f)] and int(f) not in blk]
    label_y = {}
    row = {int(k): i for i, k in enumerate(b.fp_idx)}
    for j in range(len(b.r_fp)):
        i = row[int(b.r_fp[j])]
        if b.r_on_silk[j] and int(b.r_layer[j]) == boardio.R_LAYERS['F.SilkS']:
            label_y[i] = float(b.r_y[j])
    bad = []
    for i, k in blk.items():
        mates = [j for j, kj in blk.items() if j != i and kj == k and _orient(b.fp_rot[j]) == _orient(b.fp_rot[i])
                 and np.hypot(xs[j] - xs[i], ys[j] - ys[i]) <= REACH]
        rows = [j for j in mates if abs(ys[j] - ys[i]) <= ALIGN_TOL]
        cols = [j for j in mates if abs(xs[j] - xs[i]) <= ALIGN_TOL]
        on_pin = any(np.hypot(px - xs[i], py - ys[i]) <= PIN_REACH and
                     (abs(px - xs[i]) <= ALIGN_TOL or abs(py - ys[i]) <= ALIGN_TOL) for px, py in pins)
        if not (rows or cols or on_pin):
            bad.append(f'{refs[i]}: in no row or column of block {k} and on no pin line')
        for j in rows:
            if j > i and i in label_y and j in label_y and abs(label_y[i] - label_y[j]) > ALIGN_TOL:
                bad.append(f'{refs[i]}, {refs[j]}: one row, designators {abs(label_y[i] - label_y[j]):.2f} mm apart in y')
    return bad
