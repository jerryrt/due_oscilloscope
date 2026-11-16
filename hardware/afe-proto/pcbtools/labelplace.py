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


LABMODES = {}            # {ref: 'E' | 'W'}: a designator beside the part (silkread rules 2a / 2b) instead of above it


class P:
    """one part's constants"""
    def __init__(self, ref, r, free, nolabel=False):
        self.ref = ref
        self.free = free
        self.nolabel_pair = False
        self.rx0, self.ry0, self.rx1, self.ry1 = r
        self.w = 0.0 if nolabel else len(ref) * silkread.CHAR_ADV * LABEL_H
        self.cx = (self.rx0 + self.rx1) / 2
        self.lx0, self.lx1 = self.cx - self.w / 2, self.cx + self.w / 2
        self.ly0, self.ly1 = (self.ry1, self.ry1) if nolabel else (self.ry1 + GAP, self.ry1 + GAP + LABEL_H)
        m = LABMODES.get(ref)
        if m and not nolabel:
            cy = (self.ry0 + self.ry1) / 2
            self.ly0, self.ly1 = cy - LABEL_H / 2, cy + LABEL_H / 2
            if m == 'E':
                self.lx0 = self.rx1 + GAP; self.lx1 = self.lx0 + self.w
            else:
                self.lx1 = self.rx0 - GAP; self.lx0 = self.lx1 - self.w


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


def _pair_depth(pi, xi, yi, pj, xj, yj):
    """how far the pair violates: the sum over its four shape pairs of the shortest way out (0 for a pair that is clear), plus one so that a violation never costs less than a count"""
    Ci, Li = _shapes(pi, xi, yi)
    Cj, Lj = _shapes(pj, xj, yj)
    d = 0.0
    for a, b, m in ((Ci, Cj, CC), (Li, Cj, LC), (Lj, Ci, LC), (Li, Lj, LL)):
        px, py = _pen(a, b, m - 0.05)
        if px > 0 and py > 0:
            d += min(px, py)
    return d + 1.0 if d > 0 else 0.0


def _bb(p, x, y):
    return (x + min(p.rx0, p.lx0), y + p.ry0, x + max(p.rx1, p.lx1), y + p.ly1)


def _obst_bad(p, x, y, q, tol=0.0):
    if len(q) > 4 and p.ref in q[4]:
        return False                                   # an obstacle may name the parts it does not apply to (its fifth element)
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


def solve(refs, rel, target, fence, anchors, lock_x, obstacles, rounds=40, flips=25, verbose=False, nolabel=(), caps=(), spans=(), weights=None, xmin=None):
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
        cur = _lp(parts, t, rect, lock_x, pair_rules, obst_rules, obstacles, caps, spans, idx, weights, xmin)
    def snapped(c):
        return {r: (round(float(np.round(c[i, 0] / SNAP) * SNAP), 3), round(float(np.round(c[i, 1] / SNAP) * SNAP), 3)) for i, r in enumerate(refs)}
    out = snapped(cur)
    bad = violations(parts, out, rect, anchors, obstacles, caps, spans)
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
        cur = _lp(parts, t, rect, lock_x, pair_rules, obst_rules, obstacles, caps, spans, idx, weights, xmin)
        for i in range(n):
            for j in range(i + 1, n):
                if (parts[i].free or parts[j].free) and (i, j) not in pair_rules and _pair_bad(parts[i], *cur[i], parts[j], *cur[j]):
                    pair_rules[(i, j)] = _choose(parts[i], *cur[i], parts[j], *cur[j])
        cur = _lp(parts, t, rect, lock_x, pair_rules, obst_rules, obstacles, caps, spans, idx, weights, xmin)
        out = snapped(cur)
        bad = violations(parts, out, rect, anchors, obstacles, caps, spans)
        if verbose:
            print('flip round', flip, 'violations', len(bad))
        if len(bad) < best[0]:
            best = (len(bad), out, bad)
    return best[1], best[2]


