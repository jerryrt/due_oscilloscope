#!/bin/bash
# Run the pcbnew-marked tests (and the guard) in the project environment.
#   PCB_PYTHON=<python with pcbnew, numpy, scipy, pytest> [CAPPED=<capped.sh>] tests/run_pcbnew_tests.sh [pytest args]
# PCB_PYTHON defaults to python3. CAPPED, when set, is a memory-cap wrapper taking "-m MEM -t SECONDS command".
# The pure-numpy group is:  $PCB_PYTHON -m pytest -c tests/pytest.ini -m "not pcbnew and not ngspice" tests
# No retry: a crash (signal death, rc >= 128) fails the run like any other failure. The start-up segfault that this
# wrapper once retried came from a mismatched interpreter and does not occur in the pinned image (0 of 50 loads, 0 of 32
# test-group runs). PCBTOOLS_EXPECT_PCBNEW=1 makes a missing pcbnew a failure and arms the guard test.
HERE=$(cd "$(dirname "$0")/.." && pwd)
PY=${PCB_PYTHON:-python3}
cd "$HERE" || exit 2
if [ -n "$CAPPED" ]; then
  PCBTOOLS_EXPECT_PCBNEW=1 $CAPPED -m 3G -t 300 $PY -m pytest -c tests/pytest.ini -m pcbnew --require-tool=pcbnew tests "$@"
else
  PCBTOOLS_EXPECT_PCBNEW=1 $PY -m pytest -c tests/pytest.ini -m pcbnew --require-tool=pcbnew tests "$@"
fi
exit $?
