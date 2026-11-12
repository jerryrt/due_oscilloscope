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
TQFP32 = 'Package_QFP:TQFP-32_5x5mm_P0.5mm'
# KH-BNC50-3511's drawing was not readable (bom.txt): a stand-in right-angle footprint *(check before ordering)*
BNC = 'Connector_Coaxial:BNC_Amphenol_B6252HB-NPP3G-50_Horizontal'   # the one KiCad BNC with a 3D model
TP = 'TestPoint:TestPoint_Pad_D1.0mm'

# value, LCSC, MPN, footprint, symbol per BOM line (bom.txt numbering)
T = {
    '100k': ('100k 0.1%', 'C394537', 'RESI PTFR0603B100KN9', R0603),
    '330k': ('330k 0.1%', 'C351655', 'RESI PTFR0603B330KP9', R0603),
    '174k': ('174k 0.1%', 'C861163', 'Yageo RT0603BRD07174KL', R0603),
    '953': ('953 0.1%', 'C2984375', 'Viking AR03BTCX9530', R0603),
    '249': ('249 0.1%', 'C2692731', 'RESI PTFR0603B249RN9', R0603),
    '49.9': ('49.9 0.1%', 'C869759', 'Yageo RT1206BRB0749R9L', R1206),
    '680': ('680 1%', 'C23228', 'UNI-ROYAL 0603WAF6800T5E', R0603),
    '22': ('22 1%', 'C23345', 'UNI-ROYAL 0603WAF220JT5E', R0603),
    '4.7k': ('4.7k 1%', 'C23162', 'UNI-ROYAL 0603WAF4701T5E', R0603),
    '1R': ('1 1%', 'C22936', 'UNI-ROYAL 0603WAF100KT5E', R0603),
    '12p': ('12p C0G', 'C38523', 'Samsung CL10C120JB8NNNC', C0603),
    '20p': ('20p C0G', 'C1648', 'Samsung CL10C200JB8NNNC', C0603),
    '100n': ('100n X7R', 'C14663', 'Yageo CC0603KRX7R9BB104', C0603),
    '1u': ('1u X5R', 'C15849', 'Samsung CL10A105KB8NNNC', C0603),
    '10u': ('10u X5R 25V', 'C15850', 'Samsung CL21A106KAYNNNE', C0805),
    'OPA354': ('OPA354AIDBVR', 'C36384', 'TI OPA354AIDBVR', SOT235),
    'OPA365': ('OPA365AIDBVR', 'C96626', 'TI OPA365AIDBVR', SOT235),
    'TLV9062': ('TLV9062IDR', 'C398355', 'TI TLV9062IDR', SOIC8),
    'LM27762': ('LM27762DSSR', 'C473398', 'TI LM27762DSSR', WSON12),
    'REF3030': ('REF3030EAIDBZR', 'C54120492', 'TI REF3030EAIDBZR', SOT23),
    'ADS124S08': ('ADS124S08IPBSR', 'C2870171', 'TI ADS124S08IPBSR', TQFP32),
    'TMUX1119': ('TMUX1119DCKR', 'C2673327', 'TI TMUX1119DCKR', SC706),
    'BAT54S': ('BAT54S', 'C7420333', 'hongjiacheng BAT54S', SOT23),
    # not assembled
    'BAV99': ('BAV99', '', '', SOT23),
    '0R': ('0R', '', '', R0603),
    'BNC': ('KH-BNC50-3511', 'C2837587', 'Kinghelm KH-BNC50-3511', BNC),
}
SYM = {
    'R': 'Device:R', 'C': 'Device:C',
    'OPA354': 'afe:OPA354xxDBV', 'OPA365': 'Amplifier_Operational:OPA365xxDBV',
    'TLV9062': 'Amplifier_Operational:TLV9062xD', 'LM27762': 'Regulator_SwitchedCapacitor:LM27762',
    'REF3030': 'Reference_Voltage:REF3030', 'ADS124S08': 'afe:ADS124S08', 'TMUX1119': 'afe:TMUX1119',
    'BAT54S': 'Diode:BAT54S', 'BAV99': 'Diode:BAT54S', 'BNC': 'Connector:Conn_Coaxial',
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
two('R29', '174k', P33A, 'LM_FBP', B, 'FB+ top (R1)'); two('R5', '100k', 'LM_FBP', G, B, 'FB+ bottom (R2)')
# VOUT- = -1.22 V x (R3 + R4) / R4 (SNVSAF7C eq. 3): R3 OUT- to FB-, R4 FB- to GND
two('R6', '100k', VN, 'LM_FBN', B, 'R3 = 330k || 100k'); two('R25', '330k', VN, 'LM_FBN', B, 'R3 = 330k || 100k')
for r in ('R26', 'R27', 'R28'):
    two(r, '330k', 'LM_FBN', G, B, 'R4 = 3 x 330k ||')
two('R65', '4.7k', P33A, G, B, '+3.3 V_A bleed (PR-3)')

# ------------------------------------------------------------------ 3.3 V sense and the scope Vmid (sim/scope netlib, sim/powercal P8)
B = 'vmid'
two('R38', '249', P33D, 'V3S', B, 'shared sense filter from the Due 3.3 V pin')
two('C46', '10u', 'V3S', G, B, 'sense filter'); two('C15', '100n', 'V3S', G, B, 'sense node')
two('R20', '330k', 'V3S', 'VMID_TAP', B, 'Vmid divider top'); two('R21', '330k', 'VMID_TAP', G, B, 'Vmid divider bottom')
two('C47', '10u', 'VMID_TAP', G, B, 'Vmid tap (PW-7)')
part('U6', 'TLV9062', {'1': 'CH1_VBO', '2': 'CH1_VFB', '3': 'VMID_TAP', '4': G,
                       '5': 'VMID_TAP', '6': 'CH2_VFB', '7': 'CH2_VBO', '8': P33A}, B, 'A: CH1 Vmid, B: CH2 Vmid')
two('C18', '100n', P33A, G, B, 'TLV9062 supply')
for ch, rs, rfb, cfb, cn, c10 in (('CH1', ('R73', 'R74', 'R75', 'R76'), 'R63', 'C34', 'C16', range(48, 54)),
                                  ('CH2', ('R77', 'R78', 'R79', 'R80'), 'R64', 'C35', 'C17', range(54, 60))):
    for r in rs:
        two(r, '1R', f'{ch}_VBO', f'{ch}_VMID', B, f'{ch} Vmid isolation, 4 x 1R ||')
    two(rfb, '4.7k', f'{ch}_VMID', f'{ch}_VFB', B, f'{ch} Vmid DC feedback')
    two(cfb, '1u', f'{ch}_VBO', f'{ch}_VFB', B, f'{ch} Vmid HF feedback')
    for k in c10:
        two(f'C{k}', '10u', f'{ch}_VMID', G, B, f'{ch} Vmid node, 6 x 10 uF')
    two(cn, '100n', f'{ch}_VMID', G, B, f'{ch} Vmid node')

# ------------------------------------------------------------------ scope channels (sim/scope netlib core, variant hz)
SC = {  # ch: R1 100k, R1 330k x2, R3 100k, R3 330k x2, R2, C1, C2 12p (||), C2 12p (series), C2 20p (||), C2 20p (series),
        #     Rnp, op-amp, RF, RG, switch, Riso, clamp, supply R, 10 uF, 100 nF, switch cap, pull-down, BNC
    'CH1': ('R1', ('R10', 'R11'), 'R3', ('R14', 'R15'), 'R18', 'C1', 'C3', 'C4', 'C9', 'C10',
            'R52', 'U1', 'R30', 'R36', 'U10', 'R55', 'D5', 'R71', 'C44', 'C13', 'C28', 'R66', 'J1'),
    'CH2': ('R2', ('R12', 'R13'), 'R4', ('R16', 'R17'), 'R19', 'C2', 'C5', 'C6', 'C11', 'C12',
            'R53', 'U2', 'R31', 'R37', 'U11', 'R56', 'D6', 'R72', 'C45', 'C14', 'C29', 'R67', 'J2'),
}
ADC = {'CH1': 'A1', 'CH2': 'A0'}            # afe.md: CH1 on A1, CH2 on A0
RANGE = {'CH1': 'D38', 'CH2': 'D39'}
for ch, (r1a, (r1b, r1c), r3a, (r3b, r3c), r2, c1, c2p, c2s, c2q, c2t, rnp, u, rf, rg, sw, riso, dk, rsup, c10, cpin,
         csw, rpd, j) in SC.items():
    B = ch.lower()
    n = lambda s: f'{ch}_{s}'
    other(j, 'Connector:Conn_Coaxial', 'KH-BNC50-3511', BNC, {'1': n('IN'), '2': G}, B, f'{ch} input, right-angle')
    PARTS[-1].update(lcsc='C2837587', mpn='Kinghelm KH-BNC50-3511')
    # R1 = 330k + 330k + 100k from IN to N, C1 12 pF across all of it
    two(r1b, '330k', n('IN'), n('R1A'), B, 'R1 (760k), part 1'); two(r1c, '330k', n('R1A'), n('R1B'), B, 'R1, part 2')
    two(r1a, '100k', n('R1B'), n('N'), B, 'R1, part 3'); two(c1, '12p', n('IN'), n('N'), B, 'C1 across R1')
    two(r2, '330k', n('N'), n('VMID'), B, 'R2, N to this channel Vmid')
    # C2 = 20 || 12 || (12 s 20) = 39.5 pF, N to Vmid
    two(c2q, '20p', n('N'), n('VMID'), B, 'C2: 20 pF'); two(c2p, '12p', n('N'), n('VMID'), B, 'C2: 12 pF')
    two(c2s, '12p', n('N'), n('C2S'), B, 'C2: 12 pF in series'); two(c2t, '20p', n('C2S'), n('VMID'), B, 'C2: 20 pF in series')
    # R3 = 330k + 330k + 100k from N to the shared sense node
    two(r3b, '330k', n('N'), n('R3A'), B, 'R3 (760k), part 1'); two(r3c, '330k', n('R3A'), n('R3B'), B, 'R3, part 2')
    two(r3a, '100k', n('R3B'), 'V3S', B, 'R3, part 3, to the sense node')
    two(rnp, '680', n('N'), n('NP'), B, 'Rnp, clamp-current limit')
    part(u, 'OPA354', {'1': n('OUT'), '2': G, '3': n('NP'), '4': n('FB'), '5': n('VCC')}, B, f'{ch} op-amp')
    two(rsup, '1R', P33A, n('VCC'), B, 'supply branch'); two(c10, '10u', n('VCC'), G, B, 'supply branch')
    two(cpin, '100n', n('VCC'), G, B, 'supply pin')
    two(rf, '953', n('OUT'), n('FB'), B, 'RF'); two(rg, '249', n('FB'), n('VMID'), B, 'RG to this channel Vmid')
    # range switch across RF: SEL low (pulled down) = S1-D closed = +/-5 V (G ~ 1); high = open = +/-1.25 V
    part(sw, 'TMUX1119', {'1': RANGE[ch], '2': P33A, '3': G, '4': n('OUT'), '5': n('FB')}, B, 'range switch, S2 unused')
    two(csw, '100n', P33A, G, B, 'TMUX1119 supply')
    two(rpd, '4.7k', RANGE[ch], G, B, 'range pull-down: low = +/-5 V (value assumed)')
    two(riso, '22', n('OUT'), ADC[ch], B, 'Riso')
    part(dk, 'BAT54S', {'1': G, '3': ADC[ch], '2': P33A}, B, 'ADC-pin clamp after Riso')

# ------------------------------------------------------------------ AWG (sim/awg variant buf, sim/powercal ac_netlist)
B = 'awg'
two('R54', '680', 'DAC0', 'AWG_BIN', B, 'Rbin'); two('R22', '330k', 'AWG_BIN', G, B, 'Rbpl, to GND (PR-2)')
part('U4', 'OPA365', {'1': 'AWG_BO', '2': G, '3': 'AWG_BIN', '4': 'AWG_BO', '5': 'AWG_BV'}, B, 'DAC0 buffer, follower')
part('D3', 'BAT54S', {'1': P33A, '3': 'AWG_BV'}, B, 'DAC0 buffer supply, one die (pin 1 -> 3)')
two('C19', '100n', 'AWG_BV', G, B, 'DAC0 buffer supply pin')
two('R32', '953', 'AWG_BO', 'AWG_VP', B, 'Ra')
# Rb = 953 + (249 || 249) + 22, V+ to GND
two('R34', '953', 'AWG_VP', 'AWG_RB1', B, 'Rb, 953 part')
two('R39', '249', 'AWG_RB1', 'AWG_RB2', B, 'Rb, 249 || 249'); two('R40', '249', 'AWG_RB1', 'AWG_RB2', B, 'Rb, 249 || 249')
two('R57', '22', 'AWG_RB2', G, B, 'Rb, 22 part')
# Rf = 953 + (249 || 249) + 22, out to V-, with Cf 12 pF across the whole of it; Rg 953 to the AWG Vmid
two('R35', '953', 'AWG_OUT', 'AWG_RF1', B, 'Rf, 953 part')
two('R41', '249', 'AWG_RF1', 'AWG_RF2', B, 'Rf, 249 || 249'); two('R42', '249', 'AWG_RF1', 'AWG_RF2', B, 'Rf, 249 || 249')
two('R58', '22', 'AWG_RF2', 'AWG_INV', B, 'Rf, 22 part')
two('C7', '12p', 'AWG_OUT', 'AWG_INV', B, 'Cf'); two('R33', '953', 'AWG_INV', 'AWG_VMID', B, 'Rg')
part('U3', 'OPA365', {'1': 'AWG_OUT', '2': 'AWG_VNX', '3': 'AWG_VP', '4': 'AWG_INV', '5': 'AWG_VPX'}, B, 'AWG op-amp')
# supplies: 22 || 22 from each rail, 100 nF, then a series Schottky die into the pin
two('R59', '22', P33A, 'AWG_VCC', B, 'V+ filter 22 || 22'); two('R60', '22', P33A, 'AWG_VCC', B, 'V+ filter 22 || 22')
two('C21', '100n', 'AWG_VCC', G, B, 'V+ pin filter')
part('D1', 'BAT54S', {'1': 'AWG_VCC', '3': 'AWG_VPX'}, B, 'V+ series Schottky, one die (pin 1 -> 3)')
two('R61', '22', VN, 'AWG_VEE', B, 'V- filter 22 || 22'); two('R62', '22', VN, 'AWG_VEE', B, 'V- filter 22 || 22')
two('C22', '100n', 'AWG_VEE', G, B, 'V- pin filter')
part('D2', 'BAT54S', {'1': 'AWG_VNX', '3': 'AWG_VEE'}, B, 'V- series Schottky, one die (pin 1 -> 3)')
two('R51', '49.9', 'AWG_OUT', 'AWG_BNC', B, 'series 50 ohm (AW-4), 1206')
other('J3', 'Connector:Conn_Coaxial', 'KH-BNC50-3511', BNC, {'1': 'AWG_BNC', '2': G}, B, 'AWG output, right-angle')
PARTS[-1].update(lcsc='C2837587', mpn='Kinghelm KH-BNC50-3511')
# optional output clamp, op-amp side: 3 diodes to GND per polarity, footprints only (PR-4: not needed for any limit).
# D9 and D10 each hold two diodes of one string; their pin 3 is the string's internal node and is left open.
part('D9', 'BAV99', {'1': 'AWG_OUT', '2': 'AWG_CLA2'}, B, 'clamp string a, diodes 1-2', dnp=True)
part('D11', 'BAV99', {'1': 'AWG_CLA2', '3': G, '2': 'AWG_CLB1'}, B, 'clamp string a diode 3, string b diode 1', dnp=True)
part('D10', 'BAV99', {'1': 'AWG_CLB1', '2': 'AWG_OUT'}, B, 'clamp string b, diodes 2-3', dnp=True)
# the AWG's own fast Vmid: 330k / 330k off +3.3 V_A, 12 pF at the tap, OPA365 follower, NO output capacitor
two('R23', '330k', P33A, 'AWG_VMT', B, 'AWG Vmid divider top'); two('R24', '330k', 'AWG_VMT', G, B, 'AWG Vmid divider bottom')
two('C8', '12p', 'AWG_VMT', G, B, 'AWG Vmid tap: strays under 3 pF (check at layout)')
part('U5', 'OPA365', {'1': 'AWG_VMID', '2': G, '3': 'AWG_VMT', '4': 'AWG_VMID', '5': 'AWG_MV'}, B, 'AWG Vmid follower, no output C')
part('D4', 'BAT54S', {'1': P33A, '3': 'AWG_MV'}, B, 'Vmid buffer supply, one die (pin 1 -> 3)')
two('C20', '100n', 'AWG_MV', G, B, 'Vmid buffer supply pin')

# ------------------------------------------------------------------ calibration (architecture.md "Calibration", whatif/tee)
B = 'cal'
part('U8', 'REF3030', {'1': P33A, '2': VREF, '3': G}, B, 'drives the ladder and REFP0 directly')
two('C24', '100n', P33A, G, B, 'REF3030 VIN'); two('C32', '1u', P33A, G, B, 'REF3030 VIN bulk')
two('C26', '100n', VREF, G, B, 'REFP0, 2 x 100 nF'); two('C27', '100n', VREF, G, B, 'REFP0, 2 x 100 nF')
# ladder: 3 x 249 || at the bottom, 5 x 249 in series; taps 0.188 / 0.750 / 1.312 / 1.875 / 2.438 / 3.000 V on A2..A7
for r in ('R43', 'R44', 'R45'):
    two(r, '249', 'TAP1', G, B, 'ladder bottom, 3 x 249 ||')
for r, a, b in (('R46', 'TAP1', 'TAP2'), ('R47', 'TAP2', 'TAP3'), ('R48', 'TAP3', 'TAP4'), ('R49', 'TAP4', 'TAP5'),
                ('R50', 'TAP5', VREF)):
    two(r, '249', a, b, B, 'ladder series')
two('R81', '0R', VREF, 'AREF', B, 'PA-7: reference to the Due AREF pin, unfitted', dnp=True)
# AWG-sense divider k = 1/2 at the BNC (after the 49.9 ohm); the ratio switch moves its far end
two('R7', '100k', 'AWG_BNC', 'SNS_TAP', B, 'sense divider, BNC node to tap')
two('R8', '100k', 'SNS_TAP', 'SNS_D', B, 'sense divider, tap to far end (switch D, read by the ADC)')
part('U12', 'TMUX1119', {'1': 'D40', '2': P33A, '3': G, '4': 'SNS_S1', '5': 'SNS_D', '6': VREF}, B,
     'ratio switch: SEL low = S1 (AWG Vmid via 100k), high = S2 (3.0 V)')
two('C30', '100n', P33A, G, B, 'TMUX1119 supply')
two('R68', '4.7k', 'D40', G, B, 'ratio-switch pull-down (value assumed)')
two('R9', '100k', 'AWG_VMID', 'SNS_S1', B, 'AWG Vmid to S1')
# switch-pin clamps on D and S1 (architecture.md C1-q / C1-r); not in bom.txt's BAT54S count *(BOM gap)*
part('D7', 'BAT54S', {'1': G, '3': 'SNS_D', '2': P33A}, B, 'clamp on the ratio switch D')
part('D8', 'BAT54S', {'1': G, '3': 'SNS_S1', '2': P33A}, B, 'clamp on the ratio switch S1')
part('U9', 'ADS124S08', {
    '1': G,             # AINCOM = AGND (single-ended)
    '7': 'TAP1', '6': 'TAP2', '5': 'TAP3', '4': 'TAP4', '3': 'TAP5', '2': VREF,   # AIN0..AIN5: the six taps
    '22': 'SNS_TAP', '21': 'SNS_D',                                               # AIN8, AIN9
    '8': G,             # START/SYNC to DGND
    '9': 'D36', '10': 'D34', '11': 'D33', '12': 'D35',   # CS, DIN, SCLK, DOUT/DRDY: bit-banged SPI
    '14': G, '15': P33A, '16': P33A, '17': G, '18': P33A,    # DGND, IOVDD, DVDD, CLK to DGND (internal osc), RESET high
    '24': G, '26': P33A, '27': G, '28': G, '29': G, '30': VREF,   # REFCOM, AVDD, AVSS, AVSS-SW, REFN0, REFP0
}, B, 'precision ADC; DRDY, REFOUT, NC and AIN6/7/10/11 open (SBAS660C 10.1.5)')
two('C25', '100n', P33A, G, B, 'ADS124S08 DVDD + IOVDD (tied)')
two('C33', '1u', P33A, G, B, 'ADS124S08 AVDD, >= 330 nF')
two('R69', '4.7k', 'D36', P33A, B, 'CS pull-up (placeholder value)')

# ------------------------------------------------------------------ Due headers (docs/due-header-table.md, V03)
B = 'due'
HDR = {  # ref: (symbol, value, footprint, {pin: net})
    'J4': ('Connector_Generic:Conn_01x08', 'POWER0', 'Connector_PinSocket_2.54mm:PinSocket_1x08_P2.54mm_Vertical',
           {'4': P33D, '5': P5, '6': G, '7': G}),
    'J5': ('Connector_Generic:Conn_01x08', 'ADCL0', 'Connector_PinSocket_2.54mm:PinSocket_1x08_P2.54mm_Vertical',
           {'1': VREF, '2': 'TAP5', '3': 'TAP4', '4': 'TAP3', '5': 'TAP2', '6': 'TAP1', '7': 'A1', '8': 'A0'}),
    'J6': ('Connector_Generic:Conn_01x08', 'ADCH0', 'Connector_PinSocket_2.54mm:PinSocket_1x08_P2.54mm_Vertical',
           {'5': 'DAC0'}),
    'J7': ('Connector_Generic:Conn_01x08', 'PWML0', 'Connector_PinSocket_2.54mm:PinSocket_1x08_P2.54mm_Vertical', {}),
    'J8': ('Connector_Generic:Conn_01x08', 'COMMUNICATION0',
           'Connector_PinSocket_2.54mm:PinSocket_1x08_P2.54mm_Vertical', {}),
    'J9': ('Connector_Generic:Conn_01x10', 'PWMH0', 'Connector_PinSocket_2.54mm:PinSocket_1x10_P2.54mm_Vertical',
           {'7': G, '8': 'AREF'}),
    'J10': ('Connector_Generic:Conn_02x18_Odd_Even', 'XIO0',
            'afe:PinSocket_2x18_P2.54mm_Vertical_DueXIO',     # stock socket, odd / even exchanged (build_pcb.py)
            {'1': P5, '2': P5, '14': 'D33', '15': 'D34', '16': 'D35', '17': 'D36',
             '19': 'D38', '20': 'D39', '21': 'D40', '35': G, '36': G}),
}
for ref, (sym, val, fp, pins) in HDR.items():
    other(ref, sym, val, fp, pins, B, 'generic Mega stacking header, owner-fitted')
# ISO7380 courtyard (r 3.1 mm, a 5.7 mm head): the plain M3 hole's r 3.45 overlaps ADCH0's and XIO0's courtyards
# there; the M3 x 5 pan head is 5.6 mm *(check)*
other('MH1', 'Mechanical:MountingHole', 'M3 standoff', 'MountingHole:MountingHole_3.2mm_M3_ISO7380', {}, B,
      'over the Due hole (96.52, 2.54)')
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
