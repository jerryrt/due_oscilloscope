"""Hand placement of the AFE version 2 shield (second layout pass), with the reason beside each part.

Due coordinates (mm): x right, Yup up, origin the Due's lower-left corner; rotation in degrees, KiCad's convention.
PLACE[ref] = (pad, x, y, rot) puts the named pad's centre at (x, y); pad 'c' is the footprint origin.
An 0603 at rot 0 has pin 1 on the left, 180 on the right, 90 at the bottom, 270 at the top.

Floor plan of this pass (docs: README.md, "The PCB"):
  right edge   BNCs J101 (CH1, TOP, y 41.91), J201 (CH2, y 24.13), J301 (AWG, y 8.89); each centre pin runs straight along
               its row between two rows of unused XIO0 pins;
  scope        CH1 is the upper channel and CH2 the lower, so the two ADC lines (A1 on the left header pin, A0 on the
               right) never cross.  This is why the dual's halves are swapped (design.py);
  AWG          bottom right, DAC0 straight up into the op-amp's input pin, supplies up from the bottom strip;
  wall         the two ADC lines run down to the bottom header at x 66.04 and 68.58; what must cross them (the AWG's
               sense node, the scope's VREF branch to CH2) crosses on 0 ohm bridges, listed in design.py;
  bottom strip three lanes under the ADCL0/ADCH0 pad rows (y 0.35, 0.75, 1.15, 0.2 wide, 0.2 apart) carry VNEG, +3V3A
               and the AWG's VREF branch from the left to the AWG pocket;
  power        far left by the 5 V pin, 10 mm or more from every ADC and reference trace (LR-5);
  REF / CAL    middle left above the ADCL0 pads.
"""

PLACE = {}
LOCKED = {'J601', 'J602', 'J603', 'J604', 'J605', 'J606', 'J607', 'MH601', 'MH602'}
# nets changed on the PCB only: none; design.py carries the dual's swapped halves, the bridges and the direct CH2 line.
NET_OVERRIDE = {}
# PCB-only 0 ohm bridges: none; every bridge is in design.py (BR101, BR102, BR401, BR501-504, BR506, BR507).  The dict
# stays because build_pcb.py and lr_check.py read it: ref -> (pin1 net, pin2 net, block, what it crosses)
EXTRA = {}
# blocks for LR-11 where the part sits in another block's territory (reported)
BLOCK_OVERRIDE = {}
OUTLINE = {}
LABEL = {}
SILK = []
ARROWS = []


def put(ref, pad, x, y, rot=0):
    PLACE[ref] = (pad, round(x, 3), round(y, 3), rot % 360)


# ------------------------------------------------------------------------------------------ headers, BNCs, standoffs
for ref, (x, y, rot) in {'J601': (27.94, 2.54, 90), 'J602': (50.80, 2.54, 90), 'J603': (73.66, 2.54, 90),
                         'J606': (63.50, 50.80, 270), 'J607': (68.58, 50.80, 90), 'J604': (41.656, 50.80, 270)}.items():
    put(ref, '1', x, y, rot)
put('J605', '2', 96.52, 50.80, 0)         # the Due's XIO0: this footprint swaps odd and even numbers
BNC_X = 102.0
ROW = {'CH1': 41.91, 'CH2': 24.13, 'AWG': 6.65}
put('J101', '1', BNC_X, ROW['CH1'], 270)
put('J201', '1', BNC_X, ROW['CH2'], 270)
put('J301', '1', BNC_X, ROW['AWG'], 270)
put('MH601', 'c', 96.52, 2.54)
put('MH602', 'c', 90.17, 50.8)

# ------------------------------------------------------------------------------------------ scope
UX, UY = 76.0, 33.0        # U101 (rot 90): bottom pads 1..4 at x 74.1 75.4 76.6 77.9, y 30.5; top 5..8 y 35.5
put('U101', 'c', UX, UY, 90)
NX = 82.5                  # the divider node N of each channel, x