def _lp(parts, t, rect, lock_x, pair_rules, obst_rules, obstacles, caps, spans, idx, weights, xmin):
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

    # hard-ish distance caps: pad a of part ia within D of pad b of part ib (an octagon round the circle), and net spans
    CAPW = 5000.0
    extra = 0
    xtra_rows = []     # (coeffs, rhs, weight) with variable ids that may refer to extra columns, filled after nf, nv known

    def comb(ref, pad, axis):
        """(coefficients, constant) of the pad's coordinate: position variable plus the pad offset, or a constant for a fixed part"""
        i = idx[ref]
        off = pad[0 if axis == 'x' else 1]
        if parts[i].free:
            return {(X if axis == 'x' else Y)(i): 1.0}, off
        return {}, t[i, 0 if axis == 'x' else 1] + off

    for (ra, pa, rb, pb, D) in caps:
        if not (parts[idx[ra]].free or parts[idx[rb]].free):
            continue
        cxa, ka = comb(ra, pa, 'x')
        cxb, kb = comb(rb, pb, 'x')
        cya, la = comb(ra, pa, 'y')
        cyb, lb = comb(rb, pb, 'y')
        dxc = dict(cxa)
        for v, c in cxb.items():
            dxc[v] = dxc.get(v, 0.0) - c
        dyc = dict(cya)
        for v, c in cyb.items():
            dyc[v] = dyc.get(v, 0.0) - c
        kx, ky = ka - kb, la - lb
        for sx in (1, -1):
            xtra_rows.append(({v: sx * c for v, c in dxc.items()}, D - sx * kx, CAPW))
        for sy in (1, -1):
            xtra_rows.append(({v: sy * c for v, c in dyc.items()}, D - sy * ky, CAPW))
        for sx in (1, -1):
            for sy in (1, -1):
                co = {}
                for v, c in dxc.items():
                    co[v] = co.get(v, 0.0) + sx * c
                for v, c in dyc.items():
                    co[v] = co.get(v, 0.0) + sy * c
                xtra_rows.append((co, 1.38 * D - sx * kx - sy * ky, CAPW))
    for (members, Wx, Wy) in spans:
        for axis, W in (('x', Wx), ('y', Wy)):
            vmax, vmin = 4 * nf + extra, 4 * nf + extra + 1
            extra += 2
            for ref, pad in members:
                co, k = comb(ref, pad, axis)
                c1 = dict(co)
                c1[vmax] = c1.get(vmax, 0.0) - 1.0          # coordinate <= max
                xtra_rows.append((c1, -k, CAPW))
                c2 = {v: -c for v, c in co.items()}
                c2[vmin] = c2.get(vmin, 0.0) + 1.0           # min <= coordinate
                xtra_rows.append((c2, k, CAPW))
            xtra_rows.append(({vmax: 1.0, vmin: -1.0}, W, CAPW))
    for co, rhs, w in xtra_rows:
        rows.append((co, rhs, w))
    ns = len(rows)
    nv = 4 * nf + extra + ns
    A = lil_matrix((ns + 4 * nf, nv))
    ub = np.zeros(ns + 4 * nf)
    for r, (co, rhs, _) in enumerate(rows):
        for v, c in co.items():
            A[r, v] = c
        A[r, 4 * nf + extra + r] = -1.0
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
    if weights:
        for k, i in enumerate(fi):
            w = weights.get(parts[i].ref, 1.0)
            c[2 * nf + k] = w
            c[3 * nf + k] = w
    c[4 * nf + extra:] = SLACK
    for r, (co, rhs, w) in enumerate(rows):
        if w is not True and w is not False:
            c[4 * nf + extra + r] = w
    bounds = []
    for k, i in enumerate(fi):
        p = parts[i]
        q = rect[i]
        bounds.append((max(q[0] - p.rx0, q[0] + LM - p.lx0, INTERIOR[0] - p.lx0), min(q[2] - p.rx1, q[2] - LM - p.lx1, INTERIOR[2] - p.lx1)))
    for k, i in enumerate(fi):
        p = parts[i]
        q = rect[i]
        bounds.append((q[1] - p.ry0, min(q[3] - p.ry1, q[3] - LM - p.ly1, INTERIOR[3] - p.ly1)))
    bounds += [(0, None)] * (2 * nf) + [(None, None)] * extra + [(0, None)] * ns
    for k, i in enumerate(fi):
        if parts[i].ref in LOCK:
            bounds[k] = (t[i, 0], t[i, 0])
        if xmin and parts[i].ref in xmin:
            bounds[k] = (max(bounds[k][0], xmin[parts[i].ref]), bounds[k][1])
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


