#!/usr/bin/env bash
#
# Run a command against a container-local copy of the working tree.
#
#     docker/in-copy.sh python3 -m pytest ...
#
# The populate is here rather than in docker/run.sh deliberately. run.sh
# is also how short commands run - `docker/run.sh bash`, a one-off find,
# a toolchain query - and mac-bench measures the populate at 12.5-13.5 s
# on its filesystem. Taxing every invocation to serve the few that read
# the tree thousands of times would be paid most often by the commands
# that gain nothing. docker/populate.sh says why the copy is wanted.
set -euo pipefail

repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
target=${DUE_COPY_DIR:-/tmp/due-work}

"$repo/docker/populate.sh" "$repo" "$target"
cd -- "$target"

# AND THE COPY IS WATCHED THE WAY THE TREE IS.
#
# run-ci.sh's `working tree` step watches /work between steps, and a
# step that runs in here can no longer reach it - so for that step the
# check passes by construction, which is a guard that has stopped
# guarding rather than a property that has been proved. The same
# question is asked of the copy instead: a run may leave ignored output
# behind, and it may not modify tracked source.
#
# Measured before it was added, so it is not a speculative guard: the
# board-free tier leaves __pycache__ and nothing else, and the tracked
# state is identical before and after. A difference here is a test
# writing into the tree it is testing.
before=$(git --no-optional-locks status --porcelain | LC_ALL=C sort)

set +e
"$@"
rc=$?
set -e

after=$(git --no-optional-locks status --porcelain | LC_ALL=C sort)
if [ "$before" != "$after" ]; then
    echo "---- THE COPY'S TRACKED STATE CHANGED during the run" >&2
    diff <(printf '%s\n' "$before") <(printf '%s\n' "$after") >&2 || true
    [ "$rc" -eq 0 ] && rc=1
fi
exit "$rc"
