# TPH2502 facts (clean room: datasheet only)

Written from the 3PEAK TPH2501/2/3/4 datasheet Rev. A only; no vendor SPICE model was opened.

General notes on this document:
- The datasheet covers TPH2501 (single), TPH2502 (dual, 8-pin SOP / MSOP), TPH2503 (single with shutdown) and TPH2504 (quad). Electrical tables are shared; only the crosstalk and shutdown rows name a specific part. Rows are therefore "family" values unless noted. Quiescent current is explicitly "per amplifier".
- Electrical Characteristics header (p3, p4): "TA = +25 C, RF = 0 ohm, RL = 1 kohm, and connected to VS/2, unless otherwise noted." The table does NOT state a supply voltage (VS) for most rows. Page 1 says the family is "fully specified at supplies of 2.7 V and 5.0 V". Typical-performance-curve header (p5-p7): "VS = 5 V, G = +1, RF = 0, RL = 1 kohm, connected to VS/2, unless otherwise specified."
- "Page" is the printed page number (1-18). All curve readings are visual readings of the rendered page image, not digital data.
- Several datasheet values contradict one another (listed under "## Internal inconsistencies"). They are reported as printed.

## 1. Supply and absolute maximum ratings

| quantity | symbol | min | typ | max | unit | conditions | page | table/figure |
|---|---|---|---|---|---|---|---|---|
| Supply voltage, specified operating | VDD (VS) | 2.5 | not in the datasheet | 5.5 | V | no other conditions given | 4 | Electrical Characteristics |
| Supply range, text | VS | 2.5 | | 5.5 | V | "+/-1.25 V to +/-2.75 V" split supplies; V+ to V- must be 2.5 to 5.5 V | 8 | Pin Functions, Operation |
| Fully specified supply points | VS | 2.7 | | 5.0 | V | "fully specified at supplies of 2.7 V and 5.0 V" | 1 | Description |
| Supply voltage V+ - V-, absolute max | | | | 7.0 | V | Note 2: supplies must be established simultaneously, with, or before any input signal | 2 | Absolute Maximum Ratings |
| Supply voltage, text | | | | 7.5 | V | "Supply voltages higher than 7.5 V (absolute maximum) can permanently damage" (conflicts with 7.0 V above) | 8 | Operation |
| Input voltage | VIN | V- - 0.3 | | V+ + 0.3 | V | | 2 | Abs Max |
| Input current, +IN / -IN | | -20 | | +20 | mA | Note 3: ESD diodes to each supply; if input extends >500 mV beyond supply, limit current to <10 mA (Abs Max note) | 2 | Abs Max |
| Input overload current with series resistor | | | | 20 | mA | "Current-limiting resistor required if input voltage exceeds supply rails by >0.5 V"; example 5 kohm series, +/-2.5 V supplies | 11 | Figure 4 |
| Output current, OUT | | -160 | | +160 | mA | | 2 | Abs Max |
| Output short-circuit duration | | | | infinite | | Note 4: heat sink may be needed to hold junction below max | 2 | Abs Max |
| Current at supply pins | | -60 | | +60 | mA | | 2 | Abs Max |
| Operating temperature | TA | -40 | | 125 | C | | 2 | Abs Max |
| Maximum junction temperature | TJ | | | 150 | C | | 2 | Abs Max |
| Storage temperature | | -65 | | 150 | C | | 2 | Abs Max |
| Lead temperature, soldering 10 s | | | | 260 | C | | 2 | Abs Max |
| ESD, HBM | | 4 | | | kV | MIL-STD-883H Method 3015.8 (minimum level) | 2 | ESD table |
| ESD, CDM | | 2 | | | kV | JEDEC-EIA/JESD22-C101E (minimum level) | 2 | ESD table |
| Thermal resistance, 8-pin SOP | theta_JA / theta_JC | | 158 / 43 | | C/W | | 2 | Thermal Resistance |
| Thermal resistance, 8-pin MSOP | theta_JA / theta_JC | | 210 / 45 | | C/W | | 2 | Thermal Resistance |
| Thermal shutdown threshold | | | 160 | | C | "At 160 C the protection circuit will shut down the amplifier" | 9 | Output Drive Capability |
| Thermal shutdown recovery | | | 140 | | C | "Normal operation will resume when the junction cools to below 140 C" | 9 | Output Drive Capability |

