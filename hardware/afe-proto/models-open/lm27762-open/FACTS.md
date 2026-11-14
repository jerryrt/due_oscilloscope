# LM27762 facts (clean room: datasheet only)

Written from the TI LM27762 datasheet Rev. C (SNVSAF7C) only; no vendor SPICE model was opened.

Row format: quantity | symbol | min | typ | max | unit | conditions | page | table/figure. Blank cell = not given. Pages are datasheet page numbers (printed). Pages 21-30 (mechanical/packaging/orderable) were not read for this spec.

## 1. Absolute maximum ratings and operating range (p4, Sec 5.1-5.3)

| quantity | symbol | min | typ | max | unit | conditions | page | table |
|---|---|---|---|---|---|---|---|---|
| VIN to GND or GND to VOUT | | | | 5.8 | V | | 4 | 5.1 |
| EN+, EN- | | GND-0.3 | | VIN | V | | 4 | 5.1 |
| CPOUT, OUT+, OUT- continuous output current | | | | 300 | mA | | 4 | 5.1 |
| OUT+, OUT- short-circuit to GND duration | | | | 1 | s | note: OUT may be shorted to GND for 1 s without damage but must be avoided; for TA = 85C, VOUT must not be shorted to GND or VIN | 4 | 5.1 note 3 |
| Continuous power dissipation | | | internally limited | | | | 4 | 5.1 |
| Max junction temperature | TJMAX | | | 150 | C | | 4 | 5.1 |
| Operating input voltage | VIN | 2.7 | | 5.5 | V | | 4 | 5.1 |
| Operating output current | IOUT | 0 | | 250 | mA | | 4 | 5.1 |
| Operating ambient temperature | TA | -40 | | 85 | C | | 4 | 5.1 / 5.3 |
| Operating junction temperature | TJ | -40 | | 125 | C | | 4 | 5.1 / 5.3 |
| Storage temperature | Tstg | -65 | | 150 | C | | 4 | 5.1 |
| ESD HBM (JS-001) | V(ESD) | | +-1000 | | V | | 4 | 5.2 |
| ESD CDM (JESD22-C101) | V(ESD) | | +-250 | | V | | 4 | 5.2 |

Operating input range: 2.7 V to 5.5 V (p1, p8, p12). Output range +-1.5 V to +-5 V. Output current up to +-250 mA.

## 2. Thermal (p4-5, Sec 5.4), DSS (WSON-12)

| quantity | symbol | value | unit |
|---|---|---|---|
| Junction-to-ambient | RthetaJA | 62.2 | C/W |
| Junction-to-case (top) | RthetaJC(top) | 54.7 | C/W |
| Junction-to-board | RthetaJB | 25.6 | C/W |
| Junction-to-top characterization | PsiJT | 1.8 | C/W |
| Junction-to-board characterization | PsiJB | 25.6 | C/W |
| Junction-to-case (bottom) | RthetaJC(bot) | 9.2 | C/W |

Thermal shutdown (p10, 6.3.6): shutdown when junction reaches 150 C (typ); released at 130 C (typ). Thermal cycling described as pulsing output voltage. Package: DSS WSON-12, 3 mm x 2 mm (p1). Thermal pad is ground, do not leave unconnected (p3).
Power dissipation equations (p16): PD-MAX = (TJ-MAX - TA)/RthetaJA; PD = PIN - POUT = VIN x (-IOUT- + IOUT+ + IQ) - (VOUT+ x IOUT+ + VOUT- x IOUT-); TA-MAX = TJ-MAX-OP - RthetaJA x PD-MAX, TJ-MAX-OP = 125 C.

## 3. Pinout (p3, Fig 4-1, Table 4-1), WSON-12 top view

Pins 1-6 down the left side, 12-7 down the right side (pin 1 top left, marked by circle), thermal pad in the middle.

