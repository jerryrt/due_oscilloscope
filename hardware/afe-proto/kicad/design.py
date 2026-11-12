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
    '0Rb': ('0R 1%', 'C21189', 'UNI-ROYAL 0603WAF0000T5E', R0603),       # the wall bridges: a 0603 over one of the A1 / A0 lines each (afe.md LR-1, D24)
    '2.2k': ('2.2k 1%', 'C4190', 'UNI-ROYAL 0603WAF2201T5E', R0603),
    '22k': ('22k 1%', 'C31850', 'UNI-ROYAL 0603WAF2202T5E', R0603),
    '15k': ('15k 1%', 'C22809', 'UNI-ROYAL 0603WAF1502T5E', R0603),
    '3.9k': ('3.9k 1%', 'C23018', 'UNI-ROYAL 0603WAF3901T5E', R0603),
    '13k': ('13k 1%', 'C22797', 'UNI-ROYAL 0603WAF1302T5E', R0603),
    '75k': ('75k 1%', 'C23242', 'UNI-ROYAL 0603WAF7502T5E', R0603),
    '1k': ('1k 1%', 'C21190', 'UNI-ROYAL 0603WAF1001T5E', R0603),
    '270': ('270 1%', 'C22966', 'UNI-ROYAL 0603WAF2700T5E', R0603),
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
P33E = P33A      # the AWG's +3.3 V_A: the same net, carried to the east on a strip lane under the pad rows (no bridge)
VREF = 'VREF'   # REF3030E output = ladder top tap = REFP0 (PA-8)

# ------------------------------------------------------------------ power (architecture.md "Power"; sim/powercal)
B = 'power'
two('R408', '1R', P5, P5F, B, '5 V feed sense, take only (PW-1)')
two('R410', '0Rb', VN, VN, 'power', 'POWER block agent: a 0 ohm link that carries VNEG over the +5V_F column (both pads on VNEG): the generator\'s two rails cannot both leave the pockets the +5V_F tree encloses on one layer (LR-1: no hop)')
two('C403', '10u', P5F, G, B, '5 V bulk = CIN'); two('C404', '10u', P5F, G, B, '5 V bulk = CIN')
two('C401', '100n', P5F, G, B, 'LM27762 VIN')
part('U401', 'LM27762', {'1': G, '2': 'LM_FBP', '3': P5F, '4': G, '5': 'LM_CP', '6': VN, '7': 'LM_FBN',
                       '8': P5F, '9': 'LM_C1N', '10': 'LM_C1P', '11': P33A, '12': P5F, '13': G}, B,
     'EN+ / EN- from VIN; PGOOD unused, to GND (SNVSAF7C table 4-1)')
two('C402', '1u', 'LM_C1P', 'LM_C1N', B, 'flying capacitor C101')
two('C405', '10u', 'LM_CP', G, B, 'CPOUT'); two('C406', '10u', 'LM_CP', G, B, 'CPOUT')
two('C407', '10u', P33A, G, B, 'OUT+'); two('C408', '10u', P33A, G, B, 'OUT+')
two('C409', '10u', VN, G, B, 'OUT-'); two('C410', '10u', VN, G, B, 'OUT-')
two('R406', '75k', P33A, 'LM_FBPX', B, 'FB+ top (R101) = 75k + 100k = 175k, 3.300 V nominal')
two('R409', '100k', 'LM_FBPX', 'LM_FBP', B, 'FB+ top (R101), part 2'); two('R401', '100k', 'LM_FBP', G, B, 'FB+ bottom (R201)')
# VOUT- = -1.22 V x (R3 + R4) / R4 (SNVSAF7C eq. 3): R3 OUT- to FB-, R4 FB- to GND
two('R402', '75k', VN, 'LM_FBN', B, 'R3 = 75k, -2.052 V nominal')
for r in ('R403', 'R404', 'R405'):
    two(r, '330k', 'LM_FBN', G, B, 'R4 = 3 x 330k ||')
two('R407', '2.2k', P33A, G, B, '+3.3 V_A bleed (PR-3): holds the unpowered rail under 0.5 V with +5 V forced on the AWG BNC (whatif/v1-jumper/ section 8)')

