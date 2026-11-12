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
CH = {  # ref names per channel, same order as design.SC
    'CH1': dict(y0=41.91, r1=('R10', 'R11', 'R1'), c1='C1', rnp='R52', u='U1', rf='R30', sw='U10', rg='R36',
                csw='C28', rpd='R66', cpin='C13', c10='C44', rsup='R71', riso='R55', dk='D5',
                nside=('R14', 'R18', 'C9', 'C3', 'C4'), c2t='C10', r3=('R15', 'R3')),
    'CH2': dict(y0=24.13, r1=('R12', 'R13', 'R2'), c1='C2', rnp='R53', u='U2', rf='R31', sw='U11', rg='R37',
                csw='C29', rpd='R67', cpin='C14', c10='C45', rsup='R72', riso='R56', dk='D6',
                nside=('R16', 'R19', 'C11', 'C5', 'C6'), c2t='C12', r3=('R17', 'R4')),
}
for ch, c in CH.items():
    y = c['y0']
    # input row, right to left: R1 = 330k, 330k, 100k (pin 1 toward the BNC: rotation 180), then Rnp
    for ref, x in zip(c['r1'], (90.3, 86.9, 83.5)):
        put(ref, x, y, 180)
    put(c['rnp'], 80.1, y, 180)                 # N on its right, NP on its left
    put(c['c1'], 86.9, y + 2.0, 180)            # IN (right) over the chain to N (left)
    # op-amp at 90: +IN (right end of the bottom edge) on the row, 1.7 left of Rnp's NP pad
    put(c['u'], 76.6, y + 1.137, 90)
    put(c['rf'], 76.6, y + 4.1, 0)              # OUT (left pad) and -IN (right pad) just over the op-amp
    put(c['rg'], 79.6, y + 3.4, 270)            # RG beside -IN: -IN on top, the channel's Vmid below
    put(c['sw'], 72.6, y + 4.9, 0)              # range switch left of RF: S1 (bottom-right) next to RF's OUT pad
    put(c['csw'], 69.8, y + 4.9, 90)            # its VDD decoupling on the VDD pin (left-middle)
    put(c['rpd'], 67.9, y + 4.9, 270)           # SEL's pull-down, its D16 / D39 pad (pin 1) on top
    # supply branch toward V+ (op-amp top-left): 1R from +3.3 V_A, 10 uF, then 100 nF at the pin
    put(c['cpin'], 73.1, y + 2.274, 180)
    put(c['c10'], 69.5, y + 2.274, 0)
    put(c['rsup'], 65.9, y + 2.274, 0)
    # output: Riso from OUT (op-amp bottom-left) to the left, the clamp's ADC pin (pin 3) facing it
    put(c['riso'], 72.4, y, 180)
    put(c['dk'], 67.9, y - 1.2, 0)
    # under N: R3's first part, R2 and the C2 parts, N on top (rotation 270: pin 1 up); C2's series pair side by side
    for ref, x in zip(c['nside'] + (c['c2t'],), (79.2, 81.0, 82.8, 84.6, 86.4, 88.2)):
        put(ref, x, y - 2.4, 270)
    put(c['r3'][0], 76.4, y - 3.225, 180)       # R3 chain on to the left, toward the 3.3 V sense node
    put(c['r3'][1], 72.8, y - 3.225, 180)

