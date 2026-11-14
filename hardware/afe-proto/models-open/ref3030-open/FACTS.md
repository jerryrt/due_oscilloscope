# REF3030E facts (clean room: datasheet only)

Written from the TI REF30E/REF30 datasheet Rev. K only; no vendor SPICE model was opened.

Source: SBVS032K, March 2002, revised December 2025, 37 pages. Pages 1-15 and 19-26 were read; pages 16-18 (REF30 non-E curves) and 27-37 (revision history, packaging) were not read. Page numbers below are the printed page numbers, which equal PDF page numbers.

Applicability: the REF3030E is the 3.0 V, SOT-23-3 member of the **REF30E** (enhanced) family. Use the REF30E columns. REF30 (non-E) figures are listed separately and do NOT apply to the REF3030E. The ordering table (p.2) lists REF3030EAIDBZR as 3 V.

Curve accuracy note: all curves are read by eye from rendered page images. Unless stated otherwise, reading accuracy is about +/-3% of full-scale on y and +/-0.1 decade (log axes) or +/-5 degC (linear axes) on x. All REF30E typical-characteristic curves (Figs 6-1 to 6-29) were taken at TA = 25 degC, VIN = 5 V with a **REF3050E** (5 V part) and, where two curves are shown, a 1.25 V part; the REF3030E itself is not plotted.

## 1. Pinout (p.3, Fig 5-1, Table 5-1; DBZ SOT-23-3 top view)

| pin | name | I/O | description | page | ref |
|---|---|---|---|---|---|
| 1 | IN | input | Input supply voltage | 3 | Table 5-1 |
| 2 | OUT | output | Reference output voltage | 3 | Table 5-1 |
| 3 | GND | - | Ground | 3 | Table 5-1 |

Fig 5-1: pin 1 (IN) and pin 2 (OUT) on the left side, pin 3 (GND) on the right side.

## 2. REF3030E electrical characteristics (Section 6.5, p.6-7)

Conditions: TA = 25 degC, VIN = VOUT + 300 mV, CIN = 0.1 uF, COUT = 1 uF, ILOAD = 0 mA, unless noted.

| quantity | symbol | min | typ | max | unit | conditions | page | table |
|---|---|---|---|---|---|---|---|---|
| Output voltage | VOUT | 2.997 | 3 | 3.003 | V | | 6 | 6.5 REF3030E |
| Initial accuracy | | -0.1 | | 0.1 | % | | 6 | 6.5 |
| Output voltage noise, 0.1 Hz to 10 Hz | | | 24 | | uVpp | f = 0.1 Hz to 10 Hz | 6 | 6.5 |
| Output voltage noise, 10 Hz to 10 kHz | | | 51 | | uVrms | f = 10 Hz to 10 kHz | 6 | 6.5 |
| Line regulation | | | 16 | 240 | uV/V | VOUT + 300 mV <= VIN <= 5.75 V | 6 | 6.5 |

## 3. REF30xxE common parameters (apply to REF3030E; p.7, Section 6.5 continued)

Same conditions as section 2.

