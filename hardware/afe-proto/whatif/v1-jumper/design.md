# Version 1 sense design on kvm_02's structure S3 (one circuit for v1 and v2), D25 / PA-4

Third pass, on the spec lead's direction. The earlier single-ended passes are kept in `k2-superseded/` (pass 1: 1.12 %; pass 2: k = 1/2, 47k, 0.385 %, `design-pass2-k12-47k.md`).
Engines: `net.py` (`run_s3`, my nodal model with the real v1 ladder) and kvm_02's own `sense.py` (read from origin/main, patched for the v1 ladder and window in the scratchpad, for the cross-check only).
Scripts numpy only, `./run_all.sh` regenerates `results/` (`final_s3.py` is this design). Figures marked *(check)* are not verified; nothing is measured on a board.

## 0. Result

**k = 0.405: R7 = 22k, R8 = 15k, Rd = 1k, Rs = 3.9k on the tap input, Rm = 13k on the B input, BAV99 on both ADS1115 inputs, wire B to TAP3.**

| Requirement | Result | Verdict |
|---|---|---|
| Tap and B in 0..3.21 V by hardware, wire off / on / every header wrong position, window +-1.35 V | off T0 1.147..2.312 V; on (B-TAP3) 0.465..1.595 V; B-TAP4 0.703..1.835 V; TAP4-TAP3 1.147..2.312 V; tightest +0.465 V | PASS |
| PR-3/PR-4, +-5 V on the BNC, unpowered (both inputs clamped by BAV99) | rail **0.411 V, 87 uA** (wire off), 0.402 V, 85 uA (wire on); limits 0.5 V, 100 uA | PASS only on the optimistic assumptions (REF 0 V, BAV99 curve); **on kvm_02's worst case it needs R65 = 2.2k instead of 4.7k: section 8** |
| Host detects the wire | smallest gap 383 mV against 62 mV | PASS |
| **Ratio, 99.9th percentile, channel match 0.1 % max** | **0.088 % / 1.84 mV if Zcm tracks; 0.307 % / 2.60 mV if independent** (allotment 0.05 % / 3 mV) | gain **FAIL** (1.8x / 6x); offset PASS |
| SC-7 whole stack (section 4) | tracking: sum 0.428 % / 4.88 mV, RSS 0.234 % / 3.54 mV: **PASS both**; independent: sum 0.647 % / 5.60 mV FAIL, RSS 0.376 % / 3.97 mV PASS | |

## 1. Inputs, the wire and the header (answers to corrections 1 and 2)

**ADS1115 (SBAS444E differential pairs: AIN0-1, AIN0-3, AIN1-3, AIN2-3 only): AIN2 = T0 (through Rs), AIN3 = B (through Rm), read as the pair AIN2-AIN3 = T - B and AIN3 alone single-ended; AIN0 = VREF; AIN1 = TAP3 (single-ended).**
kvm_02's "inputs 2 and 3" are AIN2 and AIN3 (pins 6 and 7); AIN0 and AIN1 here are kvm's inputs 1 and 4. The wire joins B to TAP3, which AIN1 reads: with the wire on, AIN3 and AIN1 see one voltage, a free equal-voltage cross-check of those two channels. The reference's scale is rebuilt on B with the wire off (REF = B - Rd (T - B)/Rb), so VREF on AIN0 is a check, not part of the ratio.

