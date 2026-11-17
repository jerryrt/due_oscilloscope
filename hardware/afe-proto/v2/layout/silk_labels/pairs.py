import sys, math
sys.path.insert(0, '/work/hardware/afe-proto'); sys.path.append('/usr/lib/python3/dist-packages')
import pcbnew
from pcbtools import boardio
PAIRS = [('BR510', 'R514'), ('BR507', 'R506'), ('C407', 'R403'), ('R305', 'R304'), ('R301', 'C306'), ('R308', 'C305')]
def load(path):
    b = boardio.read_board(path); pb = pcbnew.LoadBoard(path); mm = pcbnew.ToMM
    refs = list(b.fp_ref); row = {int(k): i for i, k in enumerate(b.fp_idx)}
    solid = {}
    for f in pb.GetFootprints():
        bx = pcbnew.BOX2I(); n = 0; it = []
        for g in f.GraphicalItems():
            if g.GetLayer() == pcbnew.F_Fab: bx.Merge(g.GetBoundingBox()); n += 1
        if n: it.append((mm(bx.GetX()) - 50, 150 - mm(bx.GetBottom()), mm(bx.GetRight()) - 50, 150 - mm(bx.GetY())))
        for p in f.Pads():
            q = p.GetBoundingBox(); it.append((mm(q.GetX()) - 50, 150 - mm(q.GetBottom()), mm(q.GetRight()) - 50, 150 - mm(q.GetY())))
        solid[f.GetReference()] = it
    lab = {}; pos = {}
    for j in range(len(b.r_fp)):
        r = refs[row[int(b.r_fp[j])]]
        if b.r_on_silk[j] and int(b.r_layer[j]) == boardio.R_LAYERS['F.SilkS']:
            L = len(r) * 0.95; x, y = float(b.r_x[j]), float(b.r_y[j]); a = float(b.r_ang[j]); pos[r] = (round(x, 2), round(y, 2), round(a))
            lab[r] = (x - L / 2, y - 0.6, x + L / 2, y + 0.6) if round(a) % 180 == 0 else (x - 0.6, y - L / 2, x + 0.6, y + L / 2)
    return solid, lab, pos
def gap(a, c): return math.hypot(max(c[0] - a[2], 0.0, a[0] - c[2]), max(c[1] - a[3], 0.0, a[1] - c[3]))
def ds(solid, p, bx): return min(gap(bx, it) for it in solid[p])
old, new = load(sys.argv[1]), load(sys.argv[2])
for tag, (solid, lab, pos) in (('round 4 board', old), ('new board', new)):
    print(tag)
    for a, c in PAIRS:
        if a in lab and c in lab:
            print('  %s/%s: d(%s, own label) %.2f, d(%s, label of %s) %.2f; d(%s, own label) %.2f, d(%s, label of %s) %.2f; label-to-label %.2f' % (a, c, a, ds(solid, a, lab[a]), a, c, ds(solid, a, lab[c]), c, ds(solid, c, lab[c]), c, a, ds(solid, c, lab[a]), gap(lab[a], lab[c])))
        else: print('  %s/%s: %s' % (a, c, ' and '.join('%s has no label' % q for q in (a, c) if q not in lab)))
so, lo, po = old; sn, ln, pn = new
lost = sorted(set(lo) - set(ln)); gained = sorted(set(ln) - set(lo)); moved = sorted(r for r in set(lo) & set(ln) if max(abs(po[r][0] - pn[r][0]), abs(po[r][1] - pn[r][1])) > 0.05 or po[r][2] != pn[r][2])
print('labels lost vs round 4:', len(lost), lost); print('labels gained:', len(gained), gained); print('labels moved:', len(moved), moved)
