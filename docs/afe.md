# AFE requirements

A minimal analog front end (AFE) for the Due scope and AWG: protection, level
scaling and a bipolar generator output in front of the Due's native 12-bit ADC
and DAC, with two capture modes (real-time and equivalent-time). Two scope
channels, one AWG output, and a jumper-selected differential mode (Phase 1),
with an optional fully-differential amplifier assembly (Phase 2) and an optional
precision calibration channel (Phase 3). The plan that builds it is
[afe-plan.md](afe-plan.md).

The AFE is designed, simulated, built and verified against the numbers below.

## 1. How this document set is organised

A requirement is stated once, in this file. The plan, the contractor wording and
the tests point at its identifier and do not restate it.

| File | What lives there |
|---|---|
| This file | The requirements, the Due baseline they rest on, the tests that accept them, and the decisions the owner owes |
| [afe-plan.md](afe-plan.md) | How the AFE is built: the steps and gates, the owner's side of each step, and the traceability |
| [afe/contractor/brief.md](afe/contractor/brief.md), [afe/contractor/requirements.md](afe/contractor/requirements.md) | The rounded wording sent to the contractor, checked against this file. **As sent**, and out of date on construction (it says hand-soldered, through-hole, on the proto board; MC-1 to MC-5 no longer say that): revise it before it is used again. Section 18 maps it to the identifiers here |
| [afe/contractor-inventory.txt](afe/contractor-inventory.txt), `tools/afe_export_contractor.sh` | Which files go to the contractor, and the export |
| [afe/input-divider.html](afe/input-divider.html) | The input divider design aid |
| [hardware/afe-proto](../hardware/afe-proto/README.md), [hardware/reference/arduino-due](../hardware/reference/arduino-due/README.md) | The AFE shield PCB project, and the Due V03 reference it mates with |
| [related-work.md](related-work.md) | Comparable instruments and front ends. Read before front-end hardware work |
| [noise.md](noise.md), [ets-mode.md](ets-mode.md), [ets-pam.md](ets-pam.md) | The measurements this file cites |

Conventions. **TBC** marks a value the client must confirm; none is left except
MC-8 (D8), because every other one was frozen at its stated value, as the owner's
plan required (section 19 lists them). ***(check)*** marks a figure quoted from a
datasheet or a project record that this design has not re-verified. **Proposed**
marks a requirement the owner has not yet adopted, each tied to a decision in
section 17; a proposed requirement is not binding on the contractor.

## 2. Requirement IDs

| Prefix | Meaning | Section |
|---|---|---|
| SC | Scope input | 6 |
| SM | Capture modes | 5 |
| DF | Differential mode | 7 |
| AW | AWG output | 8 |
| P2 | Phase 2 amplifier assembly | 9 |
| PA | Phase 3 precision channel | 10 |
| PR | Protection | 11 |
| PW | Power | 11 |
| CA | Calibration | 11 |
| EN | Environment | 11 |
| MC | Construction | 12 |
| VT | Verification test | 13 |
| AN | Analysis | 14 |

## 3. Scope and phasing

The AFE adds protection, level scaling and a bipolar generator output to the
Due's native converters. The design topology, part values and part choices are
the contractor's. Everything here is a requirement, a constraint, a deliverable
or an acceptance test.

| Phase | Content |
|---|---|
| 1 | Two single-ended scope channels, one AWG output, jumper-selected differential mode |
| 2 | An optional fully-differential amplifier assembly that reuses the Phase 1 design (section 9) |
| 3 | A precision reference and a slow precise converter pair (section 10, D5 adopted) |

All three phases are **one PCB design**, built over several rounds. What a round does not populate is an unfitted footprint (MC-11), so a later phase is not a new board.
## 4. The Due as measured

The Due is the fixed part of this design, and it has been characterised to its
limits. This section is its baseline: facts the requirements below rest on,
each with its source. A figure with no record behind it says so. The three Dues
differ, and every per-board value is the client's to supply.

### 4.1 The board