| name | no. | type | description |
|---|---|---|---|
| PGOOD | 1 | Output | Power-good flag; open drain; logic 0 = power good, logic 1 = power not good. Connect to ground if not used |
| FB+ | 2 | Power | Feedback input; connect to external divider between OUT+ and GND. Do not leave unconnected |
| VIN | 3 | Power | Positive supply input |
| GND | 4 | Ground | Ground |
| CP | 5 | Power | Negative unregulated output voltage (charge pump output) |
| OUT- | 6 | Power | Regulated negative output |
| FB- | 7 | Power | Feedback input; connect to external divider between OUT- and GND. Do not leave unconnected |
| EN- | 8 | Input | Enable for charge pump and negative LDO, active high |
| C1- | 9 | Power | Negative terminal of flying cap C1 |
| C1+ | 10 | Power | Positive terminal of flying cap C1 |
| OUT+ | 11 | Power | Regulated positive output |
| EN+ | 12 | Input | Enable for positive LDO, active high |
| Thermal pad | - | Ground | Ground; do not leave unconnected |

## 4. Architecture (p1, p8-p11, p13-14; Fig 6.2 p9; Fig 7-2 p14)

- Negative rail: regulated inverting charge pump (output at CP, nominally -VIN at no load) followed by a negative LDO (OUT-). Positive rail: low-noise LDO from VIN directly (OUT+). Positive LDO is NOT behind the charge pump.
- Block diagram (Fig p9): VIN feeds Current Limit -> Switch Array/Switch Drivers (C1+, C1-, CP), a 2-MHz oscillator, positive LDO current limit. EN- drives oscillator, reference, and negative LDO; a current source from CP to ground (discharge) shown controlled by inverted EN-. Negative LDO: negative bandgap -> LPF -> error amp -> pass FET from CP to OUT-; feedback via LPF from FB-; internal pull-up "PU" resistor on OUT- enabled when EN- is low. Positive LDO: positive bandgap -> LPF -> error amp -> pass FET from VIN (through a current limit block) to OUT+; feedback via LPF from FB+; pull-down "PD" on OUT+ enabled when EN+ low. Power Good Monitoring block taps both FB nodes and drives PGOOD.
- Switching scheme (Fig 7-2 p14): four switches S1-S4 and flying cap C1; in one interval S2 and S4 open, S1 and S3 closed (C1 charges from VIN); in the other, S1 and S3 open, S2 and S4 closed (C1 charges CCP/ CPOUT, anode of CCP at ground, so output = -VIN at no load). Oscillator 2 MHz; a PFM comparator (monitoring CP via a divider to VIN) gates the oscillator drive.
- Fundamental switching frequency 2 MHz (typ) (p1, p8, p10).
- PFM/pulse-skipping (p10, 6.3.3): at light load the pump switches less; "frequency of pulsed operation is not limited and can drop into the sub-2-kHz range when unloaded"; as load increases pulsing frequency increases until it transitions to constant frequency (2 MHz). Table 5.5 note: at VIN = 5.5 V the charge pump may enter PWM mode in hot conditions. Output ripple can become large during transition between PFM and constant switching (p15).
- Output resistance equation (Eq 2, p14): ROUT = (2 x RSW) + [1/(fSW x C1)] + (4 x ESR_C1) + ESR_CCP, where RSW is the sum of on-resistances of the internal MOSFET switches. Statement that ESR of C1 counts 4x, CCP ESR once. (Datasheet text mislabels the inverter section once as "LM27761"; the equation applies to this device.)
- Charge pump + positive LDO each have 500 mA (typ) input current limit when output shorted to ground (p10, 6.3.2); thermal cycling expected while limiting.
- Undervoltage lockout (p10, 6.3.1): device forced to shutdown if VIN drops to 2.4 V; resumes normal operation if VIN rises above 2.6 V.
- Output discharge (p10, 6.3.4; p11, 6.4.1): in shutdown, outputs actively pulled to GND via internal 50 kohm between each OUT pin and ground (p8 text: positive LDO output has 50 kohm pulldown to ground; negative LDO output has 50 kohm pullup to ground, i.e. both pull toward ground).
- Headroom: care needed so both positive LDO and the inverting charge pump + negative LDO have enough headroom (p11, p12). Charge-pump minimum headroom estimable from max load current and charge pump output resistance (p12).

## 5. Electrical characteristics (p5, Table 5.5)

Typical: TA = 25 C; min/max over full temperature range. Unless otherwise specified: VIN = 5 V, CIN = COUT+ = COUT- = 2.2 uF, C1 = 1 uF, CPOUT = 4.7 uF.

