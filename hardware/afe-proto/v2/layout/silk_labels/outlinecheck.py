"""python3 _work/outlinecheck.py BOARD: rule (a) on the board's own silk and the outline table (v2/layout/outlines.py via pcbtools v2_layout): what the outlines are, which parts they hold, the failures by name"""
import sys, re, itertools
sys.path.insert(0, '/work/hardware/afe-proto'); sys.path.append('/usr/lib/python3/dist-packages')
import numpy as np
from pcbtools import boardio, silkread as S
from pcbtools.boards import v2_layout as C
b = boardio.read_board(sys.argv[1]); silk = [s for s in S.read_silk(open(sys.argv[1]).read()) if s[0] == 'seg']
print('F.SilkS board-level segments:', len(silk), '; outline table blocks:', {k: len(v) for k, v in C.OUTLINE.items()})
refs = list(b.fp_ref)
cour = {refs[i]: S._box(b.fp_cx0[i], b.fp_cy0[i], b.fp_cx1[i], b.fp_cy1[i]) for i in range(len(refs)) if not np.isnan(b.fp_cx0[i])}
def inside(c, r, m=0.005): return r[0] - m <= c[0] and c[2] <= r[2] + m and r[1] - m <= c[1] and c[3] <= r[3] + m
def inter(c, r): return c[0] < r[2] and r[0] < c[2] and c[1] < r[3] and r[1] < c[3]
home = {r: (C.SHARED_PARTS.get(r) or C.BLOCK.get(r)) for r in refs}
notin, cross = [], []
for r, c in cour.items():
    h = home[r]
    if not h or h == C.EDGE_BLOCK: continue
    if not any(inside(c, q) for q in C.OUTLINE[h]): notin.append((r, h))
    for blk, rs in C.OUTLINE.items():
        if blk != h and any(inter(c, q) for q in rs): cross.append((r, h, blk))
print('parts whose courtyard is not inside a rectangle of their own block (%d):' % len(notin), notin)
print('parts whose courtyard enters another block\'s rectangle (%d):' % len(cross), cross)
ov = []
for (a, ra), (bb, rb) in itertools.combinations([(k, q) for k, rs in C.OUTLINE.items() for q in rs], 2):
    if a != bb and inter(ra, rb): ov.append((a, bb, ra, rb))
print('rectangles of different blocks that overlap (%d):' % len(ov), ov)
# is each block's outline one polygon (its rectangles connected by overlap or contact)?
for blk, rs in C.OUTLINE.items():
    comp = list(range(len(rs)))
    def f(x):
        while comp[x] != x: x = comp[x]
        return x
    for i, j in itertools.combinations(range(len(rs)), 2):
        if rs[i][0] <= rs[j][2] and rs[j][0] <= rs[i][2] and rs[i][1] <= rs[j][3] and rs[j][1] <= rs[i][3]: comp[f(i)] = f(j)
    print('block %-7s rectangles %d, separate polygons %d' % (blk, len(rs), len({f(i) for i in range(len(rs))})))
# breaks in the drawn outline: for each rectangle edge, the parts of it with no silk segment on it
def covered(p0, p1, axis):
    L = sorted(((min(s[1], s[3]), max(s[1], s[3])) if axis == 'x' else (min(s[2], s[4]), max(s[2], s[4]))) for s in silk
               if (axis == 'x' and abs(s[2] - p0[1]) < 0.02 and abs(s[4] - p0[1]) < 0.02) or (axis == 'y' and abs(s[1] - p0[0]) < 0.02 and abs(s[3] - p0[0]) < 0.02))
    lo, hi = (p0[0], p1[0]) if axis == 'x' else (p0[1], p1[1]); gaps = []; cur = lo
    for a, c in L:
        if c < cur: continue
        if a > cur + 0.02 and a > lo: gaps.append((round(cur, 2), round(min(a, hi), 2)))
        cur = max(cur, c)
    if cur < hi - 0.02: gaps.append((round(cur, 2), round(hi, 2)))
    return gaps
for blk, rs in C.OUTLINE.items():
    for q in rs:
        g = {'S': covered((q[0], q[1]), (q[2], q[1]), 'x'), 'N': covered((q[0], q[3]), (q[2], q[3]), 'x'), 'W': covered((q[0], q[1]), (q[0], q[3]), 'y'), 'E': covered((q[2], q[1]), (q[2], q[3]), 'y')}
        g = {k: v for k, v in g.items() if v}
        if g: print('  %s rect %s: silk breaks (edge: from-to) %s' % (blk, tuple(round(v, 2) for v in q), g))
