"""width_options.py BOARD OUTDIR WIDTH...: the top copper of BOARD refilled with thermal reliefs, clearance 0.3 mm and each top minimum width, as crops of the three areas (before the widths: the board as it is). Run in the PCB image
from hardware/afe-proto, with the board in its project directory; scratch copies are written beside it and removed."""
import os, subprocess, sys
sys.path.append('/usr/lib/python3/dist-packages')
import pcbnew
from PIL import Image
board, out = sys.argv[1], sys.argv[2]
widths = [float(w) for w in sys.argv[3:]]
os.makedirs(out, exist_ok=True)
X0, Y1 = 17.0, 57.84
AREAS = {'power': (28.8, 10.8, 8.0, 5.0), 'refcal': (56.5, 13.5, 7.0, 6.0), 'r304': (86.0, 8.0, 8.0, 5.5), 'overview': (67.0, 26.5, 50.0, 31.0)}
def render(path, name):
    svg = os.path.join(out, name + '.svg')
    subprocess.run(['kicad-cli', 'pcb', 'export', 'svg', '--layers', 'F.Cu,Edge.Cuts', '--mode-single', '--exclude-drawing-sheet', '--page-size-mode', '2', '-o', svg, path], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    png = os.path.join(out, name + '.png')
    subprocess.run(['rsvg-convert', '-d', '1016', '-p', '1016', '-b', 'white', '-o', png, svg], check=True)
    os.remove(svg)
    return Image.open(png).convert('RGB')
def crop(im, box, scale=1.0):
    cx, cy, hw, hh = box
    c = im.crop((int((cx - hw - X0) * 40), int((Y1 - cy - hh) * 40), int((cx + hw - X0) * 40), int((Y1 - cy + hh) * 40)))
    return c.resize((int(c.width * scale), int(c.height * scale))) if scale != 1 else c
shots = {}
variants = [('as-is', None)] + [('top-%.1f' % w, w) for w in widths]
for label, w in variants:
    tmp = os.path.join(os.path.dirname(os.path.abspath(board)), '_w.kicad_pcb')
    b = pcbnew.LoadBoard(board)
    if w is not None:
        for z in b.Zones():
            if z.GetIsRuleArea():
                continue
            if z.GetLayer() == pcbnew.F_Cu:
                z.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL); z.SetMinThickness(pcbnew.FromMM(w))
                z.SetThermalReliefGap(pcbnew.FromMM(0.25)); z.SetThermalReliefSpokeWidth(pcbnew.FromMM(0.3))
            else:
                z.SetMinThickness(pcbnew.FromMM(0.5))
            z.SetLocalClearance(pcbnew.FromMM(0.3))
        pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    pcbnew.SaveBoard(tmp, b)
    im = render(tmp, 'w-' + label)
    os.remove(tmp)
    shots[label] = im
for area, box in AREAS.items():
    tiles = [(l, crop(shots[l], box, 0.5 if area == 'overview' else 1.0)) for l, _ in variants]
    w, h = tiles[0][1].size
    sheet = Image.new('RGB', (w * len(tiles) + 12 * (len(tiles) - 1), h), 'white')
    for k, (l, t) in enumerate(tiles):
        sheet.paste(t, (k * (w + 12), 0))
    sheet.save(os.path.join(out, 'width-%s.png' % area))
for l, _ in variants:
    os.remove(os.path.join(out, 'w-%s.png' % l))
print('variants', [l for l, _ in variants])
