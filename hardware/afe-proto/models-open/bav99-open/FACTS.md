# BAV99 facts (clean room: datasheet only)

Written from Nexperia "BAV99 High-speed switching diode", Product data sheet, BAV99 v.9, 1 July 2022 (10 pages) only; no vendor SPICE model was opened.

Document confirmation: maker Nexperia (copyright Nexperia B.V. 2022). The document covers ONE type, BAV99 (the revision history, Table 8, says the family datasheet was reduced to a single-type datasheet in v.9; earlier IDs BAV99_SER_8, BAV99S_3, BAV99W_4 are only listed as superseded). Package SOT23 (TO-236AB), 3 terminals, 2.9 x 1.3 x 1 mm body (Table 3). Marking code A7% (% = manufacturing site code) (Table 4). No temperature below Tamb -65 C to 150 C is rated. No LCSC/other-vendor data is in the document.

## Pinout and internal connection (p.2, Table 2, 006aaa763)

| pin | symbol | description |
|---|---|---|
| 1 | A1 | anode (diode 1) |
| 2 | K2 | cathode (diode 2) |
| 3 | K1, A2 | cathode (diode 1) and anode (diode 2) |

Internal connection: two diodes in series, common node = pin 3 (cathode of diode 1 joined to anode of diode 2). The graphic symbol shows A1 at bottom left, K2 at bottom right, and the series junction K1,A2 at top. Per-diode data below applies to each diode.

## Absolute maxima (p.3, Table 5, IEC 60134)

| quantity | symbol | min | typ | max | unit | conditions | page | table |
|---|---|---|---|---|---|---|---|---|
| reverse voltage | VR | - | - | 100 | V | per diode | 3 | 5 |
| repetitive peak reverse voltage | VRRM | - | - | 100 | V | per diode | 3 | 5 |
| forward current | IF | - | - | 215 | mA | single diode loaded | 3 | 5 |
| forward current | IF | - | - | 125 | mA | double diode loaded | 3 | 5 |
| repetitive peak forward current | IFRM | - | - | 500 | mA | per diode | 3 | 5 |
| non-repetitive peak forward current | IFSM | - | - | 4 | A | tp = 1 us, square wave, Tj(init) = 25 C | 3 | 5 |
| non-repetitive peak forward current | IFSM | - | - | 1 | A | tp = 1 ms, square wave, Tj(init) = 25 C | 3 | 5 |
| non-repetitive peak forward current | IFSM | - | - | 0.5 | A | tp = 1 s, square wave, Tj(init) = 25 C | 3 | 5 |
| total power dissipation | Ptot | - | - | 250 | mW | per device, one diode loaded, Tamb <= 25 C, FR4 PCB, single-sided copper, tin-plated, standard footprint | 3 | 5 |
| junction temperature | Tj | - | - | 150 | C | per device | 3 | 5 |
| ambient temperature | Tamb | -65 | - | 150 | C | | 3 | 5 |
| storage temperature | Tstg | -65 | - | 150 | C | | 3 | 5 |

## Thermal resistance (p.3, Table 6)

| quantity | symbol | min | typ | max | unit | conditions | page | table |
|---|---|---|---|---|---|---|---|---|
| thermal resistance junction to ambient | Rth(j-a) | - | - | 500 | K/W | single diode loaded; free air; FR4 PCB, single-sided copper, tin-plated, standard footprint | 3 | 6 |
| thermal resistance junction to solder point | Rth(j-sp) | - | - | 360 | K/W | no further conditions stated | 3 | 6 |

## Electrical characteristics, per diode (p.4, Table 7; all Tamb = 25 C unless stated)

Forward voltage VF (only maxima given; no min or typ in the table):

| quantity | symbol | min | typ | max | unit | conditions | page | table |
|---|---|---|---|---|---|---|---|---|
| forward voltage | VF | - | - | 715 | mV | IF = 1 mA, Tamb = 25 C | 4 | 7 |
| forward voltage | VF | - | - | 855 | mV | IF = 10 mA, Tamb = 25 C | 4 | 7 |
| forward voltage | VF | - | - | 1 | V | IF = 50 mA, Tamb = 25 C | 4 | 7 |
| forward voltage | VF | - | - | 1.25 | V | IF = 150 mA, Tamb = 25 C | 4 | 7 |

Reverse current IR (only maxima given):

| quantity | symbol | min | typ | max | unit | conditions | page | table |
|---|---|---|---|---|---|---|---|---|
| reverse current | IR | - | - | 30 | nA | VR = 25 V, Tamb = 25 C | 4 | 7 |
| reverse current | IR | - | - | 0.5 | uA | VR = 80 V, Tamb = 25 C (also Table 1, p.1) | 4 | 7 |
| reverse current | IR | - | - | 30 | uA | VR = 25 V, Tj = 150 C | 4 | 7 |
| reverse current | IR | - | - | 50 | uA | VR = 80 V, Tj = 150 C | 4 | 7 |

