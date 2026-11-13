"""The AFE version 2 shield: every part and every pin's net, in one place.

This file is the source build_sch.py generates the schematic from, and the
reference check.py holds it to.  The circuits and values are the three
v2 studies' (sim/scope, sim/awg, sim/powercal, parts.csv in each) and every
part carries its study name in `sim` ("scope.R1a", "awg.R3", "pc.R_FB1") so
check.py can hold its value and LCSC number to that study's parts.csv.
Connectivity is checked against the studies' SPICE netlists by spicecmp.py
for the scope and the AWG; the power/reference/calibration block has no
netlist and is checked by value (check.py, block "cal").

A pin left out of a part's map is not connected: it must be listed in the
part's `nc` (or `nc='rest'` for a stacking header, whose unused pins pass
through to the stack's top, MC-9), or the generator refuses.

Reference designators (the studies reused R1..R8 and C1..C4; LR-11: the hundreds digit is the block, and each part's
`block` field says the same): 1xx CH1, 2xx CH2, 3xx AWG, 4xx POWER, 5xx REFCAL (reference and calibration), 6xx EDGE
(the Due pass-through headers, the I2C pull-ups, the AREF link, mounting).  U101 is the scope dual shared by both
channels and takes the 1xx number.  Connectors keep the J prefix inside their block's range: J101/J201/J301 the BNCs,
J501 the CAL jumper, J601..J607 the Due headers.  TP are test points, SH501 the loose shunt.

Own work, CC BY-SA 4.0.
"""

R0603 = 'Resistor_SMD:R_0603_1608Metric'
R1206 = 'Resistor_SMD:R_1206_3216Metric'
C0603 = 'Capacitor_SMD:C_0603_1608Metric'
C0805 = 'Capacitor_SMD:C_0805_2012Metric'
SOT23 = 'Package_TO_SOT_SMD:SOT-23'
SOP8 = 'Package_SO:SOIC-8_3.9x4.9mm_P1.27mm'
MSOP10 = 'Package_SO:MSOP-10_3x3mm_P0.5mm'
WSON12 = 'Package_SON:WSON-12-1EP_3x2mm_P0.5mm_EP1x2.65_ThermalVias'
BNC = 'afe:BNC_Kinghelm_KH-BNC50-3511_Horizontal'
TP = 'TestPoint:TestPoint_Pad_D1.5mm'
SOCKET8 = 'Connector_PinSocket_2.54mm:PinSocket_1x08_P2.54mm_Vertical'
SOCKET10 = 'Connector_PinSocket_2.54mm:PinSocket_1x10_P2.54mm_Vertical'
HDR3 = 'Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical'

# kind -> (value, LCSC, footprint, symbol).  Every passive is a JLC Basic part (V2-3, v2/jlc-basic.csv).
T = {
    '510k': ('510k 1%', 'C23192', R0603), '30k': ('30k 1%', 'C22984', R0603), '1M': ('1M 1%', 'C22935', R0603),
    '470k': ('470k 1%', 'C23178', R0603), '200k': ('200k 1%', 'C25811', R0603), '470R': ('470R 1%', 'C23179', R0603),
    '22R': ('22R 1%', 'C23345', R0603), '510R': ('510R 1%', 'C23193', R0603),
    '27k': ('27k 1%', 'C22967', R0603), '1R': ('1R 1%', 'C22936', R0603), '100R1206': ('100R 1%', 'C17901', R1206),
    '120k': ('120k 1%', 'C25808', R0603), '68k': ('68k 1%', 'C23231', R0603), '56k': ('56k 1%', 'C23206', R0603),
    '8.2k': ('8.2k 1%', 'C25981', R0603), '100k': ('100k 1%', 'C25803', R0603), '10k': ('10k 1%', 'C25804', R0603), '1.8k': ('1.8k 1%', 'C4177', R0603),
    '330R': ('330R 1%', 'C23138', R0603), '15k': ('15k 1%', 'C22809', R0603), '1k': ('1k 1%', 'C21190', R0603),
    '3.9k': ('3.9k 1%', 'C23018', R0603), '4.7k': ('4.7k 1%', 'C23162', R0603), '0R': ('0R', 'C21189', R0603),
    '22p': ('22p C0G', 'C1653', C0603), '12p': ('12p C0G', 'C38523', C0603), '10p': ('10p C0G', 'C1634', C0603),
    '100n': ('100n X7R', 'C14663', C0603), '1u': ('1u X5R', 'C15849', C0603),
    '10u': ('10u X5R 25V', 'C15850', C0805), '3k': ('3k 1%', 'C4211', R0603), '2.7k': ('2.7k 1%', 'C13167', R0603),
    '100R': ('100R 1%', 'C22775', R0603),
    'BAV99': ('BAV99', 'C2500', SOT23),
    'TPH2502': ('TPH2502-SR', 'C118223', SOP8),
    'LM27762': ('LM27762DSSR', 'C473398', WSON12),
    'REF3030': ('REF3030EAIDBZR', 'C54120492', SOT23),
    'ADS1115': ('ADS1115IDGSR', 'C37593', MSOP10),
}
SYM = {'TPH2502': 'afe:TPH2502', 'ADS1115': 'afe:ADS1115', 'LM27762': 'Regulator_SwitchedCapacitor:LM27762',
       'REF3030': 'Reference_Voltage:REF3030',
       'BAV99': 'Diode:BAT54S'}   # the three-pin series pair, pins 1 A1, 2 K2, 3 common (as version 1 drew the BAV99)

