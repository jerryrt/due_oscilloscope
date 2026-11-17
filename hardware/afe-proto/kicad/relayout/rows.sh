#!/bin/bash
# rows.sh LABEL SPEC : apply the move spec (ref:dx:dy:rot;...), rebuild, pre-route, full pf1 (25), then the LR rows on the pf output + metric
cd /work/hardware/afe-proto && export PYTHONPATH=.
LABEL=$1; SPEC=$2
python3 - "$SPEC" <<'P'
import json, sys
J = json.load(open('whatif/_scratch/pos_keep.json')); R = json.load(open('whatif/_scratch/rotov_keep2.json'))
for it in [s for s in sys.argv[1].split(';') if s]:
    r, dx, dy, rot = it.split(':')
    J[r] = [round(J[r][0] + float(dx), 3), round(J[r][1] + float(dy), 3)]
    if rot != '-': R[r] = int(rot)
json.dump(J, open('whatif/_scratch/relay_pos.json', 'w'), indent=1); json.dump(R, open('whatif/_scratch/rotov.json', 'w'), indent=1)
P
python3 kicad/relayout/gen_layout.py >/dev/null
bash whatif/_scratch/run_rel.sh 2>&1 | grep -v Debug | tail -3
python3 whatif/_scratch/assemble_final.py >/dev/null 2>&1
echo "ROWS $LABEL: $(python3 kicad/relayout/netdiff.py whatif/_scratch/final/afe-proto.kicad_pcb | tail -1)"
cp whatif/_scratch/final/afe-proto.kicad_pcb whatif/_scratch/rows_${LABEL}_final.kicad_pcb
python3 whatif/_scratch/hpwl.py whatif/_scratch/final/afe-proto.kicad_pcb 2>&1 | grep HPWL
python3 whatif/_scratch/stage1.py whatif/_scratch/final/afe-proto.kicad_pcb whatif/_scratch/rows_fixed.kicad_pcb 2>&1 | awk '{printf "%s %s; ", $1, $3}'; echo
INFL_HIZ=0.85 python3 whatif/_scratch/pf1.py whatif/_scratch/rows_fixed.kicad_pcb whatif/_scratch/rows_${LABEL}_routed.kicad_pcb 25 400 2>&1 | grep -v Debug | grep "^iter 24\|METRIC" | cut -c1-200
python3 -m pcbtools.check whatif/_scratch/rows_${LABEL}_final.kicad_pcb --config v1 2>&1 | grep -v Debug | grep "LR-11\|LR-12\|LR-5\|LR-3\|LR-4\|LR-2\|LR-7" | cut -c1-200
python3 -m pcbtools.check whatif/_scratch/rows_${LABEL}_routed.kicad_pcb --config v1 2>&1 | grep -v Debug | grep "LR-8\|LR-6\|LR-9" | cut -c1-200
cp whatif/_scratch/pos_keep.json whatif/_scratch/relay_pos.json; cp whatif/_scratch/rotov_keep2.json whatif/_scratch/rotov.json
