#!/bin/bash
# render.sh board.kicad_pcb out.png  (host side for magick; container for kicad-cli). Crop Due x 42..67, y 2..38 at 40 px/mm
D=/home/jerry/EE.Projects/due_oscilloscope_kvm01; R=hardware/afe-proto/whatif/blocks/refcal_router
b=$1; o=$2
cd $D && docker/pcb/run.sh -m 2G -c 2 -t 120 bash -c "cd /work/$R && kicad-cli pcb export svg --mode-single --page-size-mode 2 -l F.Cu,F.SilkS,Edge.Cuts,F.Courtyard -o out/r.svg $b >/dev/null" | tail -1
cd $D/$R && magick -density 1016 -background white out/r.svg -crop 1000x1440+1000+614 +repage $o && identify $o