| quantity | symbol | min | typ | max | unit | conditions | page | table |
|---|---|---|---|---|---|---|---|---|
| Supply (quiescent) current | IQ | | 390 | | uA | open circuit, no load, EN+, EN- tied to VIN (note: at VIN = 5.5 V charge pump may enter PWM mode in hot conditions) | 5 | 5.5 |
| Shutdown supply current | ISD | | 0.5 | 5 | uA | | 5 | 5.5 |
| Switching frequency | fSW | 1.7 | 2 | 2.3 | MHz | VIN = 3.6 V | 5 | 5.5 |
| Output resistance to CPOUT | RNEG | | 2.5 | | ohm | VIN = 5.5 V, IL = 100 mA | 5 | 5.5 |
| Negative LDO dropout | VLDO- | | 30 | | mV | IL = 100 mA, VOUT- = -5 V | 5 | 5.5 |
| PSRR OUT- | PSRR | | 50 | | dB | IL = 100 mA, VOUT- = -1.8 V, 10 kHz | 5 | 5.5 |
| Output noise OUT- | VN- | | 22 | | uVrms | IL = 80 mA, 10 Hz to 100 kHz | 5 | 5.5 |
| FB- reference voltage | VFB- | -1.238 | -1.22 | -1.202 | V | | 5 | 5.5 |
| Adjustable output voltage OUT- | VOUT- | -5 | | -1.5 | V | 5.5 V >= VIN >= 2.7 V | 5 | 5.5 |
| Load regulation OUT- | | | 34 | | uV/mA | 0 to 250 mA, VOUT = -1.8 V | 5 | 5.5 |
| Line regulation OUT- | | | 1.5 | | mV/V | 5 V >= VIN >= 2.7 V, IL = 50 mA | 5 | 5.5 |
| Positive LDO dropout | VLDO+ | | 45 | | mV | IL = 100 mA, VOUT = 5 V | 5 | 5.5 |
| PSRR OUT+ | PSRR | | 43 | | dB | IL = 100 mA, VOUT+ = 1.8 V, 10 kHz | 5 | 5.5 |
| Output noise OUT+ | VN+ | | 22 | | uVrms | IL = 80 mA, 10 Hz to 100 kHz | 5 | 5.5 |
| FB+ reference voltage | VFB+ | 1.182 | 1.2 | 1.218 | V | | 5 | 5.5 |
| Adjustable output voltage OUT+ | VOUT+ | 1.5 | | 5 | V | 5.5 V >= VIN >= 2.7 V | 5 | 5.5 |
| Load regulation OUT+ | | | 11 | | uV/mA | 0 to 250 mA, VOUT = 1.8 V | 5 | 5.5 |
| Line regulation OUT+ | | | 1.9 | | mV/V | 5 V >= VIN >= 2.7 V, IL = 50 mA | 5 | 5.5 |
| Enable input high | VIH | 1.2 | | | V | 5.5 V >= VIN >= 2.7 V | 5 | 5.5 |
| Enable input low | VIL | | | 0.4 | V | 5.5 V >= VIN >= 2.7 V | 5 | 5.5 |

Other stated values: 2.5 ohm inverter output impedance at VIN = 5 V (p1 features); 30 mV negative LDO dropout at 100 mA, VOUT = -5 V; 45 mV positive LDO dropout at 100 mA, VOUT = 5 V (p1).
Output current: +250 mA per rail (p1, 5.1); 300 mA absolute-max continuous (p4).
Note: the datasheet text elsewhere (Sec 1) quotes 390 uA IQ and 0.5 uA typical shutdown current.

## 6. Feedback equations (p13-14, Sec 7.2.2)

