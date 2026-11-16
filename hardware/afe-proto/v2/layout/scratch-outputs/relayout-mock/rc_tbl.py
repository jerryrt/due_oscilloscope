import sys, math
sys.path.insert(0, '/work/hardware/afe-proto/v2/layout')
import relayout_place as RP
R = '/work/hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock/'
D0, P0 = RP.load(R + 'dump_all.json'); DN, PN = RP.load(R + 'dump_new.json')
def dist(P, r, ics):
    out = []
    for q in P[r]['pads']:
        if q['net'] in ('/GND', '') or 'unconnected' in q['net']: continue
        ds = [math.hypot(q['c'][0] - w['c'][0], q['c'][1] - w['c'][1]) for ic in ics for w in P[ic]['pads'] if w['net'] == q['net'] and w['n']]
        if ds: out.append((q['n'], round(min(ds), 2)))
    return out
for r in sorted(P0):
    if RP.block_of(r) == 'REFCAL' and r not in ('U501', 'U502'):
        m = dist(P0, r, ('U501', 'U502')); n = dist(PN, r, ('U501', 'U502'))
        if m: print('TBL', r, 'main', m, 'now', n, 'limit', [(a, round(b + 1.0, 2)) for a, b in m])
