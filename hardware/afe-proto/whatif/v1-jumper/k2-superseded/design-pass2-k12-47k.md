# Version 1 without the ratio switch: the jumper ratio measurement, second pass (D25, PA-4)

Reworked on the spec lead's direction: ADS1115 datasheet facts in (SBAS444E 5.5: gain channel match 0.05 % typ / **0.1 % max**, offset channel match 3 LSB, Zcm 6 MOhm typ at +-4.096 V,
Zdiff 15 MOhm, no spread given), every wire state and every header wrong position in range **by hardware over the whole AWG window with the wire on during the sweep**, BAV99 at the sense input.
The first pass (k = 1/2, R = 100k, AIN2 reading TAP5, 1.12 % / 20 mV) is kept in `k2-superseded/`. Scripts are numpy only; `./run_all.sh` regenerates every number (about 70 s, `N=` sets the draws).
Adapted from kvm_02's v2 block (`due_oscilloscope_v2/.../powercal/`, read-only). Figures marked *(check)* are not verified. Nothing is measured on a board.

## 0. Result

**Recommended: k = 1/2, R7 = R8 = 47k, wire node TAP4, AIN2 reading the bottom end B.** The lever the brief proposed, a lower k, **makes the ratio worse, not better** (section 2): the gain error is
e0 + ((1-k)/k)(e0 - e2) in the channel gains, so it grows as k falls. What cuts the error is reading B itself on its own ADS1115 channel in both states (same-channel differences cancel the offsets), not a low wire node.