- OUT+: VOUT+ = 1.2 V x (R1 + R2) / R2 (Eq 1). R1 from OUT+ to FB+, R2 from FB+ to GND. R2 must be no less than 50 kohm. FB+ nominal reference 1.2 V (1.182 to 1.218). (Simplified schematic p1 shows FB+ at 1.182 to 1.218 V.)
- OUT-: VOUT- = -1.22 V x (R3 + R4) / R4 (Eq 3, text says "calculated using Equation 1" but the equation printed is 3). R3 from OUT- to FB-, R4 from FB- to GND. R4 must be no less than 50 kohm. FB- nominal -1.22 V (-1.238 to -1.202); simplified schematic p1 shows FB- range -1.238 V to -1.202 V.
- Output voltage window: OUT+ 1.5 V to 5 V; OUT- -1.5 V to -5 V.

## 7. Enable, PGOOD, start-up (p10-12)

- EN+ > 1.2 V enables positive LDO; EN- > 1.2 V enables negative charge pump and LDO (p11, 6.4.2). VIH min 1.2 V, VIL max 0.4 V.
- Both low: shutdown, both outputs disabled, quiescent current minimal; outputs pulled to ground by internal 50 kohm each.
- EN pins: "Enable inputs can be also shorted together and connected to VIN" (p1, p8); independent enables support independent power sequencing of the rails (p1, p8). Typical application (Fig 7-1) draws EN+ and EN- lines tied to VIN. The datasheet states that when EN inputs are tied to VIN for IQ measurement (Table 5.5).
- PGOOD (p8, p10, p12): open-drain, active low (low = good). Needs external pullup; 10 kohm to VIN recommended (RPU); connect pin to ground if not used. Monitors OUT+ and OUT-.
  Table 6-1 (p10) truth table:

| EN+ | EN- | OUT+ | OUT- | PGOOD |
|---|---|---|---|---|
| Low | Low | x | x | High |
| High | Low | <95% of target | x | High |
| High | Low | >95% of target | x | Low |
| Low | High | x | <95% of target | High |
| Low | High | x | >95% of target | Low |
| High | High | <95% of target | x | High |
| High | High | x | <95% of target | High |
| High | High | >95% of target | >95% of target | Low |

  (x = do not care.) PGOOD hysteresis/delay: not in the datasheet.
- Start-up (Fig 5-10, p7) and shutdown (Fig 5-11, p7) are oscilloscope captures only (200 us/div, 500 MS/s; channels VOUT+ 1 V/div?, PGOOD 5 V/div, EN 2 V/div, VOUT- 5 V/div as labelled in the legend). Qualitative: EN rises, VOUT- falls toward negative, VOUT+ steps up and PGOOD falls from high to low after both are up. No numeric start-up time or soft-start time given in text. Operating conditions of those captures not stated beyond the legend.

## 8. Recommended components (p12-p17)

| component | recommendation | notes | page |
|---|---|---|---|
| CIN | 4.7 uF low-ESR ceramic typical; min 2 uF effective at 250 mA load after DC-bias derating | Table 7-1 example uses 2.2 uF; Table 5.5 test uses 2.2 uF | 15, 13, 5 |
| C1 (flying) | 0.47 uF or 1 uF, 10 V, low-ESR ceramic in high-current apps; no polarised caps; too small -> cannot regulate at high load; too large -> larger input/CP ripple | Table 5.5 uses 1 uF | 15 |
| CCP / CPOUT | 4.7 uF low-ESR ceramic typical; 10 uF, 10 V low-ESR recommended for higher current; a 2 uF minimum effective is recommended to prevent toggling; example: 10 uF 10 V 0402 has ~2 uF at 5 V bias | Table 7-1 uses 4.7 uF | 15 |
| COUT+, COUT- | 2.2 uF ceramic required minimum for stable operation, located close to output | affects stability, ripple, noise, PSRR, transient | 16 |
| RPU | 10 kohm to VIN (PGOOD) | optional | 12-13 |

- Capacitor type: ceramic (SMD MLCC) recommended; very low ESR (<= 15 mohm typical). Tantalum, OS-CON, aluminium electrolytic generally not recommended (p14).
- Dielectric: X7R / X5R preferred (X7R +-15% -55 to +125 C; X5R +-15% -55 to +85 C). Y5V/Z5U generally not recommended (Y5V 22%/-82% over -30 to +85 C; Z5U 22%/-56% over 10 to 85 C; 1 uF Y5V/Z5U can drop to 0.1 uF) (p15).
- Net capacitance falls with DC bias; use caps rated well above operating voltage; evaluate with production capacitor (p15).
- Specific ESR upper limit for stability, specific capacitance min/max for CPOUT, CIN: only "minimum recommended CIN 2 uF" and COUT "2.2 uF" given; no numeric ESR window beyond <= 15 mohm typical statement.
- Table 7-1 example (p13): VIN 3.3 to 4.2 V; output +-3 V; output current 10 mA; CIN, COUT+, COUT- 2.2 uF; CCP 4.7 uF; RPU 10 kohm.