| Item | Value |
|---|---|
| Board | Arduino Due (V03 reference), unmodified. JP101 open, JR1/BR1 untouched |
| AREF | The board's 3.3 V rail, about 3.27 V on the measured board. The client supplies per-board AREF and DAC-window values for its three Dues |
| ADC | 12-bit. 22.5 MHz clock on the 90 MHz build, 19.5 MHz on the in-spec 78 MHz build |
| ADC noise | 0.80 LSB rms on a held code at the 90 MHz default (one session, no record); 1.65 LSB rms (9.49 effective bits) with DAC0 driving A0 (`docs/noise.md`, `records/phase0-noise-fast-after-623d4dc.jsonl`). Broadband, with no spectral line, drift or mains |
| One channel | 1,022,727 sps (90 MHz build), 886,363 sps (78 MHz build) |
| Two channels | 1,046,510 sps in total, 523,255 per channel (90 MHz build); 453,488 per channel (78 MHz build) |
| DAC | 12-bit, weak drive. Output 0.578 to 2.771 V with a scope on the pin (`docs/hardware.md`); theory is 1/6 to 5/6 of AREF, a span of 2.13 V at AREF 3.20 V. Window centre about 1.67 V against a mid-AREF of 1.635 V |
| DAC noise | Earlier records say about 20 mV rms (15 mV idle) with the measurement bandwidth unrecorded; the ADC loopback reads about 1.3 mV. Only the DAC-to-ADC path's floor is known (see "Level band" below), not which converter holds it: the DAC's own noise is re-measured over DC to 1 MHz (VT-3) |
| ADC pins | Always A1 (CH1) and A0 (CH2), and no others. The AFE uses no other ADC channel, and the pins do not change between modes or phases |
| Differential ADC mode | A1 and A0 form one pair (AD6/AD7). Each pin stays between 0 V and AREF. PGA gain 1 gives full scale ±AREF/2, gain 0.5 gives ±AREF. The client confirms from the datasheet which pin is VIN+; this specification assumes CH1 on A1 is IN+ *(check)* |
| Power available | Due 5V and 3.3 V pins only. A0, A1 and the DAC pins are 3.3 V pins |
| Client supplies | Firmware, host software, the JP-DIFF input pin, and the ADC acquisition settings |

### 4.2 What equivalent-time capture measured on the Due's own loop

DAC0 driving A0, 2026-11-10, two benches: `montreal5` (one board, scope probes
on) and `linux-x1` (two Dues with independent crystals). Details and every
figure's record are in [ets-pam.md](ets-pam.md) and [ets-mode.md](ets-mode.md).

| Item | Value |
|---|---|
| Edge floor of the DAC-to-ADC path | 42.4 ns rise, 45.4 ns fall. An upper bound that includes the DAC's own response. About 8 MHz as a single pole (0.35 over 42.4 ns, derived) |
| Time axis of the fold | 0.24 ns standard error of the fitted clock on two independent crystals |
| Levels that pass every gate | PAM4 to PAM32 at 1.0 V and PAM64 at 1.5 V, on both benches. PAM128 at 1.5 V fails on both, with every eye closed |
| Level band | The 0.1% to 99.9% width of each level at the symbol centre is a fixed 17.4 codes (`linux-x1`) to 19.5 codes (`montreal5`), the same at every level count and at both swings. At 0.806 mV per code that is 14 to 16 mV at the pin. It is not inter-symbol interference, which would scale with the step |
| Level spread (one standard deviation) | 1.4 codes (`montreal5`) and 2.4 codes (`linux-x1`), 1.1 to 2.0 mV: a factor of 1.7 between boards |
| Ladder straightness | Largest residual from a line 0.3 to 0.5 codes at 64 and 128 levels over a 1.5 V window (0.65 to 2.65 V). Not tested over the ADC's full range |
| Large steps | Steps above about 1.5 V at the DAC pin leave a tail of 7 to 10 codes at the next symbol centre; at 1.5 V it is 3 |
| Symbol rate demonstrated | 1.6 Msym/s, one board and two |

### 4.3 What is not known

One list, and the only one: these are the Due's gaps that no document can close
by deciding. Each says how it is closed.

| Gap | Closed by |
|---|---|
| Which converter, the DAC or the ADC, holds the level band | A source that is not the DAC at an ADC pin (VT-3 with an external instrument), or the ADC's temperature-sensor channel (a firmware change on all three tracks) |
| The ADC's own input bandwidth | The 8 MHz above is a bound that includes the DAC; the AFE's wide path (VT-16) is the first instrument that can separate them |
| Noise on the Due's own 3.3 V, AREF and 5 V rails. **No measurement of it exists**; PW-2 and PW-4 are limits derived through PSRR, not set against a measured rail | VT-8 with the AFE disconnected first, then connected |
| ADC input capacitance and resistance, DAC output impedance, noise on AREF | The SAM3X datasheet, as the contractor's brief says |
| The Due's own supply current in idle, capture, loop and playback | An inline USB meter (decision D7) |
| Channel memory and crosstalk at 90 MHz | SC-9's test (VT-10); `docs/hardware.md` lists it as unmeasured |

## 5. Capture modes

The scope is for NRZ and PAM signals, judged by eye diagrams, and one AFE serves
two capture modes that want opposite things: real-time wants a band limit,
equivalent-time wants a wide path. Equivalent-time capture is no longer untested
on this hardware (section 4.2): the host half works, and what remains is an AFE
that lets it see a signal other than the DAC's.

