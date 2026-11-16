#!/bin/bash
# runb.sh BLOCK SEED ITERS : one block, the others' positions from the files named in $PREV (default: the last set)
L=hardware/afe-proto/v2/layout; R=$L/scratch-outputs/relayout-mock
b=$1; s=$2; n=$3; others=""
for o in POWER REFCAL CH1 AWG CH2; do [ $o = $b ] && continue; others="$others $(ls -t $R/pl_${o}_[0-9]*.json | head -1)"; done
docker/pcb/run.sh -m 1G -t 900 python3 $L/relayout_place.py $R/dump_all.json $R/pl_${b}_$s.json $b $s $n $others > $R/log_${b}_$s.txt 2>&1
