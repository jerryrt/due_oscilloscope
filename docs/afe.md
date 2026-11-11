# AFE requirements

A minimal analog front end (AFE) for the Due scope and AWG: protection, level
scaling and a bipolar generator output in front of the Due's native 12-bit ADC
and DAC, with two capture modes (real-time and equivalent-time). Two scope
channels, one AWG output, and a differential mode selected in host software (Phase 1),
and a precision calibration channel (Phase 3), both in version 1. The plan that builds it is
[afe-plan.md](afe-plan.md).

The AFE is designed, simulated, built and verified against the numbers below.

## 1. How this document set is organised

A requirement is stated once, in this file. The plan and the tests point at its
identifier and do not restate it. What is sent to a contractor is drawn from this
file at the time it is sent.

| File | What lives there |
|---|---|
| This file | The requirements, the Due baseline they rest on, the tests that accept them, and the decisions the owner owes |
| [afe-plan.md](afe-plan.md) | How the AFE is built: the steps and gates, the owner's side of each step, and the traceability |
| [hardware/afe-proto](../hardware/afe-proto/README.md), [hardware/reference/arduino-due](../hardware/reference/arduino-due/README.md) | The AFE shield PCB project, and the Due V03 reference it mates with |
| [related-work.md](related-work.md) | Comparable instruments and front ends. Read before front-end hardware work |
| [noise.md](noise.md), [ets-mode.md](ets-mode.md), [ets-pam.md](ets-pam.md) | The measurements this file cites |

Conventions. ***(check)*** marks a figure quoted from a datasheet or a project
record that this design has not re-verified. Every value is stated, and every
decision is recorded in section 16.

## 2. Requirement IDs

| Prefix | Meaning | Section |
|---|---|---|
| SC | Scope input | 6 |
| SM | Capture modes | 5 |
| DF | Differential mode | 7 |
| AW | AWG output | 8 |
| PA | Phase 3 precision channel | 9 |
| PR | Protection | 10 |
| PW | Power | 10 |
| CA | Calibration | 10 |
| EN | Environment | 10 |
| MC | Construction | 11 |
| VT | Verification test | 12 |
| AN | Analysis | 13 |

## 3. Scope and phasing

The AFE adds protection, level scaling and a bipolar generator output to the
Due's native converters. The design topology, part values and part choices are
the contractor's. Everything here is a requirement, a constraint, a deliverable
or an acceptance test.

| Phase | Content |
|---|---|
| 1 | Two single-ended scope channels, one AWG output, differential mode selected in host software |
| 3 | A precision reference and a slow precise converter pair (section 9, D5 adopted) |

Both phases are **one PCB design**, built over several rounds. **Version 1 carries Phase 1, 3a and 3b** (the precision ADC and DAC included, owner 2026-11-10). What a round does not populate is an unfitted footprint (MC-11), so a later phase is not a new board.
## 4. The Due as measured

The Due is the fixed part of this design, and it has been characterised to its
limits. This section is its baseline: facts the requirements below rest on,
each with its source. A figure with no record behind it says so. The three Dues
differ, and every per-board value is the client's to supply.

### 4.1 The board

| Item | Value |
|---|---|
| Board | Arduino Due (V03 reference), unmodified. JP101 open, JR1/BR1 untouched |
| AREF | In this document AREF means the converters' reference, the SAM3X's ADVREF. On a stock Due it is the board's 3.3 V rail through JR1 and the bead L3, about 3.27 V on the measured board; the AREF header pin is not connected to it (PA-7, [the Due reference network](../hardware/reference/arduino-due/v03/README.md)). The AFE senses it at the Due's 3.3 V pin (`POWER0` pin 4), at microamps. The client supplies per-board AREF and DAC-window values for its three Dues |
| ADC | 12-bit. 22.5 MHz clock on the 90 MHz build, 19.5 MHz on the in-spec 78 MHz build |
| ADC noise | **0.8 codes rms on a held code, DAC0 to A0 on the same board, no scope probes** (about 0.64 mV, 10.5 effective bits): `montreal5` 0.79 to 0.81 (`docs/dac-open-ended-montreal5.md`) and `linux-x1` 0.81 to 0.85 on A0 and 0.87 to 0.88 on A1 (`records/diag-held-noise-samebd-linux-x1.json`, 2026-11-10); a rail-tied divider into A2 read 0.68 to 0.77 (`docs/awg.md`). The spectrum is thermal and white-like, with no 1 kHz or 8 kHz comb; the only lines are fractions of the ADC clock (fs/3, fs/4, fs/6). The same channel read 1.2 to 1.4 with scope probes attached (`montreal5`), and **2.3 to 2.5 when the signal crossed a wire between two Dues** joined by a short ground jumper (`linux-x1`), the extra spread in every frequency band. |
| One channel | 1,022,727 sps (90 MHz build), 886,363 sps (78 MHz build) |
| Two channels | 1,046,510 sps in total, 523,255 per channel (90 MHz build); 453,488 per channel (78 MHz build) |
| DAC | 12-bit. Drive strength not specified: the datasheet gives no output impedance. Output 0.578 to 2.771 V with a scope on the pin (`docs/hardware.md`); theory is 1/6 to 5/6 of AREF, a span of 2.13 V at AREF 3.20 V. Window centre about 1.67 V against a mid-AREF of 1.635 V |
| DAC noise | Held-code noise through the DAC (0.8 to 0.85 codes, row above) is close to the ADC alone (0.68 to 0.77), so the DAC adds at most about 0.5 codes in quadrature at a held code. That comparison is between sessions and is not a controlled A/B. The DAC's own noise over DC to 1 MHz is still measured with an external instrument (VT-3) |
| ADC pins | A1 (CH1) and A0 (CH2) for the scope channels, the same in every mode. The calibration ladder's taps use A2 to A9 (PA-9) and are read only during calibration. No other ADC channel is used |
| Differential ADC mode | A1 and A0 form one pair (AD6/AD7). Each pin stays between 0 V and AREF. PGA gain 1 gives full scale ±AREF/2, gain 0.5 gives ±AREF. The client confirms from the datasheet which pin is VIN+; this specification assumes CH1 on A1 is IN+ *(check)* |
| Power available | Due 5V and 3.3 V pins only. A0, A1 and the DAC pins are 3.3 V pins |
| Client supplies | Firmware, host software, the differential-mode selection, and the ADC acquisition settings |

