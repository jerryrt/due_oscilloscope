# ADS1115 analog-input facts (clean room: datasheet only)

Written from the TI ADS111x datasheet Rev. E (SBAS444E) only; no vendor SPICE model was opened.

Conventions: page = PDF page number printed on the datasheet page (the printed page number equals the PDF page index here). "-" = not stated. Electrical Characteristics (Sec 5.5) conditions: VDD = 3.3 V, DR = 8 SPS, FSR = +/-2.048 V unless noted; min/max over TA = -40 to +125 C, typ at 25 C.

## 1. Supply and absolute maximum ratings

| quantity | symbol | min | typ | max | unit | conditions | page | table/figure |
|---|---|---|---|---|---|---|---|---|
| Supply voltage (abs max) | VDD to GND | -0.3 | - | 7 | V | | 4 | Sec 5.1 |
| Analog input voltage (abs max) | AIN0..AIN3 | GND - 0.3 | - | VDD + 0.3 | V | | 4 | Sec 5.1 |
| Digital input voltage (abs max) | SDA, SCL, ADDR, ALERT/RDY | GND - 0.3 | - | 5.5 | V | | 4 | Sec 5.1 |
| Continuous input current (abs max) | - | -10 | - | 10 | mA | any pin except supply pins | 4 | Sec 5.1 |
| Operating ambient temperature (abs max) | TA | -40 | - | 125 | C | | 4 | Sec 5.1 |
| Junction temperature (abs max) | TJ | -40 | - | 150 | C | | 4 | Sec 5.1 |
| Storage temperature | Tstg | -60 | - | 150 | C | | 4 | Sec 5.1 |
| ESD HBM / CDM | V(ESD) | - | +/-2000 / +/-500 | - | V | JS-001 / JESD22-C101 | 4 | Sec 5.2 |
| Power supply (recommended) | VDD to GND | 2 | - | 5.5 | V | | 4 | Sec 5.3 |
| Absolute input voltage (recommended) | V(AINx) | GND | - | VDD | V | | 4 | Sec 5.3 |
| Full-scale input voltage range (recommended) | FSR | +/-0.256 | - | +/-6.144 | V | VIN = V(AINP) - V(AINN); expresses ADC scaling only; no more than VDD + 0.3 V may be applied to the inputs | 4 | Sec 5.3 |
| Operating ambient temperature (recommended) | TA | -40 | - | 125 | C | | 4 | Sec 5.3 |
| Supply current, power-down | IVDD | - | 0.5 | 2 (5 over temp range) | uA | TA = 25 C typ/max 2; 5 is the over-temperature max | 6 | Sec 5.5 |
| Supply current, operating | IVDD | - | 150 | 200 (300 over temp range) | uA | TA = 25 C typ/max 200; 300 over temperature | 6 | Sec 5.5 |
| Power dissipation | PD | - | 0.9 / 0.5 / 0.3 | - | mW | VDD = 5.0 / 3.3 / 2.0 V | 6 | Sec 5.5 |

Text facts on input protection (p13, Sec 7.3.1; p29, Sec 9.1.3):
- ESD diodes connect each analog input to VDD and to GND (Fig 7-4). Keep GND - 0.3 V < V(AINx) < VDD + 0.3 V to prevent the ESD diodes turning on (Eq. 3).
- If the inputs can violate this, use external Schottky diodes and series resistors to limit current. Overdriving one input on the ADS1115 can affect conversions on other inputs.
- Device can be permanently damaged by input voltages exceeding approximately 300 mV beyond the rails for extended periods. Analog inputs can withstand continuous currents as large as 10 mA.
- Devices cannot accept negative voltages on either input (p28, Sec 9.1.1). Single-ended signals range 0 V up to the lower of +VDD or +FS; no linearity loss within the input range (p29).
- If VDD < FSR (e.g. VDD = 3.3 V, FSR = +/-4.096 V), full-scale code cannot be reached; only differential signals up to |VIN| = 3.3 V can be measured, codes beyond are unused (p15, Sec 7.3.3).
- Unused analog inputs: float or tie to GND (p29, Sec 9.1.4).

## 2. Input multiplexer (ADS1115) and device variants

