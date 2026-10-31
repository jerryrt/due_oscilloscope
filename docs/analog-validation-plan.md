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
clock, which is MCK/4 at every trigger rate. The tree already has the
knob that tests the mechanism on one image: `=<tracktim>,<settling>A`,
applied at the next stream (`drivers/acq.c`), so `TRACKTIM` 0 against 15
read on A1 crosstalk is a direct control *(whether it takes effect in
loop mode is to be traced; check)*.

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
| No tolerance is written before its repeatability is measured: eight runs of the metric on this board, run 1 dropped by index, the spread is the tolerance floor. `tools/phase0.py` takes `--runs` (default 7) and neither it nor `host/repeat.py` drops run 1 today; phase 5 adds that | `measurement-suite.md`, `CLAUDE.md` |
| A key that becomes a gate takes its spread across board sessions (the reflash axis, or separate sessions), because an in-place repeat is one session and bounds only the variation inside it. Report the ratio between the axes, as `--axis both` does | `measurement-suite.md` |
| Every 90 MHz repeat run writes to a fresh `--out`, and `--report` refuses rows whose `provenance.mck_hz` differs, so a 78 MHz row cannot enter a 90 MHz spread (`records/phase0-*.jsonl` hold 78 MHz rows) | owner |
| Measure after about one minute powered | `measurement-suite.md` |
| A tolerance comes from `repeat.suggest_tolerance`, not from the range of the runs: a new draw falls outside the range of n draws with probability 2/(n+1), which is a quarter for seven *(derived)*. A one-sided gate is written as median minus (or plus) that tolerance, and a quantised key passes `floor=` (one timer tick for a rise) | `host/repeat.py` |
| The amplitude, crosstalk and silent-level values in `tests/baseline.json` date from 2026-08-22 at 78 MHz. Until phase 5 re-derives them they stay as tripwires only where they gate today, as an exception to the line below that the owner has to confirm; the file's header says which values are old. A 78 MHz value is otherwise never a gate | owner |
| One threshold per property across the ladder. A rate that misses it is the finding, not a reason for a per-rate threshold | here |
| Break each new or changed check on the thing it guards. Mutate a copy of the captured stream, never the stimulus: a feed-rate change trips the underrun check first. A mutation fails the checks of its own family and none outside it | `CLAUDE.md` |
| An unmeasured figure is marked *(check)* | `CLAUDE.md` |
| Promote a figure once, through `--calibrate` and `baseline.measured.json` | `measurement-suite.md` |
| Declare the conditions: board serial, commit, wiring, shield. `bench.json` `wiring` carries the facts, "A2 bare, shield stacked" with the jumpers; no separate note field exists | `host/provenance.py` |
| A null result says what the instrument could have detected | `CLAUDE.md` |

## Phases

Each edit has one owner, named in the phase's goal. Phase 0 changes rate
constants and the single MCK home; every logic change belongs to the
phase that names it. A phase's code exit runs against an interim or
synthetic threshold; the gate exits wait for phase 5.

