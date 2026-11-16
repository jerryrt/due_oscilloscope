import sys, json
sys.path.insert(0, '/work/hardware/afe-proto/v2/layout')
import relayout_place as RP
D = {p['ref']: p for p in json.load(open(sys.argv[1]))['parts']}
for blk, pre in (('CH1', '1'), ('CH2', '2')):
    rects = RP.REGIONS[blk]
    area = sum((r[2] - r[0]) * (r[3] - r[1]) for r in rects)
    used = sum((D[r]['cy'][2] - D[r]['cy'][0]) * (D[r]['cy'][3] - D[r]['cy'][1]) for r in D if r[1] == pre and r[0] in 'CRDTB' and D[r].get('cy') and r not in ('J101', 'J201'))
    u101 = (D['U101']['cy'][2] - D['U101']['cy'][0]) * (D['U101']['cy'][3] - D['U101']['cy'][1]) if blk == 'CH1' else 0
    print(blk, 'region area %.1f mm2' % area, 'courtyards %.1f mm2 (%.0f%%)' % (used, 100 * used / area))