### 4.2 What equivalent-time capture measured on the Due's own loop

DAC0 driving A0, 2026-11-10, two benches: `montreal5` (one board, scope probes
on) and `linux-x1` (two Dues with independent crystals). Details and every
figure's record are in [ets-pam.md](ets-pam.md) and [ets-mode.md](ets-mode.md).

| Item | Value |
|---|---|
| Edge floor of the DAC-to-ADC path | 42.4 ns rise, 45.4 ns fall. An upper bound that includes the DAC's own response. About 8 MHz as a single pole (0.35 over 42.4 ns, derived) |
| Time axis of the fold | 0.24 ns standard error of the fitted clock on two independent crystals |
| Levels that pass every gate | PAM4 to PAM32 at 1.0 V and PAM64 at 1.5 V, on both benches. PAM128 at 1.5 V fails with probes on (`montreal5`) and across a board-to-board wire (`linux-x1`), and passes on one board without either. PAM256 at 1.5 V fails |
| Level band | The 0.1% to 99.9% width of each level at the symbol centre, measured as the loss between level spacing and eye height on one `linux-x1` Due, same-board, no probes, 1.5 V swing (`records/diag-samebd-pam-linux-x1.jsonl`): 11.4 codes at PAM64, 8.6 at PAM128 and 11.3 at PAM256, with a level spread of 1.15 to 1.18 codes. PAM64 and PAM128 pass all of A3 to A6; PAM256 fails A6 (eye −4 codes, spacing 7.3). With scope probes on the pins (`montreal5`) the band is 19.5 codes, and across a board-to-board wire (`linux-x1`) 17.4, the same at every level count and both swings. It is not inter-symbol interference, which would scale with the step |
| Level spread (one standard deviation) | 1.4 codes (`montreal5`, probes on) and 2.4 codes (`linux-x1`, across a board-to-board wire), 1.1 to 2.0 mV, against a held-code floor of 0.8 to 0.85 codes without them |
| Ladder straightness | Largest residual from a line 0.3 to 0.5 codes at 64 and 128 levels over a 1.5 V window (0.65 to 2.65 V). Not tested over the ADC's full range |
| Large steps | Steps above about 1.5 V at the DAC pin leave a tail of 7 to 10 codes at the next symbol centre; at 1.5 V it is 3 |
| Symbol rate demonstrated | 1.6 Msym/s, one board and two |

### 4.3 What is not known

One list, and the only one: these are the Due's gaps that no document can close
by deciding. Each says how it is closed.

| Gap | Closed by |
|---|---|
| Why a board-to-board wire adds noise: the wire, the ground, or the other board's DAC | Not needed by the AFE, whose inputs are its own connectors (MC-10); the band through the AFE is VT-15 |
| The ADC's own input bandwidth | The 8 MHz above is a bound that includes the DAC; the AFE's wide path (VT-16) is the first instrument that can separate them |
| Noise on the Due's own 3.3 V, AREF and 5 V rails. **No measurement of it exists**; PW-2 and PW-4 are limits derived through PSRR, not set against a measured rail | VT-8 with the AFE disconnected first, then connected |
| ADC input capacitance and resistance, DAC output impedance, noise on AREF | The SAM3X datasheet |
| The Due's own supply current in idle, capture, loop and playback | Budgeted from the datasheet with headroom (D7, 300 mA); not measured. An inline USB meter reading would replace it |
| Channel memory and crosstalk at 90 MHz | SC-9's test (VT-10); `docs/hardware.md` lists it as unmeasured |

## 5. Capture modes

The scope is a general-purpose instrument with two capture modes on one wide,
unfiltered path. Real-time capture takes any signal at the Due's sample rate.
Equivalent-time capture folds a repeating signal of known content to a much finer
time axis, which is what channel estimation and signal-integrity checks need:
eye diagrams, edges and level separation of NRZ and PAM test patterns, among
other repeating signals (SM-7 says which have a host path today). Equivalent-time
capture is measured on this hardware (section 4.2): the host half works, and what
remains is an AFE that lets it see a signal other than the DAC's.

