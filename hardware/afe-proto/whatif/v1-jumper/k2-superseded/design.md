# Version 1 without the ratio switch: the jumper ratio measurement (D25, PA-4)

Design note for `whatif/v1-jumper/`. Scripts are numpy only and regenerate every number here (`./run_all.sh`, about 30 s; results in `results/`).
Adapted from kvm_02's finished v2 block (`due_oscilloscope_v2/.../powercal/`: `sense.py`, `refladder.py`, `design.md`); read-only, nothing edited there.
Figures marked *(check)* are not verified. Nothing here is measured on a board.

## 0. Result

| Requirement | Limit | Result | Margin | Verdict |
|---|---|---|---|---|
| PA-4 range, wire OFF (normal use), AWG -1.35..+1.35 V, 1 % resistors, REF +-0.1 % | sense tap 0 .. 3.21 V (the +3V3A low corner, derived: 1.182 x (1 + 1.75 x 0.98); *(check)*) | 0.792 .. 2.170 V | +0.792 V / +1.04 V | PASS |
| PA-4 range, wire ON (B to TAP5) | the same | 0.573 .. 1.943 V | +0.573 V / +1.27 V | PASS |
| PA-4 range, the other two header wire states (B-TAP4, TAP4-TAP5) | the same | 0.385 .. 1.753 V and 0.792 .. 2.170 V | +0.385 V / +1.46 V | PASS |
| VT-22, every wrong position of the Due's pass-through pins (table in section 1) | passive survival: current inside 10 mA (SBAS444E 5.1), host takes no action | at most 59.5 uA into the clamp (12 V stress), 5.6 uA for the GND wire | 10 mA / 59.5 uA = 168x | PASS; **the tap itself leaves 0..3.21 V for 4 of 10 states** (GND, TAP2, and the 5 V / 12 V stresses): the rule can only be met passively there, not in range |
| PR-4, +-5 V forced on the AWG BNC, powered or unpowered, wire off or on | the same; unpowered rail below 0.5 V | 40.1 uA clamp current at -5 V; unpowered rail 0.173 V at +5 V | 250x; 0.327 V | PASS (the BAV99 holds the pin 0.1 V past the ADS1115's abs max rows, section 3 *(check)*) |
| Host verifies the wire from the readings | 20 x 3.1 mV resolution | smallest gap 177.5 mV (B-TAP4 against B-TAP5) | +115 mV | PASS |
| AW-4 / AW-6: the divider's load on the AWG node | information | 8.0 .. 21.8 uA into the node, 0.40 .. 1.09 mV across the 49.9 ohm; noise 45 nV rms (thermal) and 13 nV (reference) against 0.3 mV | 6600x on noise | PASS |
| **Ratio precision against SC-7's fit share** | **0.1 % of fit share, 0.05 % / 3 mV allotted to the sense (v2's split)** | **gain 1.12 %, offset 20.4 mV at the 99.9th percentile (median 0.28 % / 5.4 mV)** | **-1.07 % / -17 mV** | **FAIL** |

**The ratio FAILS by a factor of 22 against the 0.05 % allotment, for the same reason v2's did (0.49 % there), and it fails worse than not measuring.** The sweep error with k trusted
at 1 % parts and the wire never fitted is 1.13 % / 30.9 mV; with the jumper it is 1.12 % / 20.4 mV. What dominates is the ADS1115, not the divider (section 2).
Everything else passes with the margins above. Decide section 2's options before D25 is taken as closed.

## 1. The circuit and the jumper

```
 A (AWG BNC node, after the 49.9 ohm) --R7 100k-- T0 --R8 100k-- B --Rd 1k-- VREF (REF3030E, permanent)
                                                  |               |
                                    ADS1115 AIN0 (direct,         jumper pad "B" ----wire---- pad "TAP5" (2.4375 V, ADS1115 AIN2)
                                    BAV99 D8 at the pin)
```

| Part | Value | LCSC | Why |
|---|---|---|---|
| R7 (A to tap) | 100k 1 % 0603 | C25803 | as in `design.py` now; k = R8/(R7+R8) = 1/2 |
| R8 (tap to B) | 100k 1 % 0603 | C25803 | as now; its far end was the switch D node, now B |
| **Rd (new, B to VREF)** | **1k 1 % 0603** | **C21190** | the permanent default tie. Wire off: B = 2.975 .. 2.995 V; wire on: the wire holds B at TAP5 and Rd pulls TAP5 up by 0.097 V (B = 2.528 .. 2.546 V, read on AIN2, so the loading is measured, not an error) |
| D8 | BAV99 (Nexperia BAV99,215) | C2500 (Basic, `jlc-basic.csv`) | replaces the BAT54S at the pin; the SOT-23 pin map is the same (1 anode to GND, 3 to the tap, 2 cathode to +3V3A), so the netlist is unchanged |

