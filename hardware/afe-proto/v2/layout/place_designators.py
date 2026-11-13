"""Silk-only designator placement for the integrated v2 board (LR-11 legibility): moves each reference designator's text so
no two are closer than the config's DESIGNATOR_GAP_MIN edge to edge, none lies over a pad / via / other silk, and each stays
within DESIGNATOR_DIST_MAX of its own part's pads. Copper and parts are untouched: only the `(at x y [rot])` of
`(property "Reference" ...)` in the board text changes.

    python3 v2/layout/place_designators.py BOARD.kicad_pcb [--write OUT.kicad_pcb]      (in the PCB image: it reads the board with pcbnew)

Method: minimum conflicts. Every designator is an axis-aligned box (text at 0 or 90 degrees: length n x ADVANCE x height by height).
A designator in conflict is moved to the candidate (grid step STEP, both orientations) nearest to where it was that clears
every hard constraint against all the others' current boxes; repeated until none is in conflict or nothing improves.
"""
import math
import os
import re
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..'))
from pcbtools import boardio, sexpr, rules  # noqa: E402
from pcbtools.boards import v2_layout as cfg  # noqa: E402
sys.path.insert(0, HERE)
import outlines  # noqa: E402

STEP = 0.1
TEXT_H = 0.8             # mm: every designator's text height: the board house's minimum legible, and one character height is then the
                         # gap the check asks for (None keeps each as it is; at 1.0 mm no placement clears 1.0 mm on this board)
PAD_CLEAR = 0.05         # mm between a designator's box (ink) and any pad
VIA_CLEAR = 0.1
SILK_CLEAR = 0.02        # and any other silk line
GAP_MARGIN = 0.05        # aim this far past DESIGNATOR_GAP_MIN, so the check does not pass by a hair
DIST_MARGIN = 0.05
ANNEAL = (0.8, 0.03, 400)
CYCLES = 12              # re-heats
REACH = 9.0              # mm: how far from a conflicted label the others may be moved to make room  # start and end temperature (in conflicted pairs) and the number of sweeps
TOUCH = 0.3              # mm: labels closer than this are one smudge; they cost TOUCH_PENALTY more than any shortfall of the wanted gap
TOUCH_PENALTY = 3.0
HOME_COST = 10.0         # mm-equivalent: see candidates()
W_DISP = 0.04            # energy per mm of displacement (a conflicted pair costs 1)


def kc(x, y):            # Due -> KiCad sheet
    return x + 50.0, 150.0 - y


def rot(a, x, y):        # footprint-local -> sheet offset, KiCad y down, positive angle counter-clockwise on screen
    c, s = math.cos(math.radians(a)), math.sin(math.radians(a))
    return x * c + y * s, -x * s + y * c


def unrot(a, x, y):
    return rot(-a, x, y)