| ID | Requirement |
|---|---|
| SM-3 | **One wide path for both modes.** Equivalent-time (a repeating signal of known content): the host folds the samples by symbol phase. Real-time: single shot, any signal, at the Due's sample rate. The AFE has no anti-alias filter, and the bandwidth is at least 8 MHz (D3, decided 2026-11-10), confirmed by simulation at G1. Real-time capture aliases anything above the Nyquist frequency, which the host cannot detect or remove, and the documentation and the host's display say so. The AFE's noise over this band is bounded by SC-6 |
| SM-5 | **Level separation.** The AFE adds at most 10% to the Due's level band (section 4.2: the same-board, probes-free band is 8.6 to 11.4 codes, so 10% is about one code), measured on PAM16 with `tools/ets_pam.py` (VT-15), per board. Inter-symbol interference between levels is not what limits a PAM eye on the Due, so the requirement is a level band and not INL or DNL |
| SM-6 | In real-time capture, a differential signal is measured with the ADC's differential mode (DF-2), not by subtracting two single-ended channels: the channels convert about 0.95 µs apart, so subtraction pairs samples taken at different times, which on an edge reads as a false difference. In equivalent-time capture each channel is folded on its own time axis, so the skew can in principle be corrected on the host; this is not demonstrated |
| SM-7 | **Host, client-supplied and measured:** the fold's time axis is 0.24 ns. The tracker locks with a template of a known repeating pattern, so a repeating signal of unknown content has no demonstrated host path, and single-shot events are out of reach by construction. The ADC and DAC rate pair follows the rule of [ets-mode.md](ets-mode.md) (an odd DAC rate constant with an even ADC one on two boards, coprime on one) or the lock degrades |
| SM-8 | The wide path can be exercised by the Due's own DAC through the unfiltered AWG output and an external cable (AW-3, MC-10), so it is verifiable without an external source |

**How many PAM levels a signal of a given amplitude can carry** on the ±5 V
range, derived from the same-board, probes-free level band of 8.6 to 11.4 codes
(section 4.2) at the SC-4 step of 3.5 to 4 mV per code: 30 to 46 mV at the input.
The eye closes when the spacing, amplitude over N−1, falls below the band. Not
measured through an AFE. The ±1.25 V range (SC-11) has about 4.6 to 4.8 times the ±5 V
range's gain, so every count rises by that factor for a signal that fits it.

| Signal, peak to peak | Levels that fit | Result |
|---|---|---|
| 0.5 V | 12 to 17 | PAM8 passes (71 mV spacing), PAM16 (33 mV) is on the limit |
| 1 V | 23 to 34 | PAM16 passes (67 mV), PAM32 (32 mV) is on the limit |
| 2 V | 45 to 67 | PAM32 passes (65 mV), PAM64 (32 mV) is on the limit |
| 5 V | 111 to 167 | PAM64 passes (79 mV), PAM128 (39 mV) is on the limit |
| 10 V, the full ±5 V | 220 to 333 | PAM128 passes (79 mV), PAM256 (39 mV) is on the limit |

With a single ±5 V range the AFE reaches PAM16 on the 1 V signals a PAM scope is
usually pointed at. SC-11 is what changes that.

## 6. Scope input (CH1 to A1, CH2 to A0)


| ID | Requirement |
|---|---|
| SC-1 | Default: two independent single-ended DC-coupled channels |
| SC-2 | Each input ±5 V, usable to ±6 V with the ADC pin inside 0 to AREF, with at least 80 mV of margin per side at AREF 3.20 V. This holds over AREF 3.20 to 3.30 V, component tolerance and a midpoint centring error of ±30 mV. The AREF spread is shown by analysis (VT-13) and by measuring each board as found, not by changing AREF |
| SC-3 | Input resistance 1 megohm per input. Input capacitance at most 30 pF including wiring |
| SC-4 | At most 4 mV per ADC code at the input. ±5 V occupies 70 to 75% of ADC full scale at nominal AREF. At 70% the step is 3.5 mV, and the 75% end leaves about 10% of full scale at ±6 V |
| SC-5 | **No filter (decided 2026-11-10).** The scope path is the one wide path of SM-3, with no low-pass beyond the bandwidth the stages have. Gain error across the band is corrected by host calibration. No band limit is added to meet noise (2026-11-11): SC-6 and AW-6 are met by the parts' own noise at the stages' bandwidth. The AFE is not an anti-alias filter, and its documentation must say so |
| SC-6 | AFE noise referred to the ADC pin at most **0.2 mV rms (decided 2026-11-10)** over the whole bandwidth of the one wide path (SM-3), on both ranges, stated as a density at the pin (0.2 mV over 10 MHz is 63 nV per root hertz, derived). The ADC's sample-and-hold folds every frequency the pin carries into the sample, so a figure over 1 MHz does not bound a wide path. Against the Due's floor of 0.8 to 0.85 codes (0.64 to 0.68 mV, section 4.1) the chosen 0.2 mV widens it by 4 to 5%; for comparison 0.5 mV would widen it by 24 to 27%, 0.3 mV by 9 to 10% and 0.1 mV by about 1%. An AFE noise below about a fifth of the floor it adds to (2% growth) is over-design. The Due's ADC cannot verify this directly: it is shown by simulation (AN-5) and by an external instrument where one is available (VT-3, VT-16), and its effect is measured through VT-15 |
| SC-7 | DC accuracy after host calibration: ±0.5% of reading ±5 mV, for the mean of at least 1024 samples |
| SC-8 | Channel matching, before host calibration: gain within 1% (2026-11-11), offset within 5 mV, bandwidth within 10%. The gain is coarse because the precision DAC calibrates each channel on both ranges (PA-3); the bound still catches a mis-assembled part |
| SC-9 | Crosstalk: a full-scale input on one channel with the other input shorted changes the other channel's reading by at most 2 LSB at 1,022,727 sps (one channel) and 523,255 sps per channel (two channels), at the client's configured acquisition settings. The project records a 56% sample-and-hold memory on an undriven pin, so a low-impedance drive is expected |
| SC-10 | Source impedance at the ADC pin at most 5 kΩ, so the ADC settles to within 0.5 LSB inside its configured acquisition window and not the sample interval. The basis is the datasheet's 12-bit track time of 0.054 ns per ohm plus 205 ns *(check)* and 15 ADC clocks at 22.5 MHz (667 ns), which gives about 8.6 kΩ before margin |
| SC-11 | **Input ranges (decided 2026-11-10, D1).** Two ranges: the ±5 V range of SC-2 and SC-4, and **±1.25 V**, a level-shifting op-amp stage with an as-built gain of **1.10 to 1.16** into the ADC pin. At that gain ±1.25 V keeps at least 80 mV of margin per side inside 0 to AREF at AREF 3.20 V with ±30 mV of centring error, as SC-2 does for ±5 V; a ±1 V AWG signal fills 69 to 73% of ADC full scale, and the step is about 0.68 to 0.71 mV per code (derived). The stage is supplied from the AFE's own 3.3 V rail so it meets PR-2. A Due pin selects the range through a solid-state switch, placed after the input protection, and the ±5 V range is selected at reset and whenever the Due's pins are undriven. Both ranges keep SC-3's input resistance, PR-1's protection, SC-6's noise and SM-3's bandwidth. The Due's level band (SM-5) referred to the input is that band divided by the range's gain (table in section 5) |

