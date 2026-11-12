# Version 1 with Basic passives only (D15, V2-3)

Every resistor below is a JLC **Basic** 0603 UNI-ROYAL thick film, 1 %, +-100 ppm/K
(20 ohm and up), read from `hardware/afe-proto/v2/jlc-basic.csv` (both JLC pages
`base`, 2026-11-12). The one 1206 is C17901. No Extended part is used. Capacitors
are unchanged (already Basic). Stock is not checked *(check before ordering)*.

All figures come from copies of the existing simulations, edited in place in this
folder (every edit is marked `v1-basic`); nothing outside `whatif/v1-basic/` was
written. Op-amp models are unchanged (OPA354 scope, OPA365 AWG). Each tool first
reproduced the current design's published numbers (control), then ran the new
values: scope windows 114.6 / 118.9 mV, SC-4 71.4-73.1 %, DF-3 32.1 / 41.2 dB,
SC-8 2.44 / 0.79 % all reproduce exactly.

## 1. Value table

| old part (0.1 %, Extended) | n | new part(s) | LCSC | Basic | serves |
|---|---|---|---|---|---|
| 100k (scope R1/R3 100k part, sense divider R7/R8, R9, FB+ bottom) | 9 | 100k 0603 | C25803 | yes | SC-3, SC-2/SC-4 divider; sense k = 1/2 (PA-4); LM27762 FB+ |
| 330k (scope R1/R3/R2, Vmid dividers, Rbpl, FB- R4) | 19 | 330k 0603 | C23137 | yes | SC-2, SC-3, Vmid, PR-2 |
| 174k (LM27762 FB+ top) | 1 | **75k + 100k = 175k** | C23242 + C25803 | yes | +3.3 V_A = 3.300 V nominal (was 3.288) |
| 100k || 330k (LM27762 FB- R3) | 2 | **75k, one part** | C23242 | yes | -2.052 V nominal (was -2.071); R4 stays 3 x 330k |
| 953 (scope RF) | 2 | **1k || 100k = 990.1 ohm** (1k alone also works, section 3) | C21190 + C25803 | yes | SC-11 gain and margin |
| 249 (scope RG) | 2 | **270** | C22966 | yes | SC-11 |
| 953 (AWG Ra, Rg) | 2 | **1k** | C21190 | yes | AW-1/AW-7 gain |
| 953 + 249||249 + 22 (AWG Rb, Rf) | 2 | **1k + 270||270 + 22 + 22** (1179 ohm) | C21190, C22966, C23345 | yes | AW-1/AW-7: Rb/Ra, Rf/Rg 1.179 |
| AWG Vmid divider top 330k | 1 | **330k + 4.7k + 4.7k = 339.4k** (4.7k C23162 already in BOM) | C23137, C23162 | yes | AW-1 window (centres Vmid against the new rails) |
| 249 (3.3 V sense filter, shared) | 1 | **270** | C22966 | yes | AN-4 / SC-2 centring |
| 249 x 8 (calibration ladder) | 8 | **270 x 8**, 3 in parallel at the bottom + 5 in series | C22966 | yes | PA-9, section 5 |
| 49.9 1206 (AWG back-termination) | 1 | **2 x 100 ohm 1206 in parallel = 50.0** | C17901 | yes | AW-4, section 6 |

Part types: leaves 953, 249, 174k, 49.9 (and the 0.1 % 100k, 330k) -- six Extended
types; adds 1k, 270, 75k, 100R-1206 -- four Basic types. Placements change by a
few (+2 scope RF, +2 AWG Rb/Rf, +2 AWG Vmid, +1 FB+, -1 FB-, +1
termination).

## 2. Scope: windows at 1 % (sim/scope `hz`, worst case = one-at-a-time extremes, plus 80-draw Monte Carlo)

+3.3 V_A corners 3.2095-3.3926 V (LM27762 datasheet limits with the 1 % feedback
resistors). Values: R1 = R3 = 330k+330k+100k, R2 = 330k, RF = 990.1, RG = 270.

