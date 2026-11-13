#!/bin/bash
# Run a command in the pinned PCB image against this working tree.
#
#     docker/pcb/run.sh [-m MEM] [-t SECONDS] [-c CPUS] command ...
#     docker/pcb/run.sh -m 2G -t 600 pytest -c hardware/afe-proto/tests/pytest.ini hardware/afe-proto
#
# Defaults 2G, 300 s, 2 CPUs. The limits are docker's own: --memory with
# --memory-swap equal to it (swap off), --cpus, and `timeout` inside. At
# most two heavy jobs at once, never a process pool (house rules).
#
# Same exit conventions and one-line summary as hardware/afe-proto/tools/
# capped.sh, so a bench row looks identical either way: 137 when the cap
# kills the job, 124 on timeout, the job's own status otherwise.
#
#   capped: peak_rss_kb=<n> wall_s=<s> exit=<n> cap=<MEM> limit_s=<T> image=<content>
#
# The repository is mounted at /work (read-write: goldens and bench rows are
# written there), --network none, and the container runs as this user.
set -euo pipefail

here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo=$(cd -- "$here/../.." && pwd)
manifest() { python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])' "$here/image-revisions.json" "$1"; }
# THE IMAGE OF RECORD IS A DIGEST, NOT A BUILD. image-revisions.json names the
# registry, the pushed manifest digest, the installed-set hash and the recipe
# hash. By default this pulls that digest (if it is not already here) and refuses
# anything else: a different digest, a recipe that is not the tree's, or an
# installed set that differs. DUE_PCB_IMAGE overrides with an explicit local
# tag (the gate's no-ngspice control, a rebuild for verification) and skips the
# digest checks, and says so in the summary line. DUE_PCB_DIGEST overrides the
# digest, which exists so a test can prove the refusal.
registry=$(manifest registry)
digest=${DUE_PCB_DIGEST:-$(manifest digest)}
pinned=1
if [ -n "${DUE_PCB_IMAGE:-}" ]; then
    image=$DUE_PCB_IMAGE
    pinned=0
else
    image="$registry@$digest"
fi
M=2G; T=300; C=2
while getopts "m:t:c:" o; do
    case $o in m) M=$OPTARG;; t) T=$OPTARG;; c) C=$OPTARG;;
        *) echo "usage: run.sh [-m MEM] [-t SECONDS] [-c CPUS] cmd..." >&2; exit 2;; esac