**The window.** v1's sweep is the AWG's own -1.35 .. +1.35 V, so for range by hardware the tap needs B_on >= 1.35 k/(1-k) = 0.92 V at k = 0.405; the +-5 V forced case is PR-3/PR-4's, not the sweep's, so v1 keeps k about 0.4 like v2 (verified: kvm_02's 5.2k/(1-k) = k 0.16 conflates the two).
Rd's 1k pulls the loaded tap up, so the wire-on B is: TAP1 0.40 V (**T0 -0.317 V: no**), **TAP2 1.20 V (T0 min 0.159 V: yes, margin 0.16 V)**, **TAP3 1.72 V (0.465 V)**, TAP4 2.12 V (0.703 V), TAP5 2.51 V (0.930 V). TAP2 works (the unloaded 0.75 V does not, the loaded 1.2 V does); **TAP3 is chosen: it keeps 0.47 V**, and the ratio is the same (0.085 / 0.088 / 0.092 % for TAP2 / 3 / 4, tracking).

**Header J_RAT, three plated holes, no part: `TAP4 | B | TAP3`**, right wire joins B (pin 2) to TAP3 (pin 3); pin 1 TAP4 is the in-range neighbour (B-TAP4: T0 0.703 V). Pins carry only AFE signals inside 0..AREF (TAP4 1.875 V, B 2.88..2.96 V off / 1.72..1.76 V on, TAP3 1.3125 V), so PR-2 holds. The header can keep the `TAP3 | B | TAP4`-style order; the order is the layout's.

| State (T0 and B both in range unless marked; window +-1.35 V, 1 % parts, 6000 draws) | T0 (V) | B (V) | Pin after BAV99 (T / B) | Clamp (T / B) | Host gap |
|---|---|---|---|---|---|
| wire OFF (normal use) | 1.147 .. 2.312 | 2.88 .. 2.96 | = | 0 / 0 | |
| **B-TAP3 (right)** | 0.465 .. 1.595 | 1.72 .. 1.76 | = | 0 / 0 | |
| B-TAP4 (header neighbour) | 0.703 .. 1.835 | 2.12 .. 2.16 | = | 0 / 0 | |
| TAP4-TAP3 (rung bridged, B on Rd) | 1.147 .. 2.312 | 2.88 .. 2.96 | = | 0 / 0 | |
| *Due pin:* B-TAP1 | -0.317 .. 0.796 **out** | 0.40 | -0.303 / | 1.1 uA / 0 | |
| B-TAP2 | 0.159 .. 1.284 | 1.20 | = | 0 / 0 | |
| B-TAP5 | 0.930 .. 2.061 | 2.51 | = | 0 / 0 | |
| B-VREF | 1.215 .. 2.337 | 3.00 | = | 0 / 0 | |
| B-GND | -0.552 .. 0.554 **out** | 0 | **-0.432** / 0 | 9.5 uA / 0 | |
| B-+3V3A (B = the rail itself) | 1.392 .. 2.516 | 3.3 | = | 0 / 0 | |
| B-Due 5V (stress) | 2.541 .. 3.683 **out** (under VDD + 0.3) | 5.25 | 2.543 / 3.79 | 5.9 / 113 uA | |
| B-Due VIN (stress) | 6.517 .. 7.723 **out** | 12 | 3.83 / 3.90 | 304 / 630 uA | |
| TAP5-GND (ladder top shorted) | 1.147 .. 2.312 | 2.88 .. 2.96 | = | 0 / 0 | REF **11.35 mA** (over the 10 mA row, *(check)*) |

Host detection: smallest gap 383 mV (`ranges.detect`), 62 mV needed. On the header every state is in range; through the Due's pins only TAP1, GND and the 5V/VIN stresses leave it. Currents are 630 uA at most against 10 mA.
**-0.3 V row:** the silicon BAV99 *(check, no datasheet read)* holds the tap pin at -0.43 V (B-GND), -0.48 V (-1.8 V forced, unpowered), -0.58 V (-5 V unpowered): 0.13 to 0.28 V past GND - 0.3 V at 9 to 117 uA, 85x to 1000x inside the 10 mA row. Same finding as before; SBAS444E 7.3.1 prefers Schottky diodes, VT-22 decides.

## 2. PR-3 / PR-4 with S3 (correction 3)

Both inputs see the network (T0 through Rs, B through Rm); a BAV99 on each; the unpowered rail is charged through the upper diodes of **both** and held down by R65 4.7k (`s3.py`, coupled solve). Unpowered, +5 V on the BNC, wire off: 

| Divider (R7/R8, total + Rd) | Rs / Rm | rail | current into it | tracking / independent Zcm gain |
|---|---|---|---|---|
| 15k/10k (kvm_02, 26k) | 3.9k / 10k | **0.491 V** | **105 uA: FAIL** (rail inside, current over) | 0.108 % / 0.264 % |
| 15k/10k | 6.8k / 13k | 0.414 V | 88 uA | 0.112 % / 0.323 % |
| 18k/12k (31k) | 3.9k / 12k | 0.451 V | 96 uA (4 % margin) | 0.096 % / 0.290 % |
| **22k/15k (38k)** | **3.9k / 13k** | **0.411 V** | **87 uA** | **0.088 % / 0.303 %** |
| 27k/18k (46k) | 3.9k / 15k | 0.364 V | 77 uA | 0.080 % / 0.342 % |
| 33k/22k (56k) | 3.9k / 18k | 0.323 V | 69 uA | 0.075 % / 0.387 % |
| 47k/30k (78k) | 3.9k / 22k | 0.253 V | 54 uA | 0.074 % / 0.479 % |

**k = 0.4 with 26k does not pass (105 uA against 100 uA); the smallest total that does is 31k (96 uA, thin) at Rs 3.9k, or 26k with Rs raised to 6.8k (88 uA).** I took 38k with Rs 3.9k: 13 % margin on both rows, and the best tracking figure of those with margin. Rm is re-solved as Rt||Rb + Rs: 8.9k + 3.9k = 12.8k, the Basic 13k. A larger Rs would also pass but pays in the independent-Zcm case (0.32 % at 6.8k, 0.37 % at 10k).
The earlier -5 V unpowered current (117 uA) goes into GND, not a supply pin. AWG load, wire off: 43 .. 116 uA into the node (2.1 .. 5.8 mV across 49.9 ohm, 0.135 % gain, permanent so calibrated); noise 104 nV thermal + 67 nV from VREF against AW-6's 0.3 mV (0.06 %).

## 3. Precision, and my model against kvm_02's (correction 4)

`net.run_s3` follows S3: the pair on AIN2-AIN3 (own gain and offset draw), B single-ended on AIN3, the scale rebuilt from the KCL, (A, k) solved from the wire-off and wire-on readings at one level, k = d(T-B)/dB, A = B + (T-B)/k, the sweep with B read at every level, gain/offset of the line fitted to the error. 99.9th percentile, 0.1 % channel match, +-3 LSB (375 uV) offsets, per-channel INL, Zcm +-25 %.

| Case | kvm_02's `sense.py`, unmodified (v2: Rt 15k, Rb 10k, Rs 3.9k, Rm 10k, 1/3 tap, window -1.95..+2.28 V) | their code on the v1 ladder and window (wire TAP3, +-1.35 V) | my model, the same v1 values |
|---|---|---|---|
| Zcm tracks | **0.050 % / 1.73 mV** | 0.097 % / 1.75 mV | 0.108 % / 1.80 mV |
| Zcm independent | **0.225 % / 2.35 mV** | 0.258 % / 2.37 mV | 0.264 % / 2.29 mV |

I reproduce their v2 numbers by running their script. My independent model agrees with their code on the v1 problem within 12 % (tracking gain) and 3 % (the rest); the difference is mine carrying the real 8 x 270 ladder and the Zcm load on its taps, and a 0.008 % to 0.02 % zero-error floor (theirs 0.008 %). **The v1/v2 difference is the window, nothing else**: their code with the v2 window on the v1 ladder gives 0.051 % / 1.78 mV tracking, with the v1 window on the v2 ladder 0.095 % / 1.75 mV (ladder and wire node change it by 0.003 %): the offset-like errors (1.8 mV) divide by a window half-span of 1.35 V instead of 2.1 V. The v1 differences they ask about: the 4.096 V range is the same, the AWG load (above) is not in the ratio.

**The chosen values, 99.9th percentile (`final_s3.py`, 20000 draws):**

| | gain | offset |
|---|---|---|
| Zcm tracks, match 0.1 % max (match 0.05 % typ: identical, 0.088 %) | **0.088 %** | **1.84 mV** (worst point 2.6 mV, k error 0.10 %) |
| Zcm independent per channel | **0.307 %** | **2.60 mV** (worst point 6.3 mV, k error 0.22 %) |
| offset read literally (187.5 uV), tracking / independent | 0.084 % / 0.306 % | 1.32 / 2.14 mV |
| ablation (one source, tracking Zcm except the row marked): channel match 0.1 % | 0.031 % | 0.51 mV (= the model floor 0.030 %: **it cancels; 2 % match moves the gain by 0.01 %**) |
| offsets 3 LSB | 0.041 % | 1.56 mV |
| 1 % resistors | 0.077 % | 0.53 mV |
| Zcm spread 25 %, independent | 0.281 % | 1.87 mV |
| averaging noise (64 readings) | 0.040 % | 0.64 mV |
| floor (INL, scale): control | 0.030 % | 0.51 mV |

S3 cancels the channel match (previous structure: 0.18 % from 0.1 %, 20x worse at 2 %) and keeps the offsets and the Zcm spread; **what is left is Zcm (if independent) and the 1 % resistors**. The match resistor Rm helps only if Zcm tracks between the inputs *(check, VT-21: the datasheet gives one typical value)*. The 0.05 % / 3 mV allotment is met on offset and missed on gain (0.088 % tracking: 1.8x; 0.307 % independent: 6x); it is not relaxed silently, see section 4.

## 4. The SC-7 stack for version 1 (`stack.py` terms, `final_s3.py`)

SC-7: +-0.5 % +-5 mV, mean of 1024 samples, 10 K since calibration. Terms: REF3030E E grade 0.130 % (afe-v2 powercal design.md section 6, hysteresis 100 ppm *(check)*); EN-1 gain drift 0.168 % (0.336 % over 20 K from `v1-basic/values.md`, halved *(check)*); Due ADC INL fit share 0.042 % (afe.md PA-3); offsets: EN-1 3.0 mV (requirement figure) + the sense.

| Sense term | Gain: sum / RSS | Offset: sum / RSS | vs 0.5 % / 5 mV |
|---|---|---|---|
| S3, Zcm tracks: 0.088 % / 1.84 mV | **0.428 % / 0.234 %** | **4.88 / 3.54 mV** | **sum PASS, RSS PASS** |
| the same with the ladder's drift (0.133 %, v2's figure, *(check)*) | 0.561 % / 0.269 % | 4.88 / 3.54 mV | sum FAIL, RSS PASS |
| S3, Zcm independent: 0.307 % / 2.60 mV | 0.647 % / 0.376 % | 5.60 / 3.97 mV | sum FAIL, RSS PASS |
| pass-2 design (0.385 %) | 0.725 % / 0.442 % | 5.64 / 4.00 mV | sum FAIL, RSS PASS |

