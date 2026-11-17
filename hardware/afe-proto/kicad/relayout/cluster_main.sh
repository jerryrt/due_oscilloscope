#!/bin/bash
# cluster_main.sh NAME: put main's parts for one cluster (CH2 | AWG | ADS | POWER | none) back on the relayout board on scratch, rebuild,
# pre-route the fixed copper, run pf1 (halo 0.85) and print the cluster metric. NAME=none is the baseline.
cd /work/hardware/afe-proto && export PYTHONPATH=.
python3 - "$1" <<'P'
import json, sys, types
from pcbtools.boards import v1 as C
name = sys.argv[1]
J = json.load(open('whatif/_scratch/pos_keep.json')); R = json.load(open('whatif/_scratch/rotov_keep2.json'))
m = types.ModuleType('ml'); exec(compile(open('whatif/_scratch/main_layout.py').read(), 'ml', 'exec'), m.__dict__)
sel = {'CH2': lambda r: C.BLOCK.get(r) == 'SCOPE' and r[1:2] == '2' and r[:1] in 'RCD',
       'AWG': lambda r: C.BLOCK.get(r) == 'AWG' and not r.startswith(('J', 'TP', 'MH')),
       'ADS': lambda r: C.BLOCK.get(r) == 'REFCAL' and not r.startswith(('J', 'TP', 'MH')),
       'POWER': lambda r: C.BLOCK.get(r) == 'POWER' and not r.startswith(('J', 'TP', 'MH')),
       'none': lambda r: False}[name]
moved = []
for r in sorted(J):
    if sel(r) and r in m.PLACE:
        x, y, a = m.PLACE[r]; J[r] = [x, y]; R[r] = a; moved.append(r)
json.dump(J, open('whatif/_scratch/relay_pos.json', 'w'), indent=1); json.dump(R, open('whatif/_scratch/rotov.json', 'w'), indent=1)
print('MOVED', name, len(moved), moved[:40])
P
python3 kicad/relayout/gen_layout.py >/dev/null
bash whatif/_scratch/run_rel.sh 2>&1 | grep -v Debug | tail -1
python3 whatif/_scratch/assemble_final.py >/dev/null 2>&1
python3 kicad/relayout/netdiff.py whatif/_scratch/final/afe-proto.kicad_pcb | tail -1
python3 whatif/_scratch/stage1.py whatif/_scratch/final/afe-proto.kicad_pcb whatif/_scratch/route2/fixed.kicad_pcb 2>&1 | grep -c "fails \[\]"
INFL_HIZ=0.85 python3 whatif/_scratch/pf1.py whatif/_scratch/route2/fixed.kicad_pcb whatif/_scratch/route2/pf1_c.kicad_pcb 25 400 2>&1 | grep -v Debug | grep "^iter 24\|METRIC\|CLUSTER\|Trace\|Error" | cut -c1-300
cp whatif/_scratch/pos_keep.json whatif/_scratch/relay_pos.json; cp whatif/_scratch/rotov_keep2.json whatif/_scratch/rotov.json
