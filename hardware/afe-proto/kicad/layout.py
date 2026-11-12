"""Hand placement of the AFE shield (FR-02): every part's position and rotation, chosen from its pinout.

Due coordinates (mm): x right, Yup up, origin the Due's lower-left corner; rotation in degrees counter-clockwise,
KiCad's convention.  Rotating an 0603 by 90 puts pin 1 at the bottom, by 270 at the top, by 180 on the right.
A SOT-23-5 op-amp at 90 has OUT, V-, +IN along its bottom edge (left to right) and V+, -IN along its top edge.

How the blocks are laid out, and why:
- Scope channels (CH1 row at Yup 41.91, CH2 at 24.13): the input enters from its BNC between two rows of unused XIO
  pins, straight along the row: R1's three parts, then the N node, then Rnp, then the op-amp's +IN, all on one
  line.  C1 rides above the chain from IN to N.  Below N, the parts from N to the channel's Vmid (R2 and the four
  C2 capacitors) stand in a row with N at their tops and Vmid at their bottoms, and R3's chain leaves N to the
  left toward the 3.3 V sense node.  RF sits across the op-amp's top (OUT under the body to RF, -IN up to RF),
  the range switch above RF with S1 / D facing it, and RG beside -IN.  The supply branch (1R, 10 uF, 100 nF)
  faces V+ on the left, and Riso with its clamp leaves OUT to the left, toward A0 / A1.
- AWG (output row at Yup 6.35 to J3): DAC0 comes up from ADCH0.5 (x 83.8) into the buffer; the buffer feeds Ra into
  the gain stage's +IN; the gain stage's feedback network stands beside it and the 49.9 ohm goes right to J3.
  The AWG's own Vmid (divider, 12 pF, follower) sits next to Rg, so the 12 pF tap node stays small.
- Power: the LM27762 by the 5V pin (x 38.1), flying capacitor on C1+ / C1-, the charge-pump and output
  capacitors on their pins, both feedback dividers on FB+ / FB-.
- Calibration: the ladder directly above A2..A7 (x 50.8..63.5, a tap per header pin), the REF3030 at its top end,
  the ADS124S08 above the ladder with its six tap inputs (AIN0..5, pins 7..2) facing the ladder.
- Scope Vmid: the TLV9062 between the two channels' loops; each loop's 6 x 10 uF sits at the end nearest its
  channel.
"""

PLACE = {}


def put(ref, x, y, rot=0):
    PLACE[ref] = (round(x, 3), round(y, 3), rot % 360)


# --------------------------------------------------------------------------------------------- scope channels
# D18: each channel is a unity follower.  The two share one TPH2502 (U1, SOIC-8) at 90 degrees in the strip between
# their input rows: its south pads 1 OUT / 2 -IN / 3 +IN / 4 GND are CH2's, its north pads 8 V+ / 7 OUT / 6 -IN / 5 +IN
# CH1's, OUT at the west end and +IN at the east end of each (-IN and OUT are neighbours, so the follower's link is one
# short trace).  Pads (Due coordinates): south row y 30.545, north row y 35.495, x 74.095 / 75.365 / 76.635 / 77.905.
# Each channel is one line from its BNC west along its row (R1's three parts, N, Rnp), then up (CH2) or down (CH1) to +IN;
# the N-side parts (R2, C2 to the channel's Vmid, and R3's chain to the 3.3 V sense node) hang on the strip side of the
# row, and OUT leaves west through Riso and the pin clamp toward A0 / A1.
Y1, Y2 = 44.45, 24.13                           # the two input rows (J1, J2), both centres of a gap between XIO pin rows
DUAL = (76.0, (Y1 + Y2) / 2)
put('U1', DUAL[0], DUAL[1], 90)
CHP = dict(CH1=dict(r1=('R10', 'R11'), c1='C1', rnp='R52', r2a='R18', r2b='R1', r3='R14', c2='C9'),
           CH2=dict(r1=('R12', 'R13'), c1='C2', rnp='R53', r2a='R19', r2b='R2', r3='R16', c2='C11'))
