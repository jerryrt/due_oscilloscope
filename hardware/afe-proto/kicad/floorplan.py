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
    'STRIP lanes under the ADC/PWM pad rows (POWER, REFCAL: y 0.55 +3V3A outermost, 0.95 VNEG, 1.35 VREF branch C innermost; 0.2 wide, 0.2 gap; pad edge 1.69, lane top 1.45)': (44.0, 0.45, 78.0, 1.45),
    'AWG riser (x 71.33: the three strip lanes turn north to U301 and the offset filter)': (70.8, 1.0, 71.9, 12.0),
    'SCOPE +3V3A branch (POWER: y 24.5 east along the REFCAL west side, then north around REFCAL, R413 over AREF, straight to R110 at (66.04, 35.7))': (44.0, 24.0, 63.6, 36.4),
    'I2C/AREF lanes (REFCAL: x 46.4, 47.4, 48.4 north, then west along y 47.5, 48.5, 49.4)': (45.9, 36.0, 48.9, 50.0),
    'QUIET VREF trunk (REFCAL: x 62.8 north to y 46.6, then east to x 75.8)': (62.0, 36.0, 63.6, 47.2),
}
# LR-5: 10 mm from the courtyards of U401 and C402 (bounding boxes from the v1 board, Due mm; courtyard margin included)
KEEPOUT = [(31.2, 7.5, 36.0, 12.2), (36.2, 8.4, 38.2, 11.2)]
KEEP_R = 10.0
FIXED = [  # name, x, y, note
    ('J301 BNC', 102.0, 7.4, 'AWG out, body +-7.35 mm, edge >= 0.3 mm'),
    ('J201 BNC', 102.0, 26.67, 'CH2 in'),
    ('J101 BNC', 102.0, 44.45, 'CH1 in'),
    ('MH601', 96.52, 2.54, 'M2.5'),
    ('MH602', 90.17, 50.8, 'M2.5, screw optional, verify socket clearance'),
    ('J501 CAL', 56.5, 12.6, '1x3, inside REFCAL'),
]
HEADERS = [  # name, x_first, y, x_last
    ('J601', 27.94, 2.54, 27.94 + 2.54 * 7), ('J602', 50.80, 2.54, 50.80 + 2.54 * 7), ('J603', 73.66, 2.54, 73.66 + 2.54 * 7),
    ('J606', 41.66, 50.8, 41.66 - 2.54 * 9), ('J604', 63.5, 50.8, 63.5 + 2.54 * 7), ('J605', 68.58, 50.8, 68.58 + 2.54 * 7),
]

# Interface contract: net, from block -> to block, edge point (x, y), layer / width (mm), bridge, owner, note
# F = top copper.  The bottom layer is one unbroken GND plane everywhere (LR-1): no bottom copper, no cut, no hop.
C = []


def row(net, frm, to, pt, lw, bridge, owner, note):
    C.append((net, frm, to, pt, lw, bridge, owner, note))