| quantity | symbol | value | page | table/figure |
|---|---|---|---|---|
| Inputs | AIN0..AIN3 | 4 single-ended or 2 differential; AIN0 or AIN1 also measurable differentially vs AIN3 | 13 | Sec 7.3.1, Fig 7-4 |
| MUX[2:0] = 000 (reset default) | - | AINP = AIN0, AINN = AIN1 | 25 | Table 8-3 |
| MUX = 001 | - | AINP = AIN0, AINN = AIN3 | 25 | Table 8-3 |
| MUX = 010 | - | AINP = AIN1, AINN = AIN3 | 25 | Table 8-3 |
| MUX = 011 | - | AINP = AIN2, AINN = AIN3 | 25 | Table 8-3 |
| MUX = 100 | - | AINP = AIN0, AINN = GND | 25 | Table 8-3 |
| MUX = 101 | - | AINP = AIN1, AINN = GND | 25 | Table 8-3 |
| MUX = 110 | - | AINP = AIN2, AINN = GND | 25 | Table 8-3 |
| MUX = 111 | - | AINP = AIN3, AINN = GND | 25 | Table 8-3 |
| Single-ended mode | - | negative input of ADC is internally connected to GND by a switch within the MUX | 13 | Sec 7.3.1 |
| Single-ended output codes | - | 0 to 32767 (Fig 9-2 annotation) | 29 | Fig 9-2 |
| AIN3 as common point | - | negative differential voltages allowed when GND < V(AIN3) < VDD; common-mode noise attenuation not offered | 29 | Sec 9.1.2 |
| ADS1113 / ADS1114 | - | no MUX; AINP = AIN0, AINN = AIN1; ADS1113 FSR fixed +/-2.048 V (not the ADS1115, listed for context) | 13, 15 | Sec 7.3.1, 7.3.3 |
| MUX structure (Fig 7-4) | - | each AINx has a diode to VDD and a diode to GND; switches route each AINx to AINP or AINN bus; AINN bus also has a switch to GND | 13 | Fig 7-4 |
| Mux/switch on-resistance, mux capacitance, channel crosstalk, channel-to-channel settling | - | not in the datasheet | - | - |

## 3. Input impedance (Sec 5.5, p5)

| quantity | symbol | min | typ | max | unit | conditions | page | table/figure |
|---|---|---|---|---|---|---|---|---|
| Common-mode input impedance | ZCM | - | 10 | - | Mohm | FSR = +/-6.144 V | 5 | Sec 5.5 |
| Common-mode input impedance | ZCM | - | 6 | - | Mohm | FSR = +/-4.096 V and +/-2.048 V | 5 | Sec 5.5 |
| Common-mode input impedance | ZCM | - | 3 | - | Mohm | FSR = +/-1.024 V | 5 | Sec 5.5 |
| Common-mode input impedance | ZCM | - | 100 | - | Mohm | FSR = +/-0.512 V and +/-0.256 V | 5 | Sec 5.5 |
| Differential input impedance | ZDIFF | - | 22 | - | Mohm | FSR = +/-6.144 V | 5 | Sec 5.5 |
| Differential input impedance | ZDIFF | - | 15 | - | Mohm | FSR = +/-4.096 V | 5 | Sec 5.5 |
| Differential input impedance | ZDIFF | - | 4.9 | - | Mohm | FSR = +/-2.048 V | 5 | Sec 5.5 |
| Differential input impedance | ZDIFF | - | 2.4 | - | Mohm | FSR = +/-1.024 V | 5 | Sec 5.5 |
| Differential input impedance | ZDIFF | - | 710 | - | kohm | FSR = +/-0.512 V and +/-0.256 V | 5 | Sec 5.5 |

Footnote (p5-6): +/-6.144 V and +/-4.096 V express ADC scaling only; no more than VDD + 0.3 V may be applied.

Text (p14, Sec 7.3.2):
- Common-mode impedance is measured by applying a common-mode signal to shorted AINP/AINN and measuring the average current per pin; "approximately 6 Mohm for the default full-scale range".
- Differential impedance is measured by applying a differential signal with one input held at 0.7 V; the current through the pin connected to 0.7 V is the differential current and "scales with the full-scale range".
- Equivalent circuit (Fig 7-5): ZCM from AINP to 0.7 V and from AINN to 0.7 V; ZDIFF between AINP and AINN.
- Zeff = VIN / IAVERAGE. The oscillator frequency drifts slightly with temperature so input impedances also drift; stated as negligible for most applications. Input impedance may need buffering if source impedance is high; active buffers add noise, offset and gain error.

