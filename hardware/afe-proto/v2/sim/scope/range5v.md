# AFE version 2 with the scope range of version 1: +-5 V nominal, usable +-6 V

Owner decision, 2026-11-13 (relayed by the spec lead): the scope range of version 2 becomes version 1's, SC-2 and SC-4 as in
`docs/afe.md`. It replaces `-1.5 .. +3.5 V` (usable -2.0 .. +4.0 V, 1.8 mV per code). **A values change on the same circuit and the same
layout**: no topology change, no new op-amp, the same six resistors and two capacitors per channel in the same positions. Nothing here
edits `docs/afe*.md`, a board or the gate 3 package.

Everything below is reproducible: `range5v.py` (closed form, numpy only), `run.py --range 5v` (ngspice, the ported v2 scope study with the
values of this note), `range5v_collect.py` (the tables). Results are in `range5v/`. Figures marked *(check)* are open.

## 1. The new values, per designator

Per channel; CH1 is the 1xx refs, CH2 is the same + 100 (`v2/kicad/design.py`). All parts are 0603 and JLC Basic (`v2/jlc-basic.csv`).

| Ref (CH1 / CH2) | Role | Old | **New** | LCSC (new) | Basic |
|---|---|---|---|---|---|
| R101 / R201 | R1a, IN to M1 | 510k | **470k** | C23178 | yes |
| R102 / R202 | R1b, M1 to N | 30k | **300k** | C23024 | yes |
| R103 / R203 | R2a, N to M2 | 1M | **470k** | C23178 | yes |
| R104 / R204 | R2b, M2 to GND | 510k | **330k** | C23137 | yes |
| R105 / R205 | R3a, N to M3 | 470k | **330k** | C23137 | yes |
| R106 / R206 | R3b, M3 to VREF | 200k | **0R** | C21189 | yes |
| C101 / C201 | C1 across R1 | 22p C0G | **18p C0G** | C1647 | yes (jlc-basic.csv, 0603, read 2026-11-12) |
| C102 / C202 | Cn, N to GND | 12p C0G | **47p C0G** | C1671 | yes (same read) |
| R107 / R207, C103 / C203, R108 / R208, D101 / D201 | Rnp 470, Cpx 10p, Riso 22, BAV99 | | **unchanged** | | |

The resistors are version 1's values (`kicad/design.py` of version 1: R101 470k + 300k, R201 470k + 330k, R3 330k) in version 2's positions, with a 0R
where version 1 has one part (R3). R1 = 770k, R2 = 800k, R3 = 330k. **Rnp stays 470 ohm** (version 1 has 680): the 12 V edge reads 0.82 mA with
Rnp 470 against the datasheet's 10 mA (section 3).

**Adopted: C1 18p (C1647) / Cn 47p (C1671), the spec lead's decision of 2026-11-13** (both confirmed JLC Basic, 0603 C0G 5 %, in `v2/jlc-basic.csv`).
Version 1's capacitors, C1 12p (C38523) / Cn 30p (C1658), are kept in the figures for the D-V2 record: they leave the divider's HF/DC step at 95 % within
+-12.9 % on version 2's stray assumption, twice what version 2 accepted (+-6.1 %); 18p / 47p give +-7.2 % at the same two capacitors per channel
(section 4). Every figure below is given for both pairs.

BOM effect (derived from `v2/kicad/design.py`, which uses each removed value only in the scope): part types out 510k C23192, 30k C22984, 1M C22935,
200k C25811, 22p C1653, 12p C38523; in 300k C23024, 330k C23137, 18p C1647, 47p C1671 (470k C23178 and 0R C21189 are already on the board).
Placements are unchanged except R106 / R206, a resistor that becomes a 0R. Prices not re-read *(check)*.

## 2. Derivation

The input reaches the follower through R1 from the input, R2 to ground and R3 to the REF3030E (3.000 V): attenuation a = Rp / R1, centre
Vr Rp / R3, input resistance R1 + R2 || R3, with Rp = R1 || R2 || R3 (`budget/v2_scope.py` for the algebra).

