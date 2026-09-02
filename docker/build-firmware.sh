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
echo

echo "== Track A =="
cmake --build build-a --target firmware_track_a --parallel
echo

echo "== what built them =="
python3 tools/image_fingerprint.py build/baremetal_bringup.elf
python3 tools/image_fingerprint.py build-a/track_a_bringup.elf
