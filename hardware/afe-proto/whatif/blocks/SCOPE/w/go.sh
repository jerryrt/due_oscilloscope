#!/bin/bash
# go.sh : build -> silk -> SCOPE.kicad_pcb -> fence -> DRC report -> png
cd /home/jerry/EE.Projects/due_oscilloscope_kvm01/hardware/afe-proto/whatif/blocks/SCOPE/w
./run.sh build.py whatif/blocks/SCOPE/w/orig.kicad_pcb whatif/blocks/SCOPE/w/b1.kicad_pcb 2>&1 | grep -E "built|rror|Trace|File"
./run.sh silk.py whatif/blocks/SCOPE/w/b1.kicad_pcb whatif/blocks/SCOPE/w/b2.kicad_pcb 2>&1 | grep -E "NO SPOT|rror|Trace|File"
cp b2.kicad_pcb ../SCOPE.kicad_pcb
./run.sh chk.py whatif/blocks/SCOPE/SCOPE.kicad_pcb 2>&1 | grep -E "fence|^  "
./run.sh drc.sh 2>&1 | grep -v capped
python3 drcrep.py | grep -v -E "Missing connection|lib_footprint|via_dangling|track_dangling" | cut -c1-260
./run.sh mychk.py whatif/blocks/SCOPE/SCOPE.kicad_pcb 2>&1 | grep -v -E "Debug|capped"
./png.sh ../SCOPE.kicad_pcb 63 17 100 51 cur.png 30
