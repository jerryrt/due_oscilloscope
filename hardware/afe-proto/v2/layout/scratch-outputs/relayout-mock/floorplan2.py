import os, sys, json
sys.path.insert(0, '/work/hardware/afe-proto/v2/layout')
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import relayout_place as RP
from PIL import Image, ImageDraw, ImageFont
D, P = RP.load('dump_all.json')
G = {r: RP.part_geom(p) for r, p in P.items()}
CUR = {'POWER': [(17.9, 4.6, 43.6, 26.0)], 'REFCAL': [(44.2, 4.6, 64.4, 27.8), (64.6, 18.6, 70.2, 26.0)], 'CH1': [(63.9, 33.0, 93.0, 50.0), (60.4, 34.6, 64.0, 36.8)], 'CH2': [(69.0, 19.75, 93.0, 32.9)], 'AWG': [(70.4, 4.55, 92.3, 19.25)]}
def area(rs): return sum((r[2] - r[0]) * (r[3] - r[1]) for r in rs)
need, used = {}, {}
for r, p in P.items():
    b = RP.block_of(r)
    if not b or r in RP.FIXED: continue
    g = G[r]; c = g['cy']; z = g['zone']
    a = (c[2] - c[0]) * (c[3] - c[1]) + (z[2] - z[0]) * (z[3] - z[1])
    used[b] = used.get(b, 0) + a
rows = {b: (round(area(CUR[b])), round(area(RP.REGIONS[b])), round(used[b]), round(used[b] / 0.55)) for b in CUR}
json.dump(rows, open('block_table.json', 'w'))
print(rows, sum(v[0] for v in rows.values()), sum(v[1] for v in rows.values()), sum(v[2] for v in rows.values()), round(sum(v[3] for v in rows.values())))
COL = {'POWER': (200, 60, 60), 'REFCAL': (40, 120, 200), 'CH1': (40, 150, 80), 'CH2': (210, 120, 0), 'AWG': (130, 70, 170)}
BOARD = (17.0, -4.5, 117.0, 57.84)
S = 14; W = int((BOARD[2] - BOARD[0] + 4) * S); H = int((BOARD[3] - BOARD[1] + 10) * S)
im = Image.new('RGB', (W, H), 'white'); d = ImageDraw.Draw(im)
try: f = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 13)
except Exception: f = ImageFont.load_default()
def Pt(x, y): return ((x - BOARD[0] + 2) * S, (BOARD[3] - y + 4) * S)
def R_(r, **k): d.rectangle([Pt(r[0], r[3]), Pt(r[2], r[1])], **k)
def dash(r, c):
    for x0, y0, x1, y1 in ((r[0], r[1], r[2], r[1]), (r[2], r[1], r[2], r[3]), (r[2], r[3], r[0], r[3]), (r[0], r[3], r[0], r[1])):
        n = int(max(abs(x1 - x0), abs(y1 - y0)) / 0.8)
        for i in range(0, n, 2):
            a = (x0 + (x1 - x0) * i / n, y0 + (y1 - y0) * i / n); b = (x0 + (x1 - x0) * min(i + 1, n) / n, y0 + (y1 - y0) * min(i + 1, n) / n)
            d.line([Pt(*a), Pt(*b)], fill=c, width=2)
R_(BOARD, outline='black', width=3, fill=(246, 246, 240))
R_((17, -4.5, 117, 0), fill=(235, 225, 205)); R_((17, 53.34, 117, 57.84), fill=(235, 225, 205))
d.text(Pt(18, -1.5), 'analog edge band (top keep-out)', fill='gray', font=f); d.text(Pt(18, 56.6), 'far edge band', fill='gray', font=f)
R_((92.16, 5.8, 98.33, 52.6), fill=(220, 220, 220), outline='gray'); R_((98.5, 0.75, 116.4, 50), fill=(232, 232, 232), outline='gray')
d.text(Pt(101, 40), 'BNC area', fill='gray', font=f)
R_((16.98, 48.98, 43.47, 52.61), fill=(215, 215, 215), outline='gray'); R_((43.91, 48.98, 88.18, 52.61), fill=(215, 215, 215), outline='gray')
R_((26.12, 0.72, 93.25, 4.35), fill=(215, 215, 215), outline='gray')
R_((17.0, 37.3, 33.5, 47.5), fill=(250, 245, 200), outline=(180, 160, 0)); d.text(Pt(18, 44), 'identity (COPPIA, S/N)', fill=(120, 100, 0), font=f)
for b, rs in RP.REGIONS.items():
    for r in rs: R_(r, fill=tuple(int(0.35 * c + 0.65 * 255) for c in COL[b]), outline=COL[b], width=2)
for b, rs in CUR.items():
    for r in rs: dash(r, (60, 60, 60))
for (r, c) in zip(RP.LANES, range(2)): R_(r, outline=(120, 120, 120)); 
d.text(Pt(60.2, 12), 'lanes A1/A0', fill=(90, 90, 90), font=f)
lab = {'POWER': 'POWER', 'REFCAL': 'REF / CAL', 'CH1': 'CH1', 'CH2': 'CH2', 'AWG': 'AWG'}
pos = {'POWER': (30, 17), 'REFCAL': (51.3, 19), 'CH1': (77, 42), 'CH2': (81, 26.3), 'AWG': (80, 11)}
for b, (cx, cy) in pos.items():
    cur, new, u, nd = rows[b]
    for i, t in enumerate((lab[b], 'now %d -> final %d mm2' % (cur, new), 'needed %d (at 55%%), used %d' % (nd, u))):
        x, y = Pt(cx, cy); d.text((x - len(t) * 3.4, y - 22 + i * 16), t, fill=(0, 0, 0), font=f)
d.text((10, 6), 'AFE-2 phase 1 floor plan, Due mm: final blocks (filled) against the old ones (dashed). Board 100 x 62.34 mm.', fill='black', font=f)
tc = sum(v[0] for v in rows.values()); tn = sum(v[1] for v in rows.values()); nd = sum(v[3] for v in rows.values())
d.text((10, H - 18), 'sum of blocks: now %d  final %d  needed %d | interior (x 17.9-92.3, y 4.55-48.98) 3305 mm2' % (tc, tn, nd), fill='black', font=f)
im.save('floorplan_final.png')
