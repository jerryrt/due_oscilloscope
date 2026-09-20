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
cmake -B build \
      -DCMAKE_TOOLCHAIN_FILE=cmake/arm-none-eabi-toolchain.cmake \
      -DCMAKE_BUILD_TYPE=Release >/dev/null
cmake -B build-a \
      -DCMAKE_TOOLCHAIN_FILE=cmake/arm-none-eabi-toolchain.cmake \
      -DCMAKE_BUILD_TYPE=Release -DBUILD_TRACK_A=ON >/dev/null
# Track C configures from the FreeRTOS copy the build image carries
# (DUE_FREERTOS_DIR, read by cmake/freertos.cmake), and on a bench without
# one it fetches FreeRTOS at the same pin.
cmake -B build-c       -DCMAKE_TOOLCHAIN_FILE=cmake/arm-none-eabi-toolchain.cmake       -DCMAKE_BUILD_TYPE=Release -DBUILD_TRACK_C=ON >/dev/null
echo "build, build-a, build-c"
echo

echo "== Track B =="
clear_stale_images build
cmake --build build -j
record_build_env build
echo

echo "== Track A =="
clear_stale_images build-a
cmake --build build-a --target firmware_track_a --parallel
record_build_env build-a
echo

echo "== Track C =="
clear_stale_images build-c
cmake --build build-c --target firmware_track_c --parallel
record_build_env build-c
echo

echo "== what built them =="
python3 tools/image_fingerprint.py build/track_b_bringup.elf
python3 tools/image_fingerprint.py build-a/track_a_bringup.elf
python3 tools/image_fingerprint.py build-c/track_c_bringup.elf
