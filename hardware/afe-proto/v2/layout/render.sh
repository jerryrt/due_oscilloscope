#!/bin/bash
# render.sh board.kicad_pcb outdir  : F.Cu+silk, B.Cu, 3D top
B=$1; O=$2; mkdir -p $O
export KICAD10_3DMODEL_DIR=/usr/share/kicad/3dmodels
kicad-cli pcb export svg --layers F.Cu,F.Silkscreen,Edge.Cuts --mode-single --exclude-drawing-sheet --page-size-mode 2 -o $O/F.svg $B >/dev/null 2>&1
kicad-cli pcb export svg --layers B.Cu,Edge.Cuts --mode-single --exclude-drawing-sheet --page-size-mode 2 -o $O/B.svg $B >/dev/null 2>&1
magick -density 400 $O/F.svg -background white -flatten $O/afe-v2-integrated-F.Cu-silk.png
magick -density 400 $O/B.svg -background white -flatten $O/afe-v2-integrated-B.Cu.png
kicad-cli pcb render --side top --quality basic --width 2400 --height 1400 -o $O/afe-v2-integrated-3d.png $B >/dev/null 2>&1
kicad-cli pcb render --side bottom --quality basic --width 2400 --height 1400 -o $O/afe-v2-integrated-3d-bottom.png $B >/dev/null 2>&1
rm -f $O/F.svg $O/B.svg
ls -la $O
