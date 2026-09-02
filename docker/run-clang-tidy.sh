#!/bin/bash
# Run clang-tidy over this project's own firmware sources.
#
#     docker/run.sh docker/run-clang-tidy.sh
#     docker/run-clang-tidy.sh          # on a bench, if clang-tidy is there
#
# The same shape as docker/run-cppcheck.sh, deliberately: written to run
# inside the image, from the repository root, carrying no container
# knowledge, so a bench can run it and compare. The analyser is pinned in
# the Dockerfile because a different clang-tidy reports a different set,
# and a finding list that moves under the reader cannot be told apart
# from new defects.
#
# WHAT IT CHECKS IS IN .clang-tidy AT THE REPOSITORY ROOT, not here.
# Two families - clang-analyzer-* and bugprone-* - and the argument for
# them, and for the three checks switched off inside them, is written
# there beside the counts each was measured at.
#
# OURS ONLY, WHICH IS A SCOPE DECISION AND NOT A SILENCING ONE.
# vendor/CMSIS, the Arduino SAM core and newlib reach the compiler
# through -isystem and are not reported: they are not ours to fix, which
# is the same reason CMakeLists.txt marks those directories SYSTEM.
# Everything under bsp/, drivers/, lib/due_shared/src/,
# apps/baremetal_bringup/ and sketches/bringup/ is reported in full.
#
# lib/due_shared/src is compiled by both tracks and is analysed once, in
# the Track B pass, as cppcheck does it. That is a real gap and not a
# free choice: Track A compiles those same files as C++ with
# -Dprintf=iprintf and the Arduino defines, and a finding that only
# appears under that dialect is not looked for here.
#
# Track C (apps/rtos_bringup/) is NOT analysed: BUILD_TRACK_C fetches
# FreeRTOS at configure time and docker/run.sh runs with --network none,
# so it cannot be configured in the image at all.
#
# THERE IS NO SUPPRESSION LIST AND NO BASELINE. A finding is answered or
# explained, never filed. A baseline written before anyone has acted on
# a finding is a suppression list under another name, and this project
# has four documented cases of an analyser becoming a guard that cannot
# fail, all written in a single day.
#
# EXIT CODES, and the distinction between them is the point.
#
#   0   clang-tidy ran over both passes and reported nothing
#   1   clang-tidy did not analyse - the tool is absent, a build tree
#       would not configure, a source is missing from the compile
#       database, a translation unit did not parse, or the canary below
#       did not fire
#   2   clang-tidy ran and reported findings
#
# 1 AND 2 ARE KEPT APART BECAUSE CLANG-TIDY WILL NOT KEEP THEM APART.
# Measured here, not assumed: point it at an EMPTY compile database and
# name a source that exists, and it prints one line -
#
#     Skipping /work/drivers/play.c. Compile command not found.
#
# - and exits 0. That is "analysed nothing" wearing the exit code of
# "found nothing", and no output tells the two apart unless something
# reads that line. A translation unit that fails to PARSE does come back
# non-zero, which is a different hole and a smaller one; this script
# detects it by its text rather than by its status, because a status
# that means "could not analyse" and a status that means "found a
# defect" must not be the same number here.
#
# THE CANARY IS THE PART THAT CANNOT BE FAKED. Before either pass, a
# synthetic translation unit is analysed under that pass's own flags -
# taken from a real database entry, not written out here - and it must
# produce four specific diagnostics:
#
#   clang-analyzer-core.DivideZero      the symbolic execution engine is
#                                       running, which nothing else in
#                                       this tree currently proves: the
#                                       real sources trip no
#                                       path-sensitive check at all
#   bugprone-branch-clone               the bugprone family is enabled
#   clang-diagnostic-unused-variable    the compiler-diagnostic half is
#                                       alive, ie -w was dropped
#   (silence from two hard assertions)  the target really is ARM, and
#                                       the libc headers really resolved
#
# The last one is inverted on purpose: the canary carries an assertion
# that the pointer is four bytes and an #include <stdio.h>, and both
# must PASS. Point the include path at nothing, or let the analysis fall
# back to the host triple, and the canary fails loudly instead of the
# whole run going quietly green - which is the exact hole that made the
# cppcheck break-on-purpose invisible until missingInclude was turned
# on.
#
# A non-zero exit on a finding is deliberate and is not softened.
# Nothing consumes this exit code yet - there is no CI - so it costs no
# one a red build today, and the day something does consume it, the
# honest state of the tree is what it will read.
set -uo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
repo=$PWD