| requirement | limit | current design (0.1 %) | new (1 %) | margin | |
|---|---|---|---|---|---|
| SC-2, +-6 V, AREF 3.20 | >= 80 mV per side | 114.6 mV | **93.2 mV** (corner search of tee.py: 100.3 mV) | +13 mV | PASS |
| SC-4 step at AREF 3.30 | <= 4 mV/code | 3.42 | 3.47 mV | +0.53 | PASS |
| SC-4 occupancy at AREF 3.30 | 70-75 % | 71.4-73.1 | **70.3-73.9 %** | 0.3 % over the 70 % floor | PASS, thin |
| SC-11 margin, +-1.25 V, AREF 3.20 | >= 80 mV | 118.9 mV | **91.3 mV** (tee.py corner search; scope sim 101.2) | +11 mV | PASS |
| SC-11 gain as built | 1.10-1.16 | 1.1185-1.1268 | **1.051-1.120** | -0.049 under 1.10 | **FAIL** |
| SC-3 R_in = R1 + R2||R3 | 1 MOhm | 0.990 MOhm nominal | 0.990 MOhm, +-1.0 % (0.980-1.000) | | derived, not simulated |
| SM-3 bandwidth, worst corner | >= 8 MHz | 106.4 / 15.1 MHz | 106.7 / 15.1 MHz | | PASS |
| SC-6 noise to 1.5 x BW | <= 200 uV | 138 / 158 uV | 140 / 154 uV | | PASS |
| AN-1 phase margin | >= 45 deg | 54.1 deg | 53.0 deg | | PASS |

SC-11 gain cannot be made to fit at 1 %: the window is 0.060 wide and 1 % parts
spread the gain over 0.069-0.071 at any nominal (RF 1k/RG 270 gives 1.059-1.129;
953/249 at 1 % gives 1.087-1.158 and also fails). **Proposal for the owner:
relax SC-11's as-built gain to the design's worst case, 1.05 to 1.13** (the host
calibrates each channel's gain on both ranges, PA-3; the 80 mV margin, which is the
real constraint, holds). Nothing else in the scope fails.

Not simulated here, flagged: with 1 % R and 5 % C the divider compensation (C1 R1 =
C2 (R2||R3)) is off by up to ~2 %, which the earlier report puts at ~0.8 % of
100 kHz step per 1 % of compensation error, so up to ~1.6 % step *(derived from
sim/scope/report.md; SC-5 flatness is host-calibrated; check)*.

## 3. SC-8, DF-3, EN-1 (sim/diff `tee.py`, 200 Monte Carlo draws + 6 signed corners, 1 %, 100 ppm/K, 20 K / +-10 K, sources matched, dT +-10 K)

| figure | requirement | current design | **new (1 %)** | verdict |
|---|---|---|---|---|
| SC-8 channel gain match, +-5 V | 3 % | 2.44 % | **5.44 %** | exceeds 3 % |
| SC-8 channel gain match, +-1.25 V | 3 % | 0.79 % | **7.07 %** | exceeds 3 % |
| DF-3 before calibration, DC, +-5 V | 30 dB | 32.1 dB (MC min 34.8) | **25.4 dB** (MC min 29.5) | below 30 |
| DF-3 before calibration, DC, +-1.25 V | 30 dB | 41.2 dB (MC min 49.7) | **23.2 dB** (MC min 30.3) | below 30 |
| DF-3 before calibration, 10 kHz, +-5 / +-1.25 V | 18 dB | 20.1 / 21.1 | 19.5 / 18.5 dB | PASS (+1.5 / +0.5) |
| DF-3 after tee calibration, DC, +-5 V (dT 10 K) | 44 dB | 47.5 | **43.6 dB** | -0.4 dB |
| DF-3 after tee calibration, DC, +-1.25 V (dT 10 K) | 44 dB | 50.9 | **42.4 dB** | -1.6 dB |
| DF-3 after tee calibration at **dT 5 K**, +-5 / +-1.25 V | 44 dB | n/a | **46.3 / 46.9 dB** | PASS |
| EN-1 gain drift over 20 K, +-5 V range | 0.2 % | 0.102 % | **0.336 %** | exceeds 0.2 % |
| EN-1 gain drift over 20 K, +-1.25 V range | 0.2 % | 0.128 % | **0.621 %** | exceeds 0.2 % |

EN-1 is `en1_drift.py`: every sign combination of each resistor's +-100 ppm/K
(R1, R2, R3, RF, RG; Ron drift 1 %/10 K added on +-5 V, from sim/diff, itself
*(check)*), simulated at -10 K and +10 K; the 0.1 % row uses 25 ppm/K (10 ppm/K RG).
The gain-grid runs are 1 mV-level reproducible; a non-converged vendor-model draw
is dropped and counted (0 dropped in the final runs).

Proposals (relaxations, as D-V2-2 and D-V2-3 already foresee), never Extended
parts: SC-8 to **5.5 % (+-5 V) and 7.1 % (+-1.25 V)**; DF-3 before calibration to
**25 dB (+-5 V) and 23 dB (+-1.25 V)** at DC (hardware differential mode held to
that); EN-1 uncalibrated gain drift to **0.34 % (+-5 V) and 0.62 % (+-1.25 V)**
over 20 K; DF-3 after calibration is held at 44 dB **only if the recalibration
threshold is 5 K since calibration** (not 10 K): the post-calibration figure is
the thing that tightens, because the stage tempco drifts the calibrated slope.

