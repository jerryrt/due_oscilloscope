#!/bin/bash
# Run every check the build container can make, and say what did not run.
#
#     docker/run.sh docker/run-ci.sh              # everything
#     docker/run.sh docker/run-ci.sh --fast       # without the elastic steps
#     docker/run.sh docker/run-ci.sh --fuzz 900   # a real campaign
#     docker/run-ci.sh                            # on a bench, same shape
#
# Written to run inside the image, from the repository root, and it
# carries no container knowledge - the same shape as
# docker/build-firmware.sh, docker/run-tests.sh, docker/run-cppcheck.sh,
# docker/run-clang-tidy.sh and docker/run-fuzz.sh. docker/run.sh is the
# one file that knows about the container, and one is the right number:
# a second home for that knowledge is two copies that start disagreeing.
#
# WHAT THIS EXISTS TO PREVENT is a summary that scores a step as passed
# when the step did not run. That failure has been paid for four times in
# this tree in a single day - an assertion satisfied by a comment, a
# regex eaten by a heredoc, a rate 512x low, and a shell tally that read
# "1 skipped, 6 deselected" as a pass - and it is why
# docker/run-cppcheck.sh, docker/run-clang-tidy.sh and docker/run-fuzz.sh
# each separate "found nothing" from "analysed nothing" in their exit
# codes. Nothing consumed that distinction until this script. Consuming
# it is most of what this script is.
#
# SO THERE ARE FIVE STATES AND NOT TWO. Every step lands in exactly one,
# it is printed in a fixed column, and no two of the words overlap:
#
#   PASS           it ran, and what it checks holds
#   FINDINGS       it ran, and reported things that do not gate
#   FAIL           it ran, and what it checks does not hold
#   DID NOT RUN    it could not run, or could not analyse what it names.
#                  The question it was asked is UNANSWERED, which is not
#                  the same as answered well, and it gates
#   NOT SELECTED   --fast, or a precondition this environment does not
#                  meet. Never counted towards a pass
#
# EXIT CODES, the convention the analysers already use, so nothing here
# invents a sixth vocabulary:
#
#   0   every selected step ran, and nothing gating failed
#   1   a step DID NOT RUN. The tree's state is unknown, not good
#   2   every step ran and a gating step failed
#
# 1 wins over 2 when both happen, because "part of this was not checked"
# is the weaker claim and the honest one to report.
#
# WHAT GATES, AND WHY NOT EVERYTHING.
#
#   firmware, host tier, board absent, reproducible   gate
#   fuzz: a crash gates, and so does a fuzzer that could not be built
#   cppcheck, clang-tidy: FINDINGS is advisory, DID NOT RUN gates
#
# The two analysers report dozens of findings on a clean tree today, all
# triaged and none fixed, so gating on "any finding" would be red on day
# one - and a check that is red on day one is a check nobody reads, which
# is the same outcome as no check. What is NOT softened is their other
# exit: an analyser that could not analyse gates, because that is the
# state this whole design is about. A baseline file would invert both
# halves of that - gate on findings and silence the existing ones - and a
# suppression written before anyone has acted on a finding is how an
# analyser becomes a guard that cannot fail.
#
# A fuzz crash is not a backlog and does gate. It is a defect in a wire
# parser a peer can reach.
#
# THE BOARD IS NOT TOUCHED, AND THE SUMMARY SAYS SO IN THE SAME BREATH.
# Nothing here opens a serial port. Every board test is deselected from
# the host tier by -m "not board", and a deselected test scores as a pass
# in any harness that greps for failures - so this does not merely assert
# that the board tier did not run. It runs the tier's own positive
# control: the board tests under --require-board, which must ERROR for
# want of hardware. A control that ran and errored is evidence; a
# sentence in a summary is not. Where a board IS reachable - a bench
# running this script directly rather than the image, which has no device
# nodes - that control is NOT SELECTED rather than executed, because
# running it would open the port it exists to prove absent.
#
# NOTHING STOPS AT THE FIRST FAILURE. The product of this script is the
# whole table, and a run that halts at step two reports four states it
# never established. The steps are ordered cheapest-and-most-fundamental
# first, so a broken tree is visible early anyway, and a step whose input
# an earlier step failed to produce reports DID NOT RUN - the cascade
# reading correctly rather than a second failure.
#
# LOGS. Every step's full output is written to docker/out/ci/<step>.log
# and echoed as it runs, so a count in the summary can be checked against
# the thing it was read from.
set -uo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
repo=$PWD