## 4. Switched-capacitor input structure (Sec 7.3.2, p14, Fig 7-5 / 7-6)

| quantity | symbol | value | page | table/figure |
|---|---|---|---|---|
| Internal oscillator | - | 1 MHz | 14, 15 | Sec 7.3.2, 7.3.5 |
| Modulator frequency | fMOD | 250 kHz (oscillator divided by 4) | 14 | Sec 7.3.2, Fig 7-5 |
| Topology | - | CA1 from AINP to ground-side node, CA2 from AINN to ground-side node, CB between the two; switches S1 (sampling) and S2 (discharge); S2 side returns to 0.7 V nodes | 14 | Fig 7-5 |
| Sampling phase | - | S1 closed: CA1 charged to V(AINP), CA2 to V(AINN), CB to V(AINP) - V(AINN) | 14 | Sec 7.3.2 |
| Discharge phase | - | S1 opened then S2 closed: CA1 and CA2 discharge to approximately 0.7 V; CB discharges to 0 V | 14 | Sec 7.3.2 |
| Switch timing | - | S1 and S2 are non-overlapping; S1 ON pulse then S2 ON pulse each period; tSAMPLE marked on S1 pulse | 14 | Fig 7-6 |
| Capacitor values CA1, CA2, CB | - | not in the datasheet (text: "The capacitors used in this input stage are small"; "capacitor values set the resistance and switching rate") | 14 | Sec 7.3.2 |
| Switch on-resistance, tSAMPLE value | - | not in the datasheet | - | - |
| Impedance scaling | - | average loading appears resistive (Zeff = VIN/IAVERAGE); differential impedance scales with FSR (values in Sec 3 above); how the PGA changes CA/CB or the switching rate is not stated | 14 | Sec 7.3.2 |
| Transient charge current | - | "very small transient current" drawn from the source; no magnitude given | 14 | Sec 7.3.2 |

## 5. Input leakage current

| quantity | symbol | min | typ | max | unit | conditions | page | table/figure |
|---|---|---|---|---|---|---|---|---|
| Analog input leakage / bias current | - | not in the datasheet | - | - | - | - | - | - |
| Digital input leakage (NOT analog, listed for disambiguation) | - | -10 | - | 10 | uA | GND < VDIG < VDD | 5 | Sec 5.5 |

## 6. PGA full-scale ranges (Sec 7.3.3, p15; Table 8-3, p26)

| PGA[2:0] | FSR (V) | LSB size (uV) | page | table/figure |
|---|---|---|---|---|
| 000 | +/-6.144 (see footnote) | 187.5 | 15, 26 | Table 7-1, Table 8-3 |
| 001 | +/-4.096 (see footnote) | 125 | 15, 26 | Table 7-1, Table 8-3 |
| 010 (reset default) | +/-2.048 | 62.5 | 15, 26 | Table 7-1, Table 8-3 |
| 011 | +/-1.024 | 31.25 | 15, 26 | Table 7-1, Table 8-3 |
| 100 | +/-0.512 | 15.625 | 15, 26 | Table 7-1, Table 8-3 |
| 101 | +/-0.256 | 7.8125 | 15, 26 | Table 7-1, Table 8-3 |
| 110 | +/-0.256 | 7.8125 | 26 | Table 8-3 |
| 111 | +/-0.256 | 7.8125 | 26 | Table 8-3 |

- LSB = FSR / 2^16 (Eq. 4); 16-bit result, two's complement (threshold registers stated as 2's complement; negative codes exist). Resolution: 16 bits, no missing codes (p5).
- Footnote: for +/-6.144 V and +/-4.096 V the FSR expresses ADC scaling only; do not apply more than VDD + 0.3 V.
- Differential input range is +/-FSR; single-ended uses only half of the range (p29).
- PGA gain network values, PGA bandwidth, PGA input-referred noise separate from the noise table: not in the datasheet.
- Voltage reference is internal, cannot be external; no specified reference value; use the FSR values directly (p15, Sec 7.3.4).

## 7. DC accuracy (Sec 5.5, p5; DR = 8 SPS, FSR = +/-2.048 V unless noted)

