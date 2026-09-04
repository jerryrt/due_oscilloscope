#!/bin/bash
# Configure and build both firmware tracks, then say what built them.
#
#     docker/run.sh docker/build-firmware.sh
#
# Written to run inside the image, from the repository root. It carries
# no container knowledge at all - the commands are CLAUDE.md's, verbatim
# - so a bench can run it directly and get its own compiler's answer to
# compare against the container's.
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
echo "build, build-a"
echo

echo "== Track B =="
cmake --build build -j
record_build_env build
echo

echo "== Track A =="
cmake --build build-a --target firmware_track_a --parallel
record_build_env build-a
echo

echo "== what built them =="
python3 tools/image_fingerprint.py build/baremetal_bringup.elf
python3 tools/image_fingerprint.py build-a/track_a_bringup.elf
