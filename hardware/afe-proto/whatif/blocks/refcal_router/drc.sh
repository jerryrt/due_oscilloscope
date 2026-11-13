#!/bin/bash
# drc.sh board.kicad_pcb out.json  (runs inside container; board stem must have .kicad_pro beside)
kicad-cli pcb drc --format json --severity-all -o "$2" "$1" >/dev/null 2>&1
python3 - "$2" <<'PY'
import json,sys,collections
d=json.load(open(sys.argv[1]))
c=collections.Counter()
for k in ('violations','unconnected_items','schematic_parity'):
    for v in d.get(k,[]): c[(k[:4],v['type'])]+=1
print(dict(c))
PY
