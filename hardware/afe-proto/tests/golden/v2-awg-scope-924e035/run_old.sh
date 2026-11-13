#!/bin/bash
# Run ONE of the old v2 simulation studies (frozen at 924e035, tests/fixtures/v2-awg-scope-924e035) inside the PCB image on a
# throw-away COPY of the fixture, and write what it produced into OUTDIR. Called as:
#     docker/pcb/run.sh -m 3G -t 3000 bash hardware/afe-proto/tests/golden/v2-awg-scope-924e035/run_old.sh TOOL OUTDIR
# TOOL: awg     run.py (every case and the guards), table.py        -> results.json awg.cir parts.csv report_table.md stdout.txt
#       scope   run.py one section per process, then report.py      -> results/*.json scope_v2.cir report.md stdout.txt
# The old code finds its op-amp macro at <afe-proto>/whatif/tph2502/models/TPH2501_ngspice.mdl and its behavioural model at
# <afe-proto>/whatif/tph2502/beh/tph2502_beh.lib, and writes beside itself; so the tree is rebuilt under a FIXED path
# (/tmp/v2-old-TOOL/afe-proto: the awg header records the macro's path) from the fixture plus the two models:
#   models/tph2501/TPH2501.mdl (fetch_models.py) through sed 's/ tc1=0.001//' (sha256 256eeb24...)
#   models-open/tph2502-beh/tph2502_beh.lib
set -u
tool=$1
W=${AFE_ROOT:-/work/hardware/afe-proto}      # the repository checkout; the container mounts it at /work
OUT=${2:-$W/tests/golden/v2-awg-scope-924e035}
mkdir -p "$OUT"
R=/tmp/v2-old-$tool/afe-proto
rm -rf "/tmp/v2-old-$tool" && mkdir -p "$R/whatif/tph2502/models" "$R/whatif/tph2502/beh"
cp -r "$W/tests/fixtures/v2-awg-scope-924e035/v2" "$R/"
sed 's/ tc1=0.001//' "$W/models/tph2501/TPH2501.mdl" > "$R/whatif/tph2502/models/TPH2501_ngspice.mdl"
cp "$W/models-open/tph2502-beh/tph2502_beh.lib" "$R/whatif/tph2502/beh/"
echo "macro sha256 $(sha256sum < "$R/whatif/tph2502/models/TPH2501_ngspice.mdl")" >&2
export PYTHONDONTWRITEBYTECODE=1
case $tool in
  awg)
    cd "$R/v2/sim/awg" || exit 2
    python3 -I run.py > "$OUT/stdout.txt" 2>&1; rc=$?
    python3 -I table.py >> "$OUT/stdout.txt" 2>&1
    cp raw/results.json awg.cir parts.csv report_table.md "$OUT/"
    echo "exit=$rc" >> "$OUT/stdout.txt"
    exit $rc ;;
  scope)
    cd "$R/v2/sim/scope" || exit 2
    mkdir -p netlists work       # the old section `netlist` writes into netlists/ without creating it (the repository's copy is gitignored but present)
    : > "$OUT/stdout.txt"; : > "$OUT/timing.txt"; rc=0   # timing.txt varies run to run: it is recorded in STAMP.json, never kept as a golden
    for s in netlist cscan dc ac bw noise d17 tran stab beh prot xtalk static mc guards; do
      /usr/bin/time -a -o "$OUT/timing.txt" -f "$s wall %e s maxrss %M kB" python3 -I run.py $s >> "$OUT/stdout.txt" 2>&1 || { rc=$?; echo "section $s exit $rc" >> "$OUT/stdout.txt"; }
    done
    python3 -I report.py >> "$OUT/stdout.txt" 2>&1 || rc=$?
    mkdir -p "$OUT/results"; cp results/*.json "$OUT/results/"; cp scope_v2.cir report.md "$OUT/"
    echo "exit=$rc" >> "$OUT/stdout.txt"
    exit $rc ;;
  *) echo "unknown tool $tool" >&2; exit 2 ;;
esac
