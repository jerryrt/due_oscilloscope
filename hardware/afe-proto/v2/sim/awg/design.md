# AFE version 2: the AWG output stage (design note)

DAC0 into one TPH2502 dual with both halves paralleled as one gain stage (V2-2: no spare half), a divider in front of the + inputs, an offset taken from the REF3030E through a
100 ohm + 10 uF x 2 filter, and a 50 ohm back-termination (no output capacitor). Every number comes from `run.py` (rows in `report_table.md`, made by `table.py`) and `design.py`
(the DC arithmetic, hard corners and the Basic-value search). Figures marked *(check)* are open. The vendor op-amp model is `simtools.vendor`'s derived copy of 3PEAK's TPH2501 (fetched, never committed) and the stability
models are `models-open/tph2502-beh/`.

**Status (owner rulings 2026-11-13): the guaranteed range is +-1.5 V with Rvr 150 ohm and R6 3.0 kohm (section "The final values"); the +-1.6 V text after it is history**; 99 rows, **0 FAIL**; see "The +-1.6 V range" below, which supersedes the -1.5 .. +1.63 V figures quoted in the older text (the sections after it are kept as the derivation and have not been re-worded). Before that ruling (REF3030E Fig. 6-14 peaking) the range was **-1.5 V to +1.63 V** (it was +1.71 V): the filter's shelf lets an AC waveform
reach above the DC window top end, so the supply-pin limit is judged on an **AC top end** of 2.197 V against 2.2275 V (+30 mV). The position-aware row is at 0.9194 (+0.0006) and the AC supply-pin
peak at 59.4 mA (+0.6 mA): both are fragile, re-run first after any change here. AW-1's guarantee is the commanded range; the last unused window codes (below about -1.95 V) clip on the weak
negative rail, and the calibration sweep must drop any level whose sense reading stops following the DAC code (spec lead). **One reading is not met:** against the flat 110 ohm bound
on the reference's output impedance (1-3 kHz) the coupling is 2.99 LSB; against the graph's own curve (peak 115 ohm near 1.9 kHz) it is 1.66 LSB. See "The reference at kHz".

**Rails:** the LM27762 with 1 % Basic feedback resistors (R1 120k, R2 68k, R3 56k + 8.2k, R4 100k) gives +3.2205 .. +3.4172 V and -1.9549 .. -2.0525 V (nominal +3.318 / -2.003 V;
`../powercal/design.md` section 1). `core.RAILS` and `design.RAIL_P/RAIL_N` carry them.

## The +-1.6 V range (owner ruling 2026-11-13) and the refused +-1.75 V request

**The ruling.** AW-1 becomes +-1.6 V into high impedance (+-0.8 V into 50 ohm), symmetric, guaranteed by hardware. It replaces -1.5 .. +1.63 V. `design.OUT_LO, OUT_HI = -1.6, +1.6`; `run.py` reads them (its AW-1 row texts no longer carry the old figures).

**The values do not change.** A search over Basic 1 % sets (`design.search`: Rbin 1.0-3.3 kohm, Rbpl 18-100 kohm with Rbin + Rbpl >= 28 kohm, Rf and Rg2 1-5.1 kohm, gain 1.6-2.3, Rvr 100 ohm) for the hard-corner AC top end <= 2.2275 V, position-aware use <= 92 %, width use <= 92 % and the commanded -1.6 V inside the window with 4 % kept gives 79 sets; **with Rf <= 3 kohm the best are Rf = Rg2 = 3 kohm with Rbin/Rbpl 2.7k/27k (or 3.0k/30k, 3.3k/33k, the same ratio)**, the existing design: hard-corner position-aware use **0.9038** (limit 0.92, +0.016), width 0.848, AC top end 2.1971 V, commandable top 1.631 V, commandable bottom -1.637 V. The larger Rf = Rg2 = 5.1 kohm sets reach 0.891 but fail AW-3 (the 10 pF Cf across a 5 kohm Rf: 6.6 MHz, B3 in the table above). The board is unchanged: R3 3 kohm, R4 3 kohm, R5 100 ohm, R6 2.7 kohm, R7 27 kohm, C1 10 pF, C3/C4 2 x 10 uF, R1/R2 2 x 100 ohm, R8/R9 1 ohm.

