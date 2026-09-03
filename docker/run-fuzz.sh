#!/bin/bash
# A libFuzzer campaign over the control-protocol parser.
#
#     docker/run.sh docker/run-fuzz.sh              # 60 s
#     docker/run.sh docker/run-fuzz.sh 900          # 15 minutes
#     DUE_FUZZ_CORPUS=/work/docker/out/fuzz \
#         docker/run.sh docker/run-fuzz.sh 3600     # and keep the corpus
#
# Written to run inside the image, from the repository root, and it
# carries no container knowledge - the same shape as
# docker/build-firmware.sh, docker/run-tests.sh and
# docker/run-cppcheck.sh, so a bench with clang can run it and compare.
#
# WHY THIS IS NOT IN THE TEST SUITE. A campaign has no natural end: its
# value is proportional to the time it is given, and the board-free tier
# is under a five-minute ceiling that the whole project's per-change loop
# depends on. So the tier runs the deterministic half - the seed corpus
# and a fixed pseudo-random grind, about a second, in
# tests/test_ctl_fuzz.py - and the coverage-guided half lives here.
# tests/ctl/fuzz_ctl.c is ONE target with two entry points, so the two
# halves cannot drift apart.
#
# THE POSITIVE CONTROL RUNS EVERY TIME, and that is the point of the
# script rather than a nicety. A fuzzer that finds nothing and a fuzzer
# that cannot run produce the same output, exactly as an analyser that
# found nothing and one that analysed nothing do - docker/run-cppcheck.sh
# separates those two for the same reason. So before the real campaign
# this builds a target against a ctl.c with the payload-length check
# removed and requires libFuzzer to crash it. If the control does not
# crash, this script exits 1 and never reports a clean campaign.
#
# The mutation is not written here. It is read out of
# tests/test_ctl_fuzz.py's MUTATIONS, so the mutation the campaign is
# certified against and the mutation the suite tests with are the same
# text, and a reword breaks both at once instead of silently disarming
# this one.
#
# EXIT CODES, and the distinction between them is the point.
#
#   0   the control crashed as required and the campaign found nothing
#   1   the fuzzer could not run - no clang, no libFuzzer runtime, a
#       build failure, or a positive control that did not crash
#   2   the campaign found something. The reproducer is left in
#       $DUE_FUZZ_CORPUS/crashes and named in the output
set -uo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

die() { echo "fuzz: $*" >&2; exit 1; }

seconds=${1:-60}
shared=lib/due_shared/src
target=tests/ctl/fuzz_ctl.c

command -v clang >/dev/null 2>&1 || die "clang is not installed"
[ -f "$target" ] || die "no $target"

# Ephemeral unless a caller names somewhere to keep it. A corpus that
# survives between runs is most of what makes a long campaign worth more
# than a short one, and a corpus written into the tree by default is
# untracked output nobody asked for.
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
corpus=${DUE_FUZZ_CORPUS:-$work/corpus}
mkdir -p "$corpus" "$corpus/crashes" "$work/seeds"

# ctl.c's own idle threshold, so the harness returns the parser to idle
# between inputs through the protocol's rule rather than a copied number.
idle=$(sed -n 's/^#define[[:space:]]*CTL_IDLE_US[[:space:]]*\([0-9]*\)u\?[[:space:]]*$/\1/p' \
       "$shared/ctl.c")
[ -n "$idle" ] || die "cannot read CTL_IDLE_US out of $shared/ctl.c"

common=(
    -std=c11 -Wall -Wextra -g -O1
    -fno-sanitize-recover=all
    -fno-omit-frame-pointer
    "-DCTL_IDLE_US_PROBE=${idle}u"
    -I "$shared"
)
sources=("$shared/crc32.c" "$shared/console_out.c")

echo "== clang =="
clang --version | head -2
echo "CTL_IDLE_US = $idle"
echo "corpus: $corpus"
echo

build_fuzzer() {   # <out> <ctl.c>
    clang "${common[@]}" -DCTL_FUZZ_LIBFUZZER \
        -fsanitize=fuzzer,address,undefined \
        -o "$1" "$target" "$2" "${sources[@]}"
}

echo "== the seed corpus =="
clang "${common[@]}" -fsanitize=address,undefined \
    -o "$work/seedgen" "$target" "$shared/ctl.c" "${sources[@]}" \
    || die "the standalone target did not build"
"$work/seedgen" --write-seeds "$work/seeds" || die "could not write seeds"
cp -n "$work"/seeds/*.bin "$corpus"/ 2>/dev/null
echo

# ---------------------------------------------------------------------
# The positive control. A deliberately broken parser, which libFuzzer
# must crash inside a few seconds; a control it cannot crash certifies
# nothing, and this script refuses to report a clean campaign after one.
# ---------------------------------------------------------------------
echo "== positive control: a parser with no payload-length check =="
python3 - "$shared/ctl.c" "$work/ctl_mutant.c" <<'PY' || die "could not build the mutant"
import sys
sys.path.insert(0, "tests")
from test_ctl_fuzz import MUTATIONS

m = MUTATIONS["no-length-check"]
src = open(sys.argv[1]).read()
if src.count(m["find"]) != 1:
    raise SystemExit("the no-length-check anchor is not in ctl.c verbatim")
open(sys.argv[2], "w").write(src.replace(m["find"], m["replace"], 1))
PY

build_fuzzer "$work/fuzz_mutant" "$work/ctl_mutant.c" \
    || die "the mutant target did not build"
# -artifact_prefix, so the reproducer lands in the scratch directory.
# Without it libFuzzer writes crash-<sha> into the working directory,
# which here is the bind-mounted repository.
"$work/fuzz_mutant" "$work/seeds" -runs=200000 -max_total_time=60 \
    -print_final_stats=1 -artifact_prefix="$work/" > "$work/control.txt" 2>&1
control=$?
tail -20 "$work/control.txt"
if [ "$control" -eq 0 ]; then
    die "the positive control did NOT crash. libFuzzer is running and
     finding nothing in a parser that writes 200 bytes past rx_payload,
     so a clean campaign below would mean nothing"
fi
echo "control crashed as required (exit $control)"
echo

echo "== campaign: ${seconds}s over lib/due_shared/src/ctl.c =="
build_fuzzer "$work/fuzz_ctl" "$shared/ctl.c" \
    || die "the fuzz target did not build"
"$work/fuzz_ctl" "$corpus" -max_total_time="$seconds" \
    -print_final_stats=1 -artifact_prefix="$corpus/crashes/" "${@:2}"
found=$?
echo

if [ "$found" -ne 0 ]; then
    echo "== the campaign found something =="
    ls -l "$corpus/crashes"
    echo
    echo "replay it:  fuzz_ctl <file>   (the standalone build takes a path)"
    exit 2
fi

echo "== no finding in ${seconds}s, from a fuzzer proven able to crash =="
echo "corpus is $(find "$corpus" -maxdepth 1 -name '*' -type f | wc -l) files"