PY = 3.2                   # row pitch of a channel: a 0.8 mm designator fits between rows (LR-11)


def channel(b, y, dy):
    """b = 100 / 200, y = the BNC row, dy = +1 when the reference chain goes up (CH1), -1 when it goes down (CH2).
    The N pads (R2a, R3a, Cn, Rnp and R1b's) sit on one vertical bus at x NX; Cn is on the inner side."""
    R = lambda k: f'R{b + k}'
    C = lambda k: f'C{b + k}'
    put(R(1), '1', NX + 5.05, y, 180)                    # R1a 510k, IN on its right
    put(R(2), '2', NX, y, 180)                           # R1b 30k, N on its left pad
    put(C(1), '1', NX + 3.325, y + PY * dy, 180)         # C1 across R1
    put(R(5), '1', NX, y + PY * dy, 180)                 # R3a 470k, N on its right
    put(R(6), '1', NX - 3.35, y + PY * dy, 180)          # R3b 200k, VREF at its left end
    put(R(3), '1', NX, y - PY * dy, 0)                   # R2a 1M
    put(R(4), '1', NX + 3.35, y - PY * dy, 0)            # R2b 510k to ground
    put(C(2), '1', NX, y - 1.8 * PY * dy, 0)             # Cn 12p at N, inner side, kept 6 mm from the other channel's (LR-2)
    put(R(7), '1', NX - 1.7, y, 180)                     # Rnp 470R


channel(100, ROW['CH1'], +1)
channel(200, ROW['CH2'], -1)
put('C103', '1', 79.9, 38.4, 270)               # Cpx at NP of CH1 (pad 5)
put('C203', '1', 79.15, 26.6, 0)                # Cpx at NP of CH2 (pad 3), pad 1 on the NP track
put('R108', '1', 75.4, 37.5, 90)                # Riso CH1: OUT at pad 7, A1 line leaves up
put('R208', '1', 74.3, 28.45, 270)              # Riso CH2: OUT at pad 1 (top), A0 line leaves down and west
put('D101', '3', 66.04, 33.0, 180)              # CH1 clamp east of the A1 column, on the dual's supply segment
put('D201', '3', 70.5, 27.3, 180)               # CH2 clamp on the A0 line, +3V3A_U to the north
put('BR101', '1', 65.215, 35.7, 0)              # +3.3 V over the A1 column (x 66.04), into the dual's V+ segment
put('C104', '1', 70.1, 34.6, 270)               # U101 V+ decoupling on +3V3A_U
put('C105', '1', 71.7, 34.6, 270)
put('TP101', 'c', 64.3, 29.5)                   # A1 test point, west of the A1 column
put('TP201', 'c', 72.1, 22.2)                   # A0 test point on the A0 column's east side

# ------------------------------------------------------------------------------------------ AWG
# U301 rot 0, centre (81.345, 11.5): west column bottom to top 4 V-, 3 BIN, 2 FB, 1 OA (x 78.87, y 9.6 .. 13.4);
# east column bottom to top 5 BIN, 6 FB, 7 OB, 8 V+ (x 83.82).  DAC0 (83.82, 2.54) rises straight into pin 5; V- comes up
# the ring gap at x 77.47 into pin 4; V+ along the north strip and down x 83.82 between R308's pads (R308 straddles
# nothing: the trench passes between its pads, no bridge needed); R304 and the filter are on the west pins.
put('U301', 'c', 81.345, 11.5, 0)
put('R306', '1', 83.82, 5.3, 90)                # DAC0 series, pad 2 at (83.82, 6.95)
put('R307', '1', 85.6, 7.0, 0)                  # BIN to ground, east of R306
put('R308', '1', 83.0, 16.9, 0)                 # OA balancing 1R, V+ comes down between its pads
put('R309', '1', 85.9, 12.3, 0)                 # OB balancing 1R
put('R303', '1', 87.55, 10.6, 180)              # Rf: pad 1 (VO) east, pad 2 (FB) west
put('C301', '1', 87.55, 8.9, 180)               # Cf: pad 1 (VO) east
put('R304', '1', 76.9, 12.135, 180)             # Rg2 at pin 2
put('R305', '1', 70.5, 6.6, 0)                  # offset filter 100R; the V+ riser (x 71.33) passes between its pads
put('C303', '1', 74.0, 9.0, 0)
put('C304', '1', 74.0, 6.6, 0)
put('R301', '1', 88.3, 14.4, 0)                 # back-termination pair at the BNC
put('R302', '1', 90.0, 9.0, 270)
put('C305', '1', 86.3, 14.9, 90)                # V+ decoupling at pin 8 (joined to the V+ pad by hand)
put('C306', '1', 79.3, 6.4, 90)                 # V- decoupling at pin 4
put('TP301', 'c', 89.6, 11.9)

