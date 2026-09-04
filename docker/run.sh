#!/bin/bash
# Run a command inside the pinned build image against this working tree.
#
#     docker/run.sh                            # an interactive shell
#     docker/run.sh docker/build-firmware.sh   # both tracks, clean
#     docker/run.sh docker/run-tests.sh        # the board-free tier
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
#
# WHICH IMAGE RAN CROSSES THE BOUNDARY HERE, and only here: a process
# inside a container cannot ask docker what it is running in, and this
# is the one file that sees both sides. The two values below go in as
# environment; docker/build-firmware.sh writes them beside the artifacts
# and tools/flash.py copies them into the flash log.
set -euo pipefail

here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo=$(dirname -- "$here")
image=${DUE_BUILD_IMAGE:-due-build:15.2.1-1.1}

if ! docker image inspect "$image" >/dev/null 2>&1; then
    echo "no such image: $image" >&2
    echo "build it:  docker/build-image.sh" >&2
    exit 2
fi

# TWO IDENTITIES, BECAUSE NEITHER ANSWERS THE OTHER'S QUESTION.
#
# `.Id` names the object that is about to run, and it is a BUILD EVENT
# rather than an environment. Measured on linux-x1: four builds of this
# Dockerfile - the tagged one, one with no --build-arg, one with the
# same --build-arg build-image.sh passes, and a repeat of the first -
# produced four different `.Id` values from a fully cached build, and
# one layer chain. Recorded rows keyed on it would read as four
# environments where there is one.
#
# The content hash is the environment. It covers the layer chain and the
# image config, which is what a build can actually see: layers alone
# miss an `ENV` change, because ENV adds no layer and HOME is what
# points the Track A build at the SAM core. Equal across all four builds
# above, and it moves when the recipe's content does.
#
# D5 takes no registry, so neither value is a registry digest and this
# one is not called one. It is a hash over what `docker image inspect`
# chose to print, so it inherits docker's choices - the same caveat that
# `layout` carries about `nm` - and it compares within a bench with
# certainty and across benches only as far as their docker agrees.
image_id=$(docker image inspect "$image" --format '{{.Id}}')
image_content=$(docker image inspect "$image" \
    --format '{{range .RootFS.Layers}}{{println .}}{{end}}{{json .Config}}' |
    python3 -c 'import hashlib,sys
print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest())')

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
    --env "DUE_BUILD_IMAGE=$image"
    --env "DUE_BUILD_IMAGE_ID=$image_id"
    --env "DUE_BUILD_IMAGE_CONTENT=$image_content"
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
