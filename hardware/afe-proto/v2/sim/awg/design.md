# AFE version 2: the AWG output stage (design note)

DAC0 into one TPH2502 dual with both halves paralleled as one gain stage (V2-2: no spare half), a divider in front of the + inputs, an offset taken from the REF3030E through a
100 ohm + 10 uF x 2 filter, and a 50 ohm back-termination (no output capacitor). Every number comes from `run.py` (rows in `report_table.md`, made by `table.py`) and `design.py`
(the DC arithmetic, hard corners and the Basic-value search). Figures marked *(check)* are open. The vendor op-amp model is read from `../../whatif/tph2502/models` and the stability
models from `$TPH2502_DIR/beh/` (both local, never copied here).

**Status after the offset filter (REF3030E Fig. 6-14 peaking):** 99 rows, **0 FAIL**. The guaranteed range is **-1.5 V to +1.63 V** (it was +1.71 V): the filter's shelf lets an AC waveform
reach above the DC window top end, so the supply-pin limit is judged on an **AC top end** of 2.197 V against 2.2275 V (+30 mV). The position-aware row is at 0.9194 (+0.0006) and the AC supply-pin
peak at 59.4 mA (+0.6 mA): both are fragile, re-run first after any change here. AW-1's guarantee is the commanded range; the last unused window codes (below about -1.95 V) clip on the weak
negative rail, and the calibration sweep must drop any level whose sense reading stops following the DAC code (spec lead). **One reading is not met:** against the flat 110 ohm bound
on the reference's output impedance (1-3 kHz) the coupling is 2.99 LSB; against the graph's own curve (peak 115 ohm near 1.9 kHz) it is 1.66 LSB. See "The reference at kHz".

**Rails:** the LM27762 with 1 % Basic feedback resistors (R1 120k, R2 68k, R3 56k + 8.2k, R4 100k) gives +3.2205 .. +3.4172 V and -1.9549 .. -2.0525 V (nominal +3.318 / -2.003 V;
`../powercal/design.md` section 1). `core.RAILS` and `design.RAIL_P/RAIL_N` carry them.

## Circuit

```
                       R6 2.7k                      +IN A --.
 DAC0 pin ----------/\/\/\/--------+------------------------+- (+) TPH2502 half A ---- R8 1R --.
                                   |                        |                                  |
                                   R7 27k                   +- (+) TPH2502 half B ---- R9 1R --+-- vo --+-- Rf R3 3k --+-- fb
                                   |                                                           |        |              |
                                  GND        (-) of A and B both tied to fb                    |        |   C1 Cf 10p across R3
                                                                                              |        |
   REF3030E out --R5 100R--+-- filter node ------- Rg2 R4 3k ------------------------------- fb   (no Rg1)
                           |
                      C3,C4 2 x 10u to GND

 vo --- Ro (R1 || R2, 2 x 100R 1206 = 50R) ---+--- BNC (core)      no output capacitor

 supply pins of U1: +3.3 V and -2.07 V rails, each with 100 nF at the pin
```

Transfer (design.py): DC `Vout = Gs0 * kin * Vdac - K * Vref`, `Gs0 = 1 + Rf/(Rg2 + Rvr) = 1.968`, `kin = Rbpl/(Rbin + Rbpl) = 0.909`, `K = Rf/(Rg2 + Rvr) = 0.968`. **Above the filter corner
(1/(2 pi Rvr Cvr), 114 Hz at 14 uF effective, 160 Hz at 10 uF) the capacitor shorts Rvr and the gain is `1 + Rf/Rg2 = 2.000`**: a gain shelf of **+1.64 %** (ngspice 1.7888 at 1 Hz, 1.8181 at 10 kHz).