# --------------------------------------------------------------------------------------------- AWG
# x 64.4..92 under CH2.  Both scope outputs run down the strip x 62.95..64.4 and step right to A1 / A0 just
# above the header (A1 at Yup ~4.9, A0 at ~5.6), so nothing of the AWG sits below Yup 6.4 left of x 69.6.  DAC0 (x 83.8) runs left along the
# bottom into the buffer (follower at 270: +IN top-left, OUT top-right, -IN bottom-left); Ra goes right over to the
# gain stage's +IN (also at 270); its OUT (top-right) goes straight right to the 49.9 ohm and down to J3 (Yup 6.35).
put('R54', 80.0, 5.6, 180)                      # DAC0 (right) .. BIN (left)
put('R22', 72.2, 5.6, 180)                      # BIN to GND
put('U4', 75.0, 8.6, 270)                       # DAC0 buffer
put('D3', 78.75, 8.4, 180)                      # its supply die: BV (pin 3, left) toward V+ (bottom-right)
put('C19', 78.7, 11.6, 0)
put('R32', 77.9, 13.8, 0)                       # Ra: BO (left) .. VP (right)
put('U3', 84.6, 12.4, 270)                      # gain stage: +IN top-left on the VP line, OUT top-right
put('R51', 90.9, 11.6, 270)                     # 49.9 ohm 1206: OUT (top) .. BNC node (bottom)
put('R34', 79.8, 16.0, 0)                       # Rb: VP .. RB1, then 249 || 249 standing, then 22 to GND
put('R39', 82.2, 16.8, 270)
put('R40', 84.0, 16.8, 270)
put('R57', 85.7, 16.8, 90)
put('R35', 88.85, 9.2, 270)                      # Rf: from OUT down the right side, 249 || 249, 22 back up to -IN
put('R41', 86.5, 7.05, 180)
put('R42', 86.5, 5.15, 180)
put('R58', 84.2, 7.8, 90)
put('C7', 81.6, 8.8, 90)                        # Cf
put('R33', 79.8, 19.0, 180)                       # Rg: -IN .. the AWG Vmid (to the cal area, upper left)
put('C21', 71.0, 18.6, 90)                       # gain stage V+: 22 || 22, 100 nF, Schottky die, left column
put('D1', 72.2, 15.3, 0)
put('R59', 65.2, 8.0, 90)
put('R60', 65.2, 11.6, 90)
put('C22', 91.35, 17.4, 90)                      # V-: 22 || 22 from the negative rail, 100 nF, Schottky die, right
put('D2', 88.6, 16.6, 180)
put('R61', 65.2, 15.2, 90)
put('R62', 65.2, 18.8, 90)
put('D9', 68.4, 8.6, 90)                        # unfitted output clamps (footprints only)
put('D10', 68.4, 12.8, 90)
put('D11', 68.4, 17.0, 90)
# the AWG's own Vmid cluster sits in the calibration area (see there), with R9, its other user

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
put('R29', 33.4, 13.8, 180)                     # FB+ divider over FB+ (pin 2): 174k from OUT+, 100k to GND
put('R5', 30.2, 14.2, 90)
put('R6', 33.6, 7.0, 0)                         # FB- divider under the chip: R3 = 330k || 100k from OUT- (left)
put('R25', 33.6, 5.2, 0)                        # to FB- (right), then R4 = 3 x 330k to GND
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
# AREF (PA-7): the unfitted 0R next to the reference, then the long way round to PWMH0.8 (x 23.876, Yup 50.8) on the
# AREF side only: down beside the REF3030, out between POWER0 and ADCL0, along the bottom edge (Yup 1.0, under the
# header pins), up the left edge (x 17.6) and along the top edge (Yup 52.6) to the pin
PREROUTE += [('AREF', 'F', [(48.425, 10.6), (49.6, 9.6), (49.6, 5.0), (48.3, 3.7), (48.3, 1.0), (17.6, 1.0),
                            (17.6, 52.6), (23.876, 52.6), (23.876, 51.7)], 0.2)]
# VREF to the ratio switch's S2 (walled in by the sense divider): a stub and a via, B.Cu round the west end of the
# AWG Vmid's B.Cu line (below) to the REFP0 capacitor
PREROUTE += [('VREF', 'F', [(57.46, 24.75), (57.3, 24.3), (57.3, 23.9)], 0.2),
             ('VREF', 'B', [(57.3, 23.9), (46.6, 23.9), (46.6, 13.3), (50.2, 12.9), (50.6, 12.9)], 0.2),
             ('VREF', 'F', [(50.6, 12.9), (50.6, 13.4)], 0.2)]
PREVIA += [('VREF', 57.3, 23.9), ('VREF', 50.6, 12.9)]
# AWG Vmid from R9 (cal area) to Rg (R33, AWG): no F.Cu lane exists between the AWG's top and CH2's bottom, so B.Cu
# along that boundary between two vias
PREROUTE += [('AWG_VMID', 'F', [(78.975, 19.0), (78.98, 20.0)], 0.2),
             ('AWG_VMID', 'B', [(78.98, 20.0), (47.8, 20.0)], 0.2),
             ('AWG_VMID', 'F', [(47.8, 20.0), (47.775, 20.6)], 0.2)]
PREVIA += [('AWG_VMID', 78.98, 20.0), ('AWG_VMID', 47.8, 20.0)]
# A1 / A0: the two ADC lines, no vias.  Each leaves its clamp's ADC pin under the clamp's body (between pins 1 and 2),
# runs down the corridor (A1 x 63.85, A0 x 64.3: between the ladder's last resistor and the AWG filter column) and
# steps right just above ADCL0, A1 at Yup 4.9 and A0 at 5.6, so they never cross
PREROUTE += [('A1', 'F', [(71.575, 41.91), (70.4, 40.71), (68.838, 40.71), (64.5, 40.71), (63.85, 40.06),
                          (63.85, 5.35), (64.3, 4.9), (65.6, 4.9), (66.04, 4.46), (66.04, 3.3)], 0.2),
             ('A0', 'F', [(71.575, 24.13), (70.4, 22.93), (68.838, 22.93), (64.95, 22.93), (64.3, 22.28),
                          (64.3, 6.25), (64.95, 5.6), (68.0, 5.6), (68.58, 5.02), (68.58, 3.3)], 0.2)]

