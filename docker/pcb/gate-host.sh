#!/bin/bash
# THE GATE OF RECORD, from the host:
#
#     docker/pcb/gate-host.sh [pytest args]
#
# Two steps, in this order, because the container runs --network none and cannot fetch what the gate requires:
#   1. fetch the vendor SPICE models on the HOST into the untracked hardware/afe-proto/models directory, by
#      tools/fetch_models.py, every file verified against its manifest sha256 (the libraries and archives only: the
#      datasheet PDFs are not simulation inputs). The container sees the directory through the repository mount.
#   2. run docker/pcb/run-gate.sh in the pinned image, which requires pcbnew, ngspice, freerouting, networkx and
#      the vendor models, so a missing one is a failure and never a skip.
# A fetch that fails stops here, loudly: a gate run without its models would fail on them anyway.
set -euo pipefail

here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo=$(cd -- "$here/../.." && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

python3 - "$repo/hardware/afe-proto/models/manifest.json" "$tmp/sim-models.json" <<'PY'
import json, sys
m = json.load(open(sys.argv[1]))
keep = [f for f in m["files"] if not f["path"].lower().endswith((".pdf", ".html"))]
if not keep:
    sys.exit("gate-host: the manifest has no model entries")
json.dump({"comment": m.get("comment", ""), "files": keep}, open(sys.argv[2], "w"))
print(f"gate-host: fetching {len(keep)} model files (of {len(m['files'])} in the manifest; datasheets skipped)", file=sys.stderr)
PY
python3 -I "$repo/hardware/afe-proto/tools/fetch_models.py" --manifest "$tmp/sim-models.json"

exec "$here/run.sh" -m 3G -t 3000 docker/pcb/run-gate.sh "$@"
