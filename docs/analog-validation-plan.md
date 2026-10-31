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
is compared against or as a gate a 90 MHz figure must pass**. A 90 MHz
figure is judged by its own repeatability and by the physics.

## Why these phases and not others

The ADC clock is 22.5 MHz against a 20 MHz limit, and with `TRACKTIM` at
0 its tracking and transfer times shrink with the ADC clock period
*(derived, check)*. That is the mechanism by which crosstalk, amplitude
at the top rates and linearity could move, so the phases that judge
signal quality at the top rates (1, 2 and the crosstalk rows) are the
ones that matter. The sample-rate ladder alone never varies the ADC
clock, which is MCK/4 at every trigger rate.

## What the loop can and cannot judge

| fact | consequence |
|---|---|
| The DAC's reference is the ADC's, so the loop is ratiometric | Codes are the unit. Volts and absolute rate need something from outside; `host/calibration.py` carries the one record, for the board it names |
| The DAC is nominally 1/6 to 5/6 of the reference, so about 683-3413 codes (`docs/noise.md`, "the reference divides out") | Gain and linearity are judged over that span only |
| A0 and A1 are one converter behind a multiplexer | The ADC's INL is common to both channels; comparing them separates DAC0 from DAC1, not the ADC |
| The loop cannot separate the DAC's noise from the ADC's | A noise figure is the loop's, and is named so |
| Per-code DNL needs a meter | Not attempted; see "What this bench cannot measure" in `measurement-suite.md` |
| Tone and sample rate are different things | A table of N points at `fs_dac` gives `f = fs_dac * c / N`. Keep the DAC rate an integer multiple of the ADC rate so the staircase's images fold onto the tone *(derived, confirm on the bench)* |
| A fixed-length window leaks unless it holds whole tone cycles | At the default 1 kHz tone no ladder rate gives a whole number of cycles in 8192 samples. Take `tone = hz_for(rc) / 256` so a cycle is 256 samples and a window holds 32 |
| The loop samples the DAC's staircase at a fixed phase within each hold | The data are table values plus settling at that delay, so the hold's sinc is not in them and must not be divided out |

## Rules for every phase

| rule | source |
|---|---|
| No tolerance is written before its repeatability is measured: eight runs of the metric on this board, run 1 dropped by index, the spread is the tolerance floor. `tools/phase0.py` takes `--runs 7` and neither it nor `host/repeat.py` drops run 1 today; phase 5 adds that | `measurement-suite.md`, `CLAUDE.md` |
| Measure after about one minute powered | `measurement-suite.md` |
| A tolerance comes from `repeat.suggest_tolerance`, not from the range of seven runs: a new run falls outside the range of seven about a quarter of the time | `host/repeat.py` |
| The amplitude values in `tests/baseline.json` stay as interim tripwires, only where they gate today, and each is re-derived from the 90 MHz spread in phase 5. That they pass is evidence they are not too tight and no evidence they are a test. A 78 MHz value is never a gate | owner |
| One threshold per property across the ladder. A rate that misses it is the finding, not a reason for a per-rate threshold | here |
| Break each new or changed check on the thing it guards. Mutate a copy of the captured stream, never the stimulus: a feed-rate change trips the underrun check first. A mutation fails the checks of its own family and none outside it | `CLAUDE.md` |
| An unmeasured figure is marked *(check)* | `CLAUDE.md` |
| Promote a figure once, through `--calibrate` and `baseline.measured.json` | `measurement-suite.md` |
| Declare the conditions: board serial, commit, wiring, shield. `bench.json` `wiring` carries the facts, "A2 bare, shield stacked" with the jumpers; no separate note field exists | `host/provenance.py` |
| A null result says what the instrument could have detected | `CLAUDE.md` |

## Phases

Each edit has one owner. Phase 0 changes rate constants only; the
others change logic.

