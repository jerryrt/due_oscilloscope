"""Placement with a label zone above every part (D30, the owner's convention of 2026-11-15; pcbtools/silkread.py rules 1-3).

    solve(refs, rel, target, fence, anchors, lock_x, obstacles) -> ({ref: (x, y)}, [violation strings])

Takes a placement as the starting point (`target`: each part's origin, rotations kept, `rel` the courtyard box minus the origin) and moves
the parts the least it can (sum of |dx| + |dy|, a linear programme) so that every part has, centred just above its courtyard, a free box for
its designator (LABEL_H high, CHAR_ADV per character as silkread reads it), and lies inside its fence. A part's shapes are its courtyard C
and its label box L; between parts i and j

    C_i / C_j  at least CC apart     L_i / C_j  at least LC apart     L_i / L_j  at least LL apart (silkread's LABEL_GAP and a tolerance)

and neither C_i nor L_i lies on a fixed obstacle. Each close pair is separated along one axis, chosen from where the parts are, in rounds:
solve the programme for the pairs found so far, find the pairs that still violate, add them, until none do. The programme is elastic (a
violated constraint costs a slack) so that a block that does not fit is reported, with the pairs that did not fit, and not refused.
"""
import numpy as np
from scipy.optimize import linprog
from scipy.sparse import lil_matrix

from . import silkread

CC = 0.25
LC = 0.15
LL = silkread.LABEL_GAP + 0.05
GAP = 0.2                # label bottom above the courtyard top
LABEL_H = 1.0
SNAP = 0.05
SLACK = 200.0


class P:
    """one part's constants"""
    def __init__(self, ref, r, free, nolabel=False):
        self.ref = ref
        self.free = free
        self.rx0, self.ry0, self.rx1, self.ry1 = r
        self.w = 0.0 if nolabel else len(ref) * silkread.CHAR_ADV * LABEL_H
        self.cx = (self.rx0 + self.rx1) / 2
        self.lx0, self.lx1 = self.cx - self.w / 2, self.cx + self.w / 2
        self.ly0, self.ly1 = (self.ry1, self.ry1) if nolabel else (self.ry1 + GAP, self.ry1 + GAP + LABEL_H)


def _shapes(p, x, y):
    return (x + p.rx0, y + p.ry0, x + p.rx1, y + p.ry1), (x + p.lx0, y + p.ly0, x + p.lx1, y + p.ly1)


def _pen(a, b, m):
    px = min(a[2] + m - b[0], b[2] + m - a[0])
    py = min(a[3] + m - b[1], b[3] + m - a[1])
    return px, py


def _pair_bad(pi, xi, yi, pj, xj, yj, tol=0.0):
    Ci, Li = _shapes(pi, xi, yi)
    Cj, Lj = _shapes(pj, xj, yj)
    for a, b, m in ((Ci, Cj, CC), (Li, Cj, LC), (Lj, Ci, LC), (Li, Lj, LL)):
        px, py = _pen(a, b, m - tol)
        if px > 0 and py > 0:
            return True
    return False


def _bb(p, x, y):
    return (x + min(p.rx0, p.lx0), y + p.ry0, x + max(p.rx1, p.lx1), y + p.ly1)


def _obst_bad(p, x, y, q, tol=0.0):
    C, L = _shapes(p, x, y)
    for a in (C, L):
        px, py = _pen(a, q, LC - tol)
        if px > 0 and py > 0:
            return True
    return False


def _choose(pi, xi, yi, pj, xj, yj):
    """('x' | 'y', i first?) for a violating pair: the axis along which the bounding boxes (grown by the largest margin) overlap least"""
    a, b = _bb(pi, xi, yi), _bb(pj, xj, yj)
    px, py = _pen(a, b, LL)
    xlocked = (pi.ref in LOCK and pi.free) or (pj.ref in LOCK and pj.free)
    if px <= py and not xlocked:
        return 'x', (a[0] + a[2]) <= (b[0] + b[2])
    return 'y', (a[1] + a[3]) <= (b[1] + b[3])


