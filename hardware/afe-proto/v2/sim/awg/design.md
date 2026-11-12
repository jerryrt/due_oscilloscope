# AFE version 2: the AWG output stage (design note)

DAC0 into one TPH2502 dual with both halves paralleled as one gain stage (V2-2: no spare half), a divider in front of the + inputs, an offset taken
straight from the REF3030E, a 50 ohm back-termination and a 330 pF output pole. Every number comes from `run.py` (rows in `report_table.md`, made by
`table.py`) and `design.py` (the DC arithmetic, hard corners and the Basic-value search). Figures marked *(check)* are open. The vendor op-amp model is
read from `../../whatif/tph2502/models` and the stability models from `$TPH2502_DIR/beh/` (both local, never copied here).

**Status after D-V2-12 and the 1 % LM27762 corners:** 89 rows, **0 FAIL**. AW-1's guarantee is the commanded range, -1.5 V to +1.71 V; the last 5 to 10 mV of unused window codes (below about -1.923 V) clip on the weak negative rail, and the calibration sweep must drop any level whose sense reading stops following the DAC code (spec lead's decision on the 1 % rail corners; the retune below was declined). The window top end stays at or below 2.2275 V in every corner as a hardware guarantee (no firmware clamp).
AW-1's top is the worst-corner top the design guarantees, **+1.71 V** (hard corners 1.7104 V with 4 % of the window kept free; the lowest window top end with no
band kept is 1.862 V). The position-aware row passes by 0.0002 (92.0 % against 92 %) and is the thinnest margin in the design: **fragile**. The 1 % rail corners did not move it (the offset is the reference, so the rails never enter that row): re-run first, still 0.9198. Any part or value change in this stage re-runs that row first (`python3 -I run.py`, the AW-1 position-aware rows), and the spec lead has accepted +1.71 V as AW-1's figure without widening the 4 % band or the 92 % use.

**Rails:** the LM27762 with 1 % Basic feedback resistors (R1 120k, R2 68k, R3 56k + 8.2k, R4 100k) gives +3.2205 .. +3.4172 V and -1.9549 .. -2.0525 V (nominal +3.318 / -2.003 V; `../powercal/design.md` section 1). `core.RAILS` and `design.RAIL_P/RAIL_N` carry them; they replace version 1's +3.235 .. +3.342 / -2.106 .. -2.041 V.

## Circuit

```
                       R5 2.4k                      +IN A --.
 DAC0 pin ----------/\/\/\/--------+------------------------+- (+) TPH2502 half A ---- R7 1R --.
                                   |                        |                                  |
                                   R6 27k                   +- (+) TPH2502 half B ---- R8 1R --+-- vo --+-- Rf R3 470 --+-- fb
                                   |                                                           |        |              |
                                  GND        (-) of A and B both tied to fb                    |        |   C1 Cf 10p across R3
                                                                                              |        |
   REF3030E output (3.000 V) -------------------- Rg2 R4 510 --------------------------------- fb   (no Rg1, no filter)

 vo --- Ro (R1 || R2, 2 x 100R 1206 = 50R) ---+--- BNC (core)
                                              |
                                           C2 330p to GND (the output pole)

 supply pins of U1: +3.3 V and -2.07 V rails, each with 100 nF at the pin
```

Transfer (design.py): `Vout = Gs0 * kin * Vdac - K * Vref`, `Gs0 = 1 + Rf/Rg2 = 1.922`, `kin = Rbpl/(Rbin + Rbpl) = 0.918`, `K = Rf/Rg2 = 0.922`, `Vref` the REF3030E
(3.000 V +-0.2 %). Gain from the DAC pin 1.765 (ngspice 1.7645).