| ID | Requirement |
|---|---|
| SM-1 | **Real-time** (single shot, any signal), **proposed (D2)**: a Gaussian-like response, 4th-order Bessel-Thomson or a buffered RC cascade, −3 dB at about 0.75 × the symbol rate, step overshoot at most about 2% *(check)*, no peaking. Replaces SC-5 if adopted |
| SM-2 | Real-time corner about 200 kHz on two channels and about 400 kHz on one, **proposed (D2)**: about 105 and 205 kbaud at 5 samples per symbol, and about 267 and 533 kbaud at 2 samples per symbol (edges only, no eye) |
| SM-3 | **Equivalent-time** (a repeating signal of known content): the host folds the samples by symbol phase, and the AFE passes a wide band with no anti-alias filter. Target bandwidth at least the loop's measured 8 MHz equivalent (section 4.2), the figure to be set by simulation at G1 (D3). The AFE's noise over this band is bounded by SC-6 |
| SM-4 | Mode selected by jumper or switch. A switch in the signal path keeps its capacitance and leakage within SC-9 and SC-10 |
| SM-5 | **Level separation.** The AFE adds at most 10% to the Due's level band (17.4 to 19.5 codes, section 4.2), measured on PAM16 with `tools/ets_pam.py` (VT-15), per board. Inter-symbol interference between levels is not what limits a PAM eye on the Due, so this replaces the draft's INL and DNL wording |
| SM-6 | Differential input (DF-2) for differential links, not two channels subtracted: the 0.95 µs channel skew is about 26% of a symbol at 267 kbaud |
| SM-7 | **Host, client-supplied and measured:** the fold's time axis is 0.24 ns. The tracker locks with a template of a known repeating pattern, so a repeating signal of unknown content has no demonstrated host path, and single-shot events are out of reach by construction. The ADC and DAC rate pair follows the rule of [ets-mode.md](ets-mode.md) (an odd DAC rate constant with an even ADC one on two boards, coprime on one) or the lock degrades |
| SM-8 | The equivalent-time path can be exercised by the Due's own DAC (AW-9), so it is verifiable without an external source |

**How many PAM levels a signal of a given amplitude can carry**, derived from the
level band at the SC-4 step of 3.5 to 4 mV per code (about 60 to 80 mV at the
input). The eye closes when the spacing, amplitude over N−1, falls below the band.
Not measured through an AFE.

| Signal, peak to peak | Levels that fit | Result |
|---|---|---|
| 0.5 V | 7 to 9 | PAM4 passes, PAM8 (71 mV spacing) is on the limit |
| 1 V | 13 to 17 | PAM8 passes (143 mV), PAM16 (67 mV) is on the limit |
| 2 V | 26 to 34 | PAM16 passes, PAM32 (65 mV) is on the limit |
| 5 V | 63 to 84 | PAM64 (79 mV) is on the limit |
| 10 V, the full ±5 V | 126 to 167 | PAM128 (79 mV) is on the limit |

With a single ±5 V range the AFE reaches PAM8 on the 1 V signals a PAM scope is
usually pointed at. SC-11 is what changes that.

## 6. Scope input (CH1 to A1, CH2 to A0)


