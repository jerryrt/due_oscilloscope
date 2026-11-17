#!/bin/bash
# run_AB.sh: rebuild the live placement, then the strict S run + hop measurement for bus variant A and for variant B
cd /work/hardware/afe-proto && export PYTHONPATH=.
export KEEPPARTIAL=1
# placement already built
for V in A B; do
  echo "=== VARIANT $V"
  BUS=$V bash kicad/relayout/run_SR.sh S > whatif/_scratch/fr/log_$V.txt 2>&1
  cp whatif/_scratch/fr/outS.kicad_pcb whatif/_scratch/fr/outS_$V.kicad_pcb
  cp whatif/_scratch/fr/lanes.kicad_pcb whatif/_scratch/fr/lanes_$V.kicad_pcb
  python3 kicad/relayout/hops.py whatif/_scratch/fr/outS_$V.kicad_pcb > whatif/_scratch/fr/hops_$V.txt 2>&1
  grep -v Debug whatif/_scratch/fr/log_$V.txt | grep "LANE\|LOCKS\|STAGE1B\|LOCKED\|RUN S\|^\[FAIL\|^FAIL\|GAPS" | cut -c1-400
  grep "^SUMMARY\|GAPS (spanning" whatif/_scratch/fr/hops_$V.txt
done
