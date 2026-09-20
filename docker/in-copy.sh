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
exec "$@"
