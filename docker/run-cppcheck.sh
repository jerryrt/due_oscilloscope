#!/bin/bash
# Run cppcheck over this project's own firmware sources.
#
#     docker/run.sh docker/run-cppcheck.sh
#     docker/run-cppcheck.sh            # on a bench, if cppcheck is there
#
# Written to run inside the image, from the repository root, and it
# carries no container knowledge - the same shape as
# docker/build-firmware.sh and docker/run-tests.sh, so a bench can run it
# and compare. The analyser is pinned in the Dockerfile because a
# different cppcheck reports a different set, and a finding list that
# moves under the reader cannot be told apart from new defects.
#
# OURS ONLY, WHICH IS A SCOPE DECISION AND NOT A SILENCING ONE.
# vendor/CMSIS and the Arduino SAM core are on the include path because
# the code will not parse without them, and their own findings are
# dropped: they are not ours to fix, which is the same reason
# CMakeLists.txt marks those directories SYSTEM. Everything under bsp/,
# drivers/, lib/due_shared/src/, apps/baremetal_bringup/ and
# sketches/bringup/ is reported in full.
#
# THERE IS NO SUPPRESSION LIST FOR OUR OWN CODE, AND --inline-suppr IS
# NOT PASSED, so a finding cannot be silenced by a comment either. A
# suppression written before anyone has decided what to do about a
# finding is how an analyser becomes a guard that cannot fail; this
# project has four documented cases of that, written in a single day.
#
# apps/baremetal_bringup/main.c is analysed although it is neither
# drivers/ nor bsp/, because main() is the one file per track that is not
# shared and is where four cross-track divergences were found in one
# afternoon. Track C (apps/rtos_bringup/) is NOT analysed: BUILD_TRACK_C
# fetches FreeRTOS at configure time and docker/run.sh runs with
# --network none, so those headers are not present. That is a gap, not a
# judgement about the code.
#
# EXIT CODES, and the distinction between them is the point.
#
#   0   cppcheck ran over both passes and reported nothing
#   1   cppcheck did not analyse - the tool is absent, an include did not
#       resolve, a file did not parse, or the SAM core is not installed
#   2   cppcheck ran and reported findings
#
# 1 and 2 are kept apart because an analyser that cannot run reports
# nothing, and "reported nothing" is what a clean run also looks like.
# Deleting cppcheck from the image, or pointing an include somewhere
# empty, has to fail LOUDLY rather than pass empty - that is phase 3's
# break-on-purpose in docs/build-container.md, and 2 must never be the
# code it produces.
#
# A non-zero exit on a finding is deliberate and is not softened by a
# baseline. Nothing consumes this exit code yet - there is no CI - so it
# costs no one a red build today, and the day something does consume it,
# the honest state of the tree is what it will read. A baseline file
# would be a suppression list wearing another name, and it would have to
# be written before anyone had acted on a single finding.
set -uo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

die() { echo "cppcheck: $*" >&2; exit 1; }

command -v cppcheck >/dev/null 2>&1 || die "not installed"

core=$(python3 tools/toolchain.py --dir arduino_sam_core) \
    || die "no Arduino SAM core; python3 tools/toolchain.py says where it looked"
[ -f "$core/cores/arduino/Arduino.h" ] \
    || die "Arduino SAM core at '$core' has no cores/arduino/Arduino.h"

# fw_git_rev.h is generated, and console.c and ctl_port.c include it. It
# normally lands in a build tree; generating it into a scratch directory
# keeps this script independent of whether anything has been built, and
# uses the generator the build itself uses so there is one definition.
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT
cmake -DREPO_DIR="$PWD" -DOUT_FILE="$scratch/fw_git_rev.h" \
      -DGIT_EXECUTABLE=git -P cmake/fw_git_rev.cmake >/dev/null \
    || die "could not generate fw_git_rev.h"

jobs=$(nproc 2>/dev/null || echo 2)

common=(
    -q
    --check-level=exhaustive
    --platform=arm32-wchar_t4
    --enable=warning,style,performance,portability,missingInclude
    '--template={file}:{line}:{column}: {severity}: {message} [{id}]'
    '--suppress=*:vendor/*'
    "--suppress=*:$core/*"
    # <stdint.h> and the rest of libc are not on the path and are not
    # meant to be: cppcheck models them itself and says so in the note it
    # emits. missingIncludeSystem is that note. Its sibling
    # missingInclude - a quoted header that did not resolve - is NOT
    # suppressed, and is what the guard below reads.
    --suppress=missingIncludeSystem
    -j "$jobs"
    -D__SAM3X8E__
    -I "$scratch"
)

