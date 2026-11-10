# The AFE requirement, reviewed against the ETS and PAM measurements

A review of [afe.md](afe.md) and of the 2026-11-09 draft on the branch
`afe-requirement-draft` (capture modes and a precision calibration channel),
against what the equivalent-time capture and the PAM4 to PAM128 runs of
2026-11-10 measured ([ets-mode.md](ets-mode.md), [ets-pam.md](ets-pam.md)).
These are proposals. Nothing in the requirement changes until the owner
decides, and the draft says the same of itself.

The draft closes with "Equivalent-time mode is untested on this hardware".
It is tested now, on the Due's own loop and on two Dues with independent
crystals, and eight of its statements change.

## What was measured that the requirement can use

| Fact | Figure | Where |
|---|---|---|
| The loop's edge floor, DAC pin to ADC code | 42.4 ns rise, 45.4 ns fall. An upper bound: it includes the DAC's own response | `ets-mode.md`, `ets-floor-linux-x1.jsonl` |
| Time axis of the fold, two independent crystals | 0.24 ns standard error of the fitted clock | `records/ets-pam-linux-x1.jsonl` |
| PAM levels that pass, DAC driving A0 | PAM4 to PAM32 at 1.0 V, PAM64 at 1.5 V, both benches. PAM128 fails | `ets-pam.md` |
| What closes an eye | a fixed band of 17.4 codes (`linux-x1`) to 19.5 codes (`montreal5`, probes on) around every level, from its 0.1% to 99.9% points at the symbol centre, the same at every level count and at both swings | `ets-pam.md` |
| The band in volts at the ADC pin | 14 to 16 mV (0.806 mV per code) | derived |
| Level spread, one standard deviation | 1.4 codes (`montreal5`) and 2.4 codes (`linux-x1`), 1.1 to 2.0 mV | `ets-pam.md` |
| Straightness of the ladder over a 1.5 V window | largest residual from a line 0.3 to 0.5 codes at 64 and 128 levels | `ets-pam.md` |
| Steps between the outermost levels at 2 V | leave a tail of 7 to 10 codes at the next symbol centre; at 1.5 V it is 3 | `ets-pam.md` |

Not measured: which converter, the DAC or the ADC, holds the floor.

## Findings, in order of consequence

### 1. A fixed input range limits the PAM level count to what the signal fills

The eye closes when the level spacing falls below the band. The band is fixed
in ADC codes, so its size at the input is the band times the volts per code.
With SC-4's 3.5 to 4 mV per code that is about 60 to 80 mV at the input, and a
signal of peak-to-peak amplitude A carries as many levels as `1 + A / band`:

| Signal, peak to peak | Levels that fit | Result |
|---|---|---|
| 0.5 V | 7 to 9 | PAM4 passes, PAM8 (71 mV spacing) is on the limit |
| 1 V | 13 to 17 | PAM8 passes (143 mV), PAM16 (67 mV) is on the limit |
| 2 V | 26 to 34 | PAM16 passes, PAM32 (65 mV) is on the limit |
| 5 V | 63 to 84 | PAM64 (79 mV) is on the limit |
| 10 V, the full range | 126 to 167 | PAM128 (79 mV) is on the limit |

All derived from the band above, not measured through an AFE. The point is that
the signals a PAM scope is pointed at are usually 1 V or less, and the
specified AFE has one range, ±5 V. It would reach PAM8 on them. **Proposal:**
selectable input ranges, a gain ahead of the ADC that fills the ADC for the
signal at hand, so the band referred to the input shrinks by the gain. SC-4 and
SC-2 describe the widest range; add the narrower ones with the same protection
(PR-1) and the same 1 megohm input. The ranges are a decision for the owner and
a design cost for the contractor; the PAM level counts are what they buy.

### 2. SC-6 bounds the wrong bandwidth for the equivalent-time path

SC-6: AFE noise at the ADC pin at most 0.5 mV rms over DC to 1 MHz. The
equivalent-time path is a wide path with no anti-alias filter (draft SM-3), and
the ADC's sample-and-hold folds every frequency the pin carries into the
sample. The loop's edge floor says the sampled path passes at least 8 MHz
(0.35 over 42.4 ns, derived). White noise of 0.5 mV rms over 1 MHz is
500 nV per root hertz, which over 10 MHz is 1.6 mV rms: more than the ADC's own
spread. **Proposal:** state the AFE's noise as a density at the ADC pin and the
bandwidth it applies to. For 0.5 mV rms over a 10 MHz path the density is at
most 160 nV per root hertz (derived). Added in quadrature to the Due's 1.1 to
2.0 mV spread, 0.5 mV widens the Gaussian part of the band by 3 to 8%; 0.3 mV
by 1 to 3%. The Due's ADC cannot verify this (VT-3 already says so).

### 3. The AWG's reconstruction filter conflicts with using the DAC as the test source

