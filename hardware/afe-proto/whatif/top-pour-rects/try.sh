#!/bin/bash
# try.sh CONFIG BOARD_DIR: rebuild the rectangle pour on the copy in BOARD_DIR (in the PCB image, from hardware/afe-proto) and print the LR-14 pour findings
cfg=$1; d=$2; ref=$3; src=$4
cd hardware/afe-proto
python3 -m pcbtools.fill_clean $d/$src $d/out.kicad_pcb --config $cfg --reference $ref 2>&1 | grep -v "Debug\|Deprec\|warn" | cut -c1-400
N=${N:-14} python3 whatif/top-pour-rects/lr14.py $cfg $d/out.kicad_pcb 2>&1 | grep -v "Debug\|Deprec\|warn"