| quantity | symbol | min | typ | max | unit | conditions | page | table/figure |
|---|---|---|---|---|---|---|---|---|
| Integral nonlinearity | INL | - | - | 1 | LSB | DR = 8 SPS, FSR = +/-2.048 V, best-fit, covers 99% of full scale | 5, 6 | Sec 5.5, footnote 2 |
| Offset error, differential inputs | - | -3 | +/-1 | 3 | LSB | FSR = +/-2.048 V | 5 | Sec 5.5 |
| Offset error, single-ended inputs | - | - | +/-3 | - | LSB | FSR = +/-2.048 V | 5 | Sec 5.5 |
| Offset drift over temperature | - | - | 0.005 | - | LSB/C | FSR = +/-2.048 V | 5 | Sec 5.5 |
| Long-term offset drift | - | - | +/-1 | - | LSB | FSR = +/-2.048 V, TA = 125 C, 1000 hours | 5 | Sec 5.5 |
| Offset power-supply rejection | - | - | 1 | - | LSB/V | FSR = +/-2.048 V, DC supply variation | 5 | Sec 5.5 |
| Offset channel match | - | - | 3 | - | LSB | match between any two inputs | 5 | Sec 5.5 |
| Gain error | - | - | 0.01% | 0.15% | - | FSR = +/-2.048 V, TA = 25 C; includes all errors from onboard PGA and voltage reference | 5 | Sec 5.5 |
| Gain drift over temperature | - | - | 7 | - | ppm/C | FSR = +/-0.256 V | 5 | Sec 5.5 |
| Gain drift over temperature | - | - | 5 | 40 | ppm/C | FSR = +/-2.048 V | 5 | Sec 5.5 |
| Gain drift over temperature | - | - | 5 | - | ppm/C | FSR = +/-6.144 V | 5 | Sec 5.5 |
| Long-term gain drift | - | - | +/-0.05% | - | - | FSR = +/-2.048 V, TA = 125 C, 1000 hours | 5 | Sec 5.5 |
| Gain power-supply rejection | - | - | 80 | - | ppm/V | | 5 | Sec 5.5 |
| Gain match | - | - | 0.02% | 0.1% | - | match between any two gains | 5 | Sec 5.5 |
| Gain channel match | - | - | 0.05% | 0.1% | - | match between any two inputs | 5 | Sec 5.5 |
| CMRR | CMRR | - | 105 | - | dB | at DC, FSR = +/-0.256 V | 5 | Sec 5.5 |
| CMRR | CMRR | - | 100 | - | dB | at DC, FSR = +/-2.048 V | 5 | Sec 5.5 |
| CMRR | CMRR | - | 90 | - | dB | at DC, FSR = +/-6.144 V | 5 | Sec 5.5 |
| CMRR | CMRR | - | 105 | - | dB | fCM = 60 Hz, DR = 8 SPS | 5 | Sec 5.5 |
| CMRR | CMRR | - | 105 | - | dB | fCM = 50 Hz, DR = 8 SPS | 5 | Sec 5.5 |
| Data-rate variation | - | -10% | - | +10% | - | all data rates | 5 | Sec 5.5 |

Typical-characteristic curves exist (readable as figures only, no tabulated numbers; not transcribed): operating current vs temperature (Fig 5-2), power-down current (5-3), single-ended offset error vs temperature (5-4: roughly 0 to -250 uV region), differential offset vs temperature (5-5), gain error vs temperature (5-6) and vs supply (5-7), INL vs supply, input, temperature (5-8 to 5-13). Page 7-8.
Pages 9-10 (figures only, qualitative; not tabulated): Fig 5-14 RMS noise vs input signal (FSR +/-0.512 V; DR 8/128/860 SPS curves roughly flat across -0.5..0.5 V); Fig 5-15 noise vs supply (FSR +/-2.048 V, 2.0-5.5 V, nearly flat); Fig 5-16 noise vs temperature (DR 8 SPS); Fig 5-17/5-18 gain-error and offset histograms (185 units); Fig 5-19 total error vs input (differential, +/-2.048 V; envelope widens toward the ends of range); Fig 5-20 data-rate error vs temperature (about -3 to +3 %, VDD-dependent); Fig 5-21 digital filter frequency response at DR = 8 SPS, 1 Hz to 10 kHz, 0 to -80 dB, with notches and repeating lobes (sinc-like shape visible; no formula given).

## 8. Data rates, oscillator, conversion timing

