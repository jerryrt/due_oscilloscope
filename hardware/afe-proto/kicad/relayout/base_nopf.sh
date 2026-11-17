#!/bin/bash
# base_nopf.sh: rebuild the live placement (pos_keep) and keep it as base_final (no pf)
cd /work/hardware/afe-proto && export PYTHONPATH=.
cp whatif/_scratch/pos_keep.json whatif/_scratch/relay_pos.json; cp whatif/_scratch/rotov_keep2.json whatif/_scratch/rotov.json; cp whatif/_scratch/labmode_keep.json whatif/_scratch/labmode.json
python3 kicad/relayout/gen_layout.py >/dev/null
bash whatif/_scratch/run_rel.sh 2>&1 | grep -v Debug | tail -3
python3 whatif/_scratch/assemble_final.py >/dev/null 2>&1
python3 kicad/relayout/netdiff.py whatif/_scratch/final/afe-proto.kicad_pcb | tail -1
cp whatif/_scratch/final/afe-proto.kicad_pcb whatif/_scratch/base_final.kicad_pcb