| ID | Requirement |
|---|---|
| SC-1 | Default: two independent single-ended DC-coupled channels |
| SC-2 | Each input ±5 V, usable to ±6 V with the ADC pin inside 0 to AREF, with at least 80 mV of margin per side at AREF 3.20 V. This holds over AREF 3.20 to 3.30 V, component tolerance and a midpoint centring error of ±30 mV. The AREF spread is shown by analysis (VT-13) and by measuring each board as found, not by changing AREF |
| SC-3 | Input resistance 1 megohm per input. Input capacitance at most 30 pF including wiring |
| SC-4 | At most 4 mV per ADC code at the input. ±5 V occupies 70 to 75% of ADC full scale at nominal AREF. At 70% the step is 3.5 mV, and the 75% end leaves about 10% of full scale at ±6 V |
| SC-5 | Low-pass with one dominant pole, −3 dB corner 270 kHz ±25%, no peaking above 0.5 dB, and no step in the response larger than 2% from divider compensation. Usable band DC to 200 kHz at 1 Msps on one channel, DC to 100 kHz at about 523 ksps per channel on two (90 kHz at 453 ksps on the 78 MHz build). Gain error across the band is corrected by host calibration. The AFE is not an anti-alias filter, and its documentation must say so. This is the real-time path; the equivalent-time path is SM-3, and SM-1 is the proposed replacement of this row (D2) |
| SC-6 | AFE noise referred to the ADC pin at most 0.5 mV rms: over DC to 1 MHz in the real-time path, and over the whole bandwidth of the equivalent-time path (SM-3), stated as a density at the pin (0.5 mV over 10 MHz is 160 nV per root hertz, derived). The ADC's sample-and-hold folds every frequency the pin carries into the sample, so a figure over 1 MHz does not bound a wide path. At 0.5 mV the AFE widens the Due's level spread in the loop (1.1 to 1.9 mV rms) by 3 to 10%, and would widen the ADC's own floor by 27% if that floor is the unrecorded 0.64 mV (0.80 codes) of section 4.1; 0.2 mV costs 5% of that floor and 0.1 mV 1%. An AFE noise below about a fifth of the floor it adds to (2% growth) is over-design. The Due's ADC cannot verify this (VT-3, VT-16) |
| SC-7 | DC accuracy after host calibration: ±0.5% of reading ±5 mV, for the mean of at least 1024 samples |
| SC-8 | Channel matching, before host calibration: gain within 0.3%, offset within 5 mV, corner within 10% |
| SC-9 | Crosstalk: a full-scale input on one channel with the other input shorted changes the other channel's reading by at most 2 LSB at 1,022,727 sps (one channel) and 523,255 sps per channel (two channels), at the client's configured acquisition settings. The project records a 56% sample-and-hold memory on an undriven pin, so a low-impedance drive is expected |
| SC-10 | Source impedance at the ADC pin at most 5 kΩ, so the ADC settles to within 0.5 LSB inside its configured acquisition window and not the sample interval. The basis is the datasheet's 12-bit track time of 0.054 ns per ohm plus 205 ns *(check)* and 15 ADC clocks at 22.5 MHz (667 ns), which gives about 8.6 kΩ before margin |
| SC-11 | **Input ranges (proposed, D1).** The ±5 V range of SC-2 and SC-4, and at least one narrower range that fills the ADC for a smaller signal, values to be chosen. Every range keeps SC-3's input resistance and PR-1's protection. The Due's level band (SM-5) referred to the input is that band divided by the range's gain, which sets how many PAM levels a signal of a given amplitude can carry (table in section 5) |

## 7. Differential mode


| ID | Requirement |
|---|---|
| DF-1 | A jumper (JP-DIFF) selects differential mode, with CH1 = IN+ and CH2 = IN−. It only signals the mode to the firmware through a spare Due digital input pin (chosen by the client) and must not change the analog signal path |
| DF-2 | Two differential ranges, chosen by the firmware's PGA gain: ±5 V difference at most 4 mV per code, and ±10 V difference at most 7.5 mV per code. Each input stays within ±6 V. The contractor shows that every ADC pin stays inside the converter's differential-mode common-mode window *(check)* for the stated combinations and states any limit on input common mode |
| DF-3 | CMRR before host calibration, with each input driven from at most 100 ohms: at least 46 dB at DC on every unit and 40 dB at 10 kHz (typical 50 dB at DC). The input network uses parts of 0.1% tolerance or better |
| DF-4 | Accuracy after host calibration: ±0.5% of reading ±1 code, for the mean of at least 1024 samples. Bandwidth and noise per SC-5 and SC-6 |

## 8. AWG output (one channel, single-ended, from DAC0)


| ID | Requirement |
|---|---|
| AW-1 | Output ±1.0 V DC-coupled. As built, including the AW-7 tolerances and AREF 3.20 to 3.30 V, reaching ±1.0 V uses at most 92% of the board's DAC window |
| AW-2 | Step at most 1 mV |
| AW-3 | −3 dB corner 360 kHz ±25%, acting as the reconstruction filter. Usable band DC to 100 kHz, gain error corrected by host calibration |
| AW-4 | Load at least 10 kilohms, output impedance at most 50 ohms. A short to ground is safe indefinitely |
| AW-5 | Draws at most 0.1 mA from the DAC pin |
| AW-6 | AFE-added noise at most 1.0 mV rms over DC to 1 MHz, measured at the AWG output with DAC0 replaced by a quiet DC source at the same level. Total output noise with DAC0 driving is measured and reported, not guaranteed. The DAC's own noise is re-measured over DC to 1 MHz and reported before this figure is accepted |
| AW-7 | Accuracy: after calibration ±0.5% ±5 mV. As built, gain from the DAC pin to the output between 1.10 and 1.20 V/V and offset within ±60 mV including the DAC window's centre error. The offset reference is derived from AREF, not from 5 V |
| AW-8 | During Due reset or boot, with DAC0 undriven, the output stays within ±1.5 V and returns to the commanded value without exceeding ±1.5 V |
| AW-9 | **Unfiltered test path (proposed, D4).** A jumper or test point delivers the DAC0 signal to a scope input through at most 50 ohms without the AW-3 filter, so the equivalent-time path can be verified with a source the AFE did not shape (VT-17). The filter of AW-3 removes the 1.6 Msym/s test patterns the loop uses. The DAC leaves a tail of 7 to 10 codes after steps above about 1.5 V at its pin (section 4.2), which AW-2's step size says nothing of; the test report states the AWG's settling after a full-scale step |