# ------------------------------------------------------------------ scope channels (sim/scope netlib core, variant hz)
# D18 and the REF3030E centre (budget/v1_scope_ref.py): each channel is IN - R101 (470k + 300k) - N, N - R201 (470k + 330k) - GND,
# N - R3 (330k) - VREF, C101 12 pF across R101, C201 30 pF from N to GND (the 39.5 pF of the compensation less the 10 pF Cnp that
# loads N behind Rnp), then Rnp 680 / Cnp 10 pF to the follower's +IN
SC = {  # ch: R101 parts, R201 parts, R3, C101, C201, Rnp, Cnp, Riso, clamp, BNC
    'CH1': (('R102', 'R103'), ('R105', 'R101'), 'R104', 'C101', 'C102', 'R106', 'C105', 'R107', 'D101', 'J101'),
    'CH2': (('R202', 'R203'), ('R205', 'R201'), 'R204', 'C201', 'C202', 'R206', 'C203', 'R207', 'D201', 'J201'),
}
ADC = {'CH1': 'A1', 'CH2': 'A0'}            # afe.md: CH1 on A1, CH2 on A0
for ch, (r1, r2, r3, c1, c2, rnp, cnp, riso, dk, j) in SC.items():
    B = ch.lower()
    n = lambda s: f'{ch}_{s}'
    other(j, 'Connector:Conn_Coaxial', 'KH-BNC50-3511', BNC, {'1': n('IN'), '2': G}, B, f'{ch} input, right-angle')
    PARTS[-1].update(lcsc='C2837587', mpn='Kinghelm KH-BNC50-3511')
    two(r1[0], '470k', n('IN'), n('R1A'), B, 'R101 (770k), part 1'); two(r1[1], '300k', n('R1A'), n('N'), B, 'R101, part 2')
    two(c1, '12p', n('IN'), n('N'), B, 'C101 across R101')
    two(r2[0], '470k', n('N'), n('R2A'), B, 'R201 (800k) to GND, part 1'); two(r2[1], '330k', n('R2A'), G, B, 'R201, part 2')
    two(r3, '330k', n('N'), 'VREF_R' if ch == 'CH1' else 'VREF_P', B, 'R3 to the REF3030E: the centre (CH2 takes the spur over the wall: R515, R516)')
    two(c2, '30p', n('N'), G, B, 'C201')
    two(rnp, '680', n('N'), n('NP'), B, 'Rnp, clamp-current limit')
    two(cnp, '10p', n('NP'), G, B, 'Cnp: AN-1 with the TPH2502 (whatif/tph2502); a pole with Rnp at 23 MHz')
    if ch == 'CH1':     # one TPH2502 for both channels (afe.md D16; VT-10 decides, else one dual per channel)
        # placed at 90 degrees between the two channels: pins 1-3 on its south edge are CH2's, 5-7 on its north edge CH1's,
        # each with OUT at the west end and +IN at the east end (layout.py); unity followers: -IN is tied to OUT
        part('U101', 'TPH2502', {'1': 'CH2_OUT', '2': 'CH2_OUT', '3': 'CH2_NP', '4': G,
                               '5': 'CH1_NP', '6': 'CH1_OUT', '7': 'CH1_OUT', '8': 'SC_VCC'}, B,
             'scope dual: A CH2, B CH1, followers')
        two('R108', '1R', 'P33_U', 'SC_VCC', B, 'scope dual supply branch (LR-6)'); two('C104', '10u', 'SC_VCC', G, B, 'supply branch')
        two('C103', '100n', 'SC_VCC', G, B, 'supply pin')
    two(riso, '22', n('OUT'), ADC[ch], B, 'Riso')
    part(dk, 'BAV99', {'1': G, '3': ADC[ch], '2': 'P33_U'}, B, 'ADC-pin clamp after Riso (BAV99, Basic: kvm_02\'s v2 scope run holds PR-2 with it)')