| Requirement | Reading | Gives |
|---|---|---|
| SC-4: 10 V occupies 70..75 % of full scale at nominal AREF 3.25 V | a = 0.70..0.75 x 3.25 / 10 | a = 0.2275 .. 0.2438; middle 0.2356 |
| SC-3: 1 Mohm +-1 %, nominal | R1 / (1 - a) = 1 Mohm | R1 = 764k at a = 0.2356 |
| Centre at AREF / 2 for an input of 0 V | Vr Rp / R3 = 1.625 V | R3 = 332k |
| R2 | 1/Rp = 1/R1 + 1/R2 + 1/R3 | 809k |

Built from Basic values in the six positions: R1 470k + 300k = 770k, R2 470k + 330k = 800k, R3 330k + 0R = 330k. `range5v.py` searches every
one- or two-part build of R1, R2, R3 from the Basic 0603 resistors, keeps those with SC-3 within 1 %, SC-4's 70..75 % at the 128 corners of
1 % parts, and ranks them by the worst SC-2 margin over those corners (VOS and the +-30 mV centring error included): **version 1's set is the best
five-part build** (slack 44.5 mV on the closed form); the only better ones need six parts (R3 300k + 33k, +26 mV) and R2 470k + 300k, which is
5 parts and +26 mV but drops the 1 % span corner to 69.9 % against SC-4's 70 %. Not worth a part or a requirement.

Nominal (closed form, and the ngspice DC sweep agrees to 0.11 mV):

| | v2 old (-1.5..+3.5 V) | **5 V** |
|---|---|---|
| R1 / R2 / R3 | 540k / 1.51M / 670k | 770k / 800k / 330k |
| Attenuation a | 0.4622 | **0.2328** |
| Centre at the node (0 V in; old: +1.0 V in is 1.625 V) | 1.1175 V | **1.6295 V** |
| Input resistance (SC-3) | 1004.1 k | **1003.6 k** (+0.36 %) |
| Rp / R3 (how much of the REF reaches the pin) | 0.3725 | **0.5432** (x1.46) |
| Pin at the range ends | 0.193 .. 2.966 V (-2 / +4 V) | **0.233 .. 3.026 V** (-6 / +6 V) |
| Codes per volt at the input, AREF 3.25 V | 582 | **293** |
| REF3030E load per channel (source at -6 V / sink with the node clamped) | 4.2 / 1.6 uA | **8.5 / 3.2 uA** (rating +-10 mA) |

REF3030E: two channels source at most 17 uA and sink at most 6 uA; the datasheet's load regulation (150 ppm/mA) moves VREF by under 3 uV, the
resistance it needs to see is unchanged. The REF reaches the pin 1.46 times more strongly (Rp / R3), which scales the REF noise and the AWG-offset
coupling through it, both in section 3.

## 3. Checks against the requirement text

All DC rows are the 200,000-draw Monte Carlo of `run.py` section `mc` (1 % resistors, 0.2 % REF, 5 % C0G, +-0.5 mV VOS and the CMRR term, +-30 mV centring)
and the 128 corners; `range5v.py` reproduces them in closed form (margins 167.3 / 124.5 mV there, the Monte Carlo 170.5 / 127.7 mV).