The rest of the stack leaves 0.160 % (sum) or 0.451 % (RSS) and 2.0 mV for the sense: S3 with a tracking Zcm fits inside the sum, an independent Zcm only inside the RSS. VT-21 decides which; the allotment (0.05 %) is not what the stack needs, the stack needs 0.16 %.

## 5. Final v1 sense design and parts delta (`parts.csv`)

| Part | Value | LCSC | Role |
|---|---|---|---|
| R7 | 22k 1 % 0603 | C31850 | BNC node to T0 (was 100k C25803) |
| R8 | 15k 1 % 0603 | C22809 | T0 to B (was 100k) |
| Rd (new) | 1k | C21190 | B to VREF, default tie |
| Rs (new) | 3.9k | C23018 | T0 to AIN2 |
| Rm (new) | 13k | C22797 | B to AIN3 (= R7 || R8 + Rs = 12.8k) |
| D8 | BAV99 | C2500 (Basic) | clamp on AIN2 after Rs (was BAT54S) |
| D_B (new) | BAV99 | C2500 | clamp on AIN3 after Rm |
| J_RAT | 3 plated holes `TAP4 | B | TAP3` | no part | the wire |

Inputs: AIN0 VREF, AIN1 TAP3, AIN2 T0, AIN3 B (pair AIN2-AIN3). **Delta against the current `design.py` cal block:** removed U12, C30, R68, D7 (4); added Rd, Rs, Rm, D_B (4); R7/R8 and D8 change value/type. **Placements 0; Extended types -1 (TMUX1119); Basic types +5 (22k, 15k, 3.9k, 13k, BAV99); about -CNY 13.07 per board at 20 (-USD 1.95)**, the four resistor prices unread (taken as the 1k's) *(check)*; BAT54S stays Extended (D1, D2, D4, D5, D6). For `design.py` (not edited): R8's far end `SNS_D` -> `SNS_B`; AIN2 = `SNS_TAP` after Rs, AIN3 = `SNS_B` after Rm; AIN0 VREF, AIN1 TAP3 (was TAP5, TAP2); D9 returns to the free list.

## 6. Guards (broken on purpose; `results/guards_s3.json`)

| Guard | Break | Result |
|---|---|---|
| G-s3-zero | errors off: floor 0.02 % (restored); host Rd 2x, Rs 2x, or Zcm 1.5 MOhm | each over 0.05 %: fails; restored passes |
| G-s3-offset | offsets off must not raise the offset; 60 LSB must | the check can fail; passes restored |
| G-s3-eps | 2 % channel match moves S3 by 0.01 % (cancels); the previous structure moves 0.29 % -> 4.43 % | previous structure fails the test |
| G-pr3 | kvm_02's values must read over 100 uA (105 uA) | fires; the final values pass (87 uA, 0.411 V) |
| G-s3-range | wire at TAP1 must put T0 below 0 (-0.317 V) | fails; TAP3 passes |
| G-s3-detect | limit at 1000 x resolution | fails; at 20 x all pass |

## 7. (check) list
BAV99 forward curve and IR (from memory); the Zcm tracking between inputs (VT-21); the ADS1115's other inputs during an overdrive (SBAS444E 7.3.1, VT-22) and its differential gain against the single-ended B reading (my model draws it independently, as kvm_02's does); INL at +-4.096 V; the 375 uV offsets (literal 187.5 uV is lower); EN-1 halving, REF hysteresis, ladder drift, the Due ADC's offset in mV; REF3030E sinking in TAP5-GND/VIN states; resistor and BAV99 prices; the +3V3A low corner 3.21 V (`values.md`); the AWG window +-1.35 V (afe.md AW-1, `v1-awg-ref`).