## 9. Layout guidance (p17, 7.4.1; Fig 7-5 p18)

- CIN on top layer, same layer as device, as close as possible; short wide traces to both VIN and GND pins.
- CCPOUT on top layer, as close as possible to CP (VOUT) and GND pins; returns of CIN and CCPOUT must come together at one point close to the GND pin; short wide traces.
- C1 on top layer as close as possible; short wide traces to C1+ and C1-.
- COUT+, COUT- on top layer, as close as possible to respective OUT pin; ground connection of COUT must go back to the GND connection at the thermal pad.
- R1 to R4 on top layer close to respective FB pin; ground connection of R2, R4 back to GND at the thermal pad.
- Avoid long trace lengths, narrow traces, vias (parasitic inductance/resistance degrade performance especially in transients).
- Fig 7-5 (p18): top-view example. Top row of device pins (left to right) EN+, OUT+, C1+, C1-, EN-, FB-; bottom row PGOOD, FB+, VIN, GND, CP, OUT-. Positive rail trace from OUT+ to load with COUT+ and R1/R2 on the upper left; C1 across C1+/C1- above; R3/R4 and COUT- on right with a negative-rail trace to load; CIN and CCPOUT below on VIN/GND/CP pads with "To Supply" and "To GND Plane" traces; thermal pad central. PGOOD pullup not shown in the figure. (Pin positions in this figure show a different pin order from Fig 4-1 in an upright orientation; as drawn they are per the figure.)

## 10. Typical characteristic curves (p6-7, p17), digitised

Reading accuracy: gridline-level, roughly +-0.1 of the minor division of each axis unless stated; frequencies on log axes +-20% of x. Curves are TI typical data, conditions as stated per figure.

### Fig 5-1 (p6) Output voltage ripple (mV) vs output current (mA); VIN = 3.7 V, VOUT = +-3 V; legend VOUT+ black, VOUT- red
VOUT+ (black), (mA, mV): (0, 0.7), (5, 1.7), (10, 2.2), (20, 1.8), (35, 2.0), (45, 2.0), (55, 1.3), (65, 1.1), (75, 0.7), (100, 0.9), (125, 1.1), (150, 1.35), (175, 1.7), (200, 2.1), (225, 2.3), (250, 2.6). Accuracy +-0.1 mV, +-5 mA.
VOUT- (red), (mA, mV): (0, 0.8), (25, 0.8), (50, 0.75), (75, 0.7), (100, 0.95), (125, 1.3), (150, 1.6), (175, 1.8), (200, 2.2), (225, 2.8), (250, 3.3). Accuracy +-0.15 mV.

### Fig 5-2 (p6) Output voltage ripple (mV) vs input voltage (V); VOUT = +-3 V, IOUT = +-100 mA; VOUT- black, VOUT+ red
VOUT- (black), (V, mV): (3.0, 2.25), (3.1, 1.95), (3.2, 1.4), (3.25, 1.2), (3.4, 1.2), (3.6, 1.28), (3.8, 1.33), (4.0, 1.35), (4.1, 1.37). Accuracy +-0.05 mV, +-0.05 V.
VOUT+ (red), (V, mV): (3.0, 2.2), (3.2, 2.17), (3.3, 2.15), (3.4, 2.25), (3.45, 1.4), (3.5, 1.3), (3.6, 1.25), (3.8, 1.22), (4.0, 1.2), (4.1, 1.2). Step between 3.4 and 3.5 V is very steep.

### Fig 5-3 (p6) LDO dropout voltage (mV) vs output current (mA); VOUT = +-3.3 V; both straight lines through (0,0)
VOUT+ (black): (0, 0), (125, 59), (250, 117) => ~0.47 ohm.
VOUT- (red): (0, 0), (125, 40), (250, 80) => ~0.32 ohm.
Accuracy +-3 mV.

