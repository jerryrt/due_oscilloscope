import json, sys
sys.path.insert(0, '/work/hardware/afe-proto/v2/layout')
import relayout_place as RP
D, P = RP.load('/work/hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock/dump_all.json')
print('region', RP.REGIONS['REFCAL'])
for r in sorted(P):
    if RP.block_of(r) == 'REFCAL':
        p = P[r]; print(r, round(p['x'], 2), round(p['y'], 2), p['rot'], [(q['n'], q['net']) for q in p['pads']][:14])