Note: the "typ" in the thermal-resistance rows is simply the single printed value.

## 2. Quiescent current

| quantity | symbol | min | typ | max | unit | conditions | page | table/figure |
|---|---|---|---|---|---|---|---|---|
| Quiescent current per amplifier | IQ | | 6.5 | 7.5 | mA | TA = 25 C; supply voltage not stated in the row | 4 | Electrical Characteristics |
| Supply current (text) | | | 6.5 | | mA | "On only 6.5 mA of supply current" | 1 | Description |
| Shutdown current (TPH2503 only) | ISD | | 1 | 5 | uA | not applicable to TPH2502 | 4 | Electrical Characteristics |

Fig. "Quiescent Current vs. Temperature" (p5), y = supply current in mA, x = temperature in C, reading accuracy about +/-0.3 mA. The plot is not labelled per amplifier or per package, so whether it is per amplifier is not stated.

| T (C) | VS = +5 V (mA) | VS = +2.5 V (mA) |
|---|---|---|
| -40 | 5.9 | 3.0 |
| -25 | 6.3 | 3.2 |
| 0 | 6.8 | 3.4 |
| 25 | 7.2 | 3.6 |
| 50 | 7.5 | 3.75 |
| 75 | 7.9 | 3.95 |
| 100 | 8.4 | 4.2 |
| 125 | 8.9 | 4.4 |

## 3. Input offset, bias, offset current, common-mode range

| quantity | symbol | min | typ | max | unit | conditions | page | table/figure |
|---|---|---|---|---|---|---|---|---|
| Input offset voltage | VOS | -500 | +/-50 | +500 | uV | VCM = VDD/2 + 0.5 V; TA = 25 C | 3 | Electrical Characteristics |
| Offset voltage drift | VOS TC | | 1 | 2 | uV/C | -40 C to 125 C | 3 | Electrical Characteristics |
| Input bias current | IB | | 0.3 | 3 | pA | TA = 27 C | 3 | Electrical Characteristics |
| Input bias current | IB | | 150 | | pA | TA = 85 C (as printed; see inconsistencies) | 3 | Electrical Characteristics |
| Input bias current | IB | | 300 | | pA | TA = 125 C (as printed; see inconsistencies) | 3 | Electrical Characteristics |
| Input offset current | IOS | | 0.001 | | pA | no conditions given | 3 | Electrical Characteristics |
| Input common-mode voltage range | VCM | V- - 0.1 | | V+ - 0.1 | V | printed exactly so: min "V- -0.1", max "V+ -0.1"; no supply given | 3 | Electrical Characteristics |
| Input common-mode range, text | | | | | | "rail-to-rail input and output"; "immune to phase reversal when the input pins exceed the supply voltages" | 1, 8 | Features, Applications Information |

Fig. "Input Bias Current vs. Temperature" (p7), y in pA (axis -0.1 to 0.9), x in C (-40 to 140). Reading accuracy about +/-0.03 pA on y, +/-5 C on x. No supply or VCM given.

| T (C) | IB (pA, as plotted) |
|---|---|
| -40 to 80 | about 0.00 (indistinguishable from zero, below 0.01) |
| 95 | 0.03 |
| 110 | 0.10 |
| 125 | 0.30 |
| 132 | 0.5 |
| 138 | 0.85 |

Fig. 1 "No Phase Reversal" (p8): VS = +/-2.5 V; VIN is a sine of about 3.0 V peak (reading +/-0.2 V), period about 1 ms (axis -500 to 1000 us); VOUT clips near +2.5 V and about -2.4 V and does not invert. Reading accuracy +/-0.2 V.

## 4. CMRR, PSRR, open-loop gain