AW-3 puts a 360 kHz corner on the AWG output as its reconstruction filter. The
PAM and PRBS runs drive the DAC at 1.6 Msym/s, a repeating pattern whose
content is above 360 kHz. If the scope's own verification of PAM and eye
performance rests on the AWG, as the draft's calibration section suggests, the
filter removes the signal. **Proposal:** a bypass or a second unfiltered test
point from DAC0 (through a 50 ohm resistor, within AW-5's 0.1 mA draw if
buffered), so the equivalent-time path can be verified without a source the AFE
did not add. Also state a settling figure for the AWG: the DAC leaves a tail of
7 to 10 codes after steps above about 1.5 V, and AW-2 (1 mV step) says nothing of
it.

### 4. SM-3's bandwidth can now be given a number

The draft leaves the equivalent-time bandwidth open, "limited by the Due's ADC
input, which is not measured". The loop's edge floor (42.4 ns rise) is an upper
bound on what the Due's DAC and ADC together add, so the ADC input is not the
limit near 1 MHz. **Proposal:** a target above the loop's own, set from the
signals of interest, with the Due's figure as the reference it must not
degrade. 8 MHz is derived and the true figure is not known: the floor includes
the DAC, so it is a lower bound on the ADC's bandwidth.

### 5. SM-5 can be written as a measurable acceptance

SM-5 says the AFE and ADC INL and DNL must be small enough to separate 4 and 8
levels, figure TBC. What separates levels is the band, not INL. **Proposal:**
the AFE adds at most 10% to the band of 17.4 to 19.5 codes, measured with
`tools/ets_pam.py` on PAM16 through the AFE, 3 runs, first dropped.

### 6. SM-7 is no longer open, and the host's limits should be stated

The draft asks for the ADC trigger's timer jitter to be measured. The fold's
time axis is 0.24 ns standard error on two independent crystals, which includes
the two clocks' relative wander (about 2.3 ppm), fitted as a low-order curve.
Three limits belong in the requirement, because they decide what the host can
and cannot capture: the tracker locks with a template of a known repeating
pattern; a repeating signal of unknown content has no demonstrated host path;
the ADC and DAC rate pair must follow the rule of `ets-mode.md` (odd DAC RC
with an even ADC RC on two boards, coprime on one) or the lock degrades;
single-shot events are out of reach by construction.

### 7. The precision calibration channel: INL is not the case for it

The draft motivates a 16-bit ruler by "gain, offset and INL". Over a 1.5 V
window the DAC and ADC together lie on a straight line to 0.3 to 0.5 codes at 64
and 128 levels, against a band of 17 to 20 codes. That says INL is not what
limits the eye, for the window tested (0.65 to 2.65 V, not the full ADC range).
What the ruler still earns: absolute gain, offset and AREF; and splitting the
DAC's noise from the ADC's if its bandwidth covers DC to 1 MHz, which VT-3 asks
for and a slow noise-free converter does not give. Its costs are real: a custom
PCB, and a switch whose leakage and capacitance (PA-4) sit on the path that
finding 4 wants wide. **Proposal:** state the justification as absolute accuracy
and noise separation, and give PA-1 the bandwidth VT-3 needs for the second.

### 8. Probes and board spread belong in the requirement

The band is 19.5 codes with the scope probes on and 17.4 on another bench,
whose spread is the larger (2.4 codes against 1.4). The probes' tail and the
board-to-board spread (1.7 times in the standard deviation) are both larger than
the AFE noise target. **Proposal:** every noise and band figure is stated per
board, and the acceptance tests run on all three Dues, as VT-13 already does for
AREF.

## Changes proposed, by identifier

| ID | Now | Proposed |
|---|---|---|
| SC-2, SC-4 | one range, ±5 V, at most 4 mV per code | add narrower ranges that fill the ADC, same protection and input resistance |
| SC-6 | 0.5 mV rms over DC to 1 MHz | a density at the ADC pin and the bandwidth it applies to; 160 nV per root hertz for 0.5 mV over 10 MHz |
| SM-3 | bandwidth TBC | a target above the loop's measured 8 MHz equivalent, TBC |
| SM-5 | INL and DNL small enough for 4 and 8 levels | the AFE adds at most 10% to the level band |
| SM-7 | trigger jitter to be measured | 0.24 ns measured; state the host's known-pattern and rate-pair limits |
| AW-3 | 360 kHz reconstruction filter | keep, and add a bypass or an unfiltered DAC0 test point |
| PA-1, PA-3 | slow 16-bit ruler for INL | justify on absolute accuracy and noise separation; bandwidth to DC to 1 MHz for the latter |
| draft section 7, item 7 | target symbol rates TBC | 1.6 Msym/s demonstrated on the loop; real-time rates unchanged |

## Not established

- Which converter, the DAC or the ADC, holds the floor. Settling it needs a
  source that is not the DAC at an ADC pin, or a software route through the
  ADC's temperature-sensor channel (a firmware change on all three tracks).
- The ADC's true input bandwidth. The floor of 42.4 ns is an upper bound that
  includes the DAC.
- Anything through an AFE. Every figure above is the Due alone.
- PAM256, and PAM128 at 2 V, which were not run.
