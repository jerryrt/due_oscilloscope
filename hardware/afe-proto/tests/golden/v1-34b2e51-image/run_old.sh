#!/bin/bash
# Run ONE of the old v1 tools (frozen at 34b2e51) inside the PCB image, on a throw-away COPY of the fixture, and write its
# output next to this script. Called as:   docker/pcb/run.sh -m 3G -t 300 bash $G/run_old.sh TOOL
# TOOL: build_pcb | check_pcb | lr_check | lr_check_mutate | fence_check
# The old tools write into their own folder (schematic, board, library): that is why they run on a copy, never on the fixture.
set -u
tool=$1
W=/work/hardware/afe-proto
OUT=${2:-$W/tests/golden/v1-34b2e51-image}
mkdir -p "$OUT"
T=/tmp/v1-old-$tool          # a fixed path, so the output text does not change between runs
rm -rf "$T" && mkdir -p "$T"
cp -r "$W/tests/fixtures/v1-34b2e51/kicad" "$W/tests/fixtures/v1-34b2e51/whatif" "$T/"
cd "$T/kicad" || exit 2
export PYTHONDONTWRITEBYTECODE=1
case $tool in
  build_pcb)       python3 -I build_pcb.py ;;
  check_pcb)       python3 -I check.py --pcb ;;
  lr_check)        python3 -I lr_check.py ;;
  lr_check_mutate) python3 -I lr_check.py --mutate ;;
  fence_check)     python3 -I fence_check.py POWER afe-proto.kicad_pcb afe-proto.kicad_pcb ;;
  *) echo "unknown tool $tool" >&2; exit 2 ;;
esac > "$OUT/$tool.raw" 2>&1
rc=$?
# wxWidgets prints timestamped 'Debug: Adding duplicate image handler' lines when pcbnew loads: noise that changes every run
grep -v ': Debug: Adding duplicate image handler' "$OUT/$tool.raw" > "$OUT/$tool.out"
rm -f "$OUT/$tool.raw"
echo "exit=$rc" >> "$OUT/$tool.out"
exit $rc
