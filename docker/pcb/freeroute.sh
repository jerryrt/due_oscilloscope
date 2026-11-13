#!/bin/bash
# Route a Specctra design with Freerouting, headless, inside the PCB image.
#
#     docker/pcb/run.sh -m 2G -t 900 docker/pcb/freeroute.sh IN.dsn OUT.ses [--passes N] [--timeout S] [--threads N]
#
# IN.dsn comes from pcbnew's ExportSpecctraDSN and OUT.ses goes back through ImportSpecctraSES. Exit status:
# Freerouting's own, 124 on --timeout, 2 on bad usage, 3 when the router or Java is not in the image (a missing
# tool is an error, never a quiet success), 4 when it exited 0 but wrote no session.
#
# DETERMINISM. The CLI has no seed. It is made repeatable by what it does offer: one thread (-mt 1, the default
# here), and the fixed 2.5.0 jar. Three runs of a small board gave a byte-identical .ses. --threads N > 1 lets the
# optimiser race and is not reproducible; it is for a run nobody compares.
#
# NO GUI, NO API SERVER, NO TELEMETRY. The GUI and the API server are disabled and java.awt.headless set; usage analytics are disabled (run.sh also
# gives the container no network). The JVM is told to size its heap from the container's cgroup limit, so run.sh's
# --memory is what bounds it; --timeout is enforced here with timeout(1) and run.sh's -t bounds the whole job.
set -uo pipefail

usage() { echo "usage: freeroute.sh IN.dsn OUT.ses [--passes N] [--timeout S] [--threads N]" >&2; exit 2; }
[ $# -ge 2 ] || usage
IN=$1; OUT=$2; shift 2
PASSES=20; LIMIT=0; THREADS=1
while [ $# -gt 0 ]; do
    case $1 in
        --passes)  PASSES=${2:?}; shift 2;;
        --timeout) LIMIT=${2:?}; shift 2;;
        --threads) THREADS=${2:?}; shift 2;;
        *) usage;;
    esac
done
case $PASSES$LIMIT$THREADS in *[!0-9]*) echo "freeroute.sh: --passes, --timeout and --threads take whole numbers" >&2; exit 2;; esac

JAR=${FREEROUTING_JAR:-/opt/freerouting/freerouting.jar}
if ! command -v java >/dev/null 2>&1 || [ ! -r "$JAR" ]; then
    echo "freeroute.sh: Freerouting is not in this image (java or $JAR missing)" >&2
    exit 3
fi
[ -r "$IN" ] || { echo "freeroute.sh: cannot read $IN" >&2; exit 2; }
rm -f "$OUT"

export FREEROUTING__GUI__ENABLED=false
export FREEROUTING__API_SERVER__ENABLED=false
export FREEROUTING__USAGE_AND_DIAGNOSTIC_DATA__DISABLE_ANALYTICS=true
cmd=(java -Djava.awt.headless=true -XX:MaxRAMPercentage=70 -jar "$JAR" -de "$IN" -do "$OUT" -mp "$PASSES" -mt "$THREADS")
if [ "$LIMIT" -gt 0 ]; then
    timeout -k 5 "$LIMIT" "${cmd[@]}"
else
    "${cmd[@]}"
fi
rc=$?
[ $rc -eq 0 ] && [ ! -s "$OUT" ] && { echo "freeroute.sh: exit 0 but $OUT is empty or missing" >&2; rc=4; }
exit $rc
