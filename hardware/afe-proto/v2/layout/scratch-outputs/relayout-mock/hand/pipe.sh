#!/bin/sh
# usage (in the image, cwd /work): pipe.sh SEED JIT   -> CSP both channels, apply, route the hi-Z nets, report lengths
R=hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock
S=$1; J=$2; T=/work/$R
cd /work/$R
rm -f csp_CH1_*.json csp_CH2_*.json
BLK=CH1 SEED=$S JIT=$J TL=30 python3 -u cspfit.py > hand/pipe_c1_$S.txt 2>&1
ls csp_CH1_*.json >/dev/null 2>&1 || { echo "seed $S: no CH1 fit"; exit 0; }
cp csp_CH1_*.json other_CH1.json
BLK=CH2 SEED=$S JIT=$J TL=30 OTHERFILE=$T/other_CH1.json python3 -u cspfit.py > hand/pipe_c2_$S.txt 2>&1
ls csp_CH2_*.json >/dev/null 2>&1 || { echo "seed $S: no CH2 fit"; exit 0; }
python3 - <<PY
import json, glob
st = {}
for f in sorted(glob.glob('csp_CH1_*.json')) + sorted(glob.glob('csp_CH2_*.json')): st.update(json.load(open(f))['st'])
st['U301'] = [76.56, 9.71, 90.0, 0]
json.dump(dict(st=st), open('hand/pipe_place_$S.json', 'w'))
open('hand/pipe_eb_$S.txt', 'w').write(','.join(sorted(r for r, v in st.items() if v[3] >= 10 and r != 'U301')))
PY
cd /work
sh $R/hand/eval_place.sh $R/hand/pipe_place_$S.json $R/hand/pipe_$S.kicad_pcb
cd $R/route
HZ=CH1_N,CH1_M1,CH1_M2,CH1_M3,CH1_NP,CH2_N,CH2_M1,CH2_M2,CH2_M3,CH2_NP
ONLYNETS=$HZ ROUTE_IN=$T/hand/pipe_$S.kicad_pcb ROUTE_OUT=$T/hand/pipe_$S.routed.kicad_pcb RIPUP_SECONDS=30 RIPUP_ROUNDS=1 python3 -I route3.py > $T/hand/pipe_r_$S.txt 2>&1
grep -E "saved|unrouted" $T/hand/pipe_r_$S.txt | tr '\n' ' ' | cut -c1-200
python3 $T/hand/hizlen.py $T/hand/pipe_$S.routed.kicad_pcb
