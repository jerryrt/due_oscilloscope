"""AFE version 1 floorplan and interface contract: ONE data set that draws floorplan.svg/.png and writes floorplan.md's table.

Due coordinates (mm), x right, y up, origin the Due's lower-left corner; the shield outline is x 17..117, y 0..53.34.
Nothing here is routed.  Run: python3 floorplan.py  (needs ImageMagick `magick` for the PNG).
Edge points are first-cut choices for review; pass-2's routes are the reference where one existed.
"""
import subprocess
import pathlib

HERE = pathlib.Path(__file__).parent
X0, X1, Y0, Y1 = 17.0, 117.0, 0.0, 53.34

# block -> list of fence rectangles (x0, y0, x1, y1); a block agent places and routes only inside its fences
FENCES = {
    'POWER': [(18.0, 4.6, 44.0, 22.0)],
    'REFCAL': [(44.5, 4.6, 64.5, 36.0)],
    'SCOPE': [(64.8, 33.5, 97.8, 50.3), (69.4, 19.9, 97.8, 33.0), (98.5, 16.5, 116.4, 50.0)],
    'AWG': [(69.8, 4.4, 95.5, 19.4), (98.5, 0.6, 116.4, 15.5)],
}
# corridors: copper owned by a block that runs outside its fence
CORRIDORS = {
    'WALL (SCOPE: A1 x 66.04, A0 x 68.58, y 2.54..38; the four wall bridges)': (64.8, 2.0, 69.4, 33.5),
    'STRIP lanes under the ADC/PWM pad rows (POWER, REFCAL: y 0.55 VNEG outermost, 0.95 +3V3A, 1.35 VREF branch C innermost; 0.2 wide, 0.2 gap; pad edge 1.69, lane top 1.45)': (44.0, 0.45, 78.0, 1.45),
    'AWG riser (x 71.33: the three strip lanes turn north to U3 and the offset filter)': (70.8, 1.0, 71.9, 12.0),
    'SCOPE +3V3A riser (x 69.6, y 1.0 to 19.9, between the wall and the AWG fence)': (69.4, 1.0, 69.8, 19.9),
    'I2C/AREF lanes (REFCAL: x 46.4, 47.4, 48.4 north, then west along y 47.5, 48.5, 49.4)': (45.9, 36.0, 48.9, 50.0),
    'QUIET VREF trunk (REFCAL: x 62.8 north to y 46.6, then east to x 75.8)': (62.0, 36.0, 63.6, 47.2),
}
# LR-5: 10 mm from the courtyards of U7 and C31 (bounding boxes from the v1 board, Due mm; courtyard margin included)
KEEPOUT = [(31.2, 7.5, 36.0, 12.2), (36.2, 8.4, 38.2, 11.2)]
KEEP_R = 10.0
FIXED = [  # name, x, y, note
    ('J3 BNC', 102.0, 7.4, 'AWG out, body +-7.35 mm, edge >= 0.3 mm'),
    ('J2 BNC', 102.0, 24.13, 'CH2 in'),
    ('J1 BNC', 102.0, 44.45, 'CH1 in'),
    ('MH1', 96.52, 2.54, 'M2.5'),
    ('MH2', 90.17, 50.8, 'M2.5, screw optional, verify socket clearance'),
    ('J11 CAL', 56.5, 12.6, '1x3, inside REFCAL'),
]
HEADERS = [  # name, x_first, y, x_last
    ('J4', 27.94, 2.54, 27.94 + 2.54 * 7), ('J5', 50.80, 2.54, 50.80 + 2.54 * 7), ('J6', 73.66, 2.54, 73.66 + 2.54 * 7),
    ('J9', 41.66, 50.8, 41.66 - 2.54 * 9), ('J7', 63.5, 50.8, 63.5 + 2.54 * 7), ('J8', 68.58, 50.8, 68.58 + 2.54 * 7),
]

# Interface contract: net, from block -> to block, edge point (x, y), layer / width (mm), bridge, owner, note
# F = top copper.  The bottom layer is one unbroken GND plane everywhere (LR-1): no bottom copper, no cut, no hop.
C = []


def row(net, frm, to, pt, lw, bridge, owner, note):
    C.append((net, frm, to, pt, lw, bridge, owner, note))