PARTS = []


def _add(p):
    PARTS.append(p)


def part(ref, kind, pins, block, sim='', note='', nc=(), dnp=False):
    val, lcsc, fp = T[kind]
    sym = SYM.get(kind) or ('Device:R' if fp.startswith('Resistor') else 'Device:C')
    _add(dict(ref=ref, sym=sym, value=val, fp=fp, lcsc=lcsc, pins=dict(pins), block=block, sim=sim, note=note,
              nc=tuple(nc), dnp=dnp, fitted_by='JLC'))


def two(ref, kind, a, b, block, sim='', note='', **kw):
    part(ref, kind, {'1': a, '2': b}, block, sim, note, **kw)


def other(ref, sym, value, fp, pins, block, note='', nc='rest', fitted_by='owner', lcsc=''):
    _add(dict(ref=ref, sym=sym, value=value, fp=fp, lcsc=lcsc, pins=dict(pins), block=block, sim='', note=note,
              nc=nc, dnp=False, fitted_by=fitted_by))


G, P5, P5F, P33A, VN, VREF = 'GND', '+5V_DUE', '+5V_F', '+3V3A', 'VNEG', 'VREF'
P33A_U = '+3V3A_U'   # the +3V3A segment at the scope dual's V+ pad, beyond bridge BR101

# ---------------------------------------------------------------- scope: one TPH2502 dual, +3.3 V_A only, V- at ground
# TPH2502 SOP-8 (datasheet pin figure): 1 OUTA, 2 -INA, 3 +INA, 4 V-, 5 +INB, 6 -INB, 7 OUTB, 8 V+
B = 'CH1'      # the shared dual belongs to both channels; it takes the 1xx number (U101) and block CH1
part('U101', 'TPH2502', {'1': 'CH1_OUT', '2': 'CH1_OUT', '3': 'CH1_NP', '4': G, '5': 'CH2_NP', '6': 'CH2_OUT',
                       '7': 'CH2_OUT', '8': P33A_U}, B, 'scope.U (shared)',
     'two unity followers: output straight to -IN (RF = 0); V- = GND, no negative-rail connection')
