import json, math, sys
sys.path.insert(0, '/work/hardware/afe-proto/v2/layout')
import relayout_place as RP
for fn in ('dump_all.json', 'dump_new.json'):
    D, P = RP.load('/work/' + '$R'.replace('$R', 'hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock/') + fn)
    print('==', fn)
    for r in sorted(P):
        if RP.block_of(r) == 'POWER' or (len(sys.argv) > 1 and r == 'U401'):
            p = P[r]; print(r, round(p['x'], 2), round(p['y'], 2), p['rot'], [(q['n'], q['net'], [round(v, 2) for v in q['c']]) for q in p['pads']][:12])