## 9. Phase 2: fully-differential amplifier assembly


| ID | Requirement |
|---|---|
| P2-1 | Installs by replacing one removable amplifier assembly, with no cuts, rework or board changes |
| P2-2 | Reuses the Phase 1 input network, protection, output network, connectors, supply and JP-DIFF |
| P2-3 | Meets DF-2 to DF-4 and drives the A1/A0 pair with balanced signals. Its CMRR and noise are no worse than Phase 1's |
| P2-4 | Single-ended mode need not work while it is installed |
| P2-5 | The contractor states its input common-mode range |
| P2-6 | The Phase 1 design package defines the assembly's interface (pinout, voltages, loads) so Phase 2 needs no Phase 1 change |

## 10. Phase 3: a precision reference and a slow converter pair

**Adopted (D5), on the same PCB as Phases 1 and 2.** Two parts. **3a** is a precision
voltage reference with a buffer, a test point, and a routed connection to the
Due's AREF header pin. **3b** is a slow, precise ADC and DAC on that reference, to
calibrate the Due's own converters. They give absolute accuracy (gain, offset, and
the AREF value as the Due's ADC reads it) and, because the reference is a quiet DC
source, the ADC's own noise floor; with 3b's bandwidth at DC to 1 MHz, also the
DAC's noise. They are not justified by INL (integral non-linearity: how far a
converter's code against voltage curve strays from a straight line): the DAC and
ADC together lie on a line to 0.3 to 0.5 codes over a 1.5 V window against a level
band of 17 to 20 codes (section 4.2). 3a has no switch on the signal path. 3b's
switch (PA-3, PA-4) is the only Phase 3 part on it.

| ID | Requirement |
|---|---|
| PA-1 | (3b) Effective resolution at least 16 bits, noise-free, at a slow rate. State the measurement bandwidth with the figure. For the noise separation, a bandwidth of DC to 1 MHz |
| PA-2 | (3a, 3b) A precision DAC and a precision ADC, both at least 16-bit, on a common low-drift voltage reference (value and drift in ppm per degree set in round 1) |
| PA-3 | (3b) The ADC can read the Due's DAC0 and the AWG output. The DAC can drive a known voltage onto A0 and A1 through a switch, so the host can fit gain and offset of each Due channel |
| PA-4 | (3b) The switch's leakage, capacitance and charge injection stay inside SC-9 and SC-10, so the fast path is not degraded when the calibration path is off |
| PA-5 | Calibration stays in host software (CA-1). Optionally the board holds its reference's measured value |
| PA-6 | Absolute accuracy is claimed only as far as it can be verified against a better standard. Linearity and noise are verified with a borrowed 6.5-digit meter and a stable reference |
| PA-7 | **(3a) The reference is routed to the shield's AREF header pin, and is not used by the Due.** The routing has a series element, a solder jumper or a resistor, unfitted by default. The Due's JR1 and BR1 stay untouched (D6, closed), so on a stock Due the pin goes nowhere and the shield is harmless on it. Using the reference as ADVREF is a later decision of the owner and a rework of the Due ([the Due reference network](../hardware/reference/arduino-due/v03/README.md)): with JR1 fitted and BR1 bridged the reference would be shorted to 3.3 V, so the series element is fitted only after that rework has been checked by continuity |
| PA-8 | **(3a)** A test point and a header put the reference at a scope input by jumper or cable, with no switch in the signal path, so the Due's ADC can read it: its own noise floor and each board's gain |

DC calibration cannot reach frequency response. Scope flatness needs the AWG into
the scope (AW-9) with the precision ADC as judge, within its bandwidth.

Starting points, each to be checked against its datasheet: ADI CN-0310 and
CN-0251 (low-noise precision chain, built for ±10 V and ±15 V supplies);
AD4111 and AD4114 (integrated ±10 V front end); CN-0183 (bipolar DAC output with
level shift); a charge pump and negative regulator such as the LM27762 for the
negative rail. **Supply:** USB 5 V through the Due's 5 V pin, nothing else, never
the 3.3 V pin (the Due's 3.3 V is a linear regulator and every milliamp there is
heat).

## 11. Protection, power and environment


