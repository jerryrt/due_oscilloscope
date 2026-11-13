#!/bin/bash
# host: png.sh board.kicad_pcb x0 y0 x1 y1 out.png [px/mm]
cd /home/jerry/EE.Projects/due_oscilloscope_kvm01/hardware/afe-proto/whatif/blocks/SCOPE/w
S=${7:-40}
b=$(realpath $1); rel=${b#/home/jerry/EE.Projects/due_oscilloscope_kvm01}
./run.sh render.sh /work$rel /work/hardware/afe-proto/whatif/blocks/SCOPE/w/tmp.svg >/dev/null 2>&1
x0=$(python3 -c "print(int(($2-17)*$S))"); w=$(python3 -c "print(int(($4-$2)*$S))")
y0=$(python3 -c "print(int((53.34-$5)*$S))"); h=$(python3 -c "print(int(($5-$3)*$S))")
magick -density $(python3 -c "print($S*25.4)") tmp.svg -background white -flatten -crop ${w}x${h}+${x0}+${y0} +repage $6
