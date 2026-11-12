# AFE version 2: power, reference and calibration block (generated from results/ by report.py)

AWG inputs read at run time: `../awg/design.py` sha256 `5827ab420628cd95`, `../awg/report_table.md` sha256 `73836e390675a858`; AWG values {"Rbin": 2400.0, "Rbpl": 27000.0, "Rf": 470.0, "Rg1": Infinity, "Rg2": 510.0, "Rvr": 0.0}.

Status: PASS / FAIL / info against the stated limit; every FAIL is also in design.md. A check was trusted only after it failed on purpose (Guards table at the end).

## 1. Shared rail, PW-1, V2-2 supply rating, PR-3 (power.py)

| | ID | req | case | limit | result | margin | note |
|---|---|---|---|---|---|---|---|
| PASS | PW-V2-2 | V2-2 | supply across the op-amp <= recommended 5.5 V (TPH2502 VDD row) at both rails' worst corners, 1 % Basic feedback, +-10 K, regulation 2.5 mV | V+ + &#124;V-&#124; at the maximum corner <= 5.5 V | 3.4177 + 2.0530 = 5.4707 V | +0.0293 V | the line: TPH2502 datasheet Rev. A, 'Electrical Characteristics' (continued), PDF page 4, row 'VDD Supply Voltage, MIN 2.5, MAX 5.5, V'; its Applications Information (PDF page 7) says 'specified over +2.7 V to +5.5 V ... the supply voltage may range from +2.5 V to +5.5 V'. The datasheet has no Recommended Operating Conditions table: 5.5 V is the top of its specified supply range and is taken as the recommended maximum. Abs max V+ - V- = 7.0 V (Absolute Maximum Ratings, PDF page 2; the text says 7.5 V). Minimum corner sum 5.175 V is inside 2.5 V. See the R3 table |
| PASS | PW-V2-2b | V2-2 | the same at the abs-max reading (information) | 7.0 V | 5.471 V | +1.53 V |  |
| PASS | PR-2 | PR-2 | the powered scope op-amp's supply <= 3.45 V (anything that drives A0/A1) | <= 3.45 V | 3.4177 V | +0.0323 V |  |
| PASS | PA-2/rail | PA-2 | REF3030E VIN >= VOUT + 0.2 V (6.3, REF30xxE) at the weakest +rail | >= 3.203 V (VOUT at +0.1 %) | 3.2200 V | +0.0170 V | only 1 % Basic feedback resistors move this: with VFB 1.5 % and the resistors 1.3 % the rail's window is the reference's whole dropout margin |
| PASS | PW-6 | PW-6 | LDO headroom at 5V pin 4.50 V: +LDO (VIN - V+max) and the pump (&#124;CPOUT&#124; - &#124;V-&#124;max) | >= 0.05 V / 0.03 V (dropout at 100 mA, 5.5 VLDO+/-) | 1.08 V / 2.35 V |  | RNEG 2.5 ohm at 100 mA / 5.5 V; 3 ohm assumed at 4.5 V (check) |
| PASS | PW-1 | PW-1 | AFE current from the Due's 5V pin, normal operation, IQ at the datasheet maximum, rails at the strong corner | <= 100 mA | 82.3 mA | +17.7 mA | charge-pump input current = output current + 10 % + IQ 0.39 mA *(check: IQ is a typical, no maximum is given; the datasheet gives no efficiency table in text)*. The AWG's offset path comes from the REF3030E, which the +rail supplies, so it counts on OUT+ either way |
| PASS | PW-1 total | PW-1 | Due (300 mA, D7) + AFE in the worst fault (indefinite short), <= 450 mA | <= 450 mA | 418 mA (117.6 mA AFE) | +32 mA | the short is exempt from the 100 mA, not from the 450 mA total |
| PASS | PW-1/th | PW-1 | LM27762 junction at 85 C ambient, worst state, 5.25 V in, RthJA 62.2 C/W (the datasheet's)  | <= 125 C | 103 C (296 mW) | +22 K | RthJA is the datasheet's JEDEC figure; a real board does better or worse: check |
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
| PASS | SC-9/DC | V2-1, SC-9, VT-20 | AWG stepped between its window ends into 50 ohm: change of a scope reading, settled, the four paths by which a scope on +3.3 V alone still hears the AWG (sum, 1 LSB = 1.73 mV at the input) | <= 2 LSB | 0.207 LSB (largest: the assumed plane return, 0.116 LSB) | +1.79 LSB | the scope is on +3.3 V only (its V- is ground), so the negative rail reaches it only through the shared LM27762: the 5 V feed and the +LDO's line regulation; the paths are the +rail's load regulation, the feed, the shared reference, and the shared return |
| PASS | SC-9/AC | SC-9 | the AWG's 15 mA step on OUT+: peak rail movement by hand (2 x 10 uF at 50 % of nominal, 4 mohm ESR, a 1 us LDO response) = 1.56 mV, through an assumed PSRR 80 dB flat to 10 kHz then -20 dB/dec at 200 kHz | <= 2 LSB | 0.0018 LSB |  | no converged LM27762 step run: hand estimate *(check)* |
| PASS | PW-2/ripple | PW-2, SC-6 | ripple at the +3.3 V rail from this block's LM27762 runs (largest peak-to-peak 0.16 mV), through the assumed PSRR at 2 MHz (-34 dB), at the scope's pin | <= 0.2 mV rms (SC-6) and the rail <= 20 mV (PW-2) | 3.3 uV pk-pk at the pin, 0.16 mV at the rail |  | the model has no LDO loop and under-reads the datasheet (version 1's note); PW-2's 20 mV holds by 30x, SC-6 by 15x on the model's figure *(check, VT-8)* |
| info | PW-2/fsw | PW-2 | switching frequency, the rule: not settable (LM27762 fSW 1.7 to 2.3 MHz, 2 MHz typ at VIN 3.6 V; pulse-skipping below that at light load, the loop 'can drop into the sub-2-kHz range when unloaded', 6.3.3) | stated, with the wide path in mind | line at 2 MHz +-15 %, inside SM-3's 8 MHz band; residue at the pin 3.3 uV |  | the AFE's idle load is never light: the AWG dual alone draws 15 mA on each rail, so the pump runs at constant frequency (a moving sub-2-MHz spur would need a load under a few mA) *(check at the PFM threshold: not given)* |
| PASS | PW-2/AWG | PW-2, AW-6 (D22: 0.3 mV) | ripple at the AWG dual's supply pin with 100 nF + 1 uF at the pin: 0.16 mV pk-pk on OUT+ (TI model) x 0.3; at the AWG output through the op-amp-like PSRR | <= 20 mV at the pin; <= 0.3 mV rms at the output (AW-6, D22) | 0.05 mV pk-pk at the pin, 0.8 uV rms at the output | +299 uV | the model under-reads: a factor 10 more still passes |
| PASS | PW-2/AWG | PW-2, AW-6 (D22: 0.3 mV) | ripple at the AWG dual's supply pin with 100 nF only (1 uF dropped): 0.16 mV pk-pk on OUT+ (TI model) x 1.0; at the AWG output through the op-amp-like PSRR | <= 20 mV at the pin; <= 0.3 mV rms at the output (AW-6, D22) | 0.16 mV pk-pk at the pin, 2.6 uV rms at the output | +297 uV | the model under-reads: a factor 10 more still passes |
| PASS | PW-7 | PW-7 | rails up (this block's LM27762 runs: +rail 90 % at 0.29 ms, -rail 0.50 ms) then the REF3030E's 2 ms to 0.1 %, then the scope node's own RC (about 12 us) | <= 15 s | 2.5 ms |  | PW-7 is met by 3 orders of magnitude by the electrical start-up; what takes seconds is thermal (VT-18), not the rails. The host flags readings not ready until the ADS1115 sees the reference within 0.1 % of its first valid reading |

## 3 and 4. REF3030E roles and the ladder (refladder.py)

| | ID | req | case | limit | result | margin | note |
|---|---|---|---|---|---|---|---|
| PASS | REF/src | PA-2, D-V2-10 | REF3030E source current, every load at once (ladder, both scope centres at -12 V, sense default tie with the AWG at the window bottom, ADS inputs, and the AWG's offset path Rg2 5.95 mA worst, from ../awg/design.md) | <= 10 mA (6.3) | 7.686 mA | +2.31 mA |  |
| PASS | REF/snk | PA-2, D-V2-10 | REF3030E sink current in the clamped-input case: both scope inputs at +12 V (node clamped past the rail) and the AWG forced +5 V through the sense divider (PR-4) | <= 10 mA | 80 uA | +9.92 mA | the sink load regulation 150 ppm/mA is 10x the source figure but at this current moves the output by 0.01 ppm |
| PASS | REF/lreg | SC-7 | the ladder's top tap (= the reference) moves with the AWG level (the sense divider's default tie and the AWG's Rg2 path): change of source current over the sweep x 15 ppm/mA | <= 3.0 mV (0.1 % fit share of 3 V) | 4.305 mA -> 193.7 uV | +2806 uV | the host reads the reference with every tap reading; this is the movement between two readings |
| PASS | REF/signal | SC-7, D-V2-10 | the scope's signal current in the reference the ADS1115 reads: both inputs swept from -12 V to +12 V, 5.4 uA to -1.4 uA each | <= 3.0 mV | 0.49 uV |  |  |
| PASS | REF/dropout | PA-2 | VIN >= VOUT + 0.2 V at the weakest +rail (power.py) | >= 3.200 V | see power.json min_p |  | the rail block's corner, see section 1 |
| info | REF/CL | PA-2 | output capacitor | 0.1..22 uF, ESR 10..500 mohm | 1 uF X5R (C15849) |  | 1 uF C15849 X5R at the output: the datasheet's CL range 0.1..22 uF holds; its ESR window 10..500 mohm is above a ceramic's (a few mohm) *(check: the datasheet states stability with ceramics only by the CL range)* |
| PASS | PA-9/Z | PA-9, SC-10 | tap source impedance against the Due ADC pin leakage 0.5 uA (over temperature): the worst tap (1/2) x 0.5 uA in LSB of 3.3 V / 4096 | <= 0.5 LSB | 495 ohm -> 0.247 mV = 0.31 LSB | +0.19 LSB | tap impedances (ohm): 275, 440, 495, 440, 275 and 0 for the top; all far under SC-10's 5 kohm |
| info | PA-9/I | PW-1 | ladder current from the reference | information | 1.53 mA at REF +0.1 %, rungs -1 % |  |  |
| PASS | PA-9/ads | SC-7 | the ADS1115's input current (V - 0.7 V over Zcm 6 Mohm -25 %, typ only) across the tap impedance, the two measured taps | <= 0.01 % (a tenth of the fit share) | 0.0098 % (1/3 tap), 0.0098 % (2/3 tap) |  | SBAS444E gives the input impedance as a typical only *(check)* |
| info | PA-9/drift | EN-1, VT-12 | a measured tap's fraction of the reference after 10 K since it was read (rungs +-100 ppm/K, opposed): the size of a check's window, not an SC-7 term | information | 0.133 % (1/3 tap), 20 K: 0.267 % | -0.033 % | D-V2-13: the taps are checks, not fit anchors, so their drift no longer enters SC-7 and the 10 K recalibration rule stands; information only. The host can re-read the measured taps at any time (no tee, no AWG), so this is the worst drift between the last read and use, not a calibration interval |
| info | PA-9/unmeas | PA-9 | the three unmeasured taps (1/6, 1/2, 5/6): fraction error from 1 % rungs, 99.9th percentile | information (fault check threshold) | 1.30 %, 0.72 %, 0.26 % |  | so a host fault check on the unmeasured taps uses a window of +-1.5 % of the nominal fraction (derived from this) |
| info | PA-9/dT | EN-1, VT-12 | the temperature change since a tap was read that keeps its drift inside 0.1 % (and inside 0.05 %, the half this design gives the ladder) | information (sets the recalibration threshold, D-V2-3) | 7.5 K (0.05 %: 3.7 K) |  | 10 K (EN-1) fails; the host re-reads the two measured taps at the start and end of each session, so the working figure is the change within one session |

## 5. Sense divider and jumper (sense.py)

| | ID | req | case | limit | result | margin | note |
|---|---|---|---|---|---|---|---|
| PASS | PA-4/range | PA-4 | sweep, wire ON throughout: sense tap pin voltage at every AWG level -1.95..+2.28 V, every resistor at +-1 %, REF +-0.1 % | 0 V .. 3.22 V (ADS supply minimum) | 0.141 .. 1.891 V | +0.141 V / +1.329 V | k = 0.4, bottom node = the 1/3 tap, Rd 1k |
| PASS | PA-4/range-off | PA-4 | the same with the wire OFF (default tie to the REF3030E; the normal-use state) | 0 V .. 3.22 V | 0.881 .. 2.697 V | +0.881 V / +0.523 V |  |
| PASS | PA-4/ratio | PA-4, SC-7 | AWG level through the sweep, structure S3 (input 3 = B with a 10k matched resistor, inputs 2-3 read DIFFERENTIALLY, the reference's scale rebuilt on input 3, no other input's gain enters), ADS1115 channel match 0.1 % max (SBAS444E 5.5 'Gain channel match'), offset 3 LSB, Zcm TRACKING between inputs (one input stage behind the mux) *(check)*, 99.9th pct | gain <= 0.05 %, offset <= 3.0 mV | gain 0.050 %, offset 1.73 mV, worst point 2.38 mV (k error 0.101 %) | +0.000 % | this design's allotment of the 0.1 % fit share |
| **FAIL** | PA-4/ratio-ind | PA-4, SC-7 | the same if Zcm spreads +-25 % INDEPENDENTLY between the inputs (the datasheet gives only a typical 6 Mohm) | gain <= 0.05 %, offset <= 3.0 mV | gain 0.225 %, offset 2.35 mV | -0.175 % | fails the sense's 0.05 % share; it fits inside SC-7's whole 0.5 % with the rest of the stack (section 6), and VT-21 measures which case the part is in |
| info | PA-4/struct | PA-4 | the structures compared (gain %, offset mV, 99.9th pct, channel match 0.1 % max): S1 = tap on input 2, B on input 3 in the wire position only, REF on input 1; S2 = B on input 3 in both positions; S3 without the matched resistor; S3 with it | information | S1 0.484 %/6.8 mV; S2 0.313/2.2; S3 0.160/2.1; S3+rm 0.225/2.4 (Zcm tracking 0.050/1.7) |  | S2 removes the offsets of the ratio (ΔT on one channel, ΔB on one channel); S3 also removes the channel-gain terms (the differential pair and the REF rebuilt on input 3); rm matches the source impedances |
| info | PA-4/load | PA-4 | the loaded ladder tap (1/3): its shift from 1.000 V over the sweep with the wire on | information (not a check point while fitted) | 631 mV at most, wire current up to 118 uA |  | B is read, so the loading is not an error; the 2/3 tap (input 4) and the reference stay readable |
| PASS | VT-22/I | VT-22, PA-4 | any position the header allows (GND, six taps, +3.3 V_A; the Due's 5V and VIN as stress): current into the ADS1115's input diodes, input 2 through Rt&#124;&#124;Rb + 3.9k, input 3 (B) through 10k | <= 10 mA (abs max), host takes no action | 848 uA at most | +9152 uA | series resistors are the only protection (no clamp: the ADS1115's own diodes conduct first); whether the other inputs read undisturbed during an overdrive is not in SBAS444E (7.3.1 warns) *(check, VT-22)* |
| PASS | VT-22/dist | V2-5, VT-22 | every position gives a distinguishable reading: input 3 reads B itself, which is the node's voltage (0, 0.5, ... 3.3 V): smallest gap between positions | >= 20 x the reading resolution (125 uV + 0.1 % of 3 V) | 300 mV gap on input 3 vs 3.12 mV |  | the top tap reads as the default (wire missing or on the top tap): the host stops either way |
| PASS | VT-21/22/det | VT-21, VT-22 | a wire left on after the calibration, or missing at its start: input 3 (B) differs between the two positions at every AWG level and tolerance draw | >= 50 mV (about 16x the reading resolution) | 1230 mV minimum | +1180 mV | left on in normal use the tap stays inside 0.14 .. 1.89 V (PA-4/range) and the 1/3 ladder tap is loaded by up to 118 uA: nothing is damaged, the host's end-of-session reading catches it |
| PASS | D23/time | D21, D23, PA-3 | ADS1115 free-running on the pair, staircase 1.5 to 3 ms a level (D23), 1024 levels: the fit's slope noise from the readings at 860 SPS (1.16 ms) counting only conversions wholly inside a level (0.3 to 1.6 a level); 125 uV rms per conversion x sqrt 2 / k at the AWG node | <= 0.005 % (a tenth of the 0.05 % share) | 0.0021 % at 860 SPS; 0.0026 % at the worst of 128 to 860 SPS |  | no averaging per level is needed: one reading per level or less, the fit averages 300 to 1600 of them; the quantisation of a 125 uV code is spread over levels that each move the pair by 13 codes. At 128 SPS (7.8 ms) one conversion spans 3 to 5 levels: aligned by time stamp it is a boxcar of the staircase and the Due codes are averaged over the same window |
| info | D23/total | D23, PA-3 | total staircase time: 1024 levels x 1.5 to 3 ms, plus the two end readings of B and the wire-off ratio readings (64 conversions at 860 SPS each, 4 of them) | information | 1.5 to 3.1 s staircase + 0.30 s of readings + channel switches |  | staircase only; warm-up is separate. The ratio readings are static levels and are not bounded by D23's step |
| PASS | CAL/clip | D23, AW-1 | the sweep drops any level whose reading stops following the DAC code (the AWG clips about 5 to 10 mV above the weak -rail -1.955 V, from -1.923 V down): slope of the pair over the last 3 levels < 0.5 x the sweep's median slope | the clipped levels dropped, the fit unchanged | first dropped level -1.950 V, 6 of 1025 dropped, bottom of the kept range -1.926 V, fit gain error -0.0002 % |  | cost: the sweep's bottom moves from -1.95 to about -1.92 V (the window bottom is -1.9 to -1.68 V): it still covers the scope's -1.5 V end, so the coverage of -1.5..+3.5 V does not change; the margin below -1.5 V shrinks by about 30 mV |

## 6. ADS1115 and SC-7, the extrapolation (sc7.py)

| | ID | req | case | limit | result | margin | note |
|---|---|---|---|---|---|---|---|
| PASS | SC-7/ext | SC-7, PA-3, VT-23 | fit extrapolated to +3.5 V (AWG window -1.9 .. 2.05 V covers 71 % of the range), INL cubic 0.5 LSB, 1024 points: A = the tee fit alone (the design, D-V2-13), B = with ladder anchors (information only, NOT used), 99.9th pct | <= 3.5 mV (0.1 % of 3.5 V) | A 0.27 mV (0.008 %), B 3.45 mV (0.099 %) | A +3.2 / B +0.0 mV | B passes the share; against SC-7's whole 0.5 % + 5 mV = 22.5 mV both leave 19.0 mV. One Due LSB is 1.73 mV at the input |
| PASS | SC-7/ext | SC-7, PA-3, VT-23 | fit extrapolated to +3.5 V (AWG window -1.9 .. 2.05 V covers 71 % of the range), INL cubic 1.2 LSB, 1024 points: A = the tee fit alone (the design, D-V2-13), B = with ladder anchors (information only, NOT used), 99.9th pct | <= 3.5 mV (0.1 % of 3.5 V) | A 0.64 mV (0.018 %), B 4.14 mV (0.118 %) | A +2.9 / B -0.6 mV | B fails the share; against SC-7's whole 0.5 % + 5 mV = 22.5 mV both leave 18.4 mV. One Due LSB is 1.73 mV at the input |
| PASS | SC-7/ext | SC-7, PA-3, VT-23 | fit extrapolated to +3.5 V (AWG window -1.9 .. 2.05 V covers 71 % of the range), INL parab 1.2 LSB, 1024 points: A = the tee fit alone (the design, D-V2-13), B = with ladder anchors (information only, NOT used), 99.9th pct | <= 3.5 mV (0.1 % of 3.5 V) | A 1.76 mV (0.050 %), B 3.29 mV (0.094 %) | A +1.7 / B +0.2 mV | B passes the share; against SC-7's whole 0.5 % + 5 mV = 22.5 mV both leave 19.2 mV. One Due LSB is 1.73 mV at the input |
| PASS | SC-7/ext | SC-7, PA-3, VT-23 | fit extrapolated to +3.5 V (AWG window -1.9 .. 2.05 V covers 71 % of the range), INL knots 1.2 LSB, 1024 points: A = the tee fit alone (the design, D-V2-13), B = with ladder anchors (information only, NOT used), 99.9th pct | <= 3.5 mV (0.1 % of 3.5 V) | A 2.28 mV (0.065 %), B 5.68 mV (0.162 %) | A +1.2 / B -2.2 mV | B fails the share; against SC-7's whole 0.5 % + 5 mV = 22.5 mV both leave 16.8 mV. One Due LSB is 1.73 mV at the input |
| PASS | SC-7/ext | SC-7, PA-3, VT-23 | fit extrapolated to +3.5 V (AWG window -1.9 .. 2.2275 V covers 75 % of the range), INL cubic 0.5 LSB, 1024 points: A = the tee fit alone (the design, D-V2-13), B = with ladder anchors (information only, NOT used), 99.9th pct | <= 3.5 mV (0.1 % of 3.5 V) | A 0.26 mV (0.008 %), B 3.28 mV (0.094 %) | A +3.2 / B +0.2 mV | B passes the share; against SC-7's whole 0.5 % + 5 mV = 22.5 mV both leave 19.2 mV. One Due LSB is 1.73 mV at the input |
| PASS | SC-7/ext | SC-7, PA-3, VT-23 | fit extrapolated to +3.5 V (AWG window -1.9 .. 2.2275 V covers 75 % of the range), INL cubic 1.2 LSB, 1024 points: A = the tee fit alone (the design, D-V2-13), B = with ladder anchors (information only, NOT used), 99.9th pct | <= 3.5 mV (0.1 % of 3.5 V) | A 0.63 mV (0.018 %), B 4.01 mV (0.115 %) | A +2.9 / B -0.5 mV | B fails the share; against SC-7's whole 0.5 % + 5 mV = 22.5 mV both leave 18.5 mV. One Due LSB is 1.73 mV at the input |
| PASS | SC-7/ext | SC-7, PA-3, VT-23 | fit extrapolated to +3.5 V (AWG window -1.9 .. 2.2275 V covers 75 % of the range), INL parab 1.2 LSB, 1024 points: A = the tee fit alone (the design, D-V2-13), B = with ladder anchors (information only, NOT used), 99.9th pct | <= 3.5 mV (0.1 % of 3.5 V) | A 1.64 mV (0.047 %), B 3.06 mV (0.087 %) | A +1.9 / B +0.4 mV | B passes the share; against SC-7's whole 0.5 % + 5 mV = 22.5 mV both leave 19.4 mV. One Due LSB is 1.73 mV at the input |
| PASS | SC-7/ext | SC-7, PA-3, VT-23 | fit extrapolated to +3.5 V (AWG window -1.9 .. 2.2275 V covers 75 % of the range), INL knots 1.2 LSB, 1024 points: A = the tee fit alone (the design, D-V2-13), B = with ladder anchors (information only, NOT used), 99.9th pct | <= 3.5 mV (0.1 % of 3.5 V) | A 2.25 mV (0.064 %), B 5.33 mV (0.152 %) | A +1.2 / B -1.8 mV | B fails the share; against SC-7's whole 0.5 % + 5 mV = 22.5 mV both leave 17.2 mV. One Due LSB is 1.73 mV at the input |
| info | SC-7/ext-ideal | SC-7 | the same (cubic 1.2 LSB, top 2.2275 V) with perfect anchors (no ADS channel mismatch, no offset, no pin offset) | information | A 0.63 mV, B 1.93 mV at +3.5 V |  | what the four-anchor quadratic estimator would give with exact ADS readings: still worse than the tee fit for cubic and random-knot INL (review.md section 2); only a parabolic INL favours it. The estimator, not only the ADS1115, loses |
| PASS | SC-7/sum | SC-7 | this block's gain terms alone, linear sum (RSS in the note), and its offset, against ±0.5 % of reading ± 5 mV | <= 0.5 % and <= 5 mV for the WHOLE of SC-7 (the scope's own terms come on top) | 0.42 % (RSS 0.27 %), 2.4 mV | +0.08 % | the sense chain still dominates; with Zcm tracking between inputs it is 0.05 % and 1.8 mV and the sum 0.25 %. The ladder's drift is not a term (D-V2-13) |
| PASS | SC-7/noise | SC-7 | ADS1115 noise averaged over 64 conversions, referred to the AWG node through k = 0.4 (125 uV rms per reading, Table 6-1) | <= 1 mV | 39 uV rms |  | the table's figure equals one LSB: the converter is quantisation-limited, so averaging reduces it only if the input noise dithers it; the worst case without dither is 0.5 LSB = 156 uV at the node |

## Rails, corners (power.py)

| | V |
|---|---|
| max_n | 2.0530 |
| max_p | 3.4177 |
| min_n | 1.9544 |
| min_p | 3.2200 |
| nom_n | 2.0032 |
| nom_p | 3.3176 |

R3 options (R1 120k, R2 68k, R4 100k fixed): the negative rail against the rating margin

| R3 | nominal | min | max | sum with the +rail max | rating margin |
|---|---|---|---|---|---|
| 62.2k | 1.9788 | 1.9309 | 2.0277 | 5.4454 | +55 mV |
| 64.2k | 2.0032 | 1.9544 | 2.0530 | 5.4707 | +29 mV |
| 66.0k | 2.0252 | 1.9756 | 2.0758 | 5.4935 | +7 mV |
| 68.0k | 2.0496 | 1.9991 | 2.1011 | 5.5188 | -19 mV |

PW-1 states (IQ at the datasheet maximum; I in mA)

| state | +rail V | OUT+ | OUT- | 5V pin | op-amp output |
|---|---|---|---|---|---|
| normal, AWG hi-Z at the window top | 3.418 | 34.5 | 15.8 | 52.3 | -0.8 |
| normal, AWG hi-Z at the window top | 3.220 | 34.4 | 15.8 | 52.2 | -0.8 |
| normal, AWG into 50 ohm at the window top | 3.418 | 56.2 | 15.0 | 73.1 | +21.6 |
| normal, AWG into 50 ohm at the window top | 3.220 | 56.1 | 15.0 | 72.9 | +21.6 |
| normal, AWG into 50 ohm at the window bottom | 3.418 | 38.9 | 39.1 | 82.3 | -24.1 |
| normal, AWG into 50 ohm at the window bottom | 3.220 | 38.8 | 39.1 | 82.2 | -24.1 |
| normal, AWG hi-Z at the window bottom | 3.418 | 38.9 | 20.0 | 61.3 | -5.0 |
| normal, AWG hi-Z at the window bottom | 3.220 | 38.8 | 20.0 | 61.2 | -5.0 |
| fault: BNC shorted, DAC at the window top | 3.418 | 78.7 | 15.0 | 95.6 | +44.2 |
| fault: BNC shorted, DAC at the window top | 3.220 | 78.6 | 15.0 | 95.5 | +44.2 |
| fault: BNC shorted, DAC at the window bottom | 3.418 | 38.9 | 58.4 | 103.6 | -43.4 |
| fault: BNC shorted, DAC at the window bottom | 3.220 | 38.8 | 58.4 | 103.5 | -43.4 |
| fault: BNC shorted, DAC at the 3.3 V reset level (output clips about 0.1 V under the rail) | 3.418 | 100.7 | 15.0 | 117.6 | +67.3 |
| fault: BNC shorted, DAC at the 3.3 V reset level (output clips about 0.1 V under the rail) | 3.220 | 100.6 | 15.0 | 117.5 | +67.3 |

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
| wire on throughout, max channel match 0.1 % | 0.225 | 2.35 | 6.21 | 0.195 |
| typical channel match 0.05 % | 0.225 | 2.35 | 6.20 | 0.156 |
| no channel mismatch | 0.225 | 2.35 | 6.19 | 0.131 |
| wire off throughout (information) | 0.445 | 6.59 | 14.25 | 0.368 |

Structures compared (99.9th percentile, ADS1115 channel match 0.1 % max, offset 3 LSB)

| structure | gain % | offset mV |
|---|---|---|
| S1: tap on input 2, B on input 3 in the wire position only, REF on input 1 | 0.484 | 6.84 |
| S2: B on input 3 in both positions | 0.313 | 2.23 |
| S3: input 3 = B, inputs 2-3 differential, REF scale rebuilt on input 3 | 0.160 | 2.14 |
| S3 + 10k matched resistor on input 3 (Zcm independent per input) | 0.225 | 2.35 |
| S3 + matched resistor, Zcm tracking between inputs | 0.050 | 1.73 |

Ablation of the shipped models (20,000 draws, 99.9th percentile; S3 = the design with 10k on input 3, Zcm independent per input; S1 = the first structure)

| case | S3 gain % | S3 offset mV | S1 gain % | S1 offset mV |
|---|---|---|---|---|
| 1 % resistors only | 0.035 | 0.03 | 0.071 | 1.16 |
| Zcm spread only | 0.212 | 1.24 | 0.136 | 0.94 |
| base (as shipped) | 0.225 | 2.35 | 0.484 | 6.84 |
| channel match only | 0.010 | 0.00 | 0.379 | 5.04 |
| no ADS offsets | 0.222 | 1.54 | 0.455 | 6.01 |
| no INL | 0.224 | 2.20 | 0.474 | 6.80 |
| no Zcm spread | 0.050 | 1.58 | 0.422 | 6.72 |
| no channel mismatch | 0.225 | 2.35 | 0.236 | 3.74 |
| no noise | 0.222 | 2.33 | 0.484 | 6.84 |
| no resistor tolerance | 0.216 | 2.34 | 0.470 | 6.80 |
| offsets only | 0.022 | 1.28 | 0.092 | 2.63 |

ADS1115 timing per level (D23: staircase 1.5 to 3 ms a level, free-running on the pair)

| DR | conversion ms | step ms | conversions per level | whole inside a level | fit slope noise % | staircase s |
|---|---|---|---|---|---|---|
| 128 | 7.81 | 1.5 | 0.19 | 0.00 | 0.0026 | 1.54 |
| 128 | 7.81 | 3.0 | 0.38 | 0.00 | 0.0018 | 3.07 |
| 250 | 4.00 | 1.5 | 0.38 | 0.00 | 0.0019 | 1.54 |
| 250 | 4.00 | 3.0 | 0.75 | 0.00 | 0.0013 | 3.07 |
| 475 | 2.11 | 1.5 | 0.71 | 0.00 | 0.0014 | 1.54 |
| 475 | 2.11 | 3.0 | 1.43 | 0.43 | 0.0018 | 3.07 |
| 860 | 1.16 | 1.5 | 1.29 | 0.29 | 0.0021 | 1.54 |
| 860 | 1.16 | 3.0 | 2.58 | 1.58 | 0.0009 | 3.07 |

Every header position (B tied to node X by the wire; T0 over the AWG sweep -1.95..+2.28 V; dT = change of the tap against the wire-off reading)

| node | X V | T0 min | T0 max | current into ADS diodes uA | wire current uA |
|---|---|---|---|---|---|
| GND | 0.0 | -0.780 | 0.912 | 48 (input 3: 0) | 91 |
| tap1 (1/6) | 0.5 | -0.480 | 1.212 | 18 (input 3: 0) | 98 |
| tap2 (1/3, ADS input 3): the RIGHT position | 1.0 | -0.180 | 1.512 | 0 (input 3: 0) | 118 |
| tap3 (1/2) | 1.5 | 0.120 | 1.812 | 0 (input 3: 0) | 138 |
| tap4 (2/3, ADS input 4 (a check only)) | 2.0 | 0.420 | 2.112 | 0 (input 3: 0) | 158 |
| tap5 (5/6) | 2.5 | 0.720 | 2.412 | 0 (input 3: 0) | 178 |
| tap6 = REF (same as wire off) | 3.0 | 1.020 | 2.712 | 0 (input 3: 0) | 198 |
| +3.3 V_A | 3.3 | 1.200 | 2.892 | 0 (input 3: 0) | 210 |
| Due 5V pin (stress) | 5.0 | 2.220 | 3.912 | 40 (input 3: 148) | 278 |
| Due VIN (stress) | 12.0 | 6.420 | 8.112 | 464 (input 3: 848) | 558 |

## SC-7 sum of this block (sc7.py)

| term | gain % | offset mV |
|---|---|---|
| REF3030E: initial 0.1 %, 15 ppm/K x 10 K, hysteresis 100 ppm, long-term 40 ppm | 0.129 | 0.0 |
| AWG sense chain, structure S3, Zcm spreading independently (the conservative case), 99.9th pct | 0.225 | 2.4 |
| Due-ADC tee fit extrapolated to +3.5 V (random-knot INL 1.2 LSB, the worst model, window top 2.2275 V; ladder anchors NOT used, D-V2-13) | 0.064 | 0.0 |
| **linear sum (RSS)** | **0.42 (0.27)** | **2.4** |

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
| G-tapcheck | the measured-tap fault check (window 1.5 % + 10 K drift) must flag a tap 5 % off | fails | passes | ok |
| G-clip | the clip check with the slope criterion disabled (threshold 0) must fail | fails | passes | ok |
| G-struct | the ratio check applied to the old structure S1 must fail; S3 with the matched resistor passes (Zcm tracking) | fails | passes | ok |
| G-range | tap range with k = 0.6 (tap goes below ground at the window bottom) must fail | fails | passes | ok |
| G-ratio | ratio accuracy with a 2 % channel match must fail a 1.5 % gain limit (the designed 0.1 % match passes it) | fails | passes | ok |
| G-distinct | distinguishability with k = 0.995 (wire barely moves the tap) must fail | fails | passes | ok |
| G-current | ESD current check with the limit lowered to 10 uA must fail | fails | passes | ok |
| G-ext | the extrapolation check with an INL of 12 LSB must fail the 0.1 % share | fails | passes | ok |
| G-sum | the SC-7 sum check against a 0.5 % limit with the sense chain's error multiplied by 3 must fail (the real sum passes the same 0.5 %) | fails | passes | ok |
| G-basic | an Extended passive (C861163) in the list must be refused | fails | passes | ok |