| quantity | symbol | min | typ | max | unit | conditions | page | table/figure |
|---|---|---|---|---|---|---|---|---|
| Data rates | DR | - | 8, 16, 32, 64, 128 (default), 250, 475, 860 | - | SPS | DR[2:0] = 000..111 | 5, 26 | Sec 5.5, Table 8-3 |
| Data-rate variation | - | -10% | - | +10% | - | all data rates | 5 | Sec 5.5 |
| Internal oscillator | - | - | 1 | - | MHz | no external clock possible; drifts with temperature and time; output data rate scales proportionally with oscillator frequency | 15 | Sec 7.3.5 |
| Modulator frequency | fMOD | - | 250 | - | kHz | oscillator / 4 | 14 | Sec 7.3.2 |
| Conversion time | - | - | 1 / DR | - | s | conversions settle within a single cycle | 15 | Sec 7.3.6 |
| Settling | - | - | single-cycle | - | - | "settle within a single cycle" | 1, 15 | Sec 1, 7.3.6 |
| Single-shot power-up time | - | - | approx. 25 | - | us | OS written 1; device powers up, converts, powers down again | 18 | Sec 7.4.2.1 |
| Conversion at 860 SPS (single-shot) | - | - | approx. 1.2 | - | ms | stated in the duty-cycling example (p18); 8 SPS example: 125 ms period | 18 | Sec 7.4.3 |
| Conversion-ready pulse | - | - | approx. 8 | - | us | continuous mode, ALERT/RDY | 17 | Sec 7.3.8, Fig 7-8 |
| Power-up wait before communication | - | - | approx. 50 | - | us | after VDD stable | 37 | Sec 10.1 |
| Digital filter | - | - | not in the datasheet (type, order, frequency response, notch positions) | - | - | text says filter response repeats at multiples of fMOD (Fig 9-3 sketch only) | 30 | Sec 9.1.5 |
| Oversampling ratio per data rate | OSR | not in the datasheet | | | | text defines OSR = fMOD / DR conceptually only | 11 | Sec 6.1 |

Conversion modes (p12, p18): single-shot (converts on request, then powers down) and continuous (next conversion starts as soon as previous completes; rate equals programmed data rate). When config changes in continuous mode, the ongoing conversion completes with old settings, then new settings start (p18).

## 9. Noise (Sec 6.1, p11; VDD = 3.3 V, inputs shorted externally, TA = 25 C)

Table 6-1. Noise in uVRMS (uVPP) at VDD = 3.3 V. Columns are FSR.

| DR (SPS) | +/-6.144 V | +/-4.096 V | +/-2.048 V | +/-1.024 V | +/-0.512 V | +/-0.256 V |
|---|---|---|---|---|---|---|
| 8 | 187.5 (187.5) | 125 (125) | 62.5 (62.5) | 31.25 (31.25) | 15.62 (15.62) | 7.81 (7.81) |
| 16 | 187.5 (187.5) | 125 (125) | 62.5 (62.5) | 31.25 (31.25) | 15.62 (15.62) | 7.81 (7.81) |
| 32 | 187.5 (187.5) | 125 (125) | 62.5 (62.5) | 31.25 (31.25) | 15.62 (15.62) | 7.81 (7.81) |
| 64 | 187.5 (187.5) | 125 (125) | 62.5 (62.5) | 31.25 (31.25) | 15.62 (15.62) | 7.81 (7.81) |
| 128 | 187.5 (187.5) | 125 (125) | 62.5 (62.5) | 31.25 (31.25) | 15.62 (15.62) | 7.81 (12.35) |
| 250 | 187.5 (252.09) | 125 (148.28) | 62.5 (84.03) | 31.25 (39.54) | 15.62 (16.06) | 7.81 (18.53) |
| 475 | 187.5 (266.92) | 125 (227.38) | 62.5 (79.08) | 31.25 (56.84) | 15.62 (32.13) | 7.81 (25.95) |
| 860 | 187.5 (430.06) | 125 (266.93) | 62.5 (118.63) | 31.25 (64.26) | 15.62 (40.78) | 7.81 (35.83) |

