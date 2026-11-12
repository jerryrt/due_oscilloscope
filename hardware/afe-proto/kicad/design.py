"""The AFE shield, round 1: every part and every pin's net, in one place.

This file is the source the schematic (build_sch.py) and the board
(build_pcb.py) are generated from, and the reference check.py holds both
of them to.  Values, part numbers and designators are whatif/bom.txt's;
the connectivity is the simulated circuit's (docs/architecture.md and the
sim/ netlist builders cited at each block).  A pin left out of a part's
map is unconnected and gets a no-connect flag.

Own work, CC BY-SA 4.0.
"""

R0603 = 'Resistor_SMD:R_0603_1608Metric'
R1206 = 'Resistor_SMD:R_1206_3216Metric'
C0603 = 'Capacitor_SMD:C_0603_1608Metric'
C0805 = 'Capacitor_SMD:C_0805_2012Metric'
SOT235 = 'Package_TO_SOT_SMD:SOT-23-5'
SOT23 = 'Package_TO_SOT_SMD:SOT-23'
SC706 = 'Package_TO_SOT_SMD:SOT-363_SC-70-6'
SOIC8 = 'Package_SO:SOIC-8_3.9x4.9mm_P1.27mm'
WSON12 = 'Package_SON:WSON-12-1EP_3x2mm_P0.5mm_EP1x2.65_ThermalVias'
TSSOP10 = 'Package_SO:TSSOP-10_3x3mm_P0.5mm'      # TI DGS (VSSOP-10), 3 x 3 mm, 0.5 mm pitch
# Kinghelm drawing KH-801-0038 rev B, pads cross-checked with the EasyEDA footprint (lib/afe.pretty descr)
BNC = 'afe:BNC_Kinghelm_KH-BNC50-3511_Horizontal'
TP = 'TestPoint:TestPoint_Pad_D1.0mm'