# ------------------------------------------------------------------ AWG (sim/awg variant buf, sim/powercal ac_netlist)
B = 'awg'
# D25/D27 and whatif/v1-awg-ref (one design with v2): DAC0 straight into a divider, ONE half of a TPH2502 as the gain stage
# (the spare half tied off: V2-2 allows it where the circuit has no use for it), the offset taken from the REF3030E through a
# 100 ohm + 2 x 10 uF filter at the Rg2 end; Vout = Gs*kin*Vdac - K*Vref.  No buffer, no Vmid follower, no series Schottkys.
two('R305', '51k', 'DAC0', 'AWG_BIN', B, 'Rbin: DAC0 series resistor and the divider\'s upper arm')
two('R308', '51k', 'AWG_BIN', 'AWG_BPL', B, 'Rbpl, part 1 (51k + 75k = 126k to GND)')
two('R301', '75k', 'AWG_BPL', G, B, 'Rbpl, part 2')
two('C304', '10p', 'DAC0', 'AWG_BIN', B, 'Cbin across Rbin: without it the divider pole fails AW-3')
two('R303', '3.3k', 'AWG_OUT', 'AWG_INV', B, 'Rf')
two('C301', '10p', 'AWG_OUT', 'AWG_INV', B, 'Cf across Rf (AN-1: the stage has no phase margin without it)')
two('R302', '4.99k', 'AWG_INV', 'AWG_X', B, 'Rg2, to the filtered REF3030E output')
two('R307', '100R', VREF, 'AWG_X', B, 'offset filter, series 100 ohm: hides the AWG current from the REF output impedance (SC-9)')
two('C305', '10u', 'AWG_X', G, B, 'offset filter, 10 uF (14 uF with the 2nd, about 7 uF each at 3 V bias *(check)*)')
two('C306', '10u', 'AWG_X', G, B, 'offset filter, 10 uF')
two('C302', '100n', P33E, G, B, 'TPH2502 V+ pin')
# the AWG's +3.3 V branch crosses the A1 and A0 lines (the ADC lines from the channels to the Due's A1 / A0 pins) on two
# 0 ohm bridges (afe.md D24: a bridge, not a bottom hop, over an ADC trace)
two('R109', '0Rb', P33A, 'P33_S', 'ch1', 'bridge over the quiet VREF trunk: the scope\'s own +3V3A branch from the star (LR-6), part 1 of 2')
two('R110', '0Rb', 'P33_S', 'P33_U', 'ch1', 'bridge over the A1 column: the scope\'s +3V3A branch to the dual V+ and the clamps, part 2 of 2')
two('R515', '0Rb', VREF, 'VREF_M', 'cal', 'wall bridge over A1 (the CH2 leg of VREF), part 1 of 2')
two('R111', '0Rb', 'VREF_P', 'VREF_Q', 'ch1', 'SCOPE agent: VREF_P reaches the CH1 R3 leg over the A0 horizontal, part 1 of 2 (A0, the supply belt and A1 close the north half of the fence), part 1 of 3')
two('R113', '0Rb', 'VREF_Q', 'VREF_S', 'ch1', 'SCOPE agent: over the supply belt (R110.2 -> R108 -> U101.8 -> U101 -> R107) inside fence 1, part 2 of 3')
two('R112', '0Rb', 'VREF_S', 'VREF_R', 'ch1', 'SCOPE agent: over the A1 horizontal, part 3 of 3: CH1 R3 (R104) hangs on VREF_R')
two('R516', '0Rb', 'VREF_M', 'VREF_P', 'cal', 'wall bridge over A0 (the CH2 leg of VREF), part 2 of 2')
two('C303', '100n', VN, G, B, 'TPH2502 V- pin (at the pin)')
part('U301', 'TPH2502', {'1': 'AWG_SP', '2': 'AWG_SP', '3': G, '4': VN, '5': 'AWG_BIN', '6': 'AWG_INV', '7': 'AWG_OUT', '8': P33E}, B,
     'half B the gain stage (pins 5-7: +IN, -IN, OUT); half A the spare: +IN to GND, follower (V2-2). At 270 degrees the '
     'stage\'s pins face the DAC0 pin and its OUT the BNC')
two('R304', '100R1206', 'AWG_OUT', 'AWG_BNC', B, 'series 50 ohm (AW-4): 2 x 100 ohm 1206 in parallel, 0.1 W each in the short')
two('R306', '100R1206', 'AWG_OUT', 'AWG_BNC', B, 'series 50 ohm (AW-4), part 2')
other('J301', 'Connector:Conn_Coaxial', 'KH-BNC50-3511', BNC, {'1': 'AWG_BNC', '2': G}, B, 'AWG output, right-angle')
PARTS[-1].update(lcsc='C2837587', mpn='Kinghelm KH-BNC50-3511')

# ------------------------------------------------------------------ calibration (architecture.md "Calibration", whatif/tee)
B = 'cal'
part('U501', 'REF3030', {'1': P33A, '2': VREF, '3': G}, B, 'drives the ladder and REFP0 directly')
two('C501', '100n', P33A, G, B, 'REF3030 VIN'); two('C505', '1u', P33A, G, B, 'REF3030 VIN bulk')
two('C503', '100n', VREF, G, B, 'reference output, at the ADS1115 AIN0')
two('C504', '1u', VREF, G, B, 'reference output: the REF3030E asks for 0.1-22 uF (SBVS032), a 100 nF part alone is 0.09 uF at -10 %')
# ladder: 100 ohm at the bottom (one part: the 3 x 270 || it replaces was 90 ohm), 5 x 270 in series; taps about 0.207 / 0.766 /
# 1.324 / 1.883 / 2.441 V on A2..A7 (the measured ones are read, the rest are checks)
two('R503', '100R', 'TAP1', G, B, 'ladder bottom')
for r, a, b in (('R504', 'TAP1', 'TAP2'), ('R505', 'TAP2', 'TAP3'), ('R506', 'TAP3', 'TAP4'), ('R507', 'TAP4', 'TAP5'),
                ('R508', 'TAP5', VREF)):
    two(r, '270', a, b, B, 'ladder series')