## 8. PR-3 on kvm_02's worst case (`pr3.py`, `pr3_run.py`, `results/pr3.json`)

**What my earlier PR-3 figure assumed** (section 2, `s3.py`): the REF3030E output at 0 V (the ladder and Rd to ground); the BAV99 on each pin as a Shockley curve (0.39 V at 5 uA, about 0.5 V at 90 uA); the ADS1115's own ESD diodes not modelled; the +3.3 V_A rail loaded only by **R65 = 4.7k, which was in the model** (it took 87 uA at the 0.411 V rail, all of the injected current); no LM27762, ADS1115 or REF3030E leakage; one rail. Reproduced: REF 0 V, drop 0.6 V, 4.7k gives 0.402 V / 86 uA here (0.484 V / 103 uA for kvm_02's 25k circuit, theirs 0.474 V / 102 uA).

**kvm_02's worst case** (both inputs' ESD onset a hard 0.3 V, 5 ohm; the reference output at 0 V, open, or clamping into the rail; resistors +-1 %; wire off and on; +5 V on the BNC, AFE unpowered). **My engine reproduces their figures to 1 %**: their 15k/10k circuit gives 0.986 V / 210 uA with the 4.7k bleed (theirs 0.974 V / 210 uA) and **0.434 V / 241 uA with the 1.8k** (theirs 0.434 V / 241 uA), once the ladder is taken off the reference node as their network does. **With the ladder in, the reference node cannot float**: the eight rungs (1.44k) tie it to ground, the reference clamp never conducts, and the same circuit reads 0.608 V / 129 uA (4.7k), 0.287 V / 159 uA (1.8k). The ladder is v1's and v2's real hardware, so "open" is a bound, not a state: I report both.