die() { echo "clang-tidy: $*" >&2; exit 1; }

command -v clang-tidy >/dev/null 2>&1 || die "not installed"
[ -f "$repo/.clang-tidy" ] \
    || die "no .clang-tidy at $repo - the default check set is nearly empty, so
         running without it would report nothing and exit 0"

scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT

echo "== clang-tidy =="
clang-tidy --version | sed -n '1,2p'
echo "config: $repo/.clang-tidy"
sed -n '/^Checks:/,/^$/p' "$repo/.clang-tidy"

# Configured into a scratch tree rather than into build/ and build-a/.
# Two reasons and both are practical: the database is then guaranteed to
# describe the source as it stands right now, and a bench's own build
# directories - which may hold the image that is on its board - are not
# touched. A configure is about half a second; nothing is compiled.
echo "== configure =="
cmake -B "$scratch/cfg-b" -S "$repo" \
      -DCMAKE_TOOLCHAIN_FILE=cmake/arm-none-eabi-toolchain.cmake \
      -DCMAKE_BUILD_TYPE=Release >"$scratch/cfg-b.log" 2>&1 \
    || { sed -n '$p;/Error/p' "$scratch/cfg-b.log" >&2
         die "Track B would not configure; see the log above"; }
cmake -B "$scratch/cfg-a" -S "$repo" \
      -DCMAKE_TOOLCHAIN_FILE=cmake/arm-none-eabi-toolchain.cmake \
      -DCMAKE_BUILD_TYPE=Release -DBUILD_TRACK_A=ON >"$scratch/cfg-a.log" 2>&1 \
    || { sed -n '$p;/Error/p' "$scratch/cfg-a.log" >&2
         die "Track A would not configure - most likely no Arduino SAM core;
         python3 tools/toolchain.py says where it looked"; }
echo "cfg-b, cfg-a"
echo

# The canary. One body, written twice so the C pass gets a .c and the
# C++ pass a .cpp; the language comes from the extension, because the
# flags it inherits carry -std=gnu11 or -std=gnu++11 and nothing else
# would agree with them.
#
# `typedef char ...[cond ? 1 : -1]` rather than _Static_assert: the same
# text has to compile as both C and C++, and _Static_assert is C's.
canary_body='
#include <stdio.h>
#include <string.h>

typedef char canary_ptr_is_32bit[(sizeof(void *) == 4) ? 1 : -1];
#if !defined(__ARM_ARCH)
#error "canary: __ARM_ARCH undefined - this is not an ARM target"
#endif

int canary_divide_by_zero(void);
int canary_divide_by_zero(void)
{
	int n = 0;
	return 10 / n;
}

int canary_branch_clone(int c);
int canary_branch_clone(int c)
{
	if (c)
		return 1;
	else
		return 1;
}

int canary_unused_variable(void);
int canary_unused_variable(void)
{
	int never_read = 1;
	return 0;
}
'
printf '%s' "$canary_body" > "$scratch/canary.c"
printf '%s' "$canary_body" > "$scratch/canary.cpp"

tidy() {  # tidy <database dir> <output file> <source>...
	local db=$1 out=$2
	shift 2
	clang-tidy -p "$db" --quiet --config-file="$repo/.clang-tidy" "$@" \
	    >"$out" 2>&1
}

# The ids that mean the analysis did not happen. A file missing from the
# database and a file that would not parse both report nothing, and
# nothing is what a clean run reports too.
unanalysed='Error while processing|\[clang-diagnostic-error\]|^Skipping '

# The three diagnostics the canary must produce, one per line, as
# extended-regex fragments. The fourth requirement - the ARM target and
# the libc headers - is the ABSENCE of an error, and is checked by the
# same unanalysed pattern the passes use.
required='\[clang-analyzer-core\.DivideZero\]
\[bugprone-branch-clone\]
\[clang-diagnostic-unused-variable\]'

check_canary() {  # check_canary <label> <output file>
	local label=$1 out=$2 missing=0 pat
	if grep -qE "$unanalysed" "$out"; then
		echo "== the $label canary did not compile =="
		cat "$out"
		exit 1
	fi
	while IFS= read -r pat; do
		grep -qE -- "$pat" "$out" || { echo "  MISSING $pat"; missing=1; }
	done <<< "$required"
	if [ "$missing" -ne 0 ]; then
		echo "== the $label canary did not fire =="
		echo "clang-tidy ran and did not report a defect it is configured"
		echo "to catch, so a clean pass below would mean nothing."
		cat "$out"
		exit 1
	fi
	echo "$label canary: all $(grep -c . <<< "$required") diagnostics fired"
}

pass() {  # pass <label> <cfg dir> <target prefix> <sentinel> <ext> <under>...
	local label=$1 cfg=$2 target=$3 sentinel=$4 ext=$5
	shift 5
	local under=()
	local u
	for u in "$@"; do under+=(--under "$u"); done

	python3 docker/clang_tidy_db.py \
	        --db "$cfg/compile_commands.json" \
	        --out "$scratch/db-$label" \
	        --repo "$repo" \
	        --target-dir "$target" \
	        --canary-src "$scratch/canary.$ext" \
	        --canary-out "$scratch/canary-$label" \
	        "${under[@]}" > "$scratch/files-$label" \
	    || die "could not build the $label compile database"

	# Every source the pass believes it covers must be IN the database.
	# clang-tidy warns and exits 0 for one that is not, so the check has
	# to happen here.
	local n
	n=$(grep -c . "$scratch/files-$label")
	[ "$n" -gt 0 ] || die "$label: no source selected"
	grep -qx "$repo/$sentinel" "$scratch/files-$label" \
	    || die "$label: $sentinel is not in the compile database, so the
         selection has moved and the file count below means nothing"
	echo "$label: $n sources, sentinel $sentinel present"

	tidy "$scratch/canary-$label" "$scratch/canary-$label.txt" \
	     "$scratch/canary.$ext"
	check_canary "$label" "$scratch/canary-$label.txt"

	# shellcheck disable=SC2046  # the file list is one path per line
	tidy "$scratch/db-$label" "$scratch/$label.txt" \
	     $(cat "$scratch/files-$label")

	if grep -qE "$unanalysed" "$scratch/$label.txt"; then
		echo "== clang-tidy did not analyse everything ($label) =="
		grep -E "$unanalysed" "$scratch/$label.txt"
		exit 1
	fi
	grep -E ': (warning|error): .*\]$' "$scratch/$label.txt" | sort
}

echo "== Track B: apps/baremetal_bringup, bsp, drivers, lib/due_shared/src =="
pass b "$scratch/cfg-b" CMakeFiles/baremetal_bringup.dir/ drivers/play.c c \
     apps/baremetal_bringup bsp drivers lib/due_shared/src
echo

echo "== Track A: sketches/bringup =="
pass a "$scratch/cfg-a" CMakeFiles/track_a_bringup.dir/ \
     sketches/bringup/bringup.ino cpp sketches/bringup
echo

cat "$scratch/b.txt" "$scratch/a.txt" > "$scratch/all.txt"
grep -E ': (warning|error): .*\]$' "$scratch/all.txt" > "$scratch/found.txt"

echo "== findings =="
awk -F'[][]' '{print $(NF-1)}' "$scratch/found.txt" | sort | uniq -c | sort -rn
total=$(grep -c . "$scratch/found.txt")
printf '%-14s %s\n' "total" "$total"

[ "$total" -eq 0 ] || exit 2