# The N-side parts (R2 = two resistors to GND, R3 to VREF, C2 to GND) stand on the FAR side of the row from the dual, so
# that VREF reaches R3 from outside the strip (CH1: along the top of the board above J8's pin pads; CH2: from the south);
# C1 and Cnp are on the dual's side.
for ch, y0, f in (('CH1', Y1, +1), ('CH2', Y2, -1)):
    c = CHP[ch]
    put(c['r1'][0], 90.3, y0, 180)              # R1 = 470k, 300k: pin 1 toward the BNC
    put(c['r1'][1], 86.9, y0, 180)
    put(c['rnp'], 80.1, y0, 180)                # N on its right, NP on its left
    put(c['c1'], 88.8, y0 - 1.9 * f, 0)         # C1: IN (right) .. N, on the dual's side
    rn = 90 if f > 0 else 270                   # pin 1 (N, or R2A) toward the row
    ro = 270 if f > 0 else 90                   # R2b: pin 1 (R2A) at the far end
    put(c['r2a'], 80.8, y0 + 2.0 * f, rn)
    put(c['r2b'], 82.4, y0 + 2.0 * f, ro)
    put(c['r3'], 84.0, y0 + 2.0 * f, rn)
    put(c['c2'], 85.6, y0 + 2.0 * f, rn)
dy = DUAL[1]
# CH2 (south): +IN is pin 3, OUT pin 1; CH1 (north): +IN is pin 5, OUT pin 7
put('C61', 78.0, dy - 8.0, 270)                 # Cnp: NP to GND, beside the +IN trace
put('C60', 78.0, dy + 8.0, 90)
put('R56', 71.2, dy - 3.0, 180)                 # Riso, OUT toward A0
put('D6', 66.8, dy - 4.0, 0)                    # the ADC-pin clamp
put('R55', 71.2, dy + 3.0, 180)                 # CH1 Riso, OUT toward A1
put('D5', 66.8, dy + 4.0, 0)
# the dual's supply: V+ (pin 8, north-west) 100 nF, 10 uF, 1R in a row to the west; GND is pin 4 (south-east)
put('C13', 72.3, dy, 90)
put('C44', 69.3, dy, 90)
put('R71', 66.5, dy, 90)

# --------------------------------------------------------------------------------------------- AWG
# x 66..92, y 3.8..20.3.  One TPH2502 (U3) at 270 degrees: its south row 5 +IN / 6 -IN / 7 OUT / 8 V+ (x 78.1 .. 81.9, y 8.5)
# is the gain stage, facing the DAC0 pin (83.8, 2.54) and with OUT at the east end toward J3; V- (pin 4) is the north row's
# west end, and the spare half (pins 1-3, the north row) is tied off with short stubs.
put('U3', 80.0, 12.0, 270)
put('R54', 83.2, 6.0, 90)                       # Rbin: DAC0 (bottom) .. BIN (top)
put('C63', 85.0, 6.0, 90)                       # Cbin across it
put('R94', 75.6, 6.8, 180)                        # Rbpl, part 1 (BIN .. BPL)
put('R22', 72.8, 6.8, 180)                        # Rbpl, part 2 (BPL .. GND)
put('R35', 80.0, 6.9, 180)                        # Rf (OUT .. INV)
put('C7', 80.0, 5.1, 180)                         # Cf across Rf
put('R33', 76.0, 9.0, 270)                      # Rg2: INV .. X
put('R93', 73.4, 9.6, 270)                       # offset filter: 100 ohm VREF .. X
put('C64', 71.4, 9.6, 90)
put('C65', 69.6, 9.6, 90)
put('C21', 84.0, 10.4, 90)                      # V+ pin
put('C22', 76.2, 14.6, 270)                      # V- pin
put('R51', 88.2, 9.6, 90)                       # 2 x 100 ohm 1206 in parallel to J3
put('R88', 90.6, 9.6, 90)