(The datasheet's RMS values at low data rates equal 1 LSB of the range, i.e. 187.5 / 125 / 62.5 / 31.25 / 15.625 / 7.8125 uV; this is an observation of the table, not an added fact.)

Table 6-2. Effective resolution from RMS noise (noise-free resolution from peak-to-peak noise), bits, VDD = 3.3 V.

| DR (SPS) | +/-6.144 V | +/-4.096 V | +/-2.048 V | +/-1.024 V | +/-0.512 V | +/-0.256 V |
|---|---|---|---|---|---|---|
| 8 | 16 (16) | 16 (16) | 16 (16) | 16 (16) | 16 (16) | 16 (16) |
| 16 | 16 (16) | 16 (16) | 16 (16) | 16 (16) | 16 (16) | 16 (16) |
| 32 | 16 (16) | 16 (16) | 16 (16) | 16 (16) | 16 (16) | 16 (16) |
| 64 | 16 (16) | 16 (16) | 16 (16) | 16 (16) | 16 (16) | 16 (16) |
| 128 | 16 (16) | 16 (16) | 16 (16) | 16 (16) | 16 (16) | 16 (15.33) |
| 250 | 16 (15.57) | 16 (15.75) | 16 (15.57) | 16 (15.66) | 16 (15.96) | 16 (14.75) |
| 475 | 16 (15.49) | 16 (15.13) | 16 (15.66) | 16 (15.13) | 16 (14.95) | 16 (14.26) |
| 860 | 16 (14.8) | 16 (14.9) | 16 (15.07) | 16 (14.95) | 16 (14.61) | 16 (13.8) |

Definitions (p11): Effective Resolution = ln(FSR / VRMS-noise) / ln(2) (Eq. 1); Noise-Free Resolution = ln(FSR / VPP-noise) / ln(2) (Eq. 2). Output noise in Sec 5.5 refers to this table. Noise at VDD other than 3.3 V, noise density, 1/f corner, input-referred noise of the analog input alone: not in the datasheet.

## 10. Input filtering and anti-alias recommendations (Sec 9.1.5 p30; Sec 9.2.2.6 p35-36)

Note on p28: application sections are not part of the TI component specification.

| item | statement | page |
|---|---|---|
| Purpose | limit aliasing; reduce external noise | 30 |
| Aliasing | components near fMOD or multiples are not attenuated by the digital filter and alias into band; digital filter response repeats at multiples of fMOD | 30 |
| Goal | ideally any signal beyond fMOD / 2 is attenuated below the ADC noise floor | 30 |
| Starting point | first-order RC low-pass with cutoff set at the output data rate or 10x higher | 30 |
| Example differential filter | R5 = R6 = 100 ohm, CDIFF = 0.22 uF, fC = 1 / [2 pi (R5 + R6) CDIFF] (Eq. 16); stated -3 dB 3.6 kHz | 35, 36 |
| Example common-mode filter | CCM1 = CCM2 = 0.022 uF, stated -3 dB 0.36 kHz | 35, 36 |
| Rule | CDIFF at least 10x the common-mode capacitors (mismatch converts CM noise to differential) | 35 |
| Series resistor limit | keep filter resistors below 1 kohm; they cause gain error through input current | 35 |
| Source impedance | use low-impedance source or buffer; input impedance values in Sec 3 | 14 |

## 11. Other input-related text facts

- Single-ended and differential: the ADC core measures V(AINP) - V(AINN) with a differential switched-capacitor delta-sigma modulator and digital filter; input compared to internal reference; strong attenuation of common-mode signals (p12).
- Config reset value 8583h: MUX = 000, PGA = 010, MODE = 1, DR = 100 (128 SPS) (p24-26).
- Decoupling: VDD with at least 0.1 uF close to the supply pin (p37).

## Gaps

Not in the datasheet (or not stated numerically in any page read):
- Sampling capacitor values CA1, CA2, CB; switch on-resistances; tSAMPLE duration; mux/ESD diode capacitance and leakage.
- Analog input leakage / bias current (only digital input leakage is specified).
- Exact impedance-versus-FSR scaling law (only the five tabulated FSR points; no equation).
- PGA internal gain, bandwidth, and any input-referred noise separate from the Table 6-1 values.
- Digital filter type, order, notch frequencies, passband droop, OSR per data rate, step response.
- Settling beyond "single cycle"; MUX channel-change settling/dead time; first-conversion behaviour after MUX change.
- Input capacitance seen at pins; ESD diode forward characteristics or clamp-current model.
- Noise at supply voltages other than 3.3 V; noise density; 1/f.
- Input-voltage dependence of the impedance, and temperature dependence of impedance (stated only as slight, due to oscillator drift).
- Figure-only data (typical-characteristic plots on pages 7-10) not transcribed as numbers, including the Fig 5-21 filter response.
- Pages not read: 20-24 (I2C protocol and register map start), 38-57 (layout, support, packaging); skipped as out of scope.
