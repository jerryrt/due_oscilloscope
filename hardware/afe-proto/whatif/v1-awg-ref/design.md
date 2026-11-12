# Version 1's AWG output stage, redone the way version 2's is (design note)

What this is: version 1's AWG with the DAC0 buffer, the AWG Vmid follower, the series Schottkys and the supply filters removed. DAC0 goes through a divider straight to
the + input of **one half** of a TPH2502 (the other half is tied off locally), the offset comes from the REF3030E output through a **100 ohm + 2 x 10 uF filter** and Rg2 (no Rg1), and
the output is the AW-4 back-termination (2 x 100 ohm 1206). Same topology as kvm_02's version 2 (origin/main 2ff6aed, `v2/sim/awg`, read-only), values re-solved for version 1's window.
`core.py`, `design.py`, `run.py`, `table.py` here are edited copies of kvm_02's earlier files. Every number is a row of `report_table.md` (115 rows by `run.py`: **112 pass, 3 fail**, the three
in "Open decisions") or of `design.py` / `search2.py`. Figures marked *(check)* are open. Rails are version 1's (`whatif/v1-basic/values.md`): +3.2095..+3.3926 V and -2.099..-2.005 V.

## Circuit

```
 DAC0 pin --- Rbin R6 51k ---+--------------------------- (+) U3 half A (pin 3) ---+
                |            |                                                    |
              Cbin C4        R7 51k + R8 75k in series (Rbpl = 126k) to GND         U3 pin 1 OUT = vo ---+--- R1 || R2 (2 x 100R 1206 = 50R) --- BNC
              10 pF (across R6)                                                     |                     |
                                                                                   Rf R3 3.3k            (no output pole)
                                            Cf C1 10 pF across R3                   |
 REF3030E out --- R5 100R --- node X ---- Rg2 R4 4.99k ------------------------ inverting node (pin 2) ---+
                              |
                        C5 || C6 = 2 x 10 uF to GND   (node X)

 U3 spare half B, tied off locally: pin 5 (+IN B) to GND, pin 6 (-IN B) to pin 7 (OUT B).   Supply: V- pin 4 to the -rail, V+ pin 8 to +3.3 V, 100 nF at each pin (C2, C3).
```

**Spare half (V2-2):** V2-2 allows a package's spare half "only where the circuit has no use for it, and the design says where". Here the circuit has no use for it: one half carries the whole stage (output
current 28 mA at a short, inside one half's rating: ISC source 290 typ / sink 160 typ, 100 min, `v2/parts.md`), and a follower of ground on the other half costs no part and no net across the package. The two-halves
version needed the two outputs joined across the package's pad rows, which one layer cannot route. Its noise does not reach the output (it has its own output and no connection to the stage).
**The filter's 2 x 10 uF and the 100 ohm are the zero-part alternative's replacement:** a buffer of VREF on the spare half would have needed OUT B (pin 7) to cross to Rg2 in the other pad row; the RC does not.

Transfer (`design.py`): DC `Vout = Gs0 kin Vdac - K Vref`, `Gs0 = 1 + Rf/(Rg2 + Rvr) = 1.6475`, `kin = Rbpl/(Rbin + Rbpl) = 0.7119`, `K = Rf/(Rg2 + Rvr) = 0.6475`
(Rvr = 100 ohm in Rg2's branch, absorbed as Rg2_eff = 5.09 kohm). DC gain G = **1.1730** (ngspice 1.1733 at 1 Hz), zero at Vdac = 1.67 V (centre output +20 mV at the 1.6745 V window centre).
**Above the filter corner** (1/(2 pi 100 ohm 14 uF) = 114 Hz) the capacitor shorts the 100 ohm and the gain is `1 + Rf/Rg2` = 1.1825: a **shelf of +0.81 %** (ngspice 1.1733 at 1 Hz, 1.1827 at 10 kHz).
Version 2's 3k/3k pair has +1.64 %. Hand check of the divider: with kin = 1, K <= Gs - 1 = 0.17, so the divider is not optional (version 2's argument, unchanged).

