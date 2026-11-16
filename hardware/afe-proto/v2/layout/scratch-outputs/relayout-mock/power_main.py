import json, sys
sys.path.insert(0, '/work/hardware/afe-proto/v2/layout')
import relayout_place as RP
R = '/work/hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock/'
D, P = RP.load(R + 'dump_all.json')
st = {r: [p['x'], p['y'], p['rot'], 0] for r, p in P.items() if RP.block_of(r) == 'POWER'}
json.dump(dict(st=st), open(R + 'power_main_place.json', 'w')); print(len(st), sorted(st))