# The five states, spelled once. A typo in one branch would otherwise
# invent a sixth that the verdict below does not know how to weigh.
S_PASS='PASS'
S_FIND='FINDINGS'
S_FAIL='FAIL'
S_NORUN='DID NOT RUN'
S_SKIP='NOT SELECTED'

fast=0
fuzz_seconds=30
logs=${DUE_CI_LOGS:-$repo/docker/out/ci}

usage() {
	cat <<'USAGE'
docker/run.sh docker/run-ci.sh [--fast] [--fuzz SECONDS] [--logs DIR]

  --fast          drop the three elastic steps - cppcheck, clang-tidy
                  and the fuzz campaign - whose cost is chosen rather
                  than set by the size of the tree
  --fuzz SECONDS  campaign length, default 30. 0 drops it
  --logs DIR      per-step logs, default docker/out/ci

exit 0 everything ran and nothing gating failed
     1 a step DID NOT RUN, so the answer is unknown rather than good
     2 every step ran and a gating step failed
USAGE
}

while [ "$#" -gt 0 ]; do
	case "$1" in
	--fast) fast=1; shift ;;
	--fuzz)
		fuzz_seconds=${2:-}
		case "$fuzz_seconds" in
		'' | *[!0-9]*) echo "--fuzz takes a whole number of seconds" >&2; exit 1 ;;
		esac
		shift 2 ;;
	--logs) logs=${2:?--logs needs a directory}; shift 2 ;;
	-h | --help) usage; exit 0 ;;
	*) echo "unknown argument: $1" >&2; usage >&2; exit 1 ;;
	esac
done

mkdir -p "$logs" || { echo "cannot write logs to $logs" >&2; exit 1; }

# One record per step, tab separated: name, state, seconds, detail.
records=()

record() {  # record <name> <state> <seconds> <detail>
	records+=("$1"$'\t'"$2"$'\t'"$3"$'\t'"$4")
}

now() { date +%s.%N; }

took() { awk -v a="$1" -v b="$2" 'BEGIN { printf "%.1f", b - a }'; }

# The last line of a log matching a pattern, for the detail column. An
# empty answer says so rather than printing blank, because a missing
# count reads as a clean count.
last_match() {  # last_match <log> <extended regex>
	local hit
	hit=$(grep -E -- "$2" "$1" 2>/dev/null | tail -1)
	echo "${hit:-(nothing matching in $1)}"
}

first_match() {  # first_match <log> <extended regex>
	local hit
	hit=$(grep -m1 -E -- "$2" "$1" 2>/dev/null)
	echo "${hit:-(nothing matching in $1)}"
}

# A tool resolved through the registry rather than off PATH: on two of
# this project's three benches the build tools are not on PATH.
have_tool() {  # have_tool <registry name>
	python3 tools/toolchain.py --exe "$1" >/dev/null 2>&1
}

have_pytest() { python3 -m pytest --version >/dev/null 2>&1; }

