#!/bin/bash
# Regenerate the gate-3 package (GATE3.md and data/*) from the integrated board and the repo. Idempotent; one command:
#
#     docker/pcb/run.sh -m 3G -t 900 -c 2 bash hardware/afe-proto/v2/layout/gate3/build_gate3.sh
#
# Runs in the pinned PCB image (pcbnew and kicad-cli are there); reads the board, writes only under this folder. The generator is the
# board-agnostic pcbtools.gate3 (see hardware/afe-proto/pcbtools/gate3/README.md), driven by the v2 layout config and the v2 table;
# this script only names them and the output folder. GATE3_STAMP, if set, replaces the generated-at time.
set -euo pipefail
here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
afe=$(cd -- "$here/../../.." && pwd)
export PYTHONPATH="$afe${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONDONTWRITEBYTECODE=1
cd "$afe/../.."
python3 -B -m pcbtools.gate3 --config v2_layout --table gate3_v2 --out "$here"
