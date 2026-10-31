# Re-taking the converters' analog figures at 90 MHz

**Status: plan. Nothing here is measured unless a row says so.**
[measurement-suite.md](measurement-suite.md) is the catalogue of what
this project measures about the converters and how a figure earns the
word baseline. This document does not repeat it. It says what the move
to a 90 MHz master clock changes, which rows of that catalogue are
re-taken on this bench, and which small pieces do not exist yet.

The only analog instrument on this bench is the DAC-to-ADC loop: DAC0
to A0, DAC1 to A1, A2 bare, a shield stacked on the board, no
oscilloscope. Every figure from an image at 78 MHz is an old reference -
another bench, another board, mostly unrecorded. It is read with a grain
of salt, printed beside a 90 MHz figure, and **never used as the arm it
is compared against or as the gate it must pass**. A 90 MHz figure is
judged by its own repeatability and by the physics.

## What the loop can and cannot judge

| fact | consequence |
|---|---|
| The DAC's reference is the ADC's, so the loop is ratiometric | Codes are the unit. Volts and absolute rate need something from outside; `host/calibration.py` carries the one record, for the board it names |
| The DAC is nominally 1/6 to 5/6 of the reference, so about 683-3413 codes (`docs/noise.md`, "the reference divides out") | Gain and linearity are judged over that span only |
| A0 and A1 are one converter behind a multiplexer | The ADC's INL is common to both channels; comparing them separates DAC0 from DAC1, not the ADC |
| The loop cannot separate the DAC's noise from the ADC's | A noise figure is the loop's, and is named so |
| Per-code DNL needs a meter | Not attempted; see "What this bench cannot measure" in `measurement-suite.md` |
| Tone and sample rate are different things | A table of N points at `fs_dac` gives `f = fs_dac * c / N`. Keep the DAC rate an integer multiple of the ADC rate so the staircase's images fold onto the tone *(derived, confirm on the bench)* |
| A fixed-length window leaks unless it holds whole tone cycles | Choose tone and rate so the 8192-sample window holds a whole number of cycles at every rate, or the analysis, not the converter, moves with rate |
| The ADC clock is MCK/4 at every trigger rate | A rate ladder varies the sample rate, not the converter clock |

## Rules for every phase

| rule | source |
|---|---|
| No tolerance is written before its repeatability is measured: N = 7 runs of the metric on this board, run 1 dropped by index, the spread is the tolerance floor | `measurement-suite.md`, `CLAUDE.md` |
| Measure after about one minute powered | `measurement-suite.md` |
| A gate that already passes at 90 MHz stays a gate; a new or changed one takes its value from the 90 MHz spread. A 78 MHz number is a printed reference, never a gate | owner |
| One threshold per property. A rate that misses it is the finding, not a reason for a per-rate threshold | here |
| Break each new or changed check on purpose, **on the thing it guards**, and watch it fail. Mutate the captured stream, not the stimulus: a feed-rate change fails the underrun check first | `CLAUDE.md` |
| An unmeasured figure is marked *(check)* | `CLAUDE.md` |
| Promote a figure once, through `--calibrate` and `baseline.measured.json` | `measurement-suite.md` |
| Declare the conditions: board serial, commit, wiring, shield. `bench.json` says only `DAC0->A0, DAC1->A1` and `host/provenance.py` has no shield field, so the plan states both in the record's note | `host/provenance.py` |
| A null result says what the instrument could have detected | `CLAUDE.md` |

## Phases