### Fig 5-4 (p6) Charge pump output resistance RCP (ohm) vs IOUT (A), log-log; VIN = 5.5 V
25 C and -40 C (nearly coincident), (A, ohm): (0.001, 300), (0.003, 120), (0.01, 35), (0.03, 7), (0.06, 3.5), (0.1, 2.5), (0.3, 2.2) (low end flattens ~2.0 for -40 C).
85 C, (A, ohm): (0.001, 170), (0.003, 70), (0.01, 22), (0.03, 3), (0.1, 2.8), (0.3, 2.8).
Accuracy: log axis, about +-25% in ohm, +-20% in A. The datasheet RNEG = 2.5 ohm at 100 mA is consistent.

### Fig 5-5 (p6) Line regulation OUT-, output voltage (V) vs input voltage (V); VOUT = -3.3 V; 0, 50, 100 mA
0 mA (black): (3.25, -3.27), (3.4, -3.33), (3.5, -3.338), (4.5, -3.338), (5.5, -3.345).
50 mA (red): (3.25, -3.245), (3.4, -3.30), (3.5, -3.34), (4.5, -3.34), (5.5, -3.34).
100 mA (gray): (3.25, -3.10), (3.35, -3.17), (3.4, -3.27), (3.5, -3.32), (3.55, -3.338), (4.5, -3.34), (5.5, -3.34).
Output (negative) magnitude collapses below about VIN = 3.5 V, i.e. headroom limit; accuracy +-0.005 V, +-0.05 V.

### Fig 5-6 (p6) Line regulation OUT+, output voltage (V) vs input voltage (V); VOUT = 3.3 V
0 mA (black): (3.25, 3.292), (4.5, 3.290), (5.5, 3.288).
50 mA (red): (3.25, 3.295), (4.25, 3.294), (4.75, 3.292), (5.0, 3.290), (5.25, 3.288), (5.5, 3.280).
100 mA (gray): (3.25, 3.302), (3.5, 3.300), (4.25, 3.299), (4.75, 3.295), (5.0, 3.291), (5.25, 3.288), (5.5, 3.282).
Accuracy +-0.0015 V.

### Fig 5-7 (p7) Load regulation OUT-, output voltage (V) vs output current (mA); VIN = 4.3 V, VOUT = -3.3 V
-40 C (black): (0, -3.325), (30, -3.330), (60, -3.332), (80, -3.335), (120, -3.333), (180, -3.330), (240, -3.327).
+25 C (red): (0, -3.338), (60, -3.341), (120, -3.339), (180, -3.337), (240, -3.335).
+85 C (gray): (0, -3.349), (60, -3.350), (120, -3.349), (180, -3.348), (240, -3.346).
Accuracy +-0.003 V.

### Fig 5-8 (p7) Load regulation OUT+, output voltage (V) vs output current (mA); VIN = 4.3 V, VOUT = 3.3 V
-40 C (black): (0, 3.2825), (125, 3.282), (250, 3.281).
+25 C (red): (0, 3.290), (125, 3.288), (250, 3.287).
+85 C (gray): overlaps the red trace within reading accuracy (not separately legible).
Accuracy +-0.002 V.

### Fig 5-9 (p7) Efficiency (%) vs output current (mA); VIN = 5.5 V, OUT- loaded
VOUT = -5 V (red): (1, 5), (5, 40), (10, 53), (25, 65), (50, 71), (75, 77), (100, 80), (150, 84), (200, 85.5), (250, 86).
VOUT = -3.3 V (black): (1, 5), (5, 25), (10, 37), (25, 47), (50, 51), (75, 54), (100, 55), (150, 57), (200, 58), (250, 58.5).
Accuracy +-2 percentage points; load-current axis +-5 mA; first-point values below 10 mA are rough.