| quantity | symbol | min | typ | max | unit | conditions | page | table/figure |
|---|---|---|---|---|---|---|---|---|
| Common-mode rejection ratio | CMRR | 65 | 85 | | dB | VCM = -1 V to 3 V, VS = 5.4 V (as printed); TA = 25 C | 3 | Electrical Characteristics |
| Power supply rejection ratio | PSRR | 80 | 120 | | dB | VCM = VS/2, VS = 2.4 V to 5.5 V; TA = 25 C | 3 | Electrical Characteristics |
| Open-loop large-signal gain | AVOL | 85 | 110 | | dB | RLOAD = 2 kohm; TA = 25 C; supply not stated | 3 | Electrical Characteristics |

Fig. "CMRR and PSRR vs. Temperature" (p6), y in dB (0 to 160), x -50 to 125 C, conditions VS = 5 V, G = +1, RL = 1 kohm. Reading accuracy +/-5 dB (about 3 % of full scale).

| T (C) | CMRR (dB) | PSRR (dB) |
|---|---|---|
| -40 | 112 | 140 |
| 0 | 112 | 134 |
| 25 | 112 | 128 |
| 50 | 113 | 122 |
| 75 | 113 | 118 |
| 100 | 114 | 115 |
| 125 | 114 | 114 |

Fig. "Open Loop Gain vs. Temperature" (p7), y in dB (80 to 160), x -55 to 125 C, VS = 5 V, RL = 1 kohm (page header conditions). Reading accuracy +/-3 dB.

| T (C) | AVOL (dB) |
|---|---|
| -55 | 149 |
| -30 | 148 |
| -5 | 146 |
| 20 | 143 |
| 45 | 139 |
| 70 | 132 |
| 95 | 124 |
| 120 | 114 |
| 125 | 112 |

CMRR or PSRR versus frequency: not in the datasheet. VOS versus VCM or supply: not in the datasheet.

## 5. Bandwidth, gain-bandwidth, phase margin, open-loop gain and phase

| quantity | symbol | min | typ | max | unit | conditions | page | table/figure |
|---|---|---|---|---|---|---|---|---|
| Small-signal bandwidth, -3 dB | f-3dB | | 250 | | MHz | G = +1, VO = 100 mVpp, RF = 25 ohm (curve label on p1/p5 says RF = 24 ohm) | 3 | Electrical Characteristics |
| Small-signal bandwidth, -3 dB | f-3dB | | 90 | | MHz | G = +2, VO = 100 mVpp | 3 | Electrical Characteristics |
| Gain-bandwidth product | GBW | | 120 | | MHz | G = +10 | 3 | Electrical Characteristics |
| GBW, text | | | 120 | | MHz | "For gains >= 5 bandwidth is Gain x BW = 120 MHz"; unity-gain bandwidth 250 MHz | 1, 9 | Features, Applications Information |
| Bandwidth for 0.1 dB flatness | f0.1dB | | 25 | | MHz | G = +2, VO = 100 mVpp | 3 | Electrical Characteristics |
| Phase margin (numeric) | | not in the datasheet | | | | | | |
| Stability statement | | | | | | "unity-gain stable"; RF for G != +1 optimum between 300 ohm and 1 kohm; RF = 0 optimum for G = +1 | 1, 8, 9 | Description, Applications Information |

Fig. "Open Loop Gain And Phase" (p7). x = frequency 10 Hz to 1000 MHz (log). Left axis "Open-Loop Gain (dB)" -60 to 160. A second, unlabelled right axis has the same numeric scale (160 to -60) and is presumed to be phase in degrees, but its unit is not printed; and the phase curve sits near +90 over most of the band, so a phase-margin reading is not safe. Conditions are the page header (VS = 5 V, RL = 1 kohm). Reading accuracy: +/-10 dB or degrees, log-axis frequency +/-a factor 1.5. The two curves cross near about 1.5 kHz at roughly 90.

| f (Hz) | gain curve (dB) | phase curve (right-axis units) |
|---|---|---|
| 10 | 138 | 130 |
| 100 | 118 | 95 |
| 1 k | 98 | 90 |
| 10 k | 78 | 90 |
| 100 k | 58 | 90 |
| 1 M | 40 | 90 |
| 10 M | 20 | 88 |
| 100 M | 5 | 75 |
| about 300 M (gain curve reaches about 0 dB, +/- factor 2) | 0 | -5 |
| 1000 M | below -20 (leaves plot) | -60 (curve at plot bottom) |