Capacitance, recovery:

| quantity | symbol | min | typ | max | unit | conditions | page | table |
|---|---|---|---|---|---|---|---|---|
| diode capacitance | Cd | - | - | 1.5 | pF | VR = 0 V, f = 1 MHz, Tamb = 25 C | 4 | 7 |
| reverse recovery time | trr | - | - | 4 | ns | IF = 10 mA, IR = 10 mA, IR(meas) = 1 mA, RL = 100 ohm, Tamb = 25 C | 4 (also 1) | 7 (1) |
| peak forward recovery voltage | VFRM | - | - | 1.75 | V | IF = 10 mA, tr = 20 ns, Tamb = 25 C | 4 | 7 |

Features list (p.1): trr <= 4 ns; Cd <= 1.5 pF; VR <= 100 V.

## Test conditions (p.5, Section 11)

Fig. 5 (mga881), reverse recovery time test: source RS = 50 ohm, V = VR + IF x RS, DUT in series with a capacitor, sampling oscilloscope Ri = 50 ohm. Input signal: reverse pulse rise time tr = 0.6 ns; reverse voltage pulse duration tp = 100 ns; duty cycle 0.05. Oscilloscope rise time tr = 0.35 ns. Output waveform: +IF then reverse current recovering; trr measured to the point where reverse current reaches IR = 1 mA ((1) in figure). 10 %/90 % points are marked on the input edge.

Fig. 6 (mga882), forward recovery voltage test: source RS = 50 ohm, 1 kohm series resistor, 450 ohm resistor, DUT, oscilloscope Ri = 50 ohm. Input signal: forward pulse rise time tr = 20 ns; forward current pulse duration tp >= 100 ns; duty cycle <= 0.005. VFR is the peak of the forward voltage overshoot on the output.

## Curves (read by eye from the rendered figures; no numeric data provided by the datasheet)

Fig. 1 and Fig. 2 were digitised from the 400 dpi page render with pixel-located gridlines (method and accuracy under each figure). Fig. 3 and Fig. 4 were read by eye from the 100 dpi view only and are coarser: Fig. 3 about ±0.01 pF, Fig. 4 about ±0.1 decade; they have not been re-read at 400 dpi.

### Fig. 1 (006aab132, p.4): IF (mA, log, 0.1 to 1000) vs VF (V, linear, 0 to 1.4), typical values
Curves: (1) Tamb = 150 C, (2) 85 C, (3) 25 C, (4) -40 C. Left to right in order 1, 2, 3, 4; they converge toward the top right. All four span IF = 0.1 mA to about 400 mA inside the plot.

Method: page 4 rendered at 400 dpi, plot cropped and thresholded. Gridlines located in pixels: vertical lines every 0.1 V at x = 101.5 + 634.3 x VF (0 V and 1.4 V lines at 101.5 and 989.5 px); decade lines at y = 55.5 (1000 mA), 277.5, 499.5, 721.5, 944.5 (0.1 mA), i.e. 222.25 px per decade. For each pixel row (excluding rows on or adjacent to gridlines) the four dark runs wider than 6 px (curve strokes, about 6-9 px wide) were centred, giving 4 traces; VF at each target IF was linearly interpolated along the trace on the log axis.

| IF (mA) | (1) 150 C VF (V) | (2) 85 C VF (V) | (3) 25 C VF (V) | (4) -40 C VF (V) |
|---|---|---|---|---|
| 0.1 | 0.188 | 0.352 | 0.497 | 0.654 |
| 0.3 | 0.263 | 0.415 | 0.550 | 0.698 |
| 1 | 0.348 | 0.486 | 0.611 | 0.745 |
| 3 | 0.429 | 0.554 | 0.671 | 0.790 |
| 10 | 0.526 | 0.638 | 0.743 | 0.847 |
| 30 | 0.639 | 0.739 | 0.827 | 0.920 |
| 100 | 0.840 | 0.914 | 0.984 | 1.060 |
| 300 | 1.210 | 1.247 | 1.288 | 1.349 |

Accuracy of these readings: stroke-centre uncertainty about 1.5 px in each axis, plus 1 px calibration, plus the curve's own line width. On x that is about +-3 mV (1 px = 1.6 mV); on y it is about +-0.007 to 0.011 decade (+-1.5 to 2.5 px at 222 px/decade), which converts to +-1 to 2 mV at 0.1-10 mA, +-2 to 4 mV at 30-100 mA, and +-4 to 5 mV at 300 mA where the curves are shallow. Combined stated accuracy: +-5 mV for IF <= 30 mA, +-8 mV at 100 and 300 mA. The 300 mA row for curve (4) lies close to the plot's top rows (valid trace rows begin at y = 169, IF about 330 mA); treat as less certain, about +-10 mV. Consistency check against Table 7 (25 C maxima): curve (3) gives 0.611 V at 1 mA (max 715 mV), 0.743 V at 10 mA (max 855 mV), about 0.89 V at 50 mA (max 1 V, interpolated between the 30 and 100 mA rows, not separately read), all below the maxima.

