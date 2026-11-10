# Equivalent-time sampling: what resolution this hardware can give

The ADC converts at most once per 0.98 us, and a DAC edge worth looking
at lasts tens to hundreds of nanoseconds. Equivalent-time sampling (ETS)
closes that gap for a **repeating** waveform: the ADC trigger and the
waveform run as two timers on one clock with different periods, so
successive samples land at successive phases of the waveform and a fold
puts them in order. `host/eqtime.py` is the reconstruction;
`tools/settletime.py` and `tools/square_shape.py` use it. Nothing in the
firmware knows about ETS: the `=<dac>,<adc>,<n>M` preset supplies the two
independent timers, and the host does the rest.

A source on a second board, with its own crystal, is a different case: the
relative phase is no longer a whole number of ticks and the time axis stops being
a lattice. How to run it, the rule for choosing the DAC and ADC RC, the tools and
what has been measured are in `docs/ets-mode.md`.

Figures marked *(check)* are unverified: read from the SAM3X datasheet
(`docs/datasheets/`) or derived from it, and not confirmed on a board.
Section numbers are the datasheet's. The ADC clock here is 22.5 MHz
against a 20 MHz datasheet maximum, so every ADC figure taken from the
datasheet is an extrapolation past its stated range *(check)*.

## The answer

Each layer is in series with the next; the measured edge is what is left
after all of them.

| layer | what sets it | value at MCK 90 MHz |
|---|---|---|
| Trigger placement | TC clock `TIMER_CLOCK1` = MCK/2 (Timer Counter, clock selection) | 22.2 ns |
| ADC start, relative to its trigger | delay of "2 MCK clock periods to 1 ADC clock period" (44.6.5) | 22.2 to 44.4 ns. Measured: the start snaps to the ADC's own clock edge, so at an odd ADC RC odd and even triggers differ by one tick, and the sample instants lie on a **44.4 ns lattice**; an even ADC RC puts every trigger at one phase (`docs/ets-mode.md`) |
| Sample formed by the track-and-hold | single pole read from `tTRACK` = 0.054 x Zsource + 205 ns (46.7) | rise of 50 to 54 ns, under two settling criteria. The measured edge floor, which also holds the DAC's own response, is 42 to 48 ns (`docs/ets-mode.md`), so this reading is pessimistic *(check the formula's assumptions)* |
| The waveform's own edge | the DAC's slew and bias | 277 to 300 ns at full step, default bias; small-step value unknown (`docs/awg.md`) |
| DAC trigger to output | 25 DACC clock periods (45.6.1) | 555.6 ns, a constant offset only if the DAC start delay is constant and no refresh conversion intervenes *(check)* |
| Vertical noise at one position | converter and DAC noise over the samples that land there | falls as 1/sqrt(samples) if white |

So **one fold samples the edge every 44.4 ns, and the track-and-hold limits
what passes through it to at most 42 to 48 ns of rise, measured.** Two folds with
the waveform shifted one tick interleave to 22.2 ns under the conditions
below. That finer grid describes the edge's shape up to the
track-and-hold limit and no further.

## The model

Let `P` be the waveform period and `R` the ADC trigger period, both in TC
ticks (`t_c = 2 / MCK`). The `n`-th trigger fires at tick `n R`, so it
falls at phase

    phi(n) = (n R) mod P

of the waveform. `P` is an integer: `2 * points * RC_dac`, or
`points * RC_dac` in solo mode (`eqtime.period_ticks`).

**Coverage of tick positions.** `n R mod P` visits every one of the `P`
tick positions once per `P` samples if and only if `gcd(R, P) = 1`;
otherwise only the multiples of `gcd(R, P)`.
`settletime.require_full_coverage` and `settletime.refuse_unless_coprime`
hold this.

**Why the fold is exact.** Everything above is integer arithmetic on
tick counts, and both timers share MCK, so the relative phase does not
drift. A dropped frame breaks `n -> time`; `check_contiguous` refuses the
run.