Note the curve's DC gain (about 138 dB) is not the same as the AVOL table value (110 dB); see inconsistencies. A closed-loop phase margin cannot be derived from this plot with any claimed accuracy.

Closed-loop frequency response curves (p1 and p5, "Noninverting Small-Signal Frequency Response", VO = 0.1 Vpp, normalized gain dB, x 100 kHz to 1000 MHz): G = 1 (RF = 24 ohm) is flat within about +/-0.5 dB, with a slight peak near 100 MHz, then rolls off; G = 2, 5, 10 use RF = 620 ohm. The -3 dB frequencies of G = 5 and G = 10 were not read to any claimable accuracy; the printed values are the table rows above. "Inverting Small-Signal Frequency Response" (p5) gives G = -1 (RF = 24 ohm), -2, -5, -10 (RF = 620 ohm), same style; not digitised.

Fig. "Frequency Response for Various CL" (p5): G = +1, VO = 0.1 Vpp, RS = 0; CL = 5.6 pF, 47 pF, 100 pF. Peaking grows with CL; the tallest peak reads about +5.5 dB near 80 to 100 MHz (curve-to-label assignment is ambiguous in the image; reading +/-1.5 dB). The CL = 5.6 pF curve is nearly flat to about 100 MHz. A rejection notch/dip near 300 MHz of about -18 dB appears on one curve. Fig. "Frequency Response vs. Capacitive Load" (p6): G = +1, VO = 0.1 Vpp; CL = 5.6 pF with RS = 0, CL = 47 pF with RS = 50 ohm, CL = 100 pF with RS = 30 ohm; all three are within about +/-0.5 dB to about 30 MHz and roll off past about 100 MHz to -12 dB by about 200 to 300 MHz (+/-factor 1.5). Fig. "Frequency Response for Various RL" (p6): G = +1, RF = 0, VO = 0.1 Vpp, CL = 0 pF; RL = 50 ohm, 100 ohm, 1 kohm, 10 kohm; curves are within about 1 dB of each other (slight peaking up to about 0 dB near 100 MHz), -3 dB near 200 MHz, reading +/-30 %.

## 6. Slew rate, settling, transient, overload

| quantity | symbol | min | typ | max | unit | conditions | page | table/figure |
|---|---|---|---|---|---|---|---|---|
| Slew rate | SR | | 200 | | V/us | VS = 5 V, G = +1, 4 V step | 3 | Electrical Characteristics |
| Slew rate | SR | | 180 | | V/us | VS = 5 V, G = +1, 2 V step | 3 | Electrical Characteristics |
| Slew rate | SR | | 160 | | V/us | VS = 3 V, G = +1, 2 V step | 3 | Electrical Characteristics |
| Slew rate direction (rise vs fall) | | not in the datasheet | | | | | | |
| Rise-and-fall time, 10 to 90 % | tF | | 2 | | ns | G = +1, VO = 200 mVpp | 3 | Electrical Characteristics |
| Rise-and-fall time, 10 to 90 % | tF | | 7 | | ns | G = +1, VO = 2 Vpp | 3 | Electrical Characteristics |
| Settling time to 0.1 % | tS | | 25 | | ns | VS = 5 V, G = +1, 2 V output step | 3 | Electrical Characteristics |
| Settling time to 0.01 % | tS | | 40 | | ns | (same conditions column left blank in the row; presumed same as 0.1 % row) | 3 | Electrical Characteristics |
| Overload recovery time | tR | | 50 | | ns | VIN x Gain = VS | 3 | Electrical Characteristics |

Step response scope photos (p5): "Noninverting Small-Signal Step Response" (50 mV/div, 20 ns/div) and "Inverting Large-Signal Step Response" (200 mV/div, 20 ns/div). Both show a short overshoot at the leading edge and settle within roughly one division (about 20 ns). They are oscilloscope images with no numeric trace; not digitised.

## 7. Noise and distortion