# value, LCSC, MPN, footprint, symbol per BOM line (bom.txt numbering)
T = {
    # D15: every resistor and capacitor a JLC Basic part (V2-3); LCSC and MPN from v2/jlc-basic.csv, read 2026-11-12
    '100k': ('100k 1%', 'C25803', 'UNI-ROYAL 0603WAF1003T5E', R0603),
    '330k': ('330k 1%', 'C23137', 'UNI-ROYAL 0603WAF3303T5E', R0603),
    '470k': ('470k 1%', 'C23178', 'UNI-ROYAL 0603WAF4703T5E', R0603),
    '300k': ('300k 1%', 'C23024', 'UNI-ROYAL 0603WAF3003T5E', R0603),
    '3.3k': ('3.3k 1%', 'C22978', 'UNI-ROYAL 0603WAF3301T5E', R0603),
    '4.99k': ('4.99k 1%', 'C23046', 'UNI-ROYAL 0603WAF4991T5E', R0603),
    '51k': ('51k 1%', 'C23196', 'UNI-ROYAL 0603WAF5102T5E', R0603),
    '100R': ('100 1%', 'C22775', 'UNI-ROYAL 0603WAF1000T5E', R0603),
    '0Rb': ('0R 1%', 'C21189', 'UNI-ROYAL 0603WAF0000T5E', R0603),       # BR1/BR2: a bridge over the A0 / A1 lines (afe.md D24)
    '2.2k': ('2.2k 1%', 'C4190', 'UNI-ROYAL 0603WAF2201T5E', R0603),
    '22k': ('22k 1%', 'C31850', 'UNI-ROYAL 0603WAF2202T5E', R0603),
    '15k': ('15k 1%', 'C22809', 'UNI-ROYAL 0603WAF1502T5E', R0603),
    '3.9k': ('3.9k 1%', 'C23018', 'UNI-ROYAL 0603WAF3901T5E', R0603),
    '13k': ('13k 1%', 'C22797', 'UNI-ROYAL 0603WAF1302T5E', R0603),
    '75k': ('75k 1%', 'C23242', 'UNI-ROYAL 0603WAF7502T5E', R0603),
    '1k': ('1k 1%', 'C21190', 'UNI-ROYAL 0603WAF1001T5E', R0603),
    '270': ('270 1%', 'C22966', 'UNI-ROYAL 0603WAF2700T5E', R0603),
    '0R1206': ('0R 1%', 'C17888', 'UNI-ROYAL 1206W4F0000T5E', R1206),        # BR3: AWG_BNC over both A lines (LCSC number *(check)*)
    '100R1206': ('100 1% 1206', 'C17901', 'UNI-ROYAL 1206W4F1000T5E', R1206),
    '680': ('680 1%', 'C23228', 'UNI-ROYAL 0603WAF6800T5E', R0603),
    '22': ('22 1%', 'C23345', 'UNI-ROYAL 0603WAF220JT5E', R0603),
    '4.7k': ('4.7k 1%', 'C23162', 'UNI-ROYAL 0603WAF4701T5E', R0603),
    '1R': ('1 1%', 'C22936', 'UNI-ROYAL 0603WAF100KT5E', R0603),
    '12p': ('12p C0G', 'C38523', 'Samsung CL10C120JB8NNNC', C0603),
    '10p': ('10p C0G', 'C1634', 'Samsung CL10C100JB8NNNC', C0603),
    '30p': ('30p C0G', 'C1658', 'FH 0603CG300J500NT', C0603),
    '100n': ('100n X7R', 'C14663', 'Yageo CC0603KRX7R9BB104', C0603),
    '1u': ('1u X5R', 'C15849', 'Samsung CL10A105KB8NNNC', C0603),
    '10u': ('10u X5R 25V', 'C15850', 'Samsung CL21A106KAYNNNE', C0805),
    'TPH2502': ('TPH2502-SR', 'C118223', '3PEAK TPH2502-SR', SOIC8),   # afe.md D13/D16, v2/parts.md: every fast role
    'TLV9062': ('TLV9062IDR', 'C398355', 'TI TLV9062IDR', SOIC8),
    'LM27762': ('LM27762DSSR', 'C473398', 'TI LM27762DSSR', WSON12),
    'REF3030': ('REF3030EAIDBZR', 'C54120492', 'TI REF3030EAIDBZR', SOT23),
    'ADS1115': ('ADS1115IDGSR', 'C37593', 'TI ADS1115IDGSR', TSSOP10),
    'TMUX1119': ('TMUX1119DCKR', 'C2673327', 'TI TMUX1119DCKR', SC706),
    # not assembled
    'BAV99': ('BAV99', 'C2500', 'Nexperia BAV99,215', SOT23),     # Basic: every clamp (series pair: 1 anode, 3 junction, 2 cathode)
    '0R': ('0R', '', '', R0603),
    'BNC': ('KH-BNC50-3511', 'C2837587', 'Kinghelm KH-BNC50-3511', BNC),
}
SYM = {
    'R': 'Device:R', 'C': 'Device:C',
    'TPH2502': 'Amplifier_Operational:LM358',     # generic dual, standard SOIC-8 pinout (TPH2502 Table 'Pin Configuration' *(check)*)
    'TLV9062': 'Amplifier_Operational:TLV9062xD', 'LM27762': 'Regulator_SwitchedCapacitor:LM27762',
    'REF3030': 'Reference_Voltage:REF3030', 'ADS1115': 'Analog_ADC:ADS1115IDGS', 'TMUX1119': 'afe:TMUX1119',
    'BAV99': 'Diode:BAT54S', 'BNC': 'Connector:Conn_Coaxial',
}

PARTS = []       # dicts: ref, sym, value, fp, lcsc, mpn, pins {pin: net}, block, dnp, fitted_by, note


def part(ref, kind, pins, block, note='', dnp=False, fitted_by='JLC'):
    val, lcsc, mpn, fp = T[kind]
    sym = SYM.get(kind) or ('Device:R' if fp.startswith('Resistor') else 'Device:C')
    PARTS.append(dict(ref=ref, sym=sym, value=val, fp=fp, lcsc=lcsc, mpn=mpn, pins=dict(pins),
                      block=block, dnp=dnp, fitted_by=fitted_by, note=note))


