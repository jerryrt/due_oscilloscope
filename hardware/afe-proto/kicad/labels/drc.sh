#!/bin/bash
# drc.sh BOARD: silk-related DRC items with positions (Due mm)
cd /work/hardware/afe-proto/kicad && cp $1 /work/hardware/afe-proto/kicad/_d.kicad_pcb && cp afe-proto.kicad_pro _d.kicad_pro && kicad-cli pcb drc --format json --severity-all -o /work/hardware/afe-proto/_d.json _d.kicad_pcb >/dev/null 2>&1; cd ..
python3 - <<'P'
import json,collections
d=json.load(open('_d.json')); print(collections.Counter(v['type'] for v in d['violations']))
for v in d['violations']:
    if v['type'] in ('silk_over_copper','silk_overlap','silk_edge_clearance'):
        it=v['items']; print(v['type'], [(i['description'][:36], round(i['pos']['x']-50,1), round(150-i['pos']['y'],1)) for i in it])
P
rm -f _d.json kicad/_d.kicad_pcb kicad/_d.kicad_pro