| quantity | symbol | min | typ | max | unit | conditions | page | table/figure |
|---|---|---|---|---|---|---|---|---|
| Input voltage noise density | en | | 6.5 | | nV/rtHz | f = 1 MHz | 3 | Electrical Characteristics |
| Input current noise density | in | | 50 | | fA/rtHz | f = 1 MHz | 3 | Electrical Characteristics |
| Noise, 0.1 to 10 Hz | | not in the datasheet | | | | | | |
| 2nd harmonic distortion | HD2 | | -78 | | dBc | G = +1, f = 1 MHz, VO = 2 Vpp, RL = 200 ohm, VCM = 1.5 V | 3 | Electrical Characteristics |
| 3rd harmonic distortion | HD3 | | -90 | | dBc | G = +1, f = 1 MHz, VO = 2 Vpp, RL = 200 ohm, VCM = 1.5 V | 3 | Electrical Characteristics |
| THD+N | | not in the datasheet | | | | | | |
| Differential gain error | GE | | 0.02 | | % | NTSC, RL = 150 ohm | 3 | Electrical Characteristics |
| Differential phase error | PE | | 0.3 | | degrees | NTSC, RL = 150 ohm | 3 | Electrical Characteristics |

Fig. "Voltage Spectral Density vs. Frequency" (p6): y = voltage noise nV/rtHz (log, 1 to 10 k), x = frequency (log; labelled 10, 1k, 100k, 10M). Conditions are the page header. Reading accuracy about +/-20 % on y.

| f (Hz) | en (nV/rtHz) |
|---|---|
| 10 | 1500 |
| 100 | 480 |
| 1 k | 150 |
| 10 k | 48 |
| 100 k | 15 |
| 1 M | 7 |
| about 3 M | 6.3 (minimum of the curve) |
| 10 M | 8.5 |
| 20 M | 9 |

## 8. Input capacitance and impedance

| quantity | symbol | min | typ | max | unit | conditions | page | table/figure |
|---|---|---|---|---|---|---|---|---|
| Input capacitance, differential | CIN | | 2.7 | | pF | | 3 | Electrical Characteristics |
| Input capacitance, common mode | CIN | | 1 | | pF | | 3 | Electrical Characteristics |
| Input impedance, differential | RI | | 10^13 \|\| 2 | | ohm \|\| pF | | 4 | Electrical Characteristics |
| Input impedance, common mode | RI | | 10^13 \|\| 2 | | ohm \|\| pF | | 4 | Electrical Characteristics |

## 9. Output swing, output current, impedances, capacitive load

| quantity | symbol | min | typ | max | unit | conditions | page | table/figure |
|---|---|---|---|---|---|---|---|---|
| Output swing from supply rail (each of VOL and VOH, one row) | VOL, VOH | | 2 | 30 | mV | RLOAD = 100 kohm; TA = 25 C; supply not stated; the row does not separate the high rail from the low rail | 4 | Electrical Characteristics |
| Output swing under other loads | | not in the datasheet (no table row) | | | | | | |
| Output swing, text | | | 2.7 | | V | "continuous output current of +/-100 mA and still provide approximately 2.7 V of output swing on a 5 V supply" (as worded; unclear whether peak-to-peak) | 9 | Output Drive Capability |
| Continuous output current, text | | -100 | | +100 | mA | "not recommended to run a continuous DC current in excess of +/-100 mA" | 9 | Output Drive Capability |
| Output short-circuit current, sink | ISC | 100 | 160 | | mA | no further conditions | 4 | Electrical Characteristics |
| Output short-circuit current, source | ISC | 100 | 290 | | mA | no further conditions | 4 | Electrical Characteristics |
| Peak output current, text | | | 200 | | mA | "peak currents up to 200 mA, which corresponds to the typical short-circuit current" | 9 | Output Drive Capability |
| Closed-loop output impedance | ROUT | | 0.01 | | ohm | G = 1, f = 1 kHz, IOUT = 0 | 4 | Electrical Characteristics |
| Open-loop output impedance | RO | | 21 | | ohm | f = 1 kHz, IOUT = 0 | 4 | Electrical Characteristics |
| Output swing vs output current curve | | PRESENT? NO. The text on p9 says "Refer to the typical characteristic curve Output Voltage Swing vs Output Current", but no such figure exists anywhere in the 18 pages | | | | | 9 | text only |
| Capacitive load statement | | | | | | "can drive 10 pF loads in parallel with 1 kohm with less than 5 dB of peaking at gain of +1"; a series resistor of 5 to 50 ohm at the output reduces peaking; back-termination for cables | 9 | Driving Capacitive Loads and Cables |
| Maximum stable CL | | not in the datasheet (curves only to 100 pF, see section 5) | | | | | | |

