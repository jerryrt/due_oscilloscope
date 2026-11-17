"""python3 assemble.py ROUTED.kicad_pcb PRE.py HAND.py OUT_SPEC.py
spec = the router's copper of every net that PRE.py does not carry + PRE.py exactly (no grid staircase) + HAND.py (new hand routes)"""
import re, sys
routed, pre, hand, out = sys.argv[1:5]
def load(f):
    ns = {}; exec(open(f).read(), ns); return ns
P, H = load(pre), load(hand)
handnets = {('/' + n.lstrip('/')) for n, *_ in P['ROUTES'] + H.get('ROUTES', [])}
t = open(routed).read()
R, V = [], []
for m in re.finditer(r'\(segment\s+\(start ([\d.]+) ([\d.]+)\)\s+\(end ([\d.]+) ([\d.]+)\)\s+\(width ([\d.]+)\)\s+\(layer "(\w)\.Cu"\)\s+\(net "([^"]+)"\)', t):
    x0, y0, x1, y1, w, ly, net = m.groups()
    if net in handnets: continue
    R.append((net, ly, [(round(float(x0) - 50, 4), round(150 - float(y0), 4)), (round(float(x1) - 50, 4), round(150 - float(y1), 4))], float(w)))
for m in re.finditer(r'\(via\s+\(at ([\d.]+) ([\d.]+)\)[^)]*?\(size [\d.]+\)\s+\(drill [\d.]+\)\s+\(layers[^)]*\)\s+\(net "([^"]+)"\)', t):
    x, y, net = m.groups()
    if net in handnets: continue
    V.append((net, round(float(x) - 50, 4), round(150 - float(y), 4)))
fix = lambda L: [(('/' + n.lstrip('/')), l, p, w) for n, l, p, w in L]
R += fix(P['ROUTES']) + fix(H.get('ROUTES', []))
V += [(('/' + n.lstrip('/')), x, y) for n, x, y in P.get('VIAS', []) + H.get('VIAS', [])]
open(out, 'w').write('ROUTES = %r\nVIAS = %r\n' % (R, V))
print('spec', len(R), 'segments', len(V), 'vias; hand nets', sorted(handnets))