def two(ref, kind, a, b, block, note='', **kw):
    part(ref, kind, {'1': a, '2': b}, block, note, **kw)


def other(ref, sym, value, fp, pins, block, note='', fitted_by='owner', dnp=False):
    PARTS.append(dict(ref=ref, sym=sym, value=value, fp=fp, lcsc='', mpn='', pins=dict(pins),
                      block=block, dnp=dnp, fitted_by=fitted_by, note=note))


G, P5, P5F, P33A, VN, P33D = 'GND', '+5V_DUE', '+5V_F', '+3V3A', 'VNEG', '+3V3_DUE'
P33E = '+3V3A_E'     # the +3.3 V_A branch east of the A0 / A1 lines (the AWG's), reached through two 0 ohm bridges
VREF = 'VREF'   # REF3030E output = ladder top tap = REFP0 (PA-8)

# ------------------------------------------------------------------ power (architecture.md "Power"; sim/powercal)
B = 'power'
two('R70', '1R', P5, P5F, B, '5 V feed sense, take only (PW-1)')
two('C36', '10u', P5F, G, B, '5 V bulk = CIN'); two('C37', '10u', P5F, G, B, '5 V bulk = CIN')
two('C23', '100n', P5F, G, B, 'LM27762 VIN')
part('U7', 'LM27762', {'1': G, '2': 'LM_FBP', '3': P5F, '4': G, '5': 'LM_CP', '6': VN, '7': 'LM_FBN',
                       '8': P5F, '9': 'LM_C1N', '10': 'LM_C1P', '11': P33A, '12': P5F, '13': G}, B,
     'EN+ / EN- from VIN; PGOOD unused, to GND (SNVSAF7C table 4-1)')
two('C31', '1u', 'LM_C1P', 'LM_C1N', B, 'flying capacitor C1')
two('C38', '10u', 'LM_CP', G, B, 'CPOUT'); two('C39', '10u', 'LM_CP', G, B, 'CPOUT')
two('C40', '10u', P33A, G, B, 'OUT+'); two('C41', '10u', P33A, G, B, 'OUT+')
two('C42', '10u', VN, G, B, 'OUT-'); two('C43', '10u', VN, G, B, 'OUT-')
two('R29', '75k', P33A, 'LM_FBPX', B, 'FB+ top (R1) = 75k + 100k = 175k, 3.300 V nominal')
two('R83', '100k', 'LM_FBPX', 'LM_FBP', B, 'FB+ top (R1), part 2'); two('R5', '100k', 'LM_FBP', G, B, 'FB+ bottom (R2)')
# VOUT- = -1.22 V x (R3 + R4) / R4 (SNVSAF7C eq. 3): R3 OUT- to FB-, R4 FB- to GND
two('R6', '75k', VN, 'LM_FBN', B, 'R3 = 75k, -2.052 V nominal')
for r in ('R26', 'R27', 'R28'):
    two(r, '330k', 'LM_FBN', G, B, 'R4 = 3 x 330k ||')
two('R65', '2.2k', P33A, G, B, '+3.3 V_A bleed (PR-3): holds the unpowered rail under 0.5 V with +5 V forced on the AWG BNC (whatif/v1-jumper/ section 8)')

