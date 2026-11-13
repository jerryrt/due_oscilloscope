"""Silk-only designator refinement for the integrated v2 board: a second pass over place_designators.py's result that makes
the labels READ apart, not only measure apart. Moves each Reference text (position and 0/90 degree turn), never a part, a pad,
a track, a via or a zone.

    python3 v2/layout/refine_designators.py BOARD.kicad_pcb --write OUT.kicad_pcb      (in the PCB image: it reads the board with pcbnew)

Hard constraints, per candidate place of one label (as place_designators): clear of every foreign pad (PAD_CLEAR), via, silk line,
and its own pads; within DESIGNATOR_DIST_MAX of its own part; on the board; no closer than HARD_GAP to another label.
Soft, in this order: a pair that reads as one label (cfg.DESIGNATOR_GAP_ONE_LABEL, same baseline), a label centred in another
block's outline, the shortfall of every pair under cfg.DESIGNATOR_GAP_MIN, the displacement from where it was. Coordinate descent
with random restarts of the labels in trouble and every label within REACH of one.
"""
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..'))
sys.path.insert(0, HERE)
import place_designators as pd  # noqa: E402
from pcbtools import boardio, rules  # noqa: E402
from pcbtools.boards import v2_layout as cfg  # noqa: E402
import outlines  # noqa: E402

STEP = 0.1
HARD_GAP = 0.3
REACH = 6.0
T0, T1, SWEEPS, CYCLES = 1.5, 0.1, 150, int(os.environ.get("REFINE_CYCLES", 6))
W_CLOSE = 40.0
W_ONE, W_FOREIGN, W_SHORT, W_DISP, W_HOME = 100.0, 100.0, 8.0, 0.15, 1.0