two('C104', '100n', P33A_U, G, B, 'scope.C (shared) 100nF', 'dual supply decoupling, at the pin')
two('C105', '1u', P33A_U, G, B, 'scope.C (shared) 1uF', 'dual supply decoupling, at the pin')
ADCPIN = {1: 'A1', 2: 'A0'}               # CH1 on A1, CH2 on A0 (version 1, afe.md)
for ch in (1, 2):
    n = lambda s: f'CH{ch}_{s}'
    b = ch * 100
    B = f'CH{ch}'
    other(f'J{b + 1}', 'Connector:Conn_Coaxial', 'KH-BNC50-3511', BNC, {'1': n('IN'), '2': G}, B,
          f'CH{ch} input BNC, right-angle', nc=(), lcsc='C2837587')
    two(f'R{b + 1}', '510k', n('IN'), n('M1'), B, 'scope.R1a', 'R1 first of two (540k)')
    two(f'R{b + 2}', '30k', n('M1'), n('N'), B, 'scope.R1b', 'R1 second of two')
    two(f'C{b + 1}', '22p', n('IN'), n('N'), B, 'scope.C1', 'C1 across R1')
    two(f'R{b + 3}', '1M', n('N'), n('M2'), B, 'scope.R2a', 'R2 first of two (1.51M)')
    two(f'R{b + 4}', '510k', n('M2'), G, B, 'scope.R2b', 'R2 second of two, to ground')
    two(f'R{b + 5}', '470k', n('N'), n('M3'), B, 'scope.R3a', 'R3 first of two (670k)')
    two(f'R{b + 6}', '200k', n('M3'), VREF, B, 'scope.R3b', 'R3 second of two, to the REF3030E output')
    two(f'C{b + 2}', '12p', n('N'), G, B, 'scope.Cn', 'Cn at the node')
    two(f'R{b + 7}', '470R', n('N'), n('NP'), B, 'scope.Rnp', 'Rnp, ahead of +IN')
    two(f'C{b + 3}', '10p', n('NP'), G, B, 'scope.Cpx', 'Cpx, +IN to ground')
    two(f'R{b + 8}', '22R', n('OUT'), 'CH2_RISO' if ch == 2 else ADCPIN[ch], B, 'scope.Riso', 'Riso, amplifier output to the Due ADC pin')
    part(f'D{b + 1}', 'BAV99', {'1': G, '3': 'CH2_RISO' if ch == 2 else ADCPIN[ch], '2': P33A_U if ch == 2 else P33A}, B,
         'scope.Dp',
         'ADC-pin clamp: GND / pin / +3.3 V_A')

# ---------------------------------------------------------------- AWG: one TPH2502 dual, both halves paralleled
# Follows sim/awg/awg.cir and parts.csv as they stood at 11:03 on 2026-11-12 (the offset filter Rvr / Cvr is back,
# Rf = Rg2 = 3k, Rbin 2.7k, and the 330 pF output pole is gone).  Designators are version 2's, the studies' in `sim`.
B = 'AWG'
part('U301', 'TPH2502', {'1': 'AWG_OA', '2': 'AWG_FB', '3': 'AWG_BIN', '4': VN, '5': 'AWG_BIN', '6': 'AWG_FB',
                       '7': 'AWG_OB', '8': P33A}, B, 'awg.U1',
     'both halves paralleled as one gain stage (V2-2)')
two('R306', '2.7k', 'DAC0', 'AWG_BIN', B, 'awg.R6', 'DAC0 series resistor, divider upper arm')
two('R307', '27k', 'AWG_BIN', G, B, 'awg.R7', 'divider lower arm: an undriven DAC0 commands ground')
two('R308', '1R', 'AWG_OA', 'AWG_VO', B, 'awg.R8', 'output balancing, half A')
two('R309', '1R', 'AWG_OB', 'AWG_VO', B, 'awg.R9', 'output balancing, half B')
two('R303', '3k', 'AWG_VO', 'AWG_FB', B, 'awg.R3', 'Rf, feedback')
two('C301', '10p', 'AWG_VO', 'AWG_FB', B, 'awg.C1', 'Cf across Rf')
two('R304', '3k', 'AWG_FB', 'AWG_VREF', B, 'awg.R4', 'Rg2: inverting node to the offset filter node, no Rg1')
two('R305', '100R', VREF, 'AWG_VREF', B, 'awg.R5', 'offset filter resistor Rvr, REF3030E output to the filter node')
two('C303', '10u', 'AWG_VREF', G, B, 'awg.C3', 'offset filter capacitor, one of two in parallel')
two('C304', '10u', 'AWG_VREF', G, B, 'awg.C4', 'offset filter capacitor, one of two in parallel')
two('R301', '100R1206', 'AWG_VO', 'AWG_BNC', B, 'awg.R1', 'back-termination, one of two in parallel (50R)')
two('R302', '100R1206', 'AWG_VO', 'AWG_BNC', B, 'awg.R2', 'back-termination, one of two in parallel (50R)')
two('C305', '100n', P33A, G, B, 'awg.C5', 'supply pin V+')
two('C306', '100n', VN, G, B, 'awg.C6', 'supply pin V-')
other('J301', 'Connector:Conn_Coaxial', 'KH-BNC50-3511', BNC, {'1': 'AWG_BNC', '2': G}, B, 'AWG output BNC, right-angle',
      nc=(), lcsc='C2837587')

