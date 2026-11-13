#!/bin/bash
# THE GATE OF RECORD for the AFE PCB and simulation tools. Runs inside the
# image, from the repository root:
#
#     docker/pcb/run.sh -m 4G -t 3000 docker/pcb/run-gate.sh
#
# All three tiers - numpy, ngspice, pcbnew - in one pytest run with
# --require-tool=pcbnew,ngspice,freerouting,networkx,vendor, so a missing tool is a failure and nothing
# can skip into a pass. The only skips left are the `jobcap` tests, whose
# per-job cap does not exist in the container (docker's cap is the whole
# container's) and which test_image_gate.py checks from the host instead;
# they are counted and named, never hidden.
#
# An exit code of 0 with no tests collected is NOT a pass: pytest exits 5
# for that and so does this script.
#
# THE FIXTURES AND GOLDENS ARE NOT WRITTEN BY A RUN, and that is checked twice. run.sh mounts them
# read-only by default, so a write fails at the writing test; and this script snapshots them (path, size, sha256)
# before and after and fails the gate, naming the files, if anything differs - which also catches a run
# where the mount is not read-only (a bench using the gate outside run.sh). Bytecode, a .kicad_prl and a
# lock file have each poisoned the next run once; this guards the class.
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 2
GUARD_FILE=$(mktemp /tmp/gate-guard.XXXXXX) || exit 2
trap 'rm -f "$GUARD_FILE"' EXIT
export GUARD_FILE
guard() {
    python3 - "$@" <<'PY'
import hashlib, os, sys
roots = ["hardware/afe-proto/tests/fixtures", "hardware/afe-proto/tests/golden"]
snap = {}
for r in roots:
    for d, _, fs in os.walk(r):
        for f in fs:
            p = os.path.join(d, f)
            snap[p] = hashlib.sha256(open(p, "rb").read()).hexdigest() if os.path.isfile(p) else "?"
if sys.argv[1] == "save":
    junk = sorted(p for p in snap if p.endswith((".kicad_prl", ".pyc")) or "/~" in p or p.endswith(".lck"))
    if junk:
        print("gate guard: the fixtures/goldens already hold leftovers of an earlier run (delete them):", file=sys.stderr)
        for p in junk:
            print(f"  leftover: {p}", file=sys.stderr)
        sys.exit(4)
    open(os.environ["GUARD_FILE"], "w").write("\n".join(f"{h} {p}" for p, h in sorted(snap.items())))
    print(f"gate guard: {len(snap)} fixture/golden files recorded", file=sys.stderr)
    sys.exit(0 if snap else 2)          # a guard that looked at nothing is not a guard
before = dict(l.split(" ", 1)[::-1] for l in open(os.environ["GUARD_FILE"]).read().splitlines())
new = sorted(set(snap) - set(before)); gone = sorted(set(before) - set(snap))
changed = sorted(p for p in snap if p in before and snap[p] != before[p])
if new or gone or changed:
    print("gate guard: the run changed the fixtures/goldens:", file=sys.stderr)
    for tag, xs in (("new", new), ("gone", gone), ("changed", changed)):
        for x in xs:
            print(f"  {tag}: {x}", file=sys.stderr)
    sys.exit(3)
print("gate guard: fixtures and goldens unchanged", file=sys.stderr)
PY
}
guard save || exit $?
PYTEST_ARGS=("$@")
# ONE PYTEST PROCESS PER GROUP. pcbnew boards loaded by the tests are never given back (collecting and malloc_trim were tried
# and returned nothing), so in a single process the pytest process alone grew to 1.3 GB, and on top of that a kicad-cli child
# needs about 1.3 GB for ERC or DRC: the gate peaked at the whole 3G cap. Measured per file with --memlog
# (python3 -m pytest ... --memlog): test_editor ends at 755 MB, test_merge 345, test_boardio 245, test_rules_live 237, test_build 231,
# test_v1_rules 222. The groups below keep each process under about 900 MB; the last session takes every test file NOT named
# here, so a new test file is never dropped. Each session also runs tests/pcbtools/test_guard.py, which checks that session's
# pcbnew group, and the sessions run one after another.
T=hardware/afe-proto/tests
GROUPS_=("$T/pcbtools/test_editor.py"
         "$T/pcbtools/test_merge.py $T/pcbtools/test_build.py $T/pcbtools/test_boardio.py"
         "$T/pcbtools/test_v1_rules.py $T/pcbtools/test_rules_live.py $T/pcbtools/test_rules_equivalence.py $T/pcbtools/test_rules_review.py $T/pcbtools/test_rules_synthetic.py")
rc=0; ran=0; ignore=()
run_session() {
    python3 -m pytest -p no:cacheprovider -c $T/pytest.ini "$@" \
        --require-tool=pcbnew,ngspice,freerouting,networkx,vendor -q
    local r=$?
    if [ "$r" -eq 5 ]; then return 0; fi          # a group emptied by a -m / -k selection
    ran=$((ran + 1))
    if [ "$r" -ne 0 ] && [ "$rc" -eq 0 ]; then rc=$r; fi
}
for g in "${GROUPS_[@]}"; do
    # shellcheck disable=SC2086
    run_session $g $T/pcbtools/test_guard.py "${PYTEST_ARGS[@]}"
    for f in $g; do ignore+=(--ignore="$f"); done
done
run_session $T "${ignore[@]}" "${PYTEST_ARGS[@]}"
if [ "$ran" -eq 0 ]; then rc=5; fi
guard check
g=$?
if [ "$g" -ne 0 ]; then exit "$g"; fi
exit $rc