**No separate series resistor is fitted.** The divider is the series resistor: with B held by any wire the source impedance at T0 is R7 || R8 = 50k, with B floating
(wire off, Rd to the stiff VREF) it is R7 || (R8 + Rd) = 50.2k, so no state puts less than 50 kohm between a forced voltage and the ADS1115 pin. A 4.7k in series would sit
beside a 50k and change the current by under 9 %. Dropping it saves a part. (v2's 4.7k protected a 10k/15k divider.) *(check)*: the ADS1115's switched-capacitor
input kicks through 50k; no value is in the datasheet and VT-21 shows it.

**The ladder** is the existing 8 x 270 ohm (3 parallel at the bottom + 5 in series): TAP1..TAP5, VREF at 0.1875 / 0.750 / 1.3125 / 1.875 / 2.4375 / 3.000 V. TAP5's
Thevenin source is 207.7 ohm behind 2.4375 V. ADS1115: AIN0 = tap, AIN1 = VREF, AIN2 = TAP5, AIN3 = TAP2 (unchanged).

**Why TAP5, and why k = 1/2 forces it.** Any wire node X keeps the tap at or above 0 V at A = -1.35 V only if (-1.35 + X)/2 >= 0, X >= 1.35 V. TAP5 (2.4375) and TAP4
(1.875) do; TAP3 (1.3125) misses by 0.02 V and TAP2 (0.75) by 0.3 V (the wire to TAP2 reaches -0.072 V in the table below, with tolerance). The measured taps are TAP2 and TAP5
(and VREF), so TAP5 is the only in-range measured node, and its distance from the default (VREF 3.0 V) is 0.46 V with Rd's pull included: that small step is the whole
trouble in section 3. The upper limit is no constraint: (1.35 + 3.0)/2 = 2.17 V.

### The jumper header (the spec lead approves the layout)

One row of three plated holes, 2.54 mm pitch, no part (the wire is a hand-fitted jumper, like V2-5's): **J_RAT = TAP4 | B | TAP5**, beside the ladder.

| Pin | Net | Carries | Range |
|---|---|---|---|
| 1 | TAP4 | ladder tap 1.875 V (not an ADS1115 input) | 1.875 V +-1 %, 0 .. AREF |
| 2 | B | the divider's bottom end | wire off 2.975 .. 2.995 V; wire on 2.528 .. 2.546 V; wrong positions below 1.9 V .. 3.0 V on the header |
| 3 | TAP5 | ladder tap 2.4375 V, ADS1115 AIN2 | 2.4375 V (2.4375 +0.097 V with the wire on) |

All three are the AFE's own signals inside 0 .. AREF, so PR-2 holds with any wire on the header. The right wire joins pins 2-3. Pin 1 is the neighbour that makes the likeliest
mistake (2-1) harmless: it is a wrong position that stays in range, which a GND or 3V3 pad would not be. A pad for each of GND or 3V3A is deliberately not offered. Positions
reachable only through the Due's stacking pins (taps on the ADC header, GND, 3V3A, 5V, VIN) are the "wrong positions of the Due's pass-through pins" below.

Positions (`ranges.py`, `detect.py`; 6000 draws, resistors 1 %, REF +-0.1 %, AWG -1.35 .. +1.35 V; "range" = T0 in 0 .. 3.21 V; the host detects each from the
shift of the tap and of the TAP5 reading against wire off, gap in mV against the 62 mV limit):

| State | T0 (V) | In range | Pin after BAV99 (V) | Clamp current | REF current | Host sees (gap) |
|---|---|---|---|---|---|---|
| wire off (default, normal use) | 0.792 .. 2.170 | yes | same | 0 | 2.12 mA | reference box |
| **B-TAP5 (right)** | 0.573 .. 1.943 | yes | same | 0 | 2.20 mA | dT -0.224..-0.215 V, dA2 +0.095..+0.100 V |
| B-TAP4 (header neighbour) | 0.385 .. 1.753 | yes | same | 0 | 2.43 mA | 177.5 mV |
| TAP4-TAP5 (across one rung; B left on Rd) | 0.792 .. 2.170 | yes | same | 0 | 2.61 mA | 222 mV |
| *Due pin:* B-TAP2 (0.75 V) | -0.072 .. 1.290 | **no, by 72 mV** | -0.077 | about 0 | 3.45 mA | 633 mV |
| B-VREF (3.0 V) | 0.803 .. 2.171 | yes | same | 0 | 2.10 mA | 224 mV (reads as "no wire": the host stops either way) |
| B-GND | -0.670 .. 0.682 | **no** | -0.400 | 5.6 uA | 5.13 mA | 1238 mV |
| B-+3V3A (3.3 V) | 0.950 .. 2.321 | yes | same | 0 | 1.80 mA | 372 mV |
| B-Due 5V (5.25 V max, stress) | 1.908 .. 3.298 | **no, by 88 mV** (but under VDD + 0.3 V = 3.51 V) | 3.317 | about 0 | 0.20 mA | 1329 mV |
| B-Due VIN (12 V, stress) | 5.222 .. 6.678 | **no** | 3.714 .. 3.753 | 59.5 uA | 7.02 mA (sinks) | 4643 mV |
| TAP5-GND (the ladder's top shorted) | 0.792 .. 2.170 | yes | same | 0 | **11.25 mA** (over the REF3030E's 10 mA recommended row, under its 35 mA short-circuit value) *(check)* | 2523 mV |
| TAP5-VREF (one rung shorted) | 0.792 .. 2.170 | yes | same | 0 | 0.03 mA | 453 mV |

**What the table says.** On the header, every state, right or wrong, keeps the tap in range by hardware alone. Through the Due's pins four wrong wires take T0 out of 0 .. 3.21 V
(TAP2, GND, 5V and VIN): no node below 1.35 V can be passive against an AWG at -1.35 V, so there the ADS1115 is protected by the 50k and the clamp, not by range. For the
GND wire the pin sits at -0.40 V, 0.1 V past the datasheet's GND - 0.3 V row, at 5.6 uA; the silicon BAV99 cannot hold -0.3 V at any current an R of 50k lets through (it would need
under 0.5 uA) *(check: BAV99 forward curve from memory, not read)*. Whether the other inputs read undisturbed in that state (SBAS444E 7.3.1 warns they can be affected) is VT-22's.

The break-on-purpose guards for this section are in section 5.

## 2. Ratio precision (`precision.py`, `net.py`)

A nodal truth model (T0, pin, B, the five ladder nodes, all 11 resistors drawn at +-1 %, REF +-0.1 %, the wire at 1 mohm) generates ADS1115 readings with per-channel gain
(channel match +-0.05 % each, so any two differ by at most the 0.1 % max), offset (+-3 x 125 uV: the datasheet's +-3 LSB is at FSR +-2.048 V, 62.5 uV an LSB; 375 uV is v2's
conservative carry, 187.5 uV is the literal reading and is run too), one INL bow of +-1 LSB common to all channels, Zcm 6 Mohm +-25 % (typ only *(check)*), and 125 uV/sqrt(64) = 15.6 uV of
averaged noise per reading (64 readings at 128 SPS, Table 6-1). The host solves (A, k) from a wire-off and a wire-on reading at each of three AWG levels (-1.3, 0, +1.3 V) with the nominal network and the nominal
Zcm, averages k, then converts the whole 25-level sweep (wire on throughout, B read every level) to AWG volts; the gain/offset of that line against the true AWG level is the error. The reading ratio to
VREF cancels the converter's gain and the reference's own 0.1 % (PA-2's share, not the sense's).

| Case (99.9th percentile of 20000 draws) | gain | offset | worst point | k error |
|---|---|---|---|---|
| all sources, channel match 0.1 % max | **1.116 %** | **20.4 mV** | 34.7 mV | 0.845 % |
| median / 95th, the same | 0.276 % / 0.767 % | 5.4 / 14.6 mV | 8.9 / 24.2 mV | 0.21 / 0.58 % |
| all sources, channel match 0.05 % typ | 0.858 % | 13.0 mV | 24.0 mV | 0.587 % |
| offset read literally (187.5 uV), 0.1 % / 0.05 % match | 1.097 % / 0.815 % | 19.4 / 11.7 mV | 33.4 / 22.4 mV | 0.805 / 0.545 % |
| **one source at a time:** channel match 0.1 % | 0.725 % | 16.9 mV | 26.4 mV | 0.639 % |
| Zcm spread +-25 % | 0.561 % | 4.2 mV | 11.7 mV | 0.289 % |
| offsets +-375 uV | 0.181 % | 5.0 mV | 7.4 mV | 0.168 % |
| resistors 1 % | 0.053 % | 1.5 mV | 2.2 mV | 0.058 % |
| averaging noise (64 readings) | 0.028 % | 0.61 mV | 1.0 mV | 0.026 % |
| control: every source off | 0.000 % | 0.01 mV | | 0.000 % |
| **no wire at all: k trusted at 1 % parts, wire-off sweep** | **1.129 %** | **30.9 mV** | 41.8 mV | 0.969 % |

**Why it cannot reach 0.1 %.** The step the ratio is read from is small: ΔB = B_on - B_off = 2.536 - 2.985 = 0.45 V, ΔT half of it. The ADS1115's channel
match turns 2.5 V on AIN2 against 3.0 V on AIN1 into 0.1 % x 2.5 V = 2.5 mV of ΔB error, 0.55 % of ΔB, and k carries it; the 3-LSB offsets are 0.17 % on top. The
AWG-sense reading through the wire-fitted sweep amplifies those errors by (B - T)/k. This is the datasheet's limit, not the divider's: the floor with k known exactly is
0.05 % + 2.5 mV from the T channel alone (the v2 allotment). Choice of ratio level, number of levels (1, 3 or 5: 1.12-1.16 %) and of R/Rd (scan below) move it by +-0.2 %.

**The divider (R, Rd choice).** Candidates scanned (`R x Rd`, 6000 draws, unmatched): 10k/1k 2.89 %, 22k/1k 1.13 %, 47k/1k **0.98 %**, 100k/330 1.33 %, **100k/1k 1.16 %**, 100k/2.2k 1.14 %. They differ by under the
statistical noise of a 0.7 % channel term, so the existing 100k pair is kept: no new part type, the lightest load on the AWG (section 4), the least clamp-leakage
clamp-leak sensitivity (0.1 mV per nA at the AWG for a 50k tap node; a lower R divides it). 10k fails outright because Rd/Rb sets how much Rd's tolerance reaches B_off:
Rd = 1k against 10k is 9 % of the drop. Rd = 1k also leaves the wire-on TAP5 pull-up at 97 mV, measured.

**Loading of the ADS1115's 6 Mohm on the 50k tap and its immunity.** The pin current is (T0 - 0.7 V)/6 Mohm and drops 50k x that off T0 (0.83 % of T0 - 0.7 V); the host divides the nominal
loading out. What is left is the Zcm spread: **0.56 % gain** at +-25 %. v2's Thevenin match puts the same 50k in series with AIN1 (VREF) and AIN2 (TAP5), two more Basic resistors
(50k = 49.9k C23184 or 51k C23196): the loading then is a common factor that the ratio to VREF cancels. Result, with Zcm common to the channels (one sampling capacitor and clock: *the datasheet
gives one typical value and says nothing about channel-to-channel spread, (check)*): the Zcm-only error falls from 0.561 % to **0.077 %** and the whole run from 1.116 % to **0.811 %** / 19.8 mV. With Zcm
spread independently per channel it is **worse: 2.86 % / 67 mV**. Without evidence on that correlation the match is not recommended; **not fitted**.

**Leakage of the clamp against the tap node.** BAV99's IR is not in this repository and its datasheet was not read; from memory it is 30 nA max at VR = 25 V at 25 C
and rises steeply with temperature *(check, read it)*. A constant leak I through the 50k tap node moves the sense by 50 kohm x I and the AWG estimate by twice that (k = 1/2):
**0.1 mV per nA**. Sim: 1 nA +0.1 mV, 30 nA +2.1 mV (20.41 -> 22.55 mV), 300 nA +29 mV. At the 3 V reverse bias here the leak is expected to be far below the 25 V figure, but no value is read: with 30 nA
as an upper bound the cost is 2 mV against a 3 mV allotment, so the **BAV99 leakage at 0..3 V and at the shield's temperature is what VT-21 should
measure, with a pin-side clamp removed as the control**. A BAV99 pair at a node at 1 .. 2 V reverse biases the GND diode at T0 and the +3V3A diode at 3.21 - T0, so the two leaks partly cancel.

**What would meet 0.1 %** (each a decision for the spec lead, none applied):

1. **Cancel the ADS1115's channel terms with an equal-voltage step.** With the same voltage on two inputs the host reads their match and offset directly (noise 15.6 uV against volts). Wire TAP5-VREF
   (the "one rung shorted" state, harmless: 0.03 mA, 453 mV from the right box) puts the identical 3.0 V on AIN1 and AIN2; a wire-on level with A set so that T0 = TAP2 at A = 2 x 0.75 - 2.536 = -1.04 V (inside the window, with the wire B-TAP5 on) and gives AIN0 against AIN3. That needs a second wire
   position, which is no longer one manual action; the sim with the channel gain and offset terms removed gives **0.58 % unmatched, 0.115 % / 3.2 mV with the Thevenin match** (correlated Zcm): near the 0.1 % share, still above the 0.05 % allotment.
2. **0.1 % resistors, no jumper.** Rerun with 0.1 % R7, R8, Rd and k trusted (wire off throughout): **0.17-0.20 % / 4.8-6.1 mV at R = 10-22k** (tolerance 0.001, correlated Zcm, same ADS1115 errors; the measurement at the same R is 1.0-1.9 %). Extended parts *(check: price and stock)*;
   `jlc-basic.csv` has no Basic 0.1 % resistor.
3. **Relax the sense's share** to about 1.2 % gain / 21 mV, which is what the jumper delivers and what trusted 1 % parts deliver (1.13 % / 31 mV): the jumper's only gain over not measuring is the offset (31 to 20 mV) and a flag for a mis-assembled divider.
4. **Use the jumper as a check, not a correction**: the host verifies k within 1 % (k error 0.85 % at the 99.9th percentile against a 1 % prior) and flags a mis-assembled divider; the fit then trusts k nominal.

## 3. The clamp, the forced BNC voltage and the AWG's load (`forced.py`, `ranges.py`)

**Clamp.** D8 = BAV99: anode 1 to GND, cathode 2 to +3V3A, common 3 to the pin; the ADS1115's own ESD diodes are in parallel and (check) conduct no later. Model: Shockley fit
through VF 0.715 V at 1 mA and 0.855 V at 10 mA (max values, from memory of the datasheet, **not read here (check)**), so 0.39 V at 5 uA. A silicon BAV99 clamps about 0.1 V *further*
than the Schottky BAT54S it replaces (about 0.2 V at 5 uA): that is the price of dropping the BAT54S, and it leaves the pin 0.1 V past the ADS1115's abs-max rows in the GND and 5 V wrong
positions and in -5 V, powered, at 12 .. 16 uA. Against the datasheet's 10 mA continuous row it is a 600x margin; SBAS444E 7.3.1 prefers Schottky diodes and says an overdriven input can
disturb the others *(check, VT-22)*. If VT-22 shows the disturbance the BAT54S (Extended, 5 other uses stay in the BOM) comes back at D8 alone: one line.

**PR-4, forced voltage on the BNC** (2000 draws, wire off and on, the Thevenin 50k to 100k into the clamp; the unpowered rail charged through the upper diode and held down by R65 4.7k):

| Forced | Powered, pin (V) / clamp | Unpowered, pin (V) / clamp / rail |
|---|---|---|
| +1.8 V | 2.39 .. 2.40 / 0 | 0.466 .. 0.469 / 8.8 uA / 0.042 V |
| -1.8 V | 0.35 .. 0.61 / 0 | -0.432 .. -0.430 / 9.6 uA / 0 V |
| +5 V | 3.58 .. 3.63 / 7.7 uA | 0.682 .. 0.687 / 36.8 uA / 0.173 V |
| -5 V | -0.464 .. -0.440 / 16.1 uA | -0.520 .. -0.518 / 40.1 uA / 0 V |
| +12 V | 3.76 .. 3.77 / 75.6 uA | 1.04 / 100.4 uA / **0.472 V** (the 0.5 V limit has 28 mV left; 12 V is beyond PR-4's 5 V) |
| -12 V | -0.565 .. -0.560 / 84.9 uA | -0.581 / 109.7 uA / 0 V |

The current from the BNC into the chain is at most 75 uA at 12 V (40 uA at 5 V); the REF3030E sinks (3 - 5)/201k = 10 uA at +5 V, far inside its +-10 mA row.

**AW-4 / AW-6 load.** With the wire off the chain pulls 8.0 uA (A = +1.35 V) to 21.8 uA (A = -1.35 V) *into* the BNC node from VREF, which is 0.40 .. 1.09 mV across the 49.9 ohm and a gain change
of 13.4 uA x 49.9 ohm / 2.7 V = 0.025 %: permanent in normal use, so AW-7's calibration contains it, and the sense reads the BNC node itself. With the wire on it is 5.8 .. 19.6 uA. Noise: the chain's thermal current through 49.9 ohm is 45 nV rms in
10 MHz (upper bound); VREF's 51 uV rms (10 Hz .. 10 kHz, SBVS032K, `common.py` of v2) reaches the node as 12.7 nV; together 0.015 % of AW-6's 0.3 mV.

## 4. Parts (`parts.csv`)

**Removed:** U12 TMUX1119DCKR (C2673327, Extended, CNY 12.96 at 20), C30 100 nF (C14663), R68 4.7k (C23162), D7 BAT54S (C7420333); the control line D9_SEL is freed.
**Added:** Rd 1k (C21190, Basic, type already in the BOM), the J_RAT pad row (three plated holes, no part). **Changed:** D8 BAT54S (Extended) to BAV99 C2500 (Basic).
Unchanged: R7, R8 (100k C25803), U9. The 100k R9 was already gone.

| | Before | After | Change |
|---|---|---|---|
| Placements in the `cal` block | 4 removed + D8 | Rd added | **-4 + 1 = -3** |
| Part types | TMUX1119, BAT54S (7 uses) | BAV99 (1 use), BAT54S (5 uses elsewhere) | **-1 Extended (TMUX1119), +1 Basic (BAV99), net 0 types, 1 fewer Extended**; BAT54S stays Extended: D1, D2, D4, D5, D6 |
| Cost at 20 boards (BOM prices) | | | **-CNY 13.15 (about -USD 1.97 at 6.6912)**: 12.96 + 0.10 + 0.0169 + 0.0786, less 0.0100 for Rd and 0.0043 swapped on D8; the BAV99 price is USD 0.0111 at qty 20 from `docs/jlcpcb-parts.md` *(check)*. The domestic 20 CNY per Extended type per order (`bom.md`) adds -20 CNY for the first order if it applies *(check)* |

**What the layout changes need** (for whoever edits `design.py`, not edited here): R8's far end net `SNS_D` becomes `SNS_B` (to Rd and the J_RAT pin 2); D7 and U12/C30/R68 deleted; D8 symbol `BAT54S` to `BAV99`, clamping `SNS_TAP`
at the pin (no series part); TAP4 brought to J_RAT pin 1 and TAP5 to pin 3; the Due pin D9 returns to the free list.

## 5. Guards: every check was broken on purpose and had to fail (results in `results/guards_precision.json`, `detect.json`)

| Guard | Break | Result |
|---|---|---|
| G-zero | host model's Rd twice the truth, every error source off | gain 3.87 % against 0.05 %: fails (restored: 0.0001 %, passes) |
| G-Z | host assumes Zcm 3 Mohm against 6 Mohm, every source off | gain 1.70 %: fails; restored passes |
| G-eps | channel match 2 % instead of 0.1 % | fails to stay under 2 x the 0.1 % figure; restored passes |
| G-range | wire at TAP2 with the +-1.35 V window | T0 reaches -0.072 V: fails; wire at TAP5 passes |
| G-range2 | window widened to +-3.0 V, wire at TAP5 | T0 reaches -0.3 V: fails; +-1.35 V passes |
| G-clamp | a solver that returns the open-circuit voltage (no diodes) must fail the "pin moved > 0.2 V" test | fails; the real solver moves the pin from -0.675 V to -0.40 V and passes |
| G-detect | distinguishability limit raised to 1000 x the resolution (3.1 V) | fails; at 20 x all ten wrong states pass |
| table check | the in-range column itself can fire: B-GND, B-TAP2, B-5V and B-VIN read "no" | it is not a check that cannot fail |

The decisive control is G-zero's restored run: with all tolerances, the ADS1115's errors and noise switched off the procedure returns 0.0001 %, so the 1.1 % is the sources, not the model. The model's INL
is one bow common to the channels; per-channel INL (v2's choice) was larger and is a pessimism this run does not carry *(check, VT-21)*.

## 6. (check) list

BAV99 forward curve and IR (no datasheet read: the model is from memory); ADS1115 Zcm channel-to-channel spread, and its INL at FSR +-4.096 V (the datasheet gives INL and offset at +-2.048 V); the 50k source's settling against
the switched-capacitor input (no value read); the other inputs' reading during an overdrive (SBAS444E 7.3.1, VT-22); REF3030E sinking 7-11 mA in the TAP5-GND and VIN states; +3V3A low corner 3.21 V (derived, not simulated);
BAV99 price and the 20 CNY Extended-type fee; the AWG window as -1.3 .. +1.3 V (taken from the brief, afe.md AW-1 gives the 92 % of window and +-1 V).
