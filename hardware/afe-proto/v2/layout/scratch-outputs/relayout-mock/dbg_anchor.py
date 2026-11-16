import json, sys, os
sys.path.insert(0, '/work/hardware/afe-proto/v2/layout')
import relayout_place as RP, relayout_run as RR
R = '/work/hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock/'
ic, seed, iters = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
D, P = RP.load(R + 'dump_all.json')
for name, mine, regions, mv in RR.CLUSTERS:
    if name == ic:
        soft = {r: (ic, (P[r]['x'] - P[ic]['x'], P[r]['y'] - P[ic]['y'])) for r in mine if r != ic}
        os.environ['RP_DEBUG'] = '1'
        res, v = RP.run(R + 'dump_all.json', '/tmp/dbg_%s.json' % ic, regions[0], seed=seed, iters=iters, mine=mine, regions=regions, cluster_of=ic if mv else None, soft=soft)
        print(res)
