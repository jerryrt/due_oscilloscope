"""twoway_check.py BOARD PLAN.json: round 9's rule, both ways, on a finished plan. (2) from the part: its own label is nearer than any other label by 0.15, to body and pads;
anchors compare only against labels of their own kind; a BNC's designator and function text are one label. Prints the failures and the list of labelled parts."""
import sys, json
sys.path.insert(0, '.'); sys.path.append('/usr/lib/python3/dist-packages')
sys.argv_ = sys.argv
exec(open('kicad/labels/ratio.py').read().split("rows = []")[0])
M = 0.15
def kind(q):
    q = q[3:] if q.startswith('fn:') else q
    if q.startswith('name:'): return None
    return 'TP' if q.startswith('TP') else q[0]
anchor = lambda q: q.startswith(('U', 'J', 'TP', 'D'))
BNCS = ('J101', 'J201', 'J301'); fnof = {'CH1 IN': 'J101', 'CH2 IN': 'J201', 'AWG OUT': 'J301'}
bad = []
for r, bx in labs.items():
    sol = solid.get(r, cour[r])
    own = min([gap(sol, bx)] + ([gap(sol, others['fn:' + t]) for t, j in fnof.items() if j == r and 'fn:' + t in others]))
    near = (9e9, '')
    for q, bo in others.items():
        if q == r or (q.startswith('fn:') and fnof[q[3:]] == r): continue
        qq = q if not q.startswith('fn:') else fnof[q[3:]]
        if anchor(r) and kind(qq if not q.startswith('name:') else q) != kind(r): continue
        d = gap(sol, bo)
        if d < near[0]: near = (d, q)
    if near[0] <= own + M: bad.append((r, own, near[0], near[1]))
print('labelled parts', len(labs), 'fail the part-side test', len(bad))
for r, o, n, q in sorted(bad, key=lambda t: t[2] - t[1]): print('  %-6s own %.2f  nearest other %.2f (%s)' % (r, o, n, q))