# ---------------------------------------------------------------------
# The step runner. Every step goes through it, so no step can hold its
# own opinion about what its exit code meant.
# ---------------------------------------------------------------------
run_step() {  # run_step <name> <classifier> <command...>
	local name=$1 classify=$2
	shift 2
	local log="$logs/${name// /-}.log" start stop rc

	echo
	echo "############ $name ############"
	start=$(now)
	"$@" 2>&1 | tee "$log"
	rc=${PIPESTATUS[0]}
	stop=$(now)

	local verdict state detail
	verdict=$("$classify" "$rc" "$log")
	state=${verdict%%$'\t'*}
	detail=${verdict#*$'\t'}
	record "$name" "$state" "$(took "$start" "$stop")" "$detail"
	echo "---- $name: $state ($detail)"
}

skip_step() {  # skip_step <name> <reason>
	record "$1" "$S_SKIP" "0.0" "$2"
	echo
	echo "############ $1 ############"
	echo "$S_SKIP: $2"
}

norun_step() {  # norun_step <name> <reason>
	record "$1" "$S_NORUN" "0.0" "$2"
	echo
	echo "############ $1 ############"
	echo "$S_NORUN: $2"
}

# ---------------------------------------------------------------------
# Classifiers. Each maps a child's exit code onto a state, and this
# script's whole claim lives in them: a code a classifier does not
# recognise is DID NOT RUN, never PASS. 127 - what a renamed or deleted
# script produces - therefore lands there by construction rather than by
# a case arm somebody remembered to write.
# ---------------------------------------------------------------------

# docker/run-cppcheck.sh, docker/run-clang-tidy.sh: 0 found nothing,
# 1 analysed nothing, 2 found things.
class_analyser() {
	local rc=$1 log=$2 total
	total=$(awk '$1 == "total" { print $2 }' "$log" 2>/dev/null | tail -1)
	case "$rc" in
	0) echo "$S_PASS"$'\t'"no findings" ;;
	2) echo "$S_FIND"$'\t'"${total:-?} findings, advisory" ;;
	*) echo "$S_NORUN"$'\t'"exit $rc: $(last_match "$log" '.')" ;;
	esac
}

# docker/run-fuzz.sh: 0 the positive control crashed and the campaign
# found nothing, 1 the fuzzer could not run or its control did not crash,
# 2 the campaign found something.
class_fuzz() {
	local rc=$1 log=$2 execs
	# The last block, because the positive control prints one of its own
	# before the campaign does.
	execs=$(awk '/number_of_executed_units/ { v = $NF } END { print v }' "$log")
	case "$rc" in
	0) echo "$S_PASS"$'\t'"${execs:-?} executions, no finding" ;;
	2) echo "$S_FAIL"$'\t'"the campaign crashed the parser; see $log" ;;
	*) echo "$S_NORUN"$'\t'"exit $rc: $(last_match "$log" '.')" ;;
	esac
}

# pytest: 0 passed, 1 tests failed, 2 interrupted, 3 internal error,
# 4 usage error, 5 nothing collected. Only 0 and 1 are answers.
class_pytest() {
	local rc=$1 log=$2 summary
	summary=$(last_match "$log" '[0-9]+ (passed|failed|error|skipped|deselected)')
	case "$rc" in
	0) echo "$S_PASS"$'\t'"$summary" ;;
	1) echo "$S_FAIL"$'\t'"$summary" ;;
	5) echo "$S_NORUN"$'\t'"pytest collected no tests" ;;
	*) echo "$S_NORUN"$'\t'"pytest exit $rc: $summary" ;;
	esac
}

# The board-absent control, whose assertion is inverted: the board tests
# must ERROR for want of hardware. A zero exit means a board answered,
# which in an environment chosen because it has none is a fault in the
# environment and not a pass.
#
# EVERY TEST HERE IS AGAINST THE SUMMARY LINE AND NOT AGAINST THE LOG.
# Grepping the whole log for "[0-9]+ passed" reads every clean run as a
# board contact: pytest echoes the failing fixture's source, and
# conftest.py's own comment about --require-board contains the words
# `match "1 passed"`. A guard satisfied by a comment is the first of the
# four this project documents, and it is easy to write right here.
class_board_absent() {
	local rc=$1 log=$2 summary
	summary=$(last_match "$log" '[0-9]+ (passed|failed|error|skipped|deselected)')
	if [ "$rc" -eq 0 ]; then
		echo "$S_FAIL"$'\t'"the control did not error - a board answered"
	elif grep -qE '[0-9]+ passed' <<< "$summary"; then
		echo "$S_FAIL"$'\t'"a board test PASSED, so hardware was reached"
	elif grep -qE '[0-9]+ error' <<< "$summary"; then
		echo "$S_PASS"$'\t'"$summary"
	else
		echo "$S_NORUN"$'\t'"neither errors nor passes: $summary"
	fi
}

