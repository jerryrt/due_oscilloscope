#!/bin/bash
# Configure and build all three firmware tracks, then say what built them.
#
#     docker/run.sh docker/build-firmware.sh
#
# Written to run inside the image, from the repository root, and only
# there: firmware is built in the container and nowhere else, and
# CMakeLists.txt refuses a configure that docker/run.sh did not launch.
# The commands are CLAUDE.md's, verbatim. What it writes lands in
# docker/out/, where tools/flash.py and the board suite read it.
#
# The configure step is idempotent and the build step is not incremental:
# `firmware` and `firmware_track_a` are clean-build wrappers, and this
# script must not become the reason that stops being true.
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

# WHICH ENVIRONMENT RAN THE COMPILER, recorded beside the artifacts.
#
# The board states its commit and tools/flash.py reads the compiler and
# the layout off the ELF; none of those says what the compiler was
# running inside. This script is the only thing that is inside it, so
# this is where the answer is written down, and tools/flash.py reads the
# file back into the flash log.
#
# THE RECORD IS BOUND TO THE BYTES IT DESCRIBES. Every artifact in the
# directory is hashed into it, and flash.py refuses a record whose hash
# does not match the binary it is flashing. A build directory outlives
# the build that filled it, so a file that merely sat in the right place
# would report the environment of the PREVIOUS build - a stale value,
# which is worse than an absent one, because a null is questioned and a
# field that is there is trusted.
#
# DUE_BUILD_IMAGE_ID is set by docker/run.sh and by nothing else, so a
# build with no container around it states `host` rather than leaving
# the question open. It is written per track, immediately after that
# track builds, so a bench that cannot build the other one still records
# the one it did.
# WHERE THE OBJECTS ARE WRITTEN, AND WHY IT IS NOT THE OUTPUT DIRECTORY.
#
# `build/`, `build-a/` and `build-c/` are bind mounts onto docker/out/,
# so on a bench whose checkout is outside the container's VM every object
# file is written across a network filesystem. Measured on mac-bench,
# interleaved AB with the first cycle dropped: 65.5 and 59.1 s writing
# into the mount against 34.1 and 34.2 s written locally and copied out -
# disjoint, and the local arm reproduces to 0.1% where the mounted one
# spans 59-81 s. The copy-out costs 213 ms for nine files there, 2 ms on
# a native daemon, and windows-desk measures the change at 0.1% on a
# bench whose mount is already local - so it is free where it does not
# help and large where it does.
#
# THE COPY-OUT ENDS THE FIRMWARE STEP, NOT THE RUN. tests/test_no_heap.py
# reads docker/out/build/*.elf during the HOST TIER, which runs after
# this script - so an artifact that appeared only at the end of the run
# would not be there when the tier looks for it. That is the same guard
# that went silently from passed to SKIPPED when the copy lacked
# docker/out, and it is why each track publishes before the next begins.
#
# Analysis builds are unaffected and deliberately so: -fstack-usage and
# -fcallgraph-info output is NOT among the artifacts copied, and
# FIRMWARE_STACK_USAGE and FIRMWARE_CALLGRAPH are never passed here, so
# a bench asking for either configures its own tree and keeps every
# intermediate where it expects it.
# No default here: docker/run.sh resolves it, so the default has one
# home. Empty - including run without that launcher - builds in place.
objdir=${DUE_BUILD_LOCAL-}

bdir() {  # bdir <name> - where this track's objects go
    if [ -n "$objdir" ]; then printf '%s/%s' "$objdir" "$1"
    else printf '%s' "$1"; fi
}

