import json, math, sys
sys.path.insert(0,'/work/hardware/afe-proto/v2/layout')
import relayout_place as RP
D=json.load(open('/work/hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock/dump_new.json')); P={p['ref']:p for p in D['parts']}
def gap(a,b):
    dx=max(b[0]-a[2],0,a[0]-b[2]); dy=max(b[1]-a[3],0,a[1]-b[3]); return math.hypot(dx,dy)
for u in ('U401','C409','C403'):
    c=P[u]['cy']; d=min(gap(c,r) for b,rs in RP.REGIONS.items() if b!='POWER' for r in rs); print(u,'to nearest other block: %.1f mm'%d)
for c,i,_w in RP.TIES: print(c,i,'courtyard gap %.1f mm'%gap(P[c]['cy'],P[i]['cy']))