# The firmware build. Its preconditions are checked before it is
# attempted, so a non-zero exit from here is a build that failed rather
# than a toolchain that was absent - the one distinction an exit code
# alone cannot carry.
class_build() {
	local rc=$1 log=$2 layouts
	layouts=$(grep -oE '"layout": "[0-9a-f]+"' "$log" | sed 's/.*: "//; s/"//' \
	          | paste -sd' ' -)
	case "$rc" in
	0) echo "$S_PASS"$'\t'"layouts ${layouts:-(not reported)}" ;;
	# The FIRST compiler diagnostic, not the last line: make's own
	# "Error 2" is the last line and names nothing a reader can act on.
	*) echo "$S_FAIL"$'\t'"exit $rc: $(first_match "$log" ': (error|fatal error): ')" ;;
	esac
}

# tools/reproducible.py: 0 identical, 1 the bytes differ, 2 the track is
# not configured or the build produced no artifact.
class_repro() {
	local rc=$1 log=$2
	case "$rc" in
	0) echo "$S_PASS"$'\t'"$(last_match "$log" '^reproducible:')" ;;
	1) echo "$S_FAIL"$'\t'"$(last_match "$log" 'NOT reproducible|failed')" ;;
	*) echo "$S_NORUN"$'\t'"exit $rc: $(last_match "$log" '.')" ;;
	esac
}

analyser_step() {  # analyser_step <name> <script> <tool>
	if [ "$fast" -eq 1 ]; then
		skip_step "$1" "--fast"
	elif ! command -v "$3" >/dev/null 2>&1; then
		norun_step "$1" "$3 is not installed"
	else
		run_step "$1" class_analyser "$2"
	fi
}

# ---------------------------------------------------------------------
echo "== due_oscilloscope: container CI =="
echo "repo      : $repo"
echo "commit    : $(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
echo "python    : $(python3 -c 'import sys; print(sys.version.split()[0], sys.executable)')"
echo "logs      : $logs"
if [ "$fast" -eq 1 ]; then
	echo "selection : fast - the elastic steps are dropped"
else
	echo "selection : everything, with a ${fuzz_seconds}s fuzz campaign"
fi
started=$(now)

# --- firmware --------------------------------------------------------
# One preflight, shared by the firmware step and the two reproducibility
# steps, because all three spawn the same compiler. It is here rather
# than in a classifier for the reason class_build gives: an exit code
# cannot tell a build that failed from a toolchain that was never there,
# and those are the two states this script exists to keep apart.
build_blocked=
if ! have_tool arm_toolchain; then
	build_blocked="no arm toolchain; python3 tools/toolchain.py says where it looked"
elif ! have_tool cmake; then
	build_blocked="no cmake; python3 tools/toolchain.py says where it looked"
elif ! python3 tools/toolchain.py --dir arduino_sam_core >/dev/null 2>&1; then
	build_blocked="no Arduino SAM core, so Track A cannot build"
fi

if [ -n "$build_blocked" ]; then
	norun_step "firmware" "$build_blocked"
else
	run_step "firmware" class_build docker/build-firmware.sh
fi

# --- the board-free tier ---------------------------------------------
if have_pytest; then
	run_step "host tier" class_pytest \
	         python3 -m pytest --track=b -m "not board" -q
else
	norun_step "host tier" "no pytest in this interpreter"
fi

# --- the board tier's positive control -------------------------------
# Discovery only. ports.find_all_ports identifies by USB VID/PID and
# opens nothing, which is what makes it safe to ask here; wait=0 is one
# scan rather than the default eight-second wait.
attached=$(python3 -c 'import sys; sys.path.insert(0, "host"); import ports; print(" ".join(str(p) for p in ports.find_all_ports(wait=0) if p))' 2>/dev/null)
if ! have_pytest; then
	norun_step "board absent" "no pytest in this interpreter"
elif [ -n "$attached" ]; then
	skip_step "board absent" "a board is attached ($attached); this control needs a machine with none, and running it would open that port"
else
	run_step "board absent" class_board_absent \
	         python3 -m pytest --track=b -m board --require-board -q
fi

# --- byte reproducibility --------------------------------------------
for track in b a; do
	if [ -n "$build_blocked" ]; then
		norun_step "reproducible-$track" "$build_blocked"
	else
		run_step "reproducible-$track" class_repro \
		         python3 tools/reproducible.py --track "$track"
	fi
done

# --- the analysers ---------------------------------------------------
analyser_step "cppcheck" docker/run-cppcheck.sh cppcheck
analyser_step "clang-tidy" docker/run-clang-tidy.sh clang-tidy