row('+5V_DUE', 'EDGE', 'POWER', (40.6, 4.6), 'F 0.3', '', 'POWER', 'J4.5 (40.64, 2.54) north to R27/R26 side (38.1, 6.0) and on to R70')
row('+3V3A to REFCAL', 'POWER', 'REFCAL', (44.5, 12.6), 'F 0.3', '', 'POWER up to the edge, REFCAL after', 'one trunk east to U8.1 and the ADS (VDD, decoupling, pull-ups)')
row('+3V3A to AWG', 'POWER', 'AWG', (44.0, 5.0), 'F 0.2, strip lane y 0.95', '', 'POWER', 'lane east to the AWG riser (x 71.33), U3.8 and its 100 nF; own branch, never touches the quiet branch')
row('+3V3A to SCOPE', 'POWER', 'SCOPE', (44.0, 5.2), 'F 0.2, strip lane y 0.95 then riser x 69.6', '', 'POWER up to the edge, SCOPE after', 'the same lane, a branch north at x 69.6 between the wall and the AWG fence to the dual V+ and the clamps; no bridge (the alternative is two more bridges at y 24.5)')
row('VNEG', 'POWER', 'AWG', (44.0, 4.8), 'F 0.2, strip lane y 0.55', '', 'POWER', 'lane east, riser x 71.33, U3.4 and its 100 nF at the pin; TP VNEG')
row('GND', 'all', 'all', 'plane', 'B.Cu pour, one piece', '', 'integrator', 'every GND pad has its own via; no cut, no bottom signal copper anywhere')
row('VREF branch A: precision readers', 'REFCAL', 'EDGE', (50.8, 4.6), 'F 0.2', '', 'REFCAL', 'U8 pin 2 to J5.1 (A7 pad, 50.8, 2.54) and the ladder top R50.2; Kelvin from the pin, own copper (LR-8)')
row('VREF branch B: ADS AIN0', 'REFCAL', 'REFCAL', ('inside', ), 'F 0.2', '', 'REFCAL', 'U8 pin to U9.4 and C26; own copper (LR-8)')
row('VREF branch C: AWG offset', 'REFCAL', 'AWG', (64.5, 1.35), 'F 0.2, strip lane y 1.35', '', 'REFCAL up to the edge, AWG after', 'U8 pin to the strip lane, east, riser x 71.33 to R93.1 (offset filter); own copper (LR-8)')
row('VREF branch D1: scope CH1 leg + sense tie', 'REFCAL', 'SCOPE', (64.8, 46.6), 'F 0.2', '', 'REFCAL up to the edge, SCOPE after', 'CH1 leg R14 and the sense tie R90 (in REFCAL): quiet trunk x 62.8 north, y 46.6 east')
row('VREF branch D2: scope CH2 leg', 'REFCAL', 'SCOPE', (64.5, 22.8), 'F 0.2', 'BR1 over A1, BR2 over A0', 'REFCAL up to the edge, SCOPE after', 'spur off the quiet trunk (62.8, 22.8) to BR1, BR2, R16.2 (VREF_P); crosses the wall, separate from the CH1 leg row above (LR-8)')
row('AREF', 'REFCAL', 'EDGE', (48.4, 36.0), 'F 0.2', '', 'REFCAL', 'R81.2 north x 48.4, west y 49.4 to J9.8 (23.876, 50.8); unfitted part')
row('SCL', 'REFCAL', 'EDGE', (46.4, 36.0), 'F 0.2', '', 'REFCAL', 'U9.10 north x 46.4, west y 47.5 to J9.10 (18.796, 50.8)')
row('SDA', 'REFCAL', 'EDGE', (47.4, 36.0), 'F 0.2', '', 'REFCAL', 'U9.9 north x 47.4, west y 48.5 to J9.9 (21.336, 50.8)')
row('TAP1..TAP5', 'EDGE', 'REFCAL', (53.3, 4.6), 'F 0.2', '', 'REFCAL', 'J5.2..J5.6 (x 53.34 .. 63.5) up to the ladder (y 6..8.2); TAP3/TAP4 on to J11 and the ADS')
row('TAP3 / TAP4 to J11 and the ADS', 'REFCAL', 'REFCAL', ('inside', ), 'F 0.2', '', 'REFCAL', 'inside the fence; nothing of another block crosses them')
row('SNS_B', 'REFCAL', 'REFCAL', ('inside', ), 'F 0.2, sense guard and pair rule', '', 'REFCAL', 'R92 and R90 to J11.2; matched to its pair partner, away from the AWG output')
row('A1', 'SCOPE', 'EDGE', (66.04, 33.5), 'F 0.2', '', 'SCOPE', 'D5/R55.2 down x 66.04 to J5.7 (66.04, 2.54); no via, top only (LR-4)')
row('A0', 'SCOPE', 'EDGE', (68.58, 33.0), 'F 0.2', '', 'SCOPE', 'D6/R56.2 down x 68.58 to J5.8 (68.58, 2.54); no via, top only (LR-4)')
row('DAC0', 'EDGE', 'AWG', (83.82, 4.4), 'F 0.2', '', 'AWG', 'J6.5 (83.82, 2.54) straight up to R54 and pin 5; short')
row('AWG_BNC (sense node)', 'AWG', 'REFCAL', (69.8, 19.0), 'F 0.2 guard + pair rule', 'BR3 over A0, BR4 over A1', 'AWG up to the edge, REFCAL after', 'from R51/R88 at the BNC to R7.1 across the wall (AWG_I is the island between the bridges)')
row('AWG supply decoupling parts', 'AWG', 'AWG', ('inside', ), '', '', 'AWG', 'V+ and V- decoupling at pins 8 and 4; INV is a short top trace, Rg2 (R33) straddles the BIN stub as a bridge; no net leaves the pocket except those listed')
row('SCOPE dual (U1)', 'SCOPE', 'SCOPE', ('inside', ), '', '', 'SCOPE (one agent for both channels)', 'U1 is shared; CH1 and CH2 are labelled on the silk beside its halves, CH2 laid out in CH1\'s pattern, mirrored')