two('R510', '0R', VREF, 'AREF', B, 'PA-7: reference to the Due AREF pin, unfitted', dnp=True)
# AWG-sense divider and the jumper ratio measurement (afe.md D25, PA-4; kvm_02's structure S3, whatif/v1-jumper/):
# BNC node - R501 - tap T0 - R502 - bottom end B - Rd - VREF (the default tie, wire off); k = R502 / (R501 + R502) = 0.405.  The wire (a
# shunt on J501) joins B to TAP3.  T0 and B each reach the ADS1115 through a series resistor (Rs 3.9k, Rm 13k = Rt||Rb + Rs
# matched) and a BAV99 clamp, and are read as the differential pair AIN2-AIN3.
two('R309', '0Rb', 'AWG_S', 'AWG_I', 'awg', 'wall bridge over A1 (AWG_BNC sense tap, west-bound), part 1 of 2')
two('R310', '0Rb', 'AWG_I', 'AWG_BNC', 'awg', 'wall bridge over A0 (AWG_BNC sense tap, west-bound), part 2 of 2')
two('R501', '22k', 'AWG_S', 'SNS_TAP', B, 'sense divider, BNC node to the tap T0')
two('R502', '15k', 'SNS_TAP', 'SNS_B', B, 'sense divider, tap to the bottom end B')
two('R512', '1k', 'SNS_B', VREF, B, 'Rd: the default tie of B to VREF (wire off)')
two('R513', '3.9k', 'SNS_TAP', 'SNS_TI', B, 'Rs: T0 to AIN2')
two('R514', '13k', 'SNS_B', 'SNS_BI', B, 'Rm: B to AIN3 (source impedance matched to AIN2)')
part('D502', 'BAV99', {'1': G, '3': 'SNS_TI', '2': 'P33_R'}, B, 'clamp on AIN2 (SBAS444E 7.3.1: an overdriven input disturbs the others)')
part('D501', 'BAV99', {'1': G, '3': 'SNS_BI', '2': 'P33_R'}, B, 'clamp on AIN3')
other('J501', 'Connector_Generic:Conn_01x03', 'CAL', 'Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical',
      {'1': 'TAP4', '2': 'SNS_B', '3': 'TAP3'}, B, 'ratio jumper: a shunt across B and TAP3 (pins 2-3); TAP4 next to it is a wrong '
      'position that stays in range', fitted_by='owner')
# precision ADC (D15: v2's ADS1115, afe-v2 V2-8 / section 3.4)
part('U502', 'ADS1115', {'1': G, '3': G, '4': VREF, '5': 'TAP3', '6': 'SNS_TI', '7': 'SNS_BI',
                       '8': 'P33_R', '9': 'SDA1_A', '10': 'SCL1_A'}, B,
     'ADDR to GND (0x48); AIN0 VREF (a check), AIN1 TAP3, AIN2 / AIN3 the sense tap T0 and the bottom end B read as a '
     'differential pair; RDY unused')
two('C502', '100n', 'P33_R', G, B, 'ADS1115 VDD')
two('R509', '4.7k', 'SDA1_A', 'P33_R', B, 'I2C pull-up, SDA1 (the Due has none on TWI0)')
two('R511', '4.7k', 'SCL1_A', 'P33_R', B, 'I2C pull-up, SCL1')
# REFCAL's planar cut (the block agent's finding): the VREF tree (legs A south, D1 north, D2 east) splits the fence, and the ADS
# straddles it. Three 0603 0 ohm bridges carry the nets that must cross: the ADS's +3V3A, SDA and SCL.
two('R517', '0Rb', P33A, 'P33_R', B, 'bridge over a VREF leg: the ADS side of +3V3A beyond it (VDD, its 100 nF, the pull-ups, the clamps)')
two('R518', '0Rb', 'SDA1', 'SDA1_A', B, 'bridge over a VREF leg: SDA to the ADS')
two('R519', '0Rb', 'SCL1', 'SCL1_A', B, 'bridge over a VREF leg: SCL to the ADS')