# --------------------------------------------------------------------------------------------- power
# LM27762 (rotation 0): left FB+ 2, VIN 3, GND 4, CP 5, OUT- 6 (top to bottom); right FB- 7, EN- 8, C1- 9, C1+ 10,
# OUT+ 11, EN+ 12 (bottom to top).  It sits by the 5V pin (x 38.1), between POWER0 and the ladder.
put('R70', 21.6, 7.6, 90)                       # 1 ohm sense: 5V_DUE (bottom, fed under POWER0 from x 38.1) .. +5V_F rail
put('U7', 33.6, 9.8, 0)
put('C31', 37.2, 9.8, 270)                      # flying capacitor C1+ (top) / C1- (bottom), 1 mm off the pins
put('C23', 30.9, 11.0, 90)                      # VIN 100 nF: its +5V_F pad (bottom) on the rail
put('C42', 30.6, 7.4, 270)                      # OUT- 10 uF at OUT- (pin 6)
put('C38', 28.2, 7.4, 270)                      # CP 10 uF, CP (pin 5) passing over C42
put('C39', 25.8, 7.4, 270)
put('C43', 23.4, 7.4, 270)
put('C36', 27.8, 11.2, 90)                      # 5 V bulk
put('C37', 25.4, 11.2, 90)
put('C40', 39.6, 12.6, 90)                      # OUT+ (+3.3 V_A) pair beyond the flying capacitor
put('C41', 41.8, 12.6, 90)
put('R83', 33.4, 13.8, 180)                     # FB+ divider over FB+ (pin 2): 75k + 100k from OUT+ (R29, R83), 100k to GND (R5)
put('R29', 36.0, 13.8, 180)
put('R5', 30.2, 14.2, 90)
put('R6', 33.6, 7.0, 0)                         # FB- divider under the chip: R3 = 75k from OUT- (left)
put('R26', 36.8, 6.6, 90)
put('R27', 38.6, 6.6, 90)
put('R28', 42.4, 7.0, 90)
put('R65', 33.0, 16.6, 0)                       # +3.3 V_A bleed
for k, (x, y) in enumerate(((19.6, 6.4), (19.6, 10.0), (20.6, 19.2), (23.4, 19.2), (26.2, 19.2)), 1):
    put(f'TP{k}', x, y)

