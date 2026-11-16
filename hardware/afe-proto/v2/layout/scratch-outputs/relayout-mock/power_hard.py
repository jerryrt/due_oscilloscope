import sys
sys.path.insert(0, '/work/hardware/afe-proto/v2/layout')
import relayout_place as RP
D, P = RP.load('/work/hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock/dump_all.json')
for h in RP.hard_constraints(P):
    if any(RP.block_of(r) == 'POWER' for r in h['refs']): print(h['refs'], h['name'])
print(RP.REGIONS['POWER'], RP.LANES)
print([ (r, RP.block_of(r)) for r in ('U401','J601','TP401')])
print([k for k in dir(RP) if k.isupper()])