# ------------------------------------------------------------------ scope channels (sim/scope netlib core, variant hz)
# D18 and the REF3030E centre (budget/v1_scope_ref.py): each channel is IN - R1 (470k + 300k) - N, N - R2 (470k + 330k) - GND,
# N - R3 (330k) - VREF, C1 12 pF across R1, C2 30 pF from N to GND (the 39.5 pF of the compensation less the 10 pF Cnp that
# loads N behind Rnp), then Rnp 680 / Cnp 10 pF to the follower's +IN
SC = {  # ch: R1 parts, R2 parts, R3, C1, C2, Rnp, Cnp, Riso, clamp, BNC
    'CH1': (('R10', 'R11'), ('R18', 'R1'), 'R14', 'C1', 'C9', 'R52', 'C60', 'R55', 'D5', 'J1'),
    'CH2': (('R12', 'R13'), ('R19', 'R2'), 'R16', 'C2', 'C11', 'R53', 'C61', 'R56', 'D6', 'J2'),
}
ADC = {'CH1': 'A1', 'CH2': 'A0'}            # afe.md: CH1 on A1, CH2 on A0
for ch, (r1, r2, r3, c1, c2, rnp, cnp, riso, dk, j) in SC.items():
    B = ch.lower()
    n = lambda s: f'{ch}_{s}'
    other(j, 'Connector:Conn_Coaxial', 'KH-BNC50-3511', BNC, {'1': n('IN'), '2': G}, B, f'{ch} input, right-angle')
    PARTS[-1].update(lcsc='C2837587', mpn='Kinghelm KH-BNC50-3511')
    two(r1[0], '470k', n('IN'), n('R1A'), B, 'R1 (770k), part 1'); two(r1[1], '300k', n('R1A'), n('N'), B, 'R1, part 2')
    two(c1, '12p', n('IN'), n('N'), B, 'C1 across R1')
    two(r2[0], '470k', n('N'), n('R2A'), B, 'R2 (800k) to GND, part 1'); two(r2[1], '330k', n('R2A'), G, B, 'R2, part 2')
    two(r3, '330k', n('N'), VREF if ch == 'CH1' else 'VREF_X', B, 'R3 to the REF3030E: the centre (CH2 takes the east branch beyond the bridge R98: the south lane is the only way past the walls)')
    two(c2, '30p', n('N'), G, B, 'C2')
    two(rnp, '680', n('N'), n('NP'), B, 'Rnp, clamp-current limit')
    two(cnp, '10p', n('NP'), G, B, 'Cnp: AN-1 with the TPH2502 (whatif/tph2502); a pole with Rnp at 23 MHz')
    if ch == 'CH1':     # one TPH2502 for both channels (afe.md D16; VT-10 decides, else one dual per channel)
        # placed at 90 degrees between the two channels: pins 1-3 on its south edge are CH2's, 5-7 on its north edge CH1's,
        # each with OUT at the west end and +IN at the east end (layout.py); unity followers: -IN is tied to OUT
        part('U1', 'TPH2502', {'1': 'CH2_OUT', '2': 'CH2_OUT', '3': 'CH2_NP', '4': G,
                               '5': 'CH1_NP', '6': 'CH1_OUT', '7': 'CH1_OUT', '8': 'SC_VCC'}, B,
             'scope dual: A CH2, B CH1, followers')
        two('R71', '1R', P33A, 'SC_VCC', B, 'scope dual supply branch (LR-6)'); two('C44', '10u', 'SC_VCC', G, B, 'supply branch')
        two('C13', '100n', 'SC_VCC', G, B, 'supply pin')
    two(riso, '22', n('OUT'), ADC[ch], B, 'Riso')
    part(dk, 'BAV99', {'1': G, '3': ADC[ch], '2': P33A}, B, 'ADC-pin clamp after Riso (BAV99, Basic: kvm_02\'s v2 scope run holds PR-2 with it)')

