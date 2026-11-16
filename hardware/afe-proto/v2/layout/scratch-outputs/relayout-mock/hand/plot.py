"""python3 plot.py X0 Y0 X1 Y1 OUT.png [spec.py ...] [--nets A,B]   pads (all), routes from the specs, in Due mm; 40 px/mm"""
import sys, json
from PIL import Image, ImageDraw
args = sys.argv[1:]
x0, y0, x1, y1 = map(float, args[:4]); out = args[4]; specs = [a for a in args[5:] if not a.startswith('--')]
hl = set()
for a in args[5:]:
    if a.startswith('--nets='): hl = set(a[7:].split(','))
S = 40
W, H = int((x1 - x0) * S), int((y1 - y0) * S)
im = Image.new('RGB', (W, H), (20, 50, 35)); d = ImageDraw.Draw(im)
def px(x, y): return ((x - x0) * S, (y1 - y) * S)
P = json.load(open('/work/hardware/afe-proto/v2/layout/scratch-outputs/relayout-mock/hand/pads.json'))
for p in P:
    bx0, by0, bx1, by1 = p['bb']
    if bx1 < x0 or bx0 > x1 or by1 < y0 or by0 > y1: continue
    a = px(bx0, by1); b = px(bx1, by0)
    col = (230, 80, 80) if p['net'] in hl else (200, 170, 60)
    d.rectangle([a, b], fill=col, outline=(255, 255, 255))
    d.text((a[0] + 1, a[1] + 1), f"{p['ref']}.{p['pin']}", fill=(0, 0, 0))
    d.text((a[0] + 1, a[1] + 11), p['net'][-7:], fill=(0, 0, 90))
for sp in specs:
    ns = {}; exec(open(sp).read(), ns)
    for net, lay, pts, w in ns.get('ROUTES', []):
        col = (90, 160, 255) if lay == 'F' else (255, 120, 255)
        if net in hl: col = (80, 255, 80)
        for (ax, ay), (bx, by) in zip(pts, pts[1:]):
            d.line([px(ax, ay), px(bx, by)], fill=col, width=max(2, int(w * S)))
    for net, x, y in ns.get('VIAS', []):
        c = px(x, y); d.ellipse([c[0] - 12, c[1] - 12, c[0] + 12, c[1] + 12], outline=(255, 255, 255))
im.save(out)