def silk_obstacles(text):
    """AABBs (x0, y0, x1, y1) of every F.SilkS line, rectangle side and circle on the board (sheet mm), footprint ones
    transformed into the sheet, long diagonals cut into pieces, plus each board-level silk word's box"""
    boxes = []

    def seg(x0, y0, x1, y1, w):
        n = max(1, int(math.hypot(x1 - x0, y1 - y0) / 0.6))
        for k in range(n):
            ax, ay = x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n
            bx, by = x0 + (x1 - x0) * (k + 1) / n, y0 + (y1 - y0) * (k + 1) / n
            boxes.append((min(ax, bx) - w / 2, min(ay, by) - w / 2, max(ax, bx) + w / 2, max(ay, by) + w / 2))

    def xy(e, key):
        v = sexpr.first(e, key)
        return float(v[1]), float(v[2])

    def shape(e, tf):
        kind = e[0]
        lay = sexpr.first(e, 'layer')
        if lay is None or str(lay[1]) != 'F.SilkS':
            return
        st = sexpr.first(e, 'stroke')
        w = float(sexpr.first(st, 'width')[1]) if st else 0.12
        if kind in ('fp_line', 'gr_line'):
            (x0, y0), (x1, y1) = xy(e, 'start'), xy(e, 'end')
            (x0, y0), (x1, y1) = tf(x0, y0), tf(x1, y1)
            seg(x0, y0, x1, y1, w)
        elif kind in ('fp_rect', 'gr_rect'):
            (x0, y0), (x1, y1) = xy(e, 'start'), xy(e, 'end')
            pts = [tf(x0, y0), tf(x1, y0), tf(x1, y1), tf(x0, y1)]
            for k in range(4):
                seg(*pts[k], *pts[(k + 1) % 4], w)
        elif kind in ('fp_circle', 'gr_circle'):
            (cx, cy), (ex, ey) = xy(e, 'center'), xy(e, 'end')
            r = math.hypot(ex - cx, ey - cy)
            X, Y = tf(cx, cy)
            boxes.append((X - r - w / 2, Y - r - w / 2, X + r + w / 2, Y + r + w / 2))
        elif kind in ('fp_arc', 'gr_arc'):
            pts = [tf(*xy(e, k)) for k in ('start', 'mid', 'end')]
            seg(*pts[0], *pts[1], w)
            seg(*pts[1], *pts[2], w)
        elif kind in ('fp_poly', 'gr_poly'):
            pts = [tf(float(p[1]), float(p[2])) for p in sexpr.first(e, 'pts')[1:] if p[0] == 'xy']
            for k in range(len(pts)):
                seg(*pts[k], *pts[(k + 1) % len(pts)], w)

    for e in sexpr.parse(text):
        if not isinstance(e, list) or not e:
            continue
        if e[0] == 'footprint':
            at = sexpr.first(e, 'at')
            fx, fy, fa = float(at[1]), float(at[2]), float(at[3]) if len(at) > 3 else 0.0
            tf = lambda x, y, fx=fx, fy=fy, fa=fa: (fx + rot(fa, x, y)[0], fy + rot(fa, x, y)[1])
            for s in e[1:]:
                if isinstance(s, list) and s and s[0].startswith('fp_'):
                    shape(s, tf)
        elif e[0].startswith('gr_') and e[0] != 'gr_text':
            shape(e, lambda x, y: (x, y))
        elif e[0] == 'gr_text':
            lay = sexpr.first(e, 'layer')
            if lay and str(lay[1]) == 'F.SilkS':
                at = sexpr.first(e, 'at')
                font = sexpr.first(sexpr.first(e, 'effects'), 'font')
                h = float(sexpr.first(font, 'size')[1])
                n = len(str(e[1]))
                L, H = n * cfg.DESIGNATOR_ADVANCE * h, cfg.DESIGNATOR_INK_H * h
                a = float(at[3]) if len(at) > 3 else 0.0
                if int(round(a)) % 180 == 90:
                    L, H = H, L
                boxes.append((float(at[1]) - L / 2, float(at[2]) - H / 2, float(at[1]) + L / 2, float(at[2]) + H / 2))
    return np.array(boxes, float).reshape(-1, 4)


def _gap(b, o):
    """gap between box b (4,) and boxes o (n,4), per box (0 = touching or overlapping)"""
    dx = np.maximum(0.0, np.maximum(o[:, 0] - b[2], b[0] - o[:, 2]))
    dy = np.maximum(0.0, np.maximum(o[:, 1] - b[3], b[1] - o[:, 3]))
    return np.hypot(dx, dy)


