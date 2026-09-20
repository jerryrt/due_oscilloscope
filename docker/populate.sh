#!/usr/bin/env bash
#
# Copy the working tree into a container-local directory and run there.
#
# WHY THIS EXISTS. `docker/run.sh` bind-mounts the checkout at /work, and
# on a bench whose checkout lives outside the container's VM that mount
# is a network filesystem. Reading it is latency-bound per operation, and
# Python's import machinery performs several stat calls per file: mac-bench
# measures ~0.9 ms an operation against ~1.4 us on a native daemon, and its
# host tier runs 315-399 s mounted against 214-219 s from a copy. The same
# measurement showed the MOUNT is also that bench's run-to-run variance -
# 26% mounted, 2% copied, interleaved in one session.
#
# So the tree is read once, sequentially, and every subsequent read is
# local. The copy is disposable and is rebuilt on every call: reusing one
# would mean a run could silently test stale source, which is a worse
# failure than the seconds it saves.
#
# WHAT IS COPIED IS GIT'S OWN VIEW OF THE TREE - tracked files plus
# untracked ones git would not ignore. That self-maintains where an
# exclude list drifts, and it keeps `git status` inside the copy identical
# to the host's, which tools/container_report.py depends on.
#
# AND WHAT GIT IGNORES IS EXACTLY WHAT THE BUILD PRODUCES, which is the
# trap here. `tests/test_no_heap.py` reads docker/out/build/*.elf to prove
# the firmware links no heap; that path is ignored, so a copy without it
# made the guard SKIP - silently, because a skip is not a failure. The
# tier went from 810 passed/5 skipped to 809/6 and nothing was red. So
# state the tier reads but does not track is bridged by symlink rather
# than left out. Add to BRIDGES rather than copying: these are read
# rarely and some are large.
#
# .git IS COPIED, ON EVERY BENCH, AND IT USED TO BE A KNOB. A bridge
# pays the mount on every git operation and a copy pays it once, and
# which is cheaper was measured to invert with the filesystem - so
# DUE_COPY_GIT let each bench pick. Then the whole gate moved into the
# copy and the git operations multiplied across eight steps, and all
# three benches landed on the same side: sshfs 5.2 s once against ~420 ms
# an operation, drvfs 30-52 s once against +42 s per host tier and +18 s
# per firmware build through the bridge, and native ext4 0.30 s for
# 5,366 files, 0.13% of a gate. A knob whose right value is a property of
# the host is a seam leak; one that every host sets the same way is a
# default in disguise. Uniform copy is the Feeder.WRITE_SIZE pattern -
# a policy one platform needs, kept everywhere because it is measured
# free where it is not needed - and it is also the stronger isolation:
# nothing a step does in the copy can reach the source's index.
#
# NO BIND MOUNT MAY LAND INSIDE THE TARGET. The daemon creates a mount
# point that does not exist, as root, before --user takes effect - so a
# bind anywhere under the target makes the target itself root-owned and
# unwritable. That is why /work cannot be the target (it is a mount
# point) and why .git is bridged from outside rather than mounted in.
set -euo pipefail

src=${1:?usage: populate.sh <source> <target>}
dst=${2:?usage: populate.sh <source> <target>}

#: Ignored state the tier reads. git's selector excludes all of it by
#: construction, so each is bridged rather than copied.
#:
#: THREE FILES, NOT ONE. docker/out was found by a guard that went
#: silently from passed to SKIPPED. The other two were found by reading
#: the selector rather than by a failure, and they are the more dangerous
#: shape: tests/test_held_link_guard.py and tests/test_container_report.py
#: branch on bench.json BY NAME, so a bench whose copy lacks it takes a
#: different path and still passes. An outcome comparison cannot see that.
#: Absent from a bench that has never declared its cabling or flashed a
#: board, which is why each is skipped when it does not exist.
BRIDGES=(.git docker/out bench.json records/flash-log.jsonl)

rm -rf -- "$dst"
mkdir -p -- "$dst"

( cd -- "$src" && git ls-files -z
  cd -- "$src" && git ls-files -z --others --exclude-standard ) \
    | tar -C "$src" --null --files-from - -cf - \
    | tar -C "$dst" -xf -

for b in "${BRIDGES[@]}"; do
    [ -e "$src/$b" ] || continue
    mkdir -p -- "$dst/$(dirname -- "$b")"
    if [ "$b" = ".git" ]; then
        # Copied, never bridged: the header says why, and the numbers.
        cp -a -- "$src/$b" "$dst/$b"
    elif [ "$b" != ".git" ] && [ -d "$src/$b" ]; then
        # A DIRECTORY BRIDGE STAYS A DIRECTORY, and its entries are
        # linked instead. A gitignore rule written with a trailing slash
        # matches directories only, so a symlink standing in for the
        # directory is not matched: docker/.gitignore says `out/`, and
        # bridging docker/out as a symlink made the copy report
        # `?? docker/out` where the source reports nothing. The fidelity
        # check below caught that, which is the whole reason it exists.
        mkdir -p -- "$dst/$b"
        for e in "$src/$b"/* "$src/$b"/.[!.]*; do
            [ -e "$e" ] || continue
            ln -sfn -- "$e" "$dst/$b/$(basename -- "$e")"
        done
    else
        ln -sfn -- "$src/$b" "$dst/$b"
    fi
done

# THE COPY MUST BE CONTENT-FAITHFUL, and git already knows how to say so.
# `git status` in the copy reads the source's index through the bridged
# .git, so it reports exactly what a copy missing a file, truncating one,
# or picking up a stray would report - and nothing for the ignored files
# the copy deliberately lacks. A silently short tar is the failure this
# catches, and it would otherwise show up as a test that skips.
#
# --no-optional-locks so reading the state cannot write the source's index.
want=$(cd -- "$src" && git --no-optional-locks status --porcelain | LC_ALL=C sort)
got=$(cd -- "$dst" && git --no-optional-locks status --porcelain | LC_ALL=C sort)
if [ "$want" != "$got" ]; then
    echo "populate: the copy does not match the source" >&2
    diff <(printf '%s\n' "$want") <(printf '%s\n' "$got") >&2 || true
    exit 1
fi