| ID | Requirement |
|---|---|
| PR-1 | Each scope input survives ±30 V continuous, powered or unpowered, and a signal applied with the Due unpowered or unconfigured. Above ±30 V the AFE may be damaged, but only in parts the owner can replace on the shield, and the Due is not damaged |
| PR-2 | A0, A1 and the DAC pin stay between −0.2 V and 3.45 V in every supply and power-off state. This is a conservative limit against the pin's datasheet absolute maximum of −0.3 to +4.0 V *(check)*. Any driver of these pins is supplied at no more than 3.45 V |
| PR-3 | With the Due unpowered and ±30 V on a scope input, the current into the Due supply pins is at most 100 µA and the rails stay below 0.5 V |
| PR-4 | The AWG output survives an external ±5 V for at least 10 s, powered or unpowered, and recovers without damage. Unpowered, the back-feed into the Due supply pins meets PR-3's limits. These excursions are exempt from PW-3 |
| PW-1 | Power only from the Due 5V and 3.3 V pins. At most 30 mA in normal operation with loads of at least 10 kilohms. The Due's own draw is unmeasured (section 4.3), so the 30 mA stands until D7 is decided |
| PW-2 | Any negative or extra rail is made on the AFE, with ripple at the amplifier supply pins of at most 20 mV |
| PW-3 | With the AWG output shorted to ground indefinitely, total current is at most 60 mA with no damage |
| PW-4 | The rms noise on the Due 3.3 V pin and AREF rises by at most 0.5 mV over DC to 1 MHz when the AFE is connected, calculated as sqrt(on² − off²) |
| PW-5 | No Due modification |
| CA-1 | Calibration of gain, offset, frequency response and common-mode error is done in host software. The AFE has no trim elements, and its performance does not depend on any particular calibration instrument |
| EN-1 | 15 to 35 °C. Gain drift at most 0.2% and offset drift at most 3 mV over that range, excluding the Due's own drift |

## 12. Construction


| ID | Constraint |
|---|---|
| MC-1 | A custom shield PCB in the Arduino Mega/Due form factor, stacked on the Due through stacking headers that carry every Due pin through. The Due's outline and pin positions are those of the V03 reference ([Due V03 in KiCad](../hardware/reference/arduino-due/v03/README.md)). It is a new KiCad project under `hardware/afe-proto` |
| MC-2 | Retired: it applied to a proto board, which the AFE no longer uses |
| MC-3 | A custom 2-layer PCB with a ground plane, surface-mount parts wherever possible. The equivalent-time path (SM-3, about 8 MHz) needs a controlled layout and does not work on a proto board. Whether it is assembled by hand or by a board house is D10 |
| MC-4 | Header pin positions come from the Due V03 KiCad reference, and are checked by continuity on the owner's boards before the first round is ordered |
| MC-5 | The design records which header pin every net uses, in a table, and passes KiCad 10.x's electrical and design rule checks |
| MC-6 | Design files use KiCad 10.x. Simulation models carry provenance and hashes |
| MC-7 | Fit and the AREF-spread conditions are demonstrated on the client's three Dues: fit by inspection, electrical performance by VT-1 and VT-6 repeated on each board as found |
| MC-8 | Connector type and the probe arrangement (×1 or ×10) are supplied by the client (D8) |
| MC-9 | Every Due pin the AFE does not use passes through the board unchanged. No AFE net connects to an unused pin (checked by continuity), no part or wire covers a header socket, and every exported pin stays reachable from the top of the stack. AREF is a used pin (PA-7) |
| MC-10 | All external connections are made on the AFE board. Nothing is wired to the Due's own headers while it is installed, and no loopback jumper (such as DAC0 to A0) is wired while the AFE circuit is fitted. Loopback is by an external cable between the AWG connector and a scope input connector |
| MC-11 | Every optional part of Phases 2 and 3 is a footprint that can be left unfitted, and every undecided choice (D1 to D4, D7) is a jumper, a solder jumper or an unfitted footprint, so one PCB design serves every round (plan, "Rounds") |

## 13. Verification


All tests use calibrated sources and instruments whose uncertainty is at
most one third of the tolerance tested. For DC tests that is about ±0.17%
±1.7 mV (5½-digit meter class), and DF-4 needs ±1.1 mV. The noise tests
(VT-3, VT-8) need an instrument with a noise floor of at most 0.15 mV rms
over DC to 1 MHz, which the Due's ADC cannot provide. The client lends
bench instruments, and the test procedure lists them.

