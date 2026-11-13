#!/bin/bash
# THE GATE OF RECORD for the AFE PCB and simulation tools. Runs inside the
# image, from the repository root:
#
#     docker/pcb/run.sh -m 3G -t 900 docker/pcb/run-gate.sh
#
# All three tiers - numpy, ngspice, pcbnew - in one pytest run with
# --require-tool=pcbnew,ngspice, so a missing tool is a failure and nothing
# can skip into a pass. The only skips left are the `jobcap` tests, whose
# per-job cap does not exist in the container (docker's cap is the whole
# container's) and which test_image_gate.py checks from the host instead;
# they are counted and named, never hidden.
#
# An exit code of 0 with no tests collected is NOT a pass: pytest exits 5
# for that and so does this script.
#
# THE FIXTURES AND GOLDENS ARE NOT WRITTEN BY A RUN, and that is checked twice. run.sh mounts them
# read-only, so a write fails at the writing test; and this script snapshots them (path, size, sha256)
# before and after and fails the gate, naming the files, if anything differs - which also catches a run
# where the mount is not read-only (a bench using the gate outside run.sh). Bytecode, a .kicad_prl and a
# lock file have each poisoned the next run once; this guards the class.
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 2
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
    open("/tmp/gate-guard.txt", "w").write("\n".join(f"{h} {p}" for p, h in sorted(snap.items())))
    print(f"gate guard: {len(snap)} fixture/golden files recorded", file=sys.stderr)
    sys.exit(0 if snap else 2)          # a guard that looked at nothing is not a guard
before = dict(l.split(" ", 1)[::-1] for l in open("/tmp/gate-guard.txt").read().splitlines())
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
python3 -m pytest -p no:cacheprovider -c hardware/afe-proto/tests/pytest.ini hardware/afe-proto/tests \
    --require-tool=pcbnew,ngspice -q "$@"
rc=$?
guard check
g=$?
if [ "$g" -ne 0 ]; then exit "$g"; fi
exit $rc