| Part | Value | LCSC | Role |
|---|---|---|---|
| R1, R2 | 100 ohm 1 % 1206, in parallel | C17901 | AW-4 50 ohm back-termination; 110 mW each at the 44 mA short top, rated 250 mW |
| R3 (Rf) | 470 ohm 1 % 0603 | C23179 | feedback |
| R4 (Rg2) | 510 ohm 1 % 0603 | C23193 | inverting node to the REF3030E output; **there is no Rg1 and no filter** |
| R5 (Rbin) | 2.4 kohm 1 % 0603 | C22940 | DAC0 series resistor and the divider's upper arm |
| R6 (Rbpl) | 27 kohm 1 % 0603 | C22967 | divider lower arm; an undriven DAC0 commands ground |
| R7, R8 | 1 ohm 1 % 0603 | C22936 | output balancing of the two halves |
| C1 (Cf) | 10 pF C0G 5 % 0603 | C1634 | across Rf: the stability capacitor (AN-1), the smallest Basic C0G |
| C2 | 330 pF C0G 5 % 0603 | C1664 | output pole |
| C3, C4 | 100 nF X7R 0603 | C14663 | supply pins, one per pin |
| U1 | TPH2502-SR | C118223 | both halves paralleled |

Ten placements' worth of lines against version 1's thirteen: the 2.2 ohm, the two 10 uF of the rail filter and the 1 uF pair are gone. Every resistor and capacitor is Basic
(`../../jlc-basic.csv`, read-only here). `parts.csv` is generated with the rows.

## Decisions

**1. The divider, and no Rg1.** With `kin = 1` the offset path subtracts at most `K <= Gs - 1`, so the window-top output is at least `Vo + Gs (Vwin_top - Vo)` (2.5 V with a 3.0 V
reference, 2.3 V from the 3.3 V rail), above the 2.2275 V the supply pin allows, at every corner. Taking 8.2 % off the DAC signal before the gain lets `K` exceed `Gs - 1`. The cost is the
2.4 kohm in front of the inputs (bandwidth) and AW-5 (below).

**2. The values (re-solved for the reference).** `design.py` searched Basic values (Rbin 0.68-3.3 kohm, Rbpl 10-100 kohm with Rbin + Rbpl >= 28 kohm, Rf 220-560, Rg2 220-1200 ohm, no Rg1) for the sets whose
hard-corner window top end is <= 2.2275 V, whose commanded -1.5 V sits inside the window with 4 % kept free and whose window bottom is inside the negative-rail reach: 21 sets. The best guaranteed top is Rf 470
/ Rg2 510 / Rbin 3.3 kohm / Rbpl 39 kohm (1.729 V) but its bandwidth corner is 8.03 MHz; **470 / 510 / 2.4 kohm / 27 kohm** (1.710 V, 8.39 MHz) was chosen. The earlier set
(390 / 470 / 1.5 kohm / 30 kohm) now puts the top end at 2.409 V: with 3.0 V in place of 3.3 V the divider has to take more, so Rbin grew from 1.5 to 2.4 kohm and the ratio Rf/Rg2 rose. Rbpl 30 kohm (next
Basic value up) lifts the top end to 2.242 V and fails; 5 % resistors give 2.26 V and fail.

**3. The offset filter: none is needed (cost of one if it is).** The 2.2 ohm + 20 uF existed to keep a noisy rail out of the offset. The REF3030E is quiet (51 uV rms, 10 Hz-10 kHz, E grade;
its noise above 10 kHz is a graph and *(check)*) and sits 0.05 ohm from the offset node. With K = 0.92 the reference's 10 Hz-10 kHz noise reaches the output as 47 uV, and the AW-6 sum rises from 75 to 88.6 uV
against 300 (row "plus the REF3030E noise"); the reference would need to be 100 nV/rtHz flat to 10 MHz to use the rest of the margin. The AWG's signal current in Rg2 (4.14 mA across the DAC window) does reach the reference
(next section): 0.21 mV peak to peak at 0.05 ohm, 0.17 mV at the scope input, about 0.1 LSB of the scope ADC against SC-9's 2 LSB. **If a filter were wanted** it would be a resistor in series with Rg2's source
(the 2.2 ohm of version 1: 13 mV of drop at 5.95 mA, a gain term that the closed form absorbs) and a cap to ground at the Rg2 end: one 10 uF X5R 0805 (C15850, about 7 uF at 3 V bias) puts the corner near 10 kHz,
the two of version 1 near 3.6 kHz. That is two or three placements and it hides the AWG's high-frequency current from the reference; it is not fitted because the coupling row passes without it.