## 7. Differential mode


| ID | Requirement |
|---|---|
| DF-1 | Differential mode, with CH1 = IN+ and CH2 = IN−, is selected in host software and needs no jumper. The analog signal path is the same in both modes, so the mode is a host setting and not a hardware input |
| DF-2 | Two differential ranges, chosen by the firmware's PGA gain: ±5 V difference at most 4 mV per code, and ±10 V difference at most 7.5 mV per code. Each input stays within ±6 V. The contractor shows that every ADC pin stays inside the converter's differential-mode common-mode window *(check)* for the stated combinations and states any limit on input common mode |
| DF-3 | CMRR before host calibration, with each input driven from at most 100 ohms: at least 46 dB at DC on every unit and 40 dB at 10 kHz (typical 50 dB at DC). The input network uses parts of 0.1% tolerance or better |
| DF-4 | Accuracy after host calibration: ±0.5% of reading ±1 code, for the mean of at least 1024 samples. Bandwidth and noise per SM-3 and SC-6. On the ±1.25 V range the same two PGA gains give about ±1.25 V and ±2.5 V of difference; the contractor states the exact values |

## 8. AWG output (one channel, single-ended, from DAC0)


| ID | Requirement |
|---|---|
| AW-1 | Output ±1.0 V DC-coupled into a high-impedance load (±0.5 V into 50 Ω, AW-4). As built, including the AW-7 tolerances and AREF 3.20 to 3.30 V, reaching ±1.0 V uses at most 92% of the board's DAC window |
| AW-2 | Step at most 1 mV |
| AW-3 | **No reconstruction filter (decided 2026-11-10).** The DAC's output reaches the AWG output unfiltered, through a stage whose bandwidth is at least the scope path's (SM-3), so the 1.6 Msym/s test patterns are not shaped. Images of the sample rate are not attenuated: a 100 kHz sine at 1 Msps has its first image about 19 dB down (derived, zero-order hold), and the host reduces them by oversampling, up to the DAC's 1.39 M updates/s. Gain error across the band is corrected by host calibration |
| AW-4 | **50 Ω back-terminated source (2026-11-10).** A 50 Ω ±1% series resistor at the output, after the output stage, drives any load from 50 Ω up: ±1 V into a high-impedance load such as a scope input, ±0.5 V into 50 Ω. The termination absorbs the reflection from an unterminated cable end, which matters on the wide path: a 1 m cable is about 5 ns against a 42 ns edge (section 4.2). A short to ground is safe indefinitely, and the resistor limits it to about ±20 mA. Accuracy (AW-7) is stated into a high-impedance load; into 50 Ω the resistor's tolerance adds up to about 0.5% of amplitude, which host calibration may correct |
| AW-5 | Draws at most 0.1 mA from the DAC pin |
| AW-6 | AFE-added noise at most **0.1 mV rms (2026-11-10)**, stated as a density over the output stage's whole bandwidth as SC-6 is. It is half of SC-6 because a loopback through the ±1.25 V range adds both: the scope's 0.2 mV and the AWG's 0.1 mV amplified by about 1.15 widen the Due's 0.64 mV floor by about 6%, inside SM-5's 10%, where 0.2 mV would take it to about 11%. Measured at the AWG output with DAC0 replaced by a quiet DC source at the same level. Total output noise with DAC0 driving is measured and reported, not guaranteed. The DAC's own noise is measured and reported before this figure is accepted. Verified as SC-6 is (AN-5, VT-3) |
| AW-7 | Accuracy: after calibration ±0.5% ±5 mV. As built, gain from the DAC pin to the output between 1.10 and 1.20 V/V and offset within ±60 mV including the DAC window's centre error. The offset reference is derived from AREF, sensed at the Due's 3.3 V pin (section 4.1), not from 5 V |
| AW-8 | During Due reset or boot, with DAC0 undriven, the output stays within ±1.5 V and returns to the commanded value without exceeding ±1.5 V |

## 9. Phase 3: a precision reference and a slow converter pair