# ---------------------------------------------------------------- power, reference, precision ADC (sim/powercal)
B = 'POWER'
two('R406', '1R', P5, P5F, B, 'pc.R_SENSE', '5 V feed sense, take only (PW-1)')
two('C401', '10u', P5F, G, B, 'pc.C_IN1', 'LM27762 VIN bulk')
two('C402', '10u', P5F, G, B, 'pc.C_IN2', 'LM27762 VIN bulk')
# LM27762 (WSON-12 DSS): 1 PGOOD, 2 FB+, 3 VIN, 4 GND, 5 CP, 6 OUT-, 7 FB-, 8 EN-, 9 C-, 10 C+, 11 OUT+, 12 EN+, 13 PAD
part('U401', 'LM27762', {'1': G, '2': 'LM_FBP', '3': P5F, '4': G, '5': 'LM_CP', '6': VN, '7': 'LM_FBN', '8': P5F,
                       '9': 'LM_C1N', '10': 'LM_C1P', '11': P33A, '12': P5F, '13': G}, B, 'pc.U1',
     'EN+ / EN- from VIN; PGOOD unused, to GND (SNVSAF7C table 4-1)')
two('C409', '1u', 'LM_C1P', 'LM_C1N', B, 'pc.C_FLY', 'flying capacitor')
two('C403', '10u', 'LM_CP', G, B, 'pc.C_CP1', 'CPOUT'); two('C404', '10u', 'LM_CP', G, B, 'pc.C_CP2', 'CPOUT')
two('C405', '10u', P33A, G, B, 'pc.C_OP1', 'OUT+'); two('C406', '10u', P33A, G, B, 'pc.C_OP2', 'OUT+')
two('C407', '10u', VN, G, B, 'pc.C_ON1', 'OUT-'); two('C408', '10u', VN, G, B, 'pc.C_ON2', 'OUT-')
two('R401', '120k', P33A, 'LM_FBP', B, 'pc.R_FB1', 'OUT+ feedback top: V+ = 1.2 (R1 + R2) / R2')
two('R402', '68k', 'LM_FBP', G, B, 'pc.R_FB2', 'OUT+ feedback bottom (>= 50k)')
two('R403', '56k', VN, 'LM_FB3M', B, 'pc.R_FB3a', 'OUT- feedback R3, first of two (64.2k)')
two('R404', '8.2k', 'LM_FB3M', 'LM_FBN', B, 'pc.R_FB3b', 'OUT- feedback R3, second of two')
two('R405', '100k', 'LM_FBN', G, B, 'pc.R_FB4', 'OUT- feedback bottom R4 (>= 50k): V- = -1.22 (R3 + R4) / R4')
two('R407', '1.8k', P33A, G, B, 'pc.R_BLEED', '+3.3 V_A bleed (PR-3)')
B = 'REFCAL'
part('U501', 'REF3030', {'1': P33A, '2': VREF, '3': G}, B, 'pc.U2', 'SOT-23: 1 VIN, 2 VOUT, 3 GND')
two('C502', '100n', P33A, G, B, 'pc.C_REFI', 'REF3030E input')
two('C501', '1u', VREF, G, B, 'pc.C_REFO', 'REF3030E output')
# ADS1115 (DGS, SBAS444E table 4-1): 1 ADDR, 2 ALERT/RDY, 3 GND, 4 AIN0, 5 AIN1, 6 AIN2, 7 AIN3, 8 VDD, 9 SDA, 10 SCL
part('U502', 'ADS1115', {'1': G, '3': G, '4': VREF, '5': 'TAP4', '6': 'ADS_TAP', '7': 'ADS_B', '8': P33A,
                       '9': 'SDA', '10': 'SCL'}, B, 'pc.U3',
     'AIN0 = REF3030E, AIN1 = 2/3 ladder tap, AIN2 = sense tap (via R510), AIN3 = sense bottom node B (via R511); differential pair AIN2-AIN3; '
     'ADDR to GND (0x48); ALERT/RDY unused', nc=('2',))