echo "== cppcheck =="
cppcheck --version
echo "core: $core"
echo

# Track B and the shared wire contract, as C. lib/due_shared/src is
# compiled as C by both tracks, so it is analysed once, here.
echo "== Track B, bsp, drivers, lib/due_shared/src (C11) =="
cppcheck "${common[@]}" \
    --std=c11 \
    -I bsp -I drivers -I lib/due_shared/src \
    -I vendor/CMSIS/Include \
    -I vendor/CMSIS/Device/ATMEL \
    -I vendor/CMSIS/Device/ATMEL/sam3xa/include \
    bsp drivers lib/due_shared/src apps/baremetal_bringup \
    >"$scratch/b.txt" 2>&1
b_status=$?
sort "$scratch/b.txt"
echo

# Track A, as C++11 against the Arduino core, matching
# cmake/track_a.cmake's flags for the sketch target. bringup.ino is named
# explicitly: cppcheck does not recognise the extension when it walks a
# directory, and arduino-cli's implicit `#include <Arduino.h>` is
# supplied by --include, exactly as track_a.cmake supplies it with
# -include.
echo "== Track A, sketches/bringup (C++11, Arduino core) =="
cppcheck "${common[@]}" \
    --language=c++ --std=c++11 \
    -DF_CPU=78000000L -DARDUINO=10819 -DARDUINO_SAM_DUE \
    -DARDUINO_ARCH_SAM -DUSBCON -DUSB_VID=0x2341 -DUSB_PID=0x003e \
    -I lib/due_shared/src -I sketches/bringup \
    -I "$core/system/libsam" \
    -I "$core/system/libsam/include" \
    -I "$core/system/CMSIS/CMSIS/Include" \
    -I "$core/system/CMSIS/Device/ATMEL" \
    -I "$core/system/CMSIS/Device/ATMEL/sam3xa/include" \
    -I "$core/cores/arduino" \
    -I "$core/variants/arduino_due_x" \
    --include="$core/cores/arduino/Arduino.h" \
    sketches/bringup sketches/bringup/bringup.ino \
    >"$scratch/a.txt" 2>&1
a_status=$?
sort "$scratch/a.txt"
echo

cat "$scratch/b.txt" "$scratch/a.txt" > "$scratch/all.txt"

# A file that did not parse produces no findings, and no findings is what
# a clean run also produces. These ids mean the analysis did not happen,
# so they are an exit 1 and never an exit 2.
#
# missingInclude is in that list because it is the one that fires when an
# include path is pointed somewhere empty, and NOTHING ELSE DOES.
# Measured: redirect all three vendor/CMSIS paths at a directory that
# does not exist and cppcheck reports the identical finding set and the
# identical exit - it parses what it can and says nothing about the
# header it could not open. So the obvious break-on-purpose for this
# script was silently invisible until missingInclude was turned on, and
# the guard was passing for the reason a guard must never pass.
unanalysed='\[(internalError|syntaxError|preprocessorErrorDirective|internalAstError|missingInclude)\]'
if grep -qE "$unanalysed" "$scratch/all.txt"; then
    echo "== cppcheck did not analyse everything =="
    grep -E "$unanalysed" "$scratch/all.txt"
    exit 1
fi

# cppcheck exits 1 on a usage or configuration failure and 0 otherwise.
# --error-exitcode is deliberately not used: it cannot tell a finding
# from a parse failure, and this script has to.
if [ "$b_status" -gt 1 ] || [ "$a_status" -gt 1 ]; then
    die "cppcheck exited $b_status (C) / $a_status (C++)"
fi

echo "== findings =="
total=0
for sev in error warning style performance portability; do
    n=$(grep -c ": $sev: " "$scratch/all.txt")
    printf '%-14s %s\n' "$sev" "$n"
    total=$((total + n))
done
printf '%-14s %s\n' "total" "$total"

[ "$total" -eq 0 ] || exit 2