# ------------------------------------------------------------------ AWG (sim/awg variant buf, sim/powercal ac_netlist)
B = 'awg'
# D25/D27 and whatif/v1-awg-ref (one design with v2): DAC0 straight into a divider, ONE half of a TPH2502 as the gain stage
# (the spare half tied off: V2-2 allows it where the circuit has no use for it), the offset taken from the REF3030E through a
# 100 ohm + 2 x 10 uF filter at the Rg2 end; Vout = Gs*kin*Vdac - K*Vref.  No buffer, no Vmid follower, no series Schottkys.
two('R54', '51k', 'DAC0', 'AWG_BIN', B, 'Rbin: DAC0 series resistor and the divider\'s upper arm')
two('R94', '51k', 'AWG_BIN', 'AWG_BPL', B, 'Rbpl, part 1 (51k + 75k = 126k to GND)')
two('R22', '75k', 'AWG_BPL', G, B, 'Rbpl, part 2')
two('C63', '10p', 'DAC0', 'AWG_BIN', B, 'Cbin across Rbin: without it the divider pole fails AW-3')
two('R35', '3.3k', 'AWG_OUT', 'AWG_INV', B, 'Rf')
two('C7', '10p', 'AWG_OUT', 'AWG_INV', B, 'Cf across Rf (AN-1: the stage has no phase margin without it)')
two('R33', '4.99k', 'AWG_INV', 'AWG_X', B, 'Rg2, to the filtered REF3030E output')
two('R93', '100R', 'VREF_X', 'AWG_X', B, 'offset filter, series 100 ohm: hides the AWG current from the REF output impedance (SC-9)')
two('C64', '10u', 'AWG_X', G, B, 'offset filter, 10 uF (14 uF with the 2nd, about 7 uF each at 3 V bias *(check)*)')
two('C65', '10u', 'AWG_X', G, B, 'offset filter, 10 uF')
two('C21', '100n', P33E, G, B, 'TPH2502 V+ pin')
# the AWG's +3.3 V branch crosses the A1 and A0 lines (the ADC lines from the channels to the Due's A1 / A0 pins) on two
# 0 ohm bridges (afe.md D24: a bridge, not a bottom hop, over an ADC trace)
two('R95', '0R1206', P33A, P33E, B, 'bridge BR1 over the A1 and A0 lines (D24): +3V3A to the AWG')
two('R98', '0R1206', VREF, 'VREF_X', B, 'bridge BR2 over the A1 and A0 lines (D24): the AWG offset branch of VREF')
two('C22', '100n', 'VNEG_E', G, B, 'TPH2502 V- pin (at the pin)')
two('R99', '0R1206', VN, 'VNEG_E', B, 'bridge BR4 over the A1 and A0 lines (D24): the negative rail to the AWG')
part('U3', 'TPH2502', {'1': 'AWG_SP', '2': 'AWG_SP', '3': G, '4': 'VNEG_E', '5': 'AWG_BIN', '6': 'AWG_INV', '7': 'AWG_OUT', '8': P33E}, B,
     'half B the gain stage (pins 5-7: +IN, -IN, OUT); half A the spare: +IN to GND, follower (V2-2). At 270 degrees the '
     'stage\'s pins face the DAC0 pin and its OUT the BNC')
two('R51', '100R1206', 'AWG_OUT', 'AWG_BNC', B, 'series 50 ohm (AW-4): 2 x 100 ohm 1206 in parallel, 0.1 W each in the short')
two('R88', '100R1206', 'AWG_OUT', 'AWG_BNC', B, 'series 50 ohm (AW-4), part 2')
other('J3', 'Connector:Conn_Coaxial', 'KH-BNC50-3511', BNC, {'1': 'AWG_BNC', '2': G}, B, 'AWG output, right-angle')
PARTS[-1].update(lcsc='C2837587', mpn='Kinghelm KH-BNC50-3511')

# ------------------------------------------------------------------ calibration (architecture.md "Calibration", whatif/tee)
B = 'cal'
part('U8', 'REF3030', {'1': P33A, '2': VREF, '3': G}, B, 'drives the ladder and REFP0 directly')
two('C24', '100n', P33A, G, B, 'REF3030 VIN'); two('C32', '1u', P33A, G, B, 'REF3030 VIN bulk')
two('C26', '100n', VREF, G, B, 'reference output, at the ADS1115 AIN0')
two('C27', '1u', VREF, G, B, 'reference output: the REF3030E asks for 0.1-22 uF (SBVS032), a 100 nF part alone is 0.09 uF at -10 %')
# ladder: 100 ohm at the bottom (one part: the 3 x 270 || it replaces was 90 ohm), 5 x 270 in series; taps about 0.207 / 0.766 /
# 1.324 / 1.883 / 2.441 V on A2..A7 (the measured ones are read, the rest are checks)
two('R43', '100R', 'TAP1', G, B, 'ladder bottom')
for r, a, b in (('R46', 'TAP1', 'TAP2'), ('R47', 'TAP2', 'TAP3'), ('R48', 'TAP3', 'TAP4'), ('R49', 'TAP4', 'TAP5'),
                ('R50', 'TAP5', VREF)):
    two(r, '270', a, b, B, 'ladder series')
