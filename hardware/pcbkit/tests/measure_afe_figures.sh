#!/bin/bash
# measure_afe_figures.sh OUTDIR  (inside the image, from a repository root): the AFE's figure sets written as files, so two
# trees can be compared by sha256: the gate-3 package (stamp fixed), the fabrication zip and its manifest, and the silkread findings
# of the integrated board and every v2 fixture board.
set -e
O=$1; rm -rf $O; mkdir -p $O
export PYTHONPATH=hardware/afe-proto
python3 -B -m pcbtools.gate3 --config v2_layout --table gate3_v2 --out $O/gate3 --stamp FIXED > $O/gate3.log 2>&1
B=hardware/afe-proto/v2/layout/integrated/afe-v2-integrated.kicad_pcb
python3 -B - > $O/fab.txt 2>&1 <<PY
import json, os, sys
from pcbtools import fab
A = 'hardware/afe-proto'
zp = fab.build('$B', '$O/fab', f'{A}/v2/bom/{fab.IDENT}-bom.csv', f'{A}/v2/bom/{fab.IDENT}-cpl.csv')
print(os.path.basename(zp)); print(json.dumps(fab.manifest(zp), indent=1))
PY
python3 -B -m pcbtools.check $B --config v2_layout --no-drc > $O/rules.txt 2>&1 || true
python3 -B - > $O/silkread.txt <<'PY'
import glob, os, sys
sys.path.append('/usr/lib/python3/dist-packages')
from pcbtools import boardio, silkread
LABELS = {'J101': 'CH1 IN', 'J201': 'CH2 IN', 'J301': 'AWG OUT'}
paths = ['hardware/afe-proto/v2/layout/integrated/afe-v2-integrated.kicad_pcb'] + sorted(glob.glob('hardware/afe-proto/tests/fixtures/v2-8a1f7ac/*.kicad_pcb'))
for p in paths:
    b = boardio.read_board(p)
    keys = silkread.read_keys(open(p).read())
    f = silkread.findings(b, keys, LABELS)
    print(os.path.basename(p), len(keys), len(f))
    for s in f: print('  ' + s)
PY
(cd $O && find . -type f ! -name '*.log' | sort | xargs sha256sum > SHA256SUMS.txt)
wc -l $O/SHA256SUMS.txt
