import sys, re, json
sys.path.insert(0, '.'); sys.path.insert(0, 'kicad/labels'); sys.path.append('/usr/lib/python3/dist-packages')
import numpy as np
from pcbtools import boardio
from pcbtools.boards import v1 as C
import regions as RG
from PIL import Image, ImageDraw
b = boardio.read_board('kicad/main_ref.kicad_pcb'); refs = list(b.fp_ref)
def blk(r):
    m = re.fullmatch(r'[A-Z]+(\d)\d\d', r)
    return {'1': 'CH1', '2': 'CH2', '3': 'AWG', '4': 'POWER', '5': 'REFCAL'}.get(m.group(1)) if m else None
BNC = {'J101': 'CH1', 'J201': 'CH2', 'J301': 'AWG'}
BNCEND = {'AWG': (98.5, -0.5, 116.4, 17.4), 'CH2': (98.5, 17.9, 116.4, 36.3), 'CH1': (98.5, 36.8, 116.4, 54.1)}
cour = {r: (float(b.fp_cx0[i]), float(b.fp_cy0[i]), float(b.fp_cx1[i]), float(b.fp_cy1[i])) for i, r in enumerate(refs) if not np.isnan(b.fp_cx0[i])}
members = {B: [] for B in ('CH1', 'CH2', 'AWG', 'POWER', 'REFCAL')}
for r, c in cour.items():
    B = blk(r)
    if B and r not in BNC: members[B].append(c)
for B, e in BNCEND.items(): members[B].append(e)
GROW = 0.3
obst = {}
for B in members:
    o = []
    for r, c in cour.items():
        if r in BNC: continue
        if blk(r) != B and not r.startswith('MH') or r.startswith('MH'): o.append(c)
    for B2, e in BNCEND.items():
        if B2 != B: o.append(e)
    obst[B] = [(c[0] - GROW, c[1] - GROW, c[2] + GROW, c[3] + GROW) for c in o]
# outside the board's Due rectangle (bands) and the pin-label bands are obstacles, except the BNC ends
for B in members:
    obst[B] += [(16.0, -2.0, 118.0, 0.2), (16.0, 53.1, 118.0, 56.0), (16.0, -2.0, 17.3, 56.0), (116.7, -2.0, 118.0, 56.0)]
    if B in BNCEND: pass
R = RG.make_regions(members, obst, halo=float(sys.argv[1]) if len(sys.argv) > 1 else 1.2)
col = {'CH1': (80, 120, 220), 'CH2': (60, 180, 200), 'AWG': (160, 90, 200), 'POWER': (230, 140, 50), 'REFCAL': (60, 190, 120)}
S = 14; im = Image.new('RGB', (int((RG.X1 - RG.X0) * S), int((RG.Y1 - RG.Y0) * S)), 'white'); d = ImageDraw.Draw(im)
P = lambda x, y: ((x - RG.X0) * S, (RG.Y1 - y) * S)
for B, m in R.items():
    for (x0, y0, x1, y1) in RG.boundary_segments(m): d.line([P(x0, y0), P(x1, y1)], fill=col[B], width=3)
for r, c in cour.items():
    (a, e), (f, g) = P(c[0], c[3]), P(c[2], c[1]); d.rectangle([a, e, f, g], outline=(150, 150, 150))
    d.text((a + 2, e + 2), r, fill=(0, 0, 0))
im.save('kicad/labels/regions.png')
for B, m in R.items():
    lab = __import__('scipy.ndimage', fromlist=['x']).label(m)[1]; print(B, 'cells', int(m.sum()), 'components', lab)
# parts of the block outside / foreign parts inside
for B, m in R.items():
    out = [r for r, c in cour.items() if blk(r) == B and r not in BNC and not m[RG.ci((c[0] + c[2]) / 2), RG.cj((c[1] + c[3]) / 2)]]
    fin = [r for r, c in cour.items() if blk(r) != B and r not in BNC and m[RG.ci((c[0] + c[2]) / 2), RG.cj((c[1] + c[3]) / 2)]]
    print(B, 'members outside', out, 'foreign inside', fin)