two('R81', '0R', VREF, 'AREF', B, 'PA-7: reference to the Due AREF pin, unfitted', dnp=True)
# AWG-sense divider and the jumper ratio measurement (afe.md D25, PA-4; kvm_02's structure S3, whatif/v1-jumper/):
# BNC node - R7 - tap T0 - R8 - bottom end B - Rd - VREF (the default tie, wire off); k = R8 / (R7 + R8) = 0.405.  The wire (a
# shunt on J11) joins B to TAP3.  T0 and B each reach the ADS1115 through a series resistor (Rs 3.9k, Rm 13k = Rt||Rb + Rs
# matched) and a BAV99 clamp, and are read as the differential pair AIN2-AIN3.
two('R97', '0R1206', 'AWG_S', 'AWG_BNC', B, 'bridge BR3 over the A1 and A0 lines (D24), carrying the sense tap west')
two('R7', '22k', 'AWG_S', 'SNS_TAP', B, 'sense divider, BNC node to the tap T0')
two('R8', '15k', 'SNS_TAP', 'SNS_B', B, 'sense divider, tap to the bottom end B')
two('R90', '1k', 'SNS_B', VREF, B, 'Rd: the default tie of B to VREF (wire off)')
two('R91', '3.9k', 'SNS_TAP', 'SNS_TI', B, 'Rs: T0 to AIN2')
two('R92', '13k', 'SNS_B', 'SNS_BI', B, 'Rm: B to AIN3 (source impedance matched to AIN2)')
part('D8', 'BAV99', {'1': G, '3': 'SNS_TI', '2': P33A}, B, 'clamp on AIN2 (SBAS444E 7.3.1: an overdriven input disturbs the others)')
part('D7', 'BAV99', {'1': G, '3': 'SNS_BI', '2': P33A}, B, 'clamp on AIN3')
other('J11', 'Connector_Generic:Conn_01x03', 'CAL', 'Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical',
      {'1': 'TAP4', '2': 'SNS_B', '3': 'TAP3'}, B, 'ratio jumper: a shunt across B and TAP3 (pins 2-3); TAP4 next to it is a wrong '
      'position that stays in range', fitted_by='owner')
# precision ADC (D15: v2's ADS1115, afe-v2 V2-8 / section 3.4)
part('U9', 'ADS1115', {'1': G, '3': G, '4': VREF, '5': 'TAP3', '6': 'SNS_TI', '7': 'SNS_BI',
                       '8': P33A, '9': 'SDA1', '10': 'SCL1'}, B,
     'ADDR to GND (0x48); AIN0 VREF (a check), AIN1 TAP3, AIN2 / AIN3 the sense tap T0 and the bottom end B read as a '
     'differential pair; RDY unused')
two('C25', '100n', P33A, G, B, 'ADS1115 VDD')
two('R69', '4.7k', 'SDA1', P33A, B, 'I2C pull-up, SDA1 (the Due has none on TWI0)')
two('R82', '4.7k', 'SCL1', P33A, B, 'I2C pull-up, SCL1')

