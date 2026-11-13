#!/bin/bash
# Run ONE of the old v2 schematic tools (frozen at 276a116, tests/fixtures/v2-kicad-276a116) inside the PCB image on a throw-away COPY
# of the fixture, and write its output next to this script. Called as:
#     docker/pcb/run.sh -m 3G -t 300 bash hardware/afe-proto/tests/golden/v2-kicad-276a116/run_old.sh TOOL [OUTDIR]
# TOOL: check       the old check.py, every row and its 24 mutation arms          -> check.raw.txt
#       build_sch   the old build_sch.py into a scratch folder, then sha256 of every file it wrote and of the committed ones
#                                                                              -> build_sch.sha256.txt
# The old tools write into their own folder, which is why they run on a copy, never on the fixture. They import pcbtools.sexpr
# from the tree under test: PCBTOOLS_ROOT says where.
set -u
tool=$1
W=/work/hardware/afe-proto
OUT=${2:-$W/tests/golden/v2-kicad-276a116}
mkdir -p "$OUT"
T=/tmp/v2-old-$tool          # a fixed path, so the output text does not change between runs
rm -rf "$T" && mkdir -p "$T"
cp -r "$W/tests/fixtures/v2-kicad-276a116/kicad" "$W/tests/fixtures/v2-kicad-276a116/sim" "$T/"
cd "$T/kicad" || exit 2
export PYTHONDONTWRITEBYTECODE=1 PCBTOOLS_ROOT=$W
case $tool in
  check)
    python3 -I check.py > "$OUT/check.raw.txt.tmp" 2>&1
    rc=$?
    echo "exit=$rc" >> "$OUT/check.raw.txt.tmp"
    mv "$OUT/check.raw.txt.tmp" "$OUT/check.raw.txt"
    exit $rc ;;
  build_sch)
    mkdir -p "$T/gen"; cp -r lib "$T/gen/"
    python3 -I build_sch.py "$T/gen" > "$T/build.log" 2>&1; rc=$?
    {
      echo "exit=$rc"
      echo "# written by the old build_sch.py (then kicad-cli sch upgrade) / the committed file of the same name"
      for f in afe-v2.kicad_sch afe-v2.kicad_pro sym-lib-table fp-lib-table lib/afe.kicad_sym; do
        printf '%s  generated  %s\n' "$(sha256sum < "$T/gen/$f" | cut -d' ' -f1)" "$f"
        printf '%s  committed  %s\n' "$(sha256sum < "$T/kicad/$f" | cut -d' ' -f1)" "$f"
      done
    } > "$OUT/build_sch.sha256.txt"
    exit $rc ;;
  *) echo "unknown tool $tool" >&2; exit 2 ;;
esac
