#!/bin/bash
cd /work/hardware/afe-proto/whatif/blocks/SCOPE
kicad-cli pcb drc --format json --severity-all --units mm -o w/drc.json SCOPE.kicad_pcb >/dev/null 2>&1
python3 - <<'PY'
import json
d=json.load(open('w/drc.json'))
def inbox(it):
    p=it['pos']; x=p['x']+50; y=150-p['y']; return 60<=x<=118 and 16<=y<=52
for sect in ('violations','unconnected_items'):
    out={}
    for v in d.get(sect,[]):
        its=v['items']
        if not any(inbox(i) for i in its): continue
        out.setdefault(v['type'],[]).append(v)
    for t,l in out.items():
        print(sect,t,len(l))
        if t in ('unconnected_items',) : pass
        for v in l[:40]:
            print('   ',v['description'][:70],'|',' ; '.join('%s@(%.2f,%.2f)'%(i['description'][:38],i['pos']['x']+50,150-i['pos']['y']) for i in v['items']))
PY