# ------------------------------------------------------------------------------------------ power
# The +5V_F trunk leaves R406 (by the 5 V pad) west along y 5.0, up x 19.5 and east along y 12.25 into VIN: it
# encloses the OUT-/CP/FB- parts on their south-west side, so VNEG leaves through the 0 ohm bridge BR401 (the only
# exit that crosses it).  EN- drops straight to the trunk; EN+ goes round the north end to VIN, and R401 straddles
# that leg (its FB+ pad inside, its +3V3A pad outside).  OUT+ and the flying capacitor have the east side to themselves.
put('U401', 'c', 31.5, 14.0, 0)
put('C409', '1', 36.0, 14.4, 0)                # flying capacitor east of pins 9 and 10, pad 1 (C+) on the west
put('R406', '1', 38.1, 6.0, 180)                # 5 V sense, pad 1 on the 5 V pad's column
put('C401', '1', 22.0, 14.3, 90)
put('C402', '1', 24.6, 14.3, 90)
put('C403', '1', 27.6, 10.2, 180)               # CP caps and OUT- caps: pad 1 (the live one) on the east, toward the pins
put('C404', '1', 23.6, 10.2, 180)
put('C407', '1', 27.6, 8.0, 180)
put('C408', '1', 23.6, 8.0, 180)
put('R403', '1', 31.0, 7.3, 0)
put('R404', '1', 31.0, 9.0, 0)
put('R405', '1', 31.0, 10.7, 0)
put('BR401', '1', 29.21, 6.825, 270)
put('R401', '1', 31.3, 19.85, 270)
put('R402', '1', 28.6, 16.6, 0)
put('C405', '1', 37.6, 17.6, 0)
put('C406', '1', 37.6, 20.4, 0)
put('R407', '1', 41.0, 23.0, 0)
for k, x in enumerate((21.0, 24.0, 27.0, 30.0), 1):
    put(f'TP40{k}', 'c', x, 22.8)               # +3V3A, VNEG, +5V_F, GND

# ------------------------------------------------------------------------------------------ reference, ladder, ADS1115, CAL
# U501 east of the ADS: its VREF pin (NE) feeds three branches that never meet - west to the ADS, north then east then
# north along x 62.8 to the scope's centring resistors (the quiet branch; R507 straddles it), and south-east through C501
# to the AWG's lane.  The I2C and AREF lines go north-west from the ADS, west of the trunk, and cross nothing.
put('U501', 'c', 58.0, 13.0, 180)
put('C501', '1', 61.0, 14.35, 270)
put('C502', '1', 58.0, 10.3, 0)
put('R514', '1', 50.5, 33.2, 0)
put('TP501', 'c', 61.4, 17.4)
put('R506', '2', 51.245, 6.0, 180)
put('R505', '2', 53.785, 8.2, 180)
put('R504', '2', 56.325, 6.0, 180)
put('R503', '2', 58.865, 8.2, 180)
put('R502', '2', 61.405, 6.0, 180)
put('R501', '1', 63.5, 8.8, 90)
put('J501', '1', 50.1, 14.4, 0)               # CAL: pins 1..3 run along y 12.9; shunt across 2-3 is 'on'
put('U502', 'c', 52.0, 19.5, 90)
put('C503', '1', 55.4, 25.6, 0)
put('R512', '1', 53.4, 25.2, 90)
put('R513', '1', 49.0, 24.6, 90)
put('R507', '1', 63.625, 19.5, 180)
put('R508', '1', 60.2, 21.8, 90)
put('R509', '1', 60.2, 25.0, 90)
put('R510', '1', 59.6, 19.5, 180)
put('R511', '1', 58.7, 23.45, 180)

