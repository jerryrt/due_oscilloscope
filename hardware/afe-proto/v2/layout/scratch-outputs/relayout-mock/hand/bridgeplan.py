"""python3 bridgeplan.py PF_SPEC.py BOARD.kicad_pcb OUT_BRIDGES.py REF:X:Y:NETA:NETB [REF:X:Y:NETA:NETB ...]   (in the image)
For each proposed bridge (a 0603 0R at the crossing point X,Y of net NETA over net NETB, user mm) cut NETA's routed copper at X,Y, find which of NETA's pads
fall on each side, rename the pads of the side that does not hold the majority (or the star/source side) to NETA_<REF>, and write BRIDGES for add_bridges.py:
pad 1 on the kept side, pad 2 on the renamed side, the axis perpendicular to NETB's nearest segment. Scratch only."""
import sys, math, re
sys.path.append('/usr/lib/python3/dist-packages')
import pcbnew
spec, board, out, *props = sys.argv[1:]
ns = {}; exec(open(spec).read(), ns)
R = ns['ROUTES']
b = pcbnew.LoadBoard(board)
mm = pcbnew.ToMM
pads = []
for f in b.GetFootprints():
    for p in f.Pads():
        bb = p.GetBoundingBox()
        pads.append((f.GetReference(), p.GetNumber(), p.GetNetname(), (mm(bb.GetX()) - 50, 150 - mm(bb.GetBottom()), mm(bb.GetRight()) - 50, 150 - mm(bb.GetY()))))
for t in b.GetTracks():
    if t.GetClass() != 'PCB_VIA':
        R = R + [(t.GetNetname(), 'F', [(mm(t.GetStart().x) - 50, 150 - mm(t.GetStart().y)), (mm(t.GetEnd().x) - 50, 150 - mm(t.GetEnd().y))], mm(t.GetWidth()))]
def sd(p, a, c):
    dx, dy = c[0] - a[0], c[1] - a[1]; L = dx * dx + dy * dy
    t = 0 if L == 0 else max(0, min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L))
    return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)
out_b = []
for pr in props:
    ref, x, y, na, nb = pr.split(':'); x, y = float(x), float(y)
    segs = [(u, v) for n, l, pl, w in R if n == na for u, v in zip(pl, pl[1:])]
    parent = {}
    def find(a):
        while parent.setdefault(a, a) != a:
            parent[a] = parent[parent[a]]; a = parent[a]
        return a
    keep = [(u, v) for u, v in segs if sd((x, y), u, v) > 0.9]
    def segd(a_, b_, c_, d_):
        return min(sd(a_, c_, d_), sd(b_, c_, d_), sd(c_, a_, b_), sd(d_, a_, b_))
    npad = [(r_, pn, bb) for r_, pn, net, bb in pads if net == na]
    par = list(range(len(keep) + len(npad)))
    def fd(i):
        while par[i] != i:
            par[i] = par[par[i]]; i = par[i]
        return i
    for i in range(len(keep)):
        for j in range(i + 1, len(keep)):
            if segd(keep[i][0], keep[i][1], keep[j][0], keep[j][1]) < 0.06:
                par[fd(i)] = fd(j)
        for q in keep[i]:
            for k, (r_, pn, bb) in enumerate(npad):
                if bb[0] - 0.05 <= q[0] <= bb[2] + 0.05 and bb[1] - 0.05 <= q[1] <= bb[3] + 0.05:
                    par[fd(i)] = fd(len(keep) + k)
    side = {}
    for k, (r_, pn, bb) in enumerate(npad):
        side[(r_, pn)] = (fd(len(keep) + k), ((bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2))
    comps = {}
    for k, (h, pc) in side.items():
        comps.setdefault(h, []).append(k)
    print(pr, 'components of %s after the cut: %s' % (na, {str(h)[:20]: v for h, v in comps.items()}))
    big = max(comps, key=lambda h: len(comps[h]))
    move = {'%s.%s' % k: '%s_%s' % (na.lstrip('/'), ref) for h, ks in comps.items() if h != big for k in ks}
    cen_keep = [side[k][1] for k in comps[big]]; cen_mv = [side[k][1] for h, ks in comps.items() if h != big for k in ks]
    nbs = [(sd((x, y), u, v), u, v) for n, l, pl, w in R if n == nb for u, v in zip(pl, pl[1:])]
    d, u, v = min(nbs)
    ang = math.atan2(v[1] - u[1], v[0] - u[0]) + math.pi / 2
    ux, uy = math.cos(ang), math.sin(ang)
    if cen_mv and cen_keep:
        mx = sum(c[0] for c in cen_mv) / len(cen_mv) - x; my = sum(c[1] for c in cen_mv) / len(cen_mv) - y
        if mx * ux + my * uy < 0: ux, uy = -ux, -uy
    th = math.degrees(math.atan2(uy, ux)) % 360
    # pad 1 (local -x) lies at -u: it must face the kept side, i.e. u points to the renamed side: pad 2 = renamed
    out_b.append(dict(ref=ref, x=round(x, 3), y=round(y, 3), rot=round(th, 1), a=na.lstrip('/'), b='%s_%s' % (na.lstrip('/'), ref), move=move))
open(out, 'w').write('BRIDGES = %r\n' % out_b)
print('wrote', out, out_b)
