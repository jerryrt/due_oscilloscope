#!/bin/bash
# base_save.sh: rebuild the approved placement, pre-route, run pf1 (25 it) and keep the boards as the local-search baseline
cd /work/hardware/afe-proto && export PYTHONPATH=.
python3 kicad/relayout/gen_layout.py >/dev/null
bash whatif/_scratch/run_rel.sh 2>&1 | grep -v Debug | tail -1
python3 whatif/_scratch/assemble_final.py >/dev/null 2>&1
python3 kicad/relayout/netdiff.py whatif/_scratch/final/afe-proto.kicad_pcb | tail -1
cp whatif/_scratch/final/afe-proto.kicad_pcb whatif/_scratch/base_final.kicad_pcb
python3 whatif/_scratch/stage1.py whatif/_scratch/final/afe-proto.kicad_pcb whatif/_scratch/base_fixed.kicad_pcb 2>&1 | grep -c "fails \[\]"
INFL_HIZ=0.85 python3 whatif/_scratch/pf1.py whatif/_scratch/base_fixed.kicad_pcb whatif/_scratch/base_routed.kicad_pcb 25 400 2>&1 | grep -v Debug | grep "^iter 24\|METRIC"
