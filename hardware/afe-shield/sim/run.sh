#!/usr/bin/env bash
# Export the SPICE netlist from the schematic and run the Stage A deck.
# Run from anywhere; needs kicad-cli 9 and ngspice on PATH.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
cd "$here"
kicad-cli sch export netlist --format spice -o stage_a.net.raw ../afe-shield.kicad_sch >/dev/null
# The export is a complete deck; strip its title and .end so it includes.
sed -e '/^\.title/d' -e '/^\.end$/d' stage_a.net.raw > stage_a.net
rm -f stage_a.net.raw
ngspice -b stage_a.cir 2>&1 | grep -v -E "^(Note|Warning): (Compat|no compat|Starting|Using|Reference value|Adding|Circuit:|Doing analysis)" | grep -v "^$"
