"""stackcheck.py BOARD [REF ...]   (in the PCB image): the two-way nearest test, margin 0.15 mm (owner, round 5), measured from the board's own text.

Distances between axis-aligned boxes (0 when they touch). A part's SOLID is its body outline box (F.Fab) and each pad box. A designator's box is 0.95 mm per character by 1.2 mm (turned with
the text); a function text is its pcbnew bounding box. A BNC's designator and function text are ONE label (the nearer counts).
 1. FROM THE LABEL: for every label of part P, d(label, P) + 0.15 <= d(label, Q) for every other part Q.
 2. FROM THE PART: for every part P with a label, d(P, its label) + 0.15 <= d(P, any other label).
An anchor (U, J, TP) is compared only against parts / labels of its own kind in both steps; a passive against all. Prints the failing parts and, with REF arguments, those
parts' measured numbers."""
import sys, math
sys.path.insert(0, '/work/hardware/afe-proto'); sys.path.append('/usr/lib/python3/dist-packages')
import numpy as np, pcbnew
from pcbtools import boardio

FUN = {'CH1 IN': 'J101', 'CH2 IN': 'J201', 'AWG OUT': 'J301'}
def kind(p): return 'TP' if p.startswith('TP') else (p[0] if p[0] in 'UJ' else 'P')


def run(path):
    b = boardio.read_board(path); pb = pcbnew.LoadBoard(path); mm = pcbnew.ToMM
    refs = list(b.fp_ref); row = {int(k): i for i, k in enumerate(b.fp_idx)}
    solid = {}
    for f in pb.GetFootprints():
        bx = pcbnew.BOX2I(); n = 0; items = []
        for g in f.GraphicalItems():
            if g.GetLayer() == pcbnew.F_Fab: bx.Merge(g.GetBoundingBox()); n += 1
        if n: items.append((mm(bx.GetX()) - 50.0, 150.0 - mm(bx.GetBottom()), mm(bx.GetRight()) - 50.0, 150.0 - mm(bx.GetY())))
        for p in f.Pads():
            q = p.GetBoundingBox(); items.append((mm(q.GetX()) - 50.0, 150.0 - mm(q.GetBottom()), mm(q.GetRight()) - 50.0, 150.0 - mm(q.GetY())))
        solid[f.GetReference()] = items
    labels = {}                                                          # part -> [boxes]
    def box(cx, cy, L, ang): return (cx - L / 2, cy - 0.6, cx + L / 2, cy + 0.6) if round(ang) % 180 == 0 else (cx - 0.6, cy - L / 2, cx + 0.6, cy + L / 2)
    for j in range(len(b.r_fp)):
        r = refs[row[int(b.r_fp[j])]]
        if b.r_on_silk[j] and int(b.r_layer[j]) == boardio.R_LAYERS['F.SilkS']: labels.setdefault(r, []).append(box(float(b.r_x[j]), float(b.r_y[j]), len(r) * 0.95, float(b.r_ang[j])))
    for d in pb.GetDrawings():
        if d.GetClass() == 'PCB_TEXT' and d.GetText() in FUN:
            bb = d.GetBoundingBox(); x0, x1 = mm(bb.GetX()) - 50.0, mm(bb.GetRight()) - 50.0; y0, y1 = 150.0 - mm(bb.GetBottom()), 150.0 - mm(bb.GetY())
            labels.setdefault(FUN[d.GetText()], []).append((x0, y0, x1, y1))
    def gap(a, c): return math.hypot(max(c[0] - a[2], 0.0, a[0] - c[2]), max(c[1] - a[3], 0.0, a[1] - c[3]))
    def dsolid(p, bx): return min(gap(bx, it) for it in solid[p]) if solid.get(p) else 9e9
    def lab_to_part(bx_list, p): return min(dsolid(p, bx) for bx in bx_list)
    out = {}; bad = {}
    for p in sorted(labels):
        own = min(dsolid(p, bx) for bx in labels[p])
        # step 1, from the label: its own part against every other part of the comparable kind
        s1 = None
        for q in solid:
            if q == p or (kind(p) != 'P' and kind(q) != kind(p)): continue
            dq = min(gap(bx, it) for bx in labels[p] for it in solid[q]) if solid[q] else 9e9
            dp = min(gap(bx, it) for bx in labels[p] for it in solid[p])
            if dp + 0.15 > dq and (s1 is None or dq - dp < s1[0]): s1 = (dq - dp, q, dp, dq)
        # step 2, from the part: its own label against every other label of the comparable kind
        s2 = None
        for o, bxs in labels.items():
            if o == p or (kind(p) != 'P' and kind(o) != kind(p)): continue
            do = min(dsolid(p, bx) for bx in bxs)
            if own + 0.15 > do and (s2 is None or do - own < s2[0]): s2 = (do - own, o, own, do)
        out[p] = (own, s1, s2)
        if s1 or s2: bad[p] = (s1, s2)
    return out, bad


if __name__ == '__main__':
    out, bad = run(sys.argv[1])
    print('parts with a label', len(out), '; failing either step', len(bad))
    for p, (s1, s2) in sorted(bad.items()):
        print('  FAIL %-6s %s %s' % (p, ('step1(label: own part %.2f, but %s at %.2f)' % (s1[2], s1[1], s1[3])) if s1 else '', ('step2(part: own label %.2f, other label of %s at %.2f)' % (s2[2], s2[1], s2[3])) if s2 else ''))
    for r in sys.argv[2:]:
        if r in out:
            own, s1, s2 = out[r]; print('  %s: d(part,own label) %.2f; %s; %s' % (r, own, 'step1 FAIL' if s1 else 'step1 ok', 'step2 FAIL' if s2 else 'step2 ok'))