def run(b, text, log=print, seed=3):
    pd.TEXT_H = None
    refs = list(b.fp_ref)
    rows = {refs[int(b.r_fp[k])]: k for k in range(len(b.r_fp)) if b.r_on_silk[k] and int(b.r_layer[k]) == 0}
    adv, ink = cfg.DESIGNATOR_ADVANCE, cfg.DESIGNATOR_INK_H
    pads = np.column_stack([b.p_bx0 + 50, 150 - b.p_by1, b.p_bx1 + 50, 150 - b.p_by0])
    owner = b.p_fp.astype(int)
    vias = np.column_stack([b.v_x + 50 - b.v_dia / 2, 150 - b.v_y - b.v_dia / 2, b.v_x + 50 + b.v_dia / 2, 150 - b.v_y + b.v_dia / 2])
    silk = pd.silk_obstacles(text)
    g = lambda a, s: a - [s, s, -s, -s]
    hard = np.vstack([g(pads, pd.PAD_CLEAR), g(vias, pd.VIA_CLEAR), g(silk, pd.SILK_CLEAR)])
    hard_owner = np.concatenate([owner, -np.ones(len(vias) + len(silk), int)])
    sheet = {k: [(r[0] + 50, 150 - r[3], r[2] + 50, 150 - r[1]) for r in v] for k, v in outlines.RECTS.items()}
    home_of = {r: cfg.BLOCK.get(r) for r in rows}
    for r in cfg.SHARED_PARTS:
        home_of[r] = None                                   # shared part: its label may sit in either outline

    waived = set(getattr(cfg, 'DESIGNATOR_FOREIGN_WAIVED', {}).items())

    def foreign(r, x, y, B=None):
        h = home_of.get(r)
        if h is None or h not in sheet:
            return False
        B = bx(st[r], x, y) if B is None else B
        cx, cy = (B[0] + B[2]) / 2, (B[1] + B[3]) / 2
        return any(k != h and (r, k) not in waived and any(a <= cx <= c and d <= cy <= e for a, d, c, e in rs) for k, rs in sheet.items())

    def straddle(r, B):
        h = home_of.get(r)
        if h is None or h not in sheet:
            return False
        return any(k != h and any(B[0] < c and B[2] > a and B[1] < e and B[3] > d for a, d, c, e in rs) for k, rs in sheet.items())

    def inhome(r, x, y):
        h = home_of.get(r)
        return h in sheet and any(a <= x <= c and d <= y <= e for a, d, c, e in sheet[h])

    st = {}
    for r, k in rows.items():
        st[r] = dict(x=b.r_x[k] + 50, y=150 - b.r_y[k], a=int(round(b.r_ang[k])) % 180, h=float(b.r_h[k]), n=len(r))
        st[r].update(x0=st[r]['x'], y0=st[r]['y'], a0=st[r]['a'])

    def bx(s, x=None, y=None, a=None):
        x = s['x'] if x is None else x
        y = s['y'] if y is None else y
        a = s['a'] if a is None else a
        L, H = s['n'] * adv * s['h'], ink * s['h']
        if a == 90:
            L, H = H, L
        return np.array([x - L / 2, y - H / 2, x + L / 2, y + H / 2])

    def pair_pen(A, B):
        """energy of two boxes (axis aligned: x0 y0 x1 y1)"""
        dx = max(0.0, max(B[0] - A[2], A[0] - B[2]))
        dy = max(0.0, max(B[1] - A[3], A[1] - B[3]))
        gap = math.hypot(dx, dy)
        if gap >= cfg.DESIGNATOR_GAP_MIN + 0.05:
            return 0.0, gap
        e = W_SHORT * (cfg.DESIGNATOR_GAP_MIN + 0.05 - gap)
        if gap < cfg.DESIGNATOR_GAP_ONE_LABEL + 0.05:
            e += W_CLOSE
        ov = min(A[3], B[3]) - max(A[1], B[1])
        if ov > 0.5 * min(A[3] - A[1], B[3] - B[1]) and dx < cfg.DESIGNATOR_GAP_ONE_LABEL + 0.05:
            e += W_ONE
        return e, gap

    cur = {r: bx(s) for r, s in st.items()}
    reg = {}
    for r in st:
        P = pads[owner == refs.index(r)]
        reg[r] = (P[:, 0].min() - 9, P[:, 1].min() - 9, P[:, 2].max() + 9, P[:, 3].max() + 9)
    near = {r: [o for o in st if o != r and reg[o][0] < reg[r][2] and reg[r][0] < reg[o][2] and reg[o][1] < reg[r][3] and reg[r][1] < reg[o][3]] for r in st}

    cands = {}
    for r, s in st.items():
        fi = refs.index(r)
        P = pads[owner == fi]
        lo, hi = P[:, :2].min(0) - cfg.DESIGNATOR_DIST_MAX, P[:, 2:].max(0) + cfg.DESIGNATOR_DIST_MAX
        Hd = hard[hard_owner != fi]
        Hd = Hd[(Hd[:, 2] >= lo[0] - 3) & (Hd[:, 0] <= hi[0] + 3) & (Hd[:, 3] >= lo[1] - 3) & (Hd[:, 1] <= hi[1] + 3)]
        Hd = np.vstack([Hd, g(P, pd.PAD_CLEAR)])
        X, Y = np.meshgrid(np.arange(lo[0], hi[0], STEP), np.arange(lo[1], hi[1], STEP))
        X, Y = X.ravel(), Y.ravel()
        out = []
        for a in (0, 90):
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
            ok &= dd <= cfg.DESIGNATOR_DIST_MAX - 0.05
            ok &= (B[:, 0] > 67.6) & (B[:, 2] < 166.4) & (B[:, 1] > 97.3) & (B[:, 3] < 149.4)
            for k in np.flatnonzero(ok):
                out.append((float(X[k]), float(Y[k]), a, B[k]))
        cands[r] = out
        log(f'  {r}: {len(out)} places') if not out else None

    for r in st:
        n_home = sum(1 for c in cands[r] if inhome(r, c[0], c[1]) and not foreign(r, c[0], c[1], c[3]))
        if n_home < 40:
            log(f'  {r}: {len(cands[r])} places, {n_home} at home')

    def energy(r, c):
        x, y, a, B = c
        e = 0.0
        for o in near[r]:
            p, gp = pair_pen(B, cur[o])
            if gp < HARD_GAP:
                return 1e9
            e += p
        s = st[r]
        if foreign(r, x, y, B):
            e += W_FOREIGN
        if straddle(r, B):
            e += 1.5
        if not inhome(r, x, y) and home_of.get(r) in sheet:
            e += W_HOME * 3
        e += W_DISP * math.hypot(x - s['x0'], y - s['y0']) + (0.03 if a != s['a0'] else 0.0)
        return e

    def pair_energy_only(r, c):
        x, y, a, B = c
        e = sum(pair_pen(B, cur[o])[0] for o in near[r])
        return e + (W_FOREIGN if foreign(r, x, y, B) else 0.0)

    def blocked(r, B=None):
        """the label's box as it stands overlaps a foreign pad, via or silk line (it moved with its part, or was never moved)"""
        B = cur[r] if B is None else B
        H = hard[hard_owner != refs.index(r)]
        return bool(np.any((B[0] < H[:, 2]) & (B[2] > H[:, 0]) & (B[1] < H[:, 3]) & (B[3] > H[:, 1])))

    def troubled():
        out = []
        for r in st:
            if blocked(r) or any(pair_pen(cur[r], cur[o])[0] > 0 for o in near[r]) or foreign(r, st[r]['x'], st[r]['y'], cur[r]):
                out.append(r)
        return out

    def total():
        t = sum(pair_pen(cur[r], cur[o])[0] for r in st for o in near[r] if o > r)
        return t + sum(W_FOREIGN for r in st if foreign(r, st[r]['x'], st[r]['y'], cur[r])) + sum(W_FOREIGN for r in st if blocked(r))

    import os as _os
    if _os.environ.get('DBG'):
        for r in _os.environ['DBG'].split(','):
            es = sorted((energy(r, c), c[0], c[1], c[2]) for c in cands[r])
            for c in cands[r][::max(1, len(cands[r]) // 6)]:
                log(f'   cand {c[0]:.1f},{c[1]:.1f},{c[2]} hit ' + ' '.join(f'{o}:{pair_pen(c[3], cur[o])[1]:.2f}' for o in near[r] if pair_pen(c[3], cur[o])[1] < HARD_GAP))
            hc = sorted((len([o for o in near[r] if pair_pen(c[3], cur[o])[1] < HARD_GAP]), c[0], c[1], c[2], tuple(o for o in near[r] if pair_pen(c[3], cur[o])[1] < HARD_GAP)) for c in cands[r])
            log('   fewest hits ' + str(hc[:8]))
            log(f'{r} now {energy(r, (st[r]["x"], st[r]["y"], st[r]["a"], cur[r])):.2f} at {st[r]["x"]:.2f},{st[r]["y"]:.2f} cands {len(cands[r])} best {es[:4]}')
    def eject(r, rng, depth=3):
        """an ejection chain for a label with no free place (a label that moved with its part): put it on a random place that
        conflicts with at most two labels, then move each of those to a place of its own, the chain going on to `depth` levels;
        undone as a whole when it does not end clear"""
        saved = {q: (st[q]['x'], st[q]['y'], st[q]['a'], cur[q]) for q in st}

        def undo():
            for q, (x, y, a, B) in saved.items():
                st[q].update(x=x, y=y, a=a)
                cur[q] = B

        def hits(r_, B):
            return [o for o in near[r_] if pair_pen(B, cur[o])[1] < HARD_GAP]

        def place(r_, d):
            cs = [c for c in cands[r_] if len(hits(r_, c[3])) <= (2 if d else 0)]
            if not cs:
                return False
            c = cs[int(rng.integers(len(cs)))]
            h = hits(r_, c[3])
            st[r_].update(x=c[0], y=c[1], a=c[2])
            cur[r_] = c[3]
            return all(place(o, d - 1) for o in h)

        if not place(r, depth):
            undo()

    rng = np.random.default_rng(seed)
    best, best_s = total(), {r: (s_['x'], s_['y'], s_['a'], cur[r]) for r, s_ in st.items()}
    log(f'start energy {best:.1f}')
    for cyc in range(CYCLES):
        for sw in range(SWEEPS):
            T = T0 * (T1 / T0) ** (sw / (SWEEPS - 1))
            bad = troubled()
            if not bad:
                break
            act = [r for r in st if any(math.hypot(st[r]['x'] - st[q]['x'], st[r]['y'] - st[q]['y']) < REACH for q in bad)]
            for r in act:
                cs = cands[r]
                if not cs:
                    continue
                if blocked(r) and rng.random() < 0.3:
                    eject(r, rng)
                    continue
                e0 = energy(r, (st[r]['x'], st[r]['y'], st[r]['a'], cur[r])) + (W_FOREIGN if blocked(r) else 0.0)
                if rng.random() < 0.6:
                    loc = [q for q in cs if abs(q[0] - st[r]['x']) < 3.0 and abs(q[1] - st[r]['y']) < 3.0] or cs
                    c = loc[int(rng.integers(len(loc)))]
                else:
                    c = cs[int(rng.integers(len(cs)))]
                d = energy(r, c) - e0
                if d <= 0 or (d < 1e8 and rng.random() < math.exp(-d / T)):
                    st[r].update(x=c[0], y=c[1], a=c[2])
                    cur[r] = c[3]
            t = total()
            if t < best - 1e-9:
                best, best_s = t, {r: (s_['x'], s_['y'], s_['a'], cur[r]) for r, s_ in st.items()}
        log(f'  cycle {cyc}: energy {total():.2f} best {best:.2f}')
        if best == 0:
            break
    for r, (x, y, a, B) in best_s.items():
        st[r].update(x=x, y=y, a=a)
        cur[r] = B
    # revert: a label goes back exactly where it was when that is no worse than where it ended up
    for _ in range(3):
        for r in st:
            o = (st[r]['x0'], st[r]['y0'], st[r]['a0'], bx(st[r], st[r]['x0'], st[r]['y0'], st[r]['a0']))
            if (st[r]['x'], st[r]['y'], st[r]['a']) != o[:3] and pair_energy_only(r, o) <= pair_energy_only(r, (st[r]['x'], st[r]['y'], st[r]['a'], cur[r])) + 1e-9 \
                    and all(pair_pen(o[3], cur[q])[1] >= HARD_GAP for q in near[r]) and not blocked(r, o[3]):
                st[r].update(x=o[0], y=o[1], a=o[2])
                cur[r] = o[3]
    # polish: a label already clear goes back toward where it was while it stays clear
    for _ in range(6):
        for r in st:
            e_here = energy(r, (st[r]['x'], st[r]['y'], st[r]['a'], cur[r]))
            for c in sorted(cands[r], key=lambda c: math.hypot(c[0] - st[r]['x0'], c[1] - st[r]['y0'])):
                if math.hypot(c[0] - st[r]['x0'], c[1] - st[r]['y0']) >= math.hypot(st[r]['x'] - st[r]['x0'], st[r]['y'] - st[r]['y0']) - 1e-9:
                    break
                if energy(r, c) <= e_here - W_DISP * 0 and pair_energy_only(r, c) <= pair_energy_only(r, (st[r]['x'], st[r]['y'], st[r]['a'], cur[r])) + 1e-9:
                    st[r].update(x=c[0], y=c[1], a=c[2])
                    cur[r] = c[3]
                    break
    for r in st:
        if blocked(r):
            log(f'  still on a foreign pad, via or silk: {r}')
        for o in near[r]:
            if o > r and pair_pen(cur[r], cur[o])[0] > 0 and pair_pen(cur[r], cur[o])[0] >= W_ONE:
                log(f'  still one label: {r} {o}')
        if foreign(r, st[r]['x'], st[r]['y'], cur[r]):
            log(f'  still foreign: {r}')
    return {r: (s['x'], s['y'], s['a']) for r, s in st.items() if (s['x'], s['y'], s['a']) != (s['x0'], s['y0'], s['a0'])}


def main(argv):
    path = argv[0]
    out = argv[argv.index('--write') + 1]
    b = boardio.read_board(path)
    text = open(path).read()
    seed = int(argv[argv.index('--seed') + 1]) if '--seed' in argv else 3
    moves = run(b, text, seed=seed)
    print(len(moves), 'designators moved:', ' '.join(sorted(moves)))
    open(out, 'w').write(pd.apply_moves(text, b, moves))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