def cap_bad(caps, spans, pos, tol=0.05):
    out = []
    for (ra, pa, rb, pb, D) in caps:
        dx = pos[ra][0] + pa[0] - pos[rb][0] - pb[0]
        dy = pos[ra][1] + pa[1] - pos[rb][1] - pb[1]
        if (dx * dx + dy * dy) ** 0.5 > D + tol:
            out.append(f'cap {ra}-{rb}: {(dx * dx + dy * dy) ** 0.5:.2f} > {D:.2f}')
    for k, (members, Wx, Wy) in enumerate(spans):
        xs = [pos[r][0] + pad[0] for r, pad in members]
        ys = [pos[r][1] + pad[1] for r, pad in members]
        if max(xs) - min(xs) > Wx + tol or max(ys) - min(ys) > Wy + tol:
            out.append(f'span {k}: {max(xs) - min(xs):.2f} x {max(ys) - min(ys):.2f} > {Wx:.2f} x {Wy:.2f}')
    return out


def violations(parts, pos, rect, anchors, obstacles, caps=(), spans=()):
    bad = []
    n = len(parts)
    for i in range(n):
        for j in range(i + 1, n):
            if not (parts[i].free or parts[j].free) and not parts[i].nolabel_pair:
                pass
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
    return bad + cap_bad(caps, spans, pos)


def polish(refs, rel, pos, fence, anchors, lock_x, obstacles, nolabel=(), rounds=6, seed=0, caps=(), spans=()):
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

    def capcost(r, p):
        old = pos[r]
        pos[r] = p
        n = 0
        for c in caps:
            if r in (c[0], c[2]):
                n += 1 if cap_bad([c], [], pos) else 0
        for sp in spans:
            if any(m[0] == r for m in sp[0]):
                n += 1 if cap_bad([], [sp], pos) else 0
        pos[r] = old
        return 12 * n

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
        n += capcost(r, p)
        return n

    steps = [0.25, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0]
    rng = np.random.default_rng(seed)
    for _ in range(rounds):
        improved = False
        bad = violations(parts, pos, rect, anchors, obstacles, caps, spans)
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
    return pos, violations(parts, pos, rect, anchors, obstacles, caps, spans)