def solve(refs, rel, target, fence, anchors, lock_x, obstacles, rounds=40, flips=25, verbose=False, nolabel=()):
    LOCK.clear()
    LOCK.update(lock_x)
    n = len(refs)
    parts = [P(r, rel[r], r not in anchors, r in nolabel) for r in refs]
    t = np.array([target[r] for r in refs], float)
    cur = t.copy()
    idx = {r: i for i, r in enumerate(refs)}
    pair_rules = {}            # (i, j) -> (axis, i first)
    obst_rules = {}            # (i, k) -> side 'l' | 'r' | 'b' | 'a'
    rect = {}
    for i, p in enumerate(parts):
        if not p.free:
            continue
        best = None
        for q in fence[p.ref]:
            bb = _bb(p, t[i, 0], t[i, 1])
            d = max(q[0] - bb[0], 0) + max(bb[2] - q[2], 0) + max(q[1] - bb[1], 0) + max(bb[3] - q[3], 0)
            if best is None or d < best[0]:
                best = (d, q)
        rect[i] = best[1]
    for rnd in range(rounds):
        new = 0
        for i in range(n):
            for j in range(i + 1, n):
                if not (parts[i].free or parts[j].free) or (i, j) in pair_rules:
                    continue
                if _pair_bad(parts[i], *cur[i], parts[j], *cur[j]):
                    pair_rules[(i, j)] = _choose(parts[i], *cur[i], parts[j], *cur[j])
                    new += 1
            for k, q in enumerate(obstacles):
                if parts[i].free and (i, k) not in obst_rules and _obst_bad(parts[i], *cur[i], q):
                    p = parts[i]
                    C, L = _shapes(p, *cur[i])
                    a = (min(C[0], L[0]), C[1], max(C[2], L[2]), L[3])
                    opts = {'l': a[2] + LC - q[0], 'r': q[2] + LC - a[0], 'b': a[3] + LC - q[1], 'a': q[3] + LC - a[1]}
                    obst_rules[(i, k)] = min(opts, key=opts.get)
                    new += 1
        if verbose:
            print('round', rnd, 'new rules', new)
        if rnd and not new:
            break
        cur = _lp(parts, t, rect, lock_x, pair_rules, obst_rules, obstacles)
    def snapped(c):
        return {r: (round(float(np.round(c[i, 0] / SNAP) * SNAP), 3), round(float(np.round(c[i, 1] / SNAP) * SNAP), 3)) for i, r in enumerate(refs)}
    out = snapped(cur)
    bad = violations(parts, out, rect, anchors, obstacles)
    best = (len(bad), out, bad)
    rng = np.random.default_rng(1)
    for flip in range(flips):
        # a pair that still violates is separated the other way: along the other axis, in the order the parts are in on it
        changed = 0
        for v in bad:
            if '/' not in v:
                continue
            a, b = v.split('/')
            i, j = sorted((idx[a], idx[b]))
            if (i, j) not in pair_rules or rng.random() < 0.3:
                continue
            axis, _ = pair_rules[(i, j)]
            other = 'y' if axis == 'x' else 'x'
            if other == 'x' and (parts[i].ref in LOCK or parts[j].ref in LOCK):
                continue
            k = 0 if other == 'x' else 1
            ci = cur[i, k] + (parts[i].rx0 + parts[i].rx1) / 2
            cj = cur[j, k] + (parts[j].rx0 + parts[j].rx1) / 2 if k == 0 else cur[j, k] + (parts[j].ry0 + parts[j].ry1) / 2
            if k == 1:
                ci = cur[i, k] + (parts[i].ry0 + parts[i].ry1) / 2
            pair_rules[(i, j)] = (other, ci <= cj)
            changed += 1
        if not changed:
            break
        cur = _lp(parts, t, rect, lock_x, pair_rules, obst_rules, obstacles)
        for i in range(n):
            for j in range(i + 1, n):
                if (parts[i].free or parts[j].free) and (i, j) not in pair_rules and _pair_bad(parts[i], *cur[i], parts[j], *cur[j]):
                    pair_rules[(i, j)] = _choose(parts[i], *cur[i], parts[j], *cur[j])
        cur = _lp(parts, t, rect, lock_x, pair_rules, obst_rules, obstacles)
        out = snapped(cur)
        bad = violations(parts, out, rect, anchors, obstacles)
        if verbose:
            print('flip round', flip, 'violations', len(bad))
        if len(bad) < best[0]:
            best = (len(bad), out, bad)
    return best[1], best[2]


