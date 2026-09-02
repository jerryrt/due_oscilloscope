#!/bin/bash
# Run a command inside the pinned build image against this working tree.
#
#     docker/run.sh                            # an interactive shell
#     docker/run.sh docker/build-firmware.sh   # both tracks, clean
#     docker/run.sh python3 tools/toolchain.py
#
# The flags below are the whole reason this script exists; none of them
# is optional and none is worth remembering by hand.
#
# --user. A container that writes as root leaves root-owned objects in
# the host tree, and the bench cannot then rebuild or delete them
# without sudo. The container runs as the invoking uid:gid, so
# everything it writes is already the user's. The image sets HOME to a
# container path, so a uid with no passwd entry still has one.
#
# THE BUILD DIRECTORIES ARE NOT THE BENCH'S. `build/` and `build-a/`
# inside the container are bind mounts onto docker/out/, so a container
# build cannot overwrite the images a bench has on its board - the
# container's compiler is xPack and the bench's may be anything, and two
# different images under one path is the mixed-revision hazard again.
# They are ordinary host directories, so the artifacts stay readable
# afterwards.
#
# --network none. Nothing in a firmware build reaches the network, and
# the pinning is worth nothing if a build step can fetch something the
# Dockerfile did not name. Failing loudly is the point.
#
# THE GIT DIRECTORY MAY LIE OUTSIDE THE TREE. In a worktree, `.git` is a
# file pointing at the main repository's git directory by absolute path.
# Mounting only the worktree gives a container where git answers
# nothing, and `cmake/fw_git_rev.cmake` then stamps `unknown` - a build
# that cannot name its commit, which is what phase 1 exists to fix. The
# common directory is mounted at the identical path so the pointer
# resolves.
set -euo pipefail

here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo=$(dirname -- "$here")
image=${DUE_BUILD_IMAGE:-due-build:15.2.1-1.1}

if ! docker image inspect "$image" >/dev/null 2>&1; then
    echo "no such image: $image" >&2
    echo "build it:  docker/build-image.sh" >&2
    exit 2
fi

# Both ends of every bind mount, created as this user before docker sees
# them. A mount point the daemon has to create is created by the daemon,
# which is root, and `--user` does not reach it: the first run without
# these left root-owned `build/` and `build-a/` in the host tree and
# cmake then refused to configure there. Measured, not anticipated.
mkdir -p "$here/out/build" "$here/out/build-a" "$repo/build" "$repo/build-a"

flags=(
    --rm
    --user "$(id -u):$(id -g)"
    --network none
    --volume "$repo:/work"
    --volume "$here/out/build:/work/build"
    --volume "$here/out/build-a:/work/build-a"
    --workdir /work
)

common=$(git -C "$repo" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)
case "$common" in
    "" | "$repo"/*) ;;
    *) flags+=(--volume "$common:$common") ;;
esac

if [ -t 0 ] && [ -t 1 ]; then
    flags+=(--interactive --tty)
fi

exec docker run "${flags[@]}" "$image" "$@"
