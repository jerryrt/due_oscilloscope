#!/bin/bash
# try2.sh K2 REST2json : apply the CH2 template translation K2 with the three remaining parts, build and route CH2's HIZ nets
cd /work/hardware/afe-proto && export PYTHONPATH=.
K2=$1 REST2="$2" python3 whatif/_scratch/apply_both.py > /dev/null
git checkout -q kicad/layout.py 2>/dev/null
python3 whatif/_scratch/gen_layout.py > /dev/null 2>&1
bash whatif/_scratch/run_rel.sh 300 > /dev/null 2>&1
python3 whatif/_scratch/assemble_final.py > /dev/null 2>&1
CHANNELS=/CH2 python3 whatif/_scratch/hiz_route_fn.py 2>&1 | grep CHANNEL