row('+5V_DUE', 'EDGE', 'POWER', (38.1, 4.6), 'F 0.3', '', 'POWER', 'J601.5 (38.10, 2.54: the 5 V pin of POWER0; x 40.64 is GND) north to R404/R403 side (38.1, 6.0) and on to R408')
row('+3V3A to REFCAL', 'POWER', 'REFCAL', (44.5, 12.6), 'F 0.3', '', 'POWER up to the edge, REFCAL after', 'first entry, west edge: U501.1 and its caps C501/C505 (the REF VIN, in the N face of the VREF tree)')
row('+3V3A to REFCAL, ADS side', 'POWER', 'REFCAL', (56.0, 36.0), 'F 0.3', 'BR7 over leg D', 'POWER up to the edge, REFCAL after', 'second entry, NORTH edge x 56 (east of the SCL/SDA/AREF exits at x 46.4 / 47.4 / 48.4): feeds only R517 north pad; the bridge order SCL, SDA, AREF, +3V3A along leg D is forced by the ADS pins (REFCAL passes 3 and 4 showed it); beyond BR7 (net P33_R) the ADS VDD, C502, R509/R511 and the clamps. Both entries are one trunk outside the fence (a tee), so LR-6 stays one piece for REFCAL; the integrator routes the trunk north outside the fences and east at y about 38, crossing the I2C/AREF bundle by a hop under SDA and SCL and a bridge over AREF')
row('+3V3A to AWG', 'POWER', 'AWG', (44.0, 5.0), 'F 0.2, strip lane y 0.55', '', 'POWER', 'lane east to the AWG riser (x 71.33), U301.8 and its 100 nF; own branch, never touches the quiet branch')
row('+3V3A to SCOPE', 'POWER', 'SCOPE', (44.0, 24.5), 'F 0.2', 'R413 over AREF (corridor, north of REFCAL), BR6 over the A1 column', 'POWER up to the edge, SCOPE after', 'own branch from the OUT+ star (LR-6): out of POWER\'s east edge, north along REFCAL\'s west side and around its north edge, R413 over AREF, then BR6 (66.04, 35.7) to the dual V+ segment and the clamp rails (P33_U); shares no copper with the AWG or REF branches')
row('VNEG', 'POWER', 'AWG', (44.0, 4.8), 'F 0.2, strip lane y 0.95', '', 'POWER', 'lane east, riser x 71.33, U301.4 and its 100 nF at the pin; TP VNEG')
row('GND', 'all', 'all', 'plane', 'B.Cu pour, one piece', '', 'integrator', 'every GND pad has its own via; no cut, no bottom signal copper anywhere')
row('VREF branch A: precision readers', 'REFCAL', 'EDGE', (50.8, 4.6), 'F 0.2', '', 'REFCAL', 'U501 pin 2 to J602.1 (A7 pad, 50.8, 2.54) and the ladder top R508.2; Kelvin from the pin, own copper (LR-8)')
row('VREF branch B: ADS AIN0', 'REFCAL', 'REFCAL', ('inside', ), 'F 0.2', '', 'REFCAL', 'U501 pin to U502.4 and C503; own copper (LR-8)')
row('VREF branch C: AWG offset', 'REFCAL', 'AWG', (64.5, 1.35), 'F 0.2, strip lane y 1.35', '', 'REFCAL up to the edge, AWG after', 'U501 pin to the strip lane, east, riser x 71.33 to R307.1 (offset filter); own copper (LR-8)')
row('VREF branch D: scope centring + sense tie', 'REFCAL', 'SCOPE', (64.5, 22.8), 'F 0.2', 'BR1 over A1, BR2 over A0', 'REFCAL up to the edge, SCOPE after', 'ONE quiet branch (the spec lead\'s first LR-8 reading): U501 pin to the sense tie R512 and out of the east edge at (64.5, 22.8) to the bridges R515 (A1) and R516 (A0); beyond them SCOPE feeds both R3 legs (R104 CH1, R204 CH2) from the net VREF_P. Replaces the earlier D1 (north trunk) and D2 rows: two legs made REFCAL unroutable on one layer')
row('AREF', 'REFCAL', 'EDGE', (48.4, 36.0), 'F 0.2', '', 'REFCAL', 'R510.2 north x 48.4, west y 49.4 to J606.8 (23.876, 50.8); unfitted part')
row('SCL', 'REFCAL', 'EDGE', (46.4, 36.0), 'F 0.2', '', 'REFCAL', 'U502.10 (net SCL1_A) through BR9 over a VREF leg, then north x 46.4, west y 47.5 to J606.10 (18.796, 50.8)')
row('SDA', 'REFCAL', 'EDGE', (47.4, 36.0), 'F 0.2', '', 'REFCAL', 'U502.9 (net SDA1_A) through BR8 over a VREF leg, then north x 47.4, west y 48.5 to J606.9 (21.336, 50.8)')
row('TAP1..TAP5', 'EDGE', 'REFCAL', (53.3, 4.6), 'F 0.2', '', 'REFCAL', 'J602.2..J602.6 (x 53.34 .. 63.5) up to the ladder (y 6..8.2); TAP3/TAP4 on to J501 and the ADS')
row('TAP3 / TAP4 to J501 and the ADS', 'REFCAL', 'REFCAL', ('inside', ), 'F 0.2', '', 'REFCAL', 'inside the fence; nothing of another block crosses them')
row('SNS_B', 'REFCAL', 'REFCAL', ('inside', ), 'F 0.2, sense guard', '', 'REFCAL', 'R514 and R520 to J501.2 (R520 splits B: SNS_B_N carries only the R512 tie to VREF branch D); no copper-length requirement (the pair is matched by the Rs / Rm source impedance, PA-4 / S3), away from the AWG output')
row('A1', 'SCOPE', 'EDGE', (66.04, 33.5), 'F 0.2', '', 'SCOPE', 'D101/R107.2 down x 66.04 to J602.7 (66.04, 2.54); no via, top only (LR-4)')
row('A0', 'SCOPE', 'EDGE', (68.58, 33.0), 'F 0.2', '', 'SCOPE', 'D201/R207.2 down x 68.58 to J602.8 (68.58, 2.54); no via, top only (LR-4)')
row('DAC0', 'EDGE', 'AWG', (83.82, 4.4), 'F 0.2', '', 'AWG', 'J603.5 (83.82, 2.54) straight up to R305 and pin 5; short')
row('AWG_BNC (sense node)', 'AWG', 'REFCAL', (69.8, 19.0), 'F 0.2 guard', 'BR3 over A0, BR4 over A1', 'AWG up to the edge, REFCAL after', 'from R304/R306 at the BNC to R501.1 across the wall (AWG_I is the island between the bridges)')
row('AWG supply decoupling parts', 'AWG', 'AWG', ('inside', ), '', '', 'AWG', 'V+ and V- decoupling at pins 8 and 4; INV is a short top trace, Rg2 (R302) straddles the BIN stub as a bridge; no net leaves the pocket except those listed')
row('SCOPE dual (U101)', 'SCOPE', 'SCOPE', ('inside', ), '', '', 'SCOPE (one agent for both channels)', 'U101 is shared; CH1 and CH2 are labelled on the silk beside its halves, CH2 laid out in CH1\'s pattern, mirrored')

