# AFE version 2: simulation summary (gate 1)

One table of requirement, figure, limit and margin from the three finished studies
(`scope/`, `awg/`, `powercal/`), written for the spec lead's review. Every figure is
copied from the study that owns it; the SC-7 sums in section 2 are arithmetic on those
figures. Taken at the commit after `63fa096`; the AWG study is being reworked for the
reference filter decision, so rows marked (AWG) will move.

Legend: PASS* a condition remains; [C] rests on a *(check)* or an assumption; [D..] accepted
by that decision; [CD] cost-down candidate.

Models: scope = ngspice 47 with the TPH2501 vendor macro (a single amplifier, not the
TPH2502) and the datasheet-fitted BEH21/BEH60, a 200k-draw Monte Carlo and 128 corners;
AWG = ngspice plus closed-form `design.py` (200k draws x 3 AREF, scenarios A and B, hard
corners); power = Python scripts, hand estimates and one converged LM27762 run.

## 1. Requirements

| Req | Limit | Figure | Margin | Verdict | Flags |
|---|---|---|---|---|---|
| AN-1 | PM ≥ 45° | scope ≥ 60.2° (BEH60); AWG 50.5° (BEH60, weak rail, 10 pF at the inverting node) | scope +15°, AWG +5.5° | PASS | [C] datasheet-fitted models; LR-4 must hold the inverting-node stray |
| SC-10 | settle 0.5 LSB in 667 ns | 203 ns, pin Z 22 Ω | 464 ns | PASS | [C] ADC input 3.8 k/6 pF derived; [CD] Riso |
| AW-1 | −1.5 to +1.71 V; window top ≤ 2.2275 V; use ≤ 92 % | top 2.202 V hard corners; width 86.2 %; position-aware 92.0 % (0.9198) | +0.025 V; **+0.0002** | PASS (fragile) | [D-V2-7] [D-V2-12] (AWG) |
| AW-2 | ≤ 1.5 mV/code | 0.964 mV | +0.536 mV | PASS | DAC DNL not included |
| AW-3 | ≥ 8 MHz | 8.39 MHz worst corner (8.88 nominal; 7.27 into 100 pF of cable, info) | +0.39 MHz | PASS | slew 10.3 V/µs needed against 180 |
| AW-4 | 50 Ω ±1 %, Basic | 2×100 Ω 1 % 1206 | | PASS | |
| AW-5 | ≤ 0.1 mA | 95.2 µA at the DAC's top code | +4.8 µA | PASS | [D-V2-12] judged at DAC codes |
| AW-6 | ≤ 0.3 mV (D22) | 88.6 µV with REF noise | 3.4× | PASS | [D22] [C] REF noise above 10 kHz |
| AW-8 | within the rails | −2.021 … +3.406 V | | PASS | afe-v2's +3.3 V is stale |
| EN-1 | ≤ 0.2 % over 20 K | 0.215 % | −0.015 % | accepted | [D-V2-3] [C] 100 ppm/K expected |
| PA-2 | ≤ 10 mA | 7.69 mA source; dropout +17 mV | +2.31 mA | PASS | thin dropout; (AWG) |
| PA-3 | device-sequenced staircase | 1.5–3.1 s for 1024 levels | | PASS | [D21] [D23] |
| PA-4 (tracking) | 0.05 % / 3 mV | 0.050 % / 1.73 mV | 0.000 % | PASS | [C] Zcm tracking assumed; VT-21 |
| PA-4 (independent) | same | 0.225 % / 2.35 mV | −0.175 % | information | [D-V2-14] |
| PA-9 | taps are checks | worst tap Z 495 Ω = 0.31 LSB | | PASS | [D-V2-13] |
| PR-1 | ±12 V, edge ≤ 10 mA | 6.6 / 9.1 mA | +0.9 mA | PASS* | [C] diode I-V assumed |
| PR-3 | rail ≤ 0.5 V unpowered | 0.378 V with a 10k bleed | +0.122 V | PASS | [C] 0.3 V clamp drop assumed |
| PR-2 | −0.2 … 3.45 V | adversarial arm −0.142 V with BAV99 | +0.06 V | PASS* | [C]; [CD] BAV99 |
| PR-4 | restated by the supply-pin rule | +0.73 V / −0.52 V | +4 / +10 mA | PASS | [D-V2-12] |
| PW-1 | ≤ 100 mA; ≤ 450 mA with the Due | 82.3 mA; 417.6 mA | +17.7 / +32 mA | PASS | [C] IQ typical only |
| PW-2 | ≤ 20 mV | 0.16 mV model | | PASS | [C] model under-reads; VT-8 |
| PW-3 | short ≤ 60 mA at the supply pin | +pin 58.7 mA | **+1.3 mA** | PASS (thin) | [D-V2-7]; reset-level short 76 mA accepted transient [D-V2-12] |
| PW-6, PW-7 | 4.50–5.25 V; ≤ 15 s | 1.08 V headroom; 2.5 ms | | PASS | |
| SC-2 | pin ≥ 80 mV inside 0…AREF | slack 60.6 mV low / 111.2 mV high | | PASS | |
| SC-3 | 1 MΩ ±1 % plus spread; ≤ 30 pF | 1004.08 k; 15.9 pF | | PASS | [D-V2-9]; HF step ±6.1 % static PASS* |
| SC-4 | ≤ 1.8 mV/code | 1.761 mV; span 70.34 % | 0.039 mV | PASS (thin) | accepted at 70.34 % |
| SC-5 | no filter | −3 dB at 40 MHz | | PASS | |
| SC-6 | ≤ 0.2 mV at the sampling capacitor (D17) | 46–88 µV macro; 31–42 µV datasheet density | 2.3× | PASS* | [C] switch resistance unmeasured |
| SC-8 | gain within 3 % | 1.78 % | +1.22 % | PASS | [CD] only catches mis-assembly |
| SC-9 scope-scope | ≤ 2 LSB to 10 MHz | circuit 7e-6 LSB; layout budget 0.02 pF N-N + 0.02 pF pad-pad = 1.72 LSB | 0.28 LSB | PASS* | [D16] [C] 20 fF between pins 3 and 5 not known reachable |
| SC-9 AWG-scope | ≤ 2 LSB | 0.207 LSB | +1.79 LSB | PASS | [C] 10 mΩ plane return assumed |
| SC-12 | undistorted to 5 MHz | THD −100 dB at 5 Vpp; slew 36 V/µs against 160 | 3.7× | PASS | [C] macro THD |
| SM-3 | ≥ 8 MHz at the ADC pin (D20) | −3 dB at 40 MHz at the pin; 6.8 MHz at the sampling capacitor | 5× at the pin | PASS* | [D20] |
| V2-2 | duals only, ≤ 2 types, rail sum ≤ 5.5 V | 5.4707 V | +29 mV | PASS (thin) | [C] 5.5 V is the datasheet's specified range, no recommended-operating table |
| V2-3 | Basic passives only | all Basic | | PASS | board-house page not read; `jlc-basic.csv` cited |

