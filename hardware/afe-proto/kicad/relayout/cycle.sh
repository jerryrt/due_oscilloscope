#!/bin/bash
# cycle.sh [ITER]: schematic -> board -> assemble -> stage1 -> pf1 -> conflict count, all inside the pcb image
cd /work/hardware/afe-proto && export PYTHONPATH=.
N=${1:-10}
PCBTOOLS_V1_SOURCE=kicad python3 -c '
import subprocess
from pcbtools import schematic as sch
from pcbtools.boards import v1
sch.write_all(v1.PARTS, v1.sch_cfg(), "kicad")
subprocess.run(["kicad-cli","sch","upgrade","kicad/afe-proto.kicad_sch"],capture_output=True,check=True)
' 2>&1 | grep -v Debug
python3 kicad/relayout/gen_layout.py
bash whatif/_scratch/run_rel.sh 2>&1 | grep -v Debug | tail -8
python3 whatif/_scratch/assemble_final.py 2>&1 | grep -v Debug | tail -1
python3 kicad/relayout/netdiff.py whatif/_scratch/final/afe-proto.kicad_pcb | tail -2
python3 whatif/_scratch/stage1.py whatif/_scratch/final/afe-proto.kicad_pcb whatif/_scratch/route2/fixed.kicad_pcb 2>&1 | grep -c "fails \[\]"
python3 whatif/_scratch/pf1.py whatif/_scratch/route2/fixed.kicad_pcb whatif/_scratch/route2/pf_out.kicad_pcb $N 400 2>&1 | grep -v Debug | grep "^iter\|wrote" | tail -2 | cut -c1-700
