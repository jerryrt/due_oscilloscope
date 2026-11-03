# AFE requirements

A minimal analog front end (AFE) for the Due scope and AWG: protection,
level scaling and a bipolar generator output in front of the Due's native
12-bit ADC and DAC. Two scope channels, one AWG output, and a
jumper-selected differential mode (Phase 1), with an optional
fully-differential amplifier assembly (Phase 2). The plan that builds it is
[afe-plan.md](afe-plan.md).

The AFE is designed, simulated, built and verified against the numbers
below. Values marked **TBC** are proposals the client must confirm.
Values marked *(check)* are quoted from the datasheet or project records
and are not yet re-verified for this design.

## Requirement IDs

| Prefix | Meaning | Section |
|---|---|---|
| SC | Scope input | 4 |
| DF | Differential mode | 5 |
| AW | AWG output | 6 |
| P2 | Phase 2 amplifier assembly | 7 |
| PR | Protection | 8 |
| PW | Power | 8 |
| CA | Calibration | 8 |
| EN | Environment | 8 |
| MC | Construction | 9 |
| VT | Verification test | 10 |
| AN | Analysis | 11 |

## 1. Scope

The AFE adds protection, level scaling and a bipolar generator output to
the Due's native converters. The design topology, part values and part
choices are the contractor's. Everything here is a requirement, a
constraint, a deliverable or an acceptance test.

## 2. Host system (client-supplied information)

| Item | Value |
|---|---|
| Board | Arduino Due (V03 reference), unmodified. JP101 open, JR1/BR1 untouched |
| AREF | The board's 3.3 V rail, about 3.27 V on the measured board. The client supplies per-board AREF and DAC-window values for its three Dues |
| ADC | 12-bit. 22.5 MHz clock on the 90 MHz build, 19.5 MHz on the in-spec 78 MHz build |
| ADC noise | 0.80 LSB rms on a held code at the 90 MHz default; 1.65 LSB rms (about 9.5 effective bits) with DAC0 driving the pin. `docs/noise.md`, `docs/hardware.md` |
| One channel | 1,022,727 sps (90 MHz build), 886,363 sps (78 MHz build) |
| Two channels | 1,046,510 sps in total, 523,255 per channel (90 MHz build); 453,488 per channel (78 MHz build) |
| DAC | 12-bit, weak drive. Output 0.578 to 2.771 V with a scope on the pin (`docs/hardware.md`); theory is 1/6 to 5/6 of AREF, a span of 2.13 V at AREF 3.20 V. Window centre about 1.67 V against a mid-AREF of 1.635 V |
| DAC noise | Earlier records say about 20 mV rms (15 mV idle) with the measurement bandwidth unrecorded; the ADC loopback reads about 1.3 mV. Treat the DAC's own noise as unknown until re-measured over DC to 1 MHz (VT-3) |
| ADC pins | Always A1 (CH1) and A0 (CH2), and no others. The AFE uses no other ADC channel, and the pins do not change between modes or phases |
| Differential ADC mode | A1 and A0 form one pair (AD6/AD7). Each pin stays between 0 V and AREF. PGA gain 1 gives full scale ±AREF/2, gain 0.5 gives ±AREF. The client confirms from the datasheet which pin is VIN+; this specification assumes CH1 on A1 is IN+ *(check)* |
| Power available | Due 5V and 3.3 V pins only. A0, A1 and the DAC pins are 3.3 V pins |
| Client supplies | Firmware, host software, the JP-DIFF input pin, and the ADC acquisition settings |

## 3. Phasing

| Phase | Content |
|---|---|
| 1 | Two single-ended scope channels, one AWG output, jumper-selected differential mode |
| 2 | An optional fully-differential amplifier assembly that reuses the Phase 1 design (section 7) |

## 4. Scope input (CH1 to A1, CH2 to A0)

| ID | Requirement |
|---|---|
| SC-1 | Default: two independent single-ended DC-coupled channels |
| SC-2 | Each input ±5 V, usable to ±6 V with the ADC pin inside 0 to AREF, with at least 80 mV of margin per side at AREF 3.20 V. This holds over AREF 3.20 to 3.30 V, component tolerance and a midpoint centring error of ±30 mV. The AREF spread is shown by analysis (VT-13) and by measuring each board as found, not by changing AREF |
| SC-3 | Input resistance 1 megohm per input. Input capacitance at most 30 pF including wiring (TBC) |
| SC-4 | At most 4 mV per ADC code at the input. ±5 V occupies 70 to 75% of ADC full scale at nominal AREF. At 70% the step is 3.5 mV, and the 75% end leaves about 10% of full scale at ±6 V |
| SC-5 | Low-pass with one dominant pole, −3 dB corner 270 kHz ±25%, no peaking above 0.5 dB, and no step in the response larger than 2% from divider compensation. Usable band DC to 200 kHz at 1 Msps on one channel, DC to 100 kHz at about 523 ksps per channel on two (90 kHz at 453 ksps on the 78 MHz build). Gain error across the band is corrected by host calibration. The AFE is not an anti-alias filter, and its documentation must say so |
| SC-6 | AFE noise referred to the ADC pin at most 0.5 mV rms over DC to 1 MHz. The Due's ADC cannot verify this (VT-3) |
| SC-7 | DC accuracy after host calibration: ±0.5% of reading ±5 mV, for the mean of at least 1024 samples |
| SC-8 | Channel matching, before host calibration: gain within 0.3%, offset within 5 mV, corner within 10% |
| SC-9 | Crosstalk: a full-scale input on one channel with the other input shorted changes the other channel's reading by at most 2 LSB at 1,022,727 sps (one channel) and 523,255 sps per channel (two channels), at the client's configured acquisition settings (TBC). The project records a 56% sample-and-hold memory on an undriven pin, so a low-impedance drive is expected |
| SC-10 | Source impedance at the ADC pin at most 5 kΩ (TBC), so the ADC settles to within 0.5 LSB inside its configured acquisition window and not the sample interval. The basis is the datasheet's 12-bit track time of 0.054 ns per ohm plus 205 ns *(check)* and 15 ADC clocks at 22.5 MHz (667 ns), which gives about 8.6 kΩ before margin |

