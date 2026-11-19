# usage: opt.sh cfg dir ref src
cd hardware/afe-proto
python3 -m pcbtools.fill_clean $2/$4 $2/out.kicad_pcb --config $1 --reference $3 2>&1 | grep -E "^[0-9]+ (SMD|GND vias)" | cut -c1-140
N=12 python3 whatif/top-pour-rects/lr14.py $1 $2/out.kicad_pcb 2>&1 | grep -v "Debug\|Deprec\|warn" | cut -c1-230