| Requirement | Limit | Result (k = 1/2, 47k/47k) | Margin | Verdict |
|---|---|---|---|---|
| Sense tap in 0 .. 3.21 V by hardware, wire OFF | 3.21 V = +3V3A low corner (`whatif/v1-basic/values.md` 3.2095 V) | 0.780 .. 2.170 V | +0.78 / +1.04 V | PASS |
| Same, wire ON throughout the sweep (B to TAP4) | the same | 0.382 .. 1.757 V | +0.38 / +1.45 V | PASS |
| Same, the other header wrong positions (B-TAP3, TAP3-TAP4) | the same | 0.182 .. 1.555 V; 0.780 .. 2.170 V | **+0.18 V** (B-TAP3) | PASS |
| VT-22, wire to a Due pin: TAP1, TAP2, GND, 5V, VIN | passive survival, current under 10 mA, no host action | at most 125 uA into the clamp (12 V stress) | 80x | PASS; **the tap leaves 0..3.21 V for these five** (nothing below 1.35 V can be in range at k = 1/2) |
| PR-4, +-5 V on the BNC, unpowered: rail and current into it | rail under 0.5 V, 100 uA (PR-3's rows) | **0.330 V, 70 uA**; powered: pin +3.67 V at 15 uA | 0.17 V, 30 uA | PASS (22k/22k fails it: 0.587 V, 125 uA; 33k is thin: 0.436 V, 93 uA) |
| -0.3 V row (ADS1115 GND - 0.3 V) | pin not below -0.3 V | **-0.437 V** (B-GND, 10 uA), -0.473 V (-1.8 V forced, unpowered), -0.564 V (-5 V unpowered) | **-0.14 to -0.26 V** | **FAIL as an abs-max row, PASS on current** (10 mA row, 100x); silicon BAV99 *(check)* |
| Host verifies the wire | 20 x 3.1 mV | smallest gap 366 mV (B-TAP5 through a Due pin against B-TAP4) | +304 mV | PASS |
| AW-4 / AW-6 load | information | 17 .. 46 uA into the node, 0.85 .. 2.3 mV across 49.9 ohm; 66 nV thermal + 27 nV from VREF against 0.3 mV | 4000x | PASS |
| **Ratio precision**, 0.1 % channel match (max), 99.9th percentile | **0.05 % / 3 mV allotted** (0.1 % fit share) | **0.385 % gain, 2.64 mV offset** (typ match 0.318 %) | **gain -0.335 %; offset +0.36 mV** | **gain FAIL (7.7x), offset PASS** |
| **Whole SC-7 stack** (section 5) | 0.5 % +- 5 mV | worst-case sum **0.725 %, 5.64 mV**; RSS **0.442 %, 4.00 mV** | sum -0.225 % / -0.64 mV; RSS +0.058 % / +1.0 mV | sum FAIL, RSS PASS |

## 1. The circuit and the jumper

```
 A (AWG BNC node) --R7 47k-- T0 --R8 47k-- B --Rd 1k-- VREF (REF3030E, permanent)
                              |             |
              ADS1115 AIN0 (direct,         header pin 2 ----wire---- pin 3 = TAP4 (1.875 V, loaded by Rd to about 2.15 V)
              BAV99 D8 at the pin)          B is also ADS1115 AIN2 (through nothing: B is 1k-stiff)
```

| Part | Value | LCSC | Note |
|---|---|---|---|
| R7, R8 | **47k** 1 % 0603 | C25819 (Basic) | were 100k C25803; k = R8/(R7 + R8) = 1/2; R7 || R8 = 23.5k is the series resistance of every wire state |
| Rd (new) | 1k 1 % 0603 | C21190 (Basic, in the BOM) | default tie B to VREF; **Rd's tolerance no longer enters the ratio**, because B is read on AIN2 in both states |
| D8 | BAV99 (Nexperia BAV99,215) | C2500 (Basic) | at the AIN0 pin, anode GND, cathode +3V3A; same SOT-23 pin map as the BAT54S |
| series / Thevenin-match resistors | **none** | | see section 2: a match is worse if Zcm differs per channel and buys 0.19 % if it does not |

**ADS1115 inputs (reassigned): AIN0 = sense tap T0, AIN1 = VREF, AIN2 = B (header pin 2), AIN3 = TAP3 (1.3125 V).** `design.py` has AIN2 = TAP5, AIN3 = TAP2. The reassignment costs one measured ladder tap:
the ladder now has VREF and TAP3 read (plus ground), not VREF, TAP5 and TAP2; with the wire on, the node on AIN2 is a loaded tap and is not a Due-ADC calibration point (the brief's rule), and with it off AIN2 reads B, which moves
with the AWG level and is not a tap either. TAP3, the middle, is the one chosen for the Due ADC's anchors; the choice has no effect on the ratio. Keeping three measured taps (AIN2 = TAP4 direct, AIN3 = TAP2, wire-off B from Rd's nominal)
is the A1 route: **0.63 % / 10.3 mV against 0.385 % / 2.64 mV** (k = 1/3: 0.64 % / 7.2 mV against 0.47 % / 3.32 mV).

**Why TAP4, and why B on the ADC.** At k = 1/2 the tap stays at or above 0 V at A = -1.35 V only if B >= 1.35 V. TAP4 (1.875 V) loaded by Rd's 1k pull is 2.15 V, so the tap is at least 0.38 V; the neighbour TAP3 (1.3125 V, 1.69 V loaded) is at least 0.18 V. Because B is read directly,
the wire node need not be one the ADS1115 reads, so TAP4 is allowed and gives ΔB = B_off - B_on = 0.81 V, against 0.45 V for TAP5.

### The jumper header (the spec lead approves the layout)

One row of three plated holes, 2.54 mm, no part: **J_RAT = TAP3 | B | TAP4**.

| Pin | Net | Carries | Range |
|---|---|---|---|
| 1 | TAP3 | ladder tap 1.3125 V (ADS1115 AIN3) | 1.3125 V +-1 %, inside 0 .. AREF |
| 2 | B | divider bottom end, ADS1115 AIN2 | wire off 2.95 .. 2.985 V; wire on 2.14 .. 2.166 V |
| 3 | TAP4 | ladder tap 1.875 V | 1.875 V +-1 % |

All three are the AFE's own signals inside 0 .. AREF, so PR-2 holds with any wire on the header. The right wire is 2-3. A GND or 3V3A pad is not offered. Wires to Due pins (taps on the ADC header, GND, 3V3A, 5V, VIN) are listed below.

Positions (`ranges.py`, 6000 draws, resistors 1 %, REF +-0.1 %, AWG -1.35 .. +1.35 V; "in range" = T0 in 0 .. 3.21 V by hardware; the host detects every state from the shift of the tap and of B against wire off, gap against the 62 mV limit):

| State | T0 (V) | In range | Pin after BAV99 | Clamp current | REF current | Host sees (gap) |
|---|---|---|---|---|---|---|
| wire OFF (default, normal use) | 0.780 .. 2.170 | yes | same | 0 | 2.15 mA | reference box |
| **B-TAP4 (right)** | 0.382 .. 1.757 | yes | same | 0 | 2.44 mA | dT -0.409..-0.393 V, dB -0.814..-0.796 V |
| B-TAP3 (header neighbour) | 0.182 .. 1.555 | yes | same | 0 | 2.83 mA | 383 mV |
| TAP3-TAP4 (one rung bridged, B on Rd) | 0.780 .. 2.170 | yes | same | 0 | 2.63 mA | 796 mV |
| *Due pin:* B-TAP1 (0.1875 V) | -0.478 .. 0.884 | **no** | -0.383 | 4.2 uA | 4.55 mA | 1729 mV |
| B-TAP2 (0.75 V) | -0.077 .. 1.293 | **no, by 77 mV** | -0.079 | about 0 | 3.45 mA | 907 mV |
| B-TAP5 (2.4375 V) | 0.570 .. 1.947 | yes | same | 0 | 2.22 mA | 366 mV |
| B-VREF (3.0 V) | 0.803 .. 2.177 | yes | same | 0 | 2.10 mA | 838 mV (reads as "no wire": the host stops either way) |
| B-GND | -0.676 .. 0.682 | **no** | **-0.437** | 10.4 uA | 5.13 mA | 2137 mV |
| B-+3V3A (3.3 V) | 0.951 .. 2.328 | yes | same | 0 | 1.80 mA | 1138 mV |
| B-Due 5V (5.25 V, stress) | 1.913 .. 3.309 | **no, by 99 mV** (under VDD + 0.3 V) | +3.318 | about 0 | 0.20 mA | 3088 mV |
| B-Due VIN (12 V, stress) | 5.242 .. 6.704 | **no** | +3.758 .. +3.798 | 124.7 uA | 7.02 mA (sinks) | 9838 mV |
| TAP5-GND (ladder top shorted) | 0.780 .. 2.170 | yes | same | 0 | **11.28 mA** (over the REF3030E's recommended 10 mA, under its 35 mA short-circuit value) *(check)* | 1488 mV |
| TAP5-VREF (one rung shorted) | 0.780 .. 2.170 | yes | same | 0 | 0.06 mA | 796 mV |

**On the header every state keeps the tap in range** (tightest +0.18 V). Through the Due's pins no node below 1.35 V can be passive against an AWG at -1.35 V at k = 1/2; those wires are survived by 23.5k and the clamp.

## 2. Ratio precision (`precision.py`, `net.py`)

Nodal truth model (T0, pin, B, the AIN2 pin, the five ladder nodes; the 11 resistors at +-1 %, REF +-0.1 %; the wire at 1 mohm) generating ADS1115 readings with per-channel gain (+-0.05 % each, so any two differ by at most the 0.1 % max),
offset (+-3 LSB at 125 uV = 375 uV, v2's conservative carry; the literal 187.5 uV is run too), one INL bow common to the channels (1 LSB, *(check)* at +-4.096 V), Zcm 6 MOhm +-25 % (two cases: **common to the four channels, or independent**),
and 125 uV/sqrt(64) = 15.6 uV per reading (64 readings at 128 SPS). The host solves (A, k) per AWG level from the wire-off and wire-on readings of T and B (the same two channels in both states, so offsets cancel in the differences), averages k over -1.3, 0, +1.3 V,
then converts the 25-level sweep (wire on throughout, B read at every level) to AWG volts; the line fitted to the error is the gain and offset. The reference's own 0.1 % is PA-2's share.

**What sets the gain error.** With T read on AIN0 and B on AIN2 against VREF on AIN1 the converted reading is A(1 + e0 + ((1-k)/k)(e0 - e2)), with e0 = g0/g1 - 1 and e2 = g2/g1 - 1 each up to the 0.1 % channel match
(the simulation reproduces it: channel match alone 0.183 % at k = 1/2, 0.284 % at 1/3, 0.364 % at 1/4, 0.448 % at 1/5, from 0.1 %). **A lower k multiplies (e0 - e2) by (1 - k)/k = 1, 2, 3, 4.** It cannot be removed while AIN0 and AIN2 are different channels
with different gains; and the floor e0 alone is up to 0.1 %.

### The k scan (99.9th percentile, 8000 to 20000 draws, 0.1 % match, Zcm independent per channel; typ = 0.05 % match)

R7, R8 are Basic values; "PR-4 +5 V" is the unpowered rail and the current into it (limits 0.5 V and 100 uA); "GND wire" the pin voltage and clamp current with B tied to GND at A = -1.35 V (the -0.3 V row).

| k | R7 / R8 | Rth | gain | offset | typ gain | PR-4 +5 V unpowered | GND wire | AWG load |
|---|---|---|---|---|---|---|---|---|
| 1/2 | 10k / 10k | 5.0k | 0.208 % | 1.42 mV | 0.128 % | **0.958 V, 204 uA: FAIL** | -0.510 V, 34 uA | 209 uA |
| 1/2 | 22k / 22k | 11k | 0.259 % | 1.80 mV | 0.186 % | **0.587 V, 125 uA: FAIL** | -0.474 V, 19 uA | 98 uA |
| **1/2** | **47k / 47k** | **23.5k** | **0.390 %** | **2.66 mV** | **0.317 %** | **0.330 V, 70 uA: PASS** | **-0.437 V, 10 uA** | **46 uA** |
| 1/3 | 20k / 10k | 6.7k | 0.329 % | 2.37 mV | 0.212 % | 0.485 V, 103 uA: FAIL | -0.411 V, 7 uA | 142 uA |
| 1/3 | 47k / 22k | 15k | 0.470 % | 3.33 mV | 0.356 % | 0.262 V, 56 uA: PASS | -0.378 V, 4 uA | 63 uA |
| 1/3 | 100k / 47k | 32k | 0.729 % | 5.25 mV | 0.628 % | 0.144 V, 31 uA | -0.353 V | 30 uA |
| 1/4 | 30k / 10k | 7.5k | 0.455 % | 3.35 mV | 0.298 % | 0.299 V, 64 uA: PASS | -0.329 V, 1.7 uA | 107 uA |
| 1/4 | 68k / 22k | 16.6k | 0.643 % | 4.66 mV | 0.499 % | 0.165 V, 35 uA | -0.313 V | 48 uA |
| 1/5 | 39k / 10k | 8.0k | 0.566 % | 4.24 mV | 0.377 % | 0.208 V, 44 uA: PASS | **-0.274 V, 0.7 uA: PASS** | 88 uA |
| 1/5 | 82k / 22k | 17.3k | 0.757 % | 5.55 mV | 0.592 % | 0.127 V, 27 uA | -0.277 V | 42 uA |

(Rows with R8 = 47k at k = 1/4 and 1/5 reach 1.05 % and 1.36 %: `results/precision.json`.) The k = 1/2, 47k pair is the lowest gain among those that pass PR-4. The lower k fixes the GND wire's -0.3 V row only at k = 1/5 and pays 0.57 % / 4.2 mV (offset over the 3 mV allotment);
the forced-voltage rows stay past -0.3 V at every k (-0.36 V at k = 1/5, -1.8 V unpowered; -0.55 V at -5 V).

### The chosen design, one source at a time (47k/47k, 99.9th, independent Zcm)

| Source | gain | offset |
|---|---|---|
| all sources, channel match 0.1 % max | **0.385 %** | **2.64 mV** (worst point 7.2 mV; k error 0.21 %) |
| all sources, channel match 0.05 % typ | 0.318 % | 2.64 mV |
| offset read literally (187.5 uV), 0.1 % / 0.05 % match | 0.387 % / 0.317 % | 2.23 mV |
| channel match 0.1 % | 0.183 % | 0.11 mV |
| channel match 0.05 % | 0.094 % | 0.11 mV |
| Zcm spread +-25 % (23.5k through 6 MOhm, loading 0.39 %) | 0.265 % | 1.88 mV |
| offsets +-375 uV (same-channel differences) | 0.022 % | 1.14 mV |
| resistors 1 % | 0.016 % | 0.15 mV |
| INL | 0.010 % | 0.11 mV |
| averaging noise (64 readings) | 0.019 % | 0.30 mV |
| every source off (control) | 0.000 % | 0.01 mV |
| ratio levels: one at -1.3, 0, +1.3 V, or all three | 0.385 .. 0.389 % | 2.64 .. 2.71 mV |
| route A1 (AIN2 reads the tap, wire-off B from Rd's nominal) | 0.631 % | 10.30 mV |
| no wire at all (k trusted at 1 % parts, wire-off sweep) / the same with 0.1 % resistors | 1.026 % / 0.253 % | 30.2 / 6.1 mV |

The same-channel routing took the offset term from 5.0 mV to 1.14 mV (it cancels in B_off - B_on and T_off - T_on) and the first pass's 1.12 % to 0.385 %. **What is left is Zcm's spread (0.265 %) and the channel match (0.183 %).**

**Loading of the 6 MOhm on the 23.5k tap and its immunity.** The host divides out the nominal loading (0.39 % of T0 - 0.7 V); the spread of Zcm is the residue. v2's Thevenin match (a series resistor equal to Rth, 24k C23352, on AIN1 and AIN2, so the loading is a common factor that the ratio to VREF cancels):

| Zcm | unmatched | matched |
|---|---|---|
| common to the four channels | 0.386 % / 2.61 mV | **0.197 % / 1.77 mV** |
| independent per channel | 0.385 % / 2.64 mV | **0.445 % / 2.97 mV** |

The match gains 0.19 % if Zcm is common and loses 0.06 % if it is not. With no datasheet statement of channel-to-channel spread it is **not fitted**; the Zcm error can instead be cut by lowering Rth, which PR-4 forbids below about 17k (above). *(check)*: the match is the one change worth VT-21's evidence.

**The noise cost of a lower k** (64 readings, 15.6 uV each, referred to the AWG node by sqrt(1 + (1-k)^2)/k, 1024 levels, 0.78 V rms level spread): per level 35 / 59 / 78 / 98 uV at k = 1/2, 1/3, 1/4, 1/5; **fit gain error 0.00014 / 0.00024 / 0.00031 / 0.00039 %, fit offset 1.1 / 1.9 / 2.4 / 3.1 uV**; without dither a conversion's half code (62.5 uV) gives 140 to 391 uV per level and 4 to 12 uV of fit offset. Negligible against the channel terms: the cost of a lower k is the channel-match multiplication above, not noise.

**Leakage of the BAV99** *(check: its IR is not in this repository; from memory 30 nA at 25 V, 25 C)*: through the 23.5k tap it costs 0.047 mV at the sense per nA of leak, 2 x that at the AWG estimate: 30 nA adds 1.4 mV (2.64 to 4.05), 300 nA adds 14 mV.

## 3. The clamp, the forced BNC voltage, the AWG load (`ranges.py`)

D8 = BAV99, model: Shockley fit through VF 0.715 V at 1 mA and 0.855 V at 10 mA (maxima, **from memory of the datasheet, not read here (check)**), 0.39 V at 5 uA. The ADS1115's own diodes are in parallel and not modelled. Forced voltage on the BNC (k = 1/2, 47k/47k; 2000 draws; the unpowered rail is charged through the upper diode and held down by R65 4.7k):

| Forced | Powered: pin (V) / clamp | Unpowered: pin (V) / clamp / rail |
|---|---|---|
| +1.8 V | 2.39 .. 2.40 / 0 | 0.534 .. 0.539 / 16 uA / 0.075 V |
| -1.8 V | 0.55 .. 0.60 / 0 | **-0.473** / 18.7 uA / 0 V |
| +5 V | 3.67 / 14.8 uA (wire on: 3.54 / 2 uA) | 0.874 .. 0.884 / 70 uA / **0.330 V** |
| -5 V | **-0.49** / 24.9 uA (wire on: -0.52 / 40 uA) | **-0.564** / 83.7 uA / 0 V |
| +12 V (stress) | 3.81 / 159 uA | 1.50 / 194 uA / 0.91 V (beyond PR-4's 5 V and PR-3's 0.5 V) |
| -12 V (stress) | -0.61 / 170 uA | -0.626 / 232 uA / 0 V |

The silicon BAV99 holds the pin 0.1 to 0.3 V past the ADS1115's GND - 0.3 V row at tens of uA (10 to 84 uA here, up to 175 uA for 22k): the current is 120x inside the 10 mA row; SBAS444E 7.3.1 prefers Schottky diodes and says an overdriven
input can disturb the others, which is VT-22's evidence *(check)*. If it shows disturbance, the BAT54S (Extended, five other uses stay in the BOM) returns at D8 alone.

**AW-4 / AW-6.** The chain pulls 17 (A = +1.35 V) to 46 uA (A = -1.35 V) into the BNC node from VREF: 0.85 .. 2.3 mV across the 49.9 ohm, a 0.054 % gain change, permanent and so calibrated (AW-7); wire on: 8 .. 38 uA. Thermal noise of the chain through 49.9 ohm is 66 nV rms in 10 MHz
(upper bound) and VREF's 51 uV rms reaches the node as 27 nV: together 0.024 % of AW-6's 0.3 mV. (At 10k/10k the load is 78 .. 209 uA, 3.9 .. 10.4 mV.)

## 4. The whole SC-7 stack for version 1 (`stack.py`)

SC-7 (afe.md): +-0.5 % of reading +-5 mV for the mean of 1024 samples, held up to 10 K after calibration. Gain terms in %, worst-case sum and RSS; terms and sources below, none re-simulated here except the sense:

| Term | Gain | Source |
|---|---|---|
| REF3030E E grade: 0.1 % initial, 15 ppm/K x 10 K, hysteresis 100 ppm *(check)*, long term 40 ppm | 0.130 % | afe-v2 powercal `design.md` section 6; PA-2 |
| EN-1 uncalibrated gain drift, +-5 V, 10 K since calibration | 0.168 % | `whatif/v1-basic/values.md` section 3: 0.336 % over 20 K, halved (linear scaling, *(check)*) |
| Due ADC INL, tee fit share at 1024 points on +-5 V | 0.042 % | afe.md PA-3 |
| **Sense (this design), 0.1 % match / 0.05 % typ** | **0.385 % / 0.318 %** | `precision.py` |
| Ladder drift of a measured tap, 10 K opposed (only if the ladder is part of the fit; v2's 330 ohm figure, v1's 8 x 270 ohm at 1 %, same mechanism *(check)*) | 0.133 % | afe-v2 powercal `design.md` section 4 |
| **Offset:** EN-1 offset drift 3.0 mV (requirement figure, not simulated) and the sense 2.64 mV; the Due ADC's own offset and INL in mV are not given for v1 *(check)* | 3.0 + 2.64 mV | afe.md EN-1; `precision.py` |

| Case | Gain: sum / RSS | Offset: sum / RSS | vs 0.5 % / 5 mV |
|---|---|---|---|
| **k = 1/2, 0.1 % match (recommended)** | **0.725 % / 0.442 %** | **5.64 / 4.00 mV** | sum FAIL, RSS PASS |
| the same with the ladder drift | 0.858 % / 0.462 % | 5.64 / 4.00 mV | sum FAIL, RSS PASS |
| k = 1/2, 0.05 % typical match | 0.658 % / 0.384 % | 5.64 / 4.00 mV | sum FAIL, RSS PASS |
| k = 1/3, 47k/22k, 0.1 % match | 0.814 % / 0.521 % | 6.32 / 4.47 mV | sum FAIL, RSS FAIL |
| the allotment itself, 0.05 % / 3 mV | 0.390 % / 0.222 % | 6.00 / 4.24 mV | gain PASS, **offset sum FAIL** (EN-1's 3 mV + 3 mV), RSS PASS |
| the first pass (1.12 % / 20.4 mV) | 1.456 % / 1.137 % | 23.4 / 20.6 mV | FAIL |

**Room for the sense term.** With REF, EN-1 and the Due fit taking 0.340 % (0.473 % with the ladder), the worst-case sum leaves **0.160 % (0.027 %)** for the sense and its offset **2.0 mV**; as an RSS it leaves **0.451 % (0.431 %)**. The recommended design's 0.385 % sits
between the two: inside the 0.5 % as an RSS (+0.058 %), outside it as a worst-case sum (-0.225 %). The 0.05 % / 3 mV allotment is not met (7.7x on gain) and is not silently relaxed: the reallocation the table shows is to the RSS reading (sense up to about 0.45 %), or the stack to a looser
SC-7 for the sense, or the channel-match term cancelled (below).

**What would meet the allotment** (derived, not simulated): the dominant sources are the ADS1115's own channel match (0.183 %) and Zcm (0.265 %), properties of the part, not of the divider.
(i) *Cancel (e0 - e2) with equal-voltage readings.* One state calibrates only the pair it equalises. With the wire off, A = 2 x 1.3125 - 2.97 = -0.35 V (inside the window) makes T0 = TAP3, so AIN0 and AIN3 read one voltage and give g0/g3 to the noise (15.6 uV in 1.3 V);
with the wire on the neighbour (B-TAP3, a header position in range) AIN2 and AIN3 read one voltage and give g2/g3. Together they give e0 - e2, which removes the ((1-k)/k)(e0 - e2) term and leaves e0 alone (up to 0.1 %, about 0.09 % at the 99.9th percentile): a gain near 0.1 % plus Zcm. It costs one extra wire position (pins 1-2 for a reading), so it is no longer
one manual action; the owner's rule for it is a decision. (ii) *Match Zcm by measurement*, VT-21 (0.197 % with the match if Zcm is common). (iii) *0.1 % resistors and no wire* (0.25 % / 6 mV; Extended parts, price unchecked). None applied.

## 5. Parts (`parts.csv`)

**Removed:** U12 TMUX1119DCKR (C2673327, Extended, CNY 12.96 at 20), C30 100 nF (C14663), R68 4.7k (C23162), D7 BAT54S (C7420333); the control line D9_SEL is freed. **Changed:** R7, R8 100k (C25803) to **47k (C25819, Basic)**; D8 BAT54S (Extended) to **BAV99 C2500 (Basic)**.
**Added:** Rd 1k (C21190, in the BOM), the J_RAT pad row (three plated holes, no part). **No series resistor and no Thevenin-match resistor.** Unchanged: U9. The 100k R9 was already gone.

| | Before | After | Change |
|---|---|---|---|
| Placements in the `cal` block | U12, C30, R68, D7 present | Rd added | **-4 + 1 = -3** |
| Part types | TMUX1119, BAT54S (7 uses) | BAV99 (1 use), 47k (2 uses), BAT54S (5 uses elsewhere: D1, D2, D4, D5, D6) | **-1 Extended (TMUX1119); +2 Basic (BAV99, 47k)**; 100k stays in use elsewhere |
| Cost at 20 boards (BOM prices) | | | **about -CNY 13.15 (-USD 1.97 at 6.6912)**: 12.96 + 0.10 + 0.0169 + 0.0786, less Rd 0.0100 and the D8 swap 0.0043; the BAV99 price is USD 0.0111 at qty 20 from `docs/jlcpcb-parts.md` and the 47k price is unread (taken equal to the 1k) *(check)*. The domestic 20 CNY per Extended type per order (`bom.md`) adds -20 CNY for the first order if it applies *(check)* |

For `design.py` (not edited here): R7 and R8 value to 47k; R8's far end net `SNS_D` to `SNS_B` (to Rd, header pin 2 and ADS1115 AIN2); D7 and U12/C30/R68 deleted; D8 symbol to `BAV99`, clamping `SNS_TAP` at the pin; AIN2 to `SNS_B`, AIN3 to TAP3; TAP3 to J_RAT pin 1 and TAP4 to pin 3; Due pin D9 returns to the free list.
**If the -0.3 V row must hold for a wire to GND**: R7 = 39k (C23153), R8 = 10k (C25804), k = 0.204, wire at TAP2, header TAP3 | B | TAP2: pin -0.274 V at 0.7 uA, PR-4 passes (0.208 V, 44 uA), at 0.566 % / 4.24 mV (stack gain sum 0.91 %, RSS 0.61 %: both FAIL). It costs one 39k type instead of 47k.

## 6. Guards: every check was broken on purpose and had to fail (`results/guards_precision.json`, `stack.txt`)

| Guard | Break | Result |
|---|---|---|
| G-zero/k1/2, /k1/3 | every error source off (restored: 0.00002 % and 0.00003 %); then host Rd twice the truth on the A1 route (150 %), host Zcm 1.5 MOhm against 6 (0.50 %, 1.00 %) | each exceeds 0.05 %: fails; restored passes. A 5 % wrong R7 does not: k is solved, not trusted |
| G-eps | channel match 2 % | exceeds 5 x the 0.1 % figure: fails; restored passes |
| G-offset | offsets of 60 LSB | offset exceeds 3 x the 3-LSB figure: fails; restored passes |
| G-range/k1/2 | wire at TAP2 (B = 1.2 V, needs 1.35 V) | T0 -0.08 V: fails; the designed TAP4 passes |
| G-range/k1/3 | k = 1/3, window +-3.0 V | fails; +-1.35 V passes |
| G-range/top | A = +3.5 V with B = VREF | T0 3.25 V above 3.21 V: fails; +1.35 V passes |
| G-clamp | a no-op solver (pin = open circuit) | fails the "pin moved > 0.1 V" test; the real solver moves -0.675 V to -0.40 V |
| G-detect | limit raised to 1000 x resolution | fails; at 20 x all twelve wrong states pass |
| G-table | the in-range column must read "no" for B-GND | a column that always read yes would fail; the real one reads no |
| G-stack | the sense term at 1.12 % / 20.4 mV | the stack fails; at 0.05 % / 2 mV it passes |

The decisive control is G-zero: with tolerances, ADS1115 errors and noise switched off the procedure returns 0.00002 %, so the 0.385 % is the sources, not the model. During the first pass the check that "lower k helps" was wrong; the simulation said so before the algebra did (section 2).

## 7. (check) list

BAV99 forward curve and IR (no datasheet read: from memory); ADS1115 Zcm channel-to-channel spread (the datasheet gives one typical value), its INL at FSR +-4.096 V, and the offset LSB (3 LSB at +-2.048 V is 187.5 uV, 375 uV carried);
the ADS1115 other inputs during an overdrive (SBAS444E 7.3.1, VT-22); settling of 23.5k into the switched-capacitor input; REF3030E sinking about 7 to 11 mA in the VIN and TAP5-GND states; +3V3A low corner 3.21 V (taken from `values.md`);
EN-1 scaled linearly from 20 K to 10 K; REF hysteresis 100 ppm; ladder drift taken from v2's 330 ohm figure; the Due ADC's offset and INL in mV for SC-7's 5 mV; BAV99 and 47k prices and the 20 CNY Extended fee; the AWG window as -1.3 .. +1.3 V (taken from the brief).
