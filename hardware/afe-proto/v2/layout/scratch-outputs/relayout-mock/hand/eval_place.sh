#!/bin/sh
# usage: eval_place.sh PLACEMENT.json OUT.kicad_pcb  (applies to the committed board copy, restores J603's label shift, runs checks)
R=hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock
B=hardware/afe-proto/v2/layout/integrated/afe-v2-integrated.kicad_pcb
python3 hardware/afe-proto/v2/layout/relayout_apply.py $B $R/dump_all.json $2 $1 2>&1 | grep -E "Error|Trace"
python3 - $2 <<'PY'
import sys
s = open(sys.argv[1]).read()
old = '(property "Reference" "J603"\n\t\t\t(at 2.615 8.89 0)'
assert s.count(old) == 1
open(sys.argv[1], 'w').write(s.replace(old, '(property "Reference" "J603"\n\t\t\t(at 2.615 9.19 0)'))
PY