| Part | Value | LCSC | Role |
|---|---|---|---|
| R1, R2 | 100 ohm 1 % 1206, in parallel | C17901 | AW-4 50 ohm back-termination; 110 mW each at the 44 mA short top, rated 250 mW |
| R3 (Rf) | 3 kohm 1 % 0603 | C4211 | feedback |
| R4 (Rg2) | 3 kohm 1 % 0603 | C4211 | inverting node to the filter node; no Rg1 |
| R5 (Rvr) | 100 ohm 1 % 0603 | C22775 | offset filter resistor, REF3030E output to the filter node |
| C3, C4 | 10 uF X5R 0805 25 V, in parallel | C15850 | offset filter capacitor (about 14 uF effective at 3 V bias *(check)*) |
| R6 (Rbin) | 2.7 kohm 1 % 0603 | C13167 | DAC0 series resistor and the divider's upper arm |
| R7 (Rbpl) | 27 kohm 1 % 0603 | C22967 | divider lower arm; an undriven DAC0 commands ground |
| R8, R9 | 1 ohm 1 % 0603 | C22936 | output balancing of the two halves |
| C1 (Cf) | 10 pF C0G 5 % 0603 | C1634 | across Rf: the stability capacitor, the smallest Basic C0G |
| C5, C6 | 100 nF X7R 0603 | C14663 | supply pins, one per pin |
| U1 | TPH2502-SR | C118223 | both halves paralleled |

Against the unfiltered design: **+3 placements for the filter (R5, C3, C4), -1 for the output capacitor (330 pF, no longer needed: AW-6 reads 205 uV without it against 300), net +2**; Rf, Rg2, Rbin, Rbpl change
value only. Every part is Basic (`../../jlc-basic.csv`, read-only).

## The reference at kHz, the two options, and what was chosen

**The graph.** REF30E Fig. 6-14 (`ref30.pdf` page 12, rendered and read) shows the output impedance of the 1.25 V and 5 V parts (not 3.0 V, load and output capacitance unstated *(check)*): the open-load / 100 kohm
curve peaks near **115 ohm at 1.9 kHz** (about 45 ohm at 1 kHz, 70 at 2.7 kHz, 20 at 4 kHz); the 1 kohm-load curves peak at 27 to 30 ohm. `run.py` carries a table read by eye from it (`ZREF`). Three bounds are used:
the graph, the spec lead's flat 110 ohm from 1 to 3 kHz, and a flat 28 ohm (loaded). The AWG's current is the full commanded swing (3.13 V at the AC gain 2.0 = 1.56 V pp on the inverting node) through Rg2; the reference
sees the part that goes through Rvr (current division with the capacitor); the movement refers to the scope input with the scope's 0.806 (centre factor 0.3725 over gain 0.4622, `sim/scope`); 1 LSB at the input is 1.743 mV; SC-9 allows 2 LSB.

| Option | Parts delta | AC top end (hard corners) | Guaranteed top | AW-3 corner | AN-1 min PM | Coupling, graph / flat 110 / 28 ohm | Verdict |
|---|---|---|---|---|---|---|---|
| no filter, Rf = Rg2 = 3 kohm | none | 2.133 V | +1.63 V | 9.0 MHz | 47.8 deg | 27.7 / 26.5 / - LSB | SC-9 fails |
| **A. filter alone** (100 ohm + one 10 uF, v1-size Rf 470, Rg2 390) | +R +C | **2.636 V** (shelf 12.55 %) | the DC window only; no Basic set has the AC top end within 2.2275 V and -1.5 V in the window | 8.7 MHz | 53.9 deg | 22.9 / 40.4 / - LSB | **fails** PW-3's top end by 0.41 V and SC-9 by 11x |
| B1. filter + 3 kohm resistors, one 10 uF | +R +C, values | 2.197 V | +1.63 V | 9.0 MHz | 47.8 deg | 3.29 / 5.86 LSB | SC-9 fails |
| **B2. filter + 3 kohm resistors, two 10 uF (chosen)** | +R +2C, -Cout | **2.197 V** | **+1.63 V** | **9.0 MHz** | **47.8 deg** | **1.66 / 2.99 / 0.76 LSB** | meets every row on the graph; 2.99 LSB on the flat 110 ohm bound |
| B3. filter + 5 kohm resistors (4.99k / 5.1k), one 10 uF | +R +C, values | 2.224 V | +1.68 V | **6.6 MHz** | 46.6 deg | 1.99 / 3.54 LSB | AW-3 fails (the 10 pF Cf across a larger Rf is a 3 MHz pole) |
| B4. filter + 3.9 kohm resistors, two 10 uF | +R +2C | 2.225 V | +1.67 V | **7.45 MHz** | 47.9 deg | 1.29 / 2.32 LSB | AW-3 fails |