# LM27762 fan-out, drawn by hand (the router's grid cannot see 0.5 mm pitch this tightly):
# - +5V_F rail on F.Cu straight left from VIN (pin 3) along Yup 10.15 through C23, C36, C37 and TP2 (their +5V_F
#   pads sit on it), R70 at its left end;
# - EN+ (pin 12, top-right) and EN- (pin 8) each to a via, joined to the rail on B.Cu around the thermal pad;
# - FB+ (pin 2) diagonally up-left over the rail to R29, OUT+ (pin 11) diagonally up-right over the flying
#   capacitor's fan to C40.
PREROUTE = [
    ('+5V_F', 'F', [(32.4, 10.05), (31.5, 10.15), (24.9, 10.15)], 0.3),
    ('+5V_F', 'F', [(34.55, 11.05), (34.55, 11.95)], 0.2),
    ('+5V_F', 'F', [(34.8, 9.05), (35.0, 9.05), (35.7, 8.35), (35.7, 7.6)], 0.2),
    ('+5V_F', 'B', [(34.55, 11.95), (35.7, 11.6), (35.7, 7.6), (29.6, 7.6), (29.6, 10.15)], 0.3),
    ('LM_FBP', 'F', [(32.4, 10.55), (32.0, 10.55), (31.8, 10.75), (31.8, 13.8), (32.4, 13.8)], 0.2),
    ('+3V3A', 'F', [(34.8, 10.55), (35.2, 10.55), (35.5, 10.85), (35.5, 11.5)], 0.2),
    ('+3V3A', 'F', [(35.5, 11.5), (35.5, 12.6), (39.0, 12.6), (39.6, 12.0)], 0.3),
    ('GND', 'F', [(32.9, 9.55), (33.25, 9.55)], 0.25),          # GND pins 4 and 1 strapped to the thermal pad
    ('VNEG', 'F', [(32.4, 8.55), (31.4, 8.55), (30.6, 8.75)], 0.3),       # OUT- (pin 6) to its 10 uF (C42 top pad)
    ('VNEG', 'F', [(32.65, 8.425), (32.775, 7.6)], 0.2),                  # ... and down to the R3 pair's OUT- pads
    ('VNEG', 'F', [(32.775, 6.5), (32.775, 5.6)], 0.2),
    ('LM_CP', 'F', [(32.4, 9.05), (31.7, 9.05), (31.45, 9.3), (29.0, 9.3), (28.2, 8.85)], 0.25),   # CP (pin 5) over C42 to its 10 uF
    ('GND', 'F', [(32.9, 11.05), (33.25, 11.0)], 0.25),
]
PREVIA = [('+5V_F', 34.55, 11.95), ('+5V_F', 35.7, 7.6), ('+5V_F', 29.6, 10.15)]
# 5 V from the POWER0 5V pin (x 38.1) along under the socket (Yup 4.0) to the 1 ohm sense resistor
PREROUTE += [('+5V_DUE', 'F', [(38.1, 3.2), (38.1, 4.0), (22.2, 4.0), (21.6, 4.6), (21.6, 6.4)], 0.4)]
# A1 and A0: the two walls, drawn by hand on F.Cu from the Due header pins straight up to their clamps; the 0 ohm bridges R95 / R96
# carry +3V3A over them (their pads straddle x 63.85 and x 65.6)
PREROUTE += [
    ('A1', 'F', [(66.04, 2.54), (66.04, 4.0), (63.85, 6.2), (63.85, 38.29), ('pad', 'D5', 3)], 0.25),
    ('A0', 'F', [(68.58, 2.54), (68.58, 6.8), (64.8, 10.6), (64.8, 30.29), ('pad', 'D6', 3)], 0.25),
]
# the AWG's gain stage by hand (the pins read 5 BIN / 6 INV / 7 OUT / 8 V+ from the west): BIN down the west side of the stage to the
# input divider and east below it to Rbin; INV down to Rf/Cf, with its one bottom hop under the BIN stub to Rg2; OUT down to Rf/Cf
PREROUTE += [
    ('AWG_BIN', 'F', [(78.09, 9.53), (78.09, 6.8), ('pad', 'R94', 1)], 0.25),
    ('AWG_BIN', 'F', [(78.09, 6.8), (78.09, 4.0), (82.3, 4.0), (82.3, 6.82), ('pad', 'R54', 2)], 0.25),
    ('AWG_INV', 'F', [(79.37, 9.53), (79.37, 8.0), (78.9, 8.0)], 0.25),
    ('AWG_INV', 'F', [(79.37, 8.0), (79.18, 7.4), ('pad', 'R35', 2)], 0.25),
    ('AWG_INV', 'B', [(78.9, 8.0), (77.3, 8.0)], 0.25),
    ('AWG_INV', 'F', [(77.3, 8.0), (77.3, 9.82), ('pad', 'R33', 1)], 0.25),
    ('AWG_OUT', 'F', [(80.65, 9.53), (80.65, 8.1), (80.82, 7.4), ('pad', 'R35', 1)], 0.25),
]
PREROUTE += [
    ('DAC0', 'F', [('pad', 'J6', 5), (83.82, 3.8), (83.2, 4.4), ('pad', 'R54', 1)], 0.25),
    ('AWG_OUT', 'F', [(80.65, 8.1), (81.4, 7.8), (86.8, 7.8), ('pad', 'R51', 1)], 0.25),
    ('AWG_OUT', 'F', [('pad', 'R51', 1), ('pad', 'R88', 1)], 0.25),
    ('AWG_BNC', 'F', [('pad', 'R51', 2), (88.2, 18.1), (85.6, 18.1)], 0.25),
    ('AWG_BNC', 'B', [(85.6, 18.1), (83.6, 18.1)], 0.25),
    ('AWG_BNC', 'F', [(83.6, 18.1), (67.0, 18.1), ('pad', 'R97', 2)], 0.25),
    ('CH1_OUT', 'F', [('pad', 'R55', 1), (72.03, 38.4), (75.36, 38.4), ('pad', 'U1', 7)], 0.25),
    ('CH1_OUT', 'F', [('pad', 'U1', 6), ('pad', 'U1', 7)], 0.25),
    ('VNEG_E', 'F', [('pad', 'R99', 2), (66.9, 11.4), (66.9, 13.3)], 0.25),
    ('VNEG_E', 'B', [(66.9, 13.3), (66.9, 15.3)], 0.25),
    ('VNEG_E', 'F', [(66.9, 15.3), (66.9, 15.4), (75.4, 15.4), ('pad', 'C22', 1)], 0.25),
    ('VNEG_E', 'F', [('pad', 'C22', 1), (77.2, 15.38), (77.2, 14.47), ('pad', 'U3', 4)], 0.25),
    ('VNEG', 'F', [(32.775, 5.6), (33.4, 4.6), (43.5, 4.6), (43.5, 10.2), (44.0, 10.2), (52.6, 10.2)], 0.25),
    ('VNEG', 'B', [(52.6, 10.2), (55.0, 10.2)], 0.25),
    ('VNEG', 'F', [(55.0, 10.2), (59.4, 10.2)], 0.25),
    ('VNEG', 'B', [(59.4, 10.2), (61.4, 10.2)], 0.25),
    ('VNEG', 'F', [(61.4, 10.2), (61.9, 11.4), ('pad', 'R99', 1)], 0.25),
    ('AWG_BNC', 'F', [('pad', 'R51', 2), ('pad', 'R88', 2)], 0.25),
    ('VREF_X', 'F', [('pad', 'R98', 2), (67.8, 14.3), (67.8, 12.5), (73.4, 12.5), ('pad', 'R93', 1)], 0.25),
    ('VREF_X', 'F', [(73.4, 12.5), (82.2, 12.5)], 0.25),
    ('VREF_X', 'B', [(82.2, 12.5), (83.8, 12.5)], 0.25),
    ('VREF_X', 'F', [(83.8, 12.5), (84.6, 12.5), (84.6, 20.4), (84.0, 20.4), ('pad', 'R16', 2)], 0.25),
    ('+3V3A_E', 'F', [('pad', 'R95', 2), (66.9, 17.1), (83.0, 17.1), (83.0, 9.55), ('pad', 'U3', 8)], 0.25),
    ('+3V3A_E', 'F', [(83.0, 9.55), ('pad', 'C21', 1)], 0.25),
    ('AWG_X', 'F', [('pad', 'R33', 2), (74.6, 8.32), (74.6, 8.78), ('pad', 'R93', 2)], 0.25),
]
PREROUTE += [
    ('A1', 'F', [('pad', 'D5', 3), (69.2, 38.29), (69.2, 37.29), ('pad', 'R55', 2)], 0.25),
    ('A0', 'F', [('pad', 'D6', 3), (69.2, 30.29), (69.2, 31.29), ('pad', 'R56', 2)], 0.25),
    ('SC_VCC', 'F', [('pad', 'R71', 2), (67.9, 35.11), (67.9, 33.34), ('pad', 'C44', 1)], 0.25),
    ('CH2_N', 'F', [('pad', 'R19', 1), ('pad', 'R53', 1)], 0.25),
    ('CH2_N', 'F', [('pad', 'R16', 1), (84.0, 24.4), (81.5, 24.4), ('pad', 'R53', 1)], 0.25),
    ('TAP4', 'F', [('pad', 'R49', 1), (53.78, 10.0), (53.78, 26.5), (46.0, 26.5), ('pad', 'J11', 1)], 0.25),
    ('TAP3', 'F', [('pad', 'R47', 2), (60.52, 10.0), (60.52, 27.5), (51.08, 27.5), ('pad', 'J11', 3)], 0.25),
    ('TAP3', 'F', [('pad', 'J11', 3), (51.08, 32.6), (47.85, 32.6), (47.85, 38.4), ('pad', 'U9', 5)], 0.25),
]
PREROUTE += [
    ('+3V3A', 'F', [(39.6, 12.0), (40.7, 12.0), (40.7, 19.0), (52.6, 19.0)], 0.3),
    ('+3V3A', 'B', [(52.6, 19.0), (55.0, 19.0)], 0.3),
    ('+3V3A', 'F', [(55.0, 19.0), (59.4, 19.0)], 0.3),
    ('+3V3A', 'B', [(59.4, 19.0), (61.4, 19.0)], 0.3),
    ('+3V3A', 'F', [(61.4, 19.0), (61.4, 16.7), ('pad', 'R95', 1)], 0.3),
    ('VREF', 'F', [('pad', 'TP6', 1), (51.8, 17.0), (51.8, 14.6), (52.6, 14.6)], 0.25),
    ('VREF', 'B', [(52.6, 14.6), (55.0, 14.6)], 0.25),
    ('VREF', 'F', [(55.0, 14.6), (59.4, 14.6)], 0.25),
    ('VREF', 'B', [(59.4, 14.6), (61.4, 14.6)], 0.25),
    ('VREF', 'F', [(61.4, 14.6), (61.4, 14.3), ('pad', 'R98', 1)], 0.25),
]
PREROUTE += [
    ('SC_VCC', 'F', [('pad', 'C44', 1), (70.8, 33.3), ('pad', 'C13', 1)], 0.25),
    ('SC_VCC', 'F', [('pad', 'C13', 1), (73.2, 33.52), (73.2, 36.77), ('pad', 'U1', 8)], 0.25),
    ('AWG_S', 'F', [('pad', 'R97', 1), (62.84, 20.4), (62.2, 20.4), (62.2, 29.5), (54.78, 29.5), ('pad', 'R7', 1)], 0.25),
]
PREROUTE += [
    ('CH1_NP', 'F', [('pad', 'C60', 1), (77.95, 38.0), ('pad', 'U1', 5)], 0.25),
    ('CH2_NP', 'F', [('pad', 'C61', 1), (79.28, 27.28), (79.28, 24.7), ('pad', 'R53', 2)], 0.25),
    ('CH2_NP', 'F', [('pad', 'C61', 1), (78.0, 28.6), (76.64, 29.6), (76.64, 31.3), ('pad', 'U1', 3)], 0.25),
]
PREVIA += [('+3V3A', 52.6, 19.0), ('+3V3A', 55.0, 19.0), ('+3V3A', 59.4, 19.0), ('+3V3A', 61.4, 19.0),
           ('VREF', 52.6, 14.6), ('VREF', 55.0, 14.6), ('VREF', 59.4, 14.6), ('VREF', 61.4, 14.6)]
