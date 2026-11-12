"""Hand placement of the AFE shield (FR-02): every part's position and rotation, chosen from its pinout.

Due coordinates (mm): x right, Yup up, origin the Due's lower-left corner; rotation in degrees counter-clockwise,
KiCad's convention.  Rotating an 0603 by 90 puts pin 1 at the bottom, by 270 at the top, by 180 on the right.
A SOT-23-5 op-amp at 90 has OUT, V-, +IN along its bottom edge (left to right) and V+, -IN along its top edge.

How the blocks are laid out, and why:
- Scope channels (CH1 row at Yup 41.91, CH2 at 24.13): the input enters from its BNC between two rows of unused XIO
  pins, straight along the row: R101's three parts, then the N node, then Rnp, then the op-amp's +IN, all on one
  line.  C101 rides above the chain from IN to N.  Below N, the parts from N to the channel's Vmid (R201 and the four
  C201 capacitors) stand in a row with N at their tops and Vmid at their bottoms, and R3's chain leaves N to the
  left toward the 3.3 V sense node.  RF sits across the op-amp's top (OUT under the body to RF, -IN up to RF),
  the range switch above RF with S1 / D facing it, and RG beside -IN.  The supply branch (1R, 10 uF, 100 nF)
  faces V+ on the left, and Riso with its clamp leaves OUT to the left, toward A0 / A1.
- AWG (output row at Yup 6.35 to J301): DAC0 comes up from ADCH0.5 (x 83.8) into the buffer; the buffer feeds Ra into
  the gain stage's +IN; the gain stage's feedback network stands beside it and the 49.9 ohm goes right to J301.
  The AWG's own Vmid (divider, 12 pF, follower) sits next to Rg, so the 12 pF tap node stays small.
- Power: the LM27762 by the 5V pin (x 38.1), flying capacitor on C101+ / C101-, the charge-pump and output
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
# D18: each channel is a unity follower.  The two share one TPH2502 (U101, SOIC-8) at 90 degrees in the strip between
# their input rows: its south pads 1 OUT / 2 -IN / 3 +IN / 4 GND are CH2's, its north pads 8 V+ / 7 OUT / 6 -IN / 5 +IN
# CH1's, OUT at the west end and +IN at the east end of each (-IN and OUT are neighbours, so the follower's link is one
# short trace).  Pads (Due coordinates): south row y 30.545, north row y 35.495, x 74.095 / 75.365 / 76.635 / 77.905.
# Each channel is one line from its BNC west along its row (R101's three parts, N, Rnp), then up (CH2) or down (CH1) to +IN;
# the N-side parts (R201, C201 to the channel's Vmid, and R3's chain to the 3.3 V sense node) hang on the strip side of the
# row, and OUT leaves west through Riso and the pin clamp toward A0 / A1.
Y1, Y2 = 44.45, 24.13                           # the two input rows (J101, J201), both centres of a gap between XIO pin rows
DUAL = (76.0, (Y1 + Y2) / 2)
put('U101', DUAL[0], DUAL[1], 90)
CHP = dict(CH1=dict(r1=('R102', 'R103'), c1='C101', rnp='R106', r2a='R105', r2b='R101', r3='R104', c2='C102'),
           CH2=dict(r1=('R202', 'R203'), c1='C201', rnp='R206', r2a='R205', r2b='R201', r3='R204', c2='C202'))
# The N-side parts (R201 = two resistors to GND, R3 to VREF, C201 to GND) stand on the FAR side of the row from the dual, so
# that VREF reaches R3 from outside the strip (CH1: along the top of the board above J605's pin pads; CH2: from the south);
# C101 and Cnp are on the dual's side.
for ch, y0, f in (('CH1', Y1, +1), ('CH2', Y2, -1)):
    c = CHP[ch]
    put(c['r1'][0], 90.3, y0, 180)              # R101 = 470k, 300k: pin 1 toward the BNC
    put(c['r1'][1], 86.9, y0, 180)
    put(c['rnp'], 80.1, y0, 180)                # N on its right, NP on its left
    put(c['c1'], 88.8, y0 - 1.9 * f, 0)         # C101: IN (right) .. N, on the dual's side
    rn = 90 if f > 0 else 270                   # pin 1 (N, or R2A) toward the row
    ro = 270 if f > 0 else 90                   # R2b: pin 1 (R2A) at the far end
    put(c['r2a'], 80.8, y0 + 2.0 * f, rn)
    put(c['r2b'], 82.4, y0 + 2.0 * f, ro)
    put(c['r3'], 84.0, y0 + 2.0 * f, rn)
    put(c['c2'], 85.6, y0 + 2.0 * f, rn)
dy = DUAL[1]
# CH2 (south): +IN is pin 3, OUT pin 1; CH1 (north): +IN is pin 5, OUT pin 7
put('C203', 78.0, dy - 8.0, 270)                 # Cnp: NP to GND, beside the +IN trace
put('C105', 78.0, dy + 8.0, 90)
put('R207', 71.2, dy - 3.0, 180)                 # Riso, OUT toward A0
put('D201', 66.8, dy - 4.0, 0)                    # the ADC-pin clamp
put('R107', 71.2, dy + 3.0, 180)                 # CH1 Riso, OUT toward A1
put('D101', 66.8, dy + 4.0, 0)
# the dual's supply: V+ (pin 8, north-west) 100 nF, 10 uF, 1R in a row to the west; GND is pin 4 (south-east)
put('C103', 72.3, dy, 90)
put('C104', 69.3, dy, 90)
put('R108', 63.2, 33.0, 90)

# --------------------------------------------------------------------------------------------- AWG
# x 66..92, y 3.8..20.3.  One TPH2502 (U301) at 270 degrees: its south row 5 +IN / 6 -IN / 7 OUT / 8 V+ (x 78.1 .. 81.9, y 8.5)
# is the gain stage, facing the DAC0 pin (83.8, 2.54) and with OUT at the east end toward J301; V- (pin 4) is the north row's
# west end, and the spare half (pins 1-3, the north row) is tied off with short stubs.
put('U301', 80.0, 12.0, 270)
put('R305', 83.2, 6.0, 90)                       # Rbin: DAC0 (bottom) .. BIN (top)
put('C304', 85.0, 6.0, 90)                       # Cbin across it
put('R308', 75.6, 6.8, 180)                        # Rbpl, part 1 (BIN .. BPL)
put('R301', 72.8, 6.8, 180)                        # Rbpl, part 2 (BPL .. GND)
put('R303', 80.0, 6.9, 180)                        # Rf (OUT .. INV)
put('C301', 80.0, 5.1, 180)                         # Cf across Rf
put('R302', 76.0, 9.0, 270)                      # Rg2: INV .. X
put('R307', 73.4, 9.6, 270)                       # offset filter: 100 ohm VREF .. X
put('C305', 71.4, 9.6, 90)
put('C306', 69.6, 9.6, 90)
put('C302', 84.0, 10.4, 90)                      # V+ pin
put('C303', 76.2, 14.6, 270)                      # V- pin
put('R304', 88.2, 9.6, 90)                       # 2 x 100 ohm 1206 in parallel to J301
put('R306', 90.6, 9.6, 90)

# --------------------------------------------------------------------------------------------- power
# LM27762 (rotation 0): left FB+ 2, VIN 3, GND 4, CP 5, OUT- 6 (top to bottom); right FB- 7, EN- 8, C101- 9, C101+ 10,
# OUT+ 11, EN+ 12 (bottom to top).  It sits by the 5V pin (x 38.1), between POWER0 and the ladder.
put('R408', 21.6, 7.6, 90)                       # 1 ohm sense: 5V_DUE (bottom, fed under POWER0 from x 38.1) .. +5V_F rail
put('U401', 33.6, 9.8, 0)
put('C402', 37.2, 9.8, 270)                      # flying capacitor C101+ (top) / C101- (bottom), 1 mm off the pins
put('C401', 30.9, 11.0, 90)                      # VIN 100 nF: its +5V_F pad (bottom) on the rail
put('C409', 30.6, 7.4, 270)                      # OUT- 10 uF at OUT- (pin 6)
put('C405', 28.2, 7.4, 270)                      # CP 10 uF, CP (pin 5) passing over C409
put('C406', 25.8, 7.4, 270)
put('C410', 23.4, 7.4, 270)
put('C403', 27.8, 11.2, 90)                      # 5 V bulk
put('C404', 25.4, 11.2, 90)
put('C407', 39.6, 12.6, 90)                      # OUT+ (+3.3 V_A) pair beyond the flying capacitor
put('C408', 41.8, 12.6, 90)
put('R409', 33.4, 13.8, 180)                     # FB+ divider over FB+ (pin 2): 75k + 100k from OUT+ (R406, R409), 100k to GND (R401)
put('R406', 36.0, 13.8, 180)
put('R401', 30.2, 14.2, 90)
put('R402', 33.6, 7.0, 0)                         # FB- divider under the chip: R3 = 75k from OUT- (left)
put('R403', 36.8, 6.6, 90)
put('R404', 38.6, 6.6, 90)
put('R405', 42.4, 7.0, 90)
put('R407', 33.0, 16.6, 0)                       # +3.3 V_A bleed
for k, (x, y) in enumerate(((19.6, 6.4), (19.6, 10.0), (20.6, 19.2), (23.4, 19.2), (26.2, 19.2)), 1):
    put(f'TP{400 + k}', x, y)

# LM27762 fan-out, drawn by hand (the router's grid cannot see 0.5 mm pitch this tightly):
# - +5V_F rail on F.Cu straight left from VIN (pin 3) along Yup 10.15 through C401, C403, C404 and TP402 (their +5V_F
#   pads sit on it), R408 at its left end;
# - EN+ (pin 12, top-right) and EN- (pin 8) each to a via, joined to the rail on B.Cu around the thermal pad;
# - FB+ (pin 2) diagonally up-left over the rail to R406, OUT+ (pin 11) diagonally up-right over the flying
#   capacitor's fan to C407.
PREROUTE = [
    ('+5V_F', 'F', [(32.4, 10.05), (31.5, 10.15), (24.9, 10.15)], 0.3),
    ('+5V_F', 'F', [(34.55, 11.05), (34.55, 11.95)], 0.2),
    ('+5V_F', 'F', [(34.8, 9.05), (35.0, 9.05), (35.7, 8.35), (35.7, 7.6)], 0.2),
    ('+5V_F', 'B', [(34.55, 11.95), (35.7, 11.6), (35.7, 7.6), (29.6, 7.6), (29.6, 10.15)], 0.3),
    ('LM_FBP', 'F', [(32.4, 10.55), (32.0, 10.55), (31.8, 10.75), (31.8, 13.8), (32.4, 13.8)], 0.2),
    ('+3V3A', 'F', [(34.8, 10.55), (35.2, 10.55), (35.5, 10.85), (35.5, 11.5)], 0.2),
    ('+3V3A', 'F', [(35.5, 11.5), (35.5, 12.6), (39.0, 12.6), (39.6, 12.0)], 0.3),
    ('GND', 'F', [(32.9, 9.55), (33.25, 9.55)], 0.25),          # GND pins 4 and 1 strapped to the thermal pad
    ('VNEG', 'F', [(32.4, 8.55), (31.4, 8.55), (30.6, 8.75)], 0.3),       # OUT- (pin 6) to its 10 uF (C409 top pad)
    ('VNEG', 'F', [(32.65, 8.425), (32.775, 7.6)], 0.2),                  # ... and down to the R3 pair's OUT- pads
    ('VNEG', 'F', [(32.775, 6.5), (32.775, 5.6)], 0.2),
    ('LM_CP', 'F', [(32.4, 9.05), (31.7, 9.05), (31.45, 9.3), (29.0, 9.3), (28.2, 8.85)], 0.25),   # CP (pin 5) over C409 to its 10 uF
    ('GND', 'F', [(32.9, 11.05), (33.25, 11.0)], 0.25),
]
PREVIA = [('+5V_F', 34.55, 11.95), ('+5V_F', 35.7, 7.6), ('+5V_F', 29.6, 10.15)]
# 5 V from the POWER0 5V pin (x 38.1) along under the socket (Yup 4.0) to the 1 ohm sense resistor
PREROUTE += [('+5V_DUE', 'F', [(38.1, 3.2), (38.1, 4.0), (22.2, 4.0), (21.6, 4.6), (21.6, 6.4)], 0.4)]
# --------------------------------------------------------------------------------------------- floorplan (docs: floorplan_table.md)
# The routes below the LM27762 fan-out are the blocks' own work (each block agent draws its fence's copper); the integrator draws
# the contract nets between fences.  Nothing here is hand-routed except the power block's fan-out above and the 5 V trunk.

# A1 / A0: down x 66.04 / x 68.58 from the clamps to the J602 pads (SCOPE's); bridges straddle them in the wall corridor
# --------------------------------------------------------------------------------------------- calibration / REFCAL
# ladder right above A7 .. A2 (x 50.80 .. 63.50): one series resistor per header pitch, in two staggered rows (A at Yup 6.0,
# B at 8.2), so every tap drops straight onto its pin
put('R508', 52.07, 6.0, 180)
put('R507', 54.61, 8.2, 180)
put('R506', 57.15, 6.0, 180)
put('R505', 59.69, 8.2, 180)
put('R504', 62.23, 6.0, 180)
put('R503', 63.05, 8.8, 90)                     # the bottom 100 ohm, TAP1 (pin 1) down on the A2 side, GND up
put('U501', 52.0, 16.0, 0)                      # REF3030: pins 1 VIN, 2 OUT (west), 3 GND; >= 13 mm from C402 (LR-5)
put('C501', 50.2, 17.6, 90)
put('C505', 50.2, 14.4, 90)
put('C503', 54.0, 13.2, 90)
put('C504', 52.4, 12.4, 90)
put('R510', 49.6, 21.0, 0)                      # unfitted 0R to AREF
put('TP501', 54.0, 11.0)
put('J501', 56.54, 12.6, 90)                    # the ratio jumper: TAP4 | B | TAP3, directly above the ladder
put('U502', 58.5, 17.8, 0)                      # ADS1115
put('C502', 61.9, 17.8, 90)
put('R509', 60.0, 21.2, 0)
put('R511', 62.4, 21.2, 0)
put('R501', 52.4, 19.6, 0)
put('R502', 52.4, 23.0, 0)
put('R512', 50.4, 10.6, 0)
put('R513', 55.2, 20.0, 0)
put('R514', 55.2, 23.0, 0)
put('D502', 58.0, 25.0, 0)
put('D501', 61.0, 25.0, 0)
# the wall bridges, each straddling its A line: VREF to CH2 (REFCAL's, rows y 22.8 / 24.5), AWG_BNC sense (AWG's, y 19.5 / 21.1),
# the scope's +3V3A (SCOPE's, y 35.7); a 0603 straddles one line, its pads at +- 0.82 mm
put('R515', 66.04, 22.8, 0)
put('R516', 68.58, 24.5, 0)
put('R309', 66.04, 19.5, 0)
put('R310', 68.58, 21.1, 0)
put('R109', 62.8, 35.7, 0)
put('R110', 66.04, 35.7, 0)

# test points on the three nodes that had none (LR-11): A1 and A0 on their own columns, AWG_OUT before R304/R306
put('TP101', 66.04, 40.8)
put('TP201', 69.9, 26.2)
put('TP301', 86.2, 12.6)

# REFCAL's three bridges over a VREF leg (the block agent places them where its legs run)
put('R517', 56.0, 29.0, 0)
put('R518', 58.4, 29.0, 0)
put('R519', 60.8, 29.0, 0)
put('R410', 39.9, 6.6, 90)                  # POWER's VNEG link over the +5V_F column (position from the POWER agent)