Why the 1.25 V range is worst: RF/RG sets its gain, so their tolerance and
tempco appear directly; 1 % RG and RF alone are +-2 % of gain.

## 4. Power rails (sim/powercal, sim/awg, 1 % feedback resistors)

| item | current | new |
|---|---|---|
| +3.3 V_A nominal / range at LM27762 limits | 3.288 / 3.235-3.342 V (0.1 %) | **3.300 / 3.2095-3.3926 V** |
| -rail nominal / range | -2.071 / -2.041..-2.106 V | **-2.052 / -2.005..-2.099 V** |
| bare rails sum at datasheet maxima (OPA365 abs max 5.5) | 5.445 V (55 mV) | **5.492 V (8 mV)** -- thin |
| P1-a op-amp pins during start-up | 4.796 V | 4.841 V (PASS) |
| AW-8 start-up worst (limit 2.1 V) | 1.745 V | 1.730 V PASS |

FB+ and FB- were chosen by a script search over Basic series/parallel
combinations of up to three parts (best -rail minimum with the bare-rail sum under
5.5 V at 1 %): 175k keeps the sum at 5.492 V; the nearer 176.7k (100k + 100k||330k)
with the old FB- gave 5.497 V and a worse AW-1. (Search not kept as a script; the
rail sums are in `results/powercal_v1b.json`.)
The 8 mV margin to the OPA365's absolute maximum is the figure to watch; it holds
only because the series Schottkys (P1-a, 4.84 V) are fitted *(unchanged)*.

## 5. AWG (sim/awg, 49 rows run on the new values, then all 151)

| requirement | limit | current | new | |
|---|---|---|---|---|
| AW-7 gain (window 1.10-1.20; as built) | 1.10-1.20 | 1.1486-1.1541 | **1.1562-1.1967** | PASS, +0.003 at the top: thin |
| AW-1 window use, position-aware [A] / [B] | <= 92 % | 88.8 / 85.1 % | **90.0 / 88.9 %** | PASS (+2.0 / +3.1) |
| AW-1 window width [A] / [B] | <= 92 % | 81.6 / 81.1 | 81.1 / 80.6 % | PASS |
| AW-2 one code at the output | <= 1 mV | 0.620 | 0.643 mV | PASS |
| AW-1 into 50 ohm (34 uV/mA) | 0.62 mV | 0.31 | 0.31 mV | PASS |
| AW-3 bandwidth hi-Z / 50 ohm (worst corner) | >= 8 MHz | 15.1 / 9.5 | 14.5 / 8.9 MHz | PASS (+0.9 MHz) |
| AW-4 overshoot, open cable | <= 5 % | 1.2 | 0.7 % | PASS |
| PW-3 short, window ends | <= 30 mA | 26.08 | 27.14 mA | PASS |
| PR-4 forced +-1.8 V, op-amp current | <= 65 mA | 57.1 | 57.6 mA | PASS |
| AN-1 DAC0 buffer phase margin | >= 45 | 59.8 | 59.6 deg | PASS |

AW-7 offset before calibration is information only (127 / 157 mV against the old
90 / 84 mV; the host calibrates it). AW-1's 92 % window is the binding check; the
Vmid divider top (339.4k) and the second 22 ohm in Rb/Rf were added to bring it
under 92 % (with 330k and one 22 ohm: 93.8 % [A], FAIL). All 151 rows: 4 FAIL.
Three (OPA365 model fit, AW-6 with OPA354 and OPA356) also fail in the current
design and are not design rows; the fourth is a guard row whose threshold the
AW-4 change moves. The one guard that changes is "Rs removed (short)", which reads 74 mA broken
and 21 mA restored against a 20.5 mA threshold; it needs its threshold re-set
(21 mA is the real short current with 50.0 ohm), not a design change.

## 6. AWG back-termination: 2 x 100 ohm 1206 (C17901) in parallel

50.0 ohm +-1 % worst case (series/parallel of 1 % parts stays within 1 %), AW-4
holds. Power: the sim's forced +-5 V case for 10 s puts 0.286 W in the pair =
0.143 W per part against a 0.25 W rating at 70 C (57 %); a short at the DAC window
ends is 27 mA = 0.04 W total (PW-3 above). If the AWG op-amp could source the 64 mA
v2's document derives, each part would see 0.10 W, 41 % of rating *(that is v2's
derived figure, not this design's)*. 0.25 W is the page's rating, derated above 70 C
*(check datasheet derating curve)*.

