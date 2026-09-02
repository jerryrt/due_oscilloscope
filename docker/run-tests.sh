#!/bin/bash
# Run the board-free test tier inside the pinned image.
#
#     docker/run.sh docker/run-tests.sh                     # the tier
#     docker/run.sh docker/run-tests.sh --track=b -q        # whole suite
#     docker/run.sh docker/run-tests.sh --track=b -m "not board" \
#                                       --require-board -q  # the control
#
# WHY THE TIER IS WORTH RUNNING HERE AND NOWHERE ELSE. docs/testing.md
# says the `board` marker is verified two ways and both are static: the
# marker is derived from fixturenames, and a grep finds no Board(),
# find_* or open_raw() in a board-free file. A container with no device
# passed through is the dynamic check - the machine with no Due on it
# that no bench has ever been. A board-free test that wants hardware
# here is a bug in the marker, not a bug in the container.
#
# AND THE TIER CANNOT CERTIFY ITSELF. A board test that skips scores as
# a pass in any harness that greps for failures, so the whole-suite run
# is only worth what its positive control is worth: --require-board
# turns those skips into errors, and it must FAIL in here. A clean
# whole-suite run with no --require-board beside it proves nothing.
#
# THE TIER IS NOT RELIABLY GREEN IN HERE YET, AND THE CAUSE IS THE
# INTERPRETER, NOT THE CONTAINER. Three of seven tier runs on linux-x1
# lost one or two tests, always in tests/test_daemon_api.py, always a
# five-second client timeout. The image's python3 is Ubuntu noble's
# 3.12.3 and the bench's venv is 3.14.4, and 3.12 starves a lock
# waiter where 3.14 hands the lock over: one thread doing
# `while True: with lk: sleep(0.01)` makes a second thread's bare
# acquire wait 1.6-5.7 ms on 3.14 and 38 ms to 4.3 s on 3.12. That is
# the shape FakeDevice.read() has - it sleeps holding the device lock -
# so a `start` call loses the race for longer than the client waits.
# Ruled out by measurement: seccomp, the network namespace, /tmp on
# overlayfs, sleep granularity, and raw CPU, which is 1.2x.
#
# Written to run inside the image, from the repository root, and it
# carries no container knowledge - a bench can run it against its own
# venv to get the row to compare against.
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

echo "== the interpreter and what is pinned into it =="
python3 -c 'import sys; print(sys.executable); print(sys.version)'
python3 -m pip freeze
echo

# tests/test_no_heap.py reads the linked ELF rather than grepping the
# sources, so with no build it skips - and a tier scored on its failures
# reads one pass short as a clean run. Say so rather than let the count
# drift silently; docker/build-firmware.sh is what fills it in.
if [ ! -f build/baremetal_bringup.elf ]; then
    echo "NOTE: build/baremetal_bringup.elf is absent, so test_no_heap will"
    echo "      SKIP and the tier will be one pass short. Run"
    echo "      docker/build-firmware.sh first for a comparable count."
    echo
fi

echo "== where the tools resolved =="
python3 tools/toolchain.py || true
echo

if [ "$#" -eq 0 ]; then
    set -- --track=b -m "not board" -q
fi

echo "== pytest $* =="
exec python3 -m pytest "$@"
