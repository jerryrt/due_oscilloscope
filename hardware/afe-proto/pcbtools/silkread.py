"""D30 (docs/afe.md): can a technician with only the board find a part from its designator?

    findings(b, bnc_labels=None, exempt=None)  -> [str]     the reasons it cannot (empty = it can)
    runs(b)                                     -> {starter ref: [member refs]}   the labelled runs the board carries

The owner's convention (2026-11-15), on the top side (the board has no bottom parts):

1. Beside its part. A visible designator is beside its own part: the gap from the text's box to its own courtyard is at
   least OWN_MARGIN smaller than the gap to any other top courtyard, the box covers no pad and no other part's courtyard,
   and a two-terminal part's designator reads along the part (0 degrees on a horizontal part, 90 on a vertical one;
   any other part's reads at 0 or 90).
2. Or a labelled run. Where same-type parts sit tight in a straight row or column, only the lowest-numbered one is
   labelled and the rest follow in order. The label lies on the run's own line (its centre within RUN_ALIGN of the
   starter's centre line), on the starter's side away from the run, within RUN_GAP_MAX of its courtyard, and covers no
   pad and no other part's courtyard; it reads along the line. The members are the starter's prefix with numbers n+1,
   n+2, ... for as long as each next one sits on the same line (RUN_ALIGN), at the same orientation, further along, and
   within RUN_ADJ of the previous member's courtyard, with its own designator hidden.
   Rule 1's margin is not asked of a starter: its label is read by the line, not by distance.
3. Every top part is labelled: its own designator is visible (rules 1 or 2), or it is a member of a labelled run.
4. One BNC frame (owner, 2026-11-15). Each connector named in `bnc_labels` ({ref: function label}) carries its function
   label on the top silk and its designator on the bottom silk beside its pins (mirrored there by the layout; this module
   does not read mirroring), none on top, each at the same offset in its own frame as the first one's, to BNC_TOL. A
   bottom designator counts as shown when it is on B.SilkS: the board arrays carry no visibility for the bottom.

A part may be exempted by name with its reason (`exempt`); the reason is the board's gate-3 notes' to give.

Text extents are estimated, not read: a stroke-font character is CHAR_ADV of its width wide *(check: 0.9 matches the
1.0 mm designators in the AFE-2 render to within a pixel at 13.5 px/mm; other fonts or sizes are unmeasured)*.
Everything is in Due mm, y up (boardio's frame).
"""
import re

import numpy as np

from pcbtools import boardio

OWN_MARGIN = 0.25      # mm, D30
BNC_TOL = 0.05         # mm, D30
RUN_ALIGN = 0.3        # mm: on one line
RUN_ADJ = 1.2          # mm: courtyard to courtyard, neighbours in a run
RUN_GAP_MAX = 1.5      # mm: a starter's label from its courtyard
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


def _split(ref):
    m = re.match(r'([A-Z]+)(\d+)$', ref)
    return (m.group(1), int(m.group(2))) if m else (None, None)


class _Board:
    """the lookups the rules share"""

    def __init__(self, b):
        self.b = b
        self.refs = list(b.fp_ref)
        self.by_ref = {r: i for i, r in enumerate(self.refs)}
        row = {int(k): i for i, k in enumerate(b.fp_idx)}
        self.row = row
        self.top = [int(s) == 0 for s in b.fp_side]
        self.cour = [_box(*c) if not np.isnan(c).any() else None for c in zip(b.fp_cx0, b.fp_cy0, b.fp_cx1, b.fp_cy1)]
        self.pads = [(int(f), (x0, y0, x1, y1)) for f, x0, y0, x1, y1 in zip(b.p_fp, b.p_bx0, b.p_by0, b.p_bx1, b.p_by1)]
        self.npads = np.bincount(np.asarray(b.p_fp, int), minlength=len(self.refs)) if len(b.p_fp) else np.zeros(len(self.refs), int)
        self.others = [i for i in range(len(self.refs)) if self.top[i] and self.cour[i] is not None]
        self.label = {}                                  # ref -> (box, angle, x, y) of its visible top designator
        for j in range(len(b.r_fp)):
            i = row[int(b.r_fp[j])]
            if self.top[i] and b.r_on_silk[j] and int(b.r_layer[j]) == boardio.R_LAYERS['F.SilkS']:
                r = self.refs[i]
                self.label[r] = (text_box(r, b.r_x[j], b.r_y[j], b.r_w[j], b.r_h[j], b.r_ang[j]), float(b.r_ang[j]),
                                 float(b.r_x[j]), float(b.r_y[j]))

    def horizontal(self, i):
        """a two-terminal part lies along x (True) or along y (False); None if it has not two pads"""
        if self.npads[i] != 2 or self.cour[i] is None:
            return None
        c = self.cour[i]
        return (c[2] - c[0]) >= (c[3] - c[1])

    def along(self, i, ang):
        """does a text at `ang` read along part i (at 0 or 90 when the part has no axis)?"""
        a = ang % 180.0
        flat, upright = min(a, 180.0 - a) < 0.5, abs(a - 90.0) < 0.5
        h = self.horizontal(i)
        return (flat or upright) if h is None else (flat if h else upright)

    def blocked(self, box, own):
        """refs whose courtyard the box lies on (own excluded), and whether it lies on a pad"""
        hits = sorted({self.refs[k] for k in self.others if k != own and _overlap(box, self.cour[k])})
        return hits, any(_overlap(box, p) for f, p in self.pads)


