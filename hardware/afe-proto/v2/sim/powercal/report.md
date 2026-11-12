# AFE version 2: power, reference and calibration block (generated from results/ by report.py)

AWG inputs read at run time: `../awg/design.py` sha256 `158d413378e44bdd`, `../awg/report_table.md` sha256 `f03b832df255f3d6`; AWG values {"Rbin": 2400.0, "Rbpl": 27000.0, "Rf": 470.0, "Rg1": Infinity, "Rg2": 510.0, "Rvr": 0.0}.

Status: PASS / FAIL / info against the stated limit; every FAIL is also in design.md. A check was trusted only after it failed on purpose (Guards table at the end).

## 1. Shared rail, PW-1, V2-2 supply rating, PR-3 (power.py)

| | ID | req | case | limit | result | margin | note |
|---|---|---|---|---|---|---|---|
| PASS | PW-V2-2 | V2-2 | supply across the op-amp <= recommended 5.5 V (TPH2502 VDD row) at both rails' worst corners, 1 % Basic feedback, +-10 K, regulation 2 mV | V+ + &#124;V-&#124; at the maximum corner <= 5.5 V | 3.4172 + 2.0525 = 5.4697 V | +0.0303 V | the TPH2502 gives only a VDD 2.5..5.5 V row; abs max 7.0 V. The margin is a few millivolts: see the R3 table |
| PASS | PW-V2-2b | V2-2 | the same at the abs-max reading (information) | 7.0 V | 5.470 V | +1.53 V |  |
| PASS | PR-2 | PR-2 | the powered scope op-amp's supply <= 3.45 V (anything that drives A0/A1) | <= 3.45 V | 3.4172 V | +0.0328 V |  |
| PASS | PA-2/rail | PA-2 | REF3030E VIN >= VOUT + 0.2 V (6.3, REF30xxE) at the weakest +rail | >= 3.203 V (VOUT at +0.1 %) | 3.2205 V | +0.0175 V | only 1 % Basic feedback resistors move this: with VFB 1.5 % and the resistors 1.3 % the rail's window is the reference's whole dropout margin |
| PASS | PW-6 | PW-6 | LDO headroom at 5V pin 4.50 V: +LDO (VIN - V+max) and the pump (&#124;CPOUT&#124; - &#124;V-&#124;max) | >= 0.05 V / 0.03 V (dropout at 100 mA, 5.5 VLDO+/-) | 1.08 V / 2.35 V |  | RNEG 2.5 ohm at 100 mA / 5.5 V; 3 ohm assumed at 4.5 V (check) |
| PASS | PW-1 | PW-1 | AFE current from the Due's 5V pin, normal operation, IQ at the datasheet maximum, rails at the strong corner | <= 100 mA | 83.2 mA | +16.8 mA | charge-pump input current = output current + 10 % + IQ 0.39 mA (the datasheet gives no efficiency table in text: check) |
| PASS | PW-1 total | PW-1 | Due (300 mA, D7) + AFE in the worst fault (indefinite short), <= 450 mA | <= 450 mA | 418 mA (117.6 mA AFE) | +32 mA | the short is exempt from the 100 mA, not from the 450 mA total |
| PASS | PW-1/th | PW-1 | LM27762 junction at 85 C ambient, worst state, 5.25 V in, RthJA 62.2 C/W (the datasheet's)  | <= 125 C | 104 C (299 mW) | +21 K | RthJA is the datasheet's JEDEC figure; a real board does better or worse: check |
| info | PW-2 | PW-2 | ripple at an amplifier supply pin <= 20 mV | <= 20 mV | see lm27762 runs and section 'PW-2' |  | the switching frequency is the part's 1.7 to 2.3 MHz (2 MHz typ), not settable; see the rule in design.md |
| info | PR-3/src | PR-3 | worst current pushed into the +3.3 V_A rail by both inputs at +12 V (0.3 V clamp drop assumed, R1 -1 %) | information | 38.5 uA |  | the scope design's 36 uA was a 0.6 V drop; a Schottky-like input structure raises it: *(check)* the TPH2502 gives no unpowered figure |
| info | PR-3/ic | PR-3 | sink the unpowered ICs provide at 0.5 V by datasheet: feedback divider only | information | 2.6 uA |  | LM27762 shutdown discharge 50 kohm would add 10 uA at 0.5 V but 6.4.1 does not say it works with VIN = 0 *(check)*; ADS1115, REF3030E and the op-amps give no leakage at 0.5 V: none counted |
| info | PR-3/ic2 | PR-3 | sink counted if the LM27762's discharge works (information) | information | 12.6 uA |  | not relied on |
| PASS | PR-3 | PR-3 | unpowered +3.3 V_A rail with both scope inputs at +12 V, 10k bleed (C25804) at +1 %, with only the resistive sinks | <= 0.5 V | 0.378 V | +0.122 V | sinks 52.1 uA against 38.5 uA pushed in at 0.5 V |
| info | PR-3/Q | PW-1 | quiescent cost of the bleed, rail at its maximum, resistor -1 % | information | 0.343 mA = 0.34 % of 100 mA |  |  |
| PASS | PR-3/Due | PR-3 | current into the Due's supply pins <= 100 uA | <= 100 uA | 1.8 uA (scope design, through R3 and the sense filter; nothing reaches the 5V pin) |  | the scope design's figure, not re-derived here; the bleed does not change it |

## 1b. SC-9 through the shared rail, PW-2, PW-7 (coupling.py)

| | ID | req | case | limit | result | margin | note |
|---|---|---|---|---|---|---|---|
| PASS | SC-9/DC | V2-1, SC-9, VT-20 | AWG stepped between its window ends into 50 ohm: change of a scope reading, settled, the four paths by which a scope on +3.3 V alone still hears the AWG (sum, 1 LSB = 1.73 mV at the input) | <= 2 LSB | 0.120 LSB (largest: the assumed plane return, 0.116 LSB) | +1.88 LSB | the scope is on +3.3 V only (its V- is ground), so the negative rail reaches it only through the shared LM27762: the 5 V feed and the +LDO's line regulation; the paths are the +rail's load regulation, the feed, the shared reference, and the shared return |
| PASS | SC-9/AC | SC-9 | the AWG's 15 mA step on OUT+: peak rail movement by hand (2 x 10 uF at 50 % of nominal, 4 mohm ESR, a 1 us LDO response) = 1.53 mV, through an assumed PSRR 80 dB flat to 10 kHz then -20 dB/dec at 200 kHz | <= 2 LSB | 0.0018 LSB |  | no converged LM27762 step run: hand estimate *(check)* |
| PASS | PW-2/ripple | PW-2, SC-6 | ripple at the +3.3 V rail from this block's LM27762 runs (largest peak-to-peak 0.16 mV), through the assumed PSRR at 2 MHz (-34 dB), at the scope's pin | <= 0.2 mV rms (SC-6) and the rail <= 20 mV (PW-2) | 3.3 uV pk-pk at the pin, 0.16 mV at the rail |  | the model has no LDO loop and under-reads the datasheet (version 1's note); PW-2's 20 mV holds by 30x, SC-6 by 15x on the model's figure *(check, VT-8)* |
| info | PW-2/fsw | PW-2 | switching frequency, the rule: not settable (LM27762 fSW 1.7 to 2.3 MHz, 2 MHz typ at VIN 3.6 V; pulse-skipping below that at light load, the loop 'can drop into the sub-2-kHz range when unloaded', 6.3.3) | stated, with the wide path in mind | line at 2 MHz +-15 %, inside SM-3's 8 MHz band; residue at the pin 3.3 uV |  | the AFE's idle load is never light: the AWG dual alone draws 15 mA on each rail, so the pump runs at constant frequency (a moving sub-2-MHz spur would need a load under a few mA) *(check at the PFM threshold: not given)* |
| PASS | PW-2/AWG | PW-2, AW-6 (D22: 0.3 mV) | ripple at the AWG dual's supply pin with 100 nF + 1 uF at the pin: 0.16 mV pk-pk on OUT+ (TI model) x 0.3; at the AWG output through the op-amp-like PSRR | <= 20 mV at the pin; <= 0.3 mV rms at the output (AW-6, D22) | 0.05 mV pk-pk at the pin, 0.8 uV rms at the output | +299 uV | the model under-reads: a factor 10 more still passes |
| PASS | PW-2/AWG | PW-2, AW-6 (D22: 0.3 mV) | ripple at the AWG dual's supply pin with 100 nF only (1 uF dropped): 0.16 mV pk-pk on OUT+ (TI model) x 1.0; at the AWG output through the op-amp-like PSRR | <= 20 mV at the pin; <= 0.3 mV rms at the output (AW-6, D22) | 0.16 mV pk-pk at the pin, 2.6 uV rms at the output | +297 uV | the model under-reads: a factor 10 more still passes |
| PASS | PW-7 | PW-7 | rails up (this block's LM27762 runs: +rail 90 % at 0.29 ms, -rail 0.50 ms) then the REF3030E's 2 ms to 0.1 %, then the scope node's own RC (about 12 us) | <= 15 s | 2.5 ms |  | PW-7 is met by 3 orders of magnitude by the electrical start-up; what takes seconds is thermal (VT-18), not the rails. The host flags readings not ready until the ADS1115 sees the reference within 0.1 % of its first valid reading |

## 3 and 4. REF3030E roles and the ladder (refladder.py)

| | ID | req | case | limit | result | margin | note |
|---|---|---|---|---|---|---|---|
| PASS | REF/src | PA-2, D-V2-10 | REF3030E source current, every load at once (ladder, both scope centres at -12 V, sense default tie with the AWG at the window bottom, ADS inputs) | <= 10 mA (6.3) | 1.736 mA | +8.26 mA |  |
| PASS | REF/snk | PA-2, D-V2-10 | REF3030E sink current in the clamped-input case: both scope inputs at +12 V (node clamped past the rail) and the AWG forced +5 V through the sense divider (PR-4) | <= 10 mA | 80 uA | +9.92 mA | the sink load regulation 150 ppm/mA is 10x the source figure but at this current moves the output by 0.01 ppm |
| PASS | REF/lreg | SC-7 | the ladder's top tap (= the reference) moves with the AWG level through the sense divider's default tie: change of source current over the sweep x 15 ppm/mA | <= 3.0 mV (0.1 % fit share of 3 V) | 0.165 mA -> 7.4 uV | +2993 uV | the host reads the reference with every tap reading; this is the movement between two readings |
| PASS | REF/signal | SC-7, D-V2-10 | the scope's signal current in the reference the ADS1115 reads: both inputs swept from -12 V to +12 V, 5.4 uA to -1.4 uA each | <= 3.0 mV | 0.49 uV |  |  |
| PASS | REF/dropout | PA-2 | VIN >= VOUT + 0.2 V at the weakest +rail (power.py) | >= 3.200 V | see power.json min_p |  | the rail block's corner, see section 1 |
| info | REF/CL | PA-2 | output capacitor | 0.1..22 uF, ESR 10..500 mohm | 1 uF X5R (C15849) |  | 1 uF C15849 X5R at the output: the datasheet's CL range 0.1..22 uF holds; its ESR window 10..500 mohm is above a ceramic's (a few mohm) *(check: the datasheet states stability with ceramics only by the CL range)* |
| PASS | PA-9/Z | PA-9, SC-10 | tap source impedance against the Due ADC pin leakage 0.5 uA (over temperature): the worst tap (1/2) x 0.5 uA in LSB of 3.3 V / 4096 | <= 0.5 LSB | 495 ohm -> 0.247 mV = 0.31 LSB | +0.19 LSB | tap impedances (ohm): 275, 440, 495, 440, 275 and 0 for the top; all far under SC-10's 5 kohm |
| info | PA-9/I | PW-1 | ladder current from the reference | information | 1.53 mA at REF +0.1 %, rungs -1 % |  |  |
| PASS | PA-9/ads | SC-7 | the ADS1115's input current (V - 0.7 V over Zcm 6 Mohm -25 %, typ only) across the tap impedance, the two measured taps | <= 0.01 % (a tenth of the fit share) | 0.0098 % (1/3 tap), 0.0098 % (2/3 tap) |  | SBAS444E gives the input impedance as a typical only *(check)* |
| **FAIL** | PA-9/drift | EN-1, VT-12 | a measured tap's fraction of the reference after 10 K since it was read (rungs +-100 ppm/K, opposed), against the fit share 0.1 % | <= 0.1 % | 0.133 % (1/3 tap), 20 K: 0.267 % | -0.033 % | the host can re-read the measured taps at any time (no tee, no AWG), so this is the worst drift between the last read and use, not a calibration interval |
| info | PA-9/unmeas | PA-9 | the three unmeasured taps (1/6, 1/2, 5/6): fraction error from 1 % rungs, 99.9th percentile | information (fault check threshold) | 1.30 %, 0.72 %, 0.26 % |  | so a host fault check on the unmeasured taps uses a window of +-1.5 % of the nominal fraction (derived from this) |
| info | PA-9/dT | EN-1, VT-12 | the temperature change since a tap was read that keeps its drift inside 0.1 % (and inside 0.05 %, the half this design gives the ladder) | information (sets the recalibration threshold, D-V2-3) | 7.5 K (0.05 %: 3.7 K) |  | 10 K (EN-1) fails; the host re-reads the two measured taps at the start and end of each session, so the working figure is the change within one session |

## 5. Sense divider and jumper (sense.py)

| | ID | req | case | limit | result | margin | note |
|---|---|---|---|---|---|---|---|
| PASS | PA-4/range | PA-4 | sweep, wire ON throughout: sense tap pin voltage over every AWG level -1.95..+2.28 V, every resistor at +-1 %, REF +-0.1 % | 0 V .. 3.22 V (ADS supply minimum) | 0.141 .. 1.891 V (node 0.140 .. 1.892) | +0.141 V / +1.329 V | k = 0.4, bottom node = the 1/3 tap |
| PASS | PA-4/range-off | PA-4 | the same with the wire OFF (default tie to the REF3030E; the normal-use state) | 0 V .. 3.22 V | 0.881 .. 2.697 V | +0.881 V / +0.523 V |  |
| **FAIL** | PA-4/ratio | PA-4, SC-7 | AWG level read through the sweep, wire on throughout, ratio from wire-off and wire-on readings at one level, ADS channel match 0.1 % (max), 99.9th percentile | gain <= 0.05 %, offset <= 3 mV (this design's half of the 0.1 % fit share, and of the 5 mV) | gain 0.489 %, offset 6.87 mV, worst point 15.71 mV (k error 0.370 %) |  | a share of 0.05 % for the sense is this design's allocation of the 0.1 % fit share (the Due-ADC fit takes the rest) |
| info | PA-4/ratio-typ | PA-4 | the same at the typical channel match 0.05 % | information | gain 0.336 %, offset 4.87 mV |  |  |
| info | PA-4/ratio-0 | PA-4 | the same with no channel mismatch (shows what the match costs) | information | gain 0.246 %, offset 3.76 mV |  |  |
| PASS | D21/sweep | D21, PA-4 | ADS1115 free-running on the sense node ONLY during the staircase; B (the wired 1/3 tap) and the reference read at the first and last step, every level between taken from the straight line of the tap through those two (the network is linear) | the same as reading B at every level | gain 0.489 %, offset 6.85 mV, worst point 15.71 mV (B at every level: 0.489 %, 6.87 mV) |  | the free-running reading loses nothing: the tap is a linear function of the AWG level, so the two end readings fix the line; the channel switches (to B and the reference) cost one conversion each at the ends |
| PASS | D21/time | D21, PA-3 | ADS1115 at 128 SPS (7.8 ms a conversion, single-cycle settling), staircase step 0.05 s: conversions per level, minus two (the one the step lands in, one for I2C alignment) | >= 4 averaged readings at the shortest step | 6 conversions, 4 averaged, 156 uV rms at the AWG node (if the input dithers the converter) |  | 128 SPS is the fastest rate whose peak-to-peak noise equals its rms in Table 6-1 (250 SPS and up: pp 148 to 267 uV); the staircase step is the Due-side averaging time (PA-3: 100,000 samples a point), which the AWG/Due set, so see the table in design.md for the total time |
| info | PA-4/load | PA-4 | the loaded ladder tap (1/3, ADS input 3): its shift from 1.000 V over the sweep with the wire on | information (not a calibration point while fitted) | 631 mV at most, wire current up to 118 uA |  | the other measured tap (2/3, input 4) is untouched; the wire-off readings before fitting and after removal read every tap |
| PASS | VT-22/I | VT-22, PA-4 | any position the header allows (GND, every tap, +3.3 V_A, and the Due's 5V and VIN as stress): the current into the ADS1115's input diodes through Rt&#124;&#124;Rb + Rs | <= 10 mA (abs max), host takes no action | 429 uA at most | +9571 uA | Rs 4.7k is the only protection; whether the other three inputs read undisturbed during the overdrive is not in SBAS444E (7.3.1 warns) *(check, VT-22)* |
| PASS | VT-22/dist | V2-5, VT-22 | every position gives a distinguishable T shift against the wire-off reading (dT = (1-k)(X - 3.0 V)); smallest gap between positions | >= 20 x the reading resolution (125 uV + 0.1 % of 3 V) | 180 mV gap vs 3.12 mV resolution |  | tap6 = REF reads dT = 0, i.e. as 'no wire': the host says 'wire missing or on the top tap' and stops either way |
| PASS | VT-21/22/det | VT-21, VT-22 | a wire left on after the calibration, or missing at its start: the tap's difference between the two positions at every AWG level (the host compares the wire-off reading taken before fitting and after removal with the sweep's) | >= 50 mV (about 16x the reading resolution) at every level, every tolerance draw | 734 mV minimum | +684 mV | left on in normal use the tap stays inside 0.14 .. 1.89 V (PA-4/range) and the 1/3 ladder tap is loaded by up to 118 uA: nothing is damaged, and the Due's reading of that tap is flagged by the host's end-of-session check |

## 6. ADS1115 and SC-7, the extrapolation (sc7.py)

| | ID | req | case | limit | result | margin | note |
|---|---|---|---|---|---|---|---|
| PASS | SC-7/ext | SC-7, PA-3, VT-23 | fit extrapolated to +3.5 V (AWG window -1.9 .. 2.05 V covers 71 % of the range), INL cubic 0.5 LSB, 1024 points: A = tee only, B = with ladder anchors, 99.9th pct | <= 3.5 mV (0.1 % of 3.5 V) | A 0.27 mV (0.008 %), B 3.45 mV (0.099 %) | A +3.2 / B +0.0 mV | B passes the share; against SC-7's whole 0.5 % + 5 mV = 22.5 mV both leave 19.0 mV. One Due LSB is 1.73 mV at the input |
| PASS | SC-7/ext | SC-7, PA-3, VT-23 | fit extrapolated to +3.5 V (AWG window -1.9 .. 2.05 V covers 71 % of the range), INL cubic 1.2 LSB, 1024 points: A = tee only, B = with ladder anchors, 99.9th pct | <= 3.5 mV (0.1 % of 3.5 V) | A 0.64 mV (0.018 %), B 4.14 mV (0.118 %) | A +2.9 / B -0.6 mV | B fails the share; against SC-7's whole 0.5 % + 5 mV = 22.5 mV both leave 18.4 mV. One Due LSB is 1.73 mV at the input |
| PASS | SC-7/ext | SC-7, PA-3, VT-23 | fit extrapolated to +3.5 V (AWG window -1.9 .. 2.05 V covers 71 % of the range), INL parab 1.2 LSB, 1024 points: A = tee only, B = with ladder anchors, 99.9th pct | <= 3.5 mV (0.1 % of 3.5 V) | A 1.76 mV (0.050 %), B 3.29 mV (0.094 %) | A +1.7 / B +0.2 mV | B passes the share; against SC-7's whole 0.5 % + 5 mV = 22.5 mV both leave 19.2 mV. One Due LSB is 1.73 mV at the input |
| PASS | SC-7/ext | SC-7, PA-3, VT-23 | fit extrapolated to +3.5 V (AWG window -1.9 .. 2.05 V covers 71 % of the range), INL knots 1.2 LSB, 1024 points: A = tee only, B = with ladder anchors, 99.9th pct | <= 3.5 mV (0.1 % of 3.5 V) | A 2.28 mV (0.065 %), B 5.68 mV (0.162 %) | A +1.2 / B -2.2 mV | B fails the share; against SC-7's whole 0.5 % + 5 mV = 22.5 mV both leave 16.8 mV. One Due LSB is 1.73 mV at the input |
| PASS | SC-7/ext | SC-7, PA-3, VT-23 | fit extrapolated to +3.5 V (AWG window -1.9 .. 2.2275 V covers 75 % of the range), INL cubic 0.5 LSB, 1024 points: A = tee only, B = with ladder anchors, 99.9th pct | <= 3.5 mV (0.1 % of 3.5 V) | A 0.26 mV (0.008 %), B 3.28 mV (0.094 %) | A +3.2 / B +0.2 mV | B passes the share; against SC-7's whole 0.5 % + 5 mV = 22.5 mV both leave 19.2 mV. One Due LSB is 1.73 mV at the input |
| PASS | SC-7/ext | SC-7, PA-3, VT-23 | fit extrapolated to +3.5 V (AWG window -1.9 .. 2.2275 V covers 75 % of the range), INL cubic 1.2 LSB, 1024 points: A = tee only, B = with ladder anchors, 99.9th pct | <= 3.5 mV (0.1 % of 3.5 V) | A 0.63 mV (0.018 %), B 4.01 mV (0.115 %) | A +2.9 / B -0.5 mV | B fails the share; against SC-7's whole 0.5 % + 5 mV = 22.5 mV both leave 18.5 mV. One Due LSB is 1.73 mV at the input |
| PASS | SC-7/ext | SC-7, PA-3, VT-23 | fit extrapolated to +3.5 V (AWG window -1.9 .. 2.2275 V covers 75 % of the range), INL parab 1.2 LSB, 1024 points: A = tee only, B = with ladder anchors, 99.9th pct | <= 3.5 mV (0.1 % of 3.5 V) | A 1.64 mV (0.047 %), B 3.06 mV (0.087 %) | A +1.9 / B +0.4 mV | B passes the share; against SC-7's whole 0.5 % + 5 mV = 22.5 mV both leave 19.4 mV. One Due LSB is 1.73 mV at the input |
| PASS | SC-7/ext | SC-7, PA-3, VT-23 | fit extrapolated to +3.5 V (AWG window -1.9 .. 2.2275 V covers 75 % of the range), INL knots 1.2 LSB, 1024 points: A = tee only, B = with ladder anchors, 99.9th pct | <= 3.5 mV (0.1 % of 3.5 V) | A 2.25 mV (0.064 %), B 5.33 mV (0.152 %) | A +1.2 / B -1.8 mV | B fails the share; against SC-7's whole 0.5 % + 5 mV = 22.5 mV both leave 17.2 mV. One Due LSB is 1.73 mV at the input |
| info | SC-7/ext-ideal | SC-7 | the same (cubic 1.2 LSB, top 2.2275 V) with perfect anchors (no ADS channel mismatch, no offset, no pin offset) | information | A 0.63 mV, B 1.93 mV at +3.5 V |  | what the ladder would buy if the ADS1115 read its taps exactly |
| **FAIL** | SC-7/sum | SC-7 | this block's gain terms alone, linear sum (RSS in the note), and its offset, against ±0.5 % of reading ± 5 mV | <= 0.5 % and <= 5 mV for the WHOLE of SC-7 (the scope's own terms come on top) | 0.77 % (RSS 0.52 %), 6.9 mV | -0.27 % | the sense chain's channel match, offsets and 1 % parts are the dominant term, see section 5 |
| PASS | SC-7/noise | SC-7 | ADS1115 noise averaged over 64 conversions, referred to the AWG node through k = 0.4 (125 uV rms per reading, Table 6-1) | <= 1 mV | 39 uV rms |  | the table's figure equals one LSB: the converter is quantisation-limited, so averaging reduces it only if the input noise dithers it; the worst case without dither is 0.5 LSB = 156 uV at the node |

## Rails, corners (power.py)

| | V |
|---|---|
| max_n | 2.0525 |
| max_p | 3.4172 |
| min_n | 1.9549 |
| min_p | 3.2205 |
| nom_n | 2.0032 |
| nom_p | 3.3176 |

R3 options (R1 120k, R2 68k, R4 100k fixed): the negative rail against the rating margin

| R3 | nominal | min | max | sum with the +rail max | rating margin |
|---|---|---|---|---|---|
| 62.2k | 1.9788 | 1.9314 | 2.0272 | 5.4444 | +56 mV |
| 64.2k | 2.0032 | 1.9549 | 2.0525 | 5.4697 | +30 mV |
| 66.0k | 2.0252 | 1.9761 | 2.0753 | 5.4925 | +8 mV |
| 68.0k | 2.0496 | 1.9996 | 2.1006 | 5.5178 | -18 mV |

PW-1 states (IQ at the datasheet maximum; I in mA)

| state | +rail V | OUT+ | OUT- | 5V pin | op-amp output |
|---|---|---|---|---|---|
| normal, AWG hi-Z at the window top | 3.417 | 34.9 | 16.2 | 53.2 | -1.2 |
| normal, AWG hi-Z at the window top | 3.220 | 34.6 | 16.0 | 52.6 | -1.0 |
| normal, AWG into 50 ohm at the window top | 3.417 | 56.2 | 15.0 | 73.1 | +21.2 |
| normal, AWG into 50 ohm at the window top | 3.220 | 56.1 | 15.0 | 72.9 | +21.4 |
| normal, AWG into 50 ohm at the window bottom | 3.417 | 39.3 | 39.5 | 83.2 | -24.5 |
| normal, AWG into 50 ohm at the window bottom | 3.220 | 39.0 | 39.3 | 82.6 | -24.3 |
| normal, AWG hi-Z at the window bottom | 3.417 | 39.3 | 20.4 | 62.2 | -5.4 |
| normal, AWG hi-Z at the window bottom | 3.220 | 39.0 | 20.2 | 61.7 | -5.2 |
| fault: BNC shorted, DAC at the window top | 3.417 | 78.7 | 15.0 | 95.6 | +43.8 |
| fault: BNC shorted, DAC at the window top | 3.220 | 78.6 | 15.0 | 95.5 | +44.0 |
| fault: BNC shorted, DAC at the window bottom | 3.417 | 39.3 | 58.8 | 104.4 | -43.8 |
| fault: BNC shorted, DAC at the window bottom | 3.220 | 39.0 | 58.6 | 103.9 | -43.6 |
| fault: BNC shorted, DAC at the 3.3 V reset level (output clips about 0.1 V under the rail) | 3.417 | 100.7 | 15.0 | 117.6 | +66.9 |
| fault: BNC shorted, DAC at the 3.3 V reset level (output clips about 0.1 V under the rail) | 3.220 | 100.6 | 15.0 | 117.5 | +67.1 |

PR-3: bleed options (Basic 0603), the unpowered rail with both inputs at +12 V, only the resistive sinks (feedback divider + bleed)

| R | LCSC | sink at 0.5 V uA | rail V | quiescent at 3.3 V mA |
|---|---|---|---|---|
| 5.1k | C23186 | 99.7 | 0.205 | 0.647 |
| 5.6k | C23189 | 91.0 | 0.224 | 0.589 |
| 6.2k | C4260 | 82.5 | 0.246 | 0.532 |
| 6.8k | C23212 | 75.4 | 0.267 | 0.485 |
| 7.5k | C23234 | 68.6 | 0.292 | 0.440 |
| 8.2k | C25981 | 63.0 | 0.317 | 0.402 |
| 9.1k | C23260 | 57.0 | 0.348 | 0.363 |
| 10k | C25804 | 52.1 | 0.378 | 0.330 |
| 12k | C22790 | 43.9 | 0.444 | 0.275 |
| 13k | C22797 | 40.7 | 0.475 | 0.254 |
| 15k | C22809 | 35.6 | 0.536 | 0.220 |
| 18k | C25810 | 30.1 | 0.622 | 0.183 |
| 20k | C4184 | 27.4 | 0.677 | 0.165 |
| 22k | C31850 | 25.1 | 0.729 | 0.150 |
| 24k | C23352 | 23.3 | 0.779 | 0.137 |
| 27k | C22967 | 21.0 | 0.851 | 0.122 |
| 30k | C22984 | 19.1 | 0.918 | 0.110 |

## Sense chain, detail (sense.py)

| case | gain % (99.9) | offset mV | worst point mV | k error % |
|---|---|---|---|---|
| wire on throughout, max channel match 0.1 % | 0.489 | 6.87 | 15.71 | 0.370 |
| typical channel match 0.05 % | 0.336 | 4.87 | 11.03 | 0.257 |
| no channel mismatch | 0.246 | 3.76 | 8.14 | 0.186 |
| wire off throughout (information) | 0.453 | 6.63 | 14.42 | 0.370 |

Every header position (B tied to node X by the wire; T0 over the AWG sweep -1.95..+2.28 V; dT = change of the tap against the wire-off reading)

| node | X V | T0 min | T0 max | current into ADS diodes uA | wire current uA |
|---|---|---|---|---|---|
| GND | 0.0 | -0.780 | 0.912 | 45 | 91 |
| tap1 (1/6) | 0.5 | -0.480 | 1.212 | 17 | 98 |
| tap2 (1/3, ADS input 3): the RIGHT position | 1.0 | -0.180 | 1.512 | 0 | 118 |
| tap3 (1/2) | 1.5 | 0.120 | 1.812 | 0 | 138 |
| tap4 (2/3, ADS input 4) | 2.0 | 0.420 | 2.112 | 0 | 158 |
| tap5 (5/6) | 2.5 | 0.720 | 2.412 | 0 | 178 |
| tap6 = REF (same as wire off) | 3.0 | 1.020 | 2.712 | 0 | 198 |
| +3.3 V_A | 3.3 | 1.200 | 2.892 | 0 | 210 |
| Due 5V pin (stress) | 5.0 | 2.220 | 3.912 | 37 | 278 |
| Due VIN (stress) | 12.0 | 6.420 | 8.112 | 429 | 558 |

## SC-7 sum of this block (sc7.py)

| term | gain % | offset mV |
|---|---|---|
| REF3030E: initial 0.1 %, 15 ppm/K x 10 K, hysteresis 100 ppm, long-term 40 ppm | 0.129 | 0.0 |
| AWG sense chain (jumper ratio, ADS1115 at the max channel match, Rs, Zcm, 1 % resistors), 99.9th pct | 0.489 | 6.9 |
| Due-ADC fit extrapolated to +3.5 V (A, cubic 1.2 LSB, window top 2.2275) | 0.018 | 0.0 |
| ladder drift of a measured tap, 10 K since read | 0.133 | 0.0 |
| **linear sum (RSS)** | **0.77 (0.52)** | **6.9** |

## LM27762 transient runs (lm_tran.py, TI's model; the model has no LDO loop and converges by lottery)

| run | ok | VIN | OUT+ dc V | OUT- dc V | +rail t90 ms | -rail t90 ms | OUT+ max V | OUT- min V | bare max V | OUT+ pp mV | VIN pp mV | pump Hz |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| rip_bot | no: [] | | | | | | | | | | | |
| step_5.0 | no: [] | | | | | | | | | | | |
| su_4.5_min | no: [] | | | | | | | | | | | |
| su_5.0 | no: [] | | | | | | | | | | | |
| su_5.25_max | yes | 5.25 | 3.4177 | -2.0553 | 0.287 | 0.498 | 3.4954 | -2.0817 | 5.4993 | 0.16 | 20.7 | 1393040 |

## Guards: each check failed on purpose, then restored

| guard | what | broken | restored | |
|---|---|---|---|---|
| G-PW-rating | V2-2 supply check: R3 = 82k (nominal -2.26 V) must exceed 5.5 V at the corners | fails | passes | ok |
| G-PW-1 | PW-1 check with the limit lowered to 40 mA must fail | fails | passes | ok |
| G-PR-3 | PR-3 check with the bleed removed (1 Gohm) must fail | fails | passes | ok |
| G-REF-VIN | REF3030E dropout check with R1 = 100k (nominal 2.97 V) must fail | fails | passes | ok |
| G-sc9 | the SC-9 DC sum with the plane return assumed 100 ohm instead of 10 mohm must fail | fails | passes | ok |
| G-pw7 | PW-7 check against a 1 ms limit must fail | fails | passes | ok |
| G-Z | tap impedance check with 1.5 kohm rungs must fail | fails | passes | ok |
| G-REF-I | REF source check with a limit of 1 mA must fail | fails | passes | ok |
| G-drift | the drift limit applied to a 1000 ppm/K tempco ladder at 10 K must fail; the 100 ppm/K design passes the same limit at 5 K | fails | passes | ok |
| G-timing | the timing check with a step of 0.01 s (one conversion at 128 SPS: nothing left to average) must fail | fails | passes | ok |
| G-detect | the detection check with the separation limit raised to 2 V must fail | fails | passes | ok |
| G-range | tap range with k = 0.6 (tap goes below ground at the window bottom) must fail | fails | passes | ok |
| G-ratio | ratio accuracy with a 2 % channel match must fail a 1.5 % gain limit (the designed 0.1 % match passes it) | fails | passes | ok |
| G-distinct | distinguishability with k = 0.995 (wire barely moves the tap) must fail | fails | passes | ok |
| G-current | ESD current check with the limit lowered to 10 uA must fail | fails | passes | ok |
| G-ext | the extrapolation check with an INL of 12 LSB must fail the 0.1 % share | fails | passes | ok |
| G-sum | the SC-7 sum check against a 1.0 % limit with the sense chain's error multiplied by 10 must fail (the real sum passes the same 1.0 %) | fails | passes | ok |
| G-basic | an Extended passive (C861163) in the list must be refused | fails | passes | ok |