PREVIA += [('VREF_X', 82.2, 12.5), ('VREF_X', 83.8, 12.5), ('AWG_BNC', 85.6, 18.1), ('AWG_BNC', 83.6, 18.1),
           ('VNEG_E', 66.9, 13.3), ('VNEG_E', 66.9, 15.3), ('VNEG', 52.6, 10.2), ('VNEG', 55.0, 10.2), ('VNEG', 59.4, 10.2), ('VNEG', 61.4, 10.2)]
PREVIA += [('AWG_INV', 78.9, 8.0), ('AWG_INV', 77.3, 8.0)]
# (A1 / A0, the VREF branch to the ratio switch and AWG Vmid are routed by route.py; hand routes are added here as needed)

# --------------------------------------------------------------------------------------------- calibration
# ladder right above A7 .. A2 (x 50.80 .. 63.50): one series resistor per header pitch, centred between the two pins it joins,
# in two staggered rows (A at Yup 6.0, B at 8.2), so every tap drops straight onto its pin; the three parallel 270 ohm from TAP1
# to GND standing beside the A2 / A3 taps (x 59..62)
put('R50', 52.07, 6.0, 180)                     # every rung at 180: its higher tap (pin 2) on the west pad, over that tap's header pin
put('R49', 54.61, 8.2, 180)
put('R48', 57.15, 6.0, 180)
put('R47', 59.69, 8.2, 180)
put('R46', 62.23, 6.0, 180)
put('R43', 63.05, 8.8, 90)                      # the bottom 100 ohm, TAP1 (pin 1) down on the A2 side, GND up
put('U8', 48.0, 15.0, 0)                        # REF3030: pins 1 VIN, 2 OUT (left), 3 GND (right)
put('C24', 45.6, 15.6, 90)
put('C32', 45.6, 12.6, 90)
put('C26', 50.4, 12.6, 90)
put('C27', 52.0, 12.6, 90)
put('R81', 44.0, 36.0, 0)                       # unfitted 0R to AREF
put('TP6', 50.4, 17.0)
# the ratio jumper (a 1 x 3 header, shunt across pins 2-3): TAP4 | B | TAP3 above the ladder
put('J11', 46.0, 31.0, 90)
# ADS1115 (TSSOP-10, rot 0) above it: west column 1 ADDR / 2 RDY / 3 GND / 4 AIN0 / 5 AIN1 (top to bottom), east column
# 6 AIN2 / 7 AIN3 / 8 VDD / 9 SDA / 10 SCL (bottom to top)
put('U9', 50.0, 40.0, 0)
put('C25', 54.4, 42.6, 90)                      # VDD
put('R69', 53.6, 45.6, 0)                      # SDA pull-up
put('R82', 56.0, 45.6, 0)                      # SCL pull-up
# the sense divider: AWG_BNC .. R7 .. T0 .. R8 .. B, Rd from B to VREF, Rs from T0 to AIN2, Rm from B to AIN3, BAV99 clamps
put('R7', 55.6, 33.6, 0)
put('R8', 52.0, 34.0, 0)
put('R90', 44.6, 42.4, 0)
put('R91', 57.0, 37.8, 0)
put('R92', 57.0, 41.6, 0)
put('D8', 58.8, 35.6, 0)
put('D7', 58.8, 44.0, 0)
# the +3.3 V_A bridges over the A1 (x 63.85) and A0 (x 65.6) lines
put('R97', 64.3, 19.0, 0)                        # BR3: 1206, pads straddling both A lines
put('R95', 64.3, 16.7, 0)
put('R98', 64.3, 14.3, 0)
put('R99', 64.3, 11.4, 0)