def _lp(parts, t, rect, lock_x, pair_rules, obst_rules, obstacles):
    n = len(parts)
    fi = [i for i, p in enumerate(parts) if p.free]
    pos = {i: k for k, i in enumerate(fi)}
    nf = len(fi)
    # variables: x (nf), y (nf), ux (nf), uy (nf) with |x - tx| <= ux, then one slack per rule
    rows = []     # (coeffs {var: c}, rhs)  meaning sum c*var <= rhs

    def X(i): return pos[i]
    def Y(i): return nf + pos[i]

    def add(co, rhs, slack=True):
        rows.append((co, rhs, slack))

    def sep(axis, i, ai, j, aj, m):
        """(pos_i + ai) + m <= (pos_j + aj) along `axis`; positions are variables for free parts, constants for the fixed"""
        co = {}
        rhs = aj - ai - m
        vi = (X if axis == 'x' else Y)
        ci = parts[i]
        cj = parts[j]
        if ci.free:
            co[vi(i)] = co.get(vi(i), 0.0) + 1.0
        else:
            rhs -= t[i, 0 if axis == 'x' else 1]
        if cj.free:
            co[vi(j)] = co.get(vi(j), 0.0) - 1.0
        else:
            rhs += t[j, 0 if axis == 'x' else 1]
        add(co, rhs)

    for (i, j), (axis, ifirst) in pair_rules.items():
        if not ifirst:
            i, j = j, i
        a, b = parts[i], parts[j]
        if axis == 'x':
            sep('x', i, a.rx1, j, b.rx0, CC)
            sep('x', i, a.lx1, j, b.rx0, LC)
            sep('x', i, a.rx1, j, b.lx0, LC)
            sep('x', i, a.lx1, j, b.lx0, LL)
        else:
            sep('y', i, a.ry1, j, b.ry0, CC)
            sep('y', i, a.ly1, j, b.ry0, LC)                   # j clears i's label box
            sep('y', i, a.ly1, j, b.ly0, LL)                    # and the labels stay apart
    for (i, k), side in obst_rules.items():
        q = obstacles[k]
        p = parts[i]
        xl, xr = min(p.rx0, p.lx0), max(p.rx1, p.lx1)
        if side == 'l':
            add({X(i): 1.0}, q[0] - LC - xr)
        elif side == 'r':
            add({X(i): -1.0}, -(q[2] + LC - xl))
        elif side == 'b':
            add({Y(i): 1.0}, q[1] - LC - p.ly1)
        else:
            add({Y(i): -1.0}, -(q[3] + LC - p.ry0))
    ns = len(rows)
    nv = 4 * nf + ns
    A = lil_matrix((ns + 4 * nf, nv))
    ub = np.zeros(ns + 4 * nf)
    for r, (co, rhs, _) in enumerate(rows):
        for v, c in co.items():
            A[r, v] = c
        A[r, 4 * nf + r] = -1.0
        ub[r] = rhs
    r0 = ns
    for k, i in enumerate(fi):
        for off, (var, uvar, tv) in enumerate(((k, 2 * nf + k, t[i, 0]), (nf + k, 3 * nf + k, t[i, 1]))):
            A[r0, var] = 1.0
            A[r0, uvar] = -1.0
            ub[r0] = tv
            r0 += 1
            A[r0, var] = -1.0
            A[r0, uvar] = -1.0
            ub[r0] = -tv
            r0 += 1
    c = np.zeros(nv)
    c[2 * nf:4 * nf] = 1.0
    c[4 * nf:] = SLACK
    bounds = []
    for k, i in enumerate(fi):
        p = parts[i]
        q = rect[i]
        bounds.append((max(q[0] - p.rx0, q[0] + LM - p.lx0, INTERIOR[0] - p.lx0), min(q[2] - p.rx1, q[2] - LM - p.lx1, INTERIOR[2] - p.lx1)))
    for k, i in enumerate(fi):
        p = parts[i]
        q = rect[i]
        bounds.append((q[1] - p.ry0, min(q[3] - p.ry1, q[3] - LM - p.ly1, INTERIOR[3] - p.ly1)))
    bounds += [(0, None)] * (2 * nf + ns)
    for k, i in enumerate(fi):
        if parts[i].ref in LOCK:
            bounds[k] = (t[i, 0], t[i, 0])
    res = linprog(c, A_ub=A.tocsr(), b_ub=ub, bounds=bounds, method='highs')
    if res.status != 0:
        raise RuntimeError('linprog: ' + res.message)
    out = t.copy()
    for k, i in enumerate(fi):
        out[i, 0], out[i, 1] = res.x[k], res.x[nf + k]
    return out