def solve(b, text, log=print):
    refs = list(b.fp_ref)
    rows = {refs[int(b.r_fp[k])]: k for k in range(len(b.r_fp)) if b.r_on_silk[k] and int(b.r_layer[k]) == 0}
    adv, ink = cfg.DESIGNATOR_ADVANCE, cfg.DESIGNATOR_INK_H
    gmin = cfg.DESIGNATOR_GAP_MIN + GAP_MARGIN
    # pads in the sheet
    px0, px1 = b.p_bx0 + 50, b.p_bx1 + 50
    py0, py1 = 150 - b.p_by1, 150 - b.p_by0
    pads = np.column_stack([px0, py0, px1, py1])
    owner = b.p_fp.astype(int)
    vias = np.column_stack([b.v_x + 50 - b.v_dia / 2, 150 - b.v_y - b.v_dia / 2, b.v_x + 50 + b.v_dia / 2, 150 - b.v_y + b.v_dia / 2])
    silk = silk_obstacles(text)
    hard = np.vstack([pads - [PAD_CLEAR, PAD_CLEAR, -PAD_CLEAR, -PAD_CLEAR], vias - [VIA_CLEAR, VIA_CLEAR, -VIA_CLEAR, -VIA_CLEAR],
                      silk - [SILK_CLEAR, SILK_CLEAR, -SILK_CLEAR, -SILK_CLEAR]])
    hard_owner = np.concatenate([owner, -np.ones(len(vias) + len(silk), int)])
    sheet_rects = [(r[0] + 50, 150 - r[3], r[2] + 50, 150 - r[1]) for r in outlines.all_rects()]
    state = {}
    for ref, k in rows.items():
        h = TEXT_H or float(b.r_h[k])
        a = int(round(b.r_ang[k])) % 180
        state[ref] = dict(x=b.r_x[k] + 50, y=150 - b.r_y[k], h=h, n=len(ref), a=a, x0=b.r_x[k] + 50, y0=150 - b.r_y[k], a0=a)

    def box(s, x=None, y=None, a=None):
        x = s['x'] if x is None else x
        y = s['y'] if y is None else y
        a = s['a'] if a is None else a
        L, H = s['n'] * adv * s['h'], ink * s['h']
        if a == 90:
            L, H = H, L
        return np.array([x - L / 2, y - H / 2, x + L / 2, y + H / 2])

    def violations(ref):
        """(count of conflicts of ref's current box)"""
        s = state[ref]
        B = box(s)
        fi = refs.index(ref)
        n = 0
        for o, t in state.items():
            if o != ref and _gap(B, box(t)[None])[0] < cfg.DESIGNATOR_GAP_MIN:
                n += 1
        m = (hard_owner != fi) & (_gap(B, hard) <= 0)          # any foreign pad / via / silk under it (own pads: below)
        n += int(m.sum())
        mine = np.flatnonzero(owner == fi)
        if len(mine) and _gap(B, pads[mine]).min() > cfg.DESIGNATOR_DIST_MAX - DIST_MARGIN:
            n += 1
        return n

    def candidates(ref):
        """every position (x, y, a, cost) of ref's box that clears the hard constraints (pads, vias, silk, the board, and the
        distance to its own pads); the cost is the displacement from where it was"""
        s = state[ref]
        fi = refs.index(ref)
        P = pads[np.flatnonzero(owner == fi)]
        px, py = b.fp_x[fi] + 50, 150 - b.fp_y[fi]
        home = [h for h in sheet_rects if h[0] <= px <= h[2] and h[1] <= py <= h[3]]
        lo = P[:, :2].min(0) - cfg.DESIGNATOR_DIST_MAX
        hi = P[:, 2:].max(0) + cfg.DESIGNATOR_DIST_MAX
        Hd = hard[(hard_owner != fi)]
        Hd = Hd[(Hd[:, 2] >= lo[0] - 3) & (Hd[:, 0] <= hi[0] + 3) & (Hd[:, 3] >= lo[1] - 3) & (Hd[:, 1] <= hi[1] + 3)]
        Hd = np.vstack([Hd, P - [PAD_CLEAR, PAD_CLEAR, -PAD_CLEAR, -PAD_CLEAR]])      # nor on its own pads
        X, Y = np.meshgrid(np.arange(lo[0], hi[0], STEP), np.arange(lo[1], hi[1], STEP))
        X, Y = X.ravel(), Y.ravel()
        out = []
        for a in ((0, 90) if s['a'] in (0, 90) else (s['a'],)):
            L, H = s['n'] * adv * s['h'], ink * s['h']
            if a == 90:
                L, H = H, L
            B = np.column_stack([X - L / 2, Y - H / 2, X + L / 2, Y + H / 2])
            ok = np.ones(len(X), bool)
            for o in Hd:
                ok &= ~((B[:, 0] < o[2]) & (B[:, 2] > o[0]) & (B[:, 1] < o[3]) & (B[:, 3] > o[1]))
            dd = np.full(len(X), 1e9)
            for p_ in P:
                dx = np.maximum(0.0, np.maximum(p_[0] - B[:, 2], B[:, 0] - p_[2]))
                dy = np.maximum(0.0, np.maximum(p_[1] - B[:, 3], B[:, 1] - p_[3]))
                dd = np.minimum(dd, np.hypot(dx, dy))
            ok &= dd <= cfg.DESIGNATOR_DIST_MAX - DIST_MARGIN
            ok &= (B[:, 0] > 67.6) & (B[:, 2] < 166.4) & (B[:, 1] > 97.3) & (B[:, 3] < 149.4)
            away = np.zeros(len(X))
            if home:                                     # a label centred outside the outline that holds its part reads as the next
                inside = np.zeros(len(X), bool)          # block's: it costs HOME_COST mm of displacement
                for h in home:
                    inside |= (X >= h[0]) & (X <= h[2]) & (Y >= h[1]) & (Y <= h[3])
                away = np.where(inside, 0.0, HOME_COST)
            cost = np.hypot(X - s['x0'], Y - s['y0']) + (0.6 if a != s['a0'] else 0.0) + away
            out += [(X[k], Y[k], a, cost[k], B[k]) for k in np.flatnonzero(ok)]
        return out

    order = list(state)
    cands = {r: candidates(r) for r in order}
    for r in order:
        if not cands[r]:
            log(f'  no admissible place at all for {r}')
    # the box the current state gives each ref; simulated annealing over the candidate sets, energy = designator pairs closer
    # than the gap (weight 1) + the displacement (weight W_DISP), so conflicts go first and the labels stay near where they were
    for r in order:                                       # a label already breaking a hard constraint (a pad, the distance) is snapped
        if cands[r] and violations(r) > 0:                # to the nearest admissible place first
            x, y, a, c, B = min(cands[r], key=lambda t: t[3])
            state[r].update(x=float(x), y=float(y), a=a, c=float(c))
    cur = {r: box(state[r]) for r in order}
    # two labels can meet only if the regions they can occupy meet: the part's pads grown by the distance limit plus a label's length
    Rg = cfg.DESIGNATOR_DIST_MAX + 5.0
    reg = {}
    for r in order:
        P_ = pads[np.flatnonzero(owner == refs.index(r))]
        reg[r] = (P_[:, 0].min() - Rg, P_[:, 1].min() - Rg, P_[:, 2].max() + Rg, P_[:, 3].max() + Rg)
    near = {r: [o for o in order if o != r and reg[o][0] < reg[r][2] and reg[r][0] < reg[o][2] and reg[o][1] < reg[r][3] and reg[r][1] < reg[o][3]]
            for r in order}

    def pair_energy(r, B):
        """the shortfall, in mm of the wanted gap, summed over the neighbours: spreads the labels as far as the room allows,
        where a count of pairs under the limit stops at the limit"""
        return sum(max(0.0, gmin - g) + (TOUCH_PENALTY if g < TOUCH else 0.0) for g in (_gap(B, cur[o][None])[0] for o in near[r]))

    def total():
        return sum(pair_energy(r, cur[r]) for r in order) / 2
    T0, T1, SWEEPS = ANNEAL
    rng = np.random.default_rng(1)

    def conflicted():
        return [r for r in order if pair_energy(r, cur[r]) > GAP_MARGIN]

    def snapshot():
        return {r: (state[r]['x'], state[r]['y'], state[r]['a'], cur[r], state[r].get('c', 0.0)) for r in order}
    best_e, best_s = total(), snapshot()
    sweep = 0
    for cycle in range(CYCLES):
        # each cycle re-heats and anneals again, but only the labels in conflict and those within REACH mm of one move
        for sw in range(SWEEPS):
            sweep += 1
            T = T0 * (T1 / T0) ** (sw / (SWEEPS - 1))
            bad = conflicted()
            if not bad:
                break
            act = [r for r in order if any(math.hypot(state[r]['x'] - state[q]['x'], state[r]['y'] - state[q]['y']) < REACH for q in bad)]
            for r in act:
                if not cands[r]:
                    continue
                e_old = pair_energy(r, cur[r])
                x, y, a, c, B = cands[r][int(rng.integers(len(cands[r])))]
                c_old = state[r].get('c', 0.0)
                d = (pair_energy(r, B) - e_old) + W_DISP * (c - c_old)
                if e_old == 0 and d > 0 and rng.random() > 0.15:   # a clear label mostly stays; sometimes it gives way to a neighbour
                    continue
                if d <= 0 or rng.random() < math.exp(-d / T):
                    state[r].update(x=float(x), y=float(y), a=a, c=float(c))
                    cur[r] = B
            e = total()
            if e < best_e:
                best_e, best_s = e, snapshot()
        log(f'  cycle {cycle} sweeps {sweep} conflicts {total():.0f} (best {best_e:.0f})')
        if best_e == 0:
            break
    for r, (x, y, a, B, c) in best_s.items():
        state[r].update(x=x, y=y, a=a, c=c)
        cur[r] = B
    # polish: with the conflicts gone, each label goes back to the admissible place nearest where it was that stays clear of the others
    for _ in range(8):
        for r in order:
            if not cands[r] or violations(r):
                continue
            for x, y, a, c, B in sorted(cands[r], key=lambda t: t[3]):
                if c >= state[r].get('c', 0.0):
                    break
                if pair_energy(r, B) == 0:
                    state[r].update(x=float(x), y=float(y), a=a, c=float(c))
                    cur[r] = B
                    break
    nrounds = sweep
    left = [r for r in state if violations(r)]
    log(f'sweeps {nrounds}; designators still in conflict: {left}')
    return {r: (s['x'], s['y'], s['a']) for r, s in state.items() if (s['x'], s['y'], s['a']) != (s['x0'], s['y0'], s['a0'])}, left


