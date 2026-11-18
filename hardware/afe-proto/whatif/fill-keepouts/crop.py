"""crop.py BOARD OUT X0 Y0 X1 Y1 [PXMM]: F.Cu + F.Fab of a board region (Due mm, y up) at PXMM pixels per mm (default 100). Run in the PCB image from the repository root."""
import os, subprocess, sys
from PIL import Image
Image.MAX_IMAGE_PIXELS = None
board, out, x0, y0, x1, y1 = sys.argv[1], sys.argv[2], *map(float, sys.argv[3:7])
k = float(sys.argv[7]) if len(sys.argv) > 7 else 100.0
X0, Y1 = 17.0, 57.84
svg = out + '.svg'
env = dict(os.environ, KICAD10_3DMODEL_DIR='/usr/share/kicad/3dmodels')
subprocess.run(['kicad-cli', 'pcb', 'export', 'svg', '--layers', 'F.Cu,F.Fab,Edge.Cuts', '--mode-single', '--exclude-drawing-sheet', '--page-size-mode', '2', '-o', svg, board], check=True, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
dpi = k * 25.4
png = out + '.full.png'
subprocess.run(['rsvg-convert', '-d', str(dpi), '-p', str(dpi), '-b', 'white', '-o', png, svg], check=True)
im = Image.open(png)
im.crop((int((x0 - X0) * k), int((Y1 - y1) * k), int((x1 - X0) * k), int((Y1 - y0) * k))).save(out)
os.remove(svg); os.remove(png)