# LR-1: no signal track on B.Cu under the analog blocks (route.py and lr_check.py read this): the calibration block and
# ladder west of the A0 / A1 corridor, the corridor itself above y 27, and the channels, strip and AWG east of it
_NB = [(41.0, 3.8, 64.6, 27.0), (63.0, 27.0, 64.6, 49.5), (64.6, 3.8, 92.6, 49.5)]
# the bottom hops, each <= 3 mm and listed in the hop table: INV under the BIN stub in the AWG, and +3V3A / VREF under the two TAP
# lines (x 53.8 and x 60.5) on their way to the bridges.  (x0, y0, x1, y1), carved out of the no-bottom zone
HOPS = [(52.4, 9.8, 55.2, 10.6), (59.2, 9.8, 61.8, 10.6), (66.5, 12.9, 67.3, 15.7), (82.0, 12.1, 84.0, 12.9), (83.4, 17.7, 86.0, 18.5), (76.5, 7.0, 79.5, 8.6), (52.4, 18.6, 55.2, 19.4), (59.2, 18.6, 62.0, 19.4), (52.4, 14.2, 55.2, 15.0), (59.2, 14.2, 61.6, 15.0)]


def _carve(rects, h):
    out = []
    for (a, b, c, d) in rects:
        if h[0] >= c or h[2] <= a or h[1] >= d or h[3] <= b:
            out.append((a, b, c, d)); continue
        if b < h[1]: out.append((a, b, c, h[1]))
        if d > h[3]: out.append((a, h[3], c, d))
        lo, hi = max(a, h[0]), min(c, h[2]); y0, y1 = max(b, h[1]), min(d, h[3])
        if a < lo: out.append((a, y0, lo, y1))
        if c > hi: out.append((hi, y0, c, y1))
    return out


NOBOTTOM = _NB
for _h in HOPS:
    NOBOTTOM = _carve(NOBOTTOM, _h)