LOCK = set()
LM = 0.0                 # a label keeps this far inside its block's outline (silkread: a designator touching a board silk line is a finding)
INTERIOR = (17.5, 4.6, 92.0, 48.7)      # a label may leave its block's rectangle (traces run under it), not this one


def violations(parts, pos, rect, anchors, obstacles):
    bad = []
    n = len(parts)
    for i in range(n):
        for j in range(i + 1, n):
            if not (parts[i].free or parts[j].free):
                continue
            if _pair_bad(parts[i], *pos[parts[i].ref], parts[j], *pos[parts[j].ref], tol=0.05):
                bad.append(f'{parts[i].ref}/{parts[j].ref}')
        for k, q in enumerate(obstacles):
            if parts[i].free and _obst_bad(parts[i], *pos[parts[i].ref], q, tol=0.05):
                bad.append(f'{parts[i].ref}: on obstacle {k}')
        if i in rect:
            p = parts[i]
            C, L = _shapes(p, *pos[p.ref])
            q = rect[i]
            if not (q[0] - 0.01 <= C[0] and q[1] - 0.01 <= C[1] and C[2] <= q[2] + 0.01 and C[3] <= q[3] + 0.01):
                bad.append(f'{p.ref}: outside its fence')
            if not (q[0] + LM - 0.01 <= L[0] and L[2] <= q[2] - LM + 0.01 and L[3] <= q[3] - LM + 0.01 and INTERIOR[0] - 0.01 <= L[0] and L[2] <= INTERIOR[2] + 0.01):
                bad.append(f'{p.ref}: label outside its outline')
    return bad


def polish(refs, rel, pos, fence, anchors, lock_x, obstacles, nolabel=(), rounds=6, seed=0):
    """hill-climb on the number of violations: shift one free part by a few steps along an axis and keep the move when the count falls (ties are
    kept when the part gets nearer the origin it had). pos {ref: (x, y)} -> (pos, violations)"""
    LOCK.clear()
    LOCK.update(lock_x)
    parts = [P(r, rel[r], r not in anchors, r in nolabel) for r in refs]
    idx = {r: i for i, r in enumerate(refs)}
    rect = {}
    for i, p in enumerate(parts):
        if p.free:
            x, y = pos[p.ref]
            bb = _bb(p, x, y)
            best = None
            for q in fence[p.ref]:
                d = max(q[0] - bb[0], 0) + max(bb[2] - q[2], 0) + max(q[1] - bb[1], 0) + max(bb[3] - q[3], 0)
                if best is None or d < best[0]:
                    best = (d, q)
            rect[i] = best[1]
    pos = dict(pos)

    def cost(r, p):
        """violations that involve part r with the others, at position p"""
        i = idx[r]
        n = 0
        for j, o in enumerate(parts):
            if j != i and (parts[i].free or o.free) and _pair_bad(parts[i], *p, o, *pos[o.ref], tol=0.05):
                n += 1
        for q in obstacles:
            if _obst_bad(parts[i], *p, q, tol=0.05):
                n += 1
        if i in rect:
            C, L = _shapes(parts[i], *p)
            q = rect[i]
            if not (q[0] - 0.01 <= C[0] and q[1] - 0.01 <= C[1] and C[2] <= q[2] + 0.01 and C[3] <= q[3] + 0.01):
                n += 1
            if not (q[0] + LM - 0.01 <= L[0] and L[2] <= q[2] - LM + 0.01 and L[3] <= q[3] - LM + 0.01):
                n += 1
        return n

    steps = [0.25, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0]
    rng = np.random.default_rng(seed)
    for _ in range(rounds):
        improved = False
        bad = violations(parts, pos, rect, anchors, obstacles)
        names = set()
        for v in bad:
            for r in v.replace(':', '/').split('/')[:2]:
                r = r.strip().split(' ')[0]
                if r in idx:
                    names.add(r)
        for r in sorted(names):
            if not parts[idx[r]].free:
                continue
            c0 = cost(r, pos[r])
            best = (c0, 0.0, pos[r])
            for dx, dy in [(s * a, s * b) for s in steps for a, b in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, 1), (1, -1), (-1, -1))]:
                if r in lock_x and dx:
                    continue
                p = (round(pos[r][0] + dx, 3), round(pos[r][1] + dy, 3))
                c = cost(r, p)
                if (c, abs(dx) + abs(dy)) < (best[0], best[1] if best[1] else 1e9) and c < best[0]:
                    best = (c, abs(dx) + abs(dy), p)
            if best[0] < c0:
                pos[r] = best[2]
                improved = True
        if not improved:
            break
    return pos, violations(parts, pos, rect, anchors, obstacles)