Fig. "Closed-Loop Output Impedance vs. Frequency" (p6): y = output impedance in ohm (log, 0.01 to 100), x = frequency 100 kHz to 1000 MHz. The inset shows a TPH2501 follower. Reading accuracy about a factor of 1.5 on y (log axis).

| f (Hz) | Zo (ohm) |
|---|---|
| 100 k | 0.02 |
| 1 M | 0.15 |
| 10 M | 1.5 |
| about 30 M | 10 |
| 100 M | 25 |
| 300 M | 60 (peak) |
| 1000 M | 45 |

Notice that the 1 kHz closed-loop value in the table (0.01 ohm) is below the left edge of the plot, and the 1 kHz open-loop value (21 ohm) has no plot.

## 10. Crosstalk

| quantity | symbol | min | typ | max | unit | conditions | page | table/figure |
|---|---|---|---|---|---|---|---|---|
| Channel-to-channel crosstalk, TPH2502 | Xtalk | | -100 | | dB | f = 5 MHz | 3 | Electrical Characteristics |
| Channel-to-channel crosstalk, TPH2504 | Xtalk | | -84 | | dB | f = 5 MHz | 3 | Electrical Characteristics |

Fig. "Channel-To-Channel Crosstalk" (p6): y = crosstalk, input-referred, dB (-150 to -80), x = frequency 100 kHz to 1000 MHz. The curve is not labelled by part. Reading accuracy +/-4 dB.

| f (Hz) | crosstalk (dB) |
|---|---|
| 100 k | -140 |
| 500 k | -141 |
| 1 M | -139 |
| 2 M | -132 |
| 5 M | -118 |
| 10 M | -111 |
| 30 M | -108 |
| 60 M | -107 |
| 100 M | -100 |
| 200 M | -93 |
| 300 M | -92 |
| 600 M | -93 |
| 1000 M | -92 |

## 11. Pin facts for the TPH2502 (8-pin SOP/MSOP, top view, p1)

| pin | name | function (p8 Pin Functions where given) |
|---|---|---|
| 1 | Out A | Amplifier A output |
| 2 | -In A | Amplifier A inverting input |
| 3 | +In A | Amplifier A non-inverting input |
| 4 | -Vs | Negative supply (V-), "normally tied to ground", may be another voltage as long as V+ to V- is 2.5 to 5.5 V; bypass with 0.1 uF if not grounded |
| 5 | +In B | Amplifier B non-inverting input |
| 6 | -In B | Amplifier B inverting input |
| 7 | Out B | Amplifier B output |
| 8 | +Vs | Positive supply (V+), 2.5 V to 5.5 V; bypass 0.1 uF close to part |

Order numbers: TPH2502-SR (8-pin SOP, tape and reel 4,000), TPH2502-VR (8-pin MSOP, 3,000), marking TPH2502 (p2). No exposed pad is shown. Power-supply bypass guidance: 4.7 uF tantalum in parallel with 0.1 uF ceramic from V+ to ground (p10). The two amplifiers share the supply pins; no pin links them otherwise (no shutdown pin on the TPH2502).

Other model-relevant text:
- Thermal shutdown at 160 C, recovery 140 C (p9).
- Input ESD structure (p11, Figure 4): current-steering diodes from each input to both V+ and V-. Diode parameters are not given.
- The inputs are CMOS (pA-level bias current), output is rail-to-rail.

## Internal inconsistencies (reported, not resolved)

