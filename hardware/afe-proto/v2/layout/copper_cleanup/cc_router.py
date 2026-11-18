"""octilinear chain router core (scratch): candidate paths of up to four legs between two terminals, validated against the copper around them"""
import math, itertools
import numpy as np

DIRS = [(math.cos(math.radians(a)), math.sin(math.radians(a))) for a in range(0, 360, 45)]
DIRS = [(round(x, 12), round(y, 12)) for x, y in DIRS]          # index k = angle 45 k degrees


def turn_ok(i, j):
    d = (j - i) % 8
    return d in (1, 2, 6, 7)                                   # a turn of 45 or 90 degrees, either way (not straight, not a hairpin)


def candidates(A, B, first_dirs, last_dirs, min_first, min_last, min_mid, max_legs=3, step=0.05, span=None):
    """[(cost, [(x, y) ...])]: octilinear paths from A to B whose first leg runs along one of first_dirs (indices) and whose last leg arrives along one of last_dirs
    (the direction travelled), legs at least min_first / min_mid / min_last long. Up to `max_legs` legs. `span`: how far (mm) a free leg may be sampled beyond the straight distance."""
    A = np.asarray(A, float); B = np.asarray(B, float)
    mf = (lambda d: min_first[d]) if isinstance(min_first, dict) else (lambda d: min_first)       # per first direction
    ml = (lambda d: min_last[d]) if isinstance(min_last, dict) else (lambda d: min_last)           # per arriving direction
    D = B - A
    dist = float(np.hypot(*D))
    out = []
    span = span if span is not None else max(2.0, dist)
    # n = 1
    for d1 in first_dirs:
        if d1 in last_dirs:
            u = np.array(DIRS[d1]); l = float(D @ u)
            if l >= max(mf(d1), ml(d1)) - 1e-9 and abs(D[0] * u[1] - D[1] * u[0]) < 1e-6:
                out.append((l, [tuple(A), tuple(B)]))
    # n = 2
    if max_legs >= 2:
        for d1 in first_dirs:
            for d2 in last_dirs:
                if not turn_ok(d1, d2):
                    continue
                M = np.array([DIRS[d1], DIRS[d2]]).T
                if abs(np.linalg.det(M)) < 1e-9:
                    continue
                l1, l2 = np.linalg.solve(M, D)
                if l1 >= mf(d1) - 1e-9 and l2 >= ml(d2) - 1e-9:
                    P = A + l1 * np.array(DIRS[d1])
                    out.append((l1 + l2 + 0.3, [tuple(A), tuple(P), tuple(B)]))
    # n = 3
    if max_legs >= 3:
        l2s = np.arange(min_mid, span + 1e-9, step)
        for d1 in first_dirs:
            for d3 in last_dirs:
                M = np.array([DIRS[d1], DIRS[d3]]).T
                if abs(np.linalg.det(M)) < 1e-9:
                    continue
                Mi = np.linalg.inv(M)
                for d2 in range(8):
                    if not (turn_ok(d1, d2) and turn_ok(d2, d3)):
                        continue
                    R = D[None, :] - l2s[:, None] * np.array(DIRS[d2])[None, :]
                    L13 = R @ Mi.T
                    ok = (L13[:, 0] >= mf(d1) - 1e-9) & (L13[:, 1] >= ml(d3) - 1e-9)
                    for k in np.flatnonzero(ok):
                        l1, l3, l2 = L13[k, 0], L13[k, 1], l2s[k]
                        P1 = A + l1 * np.array(DIRS[d1]); P2 = P1 + l2 * np.array(DIRS[d2])
                        out.append((l1 + l2 + l3 + 0.6, [tuple(A), tuple(P1), tuple(P2), tuple(B)]))
    # n = 4
    if max_legs >= 4:
        s2 = np.arange(min_mid, span + 1e-9, step * 2)
        for d1 in first_dirs:
            for d4 in last_dirs:
                M = np.array([DIRS[d1], DIRS[d4]]).T
                if abs(np.linalg.det(M)) < 1e-9:
                    continue
                Mi = np.linalg.inv(M)
                for d2 in range(8):
                    if not turn_ok(d1, d2):
                        continue
                    for d3 in range(8):
                        if not (turn_ok(d2, d3) and turn_ok(d3, d4)):
                            continue
                        for l2 in s2:
                            R = D[None, :] - l2 * np.array(DIRS[d2])[None, :] - s2[:, None] * np.array(DIRS[d3])[None, :]
                            L14 = R @ Mi.T
                            ok = (L14[:, 0] >= mf(d1) - 1e-9) & (L14[:, 1] >= ml(d4) - 1e-9)
                            for k in np.flatnonzero(ok):
                                l1, l4, l3 = L14[k, 0], L14[k, 1], s2[k]
                                P1 = A + l1 * np.array(DIRS[d1]); P2 = P1 + l2 * np.array(DIRS[d2]); P3 = P2 + l3 * np.array(DIRS[d3])
                                out.append((l1 + l2 + l3 + l4 + 0.9, [tuple(A), tuple(P1), tuple(P2), tuple(P3), tuple(B)]))
    out.sort(key=lambda t: t[0])
    return out