# ------------------------------------------------------------------ Due headers (docs/due-header-table.md, V03)
B = 'due'
HDR = {  # ref: (symbol, value, footprint, {pin: net})
    'J601': ('Connector_Generic:Conn_01x08', 'POWER0', 'Connector_PinSocket_2.54mm:PinSocket_1x08_P2.54mm_Vertical',
           {'5': P5, '6': G, '7': G}),
    'J602': ('Connector_Generic:Conn_01x08', 'ADCL0', 'Connector_PinSocket_2.54mm:PinSocket_1x08_P2.54mm_Vertical',
           {'1': VREF, '2': 'TAP5', '3': 'TAP4', '4': 'TAP3', '5': 'TAP2', '6': 'TAP1', '7': 'A1', '8': 'A0'}),
    'J603': ('Connector_Generic:Conn_01x08', 'ADCH0', 'Connector_PinSocket_2.54mm:PinSocket_1x08_P2.54mm_Vertical',
           {'5': 'DAC0'}),
    'J604': ('Connector_Generic:Conn_01x08', 'PWML0', 'Connector_PinSocket_2.54mm:PinSocket_1x08_P2.54mm_Vertical', {}),
    'J605': ('Connector_Generic:Conn_01x08', 'COMMUNICATION0',
           'Connector_PinSocket_2.54mm:PinSocket_1x08_P2.54mm_Vertical', {}),
    'J606': ('Connector_Generic:Conn_01x10', 'PWMH0', 'Connector_PinSocket_2.54mm:PinSocket_1x10_P2.54mm_Vertical',
           {'7': G, '8': 'AREF', '9': 'SDA1', '10': 'SCL1'}),
    'J607': ('Connector_Generic:Conn_02x18_Odd_Even', 'XIO0',
            'afe:PinSocket_2x18_P2.54mm_Vertical_DueXIO',     # stock socket, odd / even exchanged (build_pcb.py);
            # its 5V pins 1/2 are left open: the Due joins them to POWER0.5 on its own board, and the shield takes
            # 5 V at POWER0.5 alone (a second shield-side 5 V path would only add a trace across the board)
            {'35': G, '36': G}),
}
for ref, (sym, val, fp, pins) in HDR.items():
    other(ref, sym, val, fp, pins, B, 'generic Mega stacking header, owner-fitted')
# ISO7380 courtyard (r 3.1 mm, a 5.7 mm head): the plain M3 hole's r 3.45 overlaps ADCH0's and XIO0's courtyards
# there; the M3 x 5 pan head is 5.6 mm *(check)*
# M2.5 at both Due holes (the spec lead, with v2): MH602 at (90.17, 50.8) is 3.81 mm from XIO0's pin 1 / the top socket's end, where an M3 head
# (5.6 mm) would overlap the socket housing and an M2.5 head (4.5 mm) clears it by about 0.7 mm *(check against the housing drawing)*
other('MH601', 'Mechanical:MountingHole', 'M2.5 standoff', 'MountingHole:MountingHole_2.7mm_M2.5', {}, B,
      'over the Due hole (96.52, 2.54)')
other('MH602', 'Mechanical:MountingHole', 'M2.5 standoff', 'MountingHole:MountingHole_2.7mm_M2.5', {}, B,
      'over the Due hole (90.17, 50.8), beside the BNCs')
for k, (net, why) in enumerate(((P5, '5 V pin side of the sense resistor (R408)'), (P5F, 'AFE side of the sense resistor (R408)'),
                                (G, 'ground'), (P33A, '+3.3 V_A'), (VN, 'negative rail'), (VREF, '3.0 V reference')), 1):
    other(f'TP{400 + k}' if k <= 5 else 'TP501', 'Connector:TestPoint', net, TP, {'1': net}, 'power' if k <= 5 else 'cal', why, fitted_by='none')

# LR-11 test points on the key nodes of the blocks that had none: each ADC pin (on the existing trace, no stub: A1, A0 add pad
# capacitance to LR-4's total) and the AWG output before the back-termination
for ref, net, blk, why in (('TP101', 'A1', 'ch1', 'ADC pin A1 (CH1), on the trace'), ('TP201', 'A0', 'ch2', 'ADC pin A0 (CH2), on the trace'),
                           ('TP301', 'AWG_OUT', 'awg', 'AWG output before the back-termination')):
    other(ref, 'Connector:TestPoint', net, TP, {'1': net}, blk, why, fitted_by='none')

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