# --------------------------------------------------------------------------------------------- calibration
# ladder right above A7 .. A2 (x 50.80 .. 63.50): one series resistor per header pitch, centred between the two
# pins it joins, in two staggered rows (A at Yup 6.0, B at 8.2), so every tap drops straight onto its pin:
# R50 VREF..TAP5 (A7/A6), R49 TAP5..TAP4, R48 TAP4..TAP3, R47 TAP3..TAP2, R46 TAP2..TAP1 (A3/A2); the three
# parallel 249s from TAP1 to GND standing beside the ADC's tap pins (x 59..62), clear of the tap fan-in
put('R50', 52.07, 6.0, 0)
put('R49', 54.61, 8.2, 0)
put('R48', 57.15, 6.0, 0)
put('R47', 59.69, 8.2, 0)
put('R46', 62.23, 6.0, 0)
put('R45', 62.15, 10.6, 90)
put('R44', 60.6, 10.6, 90)
put('R43', 59.05, 10.6, 90)
put('U8', 47.6, 7.4, 0)                         # REF3030: IN, OUT (left), GND (right)
put('C24', 44.4, 8.2, 90)
put('C32', 44.4, 11.6, 90)
put('R81', 47.6, 10.6, 0)                        # unfitted 0R to AREF
put('TP6', 50.2, 10.8)
# ADS124S08 at 90: AIN0..5 (pins 7..2) along its bottom edge, right to left in the ladder's own order, above the
# taps; the SPI pins (9..12) on its right edge toward XIO0; AIN8 / AIN9 (pins 22 / 21) on its top edge under the sense
# divider; AVDD and REFP0 on its left edge with their capacitors
put('U9', 56.0, 17.0, 90)
put('C33', 50.6, 18.4, 90)                      # AVDD (pin 26)
put('C26', 50.6, 14.6, 90)                      # REFP0 (pin 30) 2 x 100 nF
put('C27', 48.8, 14.6, 90)
put('C25', 61.4, 18.6, 90)                      # DVDD / IOVDD (pins 16 / 15)
put('R69', 61.4, 14.6, 90)                      # CS (pin 9) pull-up
# sense divider over AIN8 / AIN9: R8 from SNS_TAP (left, over pin 22) to SNS_D (right, over pin 21), R7 down into
# SNS_TAP from the BNC node; the ratio switch at 180 with D facing R8, SEL / VDD on its right
put('R8', 55.8, 22.6, 0)
put('R7', 55.0, 24.9, 270)
put('U12', 58.6, 25.4, 180)
put('C30', 61.6, 25.6, 90)
put('R68', 61.0, 22.6, 0)
put('D7', 51.8, 24.6, 90)                       # SNS_D clamp
put('D8', 48.0, 24.6, 90)                       # SNS_S1 clamp
put('R9', 48.6, 21.0, 0)                        # AWG Vmid to S1
# the AWG's own Vmid: divider, 12 pF on the tap, follower, its Schottky and 100 nF
put('U5', 39.0, 21.0, 90)
put('R23', 41.6, 23.0, 90)
put('R24', 41.6, 19.4, 90)
put('C8', 39.0, 17.3, 0)
put('D4', 35.0, 22.4, 0)
put('C20', 35.4, 18.8, 90)

# --------------------------------------------------------------------------------------------- scope Vmid
# between the channels' rows (Yup 27..48) and left of them (x 32..63, keeping x 62.95..64.4 free for CH1's line to A1)
put('R38', 35.6, 27.6, 90)                      # from the Due 3.3 V pin (POWER0.4, x 35.56), up the left side
put('C46', 37.6, 27.6, 90)
put('C15', 39.4, 27.6, 90)
put('R20', 42.6, 30.4, 0)
put('R21', 42.6, 28.4, 0)
put('C47', 46.6, 29.0, 90)
put('U6', 56.0, 36.4, 0)                        # TLV9062 between the two banks: A (left pins) CH1, B (right pins) CH2
put('C18', 56.0, 40.4, 0)
put('C16', 50.8, 44.0, 90)                      # CH1 loop above it: 100 nF, 1 uF, 4 x 1R, 4.7k (toward the CH1 bank)
put('C34', 52.8, 44.0, 90)
put('R73', 54.6, 44.0, 90)
put('R74', 56.4, 44.0, 90)
put('R75', 58.2, 44.0, 90)
put('R76', 60.0, 44.0, 90)
put('R63', 62.0, 44.0, 90)
# CH1's 6 x 10 uF in a row just under CH1 (x 66..90, Yup 36.3), next to R2 / C2 / RG, which draw from the node
for k in range(6):
    put(f'C{48 + k}', 68.0 + 4.0 * k, 36.3, 0)
put('C17', 50.8, 29.0, 90)                      # CH2 loop below it, the same parts
put('C35', 52.8, 29.0, 90)
put('R77', 54.6, 29.0, 90)
put('R78', 56.4, 29.0, 90)
put('R79', 58.2, 29.0, 90)
put('R80', 60.0, 29.0, 90)
put('R64', 62.0, 29.0, 90)
# CH2's 6 x 10 uF in a row just over CH2 (Yup 32.2); the strip between the two rows carries the SPI lines across
for k in range(6):
    put(f'C{54 + k}', 68.0 + 4.0 * k, 32.2, 0)