**Adopted (D5), on the same PCB as Phase 1.** Two parts. **3a** is a precision
voltage reference with a buffer, a test point, and a routed connection to the
Due's AREF header pin. **3b** is a slow, precise ADC and DAC on that reference, to
calibrate the Due's own converters. They give absolute accuracy (gain, offset, and
the AREF value as the Due's ADC reads it) and, because the reference is a quiet DC
source, the ADC's own noise floor. The slow ADC reads DC values; noise above a
few hertz is measured by the Due's ADC on the reference (PA-8) or by an external
instrument (VT-3), not by 3b. INL (integral non-linearity: how far a converter's code against voltage curve strays from a straight line) alone does not justify them: the DAC and ADC together lie on a line to 0.3 to 0.5 codes over a 1.5 V window, small against the level spacings we use but not against a held-code noise of about 0.8 codes rms (section 4.1), and averaging removes noise and not INL. So INL is a reason for 3b only for averaged level work. 3a has no switch on the signal path. 3b's
switch (PA-3, PA-4) is the only Phase 3 part on it.

| ID | Requirement |
|---|---|
| PA-1 | (3b) Effective resolution at least 16 bits, noise-free, at a slow rate, with the measurement bandwidth stated with the figure |
| PA-2 | (3a, 3b) A precision DAC and a precision ADC, both at least 16-bit, on a common low-drift **3.0 V** voltage reference (PA-8), its drift in ppm per degree set in round 1 |
| PA-3 | (3b) **The precision ADC is one IC, with its own input multiplexer; no external multiplexer (2026-11-10).** It reads the Due's DAC0, the AWG output and every ladder tap (PA-9), one input at a time, selected by the firmware over a serial bus. If the chosen part has fewer than 10 inputs, the ladder has fewer taps (D11), never an extra multiplexer. The Due's hardware SPI (MISO, MOSI, SPCK) is only on its separate 6-pin SPI header (`SPI0` in the V03 board file), not on the edge headers: the bus is either hardware SPI with the shield connecting to that header (MC-1), or I²C on the edge header's SDA and SCL, or a software bus on ordinary pins. The precision DAC drives a known voltage into each scope channel ahead of its range network and after its protection, through a switch, so the host fits each channel's gain and offset on both ranges |
| PA-4 | (3b) The switch's leakage, capacitance and charge injection stay inside SC-9 and SC-10, so the fast path is not degraded when the calibration path is off |
| PA-5 | Calibration stays in host software (CA-1). Optionally the board holds its reference's measured value |
| PA-6 | Absolute accuracy is claimed only as far as it can be verified against a better standard. Linearity and noise are verified with a borrowed 6.5-digit meter and a stable reference |
| PA-7 | **(3a) The reference is routed to the shield's AREF header pin, and is not used by the Due.** The routing has a series 0 ohm resistor, unfitted by default (a bill-of-materials choice at assembly, not a jumper). The Due's JR1 and BR1 stay untouched (D6, closed), so on a stock Due the pin goes nowhere and the shield is harmless on it. Using the reference as ADVREF is a later decision of the owner and a rework of the Due ([the Due reference network](../hardware/reference/arduino-due/v03/README.md)): with JR1 fitted and BR1 bridged the reference would be shorted to 3.3 V, so the series element is fitted only after that rework has been checked by continuity |
| PA-8 | **(3a)** The ladder's top tap is the buffered reference itself, on a spare ADC pin (PA-9), so the Due's ADC reads it directly with no cable and no switch: its own noise floor and each board's gain. 3.0 V sits about 0.2 V below AREF |
| PA-9 | **(3b, 3a) Calibration ladder (decided 2026-11-10).** A precision resistor ladder across the reference, with **up to 8 taps on A2 to A9 (D11)**, as many as the precision ADC's inputs allow after DAC0 and the AWG output (PA-3) and never fewer than 4, built from discrete 0.1% 0603 resistors, spread from near 0 V to the reference (the top tap is PA-8's), with no switch between a tap and its pin. A10 and A11 stay free. Each tap is also readable by the precision ADC (PA-1), so the ladder's resistor error is calibrated out: the Due's ADC gain and offset are fitted against the taps' measured voltages, not nominal ratios, and more taps than a fit needs make it robust to one bad tap. Taps are low impedance (the ladder's resistance at each tap sits well inside the Due's ADC source-impedance limit of SC-10), so a tap does not leave the sample-and-hold unsettled. The scope inputs' own gain and offset are calibrated through the precision DAC and its switch (PA-3, PA-4), not through the ladder |

DC calibration cannot reach frequency response. Scope flatness needs the AWG into
the scope by external cable (AW-3, MC-10) with the precision ADC as judge, within its bandwidth.

Starting points, each to be checked against its datasheet: ADI CN-0310 and
CN-0251 (low-noise precision chain, built for ±10 V and ±15 V supplies);
AD4111 and AD4114 (integrated ±10 V front end); CN-0183 (bipolar DAC output with
level shift); a charge pump and negative regulator such as the LM27762 for the
negative rail. **Supply:** USB 5 V through the Due's 5 V pin, nothing else, never
the 3.3 V pin (the Due's 3.3 V is a linear regulator and every milliamp there is
heat).

## 10. Protection, power and environment