| phase | goal | existing work to improve | exit evidence that can fail |
|---|---|---|---|
| **0. Rates from the clock** | No tool or test holds a rate that was exact only at 78 MHz | A tree scan, built in an existing tree-scanning test (`tests/test_doc_references.py` has the normaliser and the floor pattern). It reads `tests/`, `host/`, `tools/` and `gui/`, normalises underscores and floats, and flags integer literals that are an exact rate at 78 MHz and not at 90 (otherwise 200000 flags, which both clocks divide), plus rate-keyed dictionary keys. Prose and synthetic signals are excluded by a list with a reason per entry; the scan refuses to pass below a floor of files examined. Cases a literal scan cannot see are listed by hand: `tools/settletime.py` (its 202,000 request is no rate at either clock and the defect is coprimality; `rc_dac=195`), `tools/metrics.py` (`LADDER_RC`, `m_loop`'s 1340 and 400k/200k pair, `m_noise`'s 453,488 fallback, `m_playback`'s 39 MHz divisor), `tools/dso_metrics.py` (rate-keyed presets, a 78 MHz DAC ceiling), `tools/noisetool.py`, the period-21 lattice and its RC 195 trigger in `tools/issue5_metric.py`, and `tests/test_loop_overruns.py` (take ADC and DAC rates from `hz_for`). MCK has one home, `measure.py`: `eqtime.py` and `daemon/rates.py` read their own copy of the variable today, and the daemon already imports `measure`. Tools take MCK from the identity line or refuse when it differs | A board-free test shows each tool's rate arithmetic equals `measure.hz_for(rc)` with `DUE_MCK_HZ` at both clocks; a literal planted in a tool, a test and a dictionary key each fail the scan; the scan's file count is asserted |
| **1. The ladder gets tone and crosstalk** | The matched loop is judged on signal quality at every rate | `tests/test_rates.py` runs the RC ladders (its `TWO_CH` and `ONE_CH`) and asserts rate, gaps and underruns inside `_ladder_run`, which asserts before it returns. Split a seam so the tone and window-purity checks from `test_integrity.py` and the A1 check take a result, with `tone = hz_for(rc) / 256`. Count windows per run at the slow end and lengthen it until the window fraction means something. `tools/metrics.py` `m_loop` takes the same rates. Thresholds come from phase 5 | On a copy of the result, scale `series[CH_A0]` by 0.9 and the amplitude checks fail and nothing outside that family does; add to `CH_A1` a tone of twice the crosstalk ceiling phase-locked to A0, because a tone at the ceiling can cancel the existing bleed, and the crosstalk check fails |
| **2. DC transfer** | Gain and offset of the loop in one fit | `test_dc_transfer_tracks_the_code` is one test per code and gates each against `calibration.json`'s span through `cal.dac_span_mv()`, which never checks the board. `test_dc_levels_are_monotonic` holds the order. Replace the per-code millivolt band with one fit in codes, judged against the nominal 2/3 slope and the phase 5 spread; the `calibration.json` slope is printed as a reference from another board. No DNL | A code set with one level shifted fails the fit once phase 5 has set its tolerance |
| **3. Rise and settling** | A scope-free rise figure, or a bound | `tools/settletime.py`: take the ADC request from the timer clock so its RC is prime, and refuse to report when fold coverage is below 1.0. The gate is coverage 1.0, `settletime.py control` reading FLAT, the period-scan margin and the repeat spread. The stored 789-938 ns scope range is printed as a reference only; `m_settling` records the same fields. The bench cannot time a tail to one code, so a bound is an acceptable result | RC 222 is refused. A positive control: `settletime.py --ibctl` moves the rise by the factor `records/acr-rise.jsonl` holds *(check)*, so the instrument is shown able to see a change in the converter |
| **4. Noise** | The loop's noise on a held code | `phase0.py noise-fast` at 90 MHz is the figure, since it alone has a protocol on record (Tracks A and B). Hold the code at mid-scale. Compare rates only after decimating to a shared band, because raw rms across rates compares bandwidths (`docs/noise.md`). The 0.80 codes in `hardware.md` has no protocol on record, is marked *(check)* and is not a target. `m_noise` and `noisetool.py` take the same rates | Synthetic noise of known rms added to the captured series moves the figure by the root-sum-square; the decimated cross-rate comparison agrees within the repeat tolerance |
| **5. Repeatability, then thresholds** | A measured spread for every key, and the gates written from it | Add scope-free entries to `tools/phase0.py` `METRICS`: the `m_loop` keys, the phase 2 fit and `settletime rise`; today it holds only the scope metrics and the noise ones, and its `settle` needs the scope. Eight runs, run 1 dropped by index in `host/repeat.py`. Run after the code of phases 0-4, and at the ends of the ladder as well as at 200 kHz. Each key gets a tolerance from `repeat.suggest_tolerance`; the interim `baseline.json` values are re-derived here | A recorded spread per key and rate; a key whose spread exceeds its proposed gate is reported, not gated |
| **6. Not in the tree** | The pieces nothing covers | See below | Each has a mutation on a copy of the captured stream |

## Phase 6: what does not exist

Searched in `tests/`, `tools/` and `host/` for SINAD, THD, SFDR, INL and
ENOB: only the building blocks in `host/noise.py` exist. Each new test
takes its own eight runs before it gates anything.

| missing | built from | note |
|---|---|---|
| Coherent-sine SINAD, THD and ENOB | `host/noise.py` spectrum, Welch and line-split | The loop's SINAD includes the DAC's staircase and noise; the figure says so |
| A board test that gates the noise figure | `tools/noise_metrics.py`, phase 5's spread | No board noise test exists; `baseline.json` has no noise key |
| Amplitude against tone | `run_loop(tone=...)` at varying `dac_sps`, `window_amplitudes`, whole cycles per window | The loop samples at a fixed phase in each hold, so a run reports the step response at that delay and the amplitude depends on the phase between the two timers; control it and record it. Do not divide out a hold's sinc. A DAC rate above the ADC's raises the USB traffic, so the underrun and overrun gates hold on those rows. `tools/gen_sweep.py` runs one trigger rate and is not the base |
| ADC channel skew, A0 against A1 | the internal generator | The loop measures the DAC1-after-DAC0 lag plus the A1-before-A0 spacing as one figure. `drivers/gen.c` tags slot 0 DAC0 and slot 1 DAC1 in either layout, so `=0N`/`=1N` moves the signal and leaves both delays where they are: it does not separate them. The ADC-only figure is derived, 43 ADC clocks per pair (`baseline.json`) at 22.5 MHz is about 0.96 us *(check)*, and is measured only if the ADC's sequence order can be reversed, which is a firmware change not planned here. A1 is AD6 and converts before A0, which is AD7. `dso_metrics skew` measures DAC0 against its own DAC1 sync and is not the reference |
| Crosstalk against tone, and the bare A2 pin | `test_the_other_channel_stays_flat`, `tools/bleed_cadence.py`, `tools/wiring_probe.py` | A bare pin follows A0 at about 56% of its amplitude, so quiet does not mean unwired. `run_loop` can drive DAC1 through `build_ramp_tagged` |

The `=<n>N` command is bound on all three tracks. `tools/wiring_probe.py`
and `tools/gen_sweep.py` refuse boards that are not Track B, and that
gate is out of date under the tracks' parity rule; lifting it is a
prerequisite for any row that rests on them. The suite's default is
Tracks A and B; Track C is run as an extra gate.

## Not planned here

| item | why it is not a phase |
|---|---|
| The wrap displacement at 90 MHz | The campaign metric is pinned to a period-21 lattice measured against the RC 195 trigger. At RC 225 the comb period follows RC and would fall off the lattice and read small. The period has to be derived, and the metric shown to fire with the refresh bit restored, before any campaign runs *(check)* |
| Runs past 150 s | The soak tools in `tools/` are close-wedge soaks, not long-capture integrity runs. The 150 s capture in `hardware.md` has no record behind it *(check)* |
| Per-code DNL, absolute volts, the DAC's own INL | Need a meter or the bench scope; see `measurement-suite.md` |
| Reversing the ADC's sequence order | A firmware change; it is what would separate ADC skew from the DAC lag |

## Open decisions

| decision | default until answered |
|---|---|
| Who gates and who reports? | Board tests gate; `tools/metrics.py` reports. Both run without a scope |
| Which rates carry the phase 1 tone checks? | The whole existing ladder, at one threshold from phase 5 |