done
shift $((OPTIND-1))
[ $# -ge 1 ] || { echo "usage: run.sh [-m MEM] [-t SECONDS] [-c CPUS] cmd..." >&2; exit 2; }

if ! docker image inspect "$image" >/dev/null 2>&1; then
    if [ "$pinned" = 1 ]; then
        echo "pulling $image" >&2
        docker pull --quiet "$image" >/dev/null || {
            echo "cannot pull $image (docker login $(echo "$registry" | cut -d/ -f1)?)" >&2; exit 2; }
    else
        echo "no such image: $image" >&2
        echo "build it:  docker/pcb/build-image.sh" >&2
        exit 2
    fi
fi
if [ "$pinned" = 1 ]; then
    # the digest is the identity: the image must really be that manifest
    if ! docker image inspect "$image" --format '{{range .RepoDigests}}{{println .}}{{end}}' | grep -qxF "$image"; then
        echo "image $image is not the pinned digest $digest" >&2
        exit 2
    fi
fi
# The image must be the one this tree's recipe describes, as run.sh of the
# firmware image requires: a stale image would certify inputs the commit no
# longer states. The control image (no ngspice) is exempt by explicit name.
have=$(docker image inspect "$image" --format '{{index .Config.Labels "due.image.recipe"}}')
want=$("$here/image-id.sh" recipe)
if [ "$have" != "$want" ]; then
    echo "image $image was built from a different recipe" >&2
    echo "  image recipe: ${have:-none}" >&2
    echo "  tree recipe:  $want" >&2
    echo "rebuild:  docker/pcb/build-image.sh" >&2
    exit 2
fi
content=$("$here/image-id.sh" content "$image")
installed=$("$here/image-id.sh" installed "$image")
if [ "$pinned" = 1 ] && [ "$installed" != "$(manifest installed)" ]; then
    echo "installed set of $image differs from image-revisions.json" >&2
    echo "  image: $installed" >&2
    echo "  file:  $(manifest installed)" >&2
    exit 2
fi
# What the summary line calls the image: the pinned digest, or UNPINNED:<tag> for an override, so a row taken
# in a local build can never be mistaken for one of record (bench.py refuses to write budgets from one).
ident="UNPINNED:$image"
[ "$pinned" = 1 ] && ident=$digest

# THREAD COUNTS FOLLOW THE CPU QUOTA. numpy/scipy start one BLAS/OpenMP thread per CPU they can SEE (12 here),
# while --cpus is a quota of C CPUs of time, so the threads spin against it: cap.py took 98 s instead of 15.5 s.
# This is the one place the counts are set - floor(--cpus), minimum 1 - so it covers every program in the
# image whatever its import order. tests/test_image_gate.py and tests/pcbtools/test_threads.py hold it.
threads=$(awk -v c="$C" 'BEGIN { t = int(c); if (t < 1) t = 1; print t }')
cidfile="${TMPDIR:-/tmp}/due-pcb-$$-${RANDOM}.cid"
errlog=$(mktemp)
flags=(
    --init --user "$(id -u):$(id -g)"
    --network none
    --memory "$M" --memory-swap "$M" --cpus "$C"
    --volume "$repo:/work" --workdir /work
    --env "DUE_PCB_IMAGE=$image" --env "DUE_PCB_IMAGE_CONTENT=$ident"
    --env "DUE_PCB_IMAGE_INSTALLED=$installed"
    --env "DUE_PCB_MACHINE=${DUE_PCB_MACHINE:-$(hostname)}"
    --env "DUE_PCB_CAP=$M"
    --env "OMP_NUM_THREADS=$threads" --env "OPENBLAS_NUM_THREADS=$threads"
    --env "MKL_NUM_THREADS=$threads" --env "NUMEXPR_NUM_THREADS=$threads"
    --cidfile "$cidfile"
)
# THE COMMITTED FIXTURES AND GOLDENS ARE INPUTS. They are mounted read-only by default, so a write into
# them (bytecode, a .kicad_prl, a lock file) fails at the writing test and names it, instead of poisoning the
# next run; a test that must write copies what it opens. DUE_PCB_RO_FIXTURES=0 is the explicit opt-out, for
# regenerating a golden on purpose (netlib_snapshot.py --write, update_manifest.py). docker/pcb/run-gate.sh
# checks the same directories after every run whether or not the mount is read-only.
if [ "${DUE_PCB_RO_FIXTURES:-1}" = 1 ]; then
    flags+=(--volume "$repo/hardware/afe-proto/tests/fixtures:/work/hardware/afe-proto/tests/fixtures:ro"
            --volume "$repo/hardware/afe-proto/tests/golden:/work/hardware/afe-proto/tests/golden:ro")
fi
# EXTRA MOUNTS, for a test that must put something else where the repository has its own file (an empty models
# directory, to prove a missing vendor model fails the gate). DUE_PCB_EXTRA_VOLUMES is a space-separated list of
# docker --volume specs. Not for ordinary use.
for v in ${DUE_PCB_EXTRA_VOLUMES:-}; do flags+=(--volume "$v"); done
cleanup() {
    if [ -f "$cidfile" ]; then
        cid=$(cat "$cidfile" 2>/dev/null || true)
        [ -n "$cid" ] && docker rm -f "$cid" >/dev/null 2>&1 || true
        rm -f "$cidfile"
    fi
    rm -f "$errlog"
}
trap cleanup EXIT INT TERM HUP

# Not --rm: after an OOM kill the container's State is the only record of why.
status=0
docker run "${flags[@]}" "$image" /work/docker/pcb/capped-inner.sh "$T" "$@" \
    2> >(tee "$errlog" >&2) || status=$?
wait
if ! grep -q '^capped: ' "$errlog"; then
    # The inner script did not get to report: the kernel killed it with the
    # job (cap), or the container never started. Say what is known.
    oom=$(docker inspect "$(cat "$cidfile")" --format '{{.State.OOMKilled}}' 2>/dev/null || echo false)
    [ "$oom" = true ] && status=137
    echo "capped: peak_rss_kb=? wall_s=? exit=$status cap=$M limit_s=$T image=$ident installed=$installed" >&2
fi
exit $status