| ID | Requirement |
|---|---|
| PR-1 | Each scope input survives ±30 V continuous, powered or unpowered, and a signal applied with the Due unpowered or unconfigured. Above ±30 V the AFE may be damaged, but only in parts the owner can replace on the shield, and the Due is not damaged |
| PR-2 | A0, A1 and the DAC pin stay between −0.2 V and 3.45 V in every supply and power-off state. This is a conservative limit against the pin's datasheet absolute maximum of −0.3 to +4.0 V *(check)*. Any driver of these pins is supplied at no more than 3.45 V |
| PR-3 | With the Due unpowered and ±30 V on a scope input, the current into the Due supply pins is at most 100 µA and the rails stay below 0.5 V |
| PR-4 | The AWG output survives an external ±5 V for at least 10 s, powered or unpowered, and recovers without damage. Unpowered, the back-feed into the Due supply pins meets PR-3's limits. These excursions are exempt from PW-3 |
| PW-1 | **(decided 2026-11-10)** Power only from the Due's 5V pin. The AFE makes its own 3.3 V and negative rails, and never loads the Due's 3.3 V pin, which is also the Due's AREF: current drawn from it would modulate the ADC's reference (PW-4). The 3.3 V pin may be sensed for centring (SC-2, AW-7) at microamps, as AREF (section 4.1); the AREF header pin is not, because a stock Due leaves it unconnected. The AFE draws at most 100 mA in normal operation with any AWG load AW-4 allows, and the Due and the AFE together at most 450 mA, a margin under USB 2.0's 500 mA per port. The Due is budgeted at 300 mA (D7), so the total budget is 400 mA, and 400 mA, not 450, is the design target: each USB port reaches the Due's 5 V rail through a 500 mA polyfuse (F1 on the native port, F2 on the programming port, in the V03 board file), whose hold current falls as it warms *(check the derating)* |
| PW-2 | Any negative or extra rail is made on the AFE, with ripple at the amplifier supply pins of at most 20 mV. Ripple and its harmonics that reach the ADC pin or the AWG output, through each stage's supply rejection at that frequency, count against SC-6 and AW-6: a switching rail inside the 8 MHz path is rejected far less than at low frequency. **The switching frequency of any converter is chosen with the wide path in mind (2026-11-10):** the contractor states it, and either places it where filtering and layout bring its residue under SC-6 and AW-6, or fixes it so the line it leaves can be identified and is not a moving spur. The residue at the ADC pin and at the AWG output is shown by AN-5 |
| PW-3 | With the AWG output shorted to ground indefinitely, the output current is limited to about ±20 mA by AW-4's 50 Ω, the AFE's total current stays within PW-1's 100 mA, and nothing is damaged |
| PW-4 | The rms noise on the Due 3.3 V pin and AREF rises by at most 0.3 mV over DC to 1 MHz when the AFE is connected. AREF noise enters every reading in proportion to the code, so 0.3 mV is at most 0.15 mV at mid-scale, below SC-6. The rise is calculated as sqrt(on² − off²) |
| PW-5 | No Due modification |
| PW-6 | **Input voltage range (2026-11-10, minimum 2026-11-11).** The AFE meets every requirement with the Due's 5V pin anywhere from the minimum to 5.25 V. The minimum is the higher of 4.4 V and 3.20 V plus the worst-case dropout of the Due's 3.3 V regulator at its load *(check)*: the V03 board file names an NCP1117 (1.10 V maximum at 100 mA and 1.20 V at 800 mA, so 4.4 V covers it), and the owner reports an AMS1117 on the boards in use, whose dropout is a separate datasheet check, so that AREF stays inside SC-2's 3.20 to 3.30 V across the whole range; SC-2 is not relaxed for a low 5V pin. USB 2.0 allows 4.75 to 5.25 V at a host port and as low as about 4.4 V at a bus-powered device after the cable; on the Due the path from a USB port to the 5V pin is a 500 mA polyfuse and a P-MOSFET (FDN340P, T1 and T2 in the V03 board file), and the contractor computes its drop at the budgeted current. The Due's 3.3 V, which is its AREF, comes from an NCP1117 linear regulator on that 5 V rail; it needs about 1 V of headroom *(check)*, so AREF leaves regulation as the 5V pin falls toward 4.3 V and follows it down from there; the contractor computes the minimum from the regulator's dropout at the Due's load. On barrel-jack power the Due's 5 V comes from its LM2734Y switching regulator (IC2) instead, and its ripple counts under PW-2. Below 4.4 V the AFE may stop meeting its limits but keeps PR-2 |
| CA-1 | Calibration of gain, offset, frequency response and common-mode error is done in host software. The AFE has no trim elements, and its performance does not depend on any particular calibration instrument |
| EN-1 | 15 to 35 °C. Gain drift at most 0.2% and offset drift at most 3 mV over that range, excluding the Due's own drift |

## 11. Construction