| Row | -1.5 .. +1.63 V | +-1.6 V | Limit | Margin now |
|---|---|---|---|---|
| AW-1 position-aware, hard corners | 91.9 % | **90.4 %** | <= 92 % | +1.6 % |
| AW-1 position-aware, MC A / B | 91.6 / 85.2 % | 90.1 / 89.7 % | <= 92 % | +1.9 / +2.3 % |
| AW-1 width use, hard corners | 83.0 % | 84.8 % | <= 92 % | +7.2 % |
| commanded bottom inside the window, 4 % kept, A / B | -1.664 / -1.644 V | -1.664 / -1.644 V (<= -1.6 V) | | +0.064 / +0.044 V |
| bottom reach into 50 ohm, weak rail (op-amp output), both halves paralleled | -1.835 V (+0.335 V) | -1.835 V (**+0.235 V**) | <= -1.6 V | +0.235 V |
| AW-2, AW-3 (8.99 MHz worst corner), AN-1 (47.8 deg BEH60), AW-5 (94.3 uA), AW-6 (213 uV), AW-8, PW-3 (58.0 / 59.4 / 50.7 mA), PA-2 (2.72 mA) | | unchanged | | as before |
| SC-9 through the reference | 1.66 LSB | 1.69 LSB (3.66 mV on the reference) | <= 2 LSB | +0.31 LSB |
| PR-4 restated levels | +0.73 / -0.60 V | +0.63 / -0.63 V; the forced-voltage rows 36 / 34 mA against 45 | | +9 / +11 mA |

`python3 -I run.py` gives 99 rows, 0 FAIL, 15 guards each failing broken and passing restored. The guaranteed-range guard now breaks by commanding +1.75 V (fails the hard-corner 92 % row) and the bottom-reach guard by a -1.5 V rail. The window top end, AC top end (2.197 V, +30 mV), the AC supply-pin peak (59.4 mA, +0.6 mA) and the 3 kohm values are untouched, so the watch-list rows other than SC-9 and the position-aware row did not move.

**PA-4 and SC-7.** The sense divider sees the whole DC window (-1.923 .. +2.18 V sweep, hardware unchanged), so k = 0.4, the tap range and the PA-4 tracking figure (0.050 % / 1.73 mV) are unchanged; `../powercal/sc7.py` now reads the guaranteed top as 1.6 V and its extrapolation rows move by 0.04 mV (cubic 1.2 LSB, tee fit alone: 1.29 mV; knots 1.2 LSB 2.37 mV against 3.5 mV) and the block sum stays 0.42 % linear (0.27 % RSS), 2.5 mV.

**The swing at the weak rail, with the datasheet.** `../../models/tph2502/tph2502.pdf` (3PEAK TPH2501/2/3/4, Rev. A, 18 pages; manifest entry, `models/SOURCES.md`). **Rev. A cites "Output Voltage Swing vs Output Current" on p. 9 (Output Drive Capability: continuous +-100 mA with approximately 2.7 V of swing on a 5 V supply) and does not contain the curve**: none of the typical-characteristic figures on pp. 5-8 is a swing curve, and the table on p. 4 gives only 2 mV typ / 30 mV max from the rail at 100 kohm. So the 11.5 ohm per rail (1.15 V at 100 mA) stays derived, linear in current *(check: the real curve, a later revision or a bench measurement)*. At +-0.8 V into 50 ohm the op-amp output current is 16 mA (+-1.6 V over the 100 ohm of back-termination plus load), the model's 16.8 mA sunk at -1.6 V (with the feedback). Two bounds on the bottom reach at the weak -1.9549 V rail (the macro stops 0.0323 V short): the two halves sharing the current, as the model does, -1.835 V (+0.235 V of margin); **one half carrying all of it** (R8/R9 are 1 ohm against 11.5 ohm, so sharing is close, but unmatched halves are not excluded), -1.9549 + 0.0323 + 11.5 ohm x 17 mA = **-1.727 V, +0.127 V of margin**. Into high impedance only the 0.3 mA through Rf flows and the reach is the -1.946 V of the model.