## 5. Differential mode

| ID | Requirement |
|---|---|
| DF-1 | A jumper (JP-DIFF) selects differential mode, with CH1 = IN+ and CH2 = IN−. It only signals the mode to the firmware through a spare Due digital input pin (chosen by the client) and must not change the analog signal path |
| DF-2 | Two differential ranges, chosen by the firmware's PGA gain: ±5 V difference at most 4 mV per code, and ±10 V difference at most 7.5 mV per code. Each input stays within ±6 V. The contractor shows that every ADC pin stays inside the converter's differential-mode common-mode window *(check)* for the stated combinations and states any limit on input common mode |
| DF-3 | CMRR before host calibration, with each input driven from at most 100 ohms: at least 46 dB at DC on every unit and 40 dB at 10 kHz (typical 50 dB at DC, TBC). The input network uses parts of 0.1% tolerance or better |
| DF-4 | Accuracy after host calibration: ±0.5% of reading ±1 code, for the mean of at least 1024 samples. Bandwidth and noise per SC-5 and SC-6 |

## 6. AWG output (one channel, single-ended, from DAC0)

| ID | Requirement |
|---|---|
| AW-1 | Output ±1.0 V DC-coupled. As built, including the AW-7 tolerances and AREF 3.20 to 3.30 V, reaching ±1.0 V uses at most 92% of the board's DAC window |
| AW-2 | Step at most 1 mV |
| AW-3 | −3 dB corner 360 kHz ±25%, acting as the reconstruction filter. Usable band DC to 100 kHz, gain error corrected by host calibration |
| AW-4 | Load at least 10 kilohms, output impedance at most 50 ohms. A short to ground is safe indefinitely |
| AW-5 | Draws at most 0.1 mA from the DAC pin |
| AW-6 | AFE-added noise at most 1.0 mV rms over DC to 1 MHz, measured at the AWG output with DAC0 replaced by a quiet DC source at the same level. Total output noise with DAC0 driving is measured and reported, not guaranteed. The DAC's own noise is re-measured over DC to 1 MHz and reported before this figure is accepted |
| AW-7 | Accuracy: after calibration ±0.5% ±5 mV. As built, gain from the DAC pin to the output between 1.10 and 1.20 V/V and offset within ±60 mV including the DAC window's centre error (TBC). The offset reference is derived from AREF, not from 5 V |
| AW-8 | During Due reset or boot, with DAC0 undriven, the output stays within ±1.5 V and returns to the commanded value without exceeding ±1.5 V (TBC) |

## 7. Phase 2: fully-differential amplifier assembly

| ID | Requirement |
|---|---|
| P2-1 | Installs by replacing one removable amplifier assembly, with no cuts, rework or board changes |
| P2-2 | Reuses the Phase 1 input network, protection, output network, connectors, supply and JP-DIFF |
| P2-3 | Meets DF-2 to DF-4 and drives the A1/A0 pair with balanced signals. Its CMRR and noise are no worse than Phase 1's |
| P2-4 | Single-ended mode need not work while it is installed |
| P2-5 | The contractor states its input common-mode range |
| P2-6 | The Phase 1 design package defines the assembly's interface (pinout, voltages, loads) so Phase 2 needs no Phase 1 change |

## 8. Protection, power and environment