**4. The REF3030E's three loads together** (`sim/powercal` supplies the others; PA-2, SC-7):

| Load | Source current | Note |
|---|---|---|
| AWG offset (Rg2) | **5.95 mA** worst: DAC at 0 V (boot or floating), Rg2 -1 %, reference +0.2 %. ngspice nominal 5.16 / 4.89 / 0.84 / -0.06 mA at DAC 0 / 0.55 / 2.80 / 3.3 V | the inverting node follows the + input, so Rg2 carries (3.0 - kin Vdac)/510. Never sinks more than 0.08 mA (DAC at 3.3 V: the node is above 3.0 V) |
| Ladder, both scope centres, sense default tie, ADS inputs | 1.736 mA (powercal `REF/src`: ladder 1.53 mA, scope 2 x 5.4 uA at -12 V) | the powercal figure already includes a 0.165 mA AWG sense tie; counted once there and not removed (conservative) |
| **Total** | **7.69 mA against the 10 mA rating (+2.31 mA)** | sink case: 0.16 mA against 10 mA |

Load regulation (15 ppm/mA source, 150 ppm/mA sink, `ref30.pdf` 6.5, E grade): the reference moves 186 uV between the DAC window's ends (4.14 mA x 15 ppm/mA x 3.0 V), against SC-7's 0.1 % fit share of 3 V
(3.0 mV, powercal): +2.8 mV margin. The static shift at 5.95 mA is 268 uV and calibrates out. Neither the rating nor SC-7 is exceeded, so no flag. A larger Rg2/Rf pair would cut the current but costs phase margin (the 680/820 pair read 22 deg
before Cf), so the current is not reduced further.

**5. Stability (AN-1).** The datasheet-fitted models BEH21 and BEH60, every load of the row, both rails, 2/6/10 pF at the inverting node:

