#!/bin/sh
# usage (in the image, cwd /work): gates.sh SPEC.py TAG   -> splice onto the committed board, refill zones on the copy, all LR rows, DRC by type, unconnected
R=hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock
B=hardware/afe-proto/v2/layout/integrated/afe-v2-integrated.kicad_pcb
python3 $R/hand/hr.py $B $R/hand/g_$2.kicad_pcb $1 >/dev/null
cp hardware/afe-proto/v2/layout/integrated/afe-v2-integrated.kicad_pro $R/hand/g_$2.kicad_pro
python3 - $R/hand/g_$2.kicad_pcb $1 $R/hand/pads.json <<'PY'
import sys, json, re
# the AWG_FB keep-back rule area (F.Cu, no top pour) follows the node: the bounding box of its pads and routed copper, plus 0.6 mm
t = open(sys.argv[1]).read(); ns = {}; exec(open(sys.argv[2]).read(), ns)
xs, ys = [], []
for p in json.load(open(sys.argv[3])):
    if p['net'] == '/AWG_FB': xs += [p['bb'][0], p['bb'][2]]; ys += [p['bb'][1], p['bb'][3]]
for net, lay, pts, w in ns['ROUTES']:
    if net == '/AWG_FB':
        for x, y in pts: xs += [x - w / 2, x + w / 2]; ys += [y - w / 2, y + w / 2]
x0, x1, y0, y1 = min(xs) - 0.6, max(xs) + 0.6, min(ys) - 0.6, max(ys) + 0.6
new = '(xy %.3f %.3f) (xy %.3f %.3f) (xy %.3f %.3f) (xy %.3f %.3f)' % (x0 + 50, 150 - y1, x1 + 50, 150 - y1, x1 + 50, 150 - y0, x0 + 50, 150 - y0)
m = re.search(r'\(xy 131\.3 131\.654999\) \(xy 135\.35 131\.654999\) \(xy 135\.35 144\.385\) \(xy 131\.3 144\.385\)', t)
if m: open(sys.argv[1], 'w').write(t.replace(m.group(0), new, 1)); print('AWG_FB keep-back: Due x %.2f-%.2f, y %.2f-%.2f' % (x0, x1, y0, y1))
else: print('keepout rectangle not found')
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