| ID | Requirement |
|---|---|
| PR-1 | Each scope input survives ±30 V continuous, powered or unpowered, and a signal applied with the Due unpowered or unconfigured. Above ±30 V the AFE may be damaged, but only in parts the owner can replace on the carrier, and the Due is not damaged |
| PR-2 | A0, A1 and the DAC pin stay between −0.2 V and 3.45 V in every supply and power-off state. This is a conservative limit against the pin's datasheet absolute maximum of −0.3 to +4.0 V *(check)*. Any driver of these pins is supplied at no more than 3.45 V |
| PR-3 | With the Due unpowered and ±30 V on a scope input, the current into the Due supply pins is at most 100 µA and the rails stay below 0.5 V (TBC) |
| PR-4 | The AWG output survives an external ±5 V for at least 10 s, powered or unpowered, and recovers without damage. Unpowered, the back-feed into the Due supply pins meets PR-3's limits. These excursions are exempt from PW-3 |
| PW-1 | Power only from the Due 5V and 3.3 V pins. At most 30 mA in normal operation with loads of at least 10 kilohms |
| PW-2 | Any negative or extra rail is made on the AFE, with ripple at the amplifier supply pins of at most 20 mV |
| PW-3 | With the AWG output shorted to ground indefinitely, total current is at most 60 mA with no damage (TBC against the Due's limits) |
| PW-4 | The rms noise on the Due 3.3 V pin and AREF rises by at most 0.5 mV over DC to 1 MHz when the AFE is connected, calculated as sqrt(on² − off²) |
| PW-5 | No Due modification |
| CA-1 | Calibration of gain, offset, frequency response and common-mode error is done in host software. The AFE has no trim elements, and its performance does not depend on any particular calibration instrument |
| EN-1 | 15 to 35 °C. Gain drift at most 0.2% and offset drift at most 3 mV over that range, excluding the Due's own drift (TBC) |

## 9. Construction

| ID | Constraint |
|---|---|
| MC-1 | Built on the client's Mega ProtoShield V3 carrier (103 x 55 mm), which stacks on the Due and exports every Due pin through sockets on its top side. The client supplies the KiCad project: [mega-proto-carrier](../hardware/mega-proto-carrier/README.md) |
| MC-2 | The carrier's 2.54 mm grid holes are isolated pads. The 28 holes tied to SMD lands (rows R04, R05, R11 and R12, columns C01 to C07) must not be used |
| MC-3 | All parts are through-hole, or surface-mount on adapters. No custom PCB in this scope |
| MC-4 | Signal pins (photo estimates): power at x=32 to 42 mm, A0 and A1 at x=47 and 50, DAC0 at x=80, along the carrier's bottom edge. The contractor confirms against the client's model |
| MC-5 | The design and assembly drawing map every pin to a grid hole, and record added wires and crossings |
| MC-6 | Design files use KiCad 10.x. Simulation models carry provenance and hashes |
| MC-7 | Fit and the AREF-spread conditions are demonstrated on the client's three Dues: fit by inspection, electrical performance by VT-1 and VT-6 repeated on each board as found |
| MC-8 | Connector type and the probe arrangement (×1 or ×10) are supplied by the client (TBC) |
| MC-9 | Every Due pin the AFE does not use passes through the board unchanged. No AFE net connects to an unused pin (checked by continuity), no part or wire covers a header socket, and every exported pin stays reachable from the top of the stack |
| MC-10 | All external connections are made on the AFE board. Nothing is wired to the Due's own headers while it is installed, and no loopback jumper (such as DAC0 to A0) is wired while the AFE circuit is fitted. Loopback is by an external cable between the AWG connector and a scope input connector |

## 10. Verification

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
| VT-4 | Frequency response of scope and AWG | SC-5, AW-3 |
| VT-5 | Overload, fault and unpowered tests | PR-1 to PR-4, AW-8 |
| VT-6 | AWG range, step, load, short circuit, DAC current and accuracy | AW-1 to AW-7, PW-3 |
| VT-7 | Loopback by external cable from the AWG output to a scope input, DC and sine; reported for information with no pass/fail limit | none |
| VT-8 | Supply current, ripple, and noise fed back to 3.3 V and AREF | PW-1, PW-2, PW-4 |
| VT-9 | Phase 2: repeat VT-2 and VT-3 with the assembly installed, and show installation needs no board change | P2-1, P2-3 |
| VT-10 | Input resistance, capacitance, channel matching, crosstalk and ADC-pin source impedance | SC-3, SC-8, SC-9, SC-10 |
| VT-11 | JP-DIFF function, and that the analog path is unchanged | DF-1 |
| VT-12 | Temperature drift | EN-1 |
| VT-13 | Analysis (section 11), by simulation and then measurement | AN-1 to AN-4 |
| VT-14 | Inspection and continuity check | P2-1, P2-2, P2-5, P2-6, PW-5, CA-1, MC-1 to MC-10 |

## 11. Analysis the contractor must demonstrate

| ID | Analysis |
|---|---|
| AN-1 | Stability with real parasitics: phase margin at least 45 degrees |
| AN-2 | The ADC input settles to within 0.5 LSB inside the configured acquisition window (SC-10) |
| AN-3 | The DAC load is within the DAC's drive limits (AW-5) |
| AN-4 | Offset and gain drift of references derived from 3.3 V against AREF, over AREF 3.20 to 3.30 V (SC-2) |

## 12. Deliverables and process

Schematic and simulation files, with simulation reports before any
assembly; a bill of materials with alternates; an assembly drawing; the
test procedure and results report; a written calibration note for the
client's host software; and, for Phase 2, the assembly design and its test
report. Each stage passes simulation review before assembly, and a design
review follows each phase's test report.

## 13. Out of scope

Range switching, AC coupling, a precision voltage reference, a
differential AWG, a 50 ohm terminated output, anti-alias filtering beyond
SC-5, firmware and host software.
