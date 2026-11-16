#!/bin/sh
# usage (in the image, cwd /work): combo.sh CH1.json CH2.json TAG
R=hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock
T=/work/$R
python3 - $1 $2 $3 <<'PY'
import json, sys
st = {}
for f in sys.argv[1:3]: st.update(json.load(open(f))['st'])
st['U301'] = [76.56, 9.71, 90.0, 0]
tag = sys.argv[3]
json.dump(dict(st=st), open('hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock/hand/combo_%s.json' % tag, 'w'))
open('hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock/hand/combo_eb_%s.txt' % tag, 'w').write(','.join(sorted(r for r, v in st.items() if v[3] >= 10 and r != 'U301')))
PY
sh $R/hand/eval_place.sh $R/hand/combo_$3.json $R/hand/combo_$3.kicad_pcb
echo "gap: $(python3 $R/hand/gap2.py /work/$R/hand/combo_$3.kicad_pcb 2>&1 | grep -v capped | cut -c1-90)"
cd $R/route
ONLYNETS=CH1_N,CH1_M1,CH1_M2,CH1_M3,CH1_NP,CH2_N,CH2_M1,CH2_M2,CH2_M3,CH2_NP ROUTE_IN=$T/hand/combo_$3.kicad_pcb ROUTE_OUT=$T/hand/combo_$3.routed.kicad_pcb RIPUP_SECONDS=30 RIPUP_ROUNDS=1 python3 -I route3.py > $T/hand/combo_r_$3.txt 2>&1
grep -E "unrouted" $T/hand/combo_r_$3.txt | tr '\n' ' ' | cut -c1-120
python3 $T/hand/hizlen.py $T/hand/combo_$3.routed.kicad_pcb
cd /work
echo "SUMMARY $3 beside: $(cat $T/hand/combo_eb_$3.txt | tr ',' '\n' | grep -c .) $(EXTRA_BESIDE=$(cat $T/hand/combo_eb_$3.txt) python3 $R/ac.py $R/hand/combo_$3.kicad_pcb 2>&1 | grep -E '^silkread|^align' | tr '\n' ' ')"
python3 hardware/afe-proto/v2/layout/relayout_check.py $R/hand/combo_$3.kicad_pcb $R/base.kicad_pcb 2>&1 | grep -E "findings"