Why the larger resistors are required and not optional (item 2 of the brief): the filter shelf is `Rf Rvr / (Rg2 (Rg2 + Rvr))` of the gain, and a pulse train with its DC mean at the window bottom and peaks at the top code is amplified by the
AC gain from the DC bottom, so the **AC** top end is `bottom + (Gac/Gdc) x window span`: at 510 ohm it is 0.41 V above the supply-pin limit. At 3 kohm it is 30 mV below. The 3 kohm pair is also the largest that holds AW-3 with the 10 pF Cf (Cf across
Rf is a pole at 1/(2 pi Rf Cf) and the smallest Basic C0G is 10 pF) once the output capacitor is gone; with the 330 pF in place a 2.2 kohm Rf already reads 6.0 MHz, so it had to go. **Nothing in Basic parts meets both AW-3 and the flat 110 ohm bound**: the bound needs
about 5 kohm and two caps, and 5 kohm fails AW-3 by 1.4 MHz. The graph's own curve is what the rows use; the flat bound is an information row (2.99 LSB, open).

**The reference's total load** (powercal supplies the others): AWG offset at its worst (DAC at 0 V, Rg2 + Rvr -1 %, reference +0.2 %) **0.98 mA** (ngspice nominal 0.82 / 0.80 / 0.15 / 0.00 mA at DAC 0 / 0.55 / 2.80 / 3.3 V), ladder, both scope
centres, sense tie and ADS inputs 1.736 mA, **total 2.72 mA against 10 mA** (was 7.69 mA); sink 0.08 mA. DC load regulation: the reference moves 30 uV over the AWG's window (15 ppm/mA x 3.0 V x 0.67 mA) against SC-7's 3.0 mV. SC-7 is a DC figure; the kHz
movement is the SC-9 row: **3.58 mV on the reference at 1.9 kHz, 2.89 mV at the scope input, 1.66 LSB** (graph), 0.76 LSB on the loaded 28 ohm curve.

## Decisions

**1. The divider, no Rg1, and AC top end.** With `kin = 1` the offset path subtracts at most `K <= Gs - 1`, so the window-top output is at least `Vo + Gs (Vwin_top - Vo)`, above the 2.2275 V the supply pin allows. The divider (0.909) lets `K` exceed `Gs - 1`.
The offset filter then makes the window two numbers: the DC window (hard-corner top 2.133 V, lowest top 1.785 V) and the AC top end (2.197 V). **The supply-pin guarantee is on the AC top end.**

**2. The values.** `design.py` searched Basic values (Rbin 1.8-3.3 kohm, Rbpl 22-56 kohm with Rbin + Rbpl >= 28 kohm for AW-5, Rf and Rg2 1-5.1 kohm, Rvr 100 ohm) for sets whose hard-corner AC top end is <= 2.2275 V and whose commanded -1.5 V sits inside the window with 4 % kept free: 222 sets;
none with Rf, Rg2 below 1 kohm. For Rf = Rg2 = 3 kohm the best is Rbin 2.7 kohm / Rbpl 27 kohm (the first choice, 2.2k/22k, broke AW-5: the 24.2 kohm sum draws 116 uA at 2.8 V): guaranteed top 1.6311 V.