# ------------------------------------------------------------------ Due headers (docs/due-header-table.md, V03)
B = 'due'
HDR = {  # ref: (symbol, value, footprint, {pin: net})
    'J4': ('Connector_Generic:Conn_01x08', 'POWER0', 'Connector_PinSocket_2.54mm:PinSocket_1x08_P2.54mm_Vertical',
           {'5': P5, '6': G, '7': G}),
    'J5': ('Connector_Generic:Conn_01x08', 'ADCL0', 'Connector_PinSocket_2.54mm:PinSocket_1x08_P2.54mm_Vertical',
           {'1': VREF, '2': 'TAP5', '3': 'TAP4', '4': 'TAP3', '5': 'TAP2', '6': 'TAP1', '7': 'A1', '8': 'A0'}),
    'J6': ('Connector_Generic:Conn_01x08', 'ADCH0', 'Connector_PinSocket_2.54mm:PinSocket_1x08_P2.54mm_Vertical',
           {'5': 'DAC0'}),
    'J7': ('Connector_Generic:Conn_01x08', 'PWML0', 'Connector_PinSocket_2.54mm:PinSocket_1x08_P2.54mm_Vertical', {}),
    'J8': ('Connector_Generic:Conn_01x08', 'COMMUNICATION0',
           'Connector_PinSocket_2.54mm:PinSocket_1x08_P2.54mm_Vertical', {}),
    'J9': ('Connector_Generic:Conn_01x10', 'PWMH0', 'Connector_PinSocket_2.54mm:PinSocket_1x10_P2.54mm_Vertical',
           {'7': G, '8': 'AREF', '9': 'SDA1', '10': 'SCL1'}),
    'J10': ('Connector_Generic:Conn_02x18_Odd_Even', 'XIO0',
            'afe:PinSocket_2x18_P2.54mm_Vertical_DueXIO',     # stock socket, odd / even exchanged (build_pcb.py);
            # its 5V pins 1/2 are left open: the Due joins them to POWER0.5 on its own board, and the shield takes
            # 5 V at POWER0.5 alone (a second shield-side 5 V path would only add a trace across the board)
            {'35': G, '36': G}),
}
for ref, (sym, val, fp, pins) in HDR.items():
    other(ref, sym, val, fp, pins, B, 'generic Mega stacking header, owner-fitted')
# ISO7380 courtyard (r 3.1 mm, a 5.7 mm head): the plain M3 hole's r 3.45 overlaps ADCH0's and XIO0's courtyards
# there; the M3 x 5 pan head is 5.6 mm *(check)*
# M2.5 at both Due holes (the spec lead, with v2): MH2 at (90.17, 50.8) is 3.81 mm from XIO0's pin 1 / the top socket's end, where an M3 head
# (5.6 mm) would overlap the socket housing and an M2.5 head (4.5 mm) clears it by about 0.7 mm *(check against the housing drawing)*
other('MH1', 'Mechanical:MountingHole', 'M2.5 standoff', 'MountingHole:MountingHole_2.7mm_M2.5', {}, B,
      'over the Due hole (96.52, 2.54)')
other('MH2', 'Mechanical:MountingHole', 'M2.5 standoff', 'MountingHole:MountingHole_2.7mm_M2.5', {}, B,
      'over the Due hole (90.17, 50.8), beside the BNCs')
for k, (net, why) in enumerate(((P5, '5 V pin side of the sense resistor (D7)'), (P5F, 'AFE side of the sense resistor (D7)'),
                                (G, 'ground'), (P33A, '+3.3 V_A'), (VN, 'negative rail'), (VREF, '3.0 V reference')), 1):
    other(f'TP{k}', 'Connector:TestPoint', net, TP, {'1': net}, 'power' if k <= 5 else 'cal', why, fitted_by='none')

PARTS_BY_REF = {p['ref']: p for p in PARTS}
assert len(PARTS_BY_REF) == len(PARTS), 'duplicate designator'


def nets():
    """net -> sorted [(ref, pin)]"""
    out = {}
    for p in PARTS:
        for pin, net in p['pins'].items():
            out.setdefault(net, []).append((p['ref'], pin))
    return {k: sorted(v) for k, v in out.items()}


if __name__ == '__main__':
    N = nets()
    for k in sorted(N):
        if len(N[k]) < 2:
            print('single-pin net', k, N[k])
    jlc = [p for p in PARTS if p['fitted_by'] == 'JLC' and not p['dnp']]
    print(len(PARTS), 'parts,', len(jlc), 'JLC placements,', len({p['lcsc'] for p in jlc}), 'types,', len(N), 'nets')