| quantity | symbol | min | typ | max | unit | conditions | page | table |
|---|---|---|---|---|---|---|---|---|
| Temperature drift (box method) | dVOUT/dT | | 5 | 15 | ppm/degC | 0 degC <= TA <= 70 degC | 7 | 6.5 REF30xxE, note (2) box method |
| Temperature drift (box method) | dVOUT/dT | | 6 | 20 | ppm/degC | -40 degC <= TA <= 85 degC | 7 | 6.5 |
| Temperature drift (box method) | dVOUT/dT | | 5 | 15 | ppm/degC | -40 degC <= TA <= 125 degC | 7 | 6.5 |
| Long-term stability | | | 40 | | ppm | 0 h to 1000 h | 7 | 6.5 |
| Long-term stability | | | 15 | | ppm | 1000 h to 2000 h | 7 | 6.5 |
| Load regulation, source | dVOUT/dILOAD | | 3 | 15 | ppm/mA | 0 mA < ILOAD < 10 mA, VIN = VOUT + 500 mV | 7 | 6.5 |
| Load regulation, sink | dVOUT/dILOAD | | 3 | 150 | ppm/mA | 0 mA > ILOAD > -10 mA, VIN = VOUTF + 500 mV (as printed; "VOUTF" is the datasheet's own symbol, not defined there) | 7 | 6.5 |
| Dropout voltage | VDO | | 20 | 200 | mV | no load current stated in the row; footnote (1) says minimum supply for REF3012E and REF3016E is 1.8 V | 7 | 6.5 |
| Short-circuit current | ISC | | 35 | | mA | no further condition stated | 7 | 6.5 |
| Turn-on settling time | | | 2 | | ms | to 0.1% with CL = 1 uF | 7 | 6.5 |
| Quiescent current | IQ | | 27 | | uA | TA = 25 degC | 7 | 6.5 |
| Quiescent current | IQ | | | 37 | uA | -40 degC <= TA <= 125 degC | 7 | 6.5 |
| Stable input capacitor range | CIN | 0.1 | | | uF | -40 to 125 degC; no maximum stated | 7 | 6.5 |
| Stable output capacitor range | CL | 0.1 | | 22 | uF | -40 to 125 degC; footnote (3): ESR can range from 10 mOhm to 500 mOhm | 7 | 6.5 |

Other specification-comparison figures (p.2, REF30E): max temperature drift 15 ppm/degC (-40 to +125 degC), 20 ppm/degC (-40 to +85 degC), 15 ppm/degC (0 to 70 degC); IQ 27 uA (typ); initial accuracy +/-0.1%.

## 4. Absolute maximum ratings and operating conditions

| quantity | min | max | unit | conditions | page | table |
|---|---|---|---|---|---|---|
| Supply voltage IN to GND, REF30xxE | | 6 | V | over operating free-air range | 4 | 6.1 |
| Supply voltage IN to GND, REF30xx (non-E) | | 7 | V | not REF3030E | 4 | 6.1 |
| Output short-circuit current (short to ground) | | 70 | mA | | 4 | 6.1 |
| Operating temperature | -40 | 125 | degC | | 4 | 6.1 |
| Junction temperature (TJ max) | | 150 | degC | | 4 | 6.1 |
| Storage temperature | -65 | 150 | degC | | 4 | 6.1 |
| Recommended VIN, REF30xxE | VOUT + 0.2 | 5.75 | V | footnote: for IL > 0 mA; the REF30xx (non-E) is VOUT + 0.05 to 5.5 V | 4 | 6.3 |
| Recommended load current, REF30xxE | -10 | 10 | mA | non-E is 25 mA max | 4 | 6.3 |
| Operating temperature (recommended) | -40 | 125 | degC | | 4 | 6.3 |
| ESD HBM, REF30E | | +/-2000 | V | all pins | 4 | 6.2 |
| ESD CDM, REF30E | | +/-500 | V | all pins | 4 | 6.2 |

Note on the p.4 table: its row header reads "Input voltage(3)" for the 5.75 V / 10 mA rows, and footnote (3) is "Specification for REF30xxE". Absolute max for REF30xxE is read from the "REF30xxE" row of Table 6.1.

Thermal (p.5, Table 6.4, REF30xxE DBZ SOT-23, 3 pins): RthetaJA 218.5, RthetaJC(top) 120.6, RthetaJB 48.7 degC/W; PsiJT 14.5, PsiJB 48.2 degC/W.

## 5. Quantities with no REF30E figure in the datasheet

| quantity | status |
|---|---|
| Thermal hysteresis, numeric spec | not in the datasheet for REF30E (Section 7.3.2 p.20 gives the definition, VHYST = abs(VPRE - VPOST)/VNOM x 10^6 ppm; the numeric spec row 25 ppm typ / 100 ppm max exists only in the REF30 table, p.9, which does NOT apply to the REF3030E). Typical REF30E histograms exist: see Section 7 below, Figs 6-24 to 6-29. |
| Dropout voltage vs load, REF3030E specifically | not in the datasheet; only Fig 6-11 for a REF3050E |
| Output impedance numeric spec | not in the datasheet (curve only, Fig 6-14) |
| PSRR numeric spec | not in the datasheet (curve only, Fig 6-16) |
| Supply current vs supply voltage, REF30E | not in the datasheet (Fig 7-1 on p.19 is the REF30, 42 uA part; REF30E has Figs 6-8 and 6-9 vs temperature only) |
| Maximum capacitive load, CL | 22 uF max stated (p.7); behaviour at larger CL not stated |
| Internal structure | Section 7.1/7.2 p.19: bandgap; Q1 and Q2 with Q1 at higher current density; (Vbe1 - Vbe2) is across R1, gained up and added to Vbe2 of Q2; an amplifier closes the loop; the output is a single amplifier-driven node. No component values stated. Text is for REF30 but a block diagram is printed once for the family. |

## 6. Capacitive load, stability, input capacitor (text)

- REF30E table (p.7): stable CIN range 0.1 uF minimum (no maximum stated); stable CL range 0.1 uF to 22 uF; ESR 10 mOhm to 500 mOhm (footnote 3).
- Section 8.1 (p.23): "For normal operation, the REF30 does not require a capacitor on the output. If a capacitive load is connected, take special care when using low equivalent series resistance (ESR) capacitors and high capacitance. This precaution is especially true for low-output voltage devices; therefore, for the REF3012 use a low-ESR capacitance of 10 uF or less." "A supply bypass capacitor of 0.1 uF is always recommended." (Fig 8-1: 0.1 uF from IN to GND, nothing on OUT.)
- Section 8.3 (p.25): "Use a supply bypass capacitor greater than 0.47 uF." This conflicts with the 0.1 uF statement in 8.1 and the 0.1 uF minimum on p.7; the datasheet does not reconcile them.
- Section 8.4.1 layout (p.25): low-ESR 0.1 uF ceramic bypass at VIN.
- Introduction (p.1): "the REF30 does not require a load capacitor to be stable" (REF30 text).
- Stated effect of COUT on transients: Fig 6-17 shows startup with COUT = 1 uF and 10 uF (larger COUT gives a slower ramp, see Fig 6-17 reading below). Fig 6-12 and Fig 6-16 conditions give CIN = 1 uF, COUT = 10 uF for the PSRR curve.
- Figs 6-14 impedance curves show a resonant peak that moves in frequency and size with load (see Section 7). The datasheet states no explanation or COUT dependency for that peak; the conditions of Fig 6-14 do not state CIN/COUT.

## 7. Curves (digitised; REF30E, REF3050E device unless noted; (x, y))

### Fig 6-14 Output Impedance vs Frequency (p.12)
x: 1 Hz to 1 MHz log; y: 0 to 200 Ohm linear. Six curves: VOUT = 1.25 V and 5 V, each with 100 kOhm RL, 1 kOhm RL, and open. Conditions of CIN/COUT not stated. Reading accuracy: +/-5 Ohm on y, +/-0.1 decade on x; the low-frequency region (< 10 Hz) is too small to read better than +/-3 Ohm.

All curves: near 0 to 3 Ohm below about 10 Hz, with a small narrow spike on the open/100 k curves of about 15-20 Ohm at about 2 Hz and a smaller one near 1 Hz (artefacts visible in the plot).

| curve | points (Hz, Ohm) |
|---|---|
| 5 V, open (and 5 V, 100 kOhm RL, essentially coincident) | (10, 3), (30, 8), (100, 18), (300, 35), (600, 65), (1000, 115 peak), (1500, 70), (2000, 35), (3000, 12), (10000, 4), (100000, 2), (1000000, 1) |
| 1.25 V, open (and 1.25 V, 100 kOhm RL, essentially coincident) | (10, 2), (100, 12), (300, 25), (600, 50), (1000, 88 peak), (1500, 60), (2000, 28), (3000, 10), (10000, 3), (100000, 1.5) |
| 5 V, 1 kOhm RL | (100, 4), (300, 8), (1000, 18), (2000, 28 peak), (3000, 20), (5000, 8), (10000, 3), (100000, 1.5) |
| 1.25 V, 1 kOhm RL | (100, 3), (300, 7), (1000, 15), (2500, 24), (4000, 26 peak), (6000, 15), (10000, 6), (100000, 2) |

Peak centre frequencies about 1 kHz (open, 100 kOhm), about 2 kHz (5 V, 1 kOhm) and about 4 kHz (1.25 V, 1 kOhm). Printed figure number is 6-14 (matches the earlier project notes).

### Fig 6-16 Power-Supply Rejection Ratio vs Frequency (p.12)
Single curve, CIN = 1 uF, COUT = 10 uF. x 1 Hz to 1 MHz log; y 0 to 80 dB. Accuracy +/-3 dB; above 20 kHz the trace is noisy with +/-8 dB spread, the values below are mid-trace.

(Hz, dB): (1, 77), (3, 72), (10, 66), (30, 57), (100, 48), (300, 33), (600, 21), (800, 16 min), (1000, 17), (2000, 27), (5000, 34), (10000, 38), (30000, 43), (100000, 44 with 38-52 scatter), (300000, 42), (500000, 38), (700000, 30), (1000000, 22).

### Fig 6-13 Noise Spectral Density vs Frequency (p.12)
x 10 Hz to 100 kHz log; y 0 to 2000 nV/rtHz linear. Single curve (device at TA = 25 degC, REF3050E as stated in the section header). Accuracy +/-40 nV/rtHz.

(Hz, nV/rtHz): (10, 1400), (20, 1250), (40, 1070), (60, 1050), (100, 900), (200, 800), (400, 760), (700, 790), (1000, 900), (1500, 1070 peak ~1080), (2000, 950), (3000, 600), (5000, 250), (10000, 90), (30000, 20), (100000, 3).

### Fig 6-11 Dropout Voltage vs Temperature (p.11)
x -40 to 125 degC; y 0 to 500 mV; four curves IOUT = 0, 1, 5, 10 mA. Device REF3050E (5 V). Accuracy +/-10 mV.

| IOUT | points (degC, mV) |
|---|---|
| 0 mA | (-40, 0), (26, 1), (125, 4) |
| 1 mA | (-40, 8), (-7, 0), (26, 15), (59, 60), (92, 115), (125, 175) |
| 5 mA | (-40, 40), (-7, 35), (26, 55), (59, 130), (92, 210), (125, 295) |
| 10 mA | (-40, 85), (-7, 80), (26, 110), (59, 190), (92, 275), (125, 370) |

Note: these are 5 V-part values; they do not match the 20 mV typ / 200 mV max Dropout row at the REF3030E.

### Fig 6-9 Quiescent Current vs Temperature, VOUT = 5 V (p.11)
VDD 5.2 V and 5.5 V curves coincide. (degC, uA): (-40, 26), (-7, 26.8), (26, 27.6), (59, 28.7), (92, 30), (125, 31.3).

### Fig 6-8 Quiescent Current vs Temperature, VOUT = 1.25 V (p.11)
VDD = 1.8 V: (-40, 24.5), (-7, 25.2), (26, 26.2), (59, 27.4), (92, 28.7), (125, 30).
VDD = 5.5 V: (-40, 25.4), (-7, 26.1), (26, 26.9), (59, 28.2), (92, 29.5), (125, 30.8).

### Fig 6-10 Line Regulation vs Temperature, VOUT = 2.5 V (p.11)
(degC, uV/V): (-40, 8.5), (-7, 12.5), (0, 13), (26, 12.5), (59, 12.5), (92, 15.5), (125, 19.3).

### Fig 6-6 Load Regulation Sourcing vs Temperature (p.10)
VOUT = 5 V: (-40, 1), (-7, 1.6), (26, 2.2), (59, 2.6), (92, 3.0), (125, 3.3) ppm/mA.
VOUT = 1.25 V: (-40, 1), (-7, 2.7), (26, 3.8), (59, 4.7), (75, 4.8 peak), (92, 4.7), (125, 4.3) ppm/mA.

### Fig 6-7 Load Regulation Sinking vs Temperature (p.11)
VOUT = 5 V: (-40, 18), (-7, 8), (26, 2), (59, 1), (80, 5), (92, 15), (125, 44) ppm/mA.
VOUT = 1.25 V: (-40, 4), (-7, 2), (26, 1.5), (59, 2), (92, 9), (125, 20) ppm/mA.

### Fig 6-4 Output Voltage vs Temperature, VOUT = 2.5 V (p.10) and Fig on p.1 (REF3025E)
y axis 2.475 to 2.525 V (+/-1 mV reading accuracy, so only the shape is meaningful). (degC, V): (-40, 2.4965), (-7, 2.4995), (26, 2.5002), (59, 2.5001), (92, 2.4999), (125, 2.4996). Total span about 3.7 mV, about 1.5 mV peak-to-peak after the first 30 degC.

### Fig 6-12 VOUT vs VIN across temperature (p.11)
Device 5 V part. VIN 4.95 V to 5.7 V, VOUT 4.95 V to 5.075 V. All three temperatures (-40, 25, 125 degC) rise from (4.95, 4.95) to a peak near VIN = 5.0 V (overshoot values read: -40 degC about 5.017 V, 25 degC about 5.03 V, 125 degC about 5.018 V at VIN about 5.03 V), then settle at about 4.995 V (-40 degC) / 4.998 V (25 degC) / 5.002 V (125 degC) by VIN = 5.2 V. Accuracy +/-3 mV.

### Fig 6-1/6-2/6-3 Temperature-drift histograms (p.10, population %, 1.5 ppm/degC bins)
Fig 6-1 (-40 to +125 degC): bins centred at 3: 6.5, 4.5: 30, 6: 29.5, 7.5: 26, 9: 5.5, 10.5: 1, 12: 1.5. Total range shown about 3 to 12 ppm/degC.
Fig 6-2 (-40 to +85 degC): 3: 2.5, 4.5: 15.8, 6: 21, 7.5: 21, 9: 18.5, 10.5: 15.8, 12: 5.3.
Fig 6-3 (0 to +70 degC): 3: 5.7, 4.5: 35, 6: 38.5, 7.5: 11.5, 9: 8, 10.5: 1.5.
Fig 6-5 Initial accuracy histogram (%): -0.02 bin about 8, 0 bin 33, 0.02 bin 37, 0.04 bin 21; all within about -0.02 to +0.05 %.

### Thermal hysteresis histograms (population %, ppm)
Fig 6-24 (-40 to 125 degC, cycle 1, p.13): spread to 500 ppm; the 5 V device peaks at 47 % in the 50 ppm bin; the 1.25 V device peaks about 20 % at 100-150 ppm.
Fig 6-25 (-40 to 125 degC cycle 2, p.14): about 100 % (1.25 V) and 94 % (5 V) in the 50 ppm bin, 6 % at 200 ppm for 5 V.
Figs 6-26 to 6-29 (-40 to 85 degC, and 0 to 70 degC, cycles 1 and 2, p.14): distributions 20-140 ppm in cycle 1 (peaks about 35 % at 80 ppm); cycle 2 mostly in the 20 ppm bin (about 55-60 %) with a tail to 160 ppm; 0-70 degC cycle 2 about 88 % in the 20 ppm bin.

### Long-term stability curves (p.13)
Fig 6-22 (0 to 250 h): average runs from about -3 ppm at 0 h to about +10 ppm at 250 h, sigma band roughly +/-20 ppm at 250 h. Fig 6-23 (0 to 2000 h): average rises to about 50 ppm by about 1200 h and stays at 48-50 ppm to 2000 h; average + sigma about 97 ppm at 2000 h; average - sigma about 0 ppm at 2000 h. The table (Section 3) gives 40 ppm (0-1000 h) and 15 ppm (1000-2000 h) typical.

### Flicker noise
Fig 6-21 (p.13): 0.1 to 10 Hz noise histogram (1/f noise, ppm p-p) peaks at the 9 ppm bin (39 %), range 6-13.5 ppm. This is a ppm quoting for a REF3050E; the table gives 24 uVpp for the REF3030E (that is 8 ppm of 3.0 V).

### Transients and startup (qualitative; scope plots, p.12-13)
- Fig 6-17 Step response startup (p.12): VIN steps to 5.2 V (VIN 5.2 V/div; VOUT 5 V/div, time 500 us/div). With COUT = 1 uF VOUT reaches the final value in about 2-3 divisions (about 1 to 1.5 ms); with COUT = 10 uF it takes about 4-5 divisions (about 2 to 2.5 ms). The REF30E table gives 2 ms typ to 0.1 % with CL = 1 uF.
- Fig 6-18 Load transient, sourcing (p.12): load 10 mA to 0 mA and back, VOUT 200 mV/div, time 2 ms/div. Shows a positive spike of about 0.2 div on the release and a negative spike of about 1.5 div (about 300 mV) on the 0 to 10 mA step; no settling time or exact amplitude is stated. COUT used is not stated.
- Fig 6-19 Load transient, sinking (p.13): load 0 to -10 mA and back; a positive spike of about 2 div (about 400 mV) on the sink step and a smaller negative response later; no numeric values stated.
- Fig 6-20 Line transient (p.13): VIN 5.2 V to 5.75 V step, VOUT 50 mV/div; VOUT disturbance of about +/-1 div (about 50 mV) damped oscillation at each edge; settling in about 0.5 ms.
- Fig 6-15 Solder shift histogram (p.12): shift range about -0.04 to +0.08 %.

### REF30 (non-E) specs, NOT applicable to REF3030E (for the record)
REF3030 (3.0 V) output 2.994-3.06 V (as printed), noise 33 uVpp 10 Hz-1 kHz and 94 uVrms 10 Hz-10 kHz, line regulation 120 typ / 375 max uV/V; drift 20/28/30/35 ppm/degC typ; thermal hysteresis 25 typ / 100 max ppm; long-term stability 24 ppm (0-1000 h), 15 ppm (1000-2000 h); dropout 1 typ / 50 max mV; ISC 45 mA; turn-on 120 us; IQ 42 typ / 50 max uA at 25 degC, 59 max over temperature. Section 7.3.4 text: REF30 noise less than 50 uVpp from 0.1 to 10 Hz. Section 7.3.3 text: REF30 drift typ 20 ppm from 0-70 degC and 50 ppm from -40 to +125 degC. Fig 7-1 (REF30 supply current vs supply): VIN 1.8 V 40.3 uA, 2.5 V 40.4, 3 V 40.6, 4 V 41.2, 5 V 42, 5.5 V 42.4 uA.

## Gaps

Not in the datasheet (or not readable) for the REF3030E:
- Thermal hysteresis numeric spec for REF30E (histograms only, for 1.25 V and 5 V parts).
- Dropout voltage vs load for the 3.0 V part; dropout test conditions (load current, VIN) for the 20/200 mV row.
- Short-circuit current conditions and its dependence on VIN or temperature; the ISC curve.
- Any I-V curve of the output (source or sink limit) beyond 10 mA, and any behaviour of the output when VIN is below VOUT (reverse current) or on supply removal.
- Output impedance numeric value at DC, and the CIN/COUT conditions of Fig 6-14.
- PSRR conditions other than CIN = 1 uF, COUT = 10 uF; it is a 5 V-part curve.
- Supply current vs supply voltage for REF30E (only the REF30 Fig 7-1 is plotted).
- Noise density for a 3.0 V part; the density curve is for a 5 V part. The 0.1-10 Hz noise 24 uVpp and 10 Hz-10 kHz 51 uVrms are the only REF3030E noise numbers.
- Output voltage vs temperature for the 3.0 V part (the 2.5 V curve only).
- The noise-density rms integral relation (not stated).
- Pages 16-18 (REF30 non-E curves) and 27-37 (revision history, packaging, tape and reel) were not read.
- The 0.1 uF vs 0.47 uF input bypass statement conflict is unreconciled (Section 6).
- All transient plots (Figs 6-17 to 6-20) have no stated numeric amplitudes or COUT/CIN; the values above are eyeballed from scope divisions.
