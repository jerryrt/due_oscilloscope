import sys, math
sys.path.insert(0, '/work/hardware/afe-proto/v2/layout')
import relayout_place as RP
R = '/work/hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock/'
D0, P0 = RP.load(R + 'dump_all.json'); DN, PN = RP.load(R + 'dump_new.json')
u = PN['U502']; p8 = [q for q in u['pads'] if q['n'] == '8'][0]['c']
print('U502 now', u['x'], u['y'], u['rot'], 'pin8', p8, 'U501 now', PN['U501']['x'], PN['U501']['y'], PN['U501']['rot'])
for r in sorted(PN):
    if RP.block_of(r) == 'REFCAL':
        p = PN[r]; d = math.hypot(p['x'] - p8[0], p['y'] - p8[1])
        if d < 9: print(r, round(p['x'], 2), round(p['y'], 2), p['rot'], 'dist to pin8', round(d, 2))
