import sys
sys.path.insert(0, '/work/hardware/afe-proto/v2/layout')
import relayout_place as RP
D0, P0 = RP.load('/work/hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock/dump_all.json'); DN, PN = RP.load('/work/hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock/dump_new.json')
for blk in ('CH1', 'CH2'):
    PART = sorted(r for r in P0 if RP.block_of(r) == blk)
    print(blk, PART)
    for r in PART: print('  ', r, 'main', (round(P0[r]['x'], 2), round(P0[r]['y'], 2), P0[r]['rot']), 'now', (round(PN[r]['x'], 2), round(PN[r]['y'], 2), PN[r]['rot']))
print('U101', P0['U101']['x'], P0['U101']['y'], 'J602', [ (q['n'], q['c']) for q in P0['J602']['pads'] if q['n'] in ('7','8')])