### The final values (2026-11-13, owner): +-1.5 V, Rvr 150 ohm, R6 3.0 kohm

**This supersedes the +-1.6 V / Rvr 100, the 130 ohm series pair and the +-1.55 V search below, which stay as history.** The AWG's guaranteed range is **+-1.5 V into high impedance (+-0.75 V into 50 ohm)**, `design.OUT_LO, OUT_HI = -1.5, +1.5`. Rvr (R5) is **one 150 ohm part, C22808, 0603 Basic**, to cut the AWG's current into the reference (SC-9 at the scope's +-5 V). With R6 at 2.7 kohm that fails: the AC top end is a property of the window, not of the range, so it stayed at 2.234 V (limit 2.2275 V) and the supply-pin peak at 60.1 mA at every range from 1.2 V to 1.6 V. **R6 (Rbin, the divider's upper arm) goes from 2.7 kohm C13167 to 3.0 kohm C4211**, the part Rf and Rg2 already use; R7 stays 27 kohm, so the divider ratio is 0.900 (was 0.909). The AC top end falls to 2.185 V and the supply pin to 59.1 mA. No other value changes. Hard-corner position-aware use at +-1.5 V is 0.870 and the largest symmetric range this set allows is about +-1.595 V (not used).

Every row, old (+-1.6 V, Rvr 100, R6 2.7k) -> new (+-1.5 V, Rvr 150, R6 3.0k); `run.py`: 99 rows, 0 FAIL, 15 guards each fail broken and pass restored:

