#!/bin/sh
# usage: tweak_eval.sh TAG  (placement hand/r206_TAG.json)
R=hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock
T=/work/$R
cd /work
sh $R/hand/eval_place.sh $R/hand/r206_$1.json $R/hand/r206_$1.kicad_pcb
EB=$(cat $R/hand/chosen_eb.txt)
echo "silk/align: $(EXTRA_BESIDE=$EB python3 $R/ac.py $R/hand/r206_$1.kicad_pcb 2>&1 | grep -E '^silkread|^align' | tr '\n' ' ')"
python3 hardware/afe-proto/v2/layout/relayout_check.py $R/hand/r206_$1.kicad_pcb $R/base.kicad_pcb 2>&1 | grep -E "findings|R206|C202"
python3 hardware/afe-proto/v2/layout/relayout_dump.py $R/hand/r206_$1.kicad_pcb $R/hand/dump_r206_$1.json >/dev/null 2>&1
python3 $R/lanecheck.py $T/hand/dump_r206_$1.json | grep "lane check"
echo "amb above-only: $(AMBBOTH=0 python3 $R/hand/ambcheck.py $R/hand/r206_$1.json $R/hand/dump_r206_$1.json)"
python3 $R/hand/hiz.py $T/hand/r206_$1.kicad_pcb 2>&1 | grep -E "CH2_(NP|M3)"
cd $R/route
ONLYNETS=CH1_N,CH1_M1,CH1_M2,CH1_M3,CH1_NP,CH2_N,CH2_M1,CH2_M2,CH2_M3,CH2_NP,CH1_OUT,CH2_OUT ROUTE_IN=$T/hand/r206_$1.kicad_pcb ROUTE_OUT=$T/hand/r206_$1.routed.kicad_pcb RIPUP_SECONDS=60 RIPUP_ROUNDS=2 python3 -I route3.py 2>&1 | tail -n 1
python3 $T/hand/hizlen.py $T/hand/r206_$1.routed.kicad_pcb