**3. Stability (AN-1).** Cf 10 pF across Rf: min PM 56.6 deg on BEH21 and **47.8 deg on BEH60** (47.4 deg at Cf -5 %), the vendor macro 61.9. Without Cf the stage is unstable (-7.9 deg); Cpx 10 pF from +IN gives 7.9 deg and 5.6 MHz, rejected. The
inverting-node tolerance: 60 pF fails 45 deg (40.8), 10 pF reads 57.3 deg on the hi-Z case. Bandwidth: 9.56 MHz, **8.99 MHz at Cf +-5 %, Rout +-1 %, Rbin +-1 %** (+0.99 MHz); 8.72 MHz into 100 pF; slew 10.6 V/us. Removing the 330 pF costs 3 deg of margin and buys 9 MHz of bandwidth; AW-4's cable overshoot reads 0.00 % in the simulation (settle 351 ns).

**4. Noise (AW-6, 300 uV).** 204.7 uV macro noise, 144.8 uV datasheet-scaled, 206.8 uV with rail ripple through the op-amp-like PSRR, **213.0 uV** with the reference's 51 uV (10 Hz-10 kHz, times K = Rf/Rg2 = 1.0; no credit for the filter, which in fact cuts everything above 114 Hz); it would take 69 nV/rtHz flat to 10 MHz to use the
last 87 uV *(check, Fig. 6-13 is 0.8-1.4 uV/rtHz below 3 kHz for the 5 V part)*. The 100 ohm's own thermal noise is shunted by the capacitor and is in the netlist. Most of the rise from 70 uV is the 3 kohm resistors and the missing output capacitor. The Due floor widens by 5.0 % (model), 2.5 % (datasheet-scaled).

**5. Short and PW-3.** Hard-corner DC top end **2.133 V**, which ngspice at the worst corner (Rout 49.5 ohm) turns into 43.0 mA from the op-amp pair; with 15 mA IQ max **58.0 mA** (+2.0 mA). An instantaneous peak of the AC waveform reaches the AC top end: 2.197 V / 49.5 + 15 mA = **59.4 mA** (+0.6 mA). The -pin
at the lowest window bottom: 50.7 mA (the weak rail clips the stage at -1.73 V). Junction 46 C. The reset level (DAC0 at 3.3 V) draws 76 mA at the + pin for a fraction of a second: `records/dac0-reset-montreal5.json` has DAC0 jumping to 3.3 V and falling about linearly to 0 V over about
1.4 s, its envelope above the 2.8 V window top for about 0.2 to 0.3 s *(check)*; **accepted (D-V2-12)**. At 0 V (boot) 53 mA passes.

**6. AW-8 with the filter.** The reference follows the +rail or arrives 2 ms late; the filter (Rvr Cvr = 1.4 ms) charges after it; with DAC0 at 0 V, 3.3 V, floating and the reset trace the output stays within -2.043 .. +3.409 V (3.4172 V strong rail), 2 mV beyond the +rail, 0 beyond the -rail (48 cases per rail corner).

**7. AW-1 and the rest.** Guaranteed top **+1.6311 V -> +1.63 V** (hard corners; worst Monte Carlo draw A 1.637, B 1.762 V); lowest window top end 1.785 V. Width use of -1.5 .. +1.63 V: 83.0 % (A 82.9, B 82.4); position-aware **91.9 % (0.9194)** (A 91.6, B 85.2); commanded
-1.5 V inside the window with 4 % kept: -1.664 V; one DAC code 0.978 mV (<= 1.5); window bottom -2.06 V (information: it is past the negative rail's reach, as designed: only the commanded range is guaranteed). *PR-4:* the restated level is **+0.73 V on the positive side (+0.17 V at the window bottom) and -0.60 V against the +1.63 V top** (the level
that keeps the supply-pin current inside 60 mA less 15 mA); ngspice at the restated levels 34 mA and 35 mA; +-1.8 V reads 69 mA (information), +-5 V 134 mA. *AW-5* at the DAC's own top code (2.80 V): **94.3 uA, pass**; the 3.3 V reset reads 111 uA, accepted.
*PAM (-1.5 .. +1.63 V = 3.13 V):* PAM128 has 127 steps, **24.6 mV or 25.7 DAC codes** each (nominal 0.958 mV per code); PAM256 255 steps, **12.3 mV or 12.8 codes**; through the scope path about 14.1 and 7.1 ADC codes *(check)*. No pass criterion.