**Trigger spacing.** Triggers must be "strictly greater than the duration
time of the longest conversion sequence" apart (44.6.5). The
floor is measured and not computed, because tracking of the next channel
overlaps the previous conversion (44.6.1): 43 ticks per conversion on two
channels (RC 86, 1,046,510 conversions per second in all) and 44 ticks on
one (RC 44, 1,022,727 per second). That bounds `R` from below
(`ACQ_MIN_RC`) and so sets how fast a capture accrues samples.

## Where the position resolution comes from

Two trigger edges one tick apart need not give two sample instants.

* The datasheet says the ADC starts "after a delay starting at each
  rising edge of the selected signal" and that "due to asynchronous
  handling, the delay may vary in a range of 2 MCK clock periods to 1 ADC
  clock period" (44.6.5). At `PRESCAL` = 1 the ADC clock is 22.5 MHz, so
  the delay lies between 22.2 and 44.4 ns. The datasheet gives a range,
  not a mechanism.
* Both clocks divide MCK, so the delay is a repeatable function of the
  trigger's phase against the ADC clock. If it snaps to the next ADC
  clock edge, the sample instant depends only on which ADC clock edge
  follows the trigger. Two conditions make that a lattice: the ADC
  clock's phase against `TIMER_CLOCK1` is fixed for the capture (true per
  boot, value unknown), and the snap is the whole of the delay.
* The consequence for the fold: `P` is even, so a fold reaches `P / 2`
  distinct sample instants, each carried by two adjacent tick positions
  with equal values. Measured on `linux-x1`'s two boards: at an odd ADC RC
  the odd and even samples place an edge exactly one tick (22.2 ns) apart, on
  rising and falling edges alike, and at an even ADC RC they agree to 0.02 ns
  (`records/ets-cross-linux-x1.jsonl`), so the snap is real. `tools/square_shape.py`
  places each sample at its own tick, so its tick-resolution rise times
  are quantised at 44.4 ns.

**Interleave.** Fix the lattice and move the waveform one tick between
two folds. The DAC edge moves 22.2 ns against the lattice, so the second
fold samples the same edge half a lattice step away, and the two merge to
a 22.2 ns grid. This needs the conditions above, plus a DAC edge that
moves by exactly the trigger shift: the DACC trigger-to-start delay must
be constant *(check)*.

**Finer than a tick.** The PWM block can count at MCK (11.1 ns), and the
DACC lists PWM Event Lines 0 and 1 as triggers (`DACC_MR.TRGSEL`); the
ADC's table lists Event Line 0 twice (`ADC_MR.TRGSEL` values 4 and 5), so
Event Line 1 for the ADC is an inference. The DACC runs on MCK/2
(45.6.1), so a trigger is probably taken on its own 22.2 ns clock edge,
which would absorb a finer shift. No claim below 22.2 ns is made *(check)*.

## What the sample is

During tracking the sample capacitor charges toward the input through
the source and the switch, so the value held is the input filtered by a
single pole, read where the hold begins.

The datasheet gives the time the ADC must track: `tTRACK = 0.054 x
Zsource + 205` ns, 12 bit (46.7), with the note that the formulas take
`Csample` and `Ron` into account. It does not say what accuracy that
settles to. Two readings bracket it:

| settling criterion | time constants | `tau` at Zsource = 0 | 10-90% rise, 2.2 `tau` |
|---|---|---|---|
| 1 LSB of a full-scale step | `ln 4096` = 8.3 | 24.7 ns | 54 ns |
| 1/2 LSB | `ln 8192` = 9.0 | 22.8 ns | 50 ns |