two('C503', '100n', P33A, G, B, 'pc.C_ADS', 'ADS1115 VDD')
two('R512', '4.7k', P33A, 'SDA', 'REFCAL', '', 'I2C pull-up SDA (required; 4.7k Basic, not in powercal/parts.csv)')
two('R513', '4.7k', P33A, 'SCL', 'REFCAL', '', 'I2C pull-up SCL (required)')
# Top-layer 0 ohm bridges the layout needs (afe.md LR-11 placeholders until the layout names the exact nets):
# BR101 (CH1) carries +3V3A over the A0 column to the scope dual's V+ pad; BR201 (CH2) carries CH2's route over CH1's run
# (the gap is in CH2's ADC-pin net, between Riso/the clamp D201 and the A0 pin).  Each joins two segment names of ONE electrical net; the
# netlist comparison merges them (spicecmp.BR rule: every BR part is a short).  Each sits in the block it serves.
two('BR101', '0R', P33A, P33A_U, 'CH1', '', 'top-layer 0R bridge: +3V3A to the scope dual V+ segment (placeholder net)')
two('BR201', '0R', 'CH2_RISO', 'A0', 'CH2', '', 'top-layer 0R bridge: CH2 Riso to the A0 pin segment (placeholder net)')
two('R514', '0R', VREF, 'AREF', 'REFCAL', '', 'PA-7: reference to the Due AREF pin, unfitted', dnp=True)

# ---------------------------------------------------------------- calibration ladder, sense divider (sim/powercal)
B = 'REFCAL'
LAD = [(G, 'TAP1'), ('TAP1', 'TAP2'), ('TAP2', 'TAP3'), ('TAP3', 'TAP4'), ('TAP4', 'TAP5'), ('TAP5', VREF)]
for k, (a, b) in enumerate(LAD, 1):
    two(f'R50{k}', '330R', a, b, B, f'pc.R_L{k}', f'ladder rung {k}: taps 1/6..5/6, then the reference at 6/6')
two('R507', '15k', 'AWG_BNC', 'SNS_T0', B, 'pc.R_SRT', 'sense divider top, from the AWG BNC node')
two('R508', '10k', 'SNS_T0', 'SNS_B', B, 'pc.R_SRB', 'sense divider bottom (k = 0.4)')
two('R509', '1k', 'SNS_B', VREF, B, 'pc.R_SRD', 'permanent default tie of the bottom node B to the REF3030E')
two('R510', '3.9k', 'SNS_T0', 'ADS_TAP', B, 'pc.R_SRS', 'tap to ADS1115 AIN2: the passive protection')
two('R511', '10k', 'SNS_B', 'ADS_B', B, 'pc.R_SRM', 'B to ADS1115 AIN3: matches the tap input\'s source impedance')

# ---------------------------------------------------------------- Due headers (docs/due-header-table.md, V03), calibration header
B = 'EDGE'
HDR = {
    'J601': ('Connector_Generic:Conn_01x08', 'POWER0', SOCKET8, {'5': P5, '6': G, '7': G}),
    'J602': ('Connector_Generic:Conn_01x08', 'ADCL0', SOCKET8,
           {'1': VREF, '2': 'TAP5', '3': 'TAP4', '4': 'TAP3', '5': 'TAP2', '6': 'TAP1', '7': 'A1', '8': 'A0'}),
    'J603': ('Connector_Generic:Conn_01x08', 'ADCH0', SOCKET8, {'5': 'DAC0'}),
    'J604': ('Connector_Generic:Conn_01x10', 'PWMH0', SOCKET10, {'7': G, '8': 'AREF', '9': 'SDA', '10': 'SCL'}),
    'J605': ('Connector_Generic:Conn_02x18_Odd_Even', 'XIO0', 'afe:PinSocket_2x18_P2.54mm_Vertical_DueXIO',
            {'35': G, '36': G}),
    # headers carrying no AFE signal: the stacking socket still passes every Due pin through (MC-9)
    'J606': ('Connector_Generic:Conn_01x08', 'PWML0', SOCKET8, {}),
    'J607': ('Connector_Generic:Conn_01x08', 'COMMUNICATION0', SOCKET8, {}),
}
for ref in sorted(HDR, key=lambda r: int(r[1:])):
    sym, val, fp, pins = HDR[ref]
    other(ref, sym, val, fp, pins, B, 'generic Mega stacking header, owner-fitted; unused pins pass through')