### Fig. 2 (006aab133, p.4): IR (uA, log, 1e-5 to 1e2) vs VR (V, linear, 0 to 100), typical values
Curves: (1) 150 C, (2) 85 C, (3) 25 C, (4) -40 C. All four rise slowly and smoothly with VR; no breakdown visible up to 100 V. The curves begin at VR of about 1 V (the plot at 0 V carries no curve), and start with a short steeper rise over the first 1-5 V. Method as for Fig. 1: gridlines at x = 276.5 + 8.89 x VR (px), decades at y = 55.5 (100 uA) to 944.5 (1e-5 uA), 127 px per decade; stroke centre per column read at columns offset 3 and 5 px either side of each VR (VR = 50 V sits on a gridline) and averaged.

| VR (V) | (1) 150 C IR (uA) | (2) 85 C IR (uA) | (3) 25 C IR (uA) | (4) -40 C IR (uA) |
|---|---|---|---|---|
| 1 | 9.6 | 0.32 | 4.9e-3 | 3.4e-5 |
| 10 | 13.7 | 0.48 | 6.9e-3 | 3.6e-5 |
| 25 | 16.5 | 0.59 | 8.5e-3 | 4.1e-5 |
| 50 | 19.6 | 0.72 | 1.05e-2 | 5.0e-5 |
| 75 | 22.6 | 0.85 | 1.32e-2 | 5.5e-5 |
| 95 | 27.5 | 1.07 | 1.94e-2 | 6.4e-5 |
| 99 | 29.4 | 1.17 | 2.2e-2 | 6.4e-5 |

Accuracy: stroke centre +-1.5 px at 127 px per decade, i.e. +-0.012 decade (about +-3 %), and +-0.05 V of x position is negligible. Points at VR = 1 V (curve start) and 95-99 V are less certain (stroke steeper or ending, +-0.02 decade). Table 7 anchors: curve (3) at 25 V is 8.5 nA against the 30 nA maximum; curve (1) at 80 V (between the 75 and 95 V rows) is about 24 uA against the 50 uA maximum.

### Fig. 3 (mbg446, p.5): Cd (pF, linear, 0 to 0.8) vs VR (V, linear, 0 to 16), f = 1 MHz, Tamb = 25 C, typical

| VR (V) | Cd (pF) |
|---|---|
| 0 | 0.60 |
| 1 | ~0.52 |
| 2 | ~0.49 |
| 4 | ~0.475 |
| 8 | ~0.46 |
| 12 | ~0.457 |
| 16 | ~0.455 |

Accuracy ±0.01 pF. Note the typical curve value at VR = 0 V (about 0.6 pF) is below the Table 7 maximum of 1.5 pF.

### Fig. 4 (mbg704, p.5): IFSM (A, log, 0.1 to 100) vs tp (us, log, 1 to 1e4), square wave, Tj(init) = 25 C, typical

| tp (us) | IFSM (A) |
|---|---|
| 1 | ~4 |
| 10 | ~2.2 |
| 100 | ~1.4 |
| 1000 | ~1.0 |
| 10000 | ~0.75 |

Accuracy ±0.1 decade.

## Other data present

Package outline (p.6, Fig. 7): body 2.8-3.0 x 1.2-1.4 mm, height 0.9-1.1 mm, pin pitch 1.9 mm, overall 2.1-2.5 mm. Reflow and wave solder footprints on p.7 (Fig. 8, 9). Not needed for the model.

## Gaps

Not in the datasheet:
- Any SPICE parameter (IS, N, RS, CJO, VJ, M, TT, BV, IBV, EG, XTI) or a series-resistance figure.
- Typical and minimum values for VF, IR, Cd, trr, VFRM (Table 7 gives maxima only).
- Reverse breakdown voltage and the current at breakdown (only VR/VRRM = 100 V rating; no V(BR)R row).
- Numerical VF-IF data as a table: only the 25 C maxima exist as numbers; the Fig. 1 values are the writer's pixel readings of a typical curve.
- Capacitance at reverse voltage above 16 V; capacitance vs temperature; junction capacitance vs forward bias.
- Reverse recovery charge, trr at other conditions, storage time, trr vs temperature.
- VF at -40, 85 or 150 C as table values; IR at -40 or 85 C as table values.
- Thermal resistance conditions for Rth(j-sp) (none stated), thermal capacitance.
- Pin-to-pin leakage or coupling between the two diodes; lead inductance; package capacitance.
- Reading accuracy of every curve is the writer's own estimate, not stated by Nexperia.
- Fig. 2 curves do not extend below VR of about 1 V; IR at 0 V is not plotted.