def apply_moves(text, b, moves):
    """rewrite the (at ...) of each moved designator's Reference property; abs text position -> footprint-local"""
    refs = list(b.fp_ref)
    if TEXT_H:
        for ref in refs:
            m = re.search(r'\(property "Reference" "%s".*?\(size [-\d.]+ [-\d.]+\)' % re.escape(ref), text, re.S)
            if m:
                text = text[:m.start()] + re.sub(r'\(size [-\d.]+ [-\d.]+\)$', f'(size {TEXT_H:g} {TEXT_H:g})', m.group(0)) + text[m.end():]
    for ref, (x, y, a) in moves.items():
        fi = refs.index(ref)
        fx, fy = b.fp_x[fi] + 50, 150 - b.fp_y[fi]
        fa = _fp_angle(text, ref)
        lx, ly = unrot(fa, x - fx, y - fy)
        pat = re.compile(r'(\(property "Reference" "%s"\s*\(at )([-\d.]+) ([-\d.]+)( [-\d.]+)?(\))' % re.escape(ref))
        m = pat.search(text)
        ang = float(m.group(4)) if m.group(4) else 0.0
        k = refs.index(ref)
        k = next(j for j in range(len(b.r_fp)) if int(b.r_fp[j]) == k and int(b.r_layer[j]) == 0)
        da = a - (int(round(b.r_ang[k])) % 180)
        ang_new = ang + da
        txt = f'{m.group(1)}{lx:.4f} {ly:.4f}' + (f' {ang_new:g}' if (m.group(4) or da) else '') + ')'
        text = text[:m.start()] + txt + text[m.end():]
    return text