| ID | Test | Covers |
|---|---|---|
| VT-1 | Scope DC accuracy per channel | SC-2, SC-4, SC-7 |
| VT-2 | Differential accuracy, sign, ranges and CMRR | DF-2 to DF-4 |
| VT-3 | AFE noise at the ADC pin and at the AWG output, each with an external instrument; also re-measure the DAC's own noise over DC to 1 MHz | SC-6, AW-6 |
| VT-4 | Frequency response of scope and AWG | SC-5, SM-1, SM-3, AW-3 |
| VT-5 | Overload, fault and unpowered tests | PR-1 to PR-4, AW-8 |
| VT-6 | AWG range, step, load, short circuit, DAC current and accuracy | AW-1 to AW-7, PW-3 |
| VT-7 | Loopback by external cable from the AWG output to a scope input, DC and sine; reported for information with no pass/fail limit | none |
| VT-8 | Supply current, ripple, and noise fed back to 3.3 V and AREF | PW-1, PW-2, PW-4 |
| VT-9 | Phase 2: repeat VT-2 and VT-3 with the assembly installed, and show installation needs no board change | P2-1, P2-3 |
| VT-10 | Input resistance, capacitance, channel matching, crosstalk and ADC-pin source impedance | SC-3, SC-8, SC-9, SC-10 |
| VT-11 | JP-DIFF function, and that the analog path is unchanged | DF-1 |
| VT-12 | Temperature drift | EN-1 |
| VT-13 | Analysis (section 14), by simulation and then measurement | AN-1 to AN-4 |
| VT-14 | Inspection and continuity check | P2-1, P2-2, P2-5, P2-6, PW-5, CA-1, MC-1 to MC-10 |
| VT-15 | Level band through the AFE: PAM16 by `tools/ets_pam.py` with the AFE in the loop, 3 runs with the first dropped, on each of the three Dues, compared with the Due alone | SM-5 |
| VT-16 | Equivalent-time path: bandwidth and noise density at the ADC pin with an external instrument. It is the first measurement that can separate the ADC's bandwidth from the DAC's | SM-3, SC-6 |
| VT-17 | The unfiltered DAC0 path (AW-9): feed PRBS and PAM from the Due's DAC and read it with the equivalent-time capture | AW-9, SM-8 |

## 14. Analysis the contractor must demonstrate


| ID | Analysis |
|---|---|
| AN-1 | Stability with real parasitics: phase margin at least 45 degrees |
| AN-2 | The ADC input settles to within 0.5 LSB inside the configured acquisition window (SC-10) |
| AN-3 | The DAC load is within the DAC's drive limits (AW-5) |
| AN-4 | Offset and gain drift of references derived from 3.3 V against AREF, over AREF 3.20 to 3.30 V (SC-2) |

## 15. Deliverables and process


Schematic and simulation files, with simulation reports before any
assembly; a bill of materials with alternates; an assembly drawing; the
test procedure and results report; a written calibration note for the
client's host software; and, for Phase 2, the assembly design and its test
report. Each stage passes simulation review before assembly, and a design
review follows each phase's test report.

## 16. Out of scope

Range switching beyond SC-11 (if D1 is adopted; otherwise it stays out), AC
coupling, a differential AWG, a 50 ohm terminated output, anti-alias filtering
beyond SC-5, firmware and host software. A precision voltage reference is out
of Phases 1 and 2 and is Phase 3's (section 10).

## 17. Decisions for the owner

One list, replacing those in the draft and the review. Each has a recommendation
and what it affects. None is adopted until the owner says so.

| ID | Decision | Recommendation | Affects |
|---|---|---|---|
| D1 | Narrower input ranges beside ±5 V | Yes, at least one, selected by jumper. Without it the AFE reaches PAM8 on a 1 V signal. The values (for example ±1 V) are the owner's | SC-11, SC-4, the table in section 5, the contractor's brief |
| D2 | Real-time corner and shape: 200 or 270 kHz, one fixed or one per channel count; a single pole or Bessel | Keep SC-5's single pole for Phase 1: it is the simplest and cheapest. Bessel and per-count corners as a later option | SC-5, SM-1, SM-2 |
| D3 | Equivalent-time bandwidth target | At least 8 MHz, set by the G1 budget; confirm the divider can meet it at SC-10's source impedance | SM-3, SC-6, VT-16 |
| D4 | An unfiltered DAC0 test path | Yes, a jumper or test point | AW-9, VT-17, SM-8 |
| D5 | Phase 3's precision channel and its custom PCB | **Decided 2026-11-10: adopted**, on the same PCB as the other phases: 3a (reference, buffer, test point, AREF routing) and 3b (slow precision ADC and DAC) | section 10, MC-3, PA-1 to PA-8 |
| D6 | Drive AREF from the board's reference | **Decided 2026-11-10: measure only.** JR1 and BR1 stay untouched. The reference is routed to the AREF pin and unused by default (PA-7). Using it as ADVREF later is the owner's call, a rework of the Due described in [the Due reference network](../hardware/reference/arduino-due/v03/README.md); the owner judged soldering JR1 and BR1 too risky for now | PA-7, PW-5 |
| D7 | PW-1's current budget: 30 mA, or 100 mA until the Due's draw is read | Measure the Due first with an inline USB meter in idle, capture, loop and playback, then freeze. The draft's estimate of 110 to 175 mA for the Due has no measurement behind it | PW-1, section 4.3 |
| D8 | Connector and probe arrangement (MC-8) | BNC, taking ×1 and ×10 scope probes | MC-8 |
| D9 | Real-time target symbol rates | From D2's corner: about 105 and 205 kbaud with an eye, 267 and 533 kbaud edges only. The equivalent-time rate is not an AFE limit: 1.6 Msym/s is demonstrated | SM-2 |
| D10 | Who assembles the shield: the owner by hand, or a board house | Open. A board house for the surface-mount parts, since fine soldering is a risk the owner has declined (JR1 and BR1); hand-soldering for headers and connectors only. This sets the smallest part size and package in MC-3 | MC-3 |

