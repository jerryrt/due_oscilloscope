#!/bin/sh
# usage (in the image, cwd /work): frroute.sh TAG BOARD_WITH_LABELS.kicad_pcb [BASE_FIXED_FIRST: 1]
#   hi-Z, outputs, AWG_FB, A0/A1 (fixed_noGND.py) and pf's star / Kelvin legs and GND vias are spliced as LOCKED copper; Freerouting routes the rest with B.Cu forbidden
#   (a keep-out over the whole board on B.Cu; the GND vias are already placed), 0.2 mm tracks, hi-Z class clearance 0.6; then ImportSpecctraSES, DRC and the rows.
R=hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock
H=/work/$R/hand
T=$1; B=$2
cd $H
cp $B ${T}_f0.kicad_pcb; cp S1.kicad_pro ${T}_f0.kicad_pro
python3 hr.py ${T}_f0.kicad_pcb ${T}_f1.kicad_pcb fixed_noGND.py > /dev/null; cp S1.kicad_pro ${T}_f1.kicad_pro
# pf: the star and Kelvin nets only (and the GND vias)
PF_ONLY='^/(\+3V3A|VNEG|VREF)' python3 -u pf.py ${T}_f1.kicad_pcb ${T}_k_spec.py 14 600 > ${T}_k.txt 2>&1
grep METRIC ${T}_k.txt
python3 hr.py ${T}_f1.kicad_pcb ${T}_f2.kicad_pcb ${T}_k_spec.py > /dev/null; cp S1.kicad_pro ${T}_f2.kicad_pro
# lock every segment and via on the board, set the hi-Z class, export the DSN
python3 - ${T} <<'PY'
import re, sys, json
T = sys.argv[1]
t = open(T + '_f2.kicad_pcb').read()
t = re.sub(r'(\n\t\((?:segment|via)\n(?:(?!\n\t\)).)*?)(\n\t\t\(uuid )', lambda m: m.group(1) + '\n\t\t(locked yes)' + m.group(2), t, flags=re.S)
open(T + '_f3.kicad_pcb', 'w').write(t)
d = json.load(open('S1.kicad_pro'))
hiz = ['/CH1_N', '/CH1_M1', '/CH1_M2', '/CH1_M3', '/CH1_NP', '/CH2_N', '/CH2_M1', '/CH2_M2', '/CH2_M3', '/CH2_NP']
ns = d.setdefault('net_settings', {})
cl = ns.setdefault('classes', [])
base = dict(cl[0]) if cl else {}
cl.append(dict(base, name='HIZ', clearance=0.6, track_width=0.2, via_diameter=0.6, via_drill=0.3, wire_width=base.get('wire_width', 6)))
ns['netclass_patterns'] = [{'netclass': 'HIZ', 'pattern': n} for n in hiz]
for c in cl:
    c['track_width'] = 0.2
json.dump(d, open(T + '_f3.kicad_pro', 'w'), indent=2)
PY
python3 - ${T} <<'PY'
import sys, re
sys.path.append('/usr/lib/python3/dist-packages')
import pcbnew
T = sys.argv[1]
b = pcbnew.LoadBoard(T + '_f3.kicad_pcb')
print('DSN export', pcbnew.ExportSpecctraDSN(b, T + '.dsn'))
s = open(T + '.dsn').read()
m = re.search(r'\(boundary\s*\(path pcb 0\s+([^)]*)\)', s)
nums = [int(v) for v in m.group(1).split()]
xs, ys = nums[0::2], nums[1::2]
poly = ' '.join('%d %d' % (x, y) for x, y in ((min(xs), min(ys)), (max(xs), min(ys)), (max(xs), max(ys)), (min(xs), max(ys)), (min(xs), min(ys))))
ko = '    (keepout "" (polygon B.Cu 0  %s))\n' % poly
i = s.index('    (via "Via')
s = s[:i] + ko + s[i:]
open(T + '.dsn', 'w').write(s)
print('B.Cu keep-out added over the board')
PY
timeout 1500 bash /work/docker/pcb/freeroute.sh ${T}.dsn ${T}.ses --passes ${PASSES:-20} --timeout 1200 > ${T}_fr.log 2>&1; echo "freerouting exit $?"; tail -3 ${T}_fr.log
python3 - ${T} <<'PY'
import sys
sys.path.append('/usr/lib/python3/dist-packages')
import pcbnew
T = sys.argv[1]
b = pcbnew.LoadBoard(T + '_f3.kicad_pcb')
print('SES import', pcbnew.ImportSpecctraSES(b, T + '.ses'))
pcbnew.SaveBoard(T + '_fr.kicad_pcb', b)
PY
cp ${T}_f3.kicad_pro ${T}_fr.kicad_pro
python3 - ${T} <<'PY'
import sys
sys.path.insert(0, '/work/hardware/afe-proto')
from pcbtools.editor import edit
with edit(sys.argv[1] + '_fr.kicad_pcb') as e:
    e.fill_zones()
PY
kicad-cli pcb drc --severity-all --format json -o ${T}_fr_drc.json ${T}_fr.kicad_pcb > /dev/null 2>&1
python3 - ${T} <<'PY'
import json, sys, re, collections
T = sys.argv[1]
d = json.load(open(T + '_fr_drc.json'))
print('DRC by type', dict(collections.Counter(v['type'] for v in d['violations'])), 'unconnected', len(d.get('unconnected_items', [])))
nets = collections.Counter(); where = collections.defaultdict(list)
for u in d.get('unconnected_items', []):
    its = u['items']; n = re.search(r'\[(/[^\]]+)\]', its[0]['description']); n = n.group(1) if n else '?'
    nets[n] += 1; where[n].append((round(its[0]['pos']['x'] - 50, 1), round(150 - its[0]['pos']['y'], 1)))
print('UNROUTED by net', dict(nets))
for n in nets: print('  ', n, where[n][:4])
PY
