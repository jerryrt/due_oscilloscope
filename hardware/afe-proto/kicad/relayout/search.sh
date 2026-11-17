#!/bin/bash
# search.sh CANDFILE WINDOW OPENNETS : one candidate per line "label|ref:dx:dy:rot;ref:dx:dy:rot" (rot = new rotation or - to keep)
cd /work/hardware/afe-proto && export PYTHONPATH=.
CAND=$1; WIN=$2; OPEN=$3
while IFS='|' read -r label spec; do
  [ -z "$label" ] && continue
  python3 - "$spec" <<'P'
import json, sys
J = json.load(open('whatif/_scratch/pos_keep.json')); R = json.load(open('whatif/_scratch/rotov_keep2.json'))
rotbase = json.load(open('whatif/_scratch/rot.json'))
moved = []
LM = json.load(open('whatif/_scratch/labmode_keep.json'))
for it in [s for s in sys.argv[1].split(';') if s]:
    r, dx, dy, rot = it.split(':')
    if r == 'LAB':
        LM[dx] = dy; continue
    J[r] = [round(J[r][0] + float(dx), 3), round(J[r][1] + float(dy), 3)]
    if rot != '-': R[r] = int(rot)
    moved.append(r)
json.dump(J, open('whatif/_scratch/relay_pos.json', 'w'), indent=1); json.dump(R, open('whatif/_scratch/rotov.json', 'w'), indent=1); json.dump(LM, open('whatif/_scratch/labmode.json', 'w'), indent=1)
open('whatif/_scratch/moved.txt', 'w').write(','.join(moved))
P
  python3 kicad/relayout/gen_layout.py >/dev/null
  SR=$(bash whatif/_scratch/run_rel.sh 2>&1 | grep -v Debug | tail -4 | tr '\n' ';' | cut -c1-260)
  python3 whatif/_scratch/assemble_final.py >/dev/null 2>&1
  cp whatif/_scratch/final/afe-proto.kicad_pcb whatif/_scratch/cand_${label}_final.kicad_pcb
  ND=$(python3 kicad/relayout/netdiff.py whatif/_scratch/final/afe-proto.kicad_pcb | tail -1)
  HP=$(python3 whatif/_scratch/hpwl.py whatif/_scratch/final/afe-proto.kicad_pcb 2>&1 | grep HPWL | cut -c1-200)
  python3 whatif/_scratch/stage1.py whatif/_scratch/final/afe-proto.kicad_pcb whatif/_scratch/cand_fixed.kicad_pcb 2>&1 | grep "CH2_\|CH1_" | awk '{printf "%s %s; ", $1, $3}'
  echo
  LE=$(python3 kicad/relayout/local_eval.py whatif/_scratch/cand_fixed.kicad_pcb whatif/_scratch/base_fixed.kicad_pcb whatif/_scratch/base_routed.kicad_pcb "$OPEN" "$(cat whatif/_scratch/moved.txt)" "$WIN" 12 2>&1 | tail -1)
  echo "CAND $label | $ND | $LE | $HP | silk: $SR"
done < $CAND
cp whatif/_scratch/pos_keep.json whatif/_scratch/relay_pos.json; cp whatif/_scratch/rotov_keep2.json whatif/_scratch/rotov.json; cp whatif/_scratch/labmode_keep.json whatif/_scratch/labmode.json
