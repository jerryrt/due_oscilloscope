"""Proxy search over the ladder slots: python3 ladderperm.py -> prints the best assignments (part -> slot, turned or not) by MST wire length + 30 x crossings of the TAP nets."""
import json, itertools, math
P = json.load(open('pads.json'))
SL = {'S501': (47.35, 11.25), 'S502': (47.1, 15.25), 'S503': (50.85, 27.5), 'S504': (53.55, 5.525), 'S505': (54.93, 27.5), 'S506': (49.67, 5.625)}
OFF = 0.82                                   # pad offset from the part origin (0603)
# ladder parts: name -> (net at its pad "a", net at its pad "b") in chain order; a turned part swaps them
PARTS = {'R501': ('/GND', '/TAP1'), 'R502': ('/TAP1', '/TAP2'), 'R503': ('/TAP2', '/TAP3'), 'R504': ('/TAP3', '/TAP4'), 'R505': ('/TAP4', '/TAP5'), 'R506': ('/TAP5', '/VREF')}      # (pad 1 net, pad 2 net); rot 0 puts pad 1 on the left
LAD = {'R501', 'R502', 'R503', 'R504', 'R505', 'R506'}
other = {}
for p in P:
    if p['ref'] in LAD: continue
    if p['net'] in ('/TAP1', '/TAP2', '/TAP3', '/TAP4', '/TAP5', '/VREF', '/GND') and p['net'] != '/GND':
        other.setdefault(p['net'], []).append((p['x'], p['y']))
def mst(pts):
    if len(pts) < 2: return []
    inn, out, e = [pts[0]], list(pts[1:]), []
    while out:
        d, a, b = min((math.dist(x, y), x, y) for x in inn for y in out)
        e.append((a, b)); inn.append(b); out.remove(b)
    return e
def cross(a, b, c, d):
    def ccw(p, q, r): return (r[1] - p[1]) * (q[0] - p[0]) - (q[1] - p[1]) * (r[0] - p[0])
    return ccw(a, c, d) * ccw(b, c, d) < 0 and ccw(a, b, c) * ccw(a, b, d) < 0
def cost(assign):
    nets = {n: list(v) for n, v in other.items()}
    for part, (slot, turn) in assign.items():
        x, y = SL[slot]; na, nb = PARTS[part]
        if turn: na, nb = nb, na                       # rot 180: pad 1 on the right
        nets.setdefault(na, []).append((x - OFF, y)); nets.setdefault(nb, []).append((x + OFF, y))
    edges = {n: mst(v) for n, v in nets.items() if n != '/GND'}
    wl = sum(math.dist(a, b) for e in edges.values() for a, b in e)
    ns = list(edges); cr = 0
    for i in range(len(ns)):
        for j in range(i + 1, len(ns)):
            for a, b in edges[ns[i]]:
                for c, d in edges[ns[j]]:
                    if cross(a, b, c, d): cr += 1
    return wl + 30 * cr, wl, cr
names = sorted(PARTS)
cur = {'R501': ('S501', 0), 'R502': ('S502', 0), 'R503': ('S503', 1), 'R504': ('S504', 1), 'R505': ('S505', 0), 'R506': ('S506', 1)}   # pads as placed now: R50x pad a/b by turn (1 = pad a on the right)
res = []
slots = list(SL)
for perm in itertools.permutations(slots):
    for turns in itertools.product((0, 1), repeat=6):
        a = {n: (perm[i], turns[i]) for i, n in enumerate(names)}
        res.append((cost(a), a))
res.sort(key=lambda t: t[0][0])
print('current', cost(cur))
for (c, wl, cr), a in res[:14]:
    print(round(c, 1), round(wl, 1), cr, {k: v for k, v in a.items()})
