#!/bin/bash
# THE GATE OF RECORD for the AFE PCB and simulation tools. Runs inside the
# image, from the repository root:
#
#     docker/pcb/run.sh -m 3G -t 900 docker/pcb/run-gate.sh
#
# All three tiers - numpy, ngspice, pcbnew - in one pytest run with
# --require-tool=pcbnew,ngspice, so a missing tool is a failure and nothing
# can skip into a pass. The only skips left are the `jobcap` tests, whose
# per-job cap does not exist in the container (docker's cap is the whole
# container's) and which test_image_gate.py checks from the host instead;
# they are counted and named, never hidden.
#
# An exit code of 0 with no tests collected is NOT a pass: pytest exits 5
# for that and so does this script.
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 2
python3 -m pytest -p no:cacheprovider -c hardware/afe-proto/tests/pytest.ini hardware/afe-proto/tests \
    --require-tool=pcbnew,ngspice -q "$@"