## 18. Contractor wording to requirement identifiers

For checking the contractor's results against the exact limits. The contractor's
wording is rounded and is not a tolerance.

| Contractor topic | Requirement IDs |
|---|---|
| Scope inputs: ±5 V, readable to ±6 V, margin inside 0 to reference | SC-2 |
| Step size, range use | SC-4 |
| Input resistance and capacitance | SC-3 |
| Low-pass pole about 270 kHz, no peaking | SC-5 |
| Noise at the converter pin | SC-6 |
| Channel match | SC-8 |
| Shared sample-and-hold, low-impedance driver | SC-9, SC-10, AN-2 |
| Accuracy after software correction (not stated to the contractor) | SC-7, DF-4, AW-7 |
| Differential jumper | DF-1 |
| Two differential ranges | DF-2 |
| CMRR | DF-3 |
| Generator ±1 V, step, window use | AW-1, AW-2 |
| Generator low-pass | AW-3 |
| Generator load, output impedance, short | AW-4 |
| DAC draw | AW-5, AN-3 |
| Generator noise | AW-6 |
| Generator accuracy as built, offset from the reference rail | AW-7, AN-4 |
| Reset and boot state | AW-8 |
| ±30 V survival, pin limits, unpowered back-feed | PR-1, PR-2, PR-3 |
| Generator survives external ±5 V | PR-4 |
| Power draw, negative rail ripple, noise on 3.3 V | PW-1, PW-2, PW-3, PW-4 |
| Temperature | EN-1 |
| Construction | MC-1 to MC-10, PW-5 |
| Later amplifier module interface | P2-1 to P2-6 |
| Calibration (host software) | CA-1 |

Left out of the contractor wording on purpose: exact tolerances and test methods
(VT-1 to VT-17), and Phase 2 as a separate scope. The contractor wording has no
counterpart yet for SC-11, SM-1 to SM-8, AW-9 or Phase 3; they are added when the package is revised after D1 to D4 and D10 are decided, and until then the package is exactly what was sent.

## 19. What changed from the 2026-11-06 requirement

| Change | Where | Why |
|---|---|---|
| The review, the draft of capture modes and calibration, the contractor-wording map and the owner's plan are folded in; they are no longer separate files | whole file, [afe-plan.md](afe-plan.md) | one place per fact |
| TBC frozen at the stated value: SC-3, SC-9, SC-10, DF-3, AW-7, AW-8, PR-3, PW-3, EN-1. MC-8 remains, as D8 | those rows | the owner's plan required it; the owner can veto any |
| "Host system" is now "The Due as measured", with the equivalent-time measurements and one list of what is not known | section 4 | the Due has been characterised to its limits; the gaps that remain are closed only by measuring |
| SC-6 states a density and a bandwidth | SC-6 | a 1 MHz figure does not bound a wide sampled path |
| SC-11 input ranges, AW-9 unfiltered test path, SM-1 to SM-8 capture modes | sections 5, 6, 8 | the PAM measurements and the draft; all proposed |
| Range switching leaves "Out of scope" if D1 is adopted | section 16 | it contradicted SC-11 |
| PW-1 keeps 30 mA until the Due's draw is measured | PW-1, D7 | the draft's 100 mA had no measurement |
| Phase 3 (precision channel) is optional and separate | section 10 | its INL case does not hold; it conflicts with MC-3 |
| VT-15 to VT-17 | section 13 | cover SM-3, SM-5, SC-6, AW-9 |
| A custom surface-mount shield PCB, all phases in one design built over several rounds. MC-1 to MC-5 rewritten, MC-2 retired, MC-11 added | section 12 | equivalent-time capture does not work on a proto board; the owner's decision |
| D5 adopted: Phase 3 is 3a (reference, test point, AREF routing) and 3b (slow ADC and DAC). PA-7 rewritten, PA-8 added | section 10 | the owner's decision |
| D6 closed: measure only, JR1 and BR1 untouched, the reference routed to AREF but unused by default | PA-7 | the owner judged the rework too risky for now |
| D10: who assembles the shield | section 17 | open |
