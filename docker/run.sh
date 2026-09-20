#!/bin/bash
# Run a command inside the pinned build image against this working tree.
#
#     docker/run.sh                            # an interactive shell
#     docker/run.sh docker/build-firmware.sh   # all three tracks, clean
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
# THE BUILD DIRECTORIES ARE NOT THE BENCH'S. `build/`, `build-a/` and
# `build-c/` inside the container are bind mounts onto docker/out/, so a container
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
#
# What the container is for, what it will not do, and what a bench
# gives up without it: docs/build-container.md
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
mkdir -p "$here/out/build" "$here/out/build-a" "$here/out/build-c"

flags=(
    --rm
    --init
    --user "$(id -u):$(id -g)"
    --network none
    --volume "$repo:/work"
    --workdir /work
    --env "DUE_BUILD_IMAGE=$image"
    --env "DUE_BUILD_IMAGE_ID=$image_id"
    --env "DUE_BUILD_IMAGE_CONTENT=$image_content"
    # A container inherits nothing from this shell, so a knob the bench
    # sets has to be named here or it is not a knob at all. `.git` costs
    # 28 ms an operation copied against 420 ms bridged on sshfs, and the
    # opposite on drvfs, so that one is per-bench by measurement.
    #
    # PASSED EMPTY WHEN UNSET, so the default lives in the script that
    # reads it and not in two places. `--env X=` leaves `${X:-default}`
    # downstream to supply it; naming the default here as well gives it
    # a second home, which is the shape that let FW_VERSION_STR and
    # FW_VERSION_MAJOR disagree.
    --env "DUE_COPY_GIT=${DUE_COPY_GIT:-}"
    --env "DUE_COPY_DIR=${DUE_COPY_DIR:-}"
    --env "DUE_CI_LOGS=${DUE_CI_LOGS:-}"
    --env "DUE_FUZZ_CORPUS=${DUE_FUZZ_CORPUS:-}"
)

# THE ONE HOME FOR THE OBJECT DIRECTORY'S DEFAULT. Its consumers -
# docker/build-firmware.sh and tools/reproducible.py - read the variable
# and supply no default of their own, so they cannot disagree about
# where a build went. An empty value builds in place, which is also what
# a consumer gets if it is ever run without this launcher: the old
# behaviour, and the safe one.
#
# This is the opposite of the rule for the knobs above, and deliberately
# so. Those name their default at the reader because forwarding `X=`
# empty would be indistinguishable from the bench asking for empty; here
# empty is a real request, so the default has to be resolved before it
# crosses.
flags+=(--env "DUE_BUILD_LOCAL=${DUE_BUILD_LOCAL-/tmp/due-build}")

common=$(git -C "$repo" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)
case "$common" in
    "" | "$repo"/*) ;;
    *) flags+=(--volume "$common:$common") ;;
esac

# An interactive shell keeps the terminal and returns here unchanged:
# the container ends when the user leaves it, and backgrounding the
# client to wait on it would take the tty away from the shell being run.
if [ -t 0 ] && [ -t 1 ]; then
    flags+=(--interactive --tty)
    exec docker run "${flags[@]}" "$image" "$@"
fi

# THE CONTAINER OUTLIVES A KILLED CLIENT, AND NOTHING HERE NOTICED.
#
# `docker run` is a client: the daemon owns the container, so killing
# the client leaves the work running with nothing attached to its
# output. On mac-bench three runs were killed by the host for low memory
# and all three left a container running; a fourth, a 32-bit ASan
# reproducer from an earlier session, ran under `qemu-i386` for SEVEN
# DAYS and had burned 7h02 of CPU inside a 4-vCPU VM before anyone
# looked. Every timing taken on that bench in between was taken against
# it.
#
# So the container is named and stopped on the way out, whatever the way
# out is: a normal return, a failure under `set -e`, or a signal. The
# cidfile is docker's own record of what started, which avoids guessing
# from `docker ps`.
#
# WHAT THIS DOES NOT COVER, said plainly: SIGKILL. A killed shell runs
# no trap, and the container then survives exactly as before. The fix
# for that one is to notice - `docker ps` after an interrupted run -
# because nothing a client can do protects against its own SIGKILL.
#
# `--init` is separate and smaller: PID 1 in the container is then tini
# rather than the command, so a `docker stop` reaches the process tree
# and a child that outlives its parent is reaped rather than left.
# Not mktemp: docker refuses a cidfile that already exists, so the name
# has to be one that does not, and BSD mktemp will not take a template
# with anything after the Xs - it fails, and under `set -e` the script
# then exits before it has run anything at all.
cidfile="${TMPDIR:-/tmp}/due-run-$$-${RANDOM}.cid"
flags+=(--cidfile "$cidfile")

cleanup() {
    if [ -f "$cidfile" ]; then
        cid=$(cat "$cidfile" 2>/dev/null || true)
        [ -n "$cid" ] && docker stop --timeout 5 "$cid" >/dev/null 2>&1 || true
        rm -f "$cidfile"
    fi
}
trap cleanup EXIT INT TERM HUP

# WAITED ON, NOT RUN IN THE FOREGROUND, and that is the whole mechanism.
# bash runs a trap between commands: with `docker run` in the foreground
# a TERM arriving mid-run is held until it returns, which is precisely
# the case this exists for and left the container running anyway when it
# was written that way. `wait` is interruptible, so the trap fires while
# the container is still up. Measured: a TERM mid-run leaves a container
# 2 of 2 under the old script and 0 of 2 under this one. SIGINT was
# never the failing case - the client proxies that to the container.
docker run "${flags[@]}" "$image" "$@" &
client=$!
status=0
wait "$client" || status=$?
exit "$status"