## 7. Calibration ladder: 8 x 270 ohm (C22966), 3 in parallel at the bottom, 5 in series

Total 1440 ohm; 2.08 mA nominal, 2.12 mA at all elements -1 %. Taps (V): **0.1875,
0.750, 1.3125, 1.875, 2.4375, 3.000** (the top is the REF3030E). Tap Thevenin
impedance: 84, 270, **354 (worst, tap 3)**, 338, 219 ohm; every element at +1 % gives
358 ohm. 220 ohm would give 1170 ohm total, 2.6 mA and about 290 ohm worst: both are
inside the limits; 270 keeps more margin on PA-9 leakage, so 270 is chosen.

| check | limit | result |
|---|---|---|
| C1-a tap impedance | <= 5 kohm | 358 ohm worst, PASS |
| C1-b settling into the Due S/H | <= 0.5 LSB | 0.000 LSB, PASS |
| C2-c PA-9 leakage rule, 0.5 uA x tap Z, added to the fit | <= 0.5 LSB | **0.181 LSB**, PASS |
| C2-a/b fit error with the taps re-read | <= 0.5 LSB | 0.098 / 0.101 LSB, PASS |
| C2-d the same with a stale reading (+-0.10 % drift, 100 ppm/K x 10 K) | <= 0.5 LSB | **0.826 LSB, FAIL** unless the taps are re-read at every calibration (PA-9 already requires it) |
| REF3030E load | +-10 mA (datasheet SBVS032K features and load-regulation range) | 2.12 mA; short-circuit current 35 mA typ, abs max 70 mA |
| REF3030E headroom, VIN - VOUT at +3.3 V_A min | dropout 200 mV max | **210 mV**: 10 mV over the dropout maximum -- thin, set by the 1 % FB+ resistors; with 0.1 % it was 235 mV |

Self-heating 0.18 K = 2.7 ppm; elements dissipate 1.2 mW each of 100 mW.

## 8. AN-4 / SC-2 centring at the ADC pin (sim/powercal P8-c)

P8-c computes a 30 mV centring error; with every network resistor at 1 % it reads
**57.4 mV**, which exceeds 30 mV -- but that figure counts the network's own
tolerance, which sim/scope's SC-2 corner search already counts separately. The
share that SC-2's +-30 mV centring allowance stands for (the Vmid divider, the
sense filter and the AREF/V33 spread, network ideal) is **23.1 mV** (current
design, same method: 9.0 mV). SC-2 therefore holds at the 93 mV above.

## 9. Check on the checks

- Current design reproduced exactly by each tool (section header).
- The SC-11 window check is able to fail: the same 1 % with the old 953/249 gives
  1.087-1.158 (FAIL), and RF 1k/RG 270 alone gives 1.059-1.129 (FAIL).
- tee.py's own guard "DF-3 after calibration sees the residual" reads **NO**
  at dT 10 K on the new design, because the good value (42.4 dB) is already
  below 44 dB, so the guard's premise (good >= 44 > broken) is not met; at dT 5 K
  it fires (46.3 -> 37.0). A tool-side artefact, not a defect.
- A broken-vendor-model draw (one in 200 at the first run: gain 203 % apart) was
  found and is now dropped and counted; the first SC-8 reading of 203.9 % was that
  draw, not a design result.

## 10. What I did not do

Not run: AC flatness/compensation at 1 % (SC-5), zin SC-3, power-up rows of
powercal beyond P1/P3/C1/C2, noise of the AWG with the new parts beyond the
49+ rows, and Vmid-buffer loop parts (their resistors, 4.7k and 1R, are unchanged
Basic). The op-amp change is another helper's.

## 11. Scripts (all in this folder)

- `scope_windows.py TAG RF RG [--mc]` -- sim/scope DC windows (env `V1B_TOL`, `V1B_VCC_LO/HI`).
- `scope_ac.py TAG RF RG` -- SM-3, AN-1, SC-6.
- `en1_drift.py` -- EN-1.
- `powercal_v1b.py` -- rails, ladder, AN-4 on `sim/powercal` (edited copy).
- `sim/diff/tee.py` with env `V1B_TAG V1B_TOL V1B_TCR V1B_RF V1B_RG V1B_VCC_LO V1B_VCC_HI V1B_DT` -- SC-8, DF-3. Reports: `sim/diff/report_{current,basic,basic_dt5}.md`.
- `sim/awg/run.py` (edited copy, env `V1B_FBP V1B_FBN V1B_VMTOP V1B_N22`) -- AWG; output `sim/awg/awg_basic.log`, `raw/results.json`.
- Results JSON in `results/`.
