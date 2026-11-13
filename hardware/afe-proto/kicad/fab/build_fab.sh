#!/bin/bash
# The JLC fabrication set from the final v1 board (Gerbers, drills, BOM, CPL), one deterministic zip, verified, plus the manifest. The same engine as version 2's
# (pcbtools/fab.py, --design v1); the names come from the configuration (pcbtools/boards/v1.py: COPPIA-AFE-1-REVA).
#     docker/pcb/run.sh -m 2G -t 300 bash hardware/afe-proto/kicad/fab/build_fab.sh
# Writes out/COPPIA-AFE-1-REVA-fab.zip (ignored by git) and manifest.json (committed; tests/pcbtools/test_fab_v1.py compares a fresh build with it).
set -euo pipefail
here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
afe=$(cd -- "$here/../.." && pwd)
export PYTHONPATH="$afe" PYTHONDONTWRITEBYTECODE=1
cd "$afe"
python3 -B -m pcbtools.fab build kicad/afe-proto.kicad_pcb "$here/out" --design v1
zip="$here/out/$(python3 -B -c "from pcbtools import fab; print(fab.design_ident('v1')[0])")-fab.zip"
python3 -B -m pcbtools.fab manifest "$zip" > "$here/manifest.json"
python3 -B - "$zip" <<'PY'
import sys
from pcbtools import fab
from pcbtools.boards import v1 as L
x0, y0, x1, y1 = L.BOARD_RECT
p = fab.verify(sys.argv[1], 'kicad/afe-proto.kicad_pcb', round(x1 - x0, 4), round(y1 - y0, 4), fab.design_ident('v1')[0])
print('verify:', p or 'ok'); raise SystemExit(1 if p else 0)
PY
