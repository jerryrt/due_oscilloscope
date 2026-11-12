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
# Every run prints "attempt N of M" (also attempt 1 of 1 on first-try success) and exits with the final status; a retry is a
# finding to report (the wrapper below prints a RETRY line), never a silent cost.
for try in 1 2 3; do
  echo "run_pcbnew_tests: attempt $try of 3" >&2
  if [ -n "$CAPPED" ]; then
    PCBTOOLS_EXPECT_PCBNEW=1 $CAPPED -m 3G -t 300 $PY -m pytest -c tests/pytest.ini -m pcbnew --require-tool=pcbnew tests "$@"
  else
    PCBTOOLS_EXPECT_PCBNEW=1 $PY -m pytest -c tests/pytest.ini -m pcbnew --require-tool=pcbnew tests "$@"
  fi
  rc=$?
  if [ $rc -lt 128 ]; then
    echo "run_pcbnew_tests: finished at attempt $try of 3 with status $rc" >&2
    [ $try -gt 1 ] && echo "run_pcbnew_tests: RETRY FINDING: $((try - 1)) earlier attempt(s) died with a signal (pcbnew start-up segfault)" >&2
    exit $rc
  fi
  echo "run_pcbnew_tests: attempt $try of 3 died with signal status $rc (pcbnew start-up segfault?)" >&2
done
exit $rc