## The negative rail: what the 1 % corners cost, and the retune that was declined

The commanded range is untouched. What differs is the window's last codes (information, not a failure): the hard-corner window bottom is now -2.06 V (the wider window of the larger resistors) and the weak rail lets the stage reach -1.946 V into high impedance, so about 0.11 V of unused codes clip. The power stream's figure for the -1.68 V window bottom into 50 ohm (-1.69 V reach, about 10 mV to spare) is more pessimistic than this model (-1.810 V into 50 ohm); it used 22 mA and no macro offset, and the -1.5 V the design commands has 0.31 V to spare either way. The +rail corners touch only the output swing (0.99 V under the +rail at the window top into 50 ohm), the short currents (the window sets the output, not the rail), AW-8 (-2.021..3.406 V, within the rails) and the PR-4 levels (41 mA and 35 mA at the restated levels); none moved.

**The retune, a PROPOSAL that the spec lead declined (R3 stays 56k + 8.2k; AW-1 is not changed).** It would have restored those last codes: The AWG needs the weak negative rail at 1.9653 V or more (window bottom 1.933 V + 0.0323 V macro offset), i.e. a nominal -rail of at least 2.014 V at the power stream's -2.4 % weak corner. The 5.5 V sum is the other end: with the +rail as it is (strong 3.4172 V) the strong negative corner may reach -2.0828 V, a nominal -2.033 V. So the nominal -rail window is **-2.014 to -2.033 V** (it is -2.003 V now). Basic parts: R3 = 56k + 10k = 66k (R4 100k): V- = -1.22 (R3 + R4)/R4 = **-2.0252 V nominal, weak -1.9764 V, strong -2.0750 V**; the strong sum is 5.4922 V (7.6 mV under 5.5 V, down from 30 mV), the reach into high impedance -1.9440 V (window bottom +0.011 V), into 50 ohm -1.830 V. R3 = 56k + 9.1k = 65.1k gives weak -1.9657 V, 0.4 mV of margin: too thin. The +rail nominal (3.318 V) stays: its weak corner 3.2205 V is the REF3030E's VIN >= 3.2 V limit and its strong corner 3.4172 V sets the sum. This costs the power stream 22 mV of its 30 mV sum margin. The AWG's guarantee is the commanded range: the last 5 to 10 mV of unused window codes (below about -1.923 V) clip on the weak rail, and **the calibration sweep must drop any level whose sense reading stops following the DAC code**.

## What the layout must do (LR-4, LR-7)

1. **LR-4, the inverting node.** Rf, Rg2 and Cf at the two inverting pins, as short as the pads allow; the stage tolerates about 10 to 30 pF there (57 deg at 10 pF, 48 at 30, 41 at 60 on BEH60). The two halves' inverting pins join at one node.
2. **LR-7, the output loop.** R8, R9 next to the pins, the back-termination at the BNC end of the loop, vo at the feedback tap before the termination; there is no capacitor at the BNC now.
3. The +IN node (R6, R7 and the paralleled inputs) is short: its capacitance, with the 2.7 kohm, sets the 9 MHz corner.
4. The offset filter: C3, C4 at the Rg2 end, R5 to the REF3030E output pin on a short wide trace; keep the filter node away from the scope's centre resistors and ground returns.
5. Supply decouplers (100 nF) at the pins. The short current (44 mA) passes through R1/R2: copper for 50 mA at the BNC.

## What it asks of the rest of the board

- **REF3030E:** 0.98 mA worst for the AWG offset (2.72 mA with every other load, against 10 mA); its own 1 uF + 100 nF stay; its kHz output-impedance peak (up to about 115 ohm) is now bounded at the scope by the filter.
- **+3.3 V rail:** IQ up to 15 mA and the output's source current (22.3 mA into 50 ohm at the window top, 44 mA in a short). It no longer feeds the offset.
- **Negative rail (about -2.0 V):** IQ up to 15 mA, the sink up to 15.8 mA into 50 ohm at the commanded bottom, 36 mA in a short.
- **Short:** nothing limits it beyond the choice of top end; no limiter, no firmware clamp. VT-6 logs the package temperature.

