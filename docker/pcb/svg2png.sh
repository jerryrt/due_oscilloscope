#!/bin/bash
# svg2png.sh IN.svg OUT.png [--dpi N] [--crop WxH+X+Y] [--background COLOUR]
# Rasterise a kicad-cli SVG inside the image (rsvg-convert) and optionally crop it (Pillow), replacing ImageMagick's
# `magick -density N in.svg -crop WxH+X+Y +repage out.png`. The crop is in output pixels, as magick's is.
# Run it in the container:  docker/pcb/run.sh docker/pcb/svg2png.sh in.svg out.png --dpi 1016 --crop 1000x1440+1000+614
set -euo pipefail
[ $# -ge 2 ] || { echo "usage: svg2png.sh IN.svg OUT.png [--dpi N] [--crop WxH+X+Y] [--background COLOUR]" >&2; exit 2; }
in=$1; out=$2; shift 2
dpi=96; crop=""; bg=white
while [ $# -gt 0 ]; do
    case $1 in
        --dpi) dpi=$2; shift 2 ;;
        --crop) crop=$2; shift 2 ;;
        --background) bg=$2; shift 2 ;;
        *) echo "svg2png.sh: unknown argument $1" >&2; exit 2 ;;
    esac
done
command -v rsvg-convert >/dev/null || { echo "svg2png.sh: rsvg-convert missing (the PCB image, r5 or later, carries it)" >&2; exit 3; }
rsvg-convert -d "$dpi" -p "$dpi" -b "$bg" -o "$out" "$in"
if [ -n "$crop" ]; then
    python3 - "$out" "$crop" <<'PY'
import re, sys
from PIL import Image
m = re.fullmatch(r"(\d+)x(\d+)\+(\d+)\+(\d+)", sys.argv[2])
if not m:
    sys.exit(f"svg2png.sh: bad --crop {sys.argv[2]!r}, want WxH+X+Y")
w, h, x, y = map(int, m.groups())
im = Image.open(sys.argv[1])
if x + w > im.width or y + h > im.height:
    sys.exit(f"svg2png.sh: crop {w}x{h}+{x}+{y} lies outside the {im.width}x{im.height} image")
im.crop((x, y, x + w, y + h)).save(sys.argv[1])
PY
fi
python3 -c 'import sys; from PIL import Image; im=Image.open(sys.argv[1]); print(f"{sys.argv[1]} {im.width}x{im.height}")' "$out"