def anneal(refs, rel, pos, target, fence, anchors, lock_x, obstacles, nolabel=(), iters=30000, seed=0, w_disp=0.02, t0=0.6):
    """simulated annealing on (violations + w_disp * displacement from the target), one free part moved at a time; the parts in a violation are moved
    most. -> (best pos, its violations)"""
    LOCK.clear()
    LOCK.update(lock_x)
    parts = [P(r, rel[r], r not in anchors, r in nolabel) for r in refs]
    idx = {r: i for i, r in enumerate(refs)}
    rect = {}
    for i, p in enumerate(parts):
        if p.free:
            x, y = pos[p.ref]
            bb = _bb(p, x, y)
            best = None
            for q in fence[p.ref]:
                d = max(q[0] - bb[0], 0) + max(bb[2] - q[2], 0) + max(q[1] - bb[1], 0) + max(bb[3] - q[3], 0)
                if best is None or d < best[0]:
                    best = (d, q)
            rect[i] = best[1]
    pos = dict(pos)
    rng = np.random.default_rng(seed)

    def cost(r, p):
        i = idx[r]
        n = 0.0
        for j, o in enumerate(parts):
            if j != i and (parts[i].free or o.free) and _pair_bad(parts[i], *p, o, *pos[o.ref], tol=0.05):
                n += 1
        for q in obstacles:
            if _obst_bad(parts[i], *p, q, tol=0.05):
                n += 1
        if i in rect:
            C, L = _shapes(parts[i], *p)
            q = rect[i]
            if not (q[0] - 0.01 <= C[0] and q[1] - 0.01 <= C[1] and C[2] <= q[2] + 0.01 and C[3] <= q[3] + 0.01):
                n += 1
            if not (q[0] + LM - 0.01 <= L[0] and L[2] <= q[2] - LM + 0.01 and L[3] <= q[3] - LM + 0.01):
                n += 1
        t = target[r]
        return n + w_disp * (abs(p[0] - t[0]) + abs(p[1] - t[1]))

    free = [r for r in refs if parts[idx[r]].free]
    bestv = None
    for it in range(iters):
        if it % 200 == 0:
            bad = violations(parts, pos, rect, anchors, obstacles)
            if bestv is None or len(bad) < len(bestv[1]):
                bestv = (dict(pos), bad)
            if not bad:
                break
            hot = sorted({r.strip().split(' ')[0] for v in bad for r in v.replace(':', '/').split('/')[:2] if r.strip().split(' ')[0] in idx})
        temp = t0 * (1 - it / iters)
        r = hot[rng.integers(len(hot))] if rng.random() < 0.7 else free[rng.integers(len(free))]
        if not parts[idx[r]].free:
            continue
        s = rng.choice([0.25, 0.5, 1.0, 2.0, 3.0])
        dx, dy = (rng.normal(0, s), rng.normal(0, s))
        if r in lock_x:
            dx = 0.0
        p = (round(round((pos[r][0] + dx) / SNAP) * SNAP, 3), round(round((pos[r][1] + dy) / SNAP) * SNAP, 3))
        d = cost(r, p) - cost(r, pos[r])
        if d <= 0 or rng.random() < np.exp(-d / max(temp, 1e-3)):
            pos[r] = p
    bad = violations(parts, pos, rect, anchors, obstacles)
    if bestv is None or len(bad) <= len(bestv[1]):
        bestv = (dict(pos), bad)
    return bestv