BRIDGES = [  # ref, nets, at (x, y), crosses
    ('BR1 (R98)', 'VREF / VREF_M', (66.04, 22.8), 'the A1 line (x 66.04)'),
    ('BR2 (R100)', 'VREF_M / VREF_P', (68.58, 24.5), 'the A0 line (x 68.58)'),
    ('BR3 (R102)', 'AWG_I / AWG_BNC', (68.58, 21.1), 'the A0 line (x 68.58)'),
    ('BR4 (R97)', 'AWG_S / AWG_I', (66.04, 19.5), 'the A1 line (x 66.04)'),
]

COL = {'POWER': '#d9822b', 'REFCAL': '#2a9d8f', 'SCOPE': '#3a6ea5', 'AWG': '#8a4fa8'}
S = 12.0   # px per mm


def px(x, y):
    return (x - X0 + 2) * S, (Y1 - y + 2) * S


def svg():
    w, h = (X1 - X0 + 4) * S, (Y1 - Y0 + 4) * S
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:.0f}" height="{h:.0f}" font-family="sans-serif">',
         f'<rect width="{w:.0f}" height="{h:.0f}" fill="#ffffff"/>']

    def rect(x0, y0, x1, y1, **a):
        ax, ay = px(x0, y1)
        bx, by = px(x1, y0)
        at = ' '.join(f'{k.replace("_", "-")}="{v}"' for k, v in a.items())
        o.append(f'<rect x="{ax:.1f}" y="{ay:.1f}" width="{bx - ax:.1f}" height="{by - ay:.1f}" {at}/>')

    def text(x, y, t, size=11, fill='#000', weight='normal'):
        a, b = px(x, y)
        o.append(f'<text x="{a:.1f}" y="{b:.1f}" font-size="{size}" fill="{fill}" font-weight="{weight}">{t}</text>')

    rect(X0, Y0, X1, Y1, fill='#f4f4f0', stroke='#000', stroke_width=2)
    for (a, b, c, d) in KEEPOUT:
        rect(a - KEEP_R, b - KEEP_R, c + KEEP_R, d + KEEP_R, fill='#d9822b', fill_opacity='0.10', stroke='#d9822b',
             stroke_dasharray='6 4', rx=KEEP_R * S)
    for name, (a, b, c, d) in CORRIDORS.items():
        rect(a, b, c, d, fill='#999', fill_opacity='0.25', stroke='#777', stroke_dasharray='3 3')
    for blk, rs in FENCES.items():
        for (a, b, c, d) in rs:
            rect(a, b, c, d, fill=COL[blk], fill_opacity='0.12', stroke=COL[blk], stroke_width=2)
        text(rs[0][0] + 0.5, rs[0][3] - 3.2, blk, 14, COL[blk], 'bold')
    for name, a, y, b in HEADERS:
        rect(min(a, b) - 1.3, y - 1.3, max(a, b) + 1.3, y + 1.3, fill='#ddd', stroke='#444')
        text(min(a, b), y + (-2.0 if y < 10 else 2.8), name, 10)
    for name, x, y, note in FIXED:
        a, b = px(x, y)
        o.append(f'<circle cx="{a:.1f}" cy="{b:.1f}" r="5" fill="#c00"/>')
        text(x + 0.8, y + 0.4, name, 10, '#c00')
    # edge points: numbered markers
    n = 0
    for k, (net, frm, to, pt, lw, br, own, note) in enumerate(C, 1):
        if len(pt) == 2 and not isinstance(pt[0], str):
            a, b = px(*pt)
            o.append(f'<circle cx="{a:.1f}" cy="{b:.1f}" r="7" fill="#fff" stroke="#000"/>')
            o.append(f'<text x="{a - 4.5:.1f}" y="{b + 3.5:.1f}" font-size="10">{k}</text>')
    for ref, nets, at, crosses in BRIDGES:
        if len(at) == 2:
            a, b = px(*at)
            o.append(f'<rect x="{a - 4:.1f}" y="{b - 4:.1f}" width="8" height="8" fill="#e63946"/>')
            text(at[0] + 0.6, at[1] - 0.3, ref, 8, '#e63946')
    text(X0 + 0.5, Y1 + 1.2, 'AFE v1 floorplan (Due mm); circles = edge points (contract row no.), red squares = bridges, dashed grey = corridors; bottom layer = one GND plane', 11)
    o.append('</svg>')
    return '\n'.join(o)


