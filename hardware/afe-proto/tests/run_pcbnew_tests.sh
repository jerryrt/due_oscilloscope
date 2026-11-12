#!/bin/bash
# Run the pcbnew-marked tests (and the guard) in the project environment, retried on a start-up segfault.
#   PCB_PYTHON=<python with pcbnew, numpy, scipy, pytest> [CAPPED=<capped.sh>] tests/run_pcbnew_tests.sh [pytest args]
# PCB_PYTHON defaults to python3. CAPPED, when set, is a memory-cap wrapper taking "-m MEM -t SECONDS command".
# The pure-numpy group is:  $PCB_PYTHON -m pytest -c tests/pytest.ini -m "not pcbnew and not ngspice" tests
# pcbnew segfaults intermittently while starting: a signal death (rc >= 128) is retried up to 3 times; a test failure
# (rc 1) is final. PCBTOOLS_EXPECT_PCBNEW=1 makes a missing pcbnew a failure and arms the guard test.
HERE=$(cd "$(dirname "$0")/.." && pwd)
PY=${PCB_PYTHON:-python3}
cd "$HERE" || exit 2
for try in 1 2 3; do
  if [ -n "$CAPPED" ]; then
    PCBTOOLS_EXPECT_PCBNEW=1 $CAPPED -m 3G -t 300 $PY -m pytest -c tests/pytest.ini -m pcbnew --require-tool=pcbnew tests "$@"
  else
    PCBTOOLS_EXPECT_PCBNEW=1 $PY -m pytest -c tests/pytest.ini -m pcbnew --require-tool=pcbnew tests "$@"
  fi
  rc=$?
  if [ $rc -lt 128 ]; then exit $rc; fi
  echo "run_pcbnew_tests: died with signal status $rc (pcbnew start-up segfault?); attempt $try of 3" >&2
done
exit $rc
