#!/bin/bash
# in container: render.sh board svgout   (board-fit SVG of F.Cu F.SilkS Edge F.Courtyard)
cd /work/hardware/afe-proto/whatif/blocks/SCOPE/w
kicad-cli pcb export svg --layers F.Cu,F.SilkS,Edge.Cuts,F.Courtyard --mode-single --exclude-drawing-sheet --fit-page-to-board -o $2 $1 >/dev/null 2>&1
