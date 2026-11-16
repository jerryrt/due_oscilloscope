import json, math, sys
sys.path.insert(0, '/work/hardware/afe-proto/v2/layout')
import relayout_place as RP
R = '/work/hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock/'
for fn in ('dump_all.json', 'dump_new.json'):
    D, P = RP.load(R + fn)
    u = P['U401']
    print('==', fn, 'U401', u['x'], u['y'], u['rot'], 'cy', [round(v, 2) for v in u['cy']])
    print([(q['n'], q['net']) for q in u['pads']])
    for r in sorted(P):
        if r.startswith('C4') or r.startswith('R40'):
            p = P[r]
            best = []
            for q in p['pads']:
                ds = [(math.hypot(q['c'][0] - w['c'][0], q['c'][1] - w['c'][1]), w['n']) for w in u['pads'] if w['net'] == q['net'] and w['n']]
                if ds: best.append((q['n'], q['net'], round(min(ds)[0], 2), min(ds)[1]))
            print(r, best)
print('hard', [h['name'] for h in RP.hard_constraints(P)])
