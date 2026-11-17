"""python3 mockup2.py OUT.png   (in the image, cwd hand/): v2 intra-block mock-up. Top: today's V22 parts by sub-group. Bottom: proposed zones, the supply strip under the J602/J603 pins, the risers, the AWG_BNC corridor, the VREF north trunk. Sketch only."""
import sys, textwrap, pcbnew
from PIL import Image, ImageDraw, ImageFont
b = pcbnew.LoadBoard('V22_4.kicad_pcb'); box = {}
for f in b.GetFootprints():
    bb = f.GetBoundingBox(False); box[f.GetReference()] = (bb.GetX() / 1e6 - 50, 150 - bb.GetBottom() / 1e6, bb.GetRight() / 1e6 - 50, 150 - bb.GetY() / 1e6)
C = {'op': (200, 80, 200), 'fb': (90, 140, 255), 'out': (255, 150, 60), 'inp': (170, 120, 230), 'ref': (230, 70, 70), 'lad': (70, 200, 120), 'ads': (230, 210, 60), 'sns': (60, 200, 220), 'cal': (130, 220, 160)}
TODAY = {'op': ['U301', 'C305', 'C306'], 'inp': ['R306', 'R307'], 'fb': ['R303', 'R304', 'C301', 'R305', 'C303', 'C304'], 'out': ['R301', 'R302', 'R308', 'R309', 'TP301'],
         'ref': ['U501', 'C501', 'C502', 'R514', 'TP501'], 'lad': ['R501', 'R502', 'R503', 'R504', 'R505', 'R506', 'J602'], 'cal': ['J501'], 'ads': ['U502', 'C503', 'R512', 'R513', 'R511'], 'sns': ['R507', 'R508', 'R509', 'R510']}
S = 22; X0, Y0, X1, Y1 = 44.0, -5.2, 94.0, 50.0
F = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 11); FB = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 12)
def px(x, y): return ((x - X0) * S, (Y1 - y) * S + 24)
def new(title):
    im = Image.new('RGB', (int((X1 - X0) * S), int((Y1 - Y0) * S) + 24), (246, 246, 241)); d = ImageDraw.Draw(im); d.text((6, 4), title, fill=(0, 0, 0), font=FB); return im, d
def rect(d, r, **k):
    a = px(r[0], r[3]); c = px(r[2], r[1]); d.rectangle([a, c], **k)
def ctx(d):
    rect(d, (45.5, 4.6, 65.0, 27.8), outline=(0, 0, 0), width=2); d.text(px(45.8, 27.5), 'REFCAL block', fill=(0, 0, 0), font=F)
    rect(d, (69.5, 4.55, 92.25, 19.25), outline=(0, 0, 0), width=2); d.text(px(69.8, 19.0), 'AWG block', fill=(0, 0, 0), font=F)
    for r, n in (((69.0, 19.75, 92.25, 32.9), 'CH2 (not re-placed)'), ((58.0, 33.0, 92.25, 49.0), 'CH1 (not re-placed)')): rect(d, r, outline=(150, 150, 150), width=1); d.text(px(r[0] + 0.3, r[3] - 0.3), n, fill=(130, 130, 130), font=F)
    rect(d, (65.3, 2.5, 69.3, 35.0), fill=(222, 222, 222), outline=(130, 130, 130)); d.text(px(65.4, 33.6), 'A1/A0 wall', fill=(90, 90, 90), font=F)
    rect(d, (44.0, 0.75, 93.5, 4.3), fill=(200, 200, 200)); d.text(px(70.0, 4.0), '', font=F)
    for x, nm in ((50.8, 'VREF'), (53.34, 'T5'), (55.88, 'T4'), (58.42, 'T3'), (60.96, 'T2'), (63.5, 'T1'), (66.04, 'A1'), (68.58, 'A0')):
        a = px(x, 2.54); d.ellipse([a[0] - 6, a[1] - 6, a[0] + 6, a[1] + 6], fill=(60, 60, 60)); d.text((a[0] - 9, a[1] - 20), nm, fill=(0, 0, 0), font=F)
    a = px(83.82, 2.54); d.ellipse([a[0] - 6, a[1] - 6, a[0] + 6, a[1] + 6], fill=(60, 60, 60)); d.text((a[0] - 14, a[1] - 20), 'DAC0', fill=(0, 0, 0), font=F)
    d.text(px(44.5, 1.5), 'J601 / J602 (pins 1-8: VREF T5 T4 T3 T2 T1 A1 A0) / J603 sockets', fill=(0, 0, 0), font=F)
    rect(d, (44.0, -4.55, 94.0, 0.75), outline=(180, 80, 80), width=1); d.text(px(44.3, -4.3), 'board edge at y -4.55', fill=(180, 80, 80), font=F)