The slope gives `Csample` = 0.054 ns per ohm over 8.3 = 6.5 pF (6.0 pF
at 9.0), which is consistent with the stated 8 pF maximum input
capacitance (Table 46-36) and implies a switch resistance near 3.8 kohm, which nothing confirms. A
fixed part of the 205 ns may not be RC at all, which would make `tau`
smaller; and a smaller worst-case step would make it larger. So these
figures are an interpretation of one formula *(check)*, valid only if the
tracking window is at least `tTRACK`. The firmware's
default is `TRACKTIM` 0 and `TRANSFER` 1 (`drivers/acq.c`). The register
reads as `(TRACKTIM + 1)` = 1 ADC clock of programmed tracking and
`(TRANSFER x 2 + 3)` = 5 clocks of transfer; the datasheet's case 1 for
this setting takes `tTRACK` as 15 ADC clocks (667 ns), the overlap with
the previous conversion *(check)*. The measured edge floor, 42 to 48 ns,
sits below both readings.

Consequences:

* A rise measured through the ADC is approximately
  `sqrt(t_edge^2 + t_adc^2)`, exact only for Gaussian responses, and no
  smaller than the larger of the two. Quantisation of the grid can read
  it lower.
* An edge faster than the track-and-hold reads as slow as it. The
  floor in `square_shape`'s small-step rises is the same size as the
  estimate above; that is a coincidence of two numbers until an instrument
  that does not use this ADC shows the edge.
* Carry-over: a tracking window that is short against `Rsource x C`
  leaves part of the previous conversion's value in the sample. On a
  multichannel trigger that is the previous channel, it is periodic with
  the waveform, and so it folds *coherently* into the curve instead of
  averaging out.
* Channel offsets: with `n` channels one trigger starts `n` conversions,
  spaced by the measured per-conversion interval above (about 0.96 us).
  Each channel folds on its own; the phase between channels is shifted by
  that fixed offset.

## Vertical resolution and the timing it implies

With a folded point built from `N_i` samples, the vertical noise is the
single-sample noise over `sqrt(N_i)` if it is white and uncorrelated with
phase. On the lattice model a capture of `N` samples puts `N / (P / 2)`
on each distinct instant: at 100 kHz `P` is 448 ticks, and at
`RC_adc` 221 (203.6 ksps per channel) a 3 s capture of 611,000 samples
per channel gives about 2,700 per instant. The DAC's own noise
(`docs/awg.md`) may not be white against phase *(check)*, and then the
bound is optimistic.

For an edge of slope `s` and vertical noise `sigma_v`, the time at which
it crosses one level is known to

    sigma_t = sigma_v / s

so at 6 V/us it is 0.11 ns for the single-sample noise of 0.80 codes
(0.64 mV) that `records/phase0-noise-fast-90mhz-b.jsonl` holds: A0
driven by DAC0 at a held code, 523,255 sps, `linux-x1`, Track B, 90 MHz.
The DAC's noise that reaches the sample at a held code is inside that
figure. Averaging
over `N_i` divides it by `sqrt(N_i)`.

That is the random part, and it holds only where the shape between
samples is known. A 10-90% edge spans one or two points of the 44.4 ns
lattice and two or three of the 22.2 ns grid, the shape between them is
assumed linear, and the systematic error of that is the size of a
lattice step, not of `sigma_t`.

## Reading the result

| question | answer from the model |
|---|---|
| Can the ADC sample a 750 kHz square directly? | No. An edge needs sample spacing well below its rise time and one channel converts every 0.98 us at best (RC 44, 1,022,727 Hz at 90 MHz). ETS needs only that the waveform repeats and the clocks are locked |
| What is the finest edge time it can state? | At most 42 to 48 ns of rise, measured: an upper bound that holds the DAC's own response too, below the 50 to 54 ns the datasheet formula reads, whatever the fold grid |
| What does a finer grid buy? | A cleaner edge shape up to that limit, and no more |
| What does an edge faster than the limit look like? | A rise that stops shrinking as the step shrinks, near `2.2 tau` |

Where a measurement and this model disagree, the measurement stands.
