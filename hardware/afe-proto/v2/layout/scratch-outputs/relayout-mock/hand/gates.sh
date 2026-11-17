#!/bin/sh
# usage (in the image, cwd /work): gates.sh SPEC.py TAG   -> splice onto the committed board, refill zones on the copy, all LR rows, DRC by type, unconnected
R=hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock
B=hardware/afe-proto/v2/layout/integrated/afe-v2-integrated.kicad_pcb
python3 $R/hand/hr.py $B $R/hand/g_$2.kicad_pcb $1 >/dev/null
cp hardware/afe-proto/v2/layout/integrated/afe-v2-integrated.kicad_pro $R/hand/g_$2.kicad_pro
python3 - $R/hand/g_$2.kicad_pcb <<'PY'
import sys
t = open(sys.argv[1]).read()
old = '(xy 131.3 131.654999) (xy 135.35 131.654999) (xy 135.35 144.385) (xy 131.3 144.385)'
new = '(xy 124.675 134.675) (xy 129.715 134.675) (xy 129.715 145.885) (xy 124.675 145.885)'    # AWG_FB keep-back: its pads and tracks plus 0.6 mm
if old in t: open(sys.argv[1], 'w').write(t.replace(old, new, 1))
else: print('keepout rectangle not found (already moved?)')
PY
python3 - $R/hand/g_$2.kicad_pcb <<'PY'
import sys
sys.path.insert(0, '/work/hardware/afe-proto')
from pcbtools.editor import edit
with edit(sys.argv[1]) as e:
    e.fill_zones()
PY
echo "--- rows (zones refilled)"
(cd hardware/afe-proto && python3 -m pcbtools.check /work/$R/hand/g_$2.kicad_pcb --config v2_layout --no-drc) 2>&1 | grep -E "^\[|^FAIL" | cut -c1-300
echo "--- DRC"
(cd $R/hand && kicad-cli pcb drc --severity-all --format json -o drc_g_$2.json g_$2.kicad_pcb >/dev/null 2>&1; python3 - $2 <<'PY'
import json, sys
from collections import Counter
d = json.load(open('drc_g_%s.json' % sys.argv[1]))
print(dict(Counter(v['type'] for v in d['violations'])), 'unconnected', len(d.get('unconnected_items', [])))
PY
)