## Open items

| Item | State |
|---|---|
| SC-9 against the flat 110 ohm bound | **2.99 LSB, over 2**: the graph's curve gives 1.66; no Basic combination meets both AW-3 and the flat bound (needs about 5 kohm and two capacitors) |
| fragile margins | position-aware 0.9194 (+0.0006), AC peak 59.4 mA (+0.6 mA), AC top end +30 mV, SC-9 +0.34 LSB |
| AW-6 | 213 uV against 300: the margin is 87 uV, down from 211 uV; the cause is the 3 kohm resistors and the removed output capacitor |
| *(check)* | the output saturation of 11.5 ohm per rail; the +-60 mA rating's duration; Fig. 6-14 is for 1.25 V and 5 V parts (a 3.0 V part is between), read by eye, load and capacitance unstated; the effective 14 uF of two 10 uF X5R at 3 V bias; REF3030E noise above 10 kHz; the 0.2-0.3 s above-window reset duration; the scope gain in the PAM ADC codes; DAC edge 5.85 V/us; macromodel PSRR |

## Rows that changed against the unfiltered design

AW-1/AW-2: new values, guaranteed top +1.63 V (was +1.71), width 83.0 % (86.2), position-aware 91.9 % (92.0), window bottom -2.06 V (information), one code 0.978 mV (0.964); a new **AC top end** row (2.197 V) and a new AC supply-pin peak row (59.4 mA);
AW-3 9.56 MHz / 8.99 MHz corner (8.88 / 8.39), slew 10.6 V/us; AN-1 47.8 deg BEH60 (50.5); AW-6 205-213 uV (70-89); AW-7 a gain-shelf information row (+1.64 %); AW-8 runs the filter charging; PA-2 2.72 mA (7.69), sink 0.08 mA; SC-7 30 uV (186); **SC-9 rows new** (graph, flat 110 ohm, loaded 28 ohm, no filter, filter alone, one capacitor);
AW-5 94.3 uA; PW-3 58.0 mA +pin (58.7), 50.7 mA -pin (54.3); PR-4 +0.73 / -0.60 V (-0.52).

## Guards (each broken on purpose: fails broken, passes restored)

| guard | broken |
|---|---|
| noise | feedback network 100 kohm |
| bandwidth | an output capacitor of 1 nF |
| bandwidth, +IN capacitor | Cpx 10 pF from +IN to ground |
| phase margin | Cf 0 on BEH60 |
| phase margin, node | 60 pF at the inverting node |
| window top end | Rbpl 33 kohm (AC top end over 2.2275 V) |
| tolerance | 5 % resistors |
| supply-pin current, Rout | a 45 ohm back-termination |
| supply-pin current, old top | version 1's values |
| supply-pin current, simulated | stage commanded to +3.0 V in ngspice |
| reference load | Rg2 200 ohm (over the 10 mA rating) |
| guaranteed range | commanding +1.71 V |
| **reference coupling (new)** | no offset filter (27.7 LSB) |
| **reference coupling, resistors (new)** | the filter-alone 390 ohm Rg2 with the filter (22.9 LSB) |
| bottom reach | a -1.5 V negative rail (clips at -1.4 V) |

## Reproducing

```
cd hardware/afe-proto/v2/sim/awg
TPH2502_DIR=<repo>/hardware/afe-proto/whatif/tph2502 python3 -I run.py     # about 15 s, writes raw/results.json, netlists, parts.csv
python3 -I table.py                                                      # report_table.md
python3 -I design.py                                                     # the Basic search (large and small Rf/Rg2) and the chosen values' corners
python3 -I run.py guards                                                 # the guards alone
```
