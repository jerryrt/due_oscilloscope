import json, math
D = json.load(open('/work/hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock/afe1_dump.json'))
P = {p['ref']: p for p in D['parts']}
u = P['U401']; print('U401', u['x'], u['y'])
for r in sorted(P):
    if r.startswith('C4') or r.startswith('R4'):
        p = P[r]; out = []
        for q in p['pads']:
            ds = [(math.hypot(q['c'][0] - w['c'][0], q['c'][1] - w['c'][1]), w['n']) for w in u['pads'] if w['net'] == q['net'] and w['n']]
            if ds: out.append((q['n'], q['net'], round(min(ds)[0], 2), min(ds)[1]))
        print(r, out)