def anneal(refs, rel, pos, target, fence, anchors, lock_x, obstacles, nolabel=(), iters=30000, seed=0, w_disp=0.02, t0=0.6, caps=(), spans=(), weights=None, xmin=None, nets=(), w_net=0.0, align=None, w_align=0.0, p_snap=0.0):
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

    def capcost(r, p):
        old = pos[r]
        pos[r] = p
        n = 0
        for c in caps:
            if r in (c[0], c[2]):
                n += 1 if cap_bad([c], [], pos) else 0
        for sp in spans:
            if any(m[0] == r for m in sp[0]):
                n += 1 if cap_bad([], [sp], pos) else 0
        pos[r] = old
        return 12 * n


    idx_of = {q.ref: k for k, q in enumerate(parts)}

    # D31 alignment (pcbtools/align.py): a two-pin passive shares its origin's y or x with a passive of its block and orientation within REACH, or sits on a pin line
    AREACH, APIN, ATOL = 8.0, 4.0, 0.05
    amates = {}
    if align:
        pas = align['passives']
        for r1, (b1, o1) in pas.items():
            if r1 not in idx_of:
                continue
            amates[r1] = [r2 for r2, (b2, o2) in pas.items() if r2 != r1 and b2 == b1 and o2 == o1 and r2 in idx_of]
        npads = align['pads']

    def aligned(r1, ovr=None):
        q1 = ovr if ovr is not None else pos[r1]
        for r2 in amates.get(r1, ()):
            q2 = pos[r2]
            if abs(q2[0] - q1[0]) ** 2 + abs(q2[1] - q1[1]) ** 2 <= AREACH ** 2 and (abs(q2[1] - q1[1]) <= ATOL or abs(q2[0] - q1[0]) <= ATOL):
                return True
        for rq, lst in npads.items():
            pq = pos[rq]
            for dx, dy in lst:
                px, py = pq[0] + dx, pq[1] + dy
                if (px - q1[0]) ** 2 + (py - q1[1]) ** 2 <= APIN ** 2 and (abs(px - q1[0]) <= ATOL or abs(py - q1[1]) <= ATOL):
                    return True
        return False

    def aligncost(r, p):
        if not align or w_align == 0:
            return 0.0
        old = pos[r]
        pos[r] = p
        n = 0
        if r in amates:
            n += 0 if aligned(r) else 1
            for m in amates[r]:
                n += 0 if aligned(m) else 1
        else:
            for m in {m for m2 in amates for m in [m2] if r in amates.get(m2, ())} if False else ():
                pass
            for m in amates:
                if any(abs(pos[r][0] + dx - pos[m][0]) < APIN + 1 and abs(pos[r][1] + dy - pos[m][1]) < APIN + 1 for dx, dy in npads.get(r, ())):
                    n += 0 if aligned(m) else 1
        pos[r] = old
        return w_align * n

    netsof = {}
    for ni, (members, w) in enumerate(nets):
        for m in members:
            netsof.setdefault(m[0], []).append(ni)

    def hpwl(ni, r=None, p=None):
        members, w = nets[ni]
        xs, ys = [], []
        for ref, pad in members:
            q = p if ref == r else pos[ref]
            xs.append(q[0] + pad[0])
            ys.append(q[1] + pad[1])
        return w * ((max(xs) - min(xs)) + (max(ys) - min(ys)))

    def netcost(r, p):
        return w_net * sum(hpwl(ni, r, p) for ni in netsof.get(r, ()))

    def cost(r, p):
        i = idx[r]
        n = 0.0
        for j, o in enumerate(parts):
            if j != i and (parts[i].free or o.free):
                n += _pair_depth(parts[i], *p, o, *pos[o.ref])
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
        n += capcost(r, p)
        n += netcost(r, p)
        n += aligncost(r, p)
        if xmin and r in xmin and p[0] < xmin[r]:
            n += 2
        t = target[r]
        wt = (weights or {}).get(r, 1.0)
        return n + w_disp * wt * (abs(p[0] - t[0]) + abs(p[1] - t[1]))

    free = [r for r in refs if parts[idx[r]].free]
    bestv = None
    for it in range(iters):
        if it % 200 == 0:
            bad = violations(parts, pos, rect, anchors, obstacles, caps, spans)
            ac = sum(0 if aligned(q) else 1 for q in amates) if align else 0
            sc = (len(bad), ac, sum((weights or {}).get(q, 1.0) * (abs(pos[q][0] - target[q][0]) + abs(pos[q][1] - target[q][1])) for q in pos))
            if bestv is None or sc < bestv[2]:
                bestv = (dict(pos), bad, sc)
            hot = sorted({r.strip().split(' ')[0] for v in bad for r in v.replace(':', '/').split('/')[:2] if r.strip().split(' ')[0] in idx})
        temp = t0 * (1 - it / iters)
        r = hot[rng.integers(len(hot))] if rng.random() < 0.7 else free[rng.integers(len(free))]
        if not parts[idx[r]].free:
            continue
        s = rng.choice([0.1, 0.25, 0.5, 1.0, 2.0])
        dx, dy = (rng.normal(0, s), rng.normal(0, s))
        if r in lock_x:
            dx = 0.0
        p = (round(round((pos[r][0] + dx) / SNAP) * SNAP, 3), round(round((pos[r][1] + dy) / SNAP) * SNAP, 3))
        if align and r in amates and amates[r] and rng.random() < p_snap:
            m = amates[r][rng.integers(len(amates[r]))]
            if rng.random() < 0.5:
                p = (pos[r][0], pos[m][1])
            elif r not in lock_x:
                p = (pos[m][0], pos[r][1])
        elif align and r in amates and rng.random() < p_snap * 0.4:
            cands = [(pos[q][0] + dx_, pos[q][1] + dy_) for q, lst in npads.items() for dx_, dy_ in lst if (pos[q][0] + dx_ - pos[r][0]) ** 2 + (pos[q][1] + dy_ - pos[r][1]) ** 2 <= 16.0]
            if cands:
                c = cands[rng.integers(len(cands))]
                p = (pos[r][0], round(c[1], 3)) if rng.random() < 0.5 or r in lock_x else (round(c[0], 3), pos[r][1])
        d = cost(r, p) - cost(r, pos[r])
        if d <= 0 or rng.random() < np.exp(-d / max(temp, 1e-3)):
            pos[r] = p
    bad = violations(parts, pos, rect, anchors, obstacles, caps, spans)
    ac = sum(0 if aligned(q) else 1 for q in amates) if align else 0
    sc = (len(bad), ac, sum((weights or {}).get(q, 1.0) * (abs(pos[q][0] - target[q][0]) + abs(pos[q][1] - target[q][1])) for q in pos))
    if bestv is None or sc < bestv[2]:
        bestv = (dict(pos), bad, sc)
    return bestv[0], bestv[1]