Not simulated: DF-1..4, SM-6, PW-4.

## 2. The whole SC-7 stack

Worst-case linear on the tracking-Zcm basis (D-V2-14), with the independent ±25 % case as
information. 10 K since calibration, percent of reading.

| Term | Gain % tracking | Gain % independent | Offset mV (trk / ind) | Source |
|---|---|---|---|---|
| REF3030E (initial, 15 ppm/K, hysteresis, long-term) | 0.129 | 0.129 | 0 | power |
| Sense ratio, structure S3 + 10k | **0.050** | 0.225 | 1.73 / 2.35 | power [C] tracking |
| Extrapolated tee fit to +3.5 V (random-knot INL, 1.2 LSB) | 0.064 | 0.064 | 0 | power [C] |
| Scope: R1 vs R2‖R3 drift, 100 ppm/K opposed | 0.108 | 0.108 | | scope |
| Scope: REF modulation into the offset | | | 0.36 | scope (may overlap the REF term) |
| Scope: VOS drift 2 µV/K | | | 0.04 | scope |
| **Linear sum** | **0.351** | **0.526** | **2.13 / 2.75** | |
| RSS | 0.187 | 0.288 | | |
| Limit | 0.5 | 0.5 | 5 | |
| **Margin** | **+0.149** | **−0.026 linear, +0.212 RSS** | **+2.87 / +2.25** | |

Missing as separate terms: ADC pin offset, ADS1115 INL, and the AWG's own error feeding the
tee (the AWG is read by the ADS1115, so it enters through the sense term). The sense term
with tracking is 0.050 %; the 0.243 % in the power study is its whole-block sum.

## 3. Cost-down candidates (candidates only)

| # | Item | Margin | Possible saving | Blocker |
|---|---|---|---|---|
| 1 | BAV99 at each ADC pin | PR-2 +0.06 V with, −0.09 V without | 2 placements | VT-5 unpowered read |
| 2 | Riso 22 Ω at each pin | SC-10 225×; PM ≥ 49° without | up to 2 placements | isolates the BAV99; rerun AN-1, SM-3 |
| 3 | C1 20 pF + Cn 10 pF instead of 22 + 12 | step p95 6.5 % against 5.8 % | one C0G value | decided: keep 12 pF |
| 5 | scope dual's 1 µF | PW-2 30×, SC-6 15× (model under-reads) | 1 placement | model |
| 7 | ladder's three unmeasured taps | taps are checks | up to 3 resistors | PA-9 minimum |
| 8 | sense matching 10k | helps only if Zcm tracks | 1 placement | VT-21 decides |

## 4. Cross-study contradictions found

1. The power study's extrapolation assumes a window top of 2.05 / 2.2275 V and a sweep to
   +2.28 V; the AWG's guaranteed commandable top is +1.71 V and the lowest window top is
   1.862 V. **The fit has not been run at that top**, and a shorter sweep extrapolates
   further.
2. afe-v2.md still says a 249 Ω ladder and input 3 = a ladder tap with k = 1/2; the power
   study has six 330 Ω rungs and input 3 = B with k = 0.4.
3. The AWG's PR-2 rows use 1.5 kΩ where the chosen DAC0 series resistor is 2.4 kΩ (stale,
   conservative).
4. The power study's reset-with-short figure (66.5 mA in its note) disagrees with its own
   table (100.7 mA total on OUT+) and with the AWG's 76 mA at the pin.
5. The sense row is 0.231 % / 2.4 mV in design.md and 0.225 % / 2.35 mV in report.md.
6. The REF3030E grade: scope uses ±0.2 % initial, power and afe-v2 use the E grade ±0.1 %.

## 5. Not covered by any study

Layout parasitics (VT-19) and every VT test on a board; a vendor TPH2502 model; the
unpowered TPH2502 input structure; the Due's ADC input switch; DAC DNL; the AWG's
swing-versus-current curve and supply-pin-rating duration; the REF3030E's output impedance
above DC (now being bounded by the AWG study); only one LM27762 transient run converged.