| phase | goal | existing work to improve | exit evidence that can fail |
|---|---|---|---|
| **0. Rates from the clock** | No tool or test holds a rate that was exact only at 78 MHz | A tree scan is the authority. It reads `tests/`, `host/`, `tools/` and `gui/`, matches integer literals that are 78 MHz rates or the timer clock and rate-keyed dictionary keys, excludes prose and synthetic signals by a list with a reason per entry, and refuses to pass when it examined fewer files than a floor. MCK has one home, `measure.py`; `eqtime.py` and `daemon/rates.py` read their own copy of the environment variable today and take it from there. Tools that compute rates take MCK from the identity line or refuse when it differs. Known cases with consequences: `tests/test_loop_overruns.py` (ceiling rate is RC 99 now; take ADC and DAC rates from `hz_for`), `tools/settletime.py` (its 202 kHz request folds one sixth of the phases), `tools/dso_metrics.py` (rate-keyed presets, a 78 MHz DAC ceiling), `tools/metrics.py` (`m_loop` holds 1340 and a 400k/200k pair, `m_noise` a 453,488 fallback, `m_playback` a 39 MHz divisor), `tools/noisetool.py` (preset table) | A board-free test shows each tool's rate arithmetic equals `measure.hz_for(rc)` with `DUE_MCK_HZ` at both clocks; a literal planted in a tool, in a test and in a dictionary key each fail the scan; the scan's file count is asserted |
| **1. Repeatability first** | A measured spread for every key a later phase will assert | `tools/phase0.py` over `host/repeat.py`, N = 7 per key on this board (Tracks A and B): tone amplitude per window, window fraction, A1 crosstalk, loop gain, noise rms, rise | A recorded spread per key; a key whose spread exceeds its proposed gate is reported, not gated |
| **2. The ladder gets tone and crosstalk** | The matched loop is judged on signal quality at every rate | `tests/test_rates.py` runs the RC ladders (two channels RC 780-86, one channel RC 390-44) and asserts rate, gaps and underruns. Add the tone and window-purity checks from `test_integrity.py` to `_ladder_run`, with whole cycles per window, and the A1 check on two-channel rows. Keep Hz derived from RC; count windows per run at the slow end and lengthen it until the window fraction means something. `tools/metrics.py` `m_loop` is brought to the same rates | Scale `res.stream.series[CH_A0]` by 0.9 and the amplitude check fails; add a synthetic tone of the ceiling's size to `CH_A1` and the crosstalk check fails; each mutation fails on its own check and on no other |
| **3. DC transfer** | Gain and offset of the loop in one fit | `test_dc_transfer_tracks_the_code` is one test per code and `test_dc_levels_are_monotonic` holds the order. Fit across the codes in one test. The slope is judged against the nominal 2/3 and against its own spread; the value in `calibration.json` is a reference from another board and bench. Report in codes. No DNL | A code set with one level shifted fails the fit; a slope outside the Phase 1 spread fails |
| **4. Noise** | The loop's noise on a held code | `phase0.py noise-fast` is the protocol, since it alone has a record (Tracks A and B). Hold the code at mid-scale. Compare rates only after decimating to a shared band, because raw rms across rates compares bandwidths (`docs/noise.md`). The 0.80 codes in `hardware.md` has no record: reproduce it with N = 7 or mark it *(check)*. `m_noise` and `noisetool.py` get the same rates | The figure is no lower than the ideal quantisation floor (`docs/noise.md`); a figure below it is a fault in the measurement. Repeat spread recorded |
| **5. Rise and settling** | A scope-free rise figure, or a bound | `tools/settletime.py`: take the ADC request from the timer clock so its RC is prime, and refuse to report when fold coverage is below 1.0. The gate is coverage 1.0, `settletime.py control` reading FLAT, the period-scan margin and the repeat spread. The stored 789-938 ns scope range is printed as a reference and no longer decides whether the figure is used; `m_settling` records the same fields. The bench cannot time a tail to one code, so a bound is an acceptable result | RC 222 is refused; a deliberately coarse fold is refused; the figure passes with the reference range hidden |
| **6. Not in the tree** | The pieces nothing covers | See below | Each has a mutation on the captured stream |

## Phase 6: what does not exist

Searched in `tests/`, `tools/` and `host/` for SINAD, THD, SFDR, INL and
ENOB: only the building blocks in `host/noise.py` exist.

| missing | built from | note |
|---|---|---|
| Coherent-sine SINAD, THD and ENOB | `host/noise.py` spectrum, Welch and line-split | The loop's SINAD includes the DAC's staircase and noise; the figure says so |
| A board test that gates the noise figure | `tools/noise_metrics.py`, Phase 1's spread | No board noise test exists; `baseline.json` has no noise key |
| Amplitude against tone | `run_loop(tone=...)` at varying `dac_sps`, `window_amplitudes`, whole cycles per window | The table's ideal fundamental and the hold are divided out. `tools/gen_sweep.py` runs one trigger rate and says only what changes inside a hold, so it is not the base. The DAC's own roll-off needs a DAC rate above the ADC's; its size is *(check)* and has no 90 MHz source |
| ADC channel skew, A0 against A1 | the internal generator on Track B, run in both layouts (`=0N`, `=1N`) | DAC1 lags DAC0 by about one trigger period, and the scope read -0.967 of one, not -1.000, so a fixed DAC-side offset exists that the loop alone cannot tell from the conversion spacing. Reversing the layout reverses the sign of the DAC lag while the ADC order stays fixed, which separates the two *(check)*. A1 is AD6 and converts before A0, which is AD7. About 0.96 us at 90 MHz is derived, not measured. `dso_metrics skew` measures DAC0 against its own DAC1 sync and is not the reference |
| Crosstalk against tone, and the bare A2 pin | `test_the_other_channel_stays_flat`, `tools/bleed_cadence.py`, `tools/wiring_probe.py` | A bare pin follows A0 at about 56% of its amplitude, so quiet does not mean unwired. `run_loop` can drive DAC1 through `build_ramp_tagged` |

`tools/wiring_probe.py`, `tools/gen_sweep.py` and the layout swap run on
Track B only, so the rows that rest on them are Track B rows and say so.
The suite's default is Tracks A and B; Track C is run as an extra gate.

## Not planned here

| item | why it is not a phase |
|---|---|
| The wrap displacement at 90 MHz | The campaign metric is pinned to a period-21 lattice measured against the RC 195 trigger. At RC 225 the comb period follows RC and would fall off the lattice and read small. The period has to be derived, and the metric shown to fire with the refresh bit restored, before any campaign runs *(check)* |
| Runs past 150 s | The soak tools in `tools/` are close-wedge soaks, not long-capture integrity runs. The 150 s capture in `hardware.md` has no record behind it *(check)* |
| Per-code DNL, absolute volts, the DAC's own INL | Need a meter or the bench scope; see `measurement-suite.md` |
| Crosstalk and settling beyond Phases 2 and 5 | Listed as unmeasured in `hardware.md`; Phase 2 and Phase 5 are the part this bench can take |

## Open decisions

| decision | default until answered |
|---|---|
| Who gates and who reports? | Board tests gate; `tools/metrics.py` reports. Both run without a scope |
| Which rates carry the Phase 2 tone checks? | The whole existing ladder, at one threshold |