1. Absolute max supply 7.0 V (p2) versus "higher than 7.5 V (absolute maximum)" (p8).
2. Input bias current table: 150 pA at 85 C and 300 pA at 125 C (p3), versus the IB-vs-T curve (p7) which reads about 0.0 pA at 85 C and 0.3 pA at 125 C. Table at 27 C is 0.3 pA, typ.
3. IQ typical 6.5 mA at 25 C (p4), versus the IQ-vs-T curve for VS = 5 V which reads about 7.2 mA at 25 C (p5).
4. CMRR typical 85 dB (p3) versus curve about 112 dB (p6); PSRR typical 120 dB versus curve about 128 dB at 25 C.
5. AVOL typical 110 dB with RL = 2 kohm (p3) versus curves of about 143 dB at 25 C (p7, temperature) and about 138 dB at 10 Hz (p7, Bode).
6. Crosstalk table -100 dB at 5 MHz (p3) versus curve about -118 dB at 5 MHz (p6).
7. Differential gain error 0.02 % (p3) versus text "0.03 %" (p9); the text also says "while driving 150 ohm at a gain of 2".
8. Slew rate 180 V/us in Features (p1) versus 200 V/us for the 4 V step (p3).
9. Short-circuit current: sink 160 mA, source 290 mA (p4) versus text "typical short-circuit current 200 mA" (p9).
10. Common-mode input impedance 10^13 ohm || 2 pF (p4) versus common-mode input capacitance 1 pF (p3).
11. Input common-mode range row printed as V- - 0.1 to V+ - 0.1 (p3), which does not match the "rail-to-rail input" claim; reported as printed.
12. Text (p9) says 10 pF drives with under 5 dB peaking; the CL curves (p5) only start at 5.6 pF and show about 5.5 dB at the highest CL.
13. Text on p9 describes dG/dP as "0.03 % and 0.3 degrees" at gain of 2, whereas the table says 0.02 % and 0.3 degrees at NTSC, RL = 150 ohm.
14. CMRR condition "VCM = -1 V to 3 V, VS = 5.4 V" cannot be single-supply 0 to 5.4 V; no explanation given.

## Gaps

Requested items that are NOT in the datasheet:
- Numeric phase margin (only the unlabelled-axis Bode plot on p7; not usable to claim a number).
- Open-loop gain and phase curve with labelled phase axis; phase-axis units not printed.
- Input offset current beyond a single typical (no min/max, no temperature behavior).
- Input bias current at a stated VCM or supply; IB measured conditions beyond temperature.
- Input voltage noise 0.1 Hz to 10 Hz (peak-to-peak).
- THD+N (only HD2 and HD3 at 1 MHz, 2 Vpp, RL = 200 ohm).
- Output swing versus load or versus output current: the p9 text cites a curve "Output Voltage Swing vs Output Current", which is ABSENT from this document. Only the single row VOL/VOH = 2 mV typ, 30 mV max at RL = 100 kohm exists, and that row does not give the low and high rails separately.
- Output swing at RL = 1 kohm, 150 ohm or any other load (no table).
- Short-circuit current versus supply or temperature.
- Open-loop output impedance versus frequency (only 21 ohm at 1 kHz); closed-loop output impedance at 1 kHz appears only in the table (0.01 ohm).
- Maximum capacitive load for stability (only the 10 pF statement and curves from 5.6 to 100 pF).
- CMRR and PSRR versus frequency.
- Supply voltage for the main Electrical Characteristics table (only "fully specified at 2.7 V and 5.0 V").
- Separate positive and negative slew rate; slew rate versus temperature.
- Overload/rail recovery separately for the positive and the negative rail (one tR = 50 ns row).
- Offset voltage versus common-mode voltage, supply, or temperature curve.
- Input ESD diode parameters.
- Per-channel (TPH2502) versus family differences other than the crosstalk row.
- Power-up behaviour or turn-on time.
- Any detail of the internal transfer function, poles or zeros.

## Counts (for the caller)

About 75 numeric facts in tables (rows with a value), 9 digitised curves with point tables (IQ vs T, IB vs T, CMRR/PSRR vs T, AVOL vs T, open-loop gain and phase, noise density, closed-loop output impedance, crosstalk, plus the qualitative CL and RL response curves), 14 listed inconsistencies, 20 gaps.
