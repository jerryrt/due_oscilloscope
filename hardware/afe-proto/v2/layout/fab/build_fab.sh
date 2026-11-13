#!/bin/bash
# The JLC fabrication set from the final v2 board (Gerbers, drills, BOM, CPL), one deterministic zip, verified, plus the manifest.
#     docker/pcb/run.sh -m 2G -t 300 bash hardware/afe-proto/v2/layout/fab/build_fab.sh
# Writes out/$(python3 -B -c "from pcbtools import fab; print(fab.ZIP_NAME)") (ignored by git) and manifest.json (committed; tests/pcbtools/test_fab.py compares a fresh build with it).
set -euo pipefail
here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
afe=$(cd -- "$here/../../.." && pwd)
export PYTHONPATH="$afe" PYTHONDONTWRITEBYTECODE=1
cd "$afe"
python3 -B -m pcbtools.fab build v2/layout/integrated/afe-v2-integrated.kicad_pcb "$here/out"
python3 -B -m pcbtools.fab manifest "$here/out/$(python3 -B -c "from pcbtools import fab; print(fab.ZIP_NAME)")" > "$here/manifest.json"
python3 -B - <<'PY'
from pcbtools import fab
from pcbtools.boards import v2_layout as L
x0, y0, x1, y1 = L.BOARD_RECT
p = fab.verify('v2/layout/fab/out/' + fab.ZIP_NAME, 'v2/layout/integrated/afe-v2-integrated.kicad_pcb', round(x1 - x0, 4), round(y1 - y0, 4))
print('verify:', p or 'ok'); raise SystemExit(1 if p else 0)
PY
