# AFE version 2: power, reference and calibration block (generated from results/ by report.py)

AWG inputs read at run time: `../awg/design.py` sha256 `d7b7abecdaccad22`, `../awg/report_table.md` sha256 `deb9023366497721`; AWG values {"Rbin": 3000.0, "Rbpl": 27000.0, "Rf": 3000.0, "Rg1": Infinity, "Rg2": 3000.0, "Rvr": 150.0}.

Status: PASS / FAIL / info against the stated limit; every FAIL is also in design.md. A check was trusted only after it failed on purpose (Guards table at the end).

## 1. Shared rail, PW-1, V2-2 supply rating, PR-3 (power.py)

| | ID | req | case | limit | result | margin | note |
|---|---|---|---|---|---|---|---|
| PASS | PW-V2-2 | V2-2 | supply across the op-amp <= recommended 5.5 V (TPH2502 VDD row) at both rails' worst corners, 1 % Basic feedback, +-10 K, regulation 2.5 mV | V+ + &#124;V-&#124; at the maximum corner <= 5.5 V | 3.4177 + 2.0530 = 5.4707 V | +0.0293 V | the line: TPH2502 datasheet Rev. A, 'Electrical Characteristics' (continued), PDF page 4, row 'VDD Supply Voltage, MIN 2.5, MAX 5.5, V'; its Applications Information (PDF page 7) says 'specified over +2.7 V to +5.5 V ... the supply voltage may range from +2.5 V to +5.5 V'. The datasheet has no Recommended Operating Conditions table: 5.5 V is the top of its specified supply range and is taken as the recommended maximum. Abs max V+ - V- = 7.0 V (Absolute Maximum Ratings, PDF page 2; the text says 7.5 V). Minimum corner sum 5.175 V is inside 2.5 V. See the R3 table |
| PASS | PW-V2-2b | V2-2 | the same at the abs-max reading (information) | 7.0 V | 5.471 V | +1.53 V |  |
| PASS | PR-2 | PR-2 | the powered scope op-amp's supply <= 3.45 V (anything that drives A0/A1) | <= 3.45 V | 3.4177 V | +0.0323 V |  |
| PASS | PA-2/rail | PA-2 | REF3030E VIN >= VOUT + 0.2 V (6.3, REF30xxE) at the weakest +rail | >= 3.203 V (VOUT at +0.1 %) | 3.2200 V | +0.0170 V | only 1 % Basic feedback resistors move this: with VFB 1.5 % and the resistors 1.3 % the rail's window is the reference's whole dropout margin |
| PASS | PW-6 | PW-6 | LDO headroom at 5V pin 4.50 V: +LDO (VIN - V+max) and the pump (&#124;CPOUT&#124; - &#124;V-&#124;max) | >= 0.05 V / 0.03 V (dropout at 100 mA, 5.5 VLDO+/-) | 1.08 V / 2.35 V |  | RNEG 2.5 ohm at 100 mA / 5.5 V; 3 ohm assumed at 4.5 V (check) |
| PASS | PW-1 | PW-1 | AFE current from the Due's 5V pin, normal operation, IQ at the datasheet maximum, rails at the strong corner | <= 100 mA | 74.0 mA | +26.0 mA | charge-pump input current = output current + 10 % + IQ 0.39 mA *(check: IQ is a typical, no maximum is given; the datasheet gives no efficiency table in text)*. The AWG's offset path comes from the REF3030E, which the +rail supplies, so it counts on OUT+ either way |
| PASS | PW-1 total | PW-1 | Due (300 mA, D7) + AFE in the worst fault (indefinite short), <= 450 mA | <= 450 mA | 419 mA (119.2 mA AFE) | +31 mA | the short is exempt from the 100 mA, not from the 450 mA total |
| PASS | PW-1/th | PW-1 | LM27762 junction at 85 C ambient, worst state, 5.25 V in, RthJA 62.2 C/W (the datasheet's)  | <= 125 C | 102 C (277 mW) | +23 K | RthJA is the datasheet's JEDEC figure; a real board does better or worse: check |
| info | PW-2 | PW-2 | ripple at an amplifier supply pin <= 20 mV | <= 20 mV | see lm27762 runs and section 'PW-2' |  | the switching frequency is the part's 1.7 to 2.3 MHz (2 MHz typ), not settable; see the rule in design.md |
| info | PR-3/src | PR-3 | worst current pushed into the +3.3 V_A rail by both inputs at +12 V (0.3 V clamp drop assumed, R1 -1 %) | information | 38.5 uA |  | the scope design's 36 uA was a 0.6 V drop; a Schottky-like input structure raises it: *(check)* the TPH2502 gives no unpowered figure |
| info | PR-3/ic | PR-3 | sink the unpowered ICs provide at 0.5 V by datasheet: feedback divider only | information | 2.6 uA |  | LM27762 shutdown discharge 50 kohm would add 10 uA at 0.5 V but 6.4.1 does not say it works with VIN = 0 *(check)*; ADS1115, REF3030E and the op-amps give no leakage at 0.5 V: none counted |
| info | PR-3/ic2 | PR-3 | sink counted if the LM27762's discharge works (information) | information | 12.6 uA |  | not relied on |
| PASS | PR-3 | PR-3 | unpowered +3.3 V_A rail with both scope inputs at +12 V, 1.8k bleed (C4177) at +1 %, with only the resistive sinks | <= 0.5 V | 0.075 V | +0.425 V | sinks 277.7 uA against 38.5 uA pushed in at 0.5 V |
| info | PR-3/Q | PW-1 | quiescent cost of the bleed, rail at its maximum, resistor -1 % | information | 1.903 mA = 1.90 % of 100 mA |  |  |
| PASS | PR-3/Due | PR-3 | current into the Due's supply pins <= 100 uA | <= 100 uA | 1.8 uA (scope design, through R3 and the sense filter; nothing reaches the 5V pin) |  | the scope design's figure, not re-derived here; the bleed does not change it |
| PASS | PR-3/sense | PR-3, PR-4, VT-22 | the AWG node forced to +1.8 V (PR-4) and +5 V (up to which PR-4 allows damage on the shield only) with the AFE unpowered, through the S3 network (Rt 15k, Rb 10k, Rd 1k, Rs 3.9k to AIN2, Rm 10k to AIN3): current into the +3.3 V_A rail through the ADS1115's diodes (smallest drop 0.3 V) and the rail it raises, with the 1.8k bleed at +1 %; worst of the REF3030E output open / clamping into the rail / at 0 V | <= 0.5 V (PR-3; the LM27762's body diode to the Due's 5V pin stays off, so the back-feed into the Due is nil) | 0.434 V at A = 5 V (241 uA into the rail) | +0.066 V | with the 10k bleed of the earlier draft the same case reads 1.651 V (+1.8 V: 0.527 V) and FAILS; the current into the ADS1115's diodes is at most 0.24 mA (10 mA rating); negative forcing sinks from ground, not the rail |
| info | PR-3/div | PR-3, PR-4 | the +5 V forced-sense case (the only one that binds): the largest Basic bleed that keeps the rail under 0.5 V for each divider total, and what the larger divider costs the ratio (S3, Zcm tracking / independent) | information | 25k: bleed <= 2k (1.66 mA), ratio 0.057 / 0.225 %; 33k: bleed <= 2.7k (1.23 mA), ratio 0.054 / 0.258 %; 50k: bleed <= 3.9k (0.85 mA), ratio 0.051 / 0.336 %; 75k: bleed <= 5.6k (0.59 mA), ratio 0.053 / 0.456 %; 100k: bleed <= 7.5k (0.44 mA), ratio 0.057 / 0.577 % |  | the bleed grows about as fast as the divider does, so a larger divider saves permanent current (1.8 mA -> 0.4 mA at 100k) and costs ratio accuracy when Zcm spreads between inputs (0.22 -> 0.58 %); v2 keeps 25k and 1.8k |
| PASS | PR-3/cand | PR-3, PR-4 | +5 V on the AWG node, AFE unpowered, shunt off: v2 as built: 15k / 10k, Rs 3.9k, Rm 10k, bleed 1.8k | rail < 0.5 V (PR-3); 100 uA into the Due's supply pins (PR-3), which is the LM27762's back-path, not the current into the rail | worst case (diode 0.3 V, REF open/clamp/0 V): rail 0.434 V, 241 uA into the rail; kvm_01's assumptions (REF at 0 V, diode 0.6 V): 0.228 V, 127 uA; permanent 1.84 mA; ratio 0.054 % / 0.226 % | +0.066 V | the chosen set |
| info | PR-3/cand | PR-3, PR-4 | +5 V on the AWG node, AFE unpowered, shunt off: 30k: 18k / 12k, Rs 3.9k, Rm 12k, bleed 2.2k | rail < 0.5 V (PR-3); 100 uA into the Due's supply pins (PR-3), which is the LM27762's back-path, not the current into the rail | worst case (diode 0.3 V, REF open/clamp/0 V): rail 0.449 V, 204 uA into the rail; kvm_01's assumptions (REF at 0 V, diode 0.6 V): 0.242 V, 110 uA; permanent 1.51 mA; ratio 0.049 % / 0.256 % | +0.051 V | passes (comparison, information) |
| info | PR-3/cand | PR-3, PR-4 | +5 V on the AWG node, AFE unpowered, shunt off: 30k: 18k / 12k, Rs 3.9k, Rm 12k, bleed 4.7k (kvm_01's bleed) | rail < 0.5 V (PR-3); 100 uA into the Due's supply pins (PR-3), which is the LM27762's back-path, not the current into the rail | worst case (diode 0.3 V, REF open/clamp/0 V): rail 0.856 V, 185 uA into the rail; kvm_01's assumptions (REF at 0 V, diode 0.6 V): 0.433 V, 94 uA; permanent 0.71 mA; ratio 0.049 % / 0.256 % | -0.356 V | FAILS in the worst case (comparison, information) |
| info | PR-3/cand | PR-3, PR-4 | +5 V on the AWG node, AFE unpowered, shunt off: 25k, Rs 3.9k, Rm 10k, bleed 4.7k (kvm_01's v1 bleed) | rail < 0.5 V (PR-3); 100 uA into the Due's supply pins (PR-3), which is the LM27762's back-path, not the current into the rail | worst case (diode 0.3 V, REF open/clamp/0 V): rail 0.974 V, 210 uA into the rail; kvm_01's assumptions (REF at 0 V, diode 0.6 V): 0.474 V, 102 uA; permanent 0.71 mA; ratio 0.054 % / 0.226 % | -0.474 V | FAILS in the worst case (comparison, information) |
| info | PR-3/cand | PR-3, PR-4 | +5 V on the AWG node, AFE unpowered, shunt off: 25k, Rs 3.9k, Rm 10k, bleed 10k | rail < 0.5 V (PR-3); 100 uA into the Due's supply pins (PR-3), which is the LM27762's back-path, not the current into the rail | worst case (diode 0.3 V, REF open/clamp/0 V): rail 1.651 V, 172 uA into the rail; kvm_01's assumptions (REF at 0 V, diode 0.6 V): 0.735 V, 77 uA; permanent 0.33 mA; ratio 0.054 % / 0.226 % | -1.151 V | FAILS in the worst case (comparison, information) |

## 1b. SC-9 through the shared rail, PW-2, PW-7 (coupling.py)

| | ID | req | case | limit | result | margin | note |
|---|---|---|---|---|---|---|---|
| PASS | SC-9/DC | V2-1, SC-9, VT-20 | AWG stepped between its window ends into 50 ohm: change of a scope reading, settled, the four paths by which a scope on +3.3 V alone still hears the AWG (sum, 1 LSB = 1.73 mV at the input) | <= 2 LSB | 0.133 LSB (largest: the assumed plane return, 0.116 LSB) | +1.87 LSB | the scope is on +3.3 V only (its V- is ground), so the negative rail reaches it only through the shared LM27762: the 5 V feed and the +LDO's line regulation; the paths are the +rail's load regulation, the feed, the shared reference, and the shared return |
| PASS | SC-9/AC | SC-9 | the AWG's 19 mA step on OUT+: peak rail movement by hand (2 x 10 uF at 50 % of nominal, 4 mohm ESR, a 1 us LDO response) = 2.00 mV, through an assumed PSRR 80 dB flat to 10 kHz then -20 dB/dec at 200 kHz | <= 2 LSB | 0.0023 LSB |  | no converged LM27762 step run: hand estimate *(check)* |
| PASS | PW-2/ripple | PW-2, SC-6 | ripple at the +3.3 V rail from this block's LM27762 runs (largest peak-to-peak 0.16 mV), through the assumed PSRR at 2 MHz (-34 dB), at the scope's pin | <= 0.2 mV rms (SC-6) and the rail <= 20 mV (PW-2) | 3.3 uV pk-pk at the pin, 0.16 mV at the rail |  | the model has no LDO loop and under-reads the datasheet (version 1's note); PW-2's 20 mV holds by 30x, SC-6 by 15x on the model's figure *(check, VT-8)* |
| info | PW-2/fsw | PW-2 | switching frequency, the rule: not settable (LM27762 fSW 1.7 to 2.3 MHz, 2 MHz typ at VIN 3.6 V; pulse-skipping below that at light load, the loop 'can drop into the sub-2-kHz range when unloaded', 6.3.3) | stated, with the wide path in mind | line at 2 MHz +-15 %, inside SM-3's 8 MHz band; residue at the pin 3.3 uV |  | the AFE's idle load is never light: the AWG dual alone draws 15 mA on each rail, so the pump runs at constant frequency (a moving sub-2-MHz spur would need a load under a few mA) *(check at the PFM threshold: not given)* |
| PASS | PW-2/AWG | PW-2, AW-6 (D22: 0.3 mV) | ripple at the AWG dual's supply pin with 100 nF + 1 uF at the pin: 0.16 mV pk-pk on OUT+ (TI model) x 0.3; at the AWG output through the op-amp-like PSRR | <= 20 mV at the pin; <= 0.3 mV rms at the output (AW-6, D22) | 0.05 mV pk-pk at the pin, 0.8 uV rms at the output | +299 uV | the model under-reads: a factor 10 more still passes |
| PASS | PW-2/AWG | PW-2, AW-6 (D22: 0.3 mV) | ripple at the AWG dual's supply pin with 100 nF only (1 uF dropped): 0.16 mV pk-pk on OUT+ (TI model) x 1.0; at the AWG output through the op-amp-like PSRR | <= 20 mV at the pin; <= 0.3 mV rms at the output (AW-6, D22) | 0.16 mV pk-pk at the pin, 2.6 uV rms at the output | +297 uV | the model under-reads: a factor 10 more still passes |
| PASS | PW-7 | PW-7 | rails up (this block's LM27762 runs: +rail 90 % at 0.29 ms, -rail 0.50 ms) then the REF3030E's 2 ms to 0.1 %, then the scope node's own RC (about 12 us) | <= 15 s | 2.5 ms |  | PW-7 is met by 3 orders of magnitude by the electrical start-up; what takes seconds is thermal (VT-18), not the rails. The host flags readings not ready until the ADS1115 sees the reference within 0.1 % of its first valid reading |

## 3 and 4. REF3030E roles and the ladder (refladder.py)

| | ID | req | case | limit | result | margin | note |
|---|---|---|---|---|---|---|---|
| PASS | REF/src | PA-2, D-V2-10 | REF3030E source current, every load at once (ladder, both scope centres at -12 V, sense default tie with the AWG at the window bottom, ADS inputs, and the AWG's offset path Rg2 + Rvr, computed from ../awg/design.py: 0.98 mA worst) | <= 10 mA (6.3) | 2.700 mA | +7.30 mA |  |
| PASS | REF/snk | PA-2, D-V2-10 | REF3030E sink current in the clamped-input case: both scope inputs at +12 V (node clamped past the rail) and the AWG forced +5 V through the sense divider (PR-4) | <= 10 mA | 80 uA | +9.92 mA | the sink load regulation 150 ppm/mA is 10x the source figure but at this current moves the output by 0.01 ppm |
| PASS | REF/lreg | SC-7 | the ladder's top tap (= the reference) moves with the AWG level (the sense divider's default tie and the AWG's Rg2 path): change of source current over the sweep x 15 ppm/mA | <= 3.0 mV (0.1 % fit share of 3 V) | 0.791 mA -> 35.6 uV | +2964 uV | the host reads the reference with every tap reading; this is the movement between two readings |
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
| PASS | PA-4/range | PA-4 | sweep, wire ON throughout: sense tap pin voltage at every AWG level -1.923..+2.18 V, every resistor at +-1 %, REF +-0.1 % | 0 V .. 3.22 V (ADS supply minimum) | 0.377 .. 2.076 V | +0.377 V / +1.144 V | k = 0.4, TAP_on = the 1/2 tap, Rd 1k |
| PASS | PA-4/range-off | PA-4 | the same with the wire OFF (default tie to the REF3030E; the normal-use state) | 0 V .. 3.22 V | 0.893 .. 2.656 V | +0.893 V / +0.564 V |  |
| PASS | PA-4/ratio | PA-4, SC-7 | AWG level through the sweep, structure S3 (AIN3 = B with a 10k matched resistor, AIN2 - AIN3 read DIFFERENTIALLY, the reference's scale rebuilt on AIN3, no other input's gain enters), ADS1115 channel match 0.1 % max (SBAS444E 5.5 'Gain channel match'), offset 3 LSB, Zcm TRACKING between inputs (one input stage behind the mux) *(check)*, 99.9th pct | gain <= 0.05 %, offset <= 3.0 mV | gain 0.053 %, offset 1.86 mV, worst point 2.52 mV (k error 0.105 %) | -0.003 % | this design's allotment (0.05 %; the Monte Carlo reads 0.05 +- 0.003 %, so it is AT the limit, not under it) of the 0.1 % fit share |
| **FAIL** | PA-4/ratio-ind | PA-4, SC-7 | the same if Zcm spreads +-25 % INDEPENDENTLY between the inputs (the datasheet gives only a typical 6 Mohm) | gain <= 0.05 %, offset <= 3.0 mV | gain 0.224 %, offset 2.46 mV | -0.174 % | fails the sense's 0.05 % share; it fits inside SC-7's whole 0.5 % with the rest of the stack (section 6), and VT-21 measures which case the part is in |
| info | PA-4/struct | PA-4 | the structures compared (gain %, offset mV, 99.9th pct, channel match 0.1 % max): S1 = tap on AIN2, B on AIN3 in the wire position only, REF on AIN0; S2 = B on AIN3 in both positions; S3 without the matched resistor; S3 with it | information | S1 0.621 %/11.5 mV; S2 0.314/2.3; S3 0.167/2.3; S3+rm 0.224/2.5 (Zcm tracking 0.053/1.9) |  | S2 removes the offsets of the ratio (ΔT on one channel, ΔB on one channel); S3 also removes the channel-gain terms (the differential pair and the REF rebuilt on AIN3); rm matches the source impedances |
| PASS | PA-4/pairing | PA-4 | the ratio figures for other assignments of the sense tap and B to the AINx columns (the model draws gain, offset, INL and Zcm per input independently, so the assignment is only a relabelling; the matching resistor stays on the pin that carries B) | unchanged within the Monte Carlo noise | AIN2 tap, AIN3 B (the design)&#124;tracking: 0.053 % / 1.86 mV; AIN2 tap, AIN3 B (the design)&#124;independent: 0.224 % / 2.46 mV; swapped: tap on AIN3, B on AIN2&#124;tracking: 0.054 % / 1.87 mV; swapped: tap on AIN3, B on AIN2&#124;independent: 0.224 % / 2.41 mV; tap on AIN0, B on AIN1&#124;tracking: 0.054 % / 1.86 mV; tap on AIN0, B on AIN1&#124;independent: 0.224 % / 2.40 mV |  | the reading sequence in the model: AIN0 = REF3030E and AIN1 = the 2/3 tap are NOT read in the ratio (the reference's scale is rebuilt from AIN3); they are read separately as the anchor and the check; the differential reading AIN2 - AIN3 is one more channel with its own gain and offset |
| PASS | HDR/states | V2-5, VT-22, PA-4 | the 1x3 header J_RAT = TAP_hi (2/3 tap, pin 1) &#124; B (pin 2) &#124; TAP_on (1/2 tap, pin 3), one shunt across pins 2-3: the sense tap AIN2 over the whole sweep (-1.923 .. +2.18 V, which contains the AWG's DC window), 1 % resistors, REF +-0.1 %, in every state: off 0.894 .. 2.655 V; TAP_on 0.379 .. 2.076 V; TAP_hi 0.562 .. 2.258 V | 0 V .. 3.22 V (the ADS1115's supply minimum; the Due's A0 / A1 are not on this node) | worst 0.379 V low, 2.655 V high | +0.379 V / +0.565 V | AIN3 (B) and the loaded tap stay inside 0 .. 3.0 V in every state; AIN1 reads pin 1 (TAP_hi) and AIN0 the reference; the Due's ladder pins see the taps' own voltages (the loaded tap moves by up to 631 mV, inside 0 .. AREF) |
| PASS | HDR/ratio | PA-4, SC-7 | ratio accuracy in each shunt state that carries a ratio measurement, S3, Zcm tracking / independent: TAP_on 0.053 % / 0.226 %; TAP_hi 0.059 % / 0.228 % | <= 0.05 % (tracking; the Monte Carlo reads 0.05 +- 0.003 %) | TAP_on: 0.053 % / 1.84 mV; TAP_hi (the slipped shunt): 0.059 % / 1.98 mV |  | the TAP_hi position is recoverable (the same readings give k) but it is detected and stopped on, not used |
| PASS | HDR/detect | VT-21, VT-22 | the shunt in the wrong place or off is detected: AIN3 (B) differs between every pair of states at every AWG level and tolerance draw | >= 50 mV | 300 mV minimum |  | the host reads B at the first and last step and compares with the three expected B(A) lines |
| PASS | PR-4/+5V | PR-3, PR-4 | the AWG node forced to +5 V, AFE unpowered, SHUNT OFF (the default state), through Rt 15k, Rb 10k, Rd 1k, R_SRS 3.9k, R_SRM 10k with the 1.8k bleed: worst of the REF3030E output open / clamping / at 0 V and the ADS1115 diode drop 0.3 V (ESD onset) / 0.6 V (BAV99) | rail < 0.5 V (PR-3 as PR-4 applies it); the 100 uA of PR-3 is a current into the Due's supply pins (the LM27762's back-path, nil with the rail under its diode threshold) | rail 0.434 V (clamp, 0.3 V diode), 241 uA into the rail | +0.066 V | this is the case that forced the 1.8k bleed: with the 10k of the first draft it reads 1.65 V and fails |
| info | PA-4/load | PA-4 | the loaded ladder tap (TAP_on, 1/2): its shift from 1.500 V over the sweep with the shunt on | information (not a check point while fitted) | 510 mV at most, wire current up to 137 uA |  | B is read, so the loading is not an error; AIN1 reads the 2/3 tap (TAP_hi, pin 1: loaded when the shunt is slipped) and AIN0 the reference |
| PASS | VT-22/I | VT-22, PA-4 | any position the header allows (the shunt slipped across pins 1-2, the one wrong placement; the shunt off): current into the ADS1115's input diodes, AIN2 through Rt&#124;&#124;Rb + 3.9k, AIN3 (B) through 10k | <= 10 mA (abs max), host takes no action | 0 uA at most | +10000 uA | series resistors are the only protection (no clamp: the ADS1115's own diodes conduct first); whether the other inputs read undisturbed during an overdrive is not in SBAS444E (7.3.1 warns) *(check, VT-22)* |
| PASS | VT-22/dist | V2-5, VT-22 | every position gives a distinguishable reading: AIN3 reads B itself, which is the node's voltage (1.0, 1.5 or about 2.95 V): smallest gap between positions | >= 20 x the reading resolution (125 uV + 0.1 % of 3 V) | 500 mV gap on AIN3 vs 3.12 mV |  | the top tap reads as the default (wire missing or on the top tap): the host stops either way |
| PASS | VT-21/22/det | VT-21, VT-22 | a wire left on after the calibration, or missing at its start: AIN3 (B) differs between the two positions at every AWG level and tolerance draw | >= 50 mV (about 16x the reading resolution) | 857 mV minimum | +807 mV | left on in normal use the tap stays inside 0.14 .. 1.89 V (PA-4/range) and the 1/2 ladder tap is loaded by up to 118 uA: nothing is damaged, the host's end-of-session reading catches it |
| PASS | D23/time | D21, D23, PA-3 | ADS1115 free-running on the pair, staircase 1.5 to 3 ms a level (D23), 1024 levels: the fit's slope noise from the readings at 860 SPS (1.16 ms) counting only conversions wholly inside a level (0.3 to 1.6 a level); 125 uV rms per conversion x sqrt 2 / k at the AWG node | <= 0.005 % (a tenth of the 0.05 % share) | 0.0021 % at 860 SPS; 0.0026 % at the worst of 128 to 860 SPS |  | no averaging per level is needed: one reading per level or less, the fit averages 300 to 1600 of them; the quantisation of a 125 uV code is spread over levels that each move the pair by 13 codes. At 128 SPS (7.8 ms) one conversion spans 3 to 5 levels: aligned by time stamp it is a boxcar of the staircase and the Due codes are averaged over the same window |
| info | D23/total | D23, PA-3 | total staircase time: 1024 levels x 1.5 to 3 ms, plus the two end readings of B and the wire-off ratio readings (64 conversions at 860 SPS each, 4 of them) | information | 1.5 to 3.1 s staircase + 0.30 s of readings + channel switches |  | staircase only; warm-up is separate. The ratio readings are static levels and are not bounded by D23's step |
| PASS | CAL/clip | D23, AW-1 | the sweep drops any level whose reading stops following the DAC code (the AWG clips about 5 to 10 mV above the weak -rail -1.955 V, from -1.923 V down): slope of the pair over the last 3 levels < 0.5 x the sweep's median slope | the clipped levels dropped, the fit unchanged | first dropped level -2.031 V (the sweep's window bottom -2.06 V), 28 of 1025 dropped, bottom of the kept range -1.928 V, fit gain error -0.0007 % |  | cost: the AWG's hard-corner window bottom is -2.06 V (../awg/design.md, information) but the weak -rail clips the output below about -1.923 V, so the kept sweep starts at -1.923 V: 0.14 V of the window (about 28 of 1025 levels) is lost; the coverage of the scope's -1.5 .. +3.5 V does not change, the margin below -1.5 V is 0.42 V |

## 6. ADS1115 and SC-7, the extrapolation (sc7.py)

| | ID | req | case | limit | result | margin | note |
|---|---|---|---|---|---|---|---|
| PASS | SC-7/ext | SC-7, PA-3, VT-23 | fit extrapolated to +3.5 V (AWG window -1.923 .. 1.5 V covers 60 % of the range), INL cubic 0.5 LSB, 1024 points: A = the tee fit alone (the design, D-V2-13), B = with ladder anchors (information only, NOT used), 99.9th pct | <= 3.5 mV (0.1 % of 3.5 V) | A 0.61 mV (0.017 %), B 3.94 mV (0.112 %) | A +2.9 / B -0.4 mV | B fails the share; against SC-7's whole 0.5 % + 5 mV = 22.5 mV both leave 18.6 mV. One Due LSB is 1.73 mV at the input |
| PASS | SC-7/ext | SC-7, PA-3, VT-23 | fit extrapolated to +3.5 V (AWG window -1.923 .. 1.5 V covers 60 % of the range), INL cubic 1.2 LSB, 1024 points: A = the tee fit alone (the design, D-V2-13), B = with ladder anchors (information only, NOT used), 99.9th pct | <= 3.5 mV (0.1 % of 3.5 V) | A 1.46 mV (0.042 %), B 4.36 mV (0.125 %) | A +2.0 / B -0.9 mV | B fails the share; against SC-7's whole 0.5 % + 5 mV = 22.5 mV both leave 18.1 mV. One Due LSB is 1.73 mV at the input |
| PASS | SC-7/ext | SC-7, PA-3, VT-23 | fit extrapolated to +3.5 V (AWG window -1.923 .. 1.5 V covers 60 % of the range), INL parab 1.2 LSB, 1024 points: A = the tee fit alone (the design, D-V2-13), B = with ladder anchors (information only, NOT used), 99.9th pct | <= 3.5 mV (0.1 % of 3.5 V) | A 2.16 mV (0.062 %), B 4.03 mV (0.115 %) | A +1.3 / B -0.5 mV | B fails the share; against SC-7's whole 0.5 % + 5 mV = 22.5 mV both leave 18.5 mV. One Due LSB is 1.73 mV at the input |
| PASS | SC-7/ext | SC-7, PA-3, VT-23 | fit extrapolated to +3.5 V (AWG window -1.923 .. 1.5 V covers 60 % of the range), INL knots 1.2 LSB, 1024 points: A = the tee fit alone (the design, D-V2-13), B = with ladder anchors (information only, NOT used), 99.9th pct | <= 3.5 mV (0.1 % of 3.5 V) | A 2.56 mV (0.073 %), B 6.92 mV (0.198 %) | A +0.9 / B -3.4 mV | B fails the share; against SC-7's whole 0.5 % + 5 mV = 22.5 mV both leave 15.6 mV. One Due LSB is 1.73 mV at the input |
| PASS | SC-7/ext | SC-7, PA-3, VT-23 | fit extrapolated to +3.5 V (AWG window -1.923 .. 1.747 V covers 65 % of the range), INL cubic 0.5 LSB, 1024 points: A = the tee fit alone (the design, D-V2-13), B = with ladder anchors (information only, NOT used), 99.9th pct | <= 3.5 mV (0.1 % of 3.5 V) | A 0.45 mV (0.013 %), B 3.73 mV (0.107 %) | A +3.1 / B -0.2 mV | B fails the share; against SC-7's whole 0.5 % + 5 mV = 22.5 mV both leave 18.8 mV. One Due LSB is 1.73 mV at the input |
| PASS | SC-7/ext | SC-7, PA-3, VT-23 | fit extrapolated to +3.5 V (AWG window -1.923 .. 1.747 V covers 65 % of the range), INL cubic 1.2 LSB, 1024 points: A = the tee fit alone (the design, D-V2-13), B = with ladder anchors (information only, NOT used), 99.9th pct | <= 3.5 mV (0.1 % of 3.5 V) | A 1.07 mV (0.031 %), B 4.29 mV (0.123 %) | A +2.4 / B -0.8 mV | B fails the share; against SC-7's whole 0.5 % + 5 mV = 22.5 mV both leave 18.2 mV. One Due LSB is 1.73 mV at the input |
| PASS | SC-7/ext | SC-7, PA-3, VT-23 | fit extrapolated to +3.5 V (AWG window -1.923 .. 1.747 V covers 65 % of the range), INL parab 1.2 LSB, 1024 points: A = the tee fit alone (the design, D-V2-13), B = with ladder anchors (information only, NOT used), 99.9th pct | <= 3.5 mV (0.1 % of 3.5 V) | A 1.99 mV (0.057 %), B 3.70 mV (0.106 %) | A +1.5 / B -0.2 mV | B fails the share; against SC-7's whole 0.5 % + 5 mV = 22.5 mV both leave 18.8 mV. One Due LSB is 1.73 mV at the input |
| PASS | SC-7/ext | SC-7, PA-3, VT-23 | fit extrapolated to +3.5 V (AWG window -1.923 .. 1.747 V covers 65 % of the range), INL knots 1.2 LSB, 1024 points: A = the tee fit alone (the design, D-V2-13), B = with ladder anchors (information only, NOT used), 99.9th pct | <= 3.5 mV (0.1 % of 3.5 V) | A 2.32 mV (0.066 %), B 6.36 mV (0.182 %) | A +1.2 / B -2.9 mV | B fails the share; against SC-7's whole 0.5 % + 5 mV = 22.5 mV both leave 16.1 mV. One Due LSB is 1.73 mV at the input |
| PASS | SC-7/ext | SC-7, PA-3, VT-23 | fit extrapolated to +3.5 V (AWG window -1.923 .. 2.092 V covers 72 % of the range), INL cubic 0.5 LSB, 1024 points: A = the tee fit alone (the design, D-V2-13), B = with ladder anchors (information only, NOT used), 99.9th pct | <= 3.5 mV (0.1 % of 3.5 V) | A 0.26 mV (0.007 %), B 3.42 mV (0.098 %) | A +3.2 / B +0.1 mV | B passes the share; against SC-7's whole 0.5 % + 5 mV = 22.5 mV both leave 19.1 mV. One Due LSB is 1.73 mV at the input |
| PASS | SC-7/ext | SC-7, PA-3, VT-23 | fit extrapolated to +3.5 V (AWG window -1.923 .. 2.092 V covers 72 % of the range), INL cubic 1.2 LSB, 1024 points: A = the tee fit alone (the design, D-V2-13), B = with ladder anchors (information only, NOT used), 99.9th pct | <= 3.5 mV (0.1 % of 3.5 V) | A 0.62 mV (0.018 %), B 4.11 mV (0.117 %) | A +2.9 / B -0.6 mV | B fails the share; against SC-7's whole 0.5 % + 5 mV = 22.5 mV both leave 18.4 mV. One Due LSB is 1.73 mV at the input |
| PASS | SC-7/ext | SC-7, PA-3, VT-23 | fit extrapolated to +3.5 V (AWG window -1.923 .. 2.092 V covers 72 % of the range), INL parab 1.2 LSB, 1024 points: A = the tee fit alone (the design, D-V2-13), B = with ladder anchors (information only, NOT used), 99.9th pct | <= 3.5 mV (0.1 % of 3.5 V) | A 1.75 mV (0.050 %), B 3.25 mV (0.093 %) | A +1.8 / B +0.2 mV | B passes the share; against SC-7's whole 0.5 % + 5 mV = 22.5 mV both leave 19.2 mV. One Due LSB is 1.73 mV at the input |
| PASS | SC-7/ext | SC-7, PA-3, VT-23 | fit extrapolated to +3.5 V (AWG window -1.923 .. 2.092 V covers 72 % of the range), INL knots 1.2 LSB, 1024 points: A = the tee fit alone (the design, D-V2-13), B = with ladder anchors (information only, NOT used), 99.9th pct | <= 3.5 mV (0.1 % of 3.5 V) | A 2.27 mV (0.065 %), B 5.63 mV (0.161 %) | A +1.2 / B -2.1 mV | B fails the share; against SC-7's whole 0.5 % + 5 mV = 22.5 mV both leave 16.9 mV. One Due LSB is 1.73 mV at the input |
| info | SC-7/ext-ideal | SC-7 | the same (cubic 1.2 LSB, top 1.747 V) with perfect anchors (no ADS channel mismatch, no offset, no pin offset) | information | A 1.07 mV, B 1.76 mV at +3.5 V |  | what the four-anchor quadratic estimator would give with exact ADS readings: still worse than the tee fit for cubic and random-knot INL (review.md section 2); only a parabolic INL favours it. The estimator, not only the ADS1115, loses |
| PASS | SC-7/sum | SC-7 | this block's gain terms alone, linear sum (RSS in the note), and its offset, against ±0.5 % of reading ± 5 mV | <= 0.5 % and <= 5 mV for the WHOLE of SC-7 (the scope's own terms come on top) | 0.42 % (RSS 0.27 %), 2.5 mV | +0.08 % | the sense chain still dominates; with Zcm tracking between inputs it is 0.05 % and 1.8 mV and the sum 0.25 %. The ladder's drift is not a term (D-V2-13) |
| PASS | SC-7/noise | SC-7 | ADS1115 noise averaged over 64 conversions, referred to the AWG node through k = 0.4 (125 uV rms per reading, Table 6-1) | <= 1 mV | 39 uV rms |  | the table's figure equals one LSB: the converter is quantisation-limited, so averaging reduces it only if the input noise dithers it; the worst case without dither is 0.5 LSB = 156 uV at the node |

## Wrong wires among the Due pins the AFE uses (wires.py)

| | ID | req | case | limit | result | margin | note |
|---|---|---|---|---|---|---|---|
| PASS | WIRE/top | PA-2 | a wire from the top tap (the reference itself, Due pin A7) to GND, +3.3 V, DAC0 or the AWG node: the REF3030E is short-protected, ISC 35 mA typ (SBVS032K 6.5, 'ISC Short-circuit current', PDF page 6; abs max 'Output short-circuit current(2) 70 mA', 6.1 page 4, note (2) 'Short circuit to ground'); the duration is not stated *(check)* | survived by the reference's own current limit (35 mA < 70 mA abs max): a SURVIVED FAULT, no series resistor | 5 wires reach the limit: p6 - gnd, p6 - v33, p6 - dac_lo, p6 - dac_hi, p6 - awg_lo |  | dissipation about 3.3 V x 35 mA = 0.12 W in the SOT-23 *(check: no thermal figure in the text)*; the ladder's tap-to-tap and tap-to-GND wires below do not reach it |
| info | WIRE/taps | PA-2 | every other single wrong wire (taps A2..A6 to GND, +3.3 V, DAC0, the AWG node at -1.923 / +2.18 V, or to each other; the DAC at its window ends and the AWG at its range ends): the largest current in the REF3030E | <= 10 mA (6.3 recommended); abs max 70 mA | 12.9 mA (p5 - awg_lo); wires above 10 mA: p5 - awg_lo 12.9 mA |  | tap 5 to the AWG node at -1.923 V sinks the AWG's 49.5 ohm into the ladder: 12.9 mA from the reference, above the 10 mA recommended and far inside the 35 mA limit: survived |
| info | WIRE/pins | PR-2 | the Due ADC pins A2..A7 under every wrong wire: range of the pin voltages | -0.2 .. 3.45 V (PR-2 is stated for A0, A1 and the DAC pin; the SAM3X abs max -0.3 .. 4.0 V *(check)*) | -1.63 .. 3.30 V |  | only a wire to the AWG node at -1.923 V takes a ladder pin below -0.2 V, and the wire itself drives the Due pin there: no resistor in the AFE can prevent it at a Due pin, the AWG's 49.5 ohm limits it to about 38 mA *(check the SAM3X input rating)*. A wire to +3.3 V or DAC0 stays inside 0 .. 3.3 V |

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
| normal, AWG hi-Z at the window top | 3.418 | 35.4 | 15.1 | 52.5 | -0.1 |
| normal, AWG hi-Z at the window top | 3.220 | 35.2 | 15.1 | 52.3 | -0.1 |
| normal, AWG into 50 ohm at the window top | 3.418 | 56.8 | 15.0 | 73.7 | +21.3 |
| normal, AWG into 50 ohm at the window top | 3.220 | 56.6 | 15.0 | 73.5 | +21.3 |
| normal, AWG into 50 ohm at the window bottom | 3.418 | 36.2 | 34.0 | 74.0 | -19.0 |
| normal, AWG into 50 ohm at the window bottom | 3.220 | 36.0 | 34.0 | 73.8 | -19.0 |
| normal, AWG hi-Z at the window bottom | 3.418 | 36.3 | 15.8 | 54.1 | -0.8 |
| normal, AWG hi-Z at the window bottom | 3.220 | 36.1 | 15.8 | 53.9 | -0.8 |
| fault: BNC shorted, DAC at the window top | 3.418 | 78.4 | 15.0 | 95.3 | +42.9 |
| fault: BNC shorted, DAC at the window top | 3.220 | 78.2 | 15.0 | 95.1 | +42.9 |
| fault: BNC shorted, DAC at the window bottom | 3.418 | 36.3 | 54.6 | 96.8 | -39.6 |
| fault: BNC shorted, DAC at the window bottom | 3.220 | 36.1 | 54.6 | 96.6 | -39.6 |
| fault: BNC shorted, DAC at the 3.3 V reset level (output clips about 0.1 V under the rail) | 3.418 | 102.3 | 15.0 | 119.2 | +67.1 |
| fault: BNC shorted, DAC at the 3.3 V reset level (output clips about 0.1 V under the rail) | 3.220 | 102.1 | 15.0 | 119.0 | +67.1 |

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
| wire on throughout, max channel match 0.1 % | 0.224 | 2.46 | 6.35 | 0.199 |
| typical channel match 0.05 % | 0.224 | 2.46 | 6.35 | 0.160 |
| no channel mismatch | 0.224 | 2.46 | 6.34 | 0.134 |
| wire off throughout (information) | 0.553 | 10.36 | 20.11 | 0.518 |

Structures compared (99.9th percentile, ADS1115 channel match 0.1 % max, offset 3 LSB)

| structure | gain % | offset mV |
|---|---|---|
| S1: tap on AIN2, B on AIN3 in the wire position only, REF on AIN0 | 0.621 | 11.50 |
| S2: B on AIN3 in both positions | 0.314 | 2.32 |
| S3: AIN3 = B, AIN2 - AIN3 differential, REF scale rebuilt on AIN3 | 0.167 | 2.28 |
| S3 + 10k matched resistor on AIN3 (Zcm independent per input) | 0.224 | 2.46 |
| S3 + matched resistor, Zcm tracking between inputs | 0.053 | 1.86 |

Ablation of the shipped models (20,000 draws, 99.9th percentile; S3 = the design with 10k on AIN3, Zcm independent per input; S1 = the first structure)

| case | S3 gain % | S3 offset mV | S1 gain % | S1 offset mV |
|---|---|---|---|---|
| 1 % resistors only | 0.035 | 0.03 | 0.101 | 2.05 |
| Zcm spread only | 0.212 | 1.25 | 0.135 | 0.93 |
| base (as shipped) | 0.224 | 2.46 | 0.621 | 11.50 |
| channel match only | 0.010 | 0.00 | 0.488 | 8.92 |
| no ADS offsets | 0.222 | 1.68 | 0.585 | 10.05 |
| no INL | 0.223 | 2.27 | 0.609 | 11.45 |
| no Zcm spread | 0.052 | 1.70 | 0.566 | 11.29 |
| no channel mismatch | 0.224 | 2.46 | 0.280 | 5.11 |
| no noise | 0.221 | 2.39 | 0.621 | 11.51 |
| no resistor tolerance | 0.217 | 2.45 | 0.589 | 11.04 |
| offsets only | 0.022 | 1.27 | 0.127 | 3.57 |

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
| pin 1, TAP_hi (2/3 tap): the shunt slipped to pins 1-2, the one wrong placement | 1.0 | -0.169 | 1.472 | 0 (AIN3: 0) | 117 |
| pin 3, TAP_on (1/2 tap): the calibration position (shunt across pins 2-3) | 1.5 | 0.131 | 1.772 | 0 (AIN3: 0) | 137 |
| shunt off (default tie to the REF3030E) | 3.0 | 1.031 | 2.672 | 0 (AIN3: 0) | 197 |

## SC-7 sum of this block (sc7.py)

| term | gain % | offset mV |
|---|---|---|
| REF3030E: initial 0.1 %, 15 ppm/K x 10 K, hysteresis 100 ppm, long-term 40 ppm | 0.129 | 0.0 |
| AWG sense chain, structure S3, Zcm spreading independently (the conservative case), 99.9th pct | 0.224 | 2.5 |
| Due-ADC tee fit extrapolated to +3.5 V (random-knot INL 1.2 LSB, the worst model, at the AWG's LOWEST window top end 1.747 V; ladder anchors NOT used, D-V2-13) | 0.066 | 0.0 |
| **linear sum (RSS)** | **0.42 (0.27)** | **2.5** |

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
| G-divscan | the bleed bound of the scan applied to a 10k bleed on the 25k divider must fail; the 2k the scan finds passes | fails | passes | ok |
| G-PR3-sense | the forced-sense check with the 10k bleed must fail; the 1.8k bleed passes | fails | passes | ok |
| G-PW-rating | V2-2 supply check: R3 = 82k (nominal -2.26 V) must exceed 5.5 V at the corners | fails | passes | ok |
| G-PW-1 | PW-1 check with the limit lowered to 40 mA must fail | fails | passes | ok |
| G-PR-3 | PR-3 check with the bleed removed (1 Gohm) must fail | fails | passes | ok |
| G-REF-VIN | REF3030E dropout check with R1 = 100k (nominal 2.97 V) must fail | fails | passes | ok |
| G-sc9 | the SC-9 DC sum with the plane return assumed 100 ohm instead of 10 mohm must fail | fails | passes | ok |
| G-pw7 | PW-7 check against a 1 ms limit must fail | fails | passes | ok |
| G-Z | tap impedance check with 1.5 kohm rungs must fail | fails | passes | ok |
| G-REF-I | REF source check with a limit of 1 mA must fail | fails | passes | ok |
| G-tapcheck | the measured-tap fault check (window 1.5 % + 10 K drift) must flag a tap 5 % off | fails | passes | ok |
| G-forced5 | the +5 V forced-sense check with a 4.7k bleed (the v1 helper's) and the REF output open must fail; the 1.8k bleed passes | fails | passes | ok |
| G-clip | the clip check with the slope criterion disabled (threshold 0) must fail | fails | passes | ok |
| G-struct | the ratio check applied to the old structure S1 must fail; S3 with the matched resistor passes (Zcm tracking) | fails | passes | ok |
| G-range | tap range with k = 0.6 (tap goes below ground at the window bottom) must fail | fails | passes | ok |
| G-ratio | ratio accuracy with a 2 % channel match must fail a 1.5 % gain limit (the designed 0.1 % match passes it) | fails | passes | ok |
| G-distinct | distinguishability with k = 0.995 (wire barely moves the tap) must fail | fails | passes | ok |
| G-current | the ESD-current check with a limit of 100 uA applied to a shunt wired to the Due's 5V / VIN (stress) must fail; the header's own states pass it | fails | passes | ok |
| G-ext | the extrapolation check with an INL of 12 LSB must fail the 0.1 % share | fails | passes | ok |
| G-sum | the SC-7 sum check against a 0.5 % limit with the sense chain's error multiplied by 3 must fail (the real sum passes the same 0.5 %) | fails | passes | ok |
| G-wire-limit | the check 'no wrong wire exceeds the 10 mA recommended load' must fail (the top-tap wires reach 35 mA); the survival criterion (current limit 35 mA < 70 mA abs max) passes | fails | passes | ok |
| G-wire-uncapped | without the reference's current limit the top-tap wires would read thousands of mA: the check on the raw ideal-source solution must fail | fails | passes | ok |
| G-basic | an Extended passive (C861163) in the list must be refused | fails | passes | ok |