| phase | goal | existing work to improve | code exit: can fail without any threshold from phase 5 |
|---|---|---|---|
| **0. Rates from the clock** | No tool or test holds a rate that was exact only at 78 MHz. Owns rate constants and the single MCK home, nothing else | A tree scan, built in an existing tree-scanning test (`tests/test_doc_references.py` has the normaliser and the floor pattern). It reads `tests/`, `host/`, `tools/` and `gui/`, normalises underscores and floats, and flags (a) an integer n with n = 39e6 // rc for some rc and n != 45e6 // rc for every rc, so 453488 flags and 200000 does not, and (b) the clock constants 39_000_000 and 78_000_000, plus rate-keyed dictionary keys. Expect a dozen exclusions, listed with a reason each, and a floor of files examined. Cases a literal scan cannot see are listed by hand and fixed in the phase that owns the logic: `tools/settletime.py` (202,000 is no rate at either clock, the defect is coprimality: phase 3), `tools/clock_calib.py` (`MCK_NOMINAL_HZ`), `tools/metrics.py` (`LADDER_RC`, `m_playback`'s 39 MHz divisor, `m_noise`'s 453,488 fallback), `tools/dso_metrics.py` (rate-keyed presets, a 78 MHz DAC ceiling), `tools/noisetool.py` presets, the period-21 lattice and its RC 195 trigger in `tools/issue5_metric.py`, and `tests/test_loop_overruns.py` (take ADC and DAC rates from `hz_for`). MCK has one home, `measure.py`: `eqtime.py` and `daemon/rates.py` read their own copy of the variable today, and the daemon already imports `measure`. Tools take MCK from the identity line or refuse when it differs | A board-free test shows each tool's rate arithmetic equals `measure.hz_for(rc)` with `DUE_MCK_HZ` at both clocks; a literal planted in a tool, a test and a dictionary key each fail the scan; the file count is asserted |
| **1. The ladder gets tone and crosstalk** | The matched loop is judged on signal quality at every rate. Owns the checks in `m_loop` and `_ladder_run`, including `m_loop`'s 1340 | `tests/test_rates.py` runs the RC ladders (`TWO_CH`, `ONE_CH`) and asserts rate, gaps and underruns inside `_ladder_run`, which asserts before it returns. Split a seam so the tone and window-purity checks from `test_integrity.py` take a result, with `tone = hz_for(rc) / 256`; the A1 check runs on `TWO_CH` only, since A1 is not captured on one channel. Count windows per run at the slow end (about 6 per 2 s run at RC 780) and lengthen it until every window can pass. `m_loop` takes the same checks | On a deep copy of the result, scale `series[CH_A0]` by 0.9 and the amplitude checks fail and nothing outside that family does; scale only a few windows and the window-fraction check fails; add to `CH_A1` a tone of three times the crosstalk ceiling and the crosstalk check fails at any phase. The `TRACKTIM` 0-against-15 control shows the crosstalk check can see the mechanism *(check)* |
| **2. DC transfer** | Gain and offset of the loop in one fit | `test_dc_transfer_tracks_the_code` is one test per code, runs only at 200 kHz, and gates each against `calibration.json`'s span through `cal.dac_span_mv()`, which never checks the board. Replace the per-code millivolt band with one fit in codes, run at 200 kHz and at RC 86 on two channels. Two checks: a regression gate on this board's own fitted slope and offset, and a loose physics bound against the nominal 2/3 whose width is stated from the datasheet's gain error *(check)*, not from repeatability. The `calibration.json` slope, 0.67053, is a reference from another board. No DNL | A code set with one level shifted by a stated number of codes leaves a residual above the fit's own noise and fails |
| **3. Rise and settling** | A scope-free rise figure, or a bound. Owns the `settletime.py` logic | Take the ADC request from the timer clock so its RC is prime, and refuse to report when fold coverage is below 1.0. Remove the `agrees` verdict and the `agrees` key from `settletime.py` and `m_settling`: the stored 789-938 ns range is a scope reading at what was probably the unconfigured bias *(check)*, and the tool prints it with that caveat and nothing else. The gate is coverage 1.0, `settletime.py control` reading FLAT and the period-scan margin. The bench cannot time a tail to one code, so a bound is an acceptable result | A board-free unit test: RC 222 against a 225 DAC is refused. Positive control: `settletime.py rise --ibctl 0,0` against the default 2,1, then restore 2,1 and read the ACR readback; the rise must be slower by more than the coverage's resolution. The firmware's default is already the characterised bias, so `--ibctl 2,1` changes nothing, and the 2.71 factor in `records/acr-rise.jsonl` is a 78 MHz reading from another bench, printed as a reference and never compared against |
| **4. Noise** | The loop's noise on a held code. Owns the protocol; rate constants are phase 0's | `phase0.py noise-fast` at 90 MHz is the figure, since it alone has a protocol on record (Tracks A and B). Hold the code at mid-scale. The 0.80 codes in `hardware.md` has no protocol on record, is marked *(check)* and is not a target. Cross-rate comparison after decimation is a reported result, not an exit: `docs/noise.md` reads 0.845 codes at 200 ksps and 0.657 at 453 ksps in the same 0-100 kHz band, because there is no anti-alias filter, so the two do not agree and are not expected to | Synthetic noise of known rms added to the captured series moves the figure by the root-sum-square |
| **5. Repeatability, then every gate** | A measured spread for every key and the gate exits of phases 1-4. Needs the code of phases 0-4 | Add scope-free entries to `tools/phase0.py` `METRICS`: the `m_loop` keys, the phase 2 fit and `settletime rise`; today it holds only the scope metrics and the noise ones, and its `settle` needs the scope. Eight runs, run 1 dropped by index in `host/repeat.py`, `--report` refusing mixed clocks, the reflash axis for every gate. Run at the ends of the ladder as well as at 200 kHz. Each key gets a tolerance from `repeat.suggest_tolerance`; the interim `baseline.json` values are re-derived here | A recorded spread per key, rate and axis; a key whose spread exceeds its proposed gate is reported, not gated. The gate exits: phase 1's thresholds, phase 2's slope and offset tolerances, phase 3's rise bound and phase 4's figure all come from here |
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
| ADC channel skew, A0 against A1 | the internal generator | The loop measures the DAC1-after-DAC0 lag plus the A1-before-A0 spacing as one figure. `drivers/gen.c` tags slot 0 DAC0 and slot 1 DAC1 in either layout, so `=0N`/`=1N` moves the signal and leaves both delays where they are: it does not separate them. The ADC-only figure is derived, one conversion is about 21.5 ADC clocks, half of the 43 per pair in `baseline.json`, so about 0.96 us at 22.5 MHz *(derived, check)*, and is measured only if the ADC's sequence order can be reversed, which is a firmware change not planned here. A1 is AD6 and converts before A0, which is AD7. `dso_metrics skew` measures DAC0 against its own DAC1 sync and is not the reference |
| Crosstalk against tone, and the bare A2 pin | `test_the_other_channel_stays_flat`, `tools/bleed_cadence.py`, `tools/wiring_probe.py` | A bare pin followed A0 at about 56% of its amplitude at 78 MHz *(old reference, check)*, so quiet does not mean unwired. `run_loop` can drive DAC1 through `build_ramp_tagged`. Phase 1 already varies the tone with the rate; this row varies the tone at a fixed rate |

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
| Do the 78 MHz amplitude tripwires keep gating until phase 5 re-derives them? | Yes, as a stated exception to the old-figures rule, because removing them leaves the loop unguarded for the whole plan |
| Which rates carry the phase 1 tone checks? | The whole existing ladder, at one threshold from phase 5 |