| Row | Limit | Old | New |
|---|---|---|---|
| AW-1 position-aware use, hard corners | <= 92 % | 90.4 % (+1.6) | 86.9 % (+5.1) |
| AW-1 position-aware use, MC A / B | <= 92 % | 90.1 / 89.7 % | 86.6 / 85.7 % |
| AW-1 width use, hard corners | <= 92 % | 84.8 % | 81.0 % |
| commanded bottom inside the window (4 % kept), A / B | <= -1.5 V | +0.064 / +0.044 V | +0.139 / +0.121 V |
| AW-1 window top end, DC hard corners | <= 2.2275 V | 2.133 V | 2.092 V |
| AW-1 window top end, AC hard corners | <= 2.2275 V | 2.197 V (+30 mV) | **2.185 V (+43 mV)** |
| PW-3 AC peak, supply pin | <= 60 mA | 59.4 mA (+0.6) | **59.1 mA (+0.9)** |
| PW-3 DC short, + pin / - pin | <= 60 mA | 58.0 / 50.7 mA | 57.1 / 50.7 mA |
| AW-2 one DAC code | <= 1.5 mV | 0.978 mV | 0.961 mV |
| AW-3 -3 dB, hi-Z 15 pF | >= 8 MHz | 9.56 MHz | 9.22 MHz |
| AW-3 worst corner (Cf +-5 %, Rout +-1 %, Rbin +-1 %) | >= 8 MHz | 8.99 MHz (+0.99) | **8.70 MHz (+0.70)** |
| AW-3 into 50 ohm / into 100 pF (information) | >= 8 MHz | 9.5 / 8.72 MHz | 9.2 / 8.49 MHz |
| AW-3 slew | no limiting | 10.6 V/us | 10.5 V/us |
| AN-1 PM, BEH60 / BEH21 / vendor | >= 45 deg | 47.8 / 56.6 / 61.9 | 48.8 / 57.7 / 62.5 deg |
| AW-5 DAC pin load at its top code | <= 0.1 mA | 94.3 uA | 93.3 uA |
| AW-6 (with the reference's noise) | <= 300 uV | 213.0 uV | 213.2 uV |
| AW-7 gain shelf / filter corner | information | +1.64 % / 114 Hz | +2.44 % / 76 Hz |
| AW-8 extremes | within the rails | -2.043 .. +3.409 V | -2.042 .. +3.409 V |
| PA-2 source current | <= 10 mA | 2.72 mA | 2.70 mA |
| PR-4 restated level, + / - | | +0.17 / -0.09 V (36 / 34 mA) | +0.20 / -0.14 V (35 / 33 mA) |
| weak-rail reach into 50 ohm vs the commanded bottom | <= commanded | -1.835 V (+0.235 vs -1.6) | -1.835 V (+0.335 vs -1.5) |
| SC-9 through the reference, this study's constants | <= 2 LSB | 3.66 mV on the reference, 1.69 LSB | **2.29 mV at 1885 Hz, 1.06 LSB** |
| PW-1 (`../powercal/pw1_awg.py`) | <= 100 mA / 450 mA | 71.6 mA / 412.7 mA | 70.4 mA / 412.7 mA |

The three guards that had stopped discriminating were re-derived, none weakened. **window top end**: Rbpl 33 kohm still fails (2.275 V against 2.2275 V). **guaranteed range**: it now breaks at +1.6 V, the next 0.1 V level (position-aware use 0.922 against 0.92), and passes at +1.5 V. **reference coupling, resistors**: the old break (Rg2 390 ohm with Rf left at 3 kohm) reads 1.87 LSB and passes at Rvr 150, so it now breaks with the filter-alone resistor set of option A (Rf 470, Rg2 390 ohm; 7.4 LSB, fails); Rf = Rg2 = 3 kohm passes.

PA-4 and the sense divider are unchanged: k = 0.4, and the AWG window (hard corners -2.03 .. +2.09 V, `raw/reach.json`) sits inside the sense sweep (-1.923 .. +2.18 V), so the tap range and the 0.050 % / 1.73 mV tracking figure hold; the DAC code window is unchanged (the range is a guarantee, not a hardware limit).

**AW-1 note, beyond the guaranteed range: ...** The guarantee is +-1.5 V into high impedance (+-0.75 V into 50 ohm). Driving raw DAC codes past it is **typical, not guaranteed**: nominal parts, AREF 3.27 V, ngspice with the derived 11.5 ohm per rail output saturation *(check: the datasheet's swing-versus-current curve is not in Rev. A)*, `reach.py` and `raw/reach.json`. *Top:* the DAC's own top code (2.771 V at AREF 3.27 V) gives **+2.01 V into high impedance (+1.91 V at AREF 3.20 V, +2.06 V at 3.30 V)** and +1.01 V at the BNC into 50 ohm, with no compression (within 0.1 mV of the linear map); at the hard corners the window top end is **+1.75 V on the lowest board to +2.09 V DC (+2.19 V as a pulse-train peak)**, so a board's actual top is known only from its calibration. *Bottom:* compression is where the stage output departs more than 5 mV from the linear map. At nominal rails it does not occur inside the DAC's span (the lowest code, 0.578 V, gives **-1.84 V** into high impedance and -0.92 V at the BNC into 50 ohm). At the weak -1.9549 V rail it starts below DAC 0.59 V into high impedance (stage **-1.82 V**) and below 0.60 V into 50 ohm (stage -1.80 V, **-0.90 V at the BNC**), and the lowest code is 9 mV (high impedance) to 12 mV (50 ohm) off the line; the hard-corner window bottom is -1.77 to -2.03 V, of which the last codes clip. All of it assumes the derived saturation; none of it is a requirement.

(History below: the options considered before the final values.)

### Rvr 130 ohm (2026-11-13): SC-9 through the reference at the scope's +-5 V

With the scope at +-5 V its own REF-coupling figure is 2.44 LSB against 2 (scope stream). The AWG's lever is the offset filter's resistor Rvr (R5): a larger Rvr moves less of the AWG's signal current into the reference. Only a resistor value changes (same capacitors); the DC drop across it is a fixed offset the AWG calibration removes. The price is top-end headroom: the filter shelf `Rf Rvr / (Rg2 (Rg2 + Rvr))` grows with Rvr and the supply-pin rule judges the AC top end. Everything below is at +-1.6 V, Rf = Rg2 = 3 kohm, Rbin/Rbpl 2.7k/27k, hard corners (`design.corner_stats`), with the reference coupling from `run.ref_move`. That function uses the AWG study's own scope constants (0.806 and 1.743 mV per LSB), so its LSB figures are not the +-5 V scope's; the "x vs 100" column is the scale to apply to the scope's own 2.44 LSB.

| Rvr | Basic part | AC top end (<= 2.2275 V) | supply pin (<= 60 mA) | position-aware use, hard corners (<= 92 %) | REF swing at 1.9 kHz | x vs 100 | scope 2.44 LSB becomes |
|---|---|---|---|---|---|---|---|
| 100 (was) | C22775 | 2.197 V (+0.030) | 59.4 mA (+0.6) | 90.4 % | 3.66 mV | 1.000 | 2.44 |
| 120 | C22787 | 2.212 V (+0.015) | 59.7 mA (+0.3) | 90.8 % | 3.05 mV | 0.834 | 2.04 *(still over 2 by 0.04)* |
| **130** | none: 120 + 10 ohm in series (C22787 + C22859) | **2.219 V (+0.008)** | **59.8 mA (+0.2)** | **91.2 % (+0.8)** | **2.82 mV** | **0.770** | **1.88** |
| 140 | none | 2.227 V (+0.0007) | 60.0 mA (0.0) | 91.6 % | 2.62 mV | 0.715 | 1.74 *(no top-end margin)* |
| 150 | C22808 | **2.234 V (-0.007) FAILS** | **60.1 mA (-0.1) FAILS** | 91.9 % | 2.44 mV | 0.667 | 1.63 |

**150 ohm fails**: the AC top end by 7 mV and the supply-pin peak by 0.1 mA (the sim's AW-1 AC row and PW-3 row fail, and the window-top guard stops discriminating). The only 150 ohm set that keeps the top end is Rbin/Rbpl 3.3k/30k, with hard-corner position-aware use 0.91997 against 0.92 (+0.00003, no margin). **120 ohm** is a single Basic part and passes every AWG row, but leaves the scope at about 2.04 LSB. **130 ohm is chosen.** It is not a single Basic part (`../../jlc-basic.csv` has 100, 120, 150 and 200 ohm in 0603), so R5 becomes **R5 120 ohm C22787 plus R5b 10 ohm C22859 in series**: one extra 0603 placement and a second pad pair in the R5 position *(the board edit belongs to the layout stream)*.

At 130 ohm, old (Rvr 100) -> new: AW-1 position-aware use, MC A / B 90.1 / 89.7 % -> 89.8 / 90.8 %; hard corners 90.4 % -> 91.2 % (+0.8 %); width 84.8 % -> 85.2 %; commanded bottom inside the window, A / B +0.064 / +0.044 V -> +0.042 / +0.023 V; AC top end 2.197 -> 2.219 V (+30 -> +8 mV); PW-3 AC peak 59.4 -> 59.8 mA (+0.6 -> +0.2 mA); AW-2 0.978 -> 0.973 mV; PR-4 +0.17 -> +0.19 V (37 mA, +8 mA); PA-2 2.72 -> 2.71 mA; filter corner 114 -> 87 Hz at 14 uF; AW-7 gain shelf +1.64 -> +2.12 %. AW-3 (8.99 MHz), AN-1 (47.8 deg), AW-5 (94.3 uA), AW-6 (213.0 uV; the reference's noise is counted unfiltered, so the larger Rvr earns no credit), AW-8 and the swing at the weak rail (-1.835 V into 50 ohm, +0.23 V) are unchanged to the printed digits. SC-9 in this study (its constants): 3.66 -> 2.82 mV on the reference, 1.69 -> 1.30 LSB. 99 rows, 0 FAIL, 15 guards.

### The +-1.75 V request, refused (D-V2 record)

+-1.75 V was asked for first and fails by arithmetic that no choice of values escapes. The same hard-corner machinery with `OUT_LO, OUT_HI = -1.75, +1.75`:

- 9145 Basic 1 % sets (gain 1.85-2.4): **none** has position-aware use <= 92 % with the AC top end <= 2.2275 V; the best has 0.9695 (Rf 5100, Rg2 4700, Rbin 2200, Rbpl 27k, AC top 2.225 V).
- 6000 random continuous resistor values, not restricted to Basic: the best guaranteed top is **+1.66 V**.
- The cause is the AREF spread: with the DAC window scaling with AREF over 3.20-3.30 V, the guaranteed top is **+1.807 V only at a fixed AREF 3.27 V** (resistors 0.5 %: +1.661 V; 0.1 %: +1.669 V; VOS zero +1.634 V; fixed offset reference +1.646 V; no filter shelf +1.683 V; DAC-window scenario A only +1.682 V, B only +1.764 V; baseline 1 % +1.632 V). The resistor tolerance is not the cause.
- Requiring position-aware use <= 92 % at +-1.75 V (1908 Basic sets) needs an AC top end of at least **2.331 V, which is 62.1 mA through the supply pin (15 mA IQ max + 2.331 V / 49.5 ohm) against the 60 mA rating**, and those sets have Rf 4.99-5.1 kohm, for which **AW-3 reads 6.6 MHz (< 8)**.
- The bottom reach at -1.75 V into 50 ohm is **85 mV** with both halves sharing (-1.835 V), not the 0.2 V first estimated, and **-36 mV with one half carrying all of it** (-1.714 V): the reach is not a certain pass at -1.75 V either.

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
| R5 (Rvr) | 100 ohm 1 % 0603, **now 150 ohm C22808** (section The final values) | C22775 | offset filter resistor, REF3030E output to the filter node |
| C3, C4 | 10 uF X5R 0805 25 V, in parallel | C15850 | offset filter capacitor (about 14 uF effective at 3 V bias *(check)*) |
| R6 (Rbin) | 2.7 kohm 1 % 0603, **now 3.0 kohm C4211** | C13167 | DAC0 series resistor and the divider's upper arm |
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
| fragile margins | AC peak 59.4 mA (+0.6 mA), AC top end +30 mV, SC-9 +0.31 LSB; position-aware 0.904 at +-1.6 V (+0.016) |

**Watch list.** These four rows have the least margin: position-aware use (+0.0006), the AC supply-pin peak (+0.6 mA), the AC top end (+30 mV) and SC-9 through the reference (+0.34 LSB, against the datasheet curve; D-V2-15). Any part or value change here re-runs those rows first (`python3 -I run.py`).
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
| guaranteed range | commanding +1.75 V (the refused request) |
| **reference coupling (new)** | no offset filter (27.7 LSB) |
| **reference coupling, resistors (new)** | the filter-alone 390 ohm Rg2 with the filter (22.9 LSB) |
| bottom reach | a -1.5 V negative rail (clips at about -1.4 V) |

## Reproducing

```
docker/pcb/run.sh -m 3G -t 600 python3 -I hardware/afe-proto/v2/sim/awg/run.py --out DIR --work DIR/w   # about 15 s: DIR/raw/results.json, awg.cir, parts.csv, report_table.md
docker/pcb/run.sh python3 -I hardware/afe-proto/v2/sim/awg/run.py guards                  # the guards alone
python3 -I hardware/afe-proto/v2/sim/awg/design.py                                        # the Basic search (large and small Rf/Rg2) and the chosen values' corners
```

`--out` defaults to this folder (the committed copies), `--work` to a temporary directory. Constants are in `params.py`, the
netlist builders and runner in `netlist.py`, the DC arithmetic in `design.py`; every deck runs through
`simtools.netlib_common.run_ng` (memory cap, a `.save` of the vectors the deck reads). The op-amp macro is `simtools.vendor`'s
derived copy of 3PEAK's TPH2501 (`tools/fetch_models.py`), the behavioural TPH2502 is `models-open/tph2502-beh/`.
