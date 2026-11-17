#!/bin/sh
# usage (in the image, cwd /work): evalvariant.sh TAG POS.json [BRIDGES.py]  -> hand/TAG_*.kicad_pcb, TAG.txt (pf), TAG_gates.txt, TAG_checks.txt
R=hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock
H=/work/$R/hand
T=$1; POS=$2; BR=$3
cd $H
python3 - $POS $T <<'PY'
import json, re, sys
pl = json.load(open(sys.argv[1])); t = open('/work/hardware/afe-proto/v2/layout/integrated/afe-v2-integrated.kicad_pcb').read()
for ref, (x, y, rot) in pl.items():
    i = t.index('(property "Reference" "%s"' % ref); s = t.rfind('\n\t(footprint ', 0, i)
    m = re.compile(r'\(at ([\d.\-]+) ([\d.\-]+)(?: ([\d.\-]+))?\)').search(t, s)
    t = t[:m.start()] + '(at %.4f %.4f %g)' % (x + 50, 150 - y, rot) + t[m.end():]
open(sys.argv[2] + '_1.kicad_pcb', 'w').write(t)
PY
python3 redo_outlines.py ${T}_1.kicad_pcb ${T}_2.kicad_pcb 'REFCAL=45.5,4.6,65.0,27.8' 'AWG=69.5,4.55,92.25,19.25;98.55,0.75,116.4,16.5' | tail -1
if [ -n "$BR" ]; then python3 add_bridges.py ${T}_2.kicad_pcb ${T}_2b.kicad_pcb $BR && mv ${T}_2b.kicad_pcb ${T}_2.kicad_pcb; fi
cp S1.kicad_pro ${T}_2.kicad_pro
MOVED=$(python3 -c "import json;print(','.join(json.load(open('$POS'))))")
LABELS_JSON=$LABJ ABOVE_ONLY=1 python3 labelplace.py ${T}_2.kicad_pcb ${T}_4.kicad_pcb $MOVED 2>&1 | grep -E 'silkread findings|beside set|could not'
cp S1.kicad_pro ${T}_4.kicad_pro
python3 hr.py ${T}_4.kicad_pcb ${T}_5.kicad_pcb fixed_noGND.py > /dev/null; cp S1.kicad_pro ${T}_5.kicad_pro
python3 -u pf.py ${T}_5.kicad_pcb ${T}_spec.py ${ROUNDS:-14} 900 > $T.txt 2>&1
grep METRIC $T.txt
cd /work && BASE=$R/hand/${T}_5.kicad_pcb sh $R/hand/gates.sh $R/hand/${T}_spec.py $T > $R/hand/${T}_gates.txt 2>&1
(python3 hardware/afe-proto/v2/layout/relayout_check.py $R/hand/${T}_4.kicad_pcb $R/before.kicad_pcb 2>&1 | grep -E 'courtyard|findings|fixed' ; python3 hardware/afe-proto/v2/layout/relayout_dump.py $R/hand/${T}_4.kicad_pcb /tmp/d_$T.json && python3 $R/lanecheck.py /tmp/d_$T.json 2>&1 | tail -2; python3 $R/ac.py $R/hand/${T}_4.kicad_pcb 2>&1 | grep -E '^silkread|^align'; python3 $R/hand/srcheck.py $R/hand/${T}_4.kicad_pcb | head -12) > $R/hand/${T}_checks.txt 2>&1
