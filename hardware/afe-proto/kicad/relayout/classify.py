import json, math, re, sys, itertools
from pcbtools import boardio
b = boardio.read_board('whatif/_scratch/base_fixed.kicad_pcb')
pos = {(b.fp_ref[int(b.p_fp[j])], str(b.p_pin[j])): (float(b.p_x[j]), float(b.p_y[j])) for j in range(len(b.p_fp))}
J = json.load(open('whatif/_scratch/jobpads.json'))
def pts(name):
    j = J[name]; ks = [tuple(p.split('.')) for p in j['pads'] + j['star']]
    return [pos[k] for k in ks if k in pos]
def mst(P):
    if len(P) < 2: return []
    inT = {0}; E = []
    while len(inT) < len(P):
        best = None
        for i in inT:
            for k in range(len(P)):
                if k in inT: continue
                d = math.dist(P[i], P[k])
                if best is None or d < best[0]: best = (d, i, k)
        E.append((P[best[1]], P[best[2]])); inT.add(best[2])
    return E
def ccw(a, b_, c): return (c[1]-a[1])*(b_[0]-a[0]) - (b_[1]-a[1])*(c[0]-a[0])
def inter(a, b_, c, d):
    return ccw(a, c, d)*ccw(b_, c, d) < 0 and ccw(a, b_, c)*ccw(a, b_, d) < 0
lines = [l for l in open(sys.argv[1]).read().splitlines() if l.startswith('CLUSTER')]
for l in lines:
    m = re.match(r"CLUSTER \(([-\d.]+), ([-\d.]+)\) (\[.*\])", l)
    x, y = float(m.group(1)), float(m.group(2)); names = eval(m.group(3))
    names = [n for n in names if n in J]
    kind = 'squeeze'; why = ''
    for a, c in itertools.combinations(names, 2):
        Ea, Ec = mst(pts(a)), mst(pts(c))
        X = [(e, f) for e in Ea for f in Ec if inter(e[0], e[1], f[0], f[1])]
        if X: kind = 'CROSSING'; why = '%s x %s: %d chord crossings' % (a, c, len(X)); break
    print('(%.1f, %.1f)' % (x, y), names, kind, why)