| Req | Limit | v2 old | 5 V, C1 12 / Cn 30 (version 1's, kept for the record) | **5 V adopted, C1 18 / Cn 47** | Verdict |
|---|---|---|---|---|---|
| SC-2 low: pin >= 80 mV above 0 at -6 V (AREF 3.20, +-30 mV) | 80 mV | 140.6 mV at -2 V | **170.5 mV** (slack 90.5) | same | PASS |
| SC-2 high: pin >= 80 mV below AREF at +6 V (AREF 3.20) | 80 mV | 191.2 mV at +4 V | **127.7 mV** (slack **47.7**) | same | PASS |
| SC-4 mV per code at the input (AREF 3.30, smallest a) | 4 mV (afe.md; v2 amended 1.8) | 1.761 | **3.510** (corners 3.515) | same | PASS |
| SC-4 span of +-5 V in full scale (AREF 3.25) | 70..75 % | 70.40..71.80 | **70.62..72.63** (corners 70.53..72.73) | same | PASS (0.53 % over the floor) |
| SC-3 input resistance | 1 Mohm +-1 % nominal, spread on top | 1004.1 k; 995.0..1013.3 k | **1003.6 k; 994.1..1013.3 k** | same | PASS |
| SC-3 input capacitance incl. wiring | <= 30 pF | 15.9 pF | **13.5 pF + 4 pF = 17.5 pF** | 18.0 + 4 = 22.0 pF | PASS |
| SC-3 HF/DC step (compensation), 95 % of boards, stray 2..6 pF | design call: +-6.1 % accepted for v2 | +-6.1 % (mean -0.5) | **+-12.9 %** (mean -7.3, worst -17.2/+4.0) | **+-7.2 %** (mean -1.7, worst -11.3/+9.1) | see section 4 |
| SC-3 x10 probe ripple, 10 Hz..10 MHz, Cp trimmed | information | 1.5 % at 1.80 pF | 2.9 % at 1.68 pF | 2.5 % at 2.08 pF | information |
| SC-5 / SM-3 -3 dB at the pin (worst of 3 models) | >= 8 MHz, no filter | 39.9 MHz | **38.4 MHz**; -0.28 dB at 10 MHz | 35.5 MHz; -0.31 dB | PASS |
| SC-6 noise at the sampling capacitor (D17, vendor macro / datasheet density; low-R arm) | <= 200 uV | 88.2 / 41.8 uV | **90.4 / 46.4 uV** (REF at the pin 27.7 uV, was 19.0, inside) | 90.3 / 46.4 uV | PASS |
| SC-7 scope terms, 10 K: R1 vs R2 \|\| R3 drift; REF into the centre (at the input); VOS drift | with the stack of `v2/sim/summary.md` section 2 | 0.108 %; 0.36 mV; 0.04 mV | **0.154 %; 1.05 mV; 0.09 mV** | same | PASS, stack below |
| SC-8 gain match of the two channels (200,000 draws) | 3 % (afe-v2.md 3.1; D19: 5.5 %) | 1.78 % | **2.45 %** (128 corners 3.12 %, information) | same | PASS (0.55 % margin) |
| SC-9 scope to scope, 10 MHz, full-scale input, budget 0.02 pF N-N + 0.02 pF pad-pad | <= 2 LSB | 1.72 LSB at 6 Vpp | **1.45 LSB at 12 Vpp** (1.21 at the rated 10 Vpp) | 1.28 LSB at 12 Vpp | PASS |
| SC-9 shared REF alone (no layout stray), 10 MHz | <= 2 LSB | 7e-6 | 6e-6 | 7e-6 | PASS |
| **SC-9 AWG into scope through the REF, 1.9 kHz, +-1.6 V swing (simulated, below)** | <= 2 LSB | 1.68 LSB | 2.45 LSB at Rvr 100 | 2.44 at Rvr 100; **1.87 at Rvr 130** | fails at Rvr 100; **PASS at 130 (+0.13)** |
| SC-10 settle in the 667 ns window, +6 V / -6 V through the derived ADC input; pin impedance | 0.5 LSB; <= 5 kohm | 203 ns; 22.2 ohm | **205 ns, 0.04 LSB at the end; 22.2 ohm** | 205 ns, 0.03 LSB | PASS |
| SC-12 slew, 12 Vpp at 10 MHz at the input (pin slew) | not slew-limited (datasheet 160 V/us) | 84 V/us | **79 V/us**, THD 0.0013 % at 5 MHz | 83 V/us | PASS |
| AN-1 phase margin (BEH60 / BEH21 / vendor), nominal; worst of the Riso x load grid | >= 45 deg | 60.2 / 60.2 / 69.9; 49.4 | **60.1 / 60.1 / 69.9; 49.0** | 60.0 / 60.0 / 69.8; 48.3 | PASS |
| PR-1 edge, 12 V from 50 ohm, 2 ns, peak diode current with Rnp 470 (+12 / -12 V) | 10 mA (datasheet note 3) | 6.6 / 9.1 mA | **0.49 / 0.58 mA** | 0.82 / 0.91 mA | PASS (9.4 mA margin, was 0.9) |
| PR-1 edge, 30 V / 5 ns (information) | | 25 mA | 9.9 mA | 10.2 mA | information |
| PR-1 DC, +-12 V on both inputs, powered | pins in 0..AREF, inside the clamp | | pin 3.29 V / 0.01 V, 10.6 / -14.9 uA through R1 | same | PASS |
| PR-2 pin range unpowered, adversarial diode (BAV99 at the pin) | -0.2 .. 3.45 V | -0.142 V | **-0.134 V** (0.066 V margin) | same | PASS* (diode I-V assumed) |
| PR-3 unpowered rail with +12 V on both inputs; largest bleed that holds 0.5 V | rail <= 0.5 V | 0.365 V at 10k; 14.1 kohm | **0.220 V at 10k; 26.5 kohm** | same | PASS (looser) |
| REF3030E load | +-10 mA | 4.2 uA | 8.5 uA | 8.5 uA | PASS |

### SC-7 stack on the new range, with the tee-fit row re-derived (`range5v_sc7.py`, `range5v/sc7_5v.json`)

The fit is `../powercal/sc7.py`'s Monte Carlo, imported and run unchanged except for the scope's map (a = 0.2328, centre 1.6295 V) and the points
extrapolated to. Its assumptions stand, all *(assumed, VT-23)*: a straight line of Due code against AWG volts over a 1024-point staircase from the
sweep's kept bottom -1.923 V to the window top; the Due ADC's INL a cubic bow (0.5 or 1.2 LSB), a parabolic bow (1.2 LSB) or random knots every 8 codes
(1.2 LSB); Due gain -1.56 / +0.29 % and offset -30..+56 codes; a +-0.5 LSB channel offset between the scope pin and the ladder pin; the scope's own pin
map unknown to the host (a +-2 %, centre +-30 mV); 99.9th percentile of 800 draws per cell; ladder anchors not used (D-V2-13). The AWG now covers
-1.923 .. +1.785 V (the lowest window top, the design's worst case) of the +-5 V, 3.7 V of 10 V, 37 % of the rated span (32 % for its commanded +-1.6 V);
both ends are extrapolated (v2's old range extrapolated only the top). One Due LSB is 3.43 mV at the input now (1.73 mV before).

| 99.9th percentile error at the input, mV | -6 V | -5 V | +5 V | +6 V |
|---|---|---|---|---|
| cubic 0.5 LSB | 3.05 | 1.76 | 1.76 | 3.05 |
| cubic 1.2 LSB | 7.31 | 4.23 | 4.23 | 7.33 |
| parabolic 1.2 LSB | 2.90 | 1.97 | 2.09 | 3.04 |
| **random knots 1.2 LSB (the worst model)** | 6.49 | **5.79** | **5.98** | 6.25 |

(window top 1.785 V; the 1.6 V and 2.133 V tops move the knots row to 5.73 / 6.08 and 5.54 / 5.82 mV at -5 / +5 V; `sc7_5v.json` has all twelve rows.
The guard, an INL of 12 LSB, reads 42 mV at +5 V and breaks the share, so the check can fail.)

**The fit's own share of SC-7 (0.1 % of the reading, 5.0 mV at 5 V) is exceeded by the worst INL model: 5.98 mV = 0.120 % at +5 V** (cubic models are
inside it, 4.2 mV). v2's old range read 2.35 mV = 0.067 % of 3.5 V. The cause is the 3.4 times larger Due LSB at the input and an extrapolation of 3.3 V
on each side. The **whole of SC-7 still holds** (v2's stack of `v2/sim/summary.md` section 2 and `../powercal/results/sc7.json`, the scope row and the
fit row replaced; gain terms in % of reading at the 5 V end, offset in mV):

| Term | Gain %, tracking | Gain %, independent | Offset mV (tracking / independent) |
|---|---|---|---|
| REF3030E | 0.129 | 0.129 | 0 |
| Sense ratio (powercal) | 0.050 | 0.224 | 1.73 / 2.46 |
| **Tee fit extrapolated to +-5 V (new: was 0.064 to 3.5 V)** | **0.120** | **0.120** | 0 |
| **Scope: R1 vs R2 \|\| R3 drift, 100 ppm/K opposed, 10 K (new: was 0.108)** | **0.154** | **0.154** | |
| Scope: REF modulation into the centre (new: was 0.36) | | | 1.05 |
| Scope: VOS drift 2 uV/K | | | 0.09 |
| **Linear sum** | **0.453** | **0.627** | **2.87 / 3.60** |
| RSS | 0.239 | 0.324 | |
| Limit | 0.5 | 0.5 | 5 |
| **Margin** | **+0.047 linear, +0.261 RSS** | **-0.127 linear, +0.176 RSS** | **+2.13 / +1.40** |

On D26's rule (common-cause terms linear, independent terms RSS) the stack passes on both bases; the tracking basis passes even on the plain linear
sum, with **0.047 % of margin, thin** (v2's old range: +0.149). The independent basis fails the plain linear sum, as it already did (information, -0.026 before). At
the usable +-6 V the fit reads 7.4 mV (0.123 %), information. Gain drift EN-1 over 20 K goes 0.215 -> **0.307 %**, inside afe.md's relaxed 0.34 % (D19) and the
design's computed worst case of afe-v2.md D-V2-3. VT-23 measures the residual on the board.

### AWG into scope coupling through the REF, in the simulator (`range5v_refcoupling.py`, `range5v/refcoupling_5v.json`): fails 2 LSB at Rvr 100, passes at 130 (resolution below)

How the AWG study gets its figure (`../awg/run.py` `case_ref`): the AWG's offset current moves the REF3030E output by m volts peak to peak (3.662 mV at
1885 Hz for the full commanded +-1.6 V swing, the output impedance read from the datasheet's Fig. 6-14, peak 115 ohm *(check)*), and that reaches the pin
through R3 and the divider; 1 LSB is 3.3 V / 4096 = 0.806 mV at the pin. (Powercal's 0.133 LSB is a different path, the rail and the plane, and is
unchanged; the 0.207 LSB quoted before the +-1.6 V ruling is superseded: the AWG study now reads 1.69 LSB for this path, margin +0.31.) Here m is applied
as a source on the reference node of the ported scope netlist, both channels present, and the pin's response is read from ngspice at that frequency:

| scope network | pin / REF at 1885 Hz | pin | **LSB (limit 2)** | 110 ohm flat bound (information) | 28 ohm loaded (information) |
|---|---|---|---|---|---|
| v2 old (control: reproduces the AWG study's 1.693) | 0.3688 | 1.351 mV | 1.676 | 3.05 | 0.78 |
| 5 V, 12p / 30p | 0.5394 | 1.975 mV | 2.452 | 4.44 | 1.13 |
| **5 V adopted, 18p / 47p** | **0.5357** | **1.962 mV** | **2.435, over by 0.435** | 4.44 | 1.13 |

**This is a failure on the new range and not a scaling artefact.** The REF reaches the pin by Rp / R3 = 0.543 (measured 0.536 at 1885 Hz including the node
pole), and that ratio is fixed by the requirement that the REF set the centre (Vr Rp / R3 = 1.63 V of 3.0 V): any resistor set meeting SC-2 and SC-4
has it, so a scope-side value change cannot recover it. The levers are on the AWG / REF side, outside this note's files: the movement m scales with the
offset filter, 1 / (Rvr C) above its corner, so (the AWG study's own formula `ref_move`, `Rg2` 3k, `Cvr` 14 uF, all else unchanged, derived, not a
design) **Rvr 100 -> 120 ohm gives 2.03 LSB, 130 gives 1.88, 150 gives 1.63, 200 gives 1.22**; or a larger capacitor at the REF output pin (10 uF:
1.24 LSB on the graph read as a resistive magnitude *(check: Fig. 6-14 states no output capacitance)*). Rvr is in the AWG's window arithmetic (offset
current through Rg2 + Rvr), so it belongs to that study. Not relaxed here.

#### Resolution: Rvr 130 ohm (spec lead, 2026-11-13), simulated (`range5v_refcoupling.py --rvr`, `range5v/refcoupling_rvr_5vc.json`)

The scope network is the adopted one (18p / 47p), both channels, ngspice at each case's peak frequency; the stimulus is the AWG study's REF swing at each Rvr
(`ref_move` of `../awg/run.py`, copied and checked against the committed `awg/raw/results.json`: 2.8192 mV at 1885 Hz at Rvr 130, equal to the digit).
Cases A and B are the stray cases of `../sensitivity_n_stray.json` (4.31 pF / 0.81 pF at N).

| Rvr | REF swing at 1.9 kHz | LSB baseline | LSB case A | LSB case B | Against 2 LSB |
|---|---|---|---|---|---|
| 100 (before) | 3.662 mV | 2.435 | 2.434 | 2.437 | fails |
| 120 (C22787) | 3.054 mV | 2.030 | 2.030 | 2.032 | **fails by 0.03 (no margin; the AWG accepts it)** |
| **130 (120 C22787 + 10 C22859)** | **2.819 mV** | **1.874** | **1.874** | **1.876** | **PASS, +0.126 LSB** |
| 140 | 2.618 mV | 1.741 | 1.740 | 1.742 | pass, +0.26 |
| 150 | 2.444 mV | 1.625 | 1.624 | 1.626 | pass, +0.38, but the AWG refuses it (AC top 2.234 V, supply pin 60.1 mA) |

The stray cases move the figure by 0.002 LSB: the transfer is the resistive Rp / R3 at 1.9 kHz. **At Rvr 130 the SC-9 AWG-to-scope row passes at 1.88 LSB, 0.13
LSB of margin (thin, and resting on a graph read by eye, *(check)*, VT-10).** The AWG study's own figure at 130 is 1.30 LSB at its 0.3725 factor; the 1.88 is the
same swing through the new network.

### The pin at 3.03 V against a 3.21 .. 3.39 V rail: the TPH2502's common-mode range and CMRR (`models/tph2502/tph2502.pdf`, Rev. A)

* **Input common-mode voltage range, p. 3, Electrical Characteristics, row "VCM": V- - 0.1 V (min) to V+ - 0.1 V (max)**, no typical, no test condition. So
  the datasheet's input range ends 0.1 V below the positive rail (the "rail-to-rail input" of the title and p. 8 is a claim of no phase reversal, Fig. 1,
  not a range). With V+ at its low corner 3.22 V (`../powercal`'s rails 3.220 .. 3.418 V) the limit is **3.12 V**; the scope node's worst corner is **3.044 V**
  (128 corners of 1 % parts and 0.2 % REF, +6 V in, VOS included), **margin +76 mV; on v2's old range 2.98 V, +142 mV**. It passes, and is the thinnest
  analog margin after SC-2's high side.
* **CMRR, p. 3, row "CMRR": 65 dB min, 85 dB typ, VCM = -1 V to 3 V, VS = 5.4 V.** Not stated at VS = 3.3 V or near the rail; the CMRR-vs-temperature
  curve on p. 6 is at the same conditions. The study's VOS allowance already carries the 65 dB over the swing (`CMRR_ERR` 1.7 mV at the pin, in the margins above);
  the new common-mode swing is 2.8 V at the node (0.23 .. 3.05 V), the old 2.8 V (0.19 .. 2.97 V), so the term is the same size at the pin and 2.1 times
  larger at the input (6.9 mV against 3.3 mV at 65 dB, **the linear part of which the tee calibration removes**; what it cannot remove is a crossover step,
  which no datasheet figure covers).
* **VOS, p. 3: +-500 uV max at VCM = VDD/2 + 0.5 V only**; no VOS-versus-VCM curve in the document (p. 6 has CMRR and PSRR versus temperature only).
  So an input-stage crossover or offset step near V+ - 0.1 V is **not described by the datasheet** and stays *(check)*.

Proposed VT line (VT-23 already catches "an op-amp input-stage offset step"; this extends it to the new range; text for the spec lead, not edited into
`docs/afe*.md`): **"VT-23 (addition). Scope linearity at the top of the range: the DC sweep includes the last 0.3 V of the node below the amplifier's
V+ - 0.1 V common-mode limit (input +5.2 to +6 V, node 2.85 to 3.05 V) in steps of at most 10 mV, at the AFE's measured +3.3 V_A and again with that rail
0.1 V lower on a bench supply; the residual after PA-3's fit stays within SC-7's fit share at both, and any step is reported with the rail. Covers the
TPH2502's input-stage behaviour and CMRR near the rail at 3.3 V, which datasheet Rev. A (p. 3) states only as VCM <= V+ - 0.1 V and CMRR at VS = 5.4 V."**

**Downstream, derived:** the codes per volt halve (582 -> 293), so a full AWG loopback (about 3.55 V) spans about 1,040 codes at 3.25 V (was about 2,100 to 2,200) and a 1 V signal about 293 (was about 590); afe.md's PAM table for the +-5 V range applies again in place of afe-v2.md section 3.1's last rows.

### Stray-capacitance cases A and B (SC-9, SC-5, AN-1; `range5v/sensitivity_n_stray_5v.json`)

The extraction numbers are those of `../sensitivity_n_stray.json`: A adds 0.81 pF at N to the 3.5 pF assumption (4.31 pF), B replaces it (0.81 pF),
N-to-N 0.05 fF in both. Same metrics, same definitions.

| | v2 old: base / A / B | **5 V 12 / 30**: base / A / B | **5 V 18 / 47**: base / A / B |
|---|---|---|---|
| HF/DC step, nominal | -0.59 / -2.21 / +5.19 % | -7.17 / -8.46 / -2.62 % | **-1.68 / -2.67 / +1.73 %** |
| -3 dB at the pin, worst model (MHz) | 39.9 / 39.9 / 39.9 | 38.4 / 38.4 / 39.9 | 35.5 / 35.5 / 36.9 |
| SC-9 budget 0.02 + 0.02 pF, 10 MHz (LSB, 12 Vpp for the 5 V columns) | 1.72 / 1.67 / 1.90 | 1.45 / 1.42 / 1.57 | 1.28 / 1.26 / 1.35 |
| N-N stray for 1 LSB (fF) | 27.8 / 28.7 / 24.7 | 34.5 / 35.5 / 31.2 | 46.2 / 47.2 / 43.1 |
| pad-pad stray for 1 LSB (fF) | 19.1 / 19.4 / 17.6 | 21.4 / 21.8 / 20.1 | 21.3 / 21.5 / 20.5 |
| AN-1 nominal PM, vendor / BEH21 / BEH60 | 69.9 / 60.2 / 60.2 in all three | 69.9 / 60.1 / 60.1 in all three | 69.8 / 60.0 / 60.0 in all three |

SC-9 holds in all three cases with 0.4 to 0.7 LSB to spare, better than version 2's own because the pin signal is the same and the input swing
is what changed; the N-N budget of 20 fF stands. (The cases leave `mc` alone, as in the v2 file: it draws its own stray.)

## 4. The one open item: compensation (C1 / Cn), not a numbered requirement

SC-3 asks for a compensated divider for x1 and x10 probes. Version 2 accepted a +-6 % step from 5 % C0G as a design call because it is static
(`afe-v2.md` D-V2-9, `scope/report.md`). At a = 0.2328 the same 5 % caps and 2..6 pF of stray move the step further (the divider's ratio is
smaller, so a given error in C1 / (C1 + C at N) is a larger fraction of it), and version 1's 12p / 30p are centred on a stray of about 0 pF:

| C1 / Cn | mean step | 95 % | 99 % | worst of 200,000 | case B (0.81 pF, the extraction) | network C |
|---|---|---|---|---|---|---|
| 12p / 30p (version 1's) | -7.3 % | **12.9 %** | 14.6 % | -17.2 / +4.0 % | -2.6 % | 13.5 pF |
| **18p (C1647) / 47p (C1671)** | -1.7 % | **7.2 %** | 8.8 % | -11.3 / +9.1 % | +1.7 % | 18.0 pF |
| (v2's own 22p / 12p on the old range, for scale) | -0.5 % | 6.1 % | 7.4 % | -9.6 / +9.2 % | +5.2 % | 15.9 pF |

`run.py` section `cscan` tries every one- and two-part pair from the Basic C0G values; **18 / 47 is the best two-capacitor pair** (`range5v/c18-47/results/cscan.json`;
four-part sets reach 4.7 %, which is a part more per channel for 2.5 points). The step stays static on the new values (spread over -6..+6 V of input
0.004 / 0.003 pp against 0.021 on the old range; temperature 0.014 / 0.015 pp per K against 0.011 pp per K); the bias-dependent control moves it by
73 pp (12 / 30) and 82 pp (18 / 47), so the sweep can see a dependent capacitor. A probe trimmer or the host's frequency calibration (SC-5) absorbs a static step. **No numbered
requirement fails with either pair**; the spec lead decides whether 12.9 % is acceptable for a design call made at 6.1 %. The cost of 18 / 47 is nil
(two capacitors per channel either way) and its 22.0 pF with the wiring is 8 pF under SC-3's 30 pF.

## 5. Checks on the checks (guards of `run.py`, 5 V runs)

Every guard of the v2 study was run on the new values. `range5v/results/guards.json` (12 / 30): all fail as intended. Two needed attention:

* **The edge guard "no Rnp must exceed 10 mA" cannot fire on 12 / 30**: with C1 at 12 pF the 12 V edge reads **4.76 mA with no Rnp at all**, under the
  limit, so Rnp is no longer what PR-1's edge rests on; the control became the 30 V / 5 ns edge (71 mA with no Rnp, fires). It *is* needed on 18 / 47
  (10.8 mA with no Rnp, fires). Rnp 470 stays on both for AN-1 and SM-3, unchanged.
* For 18 / 47, `guards.json` reads `all_fail_as_intended: false` on two controls that stopped firing: the combined 0.03 + 0.03 pF crosstalk control
  (1.92 LSB, under 2: the circuit is quieter than the control was tuned for) and the no-Riso 1 nF phase-margin control. Neither is a requirement; both
  mean "the control no longer breaks the circuit", which is the direction the design wants.
* The static-step control now builds its bias-dependent capacitors from the design's own C1 and Cn (it had 22p and 12p written in).
* The v2 default is untouched: `tests/test_v2_sim_port.py -k "scope or report or machine"` passes (12 passed in 155 s) against the frozen golden, and
  `tests/test_v2_range5v.py` (7) holds the closed form, the profile and a mutant per claim (REF disconnected, R2 330k to 300k, R1 too large, the old values on the new range).

## 6. Reproduce

```
python3 -I hardware/afe-proto/v2/sim/scope/range5v.py [--json FILE]                     # closed form, exit 0 when every check passes
docker/pcb/run.sh -m 3G -t 900 python3 -I hardware/afe-proto/v2/sim/scope/run.py --out DIR --work W --range 5v  SECTION     # one process per section:
        netlist cscan dc ac bw noise d17 tran stab beh prot xtalk static mc guards
        (--range 5vc for C1 18p / Cn 47p; A and B: add  --set Cn_par=4.31e-12 --set Cx=5e-17  and  --set Cn_par=0.81e-12 --set Cx=5e-17  with  ac bw static xtalk stab)
docker/pcb/run.sh python3 -I hardware/afe-proto/v2/sim/scope/range5v_sc7.py --json range5v/sc7_5v.json                  # SC-7 tee-fit row on +-5 V
docker/pcb/run.sh python3 -I hardware/afe-proto/v2/sim/scope/range5v_refcoupling.py --out range5v/refcoupling_5v.json   # AWG into scope through the REF
python3 -I hardware/afe-proto/v2/sim/scope/range5v_collect.py                           # sensitivity_n_stray_5v.json, summary_5v.json
```

In a 5 V run the keys named `lsb_at_6Vpp` in `xtalk.json` mean a 12 Vpp input (`XT_AMP` 6 V, the usable range), and `shelf_check_with_C1_12pF` is the
mutant `MUT_C1` (22 pF on 12 / 30, 33 pF on 18 / 47); `meta.json` names the range and its values.
