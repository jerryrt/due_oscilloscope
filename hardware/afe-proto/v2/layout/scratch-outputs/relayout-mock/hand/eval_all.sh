#!/bin/sh
# usage (in the image, cwd /work): eval_all.sh PLACEMENT.json OUT.kicad_pcb BESIDE_CSV
R=hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock
sh $R/hand/eval_place.sh $1 $2
echo "--- silkread/align"; EXTRA_BESIDE=$3 python3 $R/ac.py $2 2>&1 | grep -E "silkread|^   |^align" | head -14 | cut -c1-200
echo "--- relayout_check"; python3 hardware/afe-proto/v2/layout/relayout_check.py $2 $R/base.kicad_pcb 2>&1 | grep -v "Debug\|capped" | cut -c1-140
echo "--- rows"; (cd hardware/afe-proto && python3 -m pcbtools.check /work/$2 --config v2_layout --no-drc) 2>&1 | grep -E "^\[|^FAIL" | cut -c1-260
echo "--- lanes"; python3 hardware/afe-proto/v2/layout/relayout_dump.py $2 $R/hand/dump_eval.json >/dev/null 2>&1; python3 $R/lanecheck.py /work/$R/hand/dump_eval.json 2>&1 | grep -E "lane check|LABEL|PART"
echo "--- hiz"; python3 $R/hand/hiz.py /work/$2 2>&1 | grep -v capped
