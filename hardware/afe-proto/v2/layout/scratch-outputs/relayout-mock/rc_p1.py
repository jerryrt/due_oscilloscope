import sys
sys.path.insert(0, '/work/hardware/afe-proto/v2/layout')
import relayout_place as RP
R = '/work/hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock/'
D0, P0 = RP.load(R + 'dump_all.json')
cy = {r: p['cy'] for r, p in P0.items() if p['cy']}
ks = sorted(cy)
for g in (0.0, 0.02):
    bad = [(a, b) for i, a in enumerate(ks) for b in ks[i + 1:] if min(cy[a][2], cy[b][2]) - max(cy[a][0], cy[b][0]) + g > 1e-6 and min(cy[a][3], cy[b][3]) - max(cy[a][1], cy[b][1]) + g > 1e-6]
    print('gap', g, 'overlaps in main (whole board)', bad)