publish() {  # publish <build dir> <output dir>
    [ "$1" = "$2" ] && return 0
    # PUBLISHED STRAIGHT TO docker/out, NOT THROUGH A BIND MOUNT. The three
    # mounts that used to put build/ on top of docker/out/build existed
    # only so `cmake -B build` landed there; naming the destination
    # removes them, and it is the same directory whether this runs
    # against the mounted tree or against a copy that bridges docker/out.
    #
    # THE OUTPUT DIRECTORY HOLDS ONLY WHAT THIS BUILD PRODUCED. Anything
    # else is from an era when the objects were written here, and a
    # CMakeCache.txt sitting beside the artifacts says the build happened
    # in a directory it did not - the same misreading `clear_stale_images`
    # exists to prevent, one level up from the images. The contents go,
    # not the directory: it is a bind mount and cannot be removed.
    mkdir -p -- "$2"
    find "$2" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
    cp -f -- "$1"/*.bin "$1"/*.elf "$1"/*.map "$2"/ 2>/dev/null || true
}

# STALE IMAGES OUT BEFORE A BUILD, NOT AFTER.
#
# The output directories are bind mounts onto docker/out/ and survive
# every build, while record_build_env below lists whatever the directory
# HOLDS rather than what this build produced. Those two together mean a
# leftover is recorded as an artifact of this build, hashes and all, and
# tools/flash.py then accepts it as a current container image.
#
# Invisible until an artifact is renamed, because a leftover under the
# same name is simply overwritten. It became visible the day the images
# were renamed to carry their track, and both names sat in one manifest.
clear_stale_images() {  # clear_stale_images <dir>
    [ -d "$1" ] || return 0
    rm -f -- "$1"/*.bin "$1"/*.elf "$1"/*.map
}

record_build_env() {
    python3 - "$1" <<'PY'
import hashlib
import json
import os
import sys

d = sys.argv[1]
image_id = os.environ.get("DUE_BUILD_IMAGE_ID") or None
rec = {
    "build_env": "container" if image_id else "host",
    "build_image": os.environ.get("DUE_BUILD_IMAGE") if image_id else None,
    "build_image_id": image_id,
    "build_image_content": (os.environ.get("DUE_BUILD_IMAGE_CONTENT")
                            if image_id else None),
    "artifacts": {},
}
for name in sorted(os.listdir(d)):
    p = os.path.join(d, name)
    if name.endswith((".bin", ".elf")) and os.path.isfile(p):
        with open(p, "rb") as f:
            rec["artifacts"][name] = hashlib.sha256(f.read()).hexdigest()
path = os.path.join(d, "build-env.json")
with open(path, "w") as f:
    json.dump(rec, f, indent=2, sort_keys=True)
    f.write("\n")
print(f"{path}: {rec['build_env']} {rec['build_image'] or ''}".rstrip())
PY
}

# Reported, not gated. In the image `bossac` and `arduino_cli` are
# absent on purpose - nothing here flashes a board - and toolchain.py
# exits non-zero for a missing required tool, which is right on a bench
# and wrong here. What must resolve is the compiler, cmake and the SAM
# core, and the build below fails loudly if any of them did not.
echo "== where the tools resolved =="
python3 tools/toolchain.py || true
echo

echo "== configure =="
cmake -B "$(bdir build)" \
      -DCMAKE_TOOLCHAIN_FILE=cmake/arm-none-eabi-toolchain.cmake \
      -DCMAKE_BUILD_TYPE=Release >/dev/null
cmake -B "$(bdir build-a)" \
      -DCMAKE_TOOLCHAIN_FILE=cmake/arm-none-eabi-toolchain.cmake \
      -DCMAKE_BUILD_TYPE=Release -DBUILD_TRACK_A=ON >/dev/null
# Track C configures from the FreeRTOS copy the build image carries
# (DUE_FREERTOS_DIR, read by cmake/freertos.cmake), and on a bench without
# one it fetches FreeRTOS at the same pin.
cmake -B "$(bdir build-c)"       -DCMAKE_TOOLCHAIN_FILE=cmake/arm-none-eabi-toolchain.cmake       -DCMAKE_BUILD_TYPE=Release -DBUILD_TRACK_C=ON >/dev/null
echo "build, build-a, build-c"
echo

echo "== Track B =="
clear_stale_images docker/out/build
cmake --build "$(bdir build)" -j
publish "$(bdir build)" docker/out/build
record_build_env docker/out/build
echo

echo "== Track A =="
clear_stale_images docker/out/build-a
cmake --build "$(bdir build-a)" --target firmware_track_a --parallel
publish "$(bdir build-a)" docker/out/build-a
record_build_env docker/out/build-a
echo

echo "== Track C =="
clear_stale_images docker/out/build-c
cmake --build "$(bdir build-c)" --target firmware_track_c --parallel
publish "$(bdir build-c)" docker/out/build-c
record_build_env docker/out/build-c
echo

echo "== what built them =="
python3 tools/image_fingerprint.py docker/out/build/track_b_bringup.elf
python3 tools/image_fingerprint.py docker/out/build-a/track_a_bringup.elf
python3 tools/image_fingerprint.py docker/out/build-c/track_c_bringup.elf
