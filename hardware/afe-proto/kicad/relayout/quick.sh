#!/bin/bash
# quick.sh LABEL SPEC : apply ref:dx:dy:rot moves to pos_keep, rebuild, netdiff, HPWL, stage1 pre-route fails (no pf)
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
echo "Q $LABEL: $(python3 kicad/relayout/netdiff.py whatif/_scratch/final/afe-proto.kicad_pcb | tail -1)"
cp whatif/_scratch/final/afe-proto.kicad_pcb whatif/_scratch/q_${LABEL}_final.kicad_pcb
python3 whatif/_scratch/hpwl.py whatif/_scratch/final/afe-proto.kicad_pcb 2>&1 | grep HPWL
python3 whatif/_scratch/stage1.py whatif/_scratch/final/afe-proto.kicad_pcb whatif/_scratch/q_fixed.kicad_pcb 2>&1 | grep -v Debug | grep -v "fails \[\]" | cut -c1-160
python3 -m pcbtools.check whatif/_scratch/q_${LABEL}_final.kicad_pcb --config v1 2>&1 | grep -v Debug | grep -i "fail\|LR-1[12]\|LR-5\|LR-3\|LR-2 \|LR-7" | cut -c1-220
cp whatif/_scratch/pos_keep.json whatif/_scratch/relay_pos.json; cp whatif/_scratch/rotov_keep2.json whatif/_scratch/rotov.json