**v1's S3 (R7 22k, R8 15k, Rs 3.9k, Rm 13k), +5 V on the BNC, unpowered, worst of wire off / on and the reference states:**

| Bleed R65 | ladder in place (real): rail / into rail | kvm_02's no-ladder worst: rail / into rail |
|---|---|---|
| **4.7k (v1 today)** | **0.496 V** (4 mV margin) / 106 uA | **0.746 V: FAIL** / 159 uA |
| 3.3k | 0.377 V / 114 uA | 0.550 V: FAIL / 167 uA |
| 2.7k | 0.320 V / 118 uA | 0.460 V (40 mV) / 170 uA |
| **2.2k (C4190)** | **0.269 V / 122 uA** | **0.382 V (118 mV) / 173 uA** |
| 1.8k (C4177, kvm_02's) | 0.226 V / 125 uA | 0.317 V / 176 uA |

+1.8 V (PR-4's level): 0.129 V (4.7k) and 0.059 V (1.8k) real, 0.238 V and 0.101 V no-ladder. Wire on is the milder state in every row (the table is the worst of the two).

**The other PR-3 case, both scope inputs at +12 V, AFE unpowered** (v1's network from `design.py`: R1 770k, R2 800k, R3 330k to the reference node, Rnp 680, the TPH2502 input diode at 0.3 V to its V+ pin = the rail through R71 1R; the follower and REF-centre path are in): **27 uA into the rail, rail 0.125 V with 4.7k, 0.060 V with 2.2k**, the same with the reference open, at 0 V or clamping (R3 is 330k: nothing reaches it). It does not bind. The scope design's own PR-3 figures (`whatif/C2/sim/scope*`) were not re-read here *(check)*. The sense case at +5 V is the one that sizes the bleed.

**Bleed for v1: R65 = 2.2k (C4190, Basic 2.2k 0603).** It holds the rail at 0.382 V in kvm_02's worst case (118 mV margin; 2.7k leaves 40 mV, 1.8k 183 mV). **PW-1 cost: 3.4177 V / (2.2k x 0.99) = 1.57 mA permanent, 1.6 % of the 100 mA budget at the 5 V pin, +0.84 mA over the 4.7k** (kvm_02's 1.8k: 1.90 mA). The +3V3A load in normal use is the same as before otherwise *(check against v1's PW-1 table)*.

**The strict reading (100 uA INTO the rail) is not met by any bleed**: 122 to 176 uA flows into the rail whatever R65 is. The divider that meets it with the ladder in place is 55k (92 uA; 45k reads 106 uA) and, on the no-ladder worst case, 77k (90 uA; 55k reads 123 uA), at the cost of the independent-Zcm ratio (0.39 to 0.48 %, section 2 table). I recommend the rail-voltage reading, as kvm_02 does: the rail is not a Due supply pin and, below the LM27762's diode threshold, nothing reaches the 5 V pin *(check: the LM27762's reverse path, SNVSAF7C)*; the decision is the spec lead's.

**Comparison with kvm_02's choices.**

| | kvm_02 (v2) | v1 here | matters? |
|---|---|---|---|
| bleed | 1.8k (1.90 mA) | 2.2k (1.57 mA) | **yes**: it is the only thing that fixes the rail; the value follows the divider: 2.2k holds 22k/15k at 0.382 V, kvm_02's 15k/10k at 0.519 V (fails), so a shared circuit takes 1.8k with 15k/10k or 2.2k with 22k/15k |
| Rt / Rb | 15k / 10k (25k) | 22k / 15k (37k) | **a little**: 27 % less current into the rail at one bleed (173 against 236 uA at 2.2k, no-ladder worst), tracking ratio 0.088 % against 0.108 % on the v1 window, independent 0.307 % against 0.264 % |
| Rs / Rm | 3.9k / 10k | 3.9k / 13k | **no** for PR-3 (Rs sets the clamp current: Rs 6.8k saves 17 uA of 105 in the earlier model); Rm only matches Rth + Rs (the ratio) |
| wire node | 1/3 tap | TAP3 (1.3125 V) | no |
| reference state | open, no ladder | ladder in place, and no-ladder as the bound | **the 1.5x between 0.608 V and 0.986 V (4.7k, kvm_02's circuit)**; if the ladder's tie to ground is certain, 15k/10k could keep a 2.7k bleed (0.401 V) |

Guards (`results/pr3.json`): G-pr3-repro (the check that my engine matches their 0.434 V / 241 uA fails with the ladder left on and passes with it out), G-pr3-bleed (4.7k reads 0.746 V and fails, 2.2k passes), G-pr3-scope (no bleed fails, 2.2k passes). The earlier fixed-point scope solver returned 0 V for a large bleed (a void check): replaced by bisection before the guard was trusted.