| Stability component (Rf/Rg2 = 470/510, Rbin 2.4 kohm) | min PM | -3 dB hi-Z | verdict |
|---|---|---|---|
| none | 34.5 deg | 9.65 MHz | fails 45 |
| Cpx, +IN to ground, 10 pF (the scope channel's fix; the smallest Basic C0G, nothing smaller exists) | 48.4 deg | **4.66 MHz** | passes PM, **fails AW-3's 8 MHz**: the pole is the divider's 2.2 kohm Thevenin resistance with the doubled input capacitance of the paralleled halves |
| **Cf 10 pF across Rf** (chosen) | 50.5 deg (BEH60), 56.5 (BEH21); 49.8 deg at Cf -5 % | 8.88 MHz | passes both |

Bandwidth with Cout +-5 %, Cf +-5 %, Rout +-1 % at the worst corner: **8.39 MHz** against 8 (+0.39); into 100 pF 7.27 (information). The 12 / 15 / 20 pF cases of the inverting node were read on the earlier set; with Cf the margin
is of that order (10 pF to 11 pF), so the inverting-node trace is a layout rule (LR-4). The stage is 1.92 noise gain. Noise (AW-6, limit 300 uV, D22): 69.7 uV macro noise, 52.6 uV datasheet-scaled, 69.7 uV with rail terms (the supply
rails now reach the output only through the PSRR), 75.1 uV in the pessimistic op-amp-like row, 88.6 uV with the reference's noise added. The 1 uF per-pin pair stays dropped (100 nF alone passes by 211 uV or more).

**6. Short and PW-3.** The short current is the stage output at the DAC window maximum divided by the back-termination. Hard-corner top end **2.202 V** (limit 2.2275, +25 mV); in ngspice at the worst corner (Rout 49.5 ohm) the op-amp pair
sources 43.7 mA (the rest of the 44.5 mA comes from the reference through Rg2). Plus 15 mA IQ max: **58.7 mA against 60** (+1.3 mA; the +rail corner does not move it, the window sets the output). The -pin at the lowest window bottom: the weak rail clips the stage at -1.707 V in the short, so 54.3 mA (an unclipped -1.933 V would be 55.9). Junction 45 C at 25 C ambient (SOP-8 158 C/W).
The 11.5 ohm per rail output saturation behind these rows is *(check)*. **The reset level is accepted as a transient (D-V2-12):** with DAC0 at 3.3 V a short draws 76 mA (15 + 61, strong rail +3.4172 V) at the +pin. The repository records
(`records/dac0-reset-montreal5.json`, the first run dropped) that DAC0 jumps to 3.3 V, then falls about linearly to 0 V over about 1.4 s; its trace envelope stays above the 2.8 V window top for about 0.2 to 0.3 s *(check: read from 0.1 s envelope steps)*. So it
is a fraction of a second, not milliseconds; the 60 mA rating states no duration *(check)*. At 0 V (boot) a short draws 56 mA at the -pin and passes.

**7. AW-1, the guaranteed range, and how it is judged.**

| Row | Value | Needed |
|---|---|---|
| window top end, hard corners / Monte Carlo A, B | 2.202 / 2.158 / 2.196 V | <= 2.2275 V (+25 mV / +69 / +31 mV); 5 % resistors fail it |
| **lowest window top end** (the highest output every board reaches at its top DAC code, no band kept) | **1.862 V** hard corners (Monte Carlo A 1.868, B 1.992 V) | |
| **guaranteed commandable top, 4 % of the window kept free** | **1.7104 V** hard corners -> **+1.71 V** (worst Monte Carlo draw A 1.716, B 1.839 V) | AW-1's top end |
| width use of -1.5 .. +1.71 V | 86.2 % hard corners (A 86.2, B 85.7 %) | <= 92 %: **pass** |
| position-aware use of the same range | 92.0 % (0.9198) hard corners (A 91.7, B 90.7 %) | <= 92 %: **pass, +0.0002** |
| commanded -1.5 V inside the window, 4 % kept | -1.518 V hard corners | <= -1.5 V: pass |
| **commanded -1.5 V into 50 ohm at the weak rail (the pass/fail row)** | the stage output clips at -1.810 V (derived 11.5 ohm per rail *(check)*) | <= -1.5 V: **pass, +0.31 V** |
| window bottom end against the rail reach (-1.9226 V into high impedance at the weak rail) | -1.933 V (-0.010 V; Monte Carlo A -1.928 V, -0.005 V) | **information only**: codes below about -1.923 V clip; they are outside the commanded range |
| one DAC code | 0.964 mV | <= 1.5 mV |
| nominal board | -1.59 .. +1.97 V commandable | each board's actual top is measured at calibration |

At the earlier +2.05 V commanded top this design's hard-corner width is 95.4 % and position-aware 109.9 %; judged against **+1.86 V** (the lowest window top end, no band) it is 99.9 % position-aware and 90.3 % width. So the
92 % band holds only up to +1.71 V, and that is the range the rows judge. The window bottom end, -1.933 V in the worst corner, sits 0.010 V below what the weak negative rail lets the stage reach into high impedance (-1.9226 V), so the last codes of the window clip. Nothing commanded is there.

**8. The remaining decisions of the spec lead.** *PR-4:* the restated level is **+0.73 V on the positive side (the lowest commanded -1.5 V: 45 mA x 49.5 ohm - 1.5 V) and -0.18 V against the earlier +2.05 V top; against the guaranteed
+1.71 V top it is -0.52 V** (+0.29 V with the window bottom -1.93 V and 0 V with the window top end 2.202 V): the level that keeps the supply-pin current inside 60 mA less the 15 mA quiescent. ngspice at the restated levels: 41 mA (+0.29 V) and 35 mA (-0.03 V). Forced +-1.8 V reads 71 mA and +-5 V 134 mA;
the documentation states them. *AW-5:* judged at the DAC's own codes; its highest code (2.80 V, AREF 3.30 V) draws **95.2 uA** (2.4 + 27 kohm) and **passes**; the 3.3 V reset level reads 112 uA, outside the DAC's codes, accepted.
*PAM (at the guaranteed range -1.5 .. +1.71 V = 3.21 V):* PAM128 has 127 steps, **25.3 mV or 26.7 DAC codes** each (nominal 0.945 mV per code; 26.2 at the worst-corner 0.964 mV); PAM256 has 255 steps, **12.6 mV or 13.3 codes**. As the Due's ADC sees them through the scope path (gain 0.4622, 3.3 V / 4096, *(check)*) about 14.5 and 7.2 ADC codes. No pass criterion is applied.

## What the layout must do (LR-4, LR-7)

1. **LR-4, the inverting node.** Rf, Rg2 and Cf at the two inverting pins, as short as the pads allow: the stray at the node plus Cf's pad should stay near the 10 pF the PM rows assume (50.5 deg at 10 pF). The two halves' inverting pins join at one node.
2. **LR-7, the output loop.** R7, R8 next to the pins, the back-termination at the BNC end of the loop, vo at the feedback tap before the termination; the 330 pF at the BNC.
3. The +IN node (R5, R6 and the paralleled inputs) is short: its capacitance sets the 8.4-9.4 MHz corner with the output pole.
4. Rg2 runs to the REF3030E's output pin on a short, wide trace: it carries up to 5.95 mA and its signal-dependent part (4.1 mA) must not share a return with the scope centre's resistors.
5. The supply pin decouplers (100 nF) at the pins. The short current (44 mA) and sink (41 mA) pass through R1/R2: copper for 50 mA at the BNC.

## What it asks of the rest of the board

- **REF3030E:** up to 5.95 mA for Rg2, 7.69 mA in total with every other load (10 mA rating), moving 186 uV with the AWG level; it must be fitted with its own 1 uF + 100 nF (the AWG adds none).
- **+3.3 V rail:** IQ up to 15 mA, and the output's source current (21.6 mA into 50 ohm at the window top, 44 mA in a short). It no longer feeds the offset.
- **Negative rail (about -2.0 V):** IQ up to 15 mA, the sink up to 19.8 mA into 50 ohm at the commanded bottom, 39 mA in a short. At the weak corner (-1.9549 V) the stage reaches -1.923 V into high impedance and -1.810 V into 50 ohm; see the next section.
- **Short:** nothing limits it beyond the choice of top end; no limiter, no firmware clamp. VT-6 logs the package temperature.

## The negative rail: what the 1 % corners cost, and the retune that was declined

The commanded range is untouched. What differs is the window's last codes (information, not a failure): the hard-corner window bottom is -1.933 V and the weak rail lets the stage reach -1.9226 V, **0.010 V short** (Monte Carlo A 0.005 V). The power stream's figure for the -1.68 V window bottom into 50 ohm (-1.69 V reach, about 10 mV to spare) is more pessimistic than this model (-1.810 V into 50 ohm); it used 22 mA and no macro offset, and the -1.5 V the design commands has 0.31 V to spare either way. The +rail corners touch only the output swing (0.99 V under the +rail at the window top into 50 ohm), the short currents (the window sets the output, not the rail), AW-8 (-2.021..3.406 V, within the rails) and the PR-4 levels (41 mA and 35 mA at the restated levels); none moved.

**The retune, a PROPOSAL that the spec lead declined (R3 stays 56k + 8.2k; AW-1 is not changed).** It would have restored those last codes: The AWG needs the weak negative rail at 1.9653 V or more (window bottom 1.933 V + 0.0323 V macro offset), i.e. a nominal -rail of at least 2.014 V at the power stream's -2.4 % weak corner. The 5.5 V sum is the other end: with the +rail as it is (strong 3.4172 V) the strong negative corner may reach -2.0828 V, a nominal -2.033 V. So the nominal -rail window is **-2.014 to -2.033 V** (it is -2.003 V now). Basic parts: R3 = 56k + 10k = 66k (R4 100k): V- = -1.22 (R3 + R4)/R4 = **-2.0252 V nominal, weak -1.9764 V, strong -2.0750 V**; the strong sum is 5.4922 V (7.6 mV under 5.5 V, down from 30 mV), the reach into high impedance -1.9440 V (window bottom +0.011 V), into 50 ohm -1.830 V. R3 = 56k + 9.1k = 65.1k gives weak -1.9657 V, 0.4 mV of margin: too thin. The +rail nominal (3.318 V) stays: its weak corner 3.2205 V is the REF3030E's VIN >= 3.2 V limit and its strong corner 3.4172 V sets the sum. This costs the power stream 22 mV of its 30 mV sum margin. The AWG's guarantee is the commanded range: the last 5 to 10 mV of unused window codes (below about -1.923 V) clip on the weak rail, and **the calibration sweep must drop any level whose sense reading stops following the DAC code**.

## Open items

| Item | State |
|---|---|
| window bottom against the negative-rail reach | information: 0.010 V (hard corners), 0.005 V (Monte Carlo A) of unused codes clip on the weak rail; the retune was declined |
| position-aware use, hard corners | passes by 0.0002 (92.0 % against 92 %): any change that raises the window top spread fails it; `design.corner_stats` reproduces it |
| *(check)* | the output saturation of 11.5 ohm per rail (no swing-versus-current curve); the +-60 mA supply-pin rating has no stated duration, IQ max 15 mA is the dual's datasheet maximum; REF3030E noise above 10 kHz and its output impedance above DC (graphs, not text); the 0.2-0.3 s above-window duration of the reset; DAC edge 5.85 V/us (docs/hardware.md); the scope gain and ADC scale in the PAM code counts; macromodel PSRR |
| reference timing | the reference turns on in 2 ms to 0.1 % at 1 uF (datasheet); AW-8 passes with it following the +rail or arriving 2 ms late (-2.021..3.406 V against the 3.4172 V strong rail; 2 mV beyond the +rail, 0 mV beyond the -rail) |

## Rows that changed against the first re-solve (the rail-offset design)

AW-1 rows now judge the guaranteed range -1.5 .. +1.71 V (width 86.2 %, position-aware 92.0 %, against 96.7 % and 113 % for the earlier +2.05 V target on the rail-offset design); the top-end rows use the reference (hard corners 2.202 V, were 2.215 V); PA-2 and SC-7 reference rows are new;
SC-9 coupling through the reference is new; AW-2 0.964 mV (0.949); AW-3 8.88 MHz / 8.39 MHz corner (9.32 / 8.78), slew 10.3 V/us; AN-1 50.5 deg BEH60 (47.3); AW-5 passes at the DAC's own top code (95.2 uA); AW-6 69.7-88.6 uV (62-65) with a reference-noise row added; AW-8 now
runs the reference following or 2 ms late (48 cases per rail corner); PW-3 58.7 mA +pin, 55.9 mA -pin, the reset row accepted with its duration; PR-4 restated and the +-1.8 V row is information. `proposals.py` (the lower-bottom study) was removed with the rail-offset design it analysed.

## Guards (each broken on purpose: fails broken, passes restored)

| guard | broken |
|---|---|
| noise | feedback network 100x (617 uV) |
| bandwidth | Cout 1 nF |
| bandwidth, +IN capacitor | Cpx 10 pF from +IN to ground (4.7 MHz) |
| phase margin | Cf 0 on BEH60 |
| phase margin, node | 30 pF at the inverting node |
| window top end | Rbpl 30 kohm (2.242 V) |
| tolerance | 5 % resistors (2.26 V) |
| supply-pin current, Rout | a 45 ohm back-termination (64 mA) |
| supply-pin current, old top | version 1's values (about 78 mA) |
| supply-pin current, simulated | stage commanded to +3.0 V in ngspice |
| **reference load (new)** | Rg2 300 ohm: 11.9 mA against the 10 mA rating |
| **bottom reach (new)** | a negative rail of -1.6 V, which clips at -1.455 V into 50 ohm and misses the commanded -1.5 V; the 1 % weak rail -1.9549 V passes |
| **guaranteed range (new)** | commanding +1.86 V: position-aware 99.9 % |

## Reproducing

```
cd hardware/afe-proto/v2/sim/awg
TPH2502_DIR=<repo>/hardware/afe-proto/whatif/tph2502 python3 -I run.py     # about 30 s, writes raw/results.json, netlists, parts.csv
python3 -I table.py                                                      # report_table.md
python3 -I design.py                                                     # the Basic search and the chosen values' corners
python3 -I run.py guards                                                 # the guards alone
```
