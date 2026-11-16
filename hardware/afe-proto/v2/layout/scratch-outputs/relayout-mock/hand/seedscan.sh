#!/bin/sh
R=hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock
cd /work
for S in 3 4 5 8 9 11; do
  python3 hardware/afe-proto/v2/layout/relayout_dump.py $R/hand/pipe_$S.kicad_pcb $R/hand/dump_pipe_$S.json >/dev/null 2>&1
  echo "seed $S: $(python3 $R/hand/ambcheck.py $R/hand/pipe_place_$S.json $R/hand/dump_pipe_$S.json) | $(EXTRA_BESIDE=$(cat $R/hand/pipe_eb_$S.txt) python3 $R/ac.py $R/hand/pipe_$S.kicad_pcb 2>&1 | grep -E '^silkread|^align' | tr '\n' ' ')"
done
