#!/bin/bash
# the 3D top render of render.sh at 2x (4800 x 2800), same command otherwise: r3d.sh board out.png
export KICAD10_3DMODEL_DIR=/usr/share/kicad/3dmodels
kicad-cli pcb render --side top --quality basic --width 4800 --height 2800 -o "$2" "$1" >/dev/null 2>&1
ls -la "$2"