| ID | Constraint |
|---|---|
| MC-1 | A custom shield PCB in the Arduino Mega/Due form factor, stacked on the Due through stacking headers that carry every Due pin through. The Due's outline and pin positions are those of the V03 reference ([Due V03 in KiCad](../hardware/reference/arduino-due/v03/README.md)). If the precision ADC uses hardware SPI (PA-3), the shield also connects to the Due's 6-pin `SPI0` header, which the edge headers do not carry. It is a new KiCad project under `hardware/afe-proto` |
| MC-3 | A custom 2-layer PCB with a ground plane, surface-mount parts wherever possible. The equivalent-time path (SM-3, about 8 MHz) needs a controlled layout and does not work on a proto board. It is assembled by the board house's service (D10, MC-12) |
| MC-4 | Header pin positions come from the Due V03 KiCad reference, and are checked by continuity on the owner's boards before the first round is ordered |
| MC-5 | The design records which header pin every net uses, in a table, and passes KiCad 10.x's electrical and design rule checks |
| MC-6 | Design files use KiCad 10.x. Simulation models carry provenance and hashes. **Only redistributable models are committed (2026-11-11):** a vendor model whose licence forbids redistribution is used locally, fetched by a script that pins its hash, and never committed. The project's own behavioural models are fitted to datasheet figures, state the figures and their source, and are licensed CC-BY-SA 4.0 by a licence file in the models folder |
| MC-7 | Fit and the AREF-spread conditions are demonstrated on the client's three Dues: fit by inspection, electrical performance by VT-1 and VT-6 repeated on each board as found |
| MC-8 | Three BNC connectors, one 50 Ω part number: two scope inputs taking ×1 and ×10 scope probes, and the AWG output, so a loopback is one 50 Ω BNC cable and the line stays matched to AW-4's termination. All three on one board edge, hand-soldered by the owner (D8, decided) |
| MC-9 | Every Due pin the AFE does not use passes through the board unchanged. No AFE net connects to a pin outside the header-pin table of MC-5, which lists A2 to A9 as the ladder's (PA-9) (checked by continuity), no part or wire covers a header socket, and every exported pin stays reachable from the top of the stack. AREF is a used pin (PA-7) |
| MC-10 | All external connections are made on the AFE board. Nothing is wired to the Due's own headers while it is installed, and no loopback jumper (such as DAC0 to A0) is wired while the AFE circuit is fitted. Loopback is by an external cable between the AWG connector and a scope input connector |
| MC-11 | Every optional part is a footprint that can be left unfitted, and every undecided choice is a Due-pin-controlled switch or a footprint left unfitted in the bill of materials, never a jumper or a solder jumper, so one PCB design serves every round (plan, "Rounds") |
| MC-12 | **Cheap assembly (decided 2026-11-10, D10).** The board is built for the board house's assembly service at the lowest cost: parts from the service's own stock, one side populated, standard passives no smaller than 0603 (an unfitted-by-default part may be larger), no BGA, and as few distinct part numbers as the circuit allows. Precision parts that must be a specific value (reference, converters, the ladder and divider resistors) are the exceptions and are chosen for accuracy first. The contractor lists the board house's stock status of every part and the number of unique parts; a part the service lacks is justified in the design review. The hand-soldered parts are only the BNC connectors and headers (D8). Part-size and stock limits are the service's, not yet verified *(check)*. **Batch size (2026-11-10):** the first order is at most 20 boards and later orders at most 100, so per-order costs (setup, stencil, a loading fee per distinct non-library part) are a large share of each board's cost. Therefore: one part number is reused wherever its function allows, with the two scope channels in separate packages (SC-9) and the AWG stage in its own (its rails); every part that is not a precision part comes from the service's basic library; and the design review gives the per-board cost at 20 and at 100, both with Phase 3 fitted on every board and with it fitted on only some (MC-11) |

## 12. Verification


All tests use calibrated sources and instruments whose uncertainty is at
most one third of the tolerance tested. For DC tests that is about ±0.17%
±1.7 mV (5½-digit meter class), and DF-4 needs ±1.1 mV. The noise tests
need an instrument whose own floor is at most a third of the limit: about
0.07 mV rms over the wide path's bandwidth for SC-6, 0.03 mV for AW-6 and
0.1 mV over DC to 1 MHz for PW-4 (VT-3, VT-8, VT-16). The Due's ADC cannot
provide that, and the owner's 8-bit scope cannot either; where no such
instrument is borrowed, SC-6 and AW-6 rest on simulation (AN-5) and on their
measured effect in VT-15. The client lends
bench instruments, and the test procedure lists them.

| ID | Test | Covers |
|---|---|---|
| VT-1 | Scope DC accuracy per channel | SC-2, SC-4, SC-7 |
| VT-2 | Differential accuracy, sign, ranges and CMRR | DF-2 to DF-4 |
| VT-3 | AFE noise at the ADC pin and at the AWG output, each with an external instrument; also re-measure the DAC's own noise over DC to 1 MHz | SC-6, AW-6 |
| VT-4 | Frequency response of scope and AWG | SC-5, SM-3, AW-3 |
| VT-5 | Overload, fault and unpowered tests | PR-1 to PR-4, AW-8 |
| VT-6 | AWG range, step, load, short circuit, DAC current and accuracy | AW-1 to AW-7, PW-3 |
| VT-7 | Loopback by external cable from the AWG output to a scope input, DC and sine; reported for information with no pass/fail limit | none |
| VT-8 | Supply current, ripple, and noise fed back to 3.3 V and AREF, at PW-6's minimum and at 5.25 V on the 5V pin | PW-1, PW-2, PW-4, PW-6 |
| VT-10 | Input resistance, capacitance, channel matching, crosstalk and ADC-pin source impedance | SC-3, SC-8, SC-9, SC-10 |
| VT-11 | Differential-mode setting (DF-1), and that the analog path is unchanged | DF-1 |
| VT-12 | Temperature drift | EN-1 |
| VT-13 | Analysis (section 13), by simulation and then measurement | AN-1 to AN-5 |
| VT-14 | Inspection and continuity check | PW-5, CA-1, MC-1 to MC-12 |
| VT-15 | Level band through the AFE: PAM16 by `tools/ets_pam.py` with the AFE in the loop, 3 runs with the first dropped, on each of the three Dues, compared with the Due alone | SM-5 |
| VT-16 | Equivalent-time path: bandwidth and noise density at the ADC pin with an external instrument. It is the first measurement that can separate the ADC's bandwidth from the DAC's | SM-3, SC-6 |
| VT-17 | The unfiltered AWG path: feed PRBS and PAM from the Due's DAC through the AWG output and an external cable to a scope input, and read it with the equivalent-time capture | AW-3, SM-8 |

