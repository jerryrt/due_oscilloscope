#!/bin/bash
cd /work/hardware/afe-proto && export PYTHONPATH=.
python3 whatif/_scratch/stage0_lanes.py whatif/_scratch/base_final.kicad_pcb whatif/_scratch/fr/lanes.kicad_pcb 2>&1 | grep LANES
LANENETS=/VREF,/+3V3A,/VNEG python3 whatif/_scratch/stage2_gnd.py whatif/_scratch/fr/lanes.kicad_pcb whatif/_scratch/fr/gnd.kicad_pcb 2>&1 | grep -v Debug | tail -3
LANENETS=/VREF,/+3V3A,/VNEG SRC=whatif/_scratch/fr/gnd.kicad_pcb DST=whatif/_scratch/fr/pre.kicad_pcb MAXIT=1 python3 whatif/_scratch/stage1b.py 2>&1 | grep -v Debug | grep STAGE1B | cut -c1-300
for M in $1; do
  python3 kicad/relayout/fr_run2.py $M whatif/_scratch/fr/pre.kicad_pcb whatif/_scratch/fr/out$M.kicad_pcb 40 1800 2>&1 | grep -v Debug | grep "LOCKED\|FREEROUTING\|import\|POST\|BOTTOM\|saved\|Error\|Trace"
  python3 - <<P
from pcbtools.editor import edit
with edit('whatif/_scratch/fr/out$M.kicad_pcb') as e:
    e.pour('GND', 'B')
P
  cp whatif/_scratch/fr/in.kicad_pro whatif/_scratch/fr/out$M.kicad_pro
  echo "RUN $M: $(python3 kicad/relayout/netdiff.py whatif/_scratch/fr/out$M.kicad_pcb | tail -1)"
  python3 -m pcbtools.check whatif/_scratch/fr/out$M.kicad_pcb --config v1 --drc 2>&1 | grep -v Debug | cut -c1-300
  cp whatif/_scratch/fr/out$M.kicad_pcb whatif/_scratch/fr/d$M.kicad_pcb; cp whatif/_scratch/fr/in.kicad_pro whatif/_scratch/fr/d$M.kicad_pro
  (cd whatif/_scratch/fr && kicad-cli pcb drc --format json --severity-all --all-track-errors -o d$M.json d$M.kicad_pcb >/dev/null 2>&1)
  python3 kicad/relayout/gaps.py whatif/_scratch/fr/d$M.json
done