# V2-5: the calibration jumper, powercal's J_RAT / SH_RAT: a 1x3 male header, silkscreen "CAL", pins
# TAP_HI | B | TAP_CAL, hand-soldered, with one 2.54 mm shunt.  Shunt across pins 2-3 (B and the 1/2 tap, 1.5 V)
# calibrates (the "on" position, marked on the silkscreen); across 1-2 (B and the 2/3 tap, 2.0 V) is the one wrong
# placement; no shunt is the default tie.  Pin 1 is the HIGHER tap.
TAP_HI = 'TAP4'       # pin 1: the 2/3 ladder tap, 2.0 V
TAP_CAL = 'TAP3'      # pin 3: the 1/2 ladder tap, 1.5 V, the calibration node
other('J501', 'Connector_Generic:Conn_01x03', 'CAL', HDR3, {'1': TAP_HI, '2': 'SNS_B', '3': TAP_CAL},
      'REFCAL', 'V2-5 jumper "CAL" (pc.J_RAT): pin 1 TAP4 (2/3 tap), pin 2 B, pin 3 TAP3 (1/2 tap); shunt across 2-3 = '
         'calibrate (marked), across 1-2 = the wrong placement, off = default tie', nc=(), fitted_by='owner')
PARTS[-1]['sim'] = 'pc.J_RAT'
# powercal rows that are not schematic symbols: the loose shunt
NOT_A_SYMBOL = {'pc.SH_RAT': 'shunt'}
# hand-fitted by the owner (not placed by the board house); the shunt is a loose part, not a board footprint
HAND_FITTED = ['3 x BNC KH-BNC50-3511 (J101, J201, J301)', 'Mega stacking headers (J601-J607)', '1x3 male header (J501)',
               '1 x 2.54 mm shunt SH501 for J501 (loose part, pc.SH_RAT)', '2 x M2.5 standoff, nylon or brass, header-stack height (MH601, MH602) and their DIN 912 M2.5 screws, head 4.5 mm']
# Standoffs over the Due's mounting holes (Due frame, y up): the hole nearest the BNC overhang and the top-right hole.
# MH602 sits 3.81 mm from XIO0 pin 1 (93.98, 50.8): inside the outline; with the M2.5 DIN 912 head (4.5 mm)
# the clearance to that pad is about 0.7 mm (check at layout, README).
other('MH601', 'Mechanical:MountingHole', 'M2.5 standoff', 'MountingHole:MountingHole_2.7mm_M2.5', {}, B,
      'over the Due hole (96.52, 2.54)', nc=(), fitted_by='owner')
other('MH602', 'Mechanical:MountingHole', 'M2.5 standoff', 'MountingHole:MountingHole_2.7mm_M2.5', {}, B,
      'over the Due hole (90.17, 50.8)', nc=(), fitted_by='owner')
# Test points, unfitted top pads (TestPoint_Pad_D1.5mm, silkscreen label 0.8 mm), each in its block's range.  The value is
# the label to print; the net is the design's own.  +5V_F is the LM27762's filtered 5 V feed (after the sense resistor R406).
for ref, label, net, blk in (('TP101', 'A1', 'A1', 'CH1'), ('TP201', 'A0', 'A0', 'CH2'),
                             ('TP301', 'AWG_OUT', 'AWG_VO', 'AWG'),     # the stage output, before the back-termination
                             ('TP401', '+3V3A', P33A, 'POWER'), ('TP402', 'VNEG', VN, 'POWER'),
                             ('TP403', '+5V_F', P5F, 'POWER'), ('TP404', 'GND', G, 'POWER'),
                             ('TP501', 'VREF', VREF, 'REFCAL')):
    other(ref, 'Connector:TestPoint', label, TP, {'1': net}, blk, f'test point {label} (net {net})', nc=(), fitted_by='none')

PARTS_BY_REF = {p['ref']: p for p in PARTS}
assert len(PARTS_BY_REF) == len(PARTS), 'duplicate designator'


def nets(parts=None):
    """net -> sorted [(ref, pin)]"""
    out = {}
    for p in (PARTS if parts is None else parts):
        for pin, net in p['pins'].items():
            out.setdefault(net, []).append((p['ref'], pin))
    return {k: sorted(v) for k, v in out.items()}


if __name__ == '__main__':
    N = nets()
    for k in sorted(N):
        if len(N[k]) < 2:
            print('single-pin net', k, N[k])
    jlc = [p for p in PARTS if p['fitted_by'] == 'JLC' and not p['dnp']]
    print(len(PARTS), 'parts,', len(jlc), 'JLC placements,', len({p['lcsc'] for p in jlc}), 'LCSC types,', len(N), 'nets')