# --- the fuzz campaign -----------------------------------------------
# A fresh corpus per run, so every run starts from the same seeds and two
# runs are comparable; a crash reproducer then survives in the log
# directory rather than in a temporary directory the child deletes on the
# way out.
if [ "$fast" -eq 1 ]; then
	skip_step "fuzz" "--fast"
elif [ "$fuzz_seconds" -eq 0 ]; then
	skip_step "fuzz" "--fuzz 0"
elif ! command -v clang >/dev/null 2>&1; then
	norun_step "fuzz" "clang is not installed"
else
	rm -rf "$logs/fuzz-corpus"
	export DUE_FUZZ_CORPUS="$logs/fuzz-corpus"
	run_step "fuzz" class_fuzz docker/run-fuzz.sh "$fuzz_seconds"
fi

# ---------------------------------------------------------------------
# The summary. Everything above prints as it goes; this is the part a
# reader is entitled to read on its own.
# ---------------------------------------------------------------------
elapsed=$(took "$started" "$(now)")

echo
echo "=================================================================="
echo "== what this run did NOT cover ==================================="
echo "=================================================================="
echo "the board tier    NOT RUN. Nothing here opened a serial port, and"
echo "                  every board test was deselected from the host"
echo "                  tier above. A deselected test scores as a pass in"
echo "                  any harness that greps for failures, so read the"
echo "                  host tier's count as host code and nothing else."
echo "Track C           NOT ANALYSED. apps/rtos_bringup fetches FreeRTOS"
echo "                  at configure time and docker/run.sh runs with"
echo "                  --network none, so neither analyser sees it."
echo "the shared source NOT ANALYSED twice. Both analysers read"
echo "as C++            lib/due_shared/src once, in the Track B pass;"
echo "                  Track A compiles those same files as C++."
echo
echo "=================================================================="
echo "== summary ======================================================="
echo "=================================================================="
printf '%-18s %-13s %7s  %s\n' "step" "state" "seconds" "detail"
n_pass=0; n_find=0; n_fail=0; n_norun=0; n_skip=0
for rec in "${records[@]}"; do
	IFS=$'\t' read -r name state secs detail <<< "$rec"
	printf '%-18s %-13s %7s  %s\n' "$name" "$state" "$secs" "$detail"
	case "$state" in
	"$S_PASS") n_pass=$((n_pass + 1)) ;;
	"$S_FIND") n_find=$((n_find + 1)) ;;
	"$S_FAIL") n_fail=$((n_fail + 1)) ;;
	"$S_NORUN") n_norun=$((n_norun + 1)) ;;
	"$S_SKIP") n_skip=$((n_skip + 1)) ;;
	esac
done
echo
printf 'steps: %d passed, %d with advisory findings, %d failed, %d DID NOT RUN, %d not selected\n' \
	"$n_pass" "$n_find" "$n_fail" "$n_norun" "$n_skip"
printf 'wall time: %s s\n' "$elapsed"
echo

name_states() {  # name_states <state>
	local rec name state secs detail
	for rec in "${records[@]}"; do
		IFS=$'\t' read -r name state secs detail <<< "$rec"
		[ "$state" = "$1" ] && printf '  %-18s %s\n' "$name" "$detail"
	done
}

if [ "$n_norun" -gt 0 ]; then
	echo "VERDICT: INCOMPLETE. $n_norun step(s) DID NOT RUN, so this run does"
	echo "not say the tree is good - it says part of it was not checked."
	name_states "$S_NORUN"
	exit 1
fi

if [ "$n_fail" -gt 0 ]; then
	echo "VERDICT: FAILED. $n_fail gating step(s) failed."
	name_states "$S_FAIL"
	exit 2
fi

if [ "$n_skip" -gt 0 ]; then
	echo "VERDICT: the $n_pass gating step(s) selected all passed, and"
	echo "$n_skip step(s) were NOT SELECTED and are therefore unknown."
	name_states "$S_SKIP"
else
	echo "VERDICT: every step ran and every gating step passed."
fi
if [ "$n_find" -gt 0 ]; then
	echo "$n_find analyser(s) reported findings; advisory, they do not gate."
	name_states "$S_FIND"
fi
exit 0
