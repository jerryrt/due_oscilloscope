#!/bin/sh
# in the image, cwd /work. what-ifs on V22 (pf numbers only): R308/R309 swap, BR501 AREF over SDA, one +5V_F bridge at U401
R=hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock; H=/work/$R/hand; cd $H
python3 - <<'PY'
import json
d = json.load(open('fl22.json'))
C = json.load(open('main_vs_cur.json'))['cur']
d2 = dict(d); a, b = list(C['R308']), list(C['R309'])
d2['R308'], d2['R309'] = b, a                      # slot swap (neither is an inverting node: AWG_OA / AWG_OB, op-amp outputs)
json.dump(d2, open('fl22_swap.json', 'w'))
PY
python3 bridgeplan.py V22_spec.py V22_2.kicad_pcb wi_br501.py BR501:46.8:27.4:/AREF:/SDA > wi_br501.log 2>&1
python3 bridgeplan.py V22_spec.py V22_2.kicad_pcb wi_br401.py BR401:32.0:15.8:/+5V_F:/LM_FBP > wi_br401.log 2>&1
cd /work
LABJ=$H/fl22_labels.json sh $R/hand/evalvariant.sh W_swap $H/fl22_swap.json > $H/W_swap_run.txt 2>&1
LABJ=$H/fl22_labels.json sh $R/hand/evalvariant.sh W_br501 $H/fl22.json $H/wi_br501.py > $H/W_br501_run.txt 2>&1
LABJ=$H/fl22_labels.json sh $R/hand/evalvariant.sh W_br401 $H/fl22.json $H/wi_br401.py > $H/W_br401_run.txt 2>&1
