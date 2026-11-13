"""AFE version 2 floorplan and interface contract: ONE data set that draws floorplan.svg/.png and writes floorplan.md's table.

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
    'POWER': [(18.0, 4.6, 44.0, 26.0)],
    'REFCAL': [(44.5, 4.6, 64.5, 36.0)],
    'SCOPE': [(64.8, 33.5, 97.8, 50.3), (69.4, 19.9, 97.8, 33.0), (98.5, 16.5, 116.4, 50.0)],
    'AWG': [(69.8, 4.4, 95.5, 19.4), (98.5, 0.6, 116.4, 15.5)],
}
# corridors: copper owned by a block that runs outside its fence
CORRIDORS = {
    'WALL (SCOPE: A1 x 66.04, A0 x 68.58, y 2.54..38)': (64.8, 2.0, 69.4, 33.5),
    'I2C/AREF lanes (REFCAL: x 46.4, 47.4, 48.4 north, then west along y 47.5, 48.5, 49.4)': (45.9, 36.0, 48.9, 50.0),
    'STRIP lanes under the ADC/PWM pad rows (y 0.55 VNEG outermost, 0.95 +3V3A, 1.35 VREF branch C innermost; 0.2 wide, 0.2 gap; pad edge 1.69, lane top 1.45, gap 0.24)': (29.0, 0.45, 78.0, 1.45),
    'QUIET VREF trunk (REFCAL: x 62.8 north to y 46.6, then east to x 75.8)': (62.0, 36.0, 63.6, 47.2),
}
# LR-5: 10 mm from the courtyards of U401 and C409 (bounding boxes from the pass-2 board, Due mm; courtyard margin included)
KEEPOUT = [(29.7, 11.9, 33.3, 16.1), (35.2, 12.7, 38.6, 14.6)]
KEEP_R = 10.0
FIXED = [  # name, x, y, note
    ('J301 BNC', 102.0, 8.89, 'AWG out, body +-7.35 mm, edge >= 0.3 mm'),
    ('J201 BNC', 102.0, 24.13, 'CH2 in'),
    ('J101 BNC', 102.0, 41.91, 'CH1 in'),
    ('MH601', 96.52, 2.54, 'M2.5'),
    ('MH602', 90.17, 50.8, 'M2.5, screw optional, verify socket clearance'),
    ('J501 CAL', 50.1, 14.4, '1x3, inside REFCAL'),
]
HEADERS = [  # name, x_first, y, x_last
    ('J601', 27.94, 2.54, 27.94 + 2.54 * 7), ('J602', 50.80, 2.54, 50.80 + 2.54 * 7), ('J603', 73.66, 2.54, 73.66 + 2.54 * 7),
    ('J604', 41.656, 50.8, 41.656 - 2.54 * 9), ('J606', 63.5, 50.8, 63.5 + 2.54 * 7), ('J607', 68.58, 50.8, 68.58 + 2.54 * 7),
]

# Interface contract: net, from block -> to block, edge point (x, y), layer / width (mm), bridge, owner, note
# F = top copper.  The bottom layer is one unbroken GND plane everywhere (LR-1): no bottom copper, no cut.
C = []


def row(net, frm, to, pt, lw, bridge, owner, note):
    C.append((net, frm, to, pt, lw, bridge, owner, note))


row('+5V_DUE', 'EDGE', 'POWER', (40.6, 4.6), 'F 0.3', '', 'POWER', 'J601.5 (40.64, 2.54) north to R406 (38.1, 6.0)')
row('+3V3A to REFCAL', 'POWER', 'REFCAL', (44.0, 15.5), 'F 0.3', 'BR507 (in REFCAL)', 'POWER up to the edge, REFCAL after',
    'one trunk east to the REF supply (U501.1 via BR507) and the ADS (VDD, decoupling, pull-ups)')
row('+3V3A to AWG', 'POWER', 'AWG', (44.0, 6.0), 'F 0.2, strip lane y 0.95', '', 'POWER', 'lane to the AWG riser (x 71.33), pin 8 of U301; own branch, never touches the quiet branch')
row('+3V3A to SCOPE', 'POWER', 'SCOPE', (44.0, 24.5), 'F 0.2', 'BR102 (in SCOPE) crosses the quiet VREF trunk x 62.8', 'POWER', 'to BR102 at (62.0, 35.7) then BR101 over the A1 column: dual V+ segment +3V3A_U')
row('VNEG', 'POWER', 'AWG', (44.0, 4.8), 'F 0.2, strip lane y 0.55', 'BR401 (in POWER, over the +5V_F trunk)', 'POWER', 'VNEG_G to BR401 (29.21, 6.0) to the lane; to U301.4 and TP402')
row('GND', 'all', 'all', 'plane', 'B.Cu pour, one piece', '', 'integrator', 'every GND pad has its own via; no cut anywhere (spec decision 3)')
row('VREF branch A: precision readers', 'REFCAL', 'EDGE', (50.8, 4.6), 'F 0.2', '', 'REFCAL', 'U501 to J602.1 (A7 pad, 50.8, 2.54) and the ladder top R506.2; Kelvin from the pin, own copper (LR-8)')
row('VREF branch B: ADS AIN0', 'REFCAL', 'REFCAL', ('inside', ), 'F 0.2', '', 'REFCAL', 'U501 pin to U502.4; own copper (LR-8)')
row('VREF branch C: AWG offset', 'REFCAL', 'AWG', (64.5, 1.35), 'F 0.2, strip lane y 1.35', '', 'REFCAL up to the edge, AWG after', 'C501 to R305.1 (offset filter); own copper (LR-8)')
row('VREF branch D1: scope CH1 leg + sense tie', 'REFCAL', 'SCOPE', (64.8, 46.6), 'F 0.2', '', 'REFCAL up to the edge, SCOPE after', 'CH1 leg: R106 (and R509 sense tie inside REFCAL shared by agreement); quiet trunk x 62.8 north, y 46.6 east')
row('VREF branch D2: scope CH2 leg', 'REFCAL', 'SCOPE', (64.5, 22.8), 'F 0.2', 'BR503 over A1, BR504 over A0', 'REFCAL up to the edge, SCOPE after', 'spur off the quiet trunk (62.8, 22.8) to BR503, BR504, R206.2 (VREF_P); crosses the wall, separate from the CH1 leg row above')
row('AREF', 'REFCAL', 'EDGE', (48.4, 36.0), 'F 0.2', '', 'REFCAL', 'R514.2 north x 48.4, west y 49.4 to J604.8 (23.876, 50.8)')
row('SCL', 'REFCAL', 'EDGE', (46.4, 36.0), 'F 0.2', '', 'REFCAL', 'U502.10 north x 46.4, west y 47.5 to J604.10 (18.796, 50.8)')
row('SDA', 'REFCAL', 'EDGE', (47.4, 36.0), 'F 0.2', '', 'REFCAL', 'U502.9 north x 47.4, west y 48.5 to J604.9 (21.336, 50.8)')
row('TAP1..TAP5', 'EDGE', 'REFCAL', (53.3, 4.6), 'F 0.2', '', 'REFCAL', 'J602.2..J602.6 (x 53.34 .. 63.5) up to the ladder (y 6..8.2); TAP3/TAP4 on to J501.3/J501.1')
row('TAP4 to the ADS', 'REFCAL', 'REFCAL', ('inside', ), 'F 0.2', 'BR506, estimated BR508a', 'REFCAL', 'crosses the VREF branch to the ADS')
row('SNS_B', 'REFCAL', 'REFCAL', ('inside', ), 'F 0.2, pair rule', '', 'REFCAL', 'R511.1 to J501.2; matched to its pair partner (legs run together, length-matched), away from the AWG output and the charge pump, no via; the pour flanking it at normal clearance is enough (no guard track)')
row('A1', 'SCOPE', 'EDGE', (66.04, 33.5), 'F 0.2', '', 'SCOPE', 'R108.2 down x 66.04 to J602.7 (66.04, 2.54); no via, top only (LR-4)')
row('A0', 'SCOPE', 'EDGE', (68.58, 33.0), 'F 0.2', '', 'SCOPE', 'R208.2/D201 (CH2_RISO, merged into A0; BR201 deleted) down x 68.58 to J602.8 (68.58, 2.54)')
row('DAC0', 'EDGE', 'AWG', (83.82, 4.4), 'F 0.2', '', 'AWG', 'J603.5 (83.82, 2.54) straight up to R306 and pin 5; 1.6 mm (LR-7)')
row('AWG_BNC (sense node)', 'AWG', 'REFCAL', (69.8, 19.0), 'F 0.2, pair rule', 'BR501 over A0, BR502 over A1', 'AWG up to the edge, REFCAL after', 'from R301/R302 at the BNC to R507.1 across the wall')
row('AWG supply decoupling parts', 'AWG', 'AWG', ('inside', ), '', '', 'AWG', 'V+ and V- decoupling at pins 8 and 4; no net leaves the pocket except those listed')
row('SCOPE dual (U101)', 'SCOPE', 'SCOPE', ('inside', ), '', 'BR101, BR102', 'SCOPE (one agent for both channels)', 'U101 is shared; its halves are swapped so A1/A0 never cross: CH1 on pins 5-7 (upper), CH2 on pins 1-3')

BRIDGES = [  # ref, nets, at (x, y), crosses
    ('BR101', '+3V3A_S / +3V3A_U', (66.04, 35.7), 'the A1 column (x 66.04)'),
    ('BR102', '+3V3A / +3V3A_S', (62.8, 35.7), 'the quiet VREF trunk (x 62.8)'),
    ('BR401', 'VNEG_G / VNEG', (29.21, 6.0), 'the +5V_F trunk (y 6.0)'),
    ('BR501', 'AWG_BNC_M / AWG_BNC', (67.8, 21.1), 'the A0 line'),
    ('BR502', 'AWG_BNC_L / AWG_BNC_M', (65.2, 19.5), 'the A1 line'),
    ('BR503', 'VREF / VREF_M', (65.2, 22.8), 'the A1 line'),
    ('BR504', 'VREF_M / VREF_P', (67.8, 24.5), 'the A0 line'),
    ('BR506', 'TAP4 / TAP4_A', (53.6, 14.7), 'the ADS VREF branch (y 14.7)'),
    ('BR507', '+3V3A_R / +3V3A', (55.1, 14.7), 'the ADS VREF branch (y 14.7)'),
    ('BR508a (estimate)', 'TAP4 / TAP4_A', ('REFCAL', ), 'the VREF branch to the A7 pad and ladder top'),
    ('BR508b (estimate)', '+3V3A / +3V3A_R', ('REFCAL', ), 'the TAP4 westward run or a VREF branch'),
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
    text(X0 + 0.5, Y1 + 1.2, 'AFE v2 floorplan (Due mm); circles = edge points (contract row no.), red squares = bridges, dashed grey = corridors; bottom layer = one GND plane', 11)
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
            '- Keep-out (LR-5) = the courtyards of U401 and C409 inflated by 10 mm. Distances from it, mm: A7 branch edge 14.6, J602.1 15.9, TAP edge 16.8, J501.1 11.5, ADS U502 14.3, R506 14.3, I2C/AREF edge points 22.8, strip lane (y 0.55) 11.4.',
            '- Inside it by design: rows 2, 3 and 5 (5.5, 8.6, 9.6 mm), the generator\'s own output rails, carried by POWER. REFCAL\'s west fence (x 44.5) is 5.9 mm from it, so no sensitive copper in REFCAL west of x 48.6 between y 9 and y 19; only the +3V3A trunk and the rail rows may use that strip.',
            '- Strip lanes: pad edge of J601/J602 is y 1.69 (1.7 mm pads, measured on the pass-2 board), inner lane top y 1.45, gap 0.24; outermost lane edge y 0.45, 0.45 mm to the outline.',
            '- BR201 is deleted: R208.2 and D201 sit on A0 directly (design.py to follow).']
    return '\n'.join(out)


if __name__ == '__main__':
    (HERE / 'floorplan.svg').write_text(svg())
    (HERE / 'floorplan_table.md').write_text(md() + '\n')
    subprocess.run(['magick', str(HERE / 'floorplan.svg'), str(HERE / 'floorplan.png')], check=True)
    print('wrote floorplan.svg, floorplan.png, floorplan_table.md')