def md():
    out = ['| # | net | from -> to | edge point (x, y) | layer / width | bridge | owner | note |', '|---|---|---|---|---|---|---|---|']
    for k, (net, frm, to, pt, lw, br, own, note) in enumerate(C, 1):
        p = 'inside the fence' if (len(pt) == 1) else ('plane' if pt == 'plane' else f'({pt[0]}, {pt[1]})')
        out.append(f'| {k} | {net} | {frm} -> {to} | {p} | {lw} | {br} | {own} | {note} |')
    out += ['', '| bridge | nets split | at (x, y) | crosses |', '|---|---|---|---|']
    for ref, nets, at, crosses in BRIDGES:
        p = f'({at[0]}, {at[1]})' if len(at) == 2 else f'in {at[0]}, to be placed'
        out.append(f'| {ref} | {nets} | {p} | {crosses} |')
    out += ['', 'Notes:',
            '- v2 arrangement (AWG east beside J3), as the spec lead ruled: LR-7 keeps the AWG current loop and the 50 ohm return in its own zone. Four 0603 0R bridges (existing type), no hop, no 1206.',
            '- The first v1 contract moved the AWG west and is withdrawn: it put the AWG output lane 95 mm past the TAP and A pads.',
            '- Pad edges of J4/J5/J6 are y 1.69 (1.7 mm pads): inner lane top 1.45, gap 0.24; outer lane edge 0.45 mm to the outline. Check on the v1 board.',
            '- Keep-out (LR-5) = the courtyards of U7 and C31 inflated by 10 mm. Sensitive copper in REFCAL stays east of x 48.6 between y 9 and y 19.',
            '- The only +3V3A route to SCOPE with no bridge is the riser at x 69.6, 1.0 mm from A0 (a supply, quiet); the alternative is two more bridges at y 24.5 (to the spec lead).',
            '- Test points: one per block key node, on the existing path, no stub on A1/A0: A1, A0, AWG_OUT before R51/R88, +5V_DUE, +5V_F, +3V3A, VNEG, VREF, GND = 9, three new.']
    return '\n'.join(out)


if __name__ == '__main__':
    (HERE / 'floorplan.svg').write_text(svg())
    (HERE / 'floorplan_table.md').write_text(md() + '\n')
    subprocess.run(['magick', str(HERE / 'floorplan.svg'), str(HERE / 'floorplan.png')], check=True)
    print('wrote floorplan.svg, floorplan.png, floorplan_table.md')
