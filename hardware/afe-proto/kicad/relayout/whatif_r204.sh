#!/bin/bash
# whatif_r204.sh DX DY : move R204 by (DX, DY) from its approved position, rebuild, report
cd /work/hardware/afe-proto && export PYTHONPATH=.
python3 - "$1" "$2" <<'P'
import json, sys
dx, dy = float(sys.argv[1]), float(sys.argv[2])
J = json.load(open('whatif/_scratch/pos_keep.json'))
J['R204'] = [round(J['R204'][0] + dx, 3), round(J['R204'][1] + dy, 3)]
json.dump(J, open('whatif/_scratch/relay_pos.json', 'w'), indent=1)
P
python3 kicad/relayout/gen_layout.py >/dev/null
bash whatif/_scratch/run_rel.sh 2>&1 | grep -v Debug | tail -6
python3 whatif/_scratch/assemble_final.py 2>&1 | grep -v Debug | tail -1 >/dev/null
python3 kicad/relayout/netdiff.py whatif/_scratch/final/afe-proto.kicad_pcb | tail -1
python3 whatif/_scratch/hpwl.py whatif/_scratch/final/afe-proto.kicad_pcb 2>&1 | grep HPWL
python3 whatif/_scratch/stage1.py whatif/_scratch/final/afe-proto.kicad_pcb whatif/_scratch/route2/fixed.kicad_pcb 2>&1 | grep "CH2_\|AWG_INV" | tr '\n' ' '; echo
INFL_HIZ=0.85 python3 whatif/_scratch/pf1.py whatif/_scratch/route2/fixed.kicad_pcb whatif/_scratch/route2/pf1_w.kicad_pcb 25 400 2>&1 | grep -v Debug | grep "^iter 24\|^PAIRS" | cut -c1-300
