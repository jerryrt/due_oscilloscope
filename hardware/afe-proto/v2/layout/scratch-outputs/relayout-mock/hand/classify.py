"""python3 classify.py BOARD PF_LOG: classify each CLUSTER of a pf run as a crossing (the straight pad-to-pad trees of two of its nets cross within 4 mm of the spot) or a squeeze (they do not: the nets
conflict for lack of room). Uses the pads of the board; groups of a supply / Kelvin net by pf_cfg_afe2."""
import sys, re, math, itertools
sys.path.append('/usr/lib/python3/dist-packages'); sys.path.insert(0, '/work/hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock/hand')
import pcbnew, pf_cfg_afe2 as cfg
b = pcbnew.LoadBoard(sys.argv[1]); mm = pcbnew.ToMM
P = {}
for f in b.GetFootprints():
    for p in f.Pads():
        P[(f.GetReference(), p.GetNumber())] = (mm(p.GetPosition().x) - 50, 150 - mm(p.GetPosition().y), p.GetNetname())
def pts(job):
    if '#' in job:
        net, g = job.split('#')
        if net in cfg.GROUPS and g in cfg.GROUPS[net]:
            return [P[tuple(k.split('.'))][:2] for k in cfg.GROUPS[net][g] + cfg.STAR[net][:1] if tuple(k.split('.')) in P]
        if net in cfg.KELVIN:
            if g == 'src': return [P[tuple(k.split('.'))][:2] for k in cfg.KELVIN[net]['src']]
            return [P[tuple(k.split('.'))][:2] for k in cfg.KELVIN[net]['groups'][int(g)] + cfg.KELVIN[net]['src'][:1]]
        if g == 'star': return [P[tuple(k.split('.'))][:2] for k in cfg.STAR[net]]
    return [v[:2] for v in P.values() if v[2] == job]
def mst(p):
    if len(p) < 2: return []
    inn, out, e = [p[0]], list(p[1:]), []
    while out:
        d, a, c = min((math.dist(x, y), x, y) for x in inn for y in out); e.append((a, c)); inn.append(c); out.remove(c)
    return e
def cr(a, c, d, e):
    def ccw(p, q, r): return (r[1] - p[1]) * (q[0] - p[0]) - (q[1] - p[1]) * (r[0] - p[0])
    return ccw(a, d, e) * ccw(c, d, e) < 0 and ccw(a, c, d) * ccw(a, c, e) < 0
def sd(p, a, c):
    dx, dy = c[0] - a[0], c[1] - a[1]; L = dx * dx + dy * dy; t = 0 if L == 0 else max(0, min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L)); return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)
for l in open(sys.argv[2]):
    m = re.match(r"CLUSTER \(([\d.]+), ([\d.]+)\) (\[.*\])", l)
    if not m: continue
    x, y = float(m.group(1)), float(m.group(2)); jobs = eval(m.group(3)); kind = 'squeeze'; why = ''
    for a, c in itertools.combinations(jobs, 2):
        for e1 in mst(pts(a)):
            for e2 in mst(pts(c)):
                if cr(e1[0], e1[1], e2[0], e2[1]):
                    mx = [(e1[0][0] + e1[1][0]) / 2, (e1[0][1] + e1[1][1]) / 2]
                    if min(sd((x, y), *e1), sd((x, y), *e2)) < 6.0:
                        kind = 'crossing'; why = '%s x %s' % (a, c)
    print('(%.1f, %.1f)' % (x, y), kind, why, jobs)