### Fig 7-3 (p17) PSRR (dB) vs frequency (Hz) for OUT-; 10 Hz to 100 kHz, log x; legend: black VIN=3.7 V IOUT=100 mA, red VIN=3.7 V IOUT=10 mA, gray VIN=3.3 V IOUT=10 mA
Black, (Hz, dB): (10, -53), (100, -53), (1k, -50), (3k, -47), (10k, -45), (30k, -40), (50k, -38), (80k, -43), (100k, -46)  (a small peak near 50-60 kHz).
Red: (10, -53), (100, -53), (1k, -51), (3k, -48), (10k, -45), (30k, -38), (60k, -28), (70k, -45), (100k, -50) (sharp peak near 60 kHz then dip).
Gray: (10, -52), (100, -52), (1k, -49), (3k, -45), (10k, -35), (30k, -28), (45k, -22), (50k, -28) then drops (curve after peak not clearly legible).
Accuracy +-3 dB, frequency +-25%. The three-trace identification of peak positions is rough. Datasheet scalar: -50 dB at 10 kHz, 100 mA, VOUT- = -1.8 V (Table 5.5).

### Fig 7-4 (p17) PSRR (dB) vs frequency for OUT+; legend: VIN=3.7 V/100 mA (black), 3.3 V/100 mA (red), 3.7 V/10 mA (gray), 3.3 V/10 mA (blue); curves nearly coincident
Representative, (Hz, dB): (10, -65), (30, -65), (100, -64), (1k, -61), (3k, -57), (10k, -50), (30k, -40), (70k, -30), (100k, -26).
Accuracy +-3 dB below 1 kHz at 10 Hz-30 Hz, +-2 dB elsewhere; frequency +-25%. Small notch near 10 Hz on the red trace. Datasheet scalar: -43 dB at 10 kHz, 100 mA, VOUT+ = 1.8 V (Table 5.5), which differs from the plotted -50 dB at 10 kHz (plotted at different VOUT/VIN conditions: Fig 7-4 does not state VOUT).

## 11. Ripple specs and test conditions

- No ripple specification in Table 5.5. Ripple appears only in Fig 5-1 (vs load) and Fig 5-2 (vs VIN), with VOUT = +-3 V, VIN = 3.7 V (Fig 5-1) or IOUT = +-100 mA (Fig 5-2). Bandwidth and measurement capacitors for the ripple curves: not in the datasheet.
- Output noise: 22 uVrms each rail, 80 mA, 10 Hz to 100 kHz (Table 5.5).

## Gaps

Not in the datasheet:
- Numeric start-up time, soft-start time or inrush current (only Fig 5-10 scope capture, no numeric values).
- Numeric PGOOD delay, hysteresis, or threshold tolerance beyond "95% of target value"; PGOOD pull-down on-resistance or leakage; PGOOD sink-current rating.
- Enable pin input current/resistance or hysteresis; enable pin internal pull-up/down; explicit statement that EN pins must not float.
- Current-limit min/max values (only 500 mA typ input current limit for charge pump and positive LDO; no output-current-limit for OUT- LDO as a separate number).
- Quiescent current for each rail separately, or vs VIN/temperature; IQ in PFM vs PWM mode; the PFM threshold current; the PFM frequency range beyond "sub-2 kHz".
- Dropout vs temperature; line regulation or noise vs temperature; the exact noise spectrum density.
- Switching frequency over VIN or temperature beyond min/typ/max at VIN = 3.6 V.
- Charge pump switch on-resistances individually (RSW); ESR numeric ceiling for stability; maximum capacitance values; CIN ESR.
- Output ripple specification in the electrical table; ripple measurement bandwidth.
- Efficiency curves for OUT+ alone or for VIN other than 5.5 V; ripple vs load at other VIN.
- Transient (load/line step) response curves or numeric values.
- Thermal shutdown hysteresis other than 150 C/130 C typ; UVLO hysteresis given only as 2.4 V falling / 2.6 V rising.
- Internal discharge resistor tolerance (50 kohm stated without tolerance); the 50 kohm is the only discharge value.
- PSRR at frequencies other than the plotted curves; Fig 7-3/7-4 conditions on VOUT not stated.
- Any SPICE-relevant internal parameters (error amp gain/bandwidth, bandgap values other than VFB, pass-device size, LPF corner frequencies, oscillator duty cycle, dead time).
- Packaging detail from pages 21-30 (not read for this document).