| Ref | Part | LCSC | Role |
|---|---|---|---|
| R1, R2 | 100 ohm 1 % 1206, in parallel | C17901 | AW-4, 50 ohm; 20 mW each at the 28 mA short (rated 250 mW) |
| R3 (Rf) | 3.3 kohm 1 % 0603 | C22978 | feedback |
| R4 (Rg2) | 4.99 kohm 1 % 0603 | C23046 | inverting node to node X; no Rg1 |
| R5 (Rvr) | 100 ohm 1 % 0603 | C22775 | offset filter resistor, REF output to node X |
| C5, C6 | 10 uF X5R 10 % 0805 25 V, in parallel | C15850 | offset filter capacitor, about 7 uF each at 3 V DC bias *(check: the brief's figure)* |
| R6 (Rbin) | 51 kohm 1 % 0603 | C23196 | DAC0 series resistor, divider upper arm |
| R7 + R8 (Rbpl) | 51 kohm C23196 + 75 kohm C23242 in series = 126 kohm | | divider lower arm (a pair of Basic parts stays within 1 %); an undriven DAC0 commands ground |
| C1 (Cf) | 10 pF C0G 5 % 0603 | C1634 | across Rf: phase margin (AN-1) |
| C4 (Cbin) | 10 pF C0G 5 % 0603 | C1634 | across Rbin: divider compensation (AW-3) |
| C2, C3 | 100 nF X7R 0603 | C14663 | one per supply pin |
| U3 | TPH2502-SR | C118223 | half A the stage, half B tied off |

Every R and C is Basic (`v2/jlc-basic.csv`). **15 placements, 10 part types** (`parts.csv`).

## Against version 1's AWG block (`kicad/design.py`, block 'awg')

Version 1 has 40 lines: 36 fitted + the BNC J3 + 3 unfitted BAV99 clamp footprints (not carried). This design: **15 placements, net -21; part types 13 -> 10.**
Removed (25): the Vmid follower (R23, R24, R86, R87, C8, U5, D4, C20: 8), the DAC0 buffer's Ra/Rb/Cb (R32, R34, R39, R40, R57, R84, C62: 7), the collapsed Rf chain (R41, R42, R58, R85: 4), the supply filters and Schottkys
(R59, R60, R61, R62, D1, D2: 6). Added: R5 + C5 + C6 (the offset filter, 3), R94 (the Rbpl pair's second part, 1) -> 36 - 25 + 4 = 15; the 1 ohm balancers R7/R8 of the two-halves version are gone.
Re-valued and kept: R54 (Rbin 680 -> 51k), R22 (Rbpl 330k -> 75k part), C63 (-> Cbin 10p, now across Rbin), R35 (Rf), R33 (Rg2), C7 (Cf), C21, C22 (100 nF, now direct on the rails), R51, R88, U3.
**New part types against the block (and against version 1's board list): 3.3k, 4.99k, 51k, 100R 0603** (10 uF C15850 is a new type unless version 1's '10u' is that part *(check)*); 75k, 100n, 10p, 1206 100R are on the board.

## What changed in this round, and what the rows say

**1. One half instead of two (and why nothing fails because of it).** Rows that moved, one half against the two-halves version at the same stage values:

| Row | two halves (earlier run) | one half | |
|---|---|---|---|
| AN-1 min PM, BEH60 (loop at the inverting pin; loads hi-Z / 50 ohm / 5 ns cable / 330 pF / 1 nF; 2/6/10 pF at the node) | 62.4 deg | **52.7 deg** (BEH21 61.4, vendor 61.2) | >= 45: pass, +7.7 deg. The op-amp's open-loop output resistance is no longer halved by a second half in parallel (BEH21 21 ohm, BEH60 60 ohm). Without Cf: **-2.1 deg**, so Cf is essential |
| AW-3 bandwidth, hi-Z + 15 pF | 77.6 MHz | 96.2 MHz; worst component corner 12.5 MHz (>= 8, +4.5) | one half has half the input capacitance |
| AW-4 overshoot into a 1 m open line | 3.26 % | 3.85 % | <= 5 %: +1.15 % |
| AW-6 noise | 168 uV | **216 uV** (214 macro, 151 datasheet-scaled; with the filtered REF noise 216.0) | < 300: +84 uV. One half has no averaging of its 9.3 nV/rtHz; the spare half's noise does not reach the output |
| short, window-top current through the half | pair 27.8 mA | 27.7 mA at the stage output | the supply-pin total is the same: 42.7 mA at the + pin (IQ 15 + 27.7), +17.3 mA to 60; -pin 43.8 mA |
| swing at +-1.3 V into 50 ohm | | the 4 reach rows (+1.0 V, window top 1.379 V, -1.0 V, bottom -1.398 V, both rails, Rout 49.5..50.5) show 0.00 mV difference between the saturated and unsaturated model | into 50 ohm: 13.7 mA at the top end |

Datasheet quotes for the one half (`v2/parts.md`, from the 3PEAK TPH2501/2/3/4 Rev. A text): "ISC sink 100 min / 160 typ, source 100 min / 290 typ mA; abs +-160 mA"; "Output Short-Circuit Duration ... Infinite"; "Current at Supply Pins +-60 mA" (abs max); the
text (p. 7, "Output Stage") says "a continuous output current of +-100 mA and still approximately 2.7 V of output swing on a 5 V supply" (1.15 V lost per rail at 100 mA, an 11.5 ohm per rail linear model *(check: the datasheet has no swing-vs-current curve)*).
At 28 mA that is 0.32 V of the 3.2 V rail against a 1.4 V output: the swing does not bind. **No row that passed with two halves fails with one.** AN-1 is the one that gave margin, +17 deg to +7.7 deg. Recommendation: one half; if the layout later puts more than about 30 pF at
the inverting node (LR-4), watch AN-1 first (100 pF at the node read 58.7 deg with the earlier values; re-run).

**2. The Basic-value search (`search2.py`, 371,513 candidates after the nominal filter, singles and series pairs of Basic 0603 for Rbin and Rbpl; Rf 2-6.8k, Rg2 3-10k; Rvr 100 ohm).**
The three asks together (AW-7 offset margin >= 5 mV, gain margin >= 0.02, AW-1 position-aware <= 92 %) **have no solution**: the stack of 1 % tolerances makes the offset at Vdac = 1.67 V a window 80 mV wide; AW-1's position-aware 92 % needs
the window's centre pushed about +25 mV; gain margin 0.02 caps the gain, and a smaller gain takes AW-1 away. Best at each gain ceiling (position-aware <= 92 %), from `search2.py`:

| gain ceiling (DC / AC) | best offset (hard corner) | offset margin | example |
|---|---|---|---|
| 1.18 | +61.5 mV | **-1.5 mV** | Rf 3.3k, Rg2 5.1k, Rbin 10k, Rbpl 24k |
| 1.185 | 49.3 mV | +10.7 mV, AW-1 92.00 % (no margin) | Rf 2.2k, Rg2 3.3k |
| 1.19 | 47.7 mV | +12.3 mV, AW-1 92.00 % | Rf 2.4k, Rg2 3.6k, Rbin 33k + 560, Rbpl 82k |
| **1.19 / AC 1.199 (chosen)** | **+54.4 mV** | **+5.6 mV**, AW-1 91.19 % (+0.81 %) | **Rf 3.3k, Rg2 4.99k, Rbin 51k, Rbpl 51k + 75k** |
| 1.183 / 1.198 (all singles) | +52.9 mV | +7.1 mV, AW-1 91.78 % (+0.22 %) | Rf 2k, Rg2 3k, Rbin 82k, Rbpl 200k (C25811); but its REF current is 0.98 mA and the SC-9 filter needs 2 caps and still reads 1.86 codes |

**Chosen: Rf 3.3k / Rg2 4.99k / Rbin 51k / Rbpl 51k + 75k.** Offset margin **+5.6 mV** (was +0.15), AW-1 position-aware **91.2 % (+0.8 %**, was +1.3 %), DC gain 1.158..1.189 (margin **+0.011**, not the 0.02 asked), AC gain 1.199 (+0.001).
The gain margin of 0.02 is what the three-way conflict gives up; the DC gain is what the host calibrates and the AC figure is the shelf-added one. The 2k/3k single-resistor set has gain margin +0.017 but only 0.22 % on AW-1.
The REF load stays low: 3.3k/4.99k is the 3.3k/5.1k scale. Rf and Rg2 stay on the AW-3-and-PM side: the larger the pair, the larger the pole of Cf across Rf and the stage still reads 12.5 MHz at the worst corner.

**3. The offset filter is fitted (spec lead's decision), and what it does.**

| | |
|---|---|
| Parts | R5 100 ohm (C22775) from the REF output to node X, C5 + C6 = 2 x 10 uF (C15850) from X to GND, Rg2 from X; **3 placements, +3 over the unfiltered stage** |
| DC | the AWG offset current 0.60 mA at its worst drops **60 mV** in R5: in the transfer as Rg2 + 100 ohm (the closed form and every corner use it, ngspice agrees to 0.12 mV) |
| Shelf | **+0.81 %** (above 114 Hz, 1.1733 -> 1.1827); AC gain 1.158..1.199 against the DC 1.158..1.189 |
| AC top end (AW-1, short) | the AC waveform with its mean at the window bottom and peaks at the top code reaches bottom + shelf x span: **1.399 V** at the hard corners against the supply-pin limit 2.2275 V (+0.83 V); the AC peak in a short is **28.3 mA** (PW-3's 30 mA: +1.7 mA), supply pin 43.3 mA (+16.7). kvm_02's 3k/3k pair at **their** window has AC top end 2.197 V (+30 mV) and was forced to Rf = Rg2 = 3k by this limit; at version 1's window the 1.4 V top leaves the limit non-binding |
| SC-9 (see 4) | |
| Start-up | tau = 100 ohm x 14 uF = 1.4 ms; node X charges after the reference. AW-8 rows below: the filter changes none of the numbers beyond the failing power-up rows (extreme +3.377 V, the rail) |
| REF load regulation | unchanged: the AWG current is 0.33 mA across the window, **15 uV (5 ppm)** against SC-7's 3.0 mV; the REF sees the capacitor behind 100 ohm, 1.1 uF + 100 nF at its own pin, inside its 0.1-22 uF range |
| AW-6 | the REF's noise through the filter: 12.1 uV (1.4 uV/rtHz at its worst, flat, x K and the 114 Hz corner) against 33.1 uV unfiltered; the 100 ohm adds 1.3 nV/rtHz and is in the netlist. Total 216.0 uV (300) |
| AW-3 / AN-1 | node X is an AC ground above 114 Hz; the inverting node sees Rf || (Rg2 + ~0) = 2 kohm at high frequency. Both read as above |

**4. The reference at kHz (SC-9), against kvm_02's figures.** REF30E Fig 6-14 as kvm_02 read it (open-load curve, peak 115 ohm at 1.9 kHz; the 5 V and 1.25 V parts, load and capacitance unstated *(check)*), the full commanded +-1 V swing (1.20 V pp at the inverting node,
scope centre factor 0.543 (version 1's scope: R3 330k, Rp = R1 || R2 || R3 = 179 kohm; the follower has gain 1), 1 LSB at the ADC pin 0.806 mV:

| Case | on the REF | at the scope follower | ADC codes (limit 2) |
|---|---|---|---|
| **chosen: 100 ohm + 2 x 10 uF (14 uF), graph** | 1.66 mV at 1.9 kHz | 0.90 mV | **1.12 (pass, +0.88)** |
| the same, spec lead's flat 110 ohm bound (1-3 kHz) | 2.99 mV | 1.62 mV | 2.01 (information, over by 0.01) |
| the same, flat 28 ohm (1 kohm-load peak) | 0.76 mV | 0.41 mV | 0.51 |
| **one 10 uF (7 uF) instead of two, graph** | 3.30 mV | 1.79 mV | **2.22 (fails)** |
| no filter, graph | 27.7 mV | 15.1 mV | 18.7 |
| Rg2 3k (kvm_02's value) with this swing, 2 x 10 uF, graph | 2.75 mV | 1.50 mV | 1.86 |
| kvm_02, version 2 (their run.py: 3k/3k, 2.7 mA-class current, 3.13 V swing, scope factor 0.806 per volt at the input) | 3.58 mV at 1.9 kHz | 2.89 mV at the scope input | 1.66 (graph) / 2.99 (110 ohm) / 0.76 (28 ohm) |

**One 10 uF does not suffice** here (2.22 codes, graph); two do (1.12), with 0.88 codes of margin on the graph and 0.01 over on the flat 110 ohm bound, the same reading kvm_02 has on theirs (2.99 against 1.66 on the graph). The coupling is smaller than theirs
(1.12 against 1.66 codes) because the current in Rg2 is smaller: 0.60 mA at its worst against their 0.98 mA (one reading of the 0.6 mA: 5.09 kohm; theirs: 3.1 kohm). **The DC coupling (0.045 ohm) is 0.01 code.** The flat 110 ohm bound is
the spec lead's, and it would need Rg2 about 5 kohm and two capacitors on their side, which kvm_02 could not reach for lack of bandwidth: here the pair is 3.3k/4.99k and AW-3 holds (12.5 MHz at the worst corner) because Cbin keeps the + input fast.

**5. The REF's loads.**

| Load | Source current | Note |
|---|---|---|
| AWG offset (Rg2 + 100 ohm) | **0.60 mA** worst (DAC 0 V, Rg2 -1 %, REF +0.2 %); ngspice 0.59 / 0.51 / 0.20 / 0.13 mA at DAC 0 / 0.55 / 2.80 / 3.3 V | never sinks (the + node reaches 0.712 x 3.3 = 2.35 V < 3.0 V) |
| ladder (2.12 mA), scope centres, sense tie, ADS inputs *(check)* | 2.17 mA | `whatif/v1-basic/values.md`, derived |
| **Total** | **2.77 mA of 10 mA** (+7.2); kvm_02's v2 reads 2.72 mA with its 0.98 mA AWG share against 1.736 mA of other loads | the unfiltered 330/510-class pair here was 8.1 mA; kvm_02's note has the load falling from 7.7 to 2.7 mA; here the unfiltered 510-class pair read 8.1 mA |

Load regulation, **ref30.pdf 6.5 (REF30E): "Load regulation Source, 0mA < ILOAD < 10mA, VIN = VOUT + 500mV: 3 typ, 15 max ppm/mA"** (the test VIN - VOUT is 0.5 V; this board has 0.20-0.39 V *(check)*): 0.33 mA over the DAC window is **15 uV (5 ppm)**
against SC-7's 3.0 mV fit share; the static shift at 0.60 mA is 27 uV (calibrated out). Ladder taps and the ADS1115 anchor are ratiometric to Vref and do not move; the Due's ADC sees 5 ppm. SC-9 at DC: 0.01 code. Headroom: 203 mV at the lowest +rail corner (3.2095 V - 3.006 V);
Fig 6-11 (5 V part) reads about 60 mV at 5 mA and 25 C, 130 mV at 59 C, 295 mV at 125 C, so 15-35 C (EN-1) is inside it and a hot enclosure would not be *(check)*.

**6. DAC0 straight into the divider.** AW-5 at the DAC's real top code (2.80 V): **15.8 uA** (51k + 126k), 16.0 uA at -1 %, 18.6 uA at the 3.3 V reset level (outside the codes); kvm_02's 2.7k/27k reads 94.3 uA and 111 uA. PR-2, unpowered AFE, DAC0 at 3.3 V (and 0, 1.67, 2.80), rails in every order
(both, +3.3 V first, -rail first, both up, neither): **0.056 mA** drawn from the pin against VT-5's 3.8 mA bound (version 1's 680 ohm: 4.1 mA, 73x); diodes at the + input with Vf about 0.5 V are an assumption *(check)*. The -0.2 V rule: the AFE pushes back at most **1.7 uA** into the pin and the +
input never goes below ground for DAC0 >= 0 (at DAC0 = -0.2 V it reads -0.142 V). The SAM3X DAC's own drive and output impedance are not in the repo *(check)*; this load is 16 uA and about 14 pF. The divider's 177 kohm node carries the TPH2502's input bias current *(check: not read)*: 1 nA would be 0.1 mV x 1.17 at the output.
Cbin 10 pF (ratio 126/51 = 2.47, flat for 4.0 pF at the + input node): -3 dB 96 MHz nominal, 12.5 MHz at the worst component corner, a 12 pF stray fails the 8 MHz (guard); 1.16 dB peaking / 3.9 % overshoot at the nominal stray.

**7. Short and PW-3 (the supply-pin rule).** Hard-corner window top **1.379 V** (limit 2.2275 V, +0.85 V); AC top 1.399 V. Through the 50 ohm short:

| Case | Current | Rating | Margin |
|---|---|---|---|
| window top / bottom end into the short (49.5 ohm), hard corners | 27.9 / 28.2 mA | PW-3 30 mA (v1: 27.14 mA) | +1.8 mA |
| AC top end into the short | 28.3 mA | 30 mA | +1.7 mA |
| +pin at the window top: IQ max 15 + 27.7 mA | **42.7 mA**; at the AC top 43.3 mA | 60 mA (abs max, no duration stated *(check)*) | **+17.3 mA** (+16.7) |
| -pin at the window bottom, weak -rail | 43.8 mA | 60 mA | +16.2 mA |
| DAC0 at 3.3 V (reset level, 0.2-0.3 s above the window per `records/dac0-reset-montreal5.json` *(check)*) | 54 mA | 60 mA | +6 mA |
| DAC0 at 0 V (boot) | 50 mA | 60 mA | +10 mA |

Junction 46 C at 25 C ambient (SOP-8 158 C/W). No clamp: hardware alone.

**8. AW-1, AW-2, AW-7.** Width use 81.0 % (hard) / 80.9 / 80.4 (MC A, B) against 92; **position-aware 91.2 % (+0.8 %)** hard corners (MC 90.5 / 84.2 %); commanded +-1.0 V inside the window with 4 % free (bottom -1.127 V A, -1.116 V B; commandable top +1.019 V A, +1.099 V B at the worst draw);
bottom end -1.398 V against the rail reach -1.917 V (v2's 88 mV above the rail applied to -2.005 V *(check)*). AW-2: 0.643 mV against 1 mV. AW-7: DC gain 1.158..1.189 (+0.011 at the top; the shelf's AC 1.199, +0.001), **offset at Vdac = 1.67 V -26..+54 mV (+5.6 mV margin, hard corners; MC -21..+51, +9 mV)**.

**9. AW-3, AW-4, AN-1.** In "1" above and the table. Bandwidth into 50 ohm 63.8 MHz, into 100 pF 27.7 MHz; peaking 1.16 dB; slew 7.4 V/us against 5.85 V/us x gain, no slew limit; AW-4 overshoot 3.85 % (<= 5 %); an ideal 5 ns step 9.3 % (information). PM without Cf is -2.1 deg: Cf is not optional (kvm_02 found -7.9 deg).

## Open decisions: the 3 fails

| Row | Result | Needed |
|---|---|---|
| AW-8, AFE rails ramping (3 orders, 20 us / 2 ms) with DAC0 already at 3.3 V (reset trace), the REF following the +rail | -1.943 .. +3.377 V | +-2.1 V: **fail** by 1.28 V (the output sits at the +rail; ngspice output = 3.88 V - K x Vx with node X still charging) |
| the same with the REF 2 ms late | -1.943 .. +3.377 V | **fail** |
| (the same rows read against the rails present, the version 2 reading of AW-8) | 1 mV beyond the +rail | **pass** |
| AW-8, Due reset with the AFE powered, DAC0 anywhere 0 .. 3.3 V, hard corners | -1.989 .. +1.963 V | +-2.1 V: pass (+0.111 V) |
| PR-4 forced +-1.8 V, 10 s, powered | 57 mA | <= 45 mA (60 mA pin - 15 mA IQ): **fail** by 12 mA; the levels that hold are **+0.83 V / -0.85 V** (37 mA each) |

The filter does not change AW-8 or PR-4: the first is the AFE's own rail ramp against DAC0 at 3.3 V, the second the supply-pin rating. Both are decisions for the spec lead (kvm_02's v2 reads AW-8 as within the rails and restates PR-4).

## Netlist (for `kicad/design.py`, block 'awg'; pin 1 net / pin 2 net)

Existing nets: `DAC0`, `GND` (`G`), `+3V3A` (`P33A`), `VNEG` (`VN`), `VREF`, `AWG_BNC`, `AWG_OUT`, `AWG_INV`, `AWG_BIN`. New nets: `AWG_BPL` (middle of the Rbpl pair), `AWG_X` (the filter node), `AWG_SP` (the tied-off half's pin 6 / pin 7).

| Ref | Value | LCSC | pin 1 net | pin 2 net | note |
|---|---|---|---|---|---|
| R54 | 51k | C23196 | DAC0 | AWG_BIN | Rbin (was 680) |
| R94 (new) | 51k | C23196 | AWG_BIN | AWG_BPL | Rbpl part 1 |
| R22 | 75k | C23242 | AWG_BPL | GND | Rbpl part 2 (was 330k to GND) |
| C63 | 10p | C1634 | DAC0 | AWG_BIN | Cbin across R54 (was AWG_BIN to GND) |
| R35 | 3.3k | C22978 | AWG_OUT | AWG_INV | Rf (was 1k chain) |
| C7 | 10p | C1634 | AWG_OUT | AWG_INV | Cf (was 12p) |
| R33 | 4.99k | C23046 | AWG_INV | AWG_X | Rg2 (was to AWG_VMID) |
| R93 (new) | 100R | C22775 | VREF | AWG_X | offset filter resistor |
| C64 (new) | 10u (C15850, 0805 X5R 25 V) | C15850 | AWG_X | GND | offset filter capacitor |
| C65 (new) | 10u (C15850) | C15850 | AWG_X | GND | in parallel with C64 |
| C21 | 100n | C14663 | +3V3A | GND | V+ pin 8, direct on the rail (was AWG_VCC) |
| C22 | 100n | C14663 | VNEG | GND | V- pin 4, direct on the rail (was AWG_VEE) |
| R51 | 100R 1206 | C17901 | AWG_OUT | AWG_BNC | AW-4 (unchanged) |
| R88 | 100R 1206 | C17901 | AWG_OUT | AWG_BNC | AW-4 (unchanged) |
| U3 | TPH2502 | C118223 | | | pins: 1 AWG_OUT, 2 AWG_INV, 3 AWG_BIN, 4 VNEG, 5 GND, 6 AWG_SP, 7 AWG_SP, 8 +3V3A |

Removed refs: R23, R24, R86, R87, C8, U5, D4, C20 (Vmid follower); R32, C62, R34, R39, R40, R57, R84 (buffer network); R41, R42, R58, R85 (Rf chain); R59, R60, R61, R62, D1, D2 (supply filters); D9, D10, D11 (the unfitted clamps).
Refs R93, R94, C64, C65 are free in the working-tree `design.py` (highest R88/R92, C63) *(check against origin/main)*. Rails: `AWG_VP`, `AWG_VPX`, `AWG_VNX`, `AWG_VCC`, `AWG_VEE`, `AWG_VMID`, `AWG_VMT*`, `AWG_MV`, `AWG_RB*`, `AWG_RF*` and `AWG_BO` disappear.

## Layout (LR-4, LR-7)

1. Rf, Rg2 and Cf at pin 2, short; the stage tolerates tens of pF there (re-run AN-1 for the actual figure).
2. Cbin across Rbin next to the + input; the + input node short (flat for 4 pF; fails near 10 pF of stray).
3. The back-termination at the BNC end of the loop, vo (pin 1) at the feedback tap before it.
4. The offset filter: R93 and C64, C65 at the Rg2 end, R93 to the REF output pin on a short wide trace; node X away from the scope centre resistors (signal current under 0.4 mA).
5. Spare half on pins 5-7: pin 6 to pin 7 by one short trace, pin 5 to the plane; no net crosses the package.

## Open items

| Item | State |
|---|---|
| gain margin 0.02 not reached (0.011 DC, 0.001 AC) | the three asks conflict; the table in "2" is the Pareto |
| AW-1 position-aware +0.8 %, AW-7 offset +5.6 mV, AC gain +0.001 | all at the stacked corner; any value change re-runs `search2.py` first |
| SC-9: 1.12 codes on the graph, 2.01 on the flat 110 ohm bound | the graph is by eye (kvm_02's table), another output voltage, load capacitance unstated *(check)* |
| AW-8 power-up, PR-4 +-1.8 V | spec decisions (above) |
| *(check)* | + input capacitance (Cbin flat at 4 pF); clamp Vf; input bias current at 177 kohm; SAM3X DAC drive; output saturation 11.5 ohm/rail; 60 mA pin rating has no duration; ADS1115 input current; dropout graph is the 5 V part; C15850 about 7 uF at 3 V *(the brief's figure)*; whether 3.3k / 4.99k / 51k / 100R 0603 / 10u C15850 are already on the board; free refs |

## Guards (each broken on purpose: fails broken, passes restored; 15 of them)

| guard | broken |
|---|---|
| noise | feedback network 100x |
| bandwidth, divider compensation | Cbin removed |
| bandwidth, + input stray | 12 pF stray at the + input |
| phase margin | Cf removed (BEH60) |
| phase margin, node | 400 pF at the inverting node |
| AW-1 position-aware | Rbpl 100k (109 %) |
| tolerance | 5 % resistors |
| AW-7 gain | version 2's values on version 1's window (gain 1.6) |
| AW-7 offset | the earlier 3.3k / 5.1k / 33k / 82k set (+81.8 mV with the 100 ohm in Rg2) |
| SC-9 offset filter | no filter (the 2 LSB) |
| short-circuit current | 45 ohm back-termination |
| reference load | Rg2 300 ohm |
| AW-1 range | +-1.2 V |
| short-circuit current, simulated | stage commanded to +2.0 V |
| unpowered DAC0 current | Rbin 1 kohm |

## Reproducing

```
cd hardware/afe-proto/whatif/v1-awg-ref
TPH2502_DIR=<repo>/hardware/afe-proto/whatif/tph2502 python3 -I run.py    # about 6 min: raw/results.json, netlists/, parts.csv, awg.cir
python3 -I table.py                                                     # report_table.md
python3 -I search2.py                                                   # the value search (about 4 min; writes search2.pkl, 19 MB, delete after use)
TPH2502_DIR=... python3 -I run.py guards                                # the guards alone
```
`core.py` locates the vendor macro at `../tph2502/models` (local only, sha256 checked) and the stability models at `$TPH2502_DIR/beh`.
