import sys, math, json
sys.path.insert(0, '/work/hardware/afe-proto/v2/layout')
import numpy as np, relayout_place as RP
R = '/work/hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock/'
D0, P0 = RP.load(R + 'dump_all.json')
reg = RP.REGIONS['REFCAL']; mext = RP.Mask(reg, 0.2)
PART = sorted(r for r in P0 if RP.block_of(r) == 'REFCAL')
ics = {r: P0[r] for r in ('U501', 'U502')}
tied = {}
for r in PART:
    if r in ics: continue
    for q in P0[r]['pads']:
        if q['net'] in ('/GND', '') or 'unconnected' in q['net']: continue
        ds = [(math.hypot(q['c'][0] - w['c'][0], q['c'][1] - w['c'][1]), ic, w['n']) for ic, pic in ics.items() for w in pic['pads'] if w['net'] == q['net'] and w['n']]
        if ds:
            d = min(ds); tied.setdefault(r, []).append((q['n'], q['net'], round(d[0], 2), d[1], d[2]))
for r, v in tied.items(): print('TIE', r, v)
print('untied', [r for r in PART if r not in tied and r not in ics])
cy = {}
for r in PART:
    p = P0[r]; g = RP.part_geom(p); x, y = p['x'], p['y']; cy[r] = (g['cy'][0] + x, g['cy'][1] + y, g['cy'][2] + x, g['cy'][3] + y)
bad = [(a, b) for i, a in enumerate(PART) for b in PART[i + 1:] if min(cy[a][2], cy[b][2]) - max(cy[a][0], cy[b][0]) + 0.02 > 1e-6 and min(cy[a][3], cy[b][3]) - max(cy[a][1], cy[b][1]) + 0.02 > 1e-6]
print('main courtyard conflicts (gap 0.02)', bad)
out = []
for r in PART:
    p = P0[r]; g = RP.part_geom(p); x, y = p['x'], p['y']
    e = (g['ext'][0] + x, g['ext'][1] + y, g['ext'][2] + x, g['ext'][3] + y)
    if mext.bad(e) > 0: out.append((r, round(x, 1), round(y, 1)))
print('main positions outside the REF/CAL region', out)