# ------------------------------------------------------------------------------------------ the wall bridges (EXTRA)
# The ADC lines A1 (x 66.04) and A0 (x 68.58) are a wall between the left half and the AWG pocket.  What crosses it
# does so on 0 ohm bridges, one per line: the AWG's sense node (AWG_BNC -> R507) and the scope's VREF branch to CH2's R3b.
put('BR102', '1', 61.975, 35.7, 0)
put('BR507', '1', 55.1, 13.735, 90)
put('BR506', '1', 53.6, 13.875, 90)
put('BR502', '1', 65.215, 19.5, 0)
put('BR501', '1', 67.755, 21.1, 0)
put('BR503', '1', 65.215, 22.8, 0)
put('BR504', '1', 67.755, 24.5, 0)

# ------------------------------------------------------------------------------------------ hand routes
LW = 0.2
Y_N, Y_3, Y_R = 0.35, 0.75, 1.15        # VNEG, +3V3A, VREF lanes under the pad rows
PREROUTE = [
    # the ADC lines: a wall at x 66.04 (A1) and 68.58 (A0)
    ('A1', 'F', [('R108', '2'), (66.04, 38.95), (66.04, 2.54)], 0.2),
    ('A0', 'F', [('R208', '2'), (74.3, 27.0), (68.58, 27.0), (68.58, 2.54)], 0.2),
    # lanes: VNEG to the AWG's pin 4, +3V3A (riser x 71.33, north strip y 18.6, down x 83.82) to pin 8, VREF to R305
    ('VNEG', 'F', [('BR401', '2'), (29.21, Y_N), (77.47, Y_N), (77.47, 6.4), ('C306', '1'), (78.2, 6.4), (78.2, 9.0), ('U301', '4')], LW),
    ('+3V3A', 'F', [(47.5, 6.0), (47.5, Y_3), (71.33, Y_3), (71.33, 18.6), (83.82, 18.6), (83.82, 13.405), ('U301', '8')], LW),
    ('VREF', 'F', [('C501', '1'), (64.77, 14.35), (64.77, Y_R), (70.5, Y_R), ('R305', '1')], LW),
    # the quiet VREF branch: from the pin north, east, then north along x 62.8 (R507 straddles it at y 19.5), spurs to
    # R509 and BR503, then along y 46.6 to R106
    ('VREF', 'F', [('U501', '2'), (58.94, 15.2), (62.8, 15.2), (62.8, 46.6), (75.8, 46.6), ('R106', '2')], 0.2),
    ('VREF', 'F', [(62.8, 22.8), ('BR503', '1')], 0.2),
    ('VREF', 'F', [(62.8, 26.65), ('R509', '2')], 0.2),
    # the generator: +5V_F trunk (R406, x 19.5, VIN), EN- straight down to it, EN+ round the north end (R401 straddles)
    ('+5V_F', 'F', [('R406', '2'), (19.5, 6.0), (19.5, 14.25), ('U401', '3')], 0.3),
    ('+5V_F', 'F', [('U401', '8'), (34.0, 13.25), (34.0, 6.0)], 0.2),
    ('+5V_F', 'F', [('U401', '12'), (32.45, 19.0), (27.0, 19.0), (27.0, 14.25)], 0.2),
    # inside the trunk: CP along y 13.25 / 11.6 to both caps; OUT- down x 30.0 to the caps, the divider and BR401
    ('LM_CP', 'F', [('U401', '5'), (23.6, 13.25), (23.6, 10.93)], 0.2),
    ('LM_CP', 'F', [(27.6, 13.25), (27.6, 10.93)], 0.2),
    ('VNEG_G', 'F', [('U401', '6'), (30.0, 12.75), (30.0, 9.1), (23.6, 9.1), (23.6, 8.73)], 0.2),
    ('VNEG_G', 'F', [(30.0, 9.1), (28.2, 8.0), (27.6, 8.0)], 0.2),
    ('VNEG_G', 'F', [(30.0, 7.3), (31.0, 7.3)], 0.2),
    ('VNEG_G', 'F', [(30.0, 9.1), (30.0, 6.9), (29.61, 6.9)], 0.2),
    # I2C and AREF: north along x 46.4 (SCL), 47.4 (SDA), 48.4 (AREF), then west along the top edge to the PWMH0 pins
    ('SCL', 'F', [('U502', '10'), (51.0, 27.0), (46.4, 27.0), (46.4, 47.5), (18.796, 47.5), ('J604', '10')], 0.2),
    ('SDA', 'F', [('U502', '9'), (51.5, 27.8), (47.4, 27.8), (47.4, 48.5), (21.336, 48.5), ('J604', '9')], 0.2),
    ('AREF', 'F', [('R514', '2'), (52.15, 34.2), (48.4, 34.2), (48.4, 49.4), (23.876, 49.4), ('J604', '8')], 0.2),
    # the sense node's long leg: from BR501 along the north strip (y 19.5) and down the east edge (x 91.35) to R301
    ('AWG_BNC', 'F', [('BR501', '2'), (70.2, 21.1), (70.2, 19.5), (91.35, 19.5), (91.35, 14.4)], 0.2),
    ('+3V3A', 'F', [('C305', '1'), (85.3, 14.2), (84.6, 13.405)], 0.2),
    # the flying capacitor, by hand (the 0.5 mm pins close each other in otherwise)
    ('LM_C1N', 'F', [('U401', '9'), (33.0, 13.6), (37.65, 13.6), ('C409', '2')], 0.2),
    # the OUT+ star point: the pin, C405 and C406 joined by hand; the branches leave it from the router
    ('+3V3A', 'F', [('U401', '11'), (33.2, 14.75), (33.9, 15.5), (37.0, 15.5), (37.0, 17.6), ('C405', '1')], 0.3),
    ('+3V3A', 'F', [(37.0, 17.6), (37.0, 20.4), ('C406', '1')], 0.3),
    ('LM_C1P', 'F', [('U401', '10'), ('C409', '1')], 0.2),
    ('GND', 'F', [('C407', '2'), (25.6, 6.95)], 0.2),
    ('GND', 'F', [('C408', '2'), (21.6, 6.95)], 0.2),
    ('VREF', 'F', [('U502', '4'), (52.5, 14.7), (56.0, 14.7), (58.2, 13.95), ('U501', '2')], 0.2),
    ('TAP4_A', 'F', [('U502', '5'), (53.0, 16.3), (53.6, 15.525)], 0.2),
    ('+3V3A', 'F', [(52.0, 19.5), (55.1, 19.5), ('BR507', '2')], 0.2),
    ('VREF', 'F', [('J602', '1'), (50.0, 3.34), (50.0, 5.5), (50.5, 6.0), ('R506', '2')], 0.2),
    # ADS: the +3V3A feed comes in from the west under the package (y 19.5) to VDD, then north to C503 and R512
    ('+3V3A', 'F', [('U502', '8'), (52.0, 19.5)], 0.2),
    ('+3V3A', 'F', [(49.0, 19.5), ('R513', '1')], 0.2),
    ('+3V3A', 'F', [('U502', '8'), (52.0, 24.6), (55.4, 24.6), ('C503', '1')], 0.2),
    ('+3V3A', 'F', [(53.4, 24.6), ('R512', '1')], 0.2),
    ('SDA', 'F', [('R512', '2'), (51.5, 26.85)], 0.2),
    ('ADS_TAP', 'F', [('U502', '6'), (53.0, 22.3), (57.0, 22.3), (57.95, 20.0), ('R510', '2')], 0.2),
    ('ADS_B', 'F', [('U502', '7'), (52.5, 23.0), (56.0, 23.0), ('R511', '2')], 0.2),
    # AWG: the two ties under the body
    ('AWG_BIN', 'F', [('U301', '3'), ('U301', '5')], 0.2),
    ('AWG_FB', 'F', [('U301', '2'), ('U301', '6')], 0.2),
]
PREEND = [('+3V3A', (47.5, 6.0)), ('+3V3A', (52.0, 19.5))]
PREVIA = [('GND', (25.6, 6.95)), ('GND', (21.6, 6.95))]
PSEUDO_PRE = False                  # True gives every hand-drawn Kelvin branch its own pseudo net in the router (tried: it closes the source pads in, see README)
STAR_HAND = {'+3V3A'}               # nets whose star point is drawn by hand above
BRIDGE_PADS = [('BR101', '1', 'BR101', '2')]
# ------------------------------------------------------------------------------------------ silk outlines (LR-11)
# block -> rectangles (x0, y0, x1, y1) in Due coordinates; a block may be several rectangles
OUTLINE.update({
    'POWER': [(17.9, 4.6, 43.6, 26.0)],
    'REFCAL': [(44.2, 4.6, 64.4, 27.8), (64.6, 18.6, 70.2, 26.0), (48.9, 31.6, 54.2, 34.9)],
    'CH1': [(98.5, 34.0, 116.4, 50.0), (77.6, 34.0, 93.0, 47.3), (73.9, 36.6, 76.9, 40.0), (63.9, 30.6, 76.4, 36.6),
            (60.4, 34.6, 64.0, 36.8), (63.0, 28.8, 65.5, 30.3)],
    'CH2': [(98.5, 16.5, 116.4, 32.0), (77.6, 19.0, 93.0, 32.0), (67.4, 25.6, 76.3, 29.9), (70.4, 21.2, 72.4, 23.2)],
    'AWG': [(98.5, 0.6, 116.4, 13.5), (69.6, 4.4, 92.4, 19.4)],
})
LABEL.update({'POWER': (18.3, 24.0), 'REFCAL': (44.6, 27.2), 'CH1': (77.8, 46.6), 'CH2': (77.8, 31.4), 'AWG': (70.0, 18.8)})
LABELS = [('CH1 IN', 98.8, 44.4), ('CH2 IN', 98.8, 26.6), ('AWG OUT', 98.8, 9.4),
          ('CAL', 45.6, 14.4), ('ON', 46.0, 10.6)]
ARROWS = [((92.8, 40.3), (84.0, 40.3)), ((92.8, 22.5), (84.0, 22.5)), ((72.5, 40.5), (68.0, 40.5)),
          ((91.0, 4.6), (87.0, 4.6)), ((20.5, 4.2), (24.0, 4.2))]

# MH602 (90.17, 50.8): screw optional, verify socket clearance.  Head keepout radius 2.25 mm (M2.5 DIN 912, 4.5 mm head).
# Nearest socket pins J607.8 (86.36, 50.8) and J605.1 (93.98, 50.8) are 3.81 mm from the hole centre.  A standard 2.54 mm
# female housing edge is about 1.27 mm from a pin centreline (check): pin centre to head keepout = 3.81 - 2.25 = 1.56 mm
# >= 1.27 + 0.2, so it clears sideways; but the housing END face lies 1.27 mm beyond the last pin along the row, so the
# head-to-housing-end gap is 3.81 - 1.27 - 2.25 = 0.29 mm (check, housing drawing not in the repository).  The 2
# courtyard items against J605 / J607 stay documented for that reason.  Silk note to add on the next rebuild:
# "MH602: screw optional, verify socket clearance".