def _run_from(B, r):
    """the members after starter r, if its label sits on a run's line; [] if it is no starter"""
    i = B.by_ref[r]
    box, ang, lx, ly = B.label[r]
    h = B.horizontal(i)
    pre, n = _split(r)
    if h is None or pre is None:
        return []
    b = B.b
    cx, cy = b.fp_x[i], b.fp_y[i]
    if h and abs(ly - cy) <= RUN_ALIGN:
        axis, sign = 0, (1.0 if lx < cx else -1.0)       # the run goes away from the label
    elif not h and abs(lx - cx) <= RUN_ALIGN:
        axis, sign = 1, (1.0 if ly < cy else -1.0)
    else:
        return []
    members, prev = [], i
    while True:
        q = B.by_ref.get(f'{pre}{n + len(members) + 1}')
        if q is None or not B.top[q] or B.horizontal(q) != h or B.refs[q] in B.label:
            break
        if abs((b.fp_y[q] - cy) if axis == 0 else (b.fp_x[q] - cx)) > RUN_ALIGN:
            break
        d = ((b.fp_x[q] - b.fp_x[prev]) if axis == 0 else (b.fp_y[q] - b.fp_y[prev])) * sign
        if d <= 0 or _gap(B.cour[prev], B.cour[q]) > RUN_ADJ:
            break
        members.append(B.refs[q])
        prev = q
    return members


def runs(b):
    B = _Board(b)
    return {r: m for r in B.label for m in [_run_from(B, r)] if m}


def findings(b, bnc_labels=None, exempt=None):
    B = _Board(b)
    exempt = dict(exempt or {})
    bad = []
    starters = {r: m for r in B.label for m in [_run_from(B, r)] if m}
    member = {x for m in starters.values() for x in m}

    for r, (box, ang, lx, ly) in B.label.items():
        if r in exempt:
            continue
        i = B.by_ref[r]
        if not B.along(i, ang):
            bad.append(f'{r}: designator at {ang:g} degrees does not read along its part')
        if B.cour[i] is None:
            bad.append(f'{r}: no courtyard to be beside')
            continue
        hits, on_pad = B.blocked(box, i)
        if hits:
            bad.append(f'{r}: designator lies on the courtyard of {", ".join(hits)}')
        if on_pad:
            bad.append(f'{r}: designator lies on a pad')
        if _overlap(box, B.cour[i]):
            bad.append(f'{r}: designator lies on its own part, which hides it')
        own = _gap(box, B.cour[i])
        if r in starters:
            if own > RUN_GAP_MAX:
                bad.append(f'{r}: run label {own:.2f} mm from its starter, more than {RUN_GAP_MAX}')
            continue
        near = min(((_gap(box, B.cour[k]), B.refs[k]) for k in B.others if k != i), default=(np.inf, ''))
        if near[0] - own < OWN_MARGIN:
            bad.append(f'{r}: designator {own:.2f} mm from its part and {near[0]:.2f} mm from {near[1]}, margin under {OWN_MARGIN}')

    for i in B.others:
        r = B.refs[i]
        if r not in B.label and r not in member and r not in exempt and r not in (bnc_labels or {}):
            bad.append(f'{r}: no designator and in no labelled run')

    frames = {}
    for r, label in (bnc_labels or {}).items():
        if r not in B.by_ref:
            bad.append(f'{r}: no such connector')
            continue
        i = B.by_ref[r]
        top = [j for j in range(len(b.r_fp)) if B.row[int(b.r_fp[j])] == i and b.r_on_silk[j]]
        bot = [j for j in range(len(b.r_fp)) if B.row[int(b.r_fp[j])] == i and int(b.r_layer[j]) == boardio.R_LAYERS['B.SilkS']]
        ls = [n for n, t in enumerate(b.t_text) if t == label]
        if len(ls) != 1 or len(bot) != 1 or top:
            bad.append(f'{r}: {len(ls)} "{label}" labels on top, {len(bot)} designators on the bottom and {len(top)} on top; '
                       f'wanted one label, one bottom designator, none on top')
            continue
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
