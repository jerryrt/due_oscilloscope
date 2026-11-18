"""bottom_slivers.py BOARD REPORT.txt OUT_PREFIX: the bottom plane with the fill_quality 'narrow' findings of REPORT (pcbkit_regress/geometry.py) circled, cropped to the Due header columns and
to the south header row, at 40 px/mm. Run in the PCB image from the repository root. The page is BOARD_RECT (17, -4.5, 117, 57.84)."""
import subprocess, sys, os
import numpy as np
from PIL import Image, ImageDraw
board, rep, out = sys.argv[1:4]
X0, Y1 = 17.0, 57.84
svg = out + '.svg'
subprocess.run(['kicad-cli', 'pcb', 'export', 'svg', '--layers', 'B.Cu,Edge.Cuts', '--mode-single', '--exclude-drawing-sheet', '--page-size-mode', '2', '-o', svg, board], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
subprocess.run(['rsvg-convert', '-d', '1016', '-p', '1016', '-b', 'white', '-o', out + '-full.png', svg], check=True)
os.remove(svg)
im = Image.open(out + '-full.png').convert('RGB'); d = ImageDraw.Draw(im)
pts = []
for l in open(rep):
    f = l.split()
    if f and f[0] == 'narrow' and f[3] == 'B':
        pts.append((float(f[1]), float(f[2])))
for x, y in pts:
    cx, cy = (x - X0) * 40, (Y1 - y) * 40
    d.ellipse([cx - 16, cy - 16, cx + 16, cy + 16], outline=(0, 90, 255), width=4)
def crop(x0, y0, x1, y1, name):
    im.crop((int((x0 - X0) * 40), int((Y1 - y1) * 40), int((x1 - X0) * 40), int((Y1 - y0) * 40))).save('%s-%s.png' % (out, name))
crop(88, 8, 100, 30, 'east-header')
crop(27, 0, 64, 6, 'south-row')
crop(27, 48.5, 64, 53, 'north-row')
os.remove(out + '-full.png')
print(len(pts), 'narrow findings circled')
