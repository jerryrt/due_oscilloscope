import json, sys, os
sys.path.insert(0, '/work/hardware/afe-proto/v2/layout')
import relayout_place as RP
R = '/work/hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock/'
blk, seed, iters = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
fr = {}
import glob
for fn in sorted(glob.glob(R + 'run4/*.json')):
    if 'rest_CH1' in fn or 'placement' in fn: continue
    fr.update(json.load(open(fn))['st'])
os.environ['RP_DEBUG'] = '1'
RP.run(R + 'dump_all.json', '/tmp/dbg_%s.json' % blk, blk, seed=seed, iters=iters, frozen=fr)