im1, d1 = new('TODAY (V22): parts by sub-group (same colour = one cluster)'); ctx(d1)
for g, refs in TODAY.items():
    for r in refs:
        if r in box and r != 'J602':
            rect(d1, box[r], fill=C[g], outline=(0, 0, 0)); d1.text(px(box[r][0] + 0.1, box[r][3] - 0.1), r, fill=(0, 0, 0), font=F)
im2, d2 = new('PROPOSED v2 (sketch, not fine placement): sub-group zones, supply strip, risers, corridors'); ctx(d2)
Z = [('ref', (45.7, 8.8, 53.0, 17.0), 'VREF SOURCE: U501 C501 C502 R514 TP501. VREF leaves at J602 pin 1; Kelvin branches start here'),
     ('lad', (50.5, 5.0, 65.0, 8.4), 'TAP LADDER, vertical resistors one per pin pitch: R506 R505 R504 R503 R502 R501 (R501 = GND end, east). TAPk drops to its pin'),
     ('cal', (54.6, 9.0, 64.0, 12.8), 'CAL header J501 over the TAP3 / TAP4 nodes it taps'),
     ('ads', (53.4, 13.8, 60.7, 27.5), 'ADS: U502 C503 R512 R513 R511. SDA/SCL leave north'),
     ('sns', (61.9, 13.8, 64.8, 27.5), 'SENSE R509 R508 R507 R510'),
     ('op', (71.9, 5.2, 80.4, 13.8), 'OP-AMP: U301 C305 C306 R308 R309 (1R at OA/OB pins)'),
     ('inp', (80.6, 4.7, 86.4, 7.0), 'INPUT R306 R307 over DAC0'),
     ('fb', (80.6, 7.2, 86.4, 13.8), 'FEEDBACK / HALF-RAIL, east of U301: R303 R304 C301 R305 C303 C304. AWG_FB tee at U301 pins 2/6 (INV_MAX 5.0)'),
     ('out', (86.7, 5.2, 92.0, 17.5), 'OUTPUT: R301 R302 TP301 at the BNC side')]
for g, r, t in Z:
    rect(d2, r, fill=C[g], outline=(0, 0, 0), width=2)
    a = px(r[0], r[3]); wch = max(8, int((r[2] - r[0]) * S / 6.4))
    for i, ln in enumerate(textwrap.wrap(t, wch)[:12]): d2.text((a[0] + 3, a[1] + 3 + 13 * i), ln, fill=(0, 0, 0), font=F)
def line(d, pts, col, w=3): d.line([px(*p) for p in pts], fill=col, width=w)
for y, col, nm in ((0.9, (210, 40, 40), 'VREF'), (0.1, (200, 140, 0), '+3V3A'), (-0.7, (140, 60, 200), 'VNEG')):
    line(d2, [(44.5, y), ({'VREF': 70.0, '+3V3A': 70.7, 'VNEG': 71.4}[nm], y), ({'VREF': 70.0, '+3V3A': 70.7, 'VNEG': 71.4}[nm], 5.6)], col, 3)
    d2.text(px(45.0, y + 0.05), nm + ' lane', fill=col, font=F)
d2.text(px(47.0, -2.5), 'SUPPLY STRIP: VREF inner (nearest the pins), +3V3A middle, VNEG outer. From the POWER star at the west; no net crossed (A1/A0 leave north)', fill=(0, 0, 0), font=F)
line(d2, [(65.0, 18.6), (88.0, 18.6)], (0, 150, 190), 3); d2.text(px(70.5, 18.45), 'AWG_BNC corridor (one bridge over the A1/A0 lane)', fill=(0, 100, 140), font=F)
line(d2, [(61.5, 14.0), (61.5, 47.0), (76.0, 47.0)], (210, 40, 40), 2); d2.text(px(62.0, 30.0), 'VREF north trunk (branch 5)', fill=(210, 40, 40), font=F)
line(d2, [(70.7, 13.9), (70.7, 33.0)], (200, 140, 0), 2); d2.text(px(71.0, 28.0), '+3V3A to scope: west edge of CH2, 2 bridges over A0 / A1 laterals', fill=(150, 100, 0), font=F)
W, H = im1.size; out = Image.new('RGB', (W, 2 * H), (255, 255, 255)); out.paste(im1, (0, 0)); out.paste(im2, (0, H)); out.save(sys.argv[1]); print(out.size)