## 13. Analysis the contractor must demonstrate


| ID | Analysis |
|---|---|
| AN-1 | Stability with real parasitics: phase margin at least 45 degrees |
| AN-2 | The ADC input settles to within 0.5 LSB inside the configured acquisition window (SC-10) |
| AN-3 | The DAC load is within the DAC's drive limits (AW-5) |
| AN-4 | Offset and gain drift of references derived from 3.3 V against AREF, over AREF 3.20 to 3.30 V (SC-2) |
| AN-5 | Noise at the ADC pin on both ranges and at the AWG output, as densities over the stage bandwidths, including resistor, amplifier, reference and supply-ripple contributions (SC-6, AW-6, PW-2) |

## 14. Deliverables and process


Schematic and simulation files, with simulation reports before any
assembly; a bill of materials with alternates; an assembly drawing; the
test procedure and results report; a written calibration note for the
client's host software. Each stage passes simulation review before assembly, and a design
review follows each phase's test report.

## 15. Out of scope

Range switching beyond SC-11's two ranges, AC
coupling, a differential AWG, anti-alias and reconstruction filtering (SC-5, AW-3), firmware and host software. A precision voltage reference is Phase 3's (section 9).

## 16. Decisions for the owner

Each records the owner's decision and what it affects.

| ID | Decision | Recommendation | Affects |
|---|---|---|---|
| D1 | Narrower input ranges beside ±5 V | **Decided 2026-11-10:** one, ±1.25 V, a level-shifting op-amp stage of as-built gain 1.10 to 1.16, selected by a Due pin through a solid-state switch, ±5 V at reset | SC-11, SC-4, the table in section 5 |
| D2 | Real-time corner and shape | **Decided 2026-11-10: no filter** (SC-5, SM-3). A single pole attenuates only about 6.6 dB at the one-channel Nyquist frequency, so it does not protect against aliasing; a proper filter would be a higher-order one in a later round | SC-5, SM-3 |
| D3 | Wide-path bandwidth target | **Decided 2026-11-10: at least 8 MHz**, confirmed by simulation at G1, including that the divider meets it at SC-10's source impedance | SM-3, SC-6, VT-16 |
| D4 | An unfiltered DAC0 test path | **Decided 2026-11-10: not needed**, since the AWG output has no filter (AW-3) | AW-3, VT-17, SM-8 |
| D5 | Phase 3's precision channel and its custom PCB | **Decided 2026-11-10: adopted**, on the same PCB as the other phases: 3a (reference, buffer, test point, AREF routing) and 3b (slow precision ADC and DAC). **Version 1 carries 3a and 3b, the precision DAC included** (owner, 2026-11-10) | section 9, MC-3, PA-1 to PA-9 |
| D6 | Drive AREF from the board's reference | **Decided 2026-11-10: measure only.** JR1 and BR1 stay untouched. The reference is routed to the AREF pin and unused by default (PA-7). Using it as ADVREF later is the owner's call, a rework of the Due described in [the Due reference network](../hardware/reference/arduino-due/v03/README.md); the owner judged soldering JR1 and BR1 too risky for now | PA-7, PW-5 |
| D7 | PW-1's current budget | **Decided 2026-11-10: a datasheet budget with headroom, not a measurement.** The Due is budgeted at 300 mA from 5 V: the SAM3X at 84 MHz draws 76.5 mA typical in active mode with peripheral clocks off (datasheet table 46-11, about 79 mA extrapolated to 90 MHz), the peripherals this project clocks add about 17 mA at 90 MHz (table 46-13: USB, ADC, DAC, TC0 to TC2, PIOA to PIOD, UART), the high-speed USB transceiver up to 60 mA while transmitting, and the rest of the board (the 16U2, LEDs, regulators) an allowance of 50 mA that no datasheet here gives: about 206 mA, with roughly 1.5x headroom. The Due's 3.3 V regulator is linear, so its 5 V current equals its 3.3 V current. The ADC's and DAC's analog currents were not found and sit inside the headroom. With the AFE's 100 mA the total is 400 mA, under PW-1's 450 mA. A meter reading may replace the estimate later | PW-1, section 4.3 |
| D8 | Connector and probe arrangement (MC-8) | **Decided 2026-11-10: BNC**, three of one 50 Ω part: two scope inputs taking ×1 and ×10 scope probes and the AWG output, on one board edge. The owner solders the connectors | MC-8 |
| D9 | Real-time target symbol rates | **Decided 2026-11-10: none set.** With no real-time filter there is no corner to set them from. The equivalent-time rate is not an AFE limit: 1.6 Msym/s is demonstrated | SM-3 |
| D10 | Who assembles the shield: the owner by hand, or a board house | **Decided 2026-11-10: the board house's assembly service, ordered once the PCB is out.** The owner hand-solders only the BNC connectors and headers. Fine soldering is a risk the owner has declined (JR1 and BR1). This sets the smallest part size and package in MC-3, to what the chosen service can place | MC-3 |
| D11 | The calibration ladder's tap count and part (PA-9) | **Decided 2026-11-10: up to 8 taps on A2 to A9, discrete 0.1% 0603 resistors**, reduced if the one-IC precision ADC has fewer than 10 inputs (PA-3), and never fewer than 4: two fit gain and offset, a third shows one bad tap, and a fourth keeps a fit after it is dropped. Unused pins of A2 to A11 stay free. The taps cost sample rate when read together, since one ADC serves every channel (section 4.1), so the ladder is read during calibration and not while capturing | PA-9 |
