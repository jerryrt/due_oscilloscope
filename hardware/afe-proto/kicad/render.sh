#!/bin/bash
# render.sh board.kicad_pcb outdir : v1-top.png (F.Cu + silk), v1-bottom.png (B.Cu), v1-3d.png and v1-3d-bottom.png, and one crop of the top silk per
# overhang band (the Due's pin names). Run in the PCB image (r5 or later), on a COPY of the board with its project beside it (kicad-cli rewrites a project):
#   docker/pcb/run.sh -m 3G -t 900 -c 2 bash hardware/afe-proto/kicad/render.sh <board> <outdir>
here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
svg2png=$here/../../../docker/pcb/svg2png.sh
B=$1; O=$2; mkdir -p "$O"
export KICAD10_3DMODEL_DIR=/usr/share/kicad/3dmodels
kicad-cli pcb export svg --layers F.Cu,F.Silkscreen,Edge.Cuts --mode-single --exclude-drawing-sheet --page-size-mode 2 -o "$O/F.svg" "$B" >/dev/null 2>&1
kicad-cli pcb export svg --layers B.Cu,B.Silkscreen,Edge.Cuts --mode-single --exclude-drawing-sheet --page-size-mode 2 -o "$O/B.svg" "$B" >/dev/null 2>&1
$svg2png "$O/F.svg" "$O/v1-top.png" --dpi 400
$svg2png "$O/B.svg" "$O/v1-bottom.png" --dpi 400
kicad-cli pcb render --side top --quality basic --width 2400 --height 1400 -o "$O/v1-3d.png" "$B" >/dev/null 2>&1
kicad-cli pcb render --side bottom --quality basic --width 2400 --height 1400 -o "$O/v1-3d-bottom.png" "$B" >/dev/null 2>&1
# one crop of the top silk per overhang band, 40 px/mm: the band and the strip to the sockets' pads, full width. Geometry from the board config
# (the page is the board rectangle, y down from its north edge).
dpi=1016
afe=$(cd -- "$here/.." && pwd)
PYTHONPATH=$afe python3 - "$dpi" <<'PY' | while read -r name geom; do $svg2png "$O/F.svg" "$O/v1-$name.png" --dpi $dpi --crop "$geom"; done
import sys
from pcbtools.boards import v1 as L
dpi = float(sys.argv[1]); k = dpi / 25.4
x0, y0, x1, y1 = L.BOARD_RECT
strip = L.PIN_PAD_EDGE + 0.2                             # mm from the band's inner edge to just past the socket pads: where a label may reach
for (n, (bx0, by0, bx1, by1)), tag in zip(L.KEEPOUTS, ('band-south', 'band-north')):
    south = by0 < 1.0
    top, bot = (by1 + strip, by0) if south else (by1, by0 - strip)          # Due mm, y up
    H, off = int((y1 - y0) * k), int((y1 - top) * k)
    print(tag, '%dx%d+0+%d' % (int((x1 - x0) * k), min(int((top - bot) * k), H - off), off))
PY
rm -f "$O/F.svg" "$O/B.svg"
ls -la "$O"
