"""python3 mockup.py OUT.png   (in the image, cwd hand/): intra-block mock-up for AWG and REFCAL. Top: today's V22 parts coloured by sub-group. Bottom: the proposed sub-group zones (sketch, not fine placement)."""
import sys, json, pcbnew
from PIL import Image, ImageDraw
b = pcbnew.LoadBoard('V22_4.kicad_pcb'); box = {}
for f in b.GetFootprints():
    bb = f.GetBoundingBox(False)
    box[f.GetReference()] = (bb.GetX() / 1e6 - 50, 150 - bb.GetBottom() / 1e6, bb.GetRight() / 1e6 - 50, 150 - bb.GetY() / 1e6)
G = {'AWG op-amp': ((200, 80, 200), ['U301', 'C305', 'C306', 'R306', 'R307']),
     'AWG feedback / half-rail': ((90, 140, 255), ['R303', 'R304', 'C301', 'R305', 'C303', 'C304']),
     'AWG output / back-termination': ((255, 150, 60), ['R301', 'R302', 'R308', 'R309', 'TP301']),
     'VREF source': ((230, 70, 70), ['U501', 'C501', 'C502', 'R514', 'TP501']),
     'tap ladder + connectors': ((70, 200, 120), ['R501', 'R502', 'R503', 'R504', 'R505', 'R506', 'J501', 'J602']),
     'ADS + pull-ups': ((230, 210, 60), ['U502', 'C503', 'R512', 'R513', 'R511']),
     'sense divider': ((60, 200, 220), ['R507', 'R508', 'R509', 'R510'])}
S = 30; X0, Y0, X1, Y1 = 44.0, 0.0, 93.0, 29.0
def px(x, y): return ((x - X0) * S, (Y1 - y) * S)
def panel(title):
    im = Image.new('RGB', (int((X1 - X0) * S), int((Y1 - Y0) * S) + 30), (245, 245, 240)); d = ImageDraw.Draw(im)
    d.text((6, 4), title, fill=(0, 0, 0))
    return im, d
def frame(d, oy):
    for (x0, y0, x1, y1, nm) in ((45.5, 4.6, 65.0, 27.8, 'REFCAL'), (69.5, 4.55, 92.25, 19.25, 'AWG')):
        a = px(x0, y1); c = px(x1, y0); d.rectangle([a[0], a[1] + oy, c[0], c[1] + oy], outline=(0, 0, 0), width=2); d.text((a[0] + 4, a[1] + oy + 2), nm, fill=(0, 0, 0))
    a = px(65.3, 18.4); c = px(69.3, 4.6); d.rectangle([a[0], a[1] + oy, c[0], c[1] + oy], fill=(215, 215, 215), outline=(120, 120, 120)); d.text((a[0] + 2, a[1] + oy + 40), 'A1/A0 wall', fill=(90, 90, 90))
    a = px(50.8 - 1.3, 3.8); c = px(70, 1.2); d.rectangle([a[0], a[1] + oy, c[0], c[1] + oy], fill=(170, 170, 170)); d.text((a[0] + 4, a[1] + oy + 2), 'J602 pins 1..8 (VREF, TAP5..TAP1, A1, A0) / J603 (DAC0)', fill=(0, 0, 0))
    a = px(19.4, 0); 
# top panel: today
im1, d1 = panel('TODAY (V22): parts coloured by sub-group; the same colour should be one cluster')
frame(d1, 30)
for gname, (col, refs) in G.items():
    for r in refs:
        if r in box:
            x0, y0, x1, y1 = box[r]; a = px(x0, y1); c = px(x1, y0); d1.rectangle([a[0], a[1] + 30, c[0], c[1] + 30], fill=col, outline=(0, 0, 0)); d1.text((a[0] + 1, a[1] + 31), r, fill=(0, 0, 0))
# bottom panel: proposed zones
ZONES = [  # name, rect Due mm, parts, why
    ('VREF source', (45.7, 5.0, 52.6, 17.3), 'U501 C501 C502 R514 TP501', 'VREF leaves at the west end of the J602 row (pin 1); Kelvin branches start here'),
    ('tap ladder + connectors', (52.8, 4.9, 64.6, 10.6), 'R506 R505 R504 R503 R502 (one per pin pitch, in pin order)', 'each TAP drops straight to its J602 pin; no TAP crosses another'),
    ('tap ladder + connectors', (55.6, 11.0, 61.0, 15.0), 'J501 R501', 'CAL header sits above the TAP3/TAP4 nodes it taps'),
    ('ADS + pull-ups', (52.8, 16.0, 60.6, 27.5), 'U502 C503 R512 R513 R511', 'SDA/SCL leave north, away from the wall; +3V3A and VREF come from the west'),
    ('sense divider', (61.0, 12.0, 64.8, 27.5), 'R507 R508 R509 R510', 'east edge: AWG_BNC / A0 sense side, one column'),
    ('AWG op-amp', (70.0, 5.0, 77.4, 12.4), 'U301 C305 C306 R306 R307', 'DAC0 (J603) and VNEG/+3V3A arrive from the west and south'),
    ('AWG feedback / half-rail', (70.0, 12.8, 83.0, 19.0), 'R303 R304 C301 R305 C303 C304', 'a row above the op-amp: AWG_FB stays under 5 mm; VREF half-rail pair beside it'),
    ('AWG output / back-termination', (77.8, 5.0, 92.0, 12.4), 'R308 R309 R301 R302 TP301', 'east, towards the BNC; the output run leaves east'),
]
im2, d2 = panel('PROPOSED zones (sketch only, no fine placement; every rule kept)')
frame(d2, 30)
for nm, (x0, y0, x1, y1), parts, why in ZONES:
    col = G[nm][0]; a = px(x0, y1); c = px(x1, y0)
    d2.rectangle([a[0], a[1] + 30, c[0], c[1] + 30], fill=col, outline=(0, 0, 0), width=2)
    d2.text((a[0] + 4, a[1] + 34), nm, fill=(0, 0, 0)); d2.text((a[0] + 4, a[1] + 48), parts[:44], fill=(0, 0, 0)); d2.text((a[0] + 4, a[1] + 62), why[:58], fill=(0, 0, 0))
W, H = im1.size
out = Image.new('RGB', (W, 2 * H), (255, 255, 255)); out.paste(im1, (0, 0)); out.paste(im2, (0, H)); out.save(sys.argv[1])
print(out.size)