BRIDGES = [  # ref, nets, at (x, y), crosses
    ('BR1 (R515)', 'VREF / VREF_M', (66.04, 22.8), 'the A1 line (x 66.04)'),
    ('BR2 (R516)', 'VREF_M / VREF_P', (68.58, 24.5), 'the A0 line (x 68.58)'),
    ('BR3 (R310)', 'AWG_I / AWG_BNC', (68.58, 21.1), 'the A0 line (x 68.58)'),
    ('BR4 (R309)', 'AWG_S / AWG_I', (66.04, 19.5), 'the A1 line (x 66.04)'),
    ('BR6 (R110)', 'P33_S / P33_U', (66.04, 35.7), 'the A1 column (x 66.04)'),
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
            '- v2 arrangement (AWG east beside J301), as the spec lead ruled: LR-7 keeps the AWG current loop and the 50 ohm return in its own zone. Thirteen 0603 0R bridges (existing type), no hop, no 1206: six in the wall corridor and three inside REFCAL (the block agent found a planar cut there: the VREF tree with exits south, north and east splits the fence and the ADS straddles it, so +3V3A, SDA and SCL cross a VREF leg by a bridge each).',
            '- The first v1 contract moved the AWG west and is withdrawn: it put the AWG output lane 95 mm past the TAP and A pads.',
            '- Strip lane order (spec lead accepted): +3V3A y 0.55 outermost, VNEG y 0.95, VREF C y 1.35 inner; not VNEG outermost. Estimate *(check)*: over about 20 mm of parallel 0.2 / 0.2 mm lane the mutual capacitance is order 0.1-0.2 pF; with about 10 mV of 2 MHz pump ripple *(check)* on VNEG that injects roughly 25 nA into the VREF lane, negligible at the reference output impedance, and the AWG-end 100 ohm / 20 uF filter removes it.',
            '- Measured on v1 footprints (J601, J602, J603): pad edge y 1.69 (1.7 mm pads), inner lane top y 1.45, gap 0.24; outermost lane edge y 0.45, which is 0.50 mm from the outline (y -0.05).',
            '- Keep-out (LR-5) = the courtyards of U401 and C402 inflated by 10 mm. Sensitive copper in REFCAL stays east of x 48.6 between y 9 and y 19.',
            '- +3V3A to SCOPE is its own branch from the star (LR-6) with two bridges (R413 over AREF, BR6 over the A1 column; the old BR5 over the VREF trunk is removed), as row 4 of v2; the riser variant is rejected because it shares the strip lane of the AWG.',
            '- Test points: one per block key node, on the existing path, no stub on A1/A0: A1, A0, AWG_OUT before R304/R306, +5V_DUE, +5V_F, +3V3A, VNEG, VREF, GND = 9, three new.']
    return '\n'.join(out)


if __name__ == '__main__':
    (HERE / 'floorplan.svg').write_text(svg())
    (HERE / 'floorplan_table.md').write_text(md() + '\n')
    subprocess.run(['magick', str(HERE / 'floorplan.svg'), str(HERE / 'floorplan.png')], check=True)
    print('wrote floorplan.svg, floorplan.png, floorplan_table.md')