def _fp_angle(text, ref):
    m = re.search(r'\(footprint "[^"]*"(?:(?!\(footprint ).)*?\(at [-\d.]+ [-\d.]+(?: ([-\d.]+))?\)(?:(?!\(footprint ).)*?\(property "Reference" "%s"' % re.escape(ref), text, re.S)
    return float(m.group(1)) if m and m.group(1) else 0.0


def main(argv):
    path = argv[0]
    out = argv[argv.index('--write') + 1] if '--write' in argv else None
    b = boardio.read_board(path)
    text = open(path).read()
    before = rules.designator_findings(b, cfg)
    print(f'before: {len(before[0])} pairs closer than {cfg.DESIGNATOR_GAP_MIN} mm, {len(before[1])} over a pad, {len(before[2])} too far')
    moves, left = solve(b, text)
    print(f'{len(moves)} designators moved')
    if out:
        open(out, 'w').write(apply_moves(text, b, moves))
        after = rules.designator_findings(boardio.read_board(out), cfg)
        print(f'after: {len(after[0])} pairs closer than {cfg.DESIGNATOR_GAP_MIN} mm, {len(after[1])} over a pad, {len(after[2])} too far')
        # the pairs the room does not allow, as the config's DESIGNATOR_GAP_WAIVED (floor = the gap reached, rounded down to 0.05)
        print('DESIGNATOR_GAP_WAIVED = {' + ', '.join(f'({a!r}, {c!r}): {math.floor(g * 20) / 20:.2f}' for a, c, g in after[0]) + '}')
    return 1 if left else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
