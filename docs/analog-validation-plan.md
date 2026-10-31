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
is compared against or as the source of a tolerance**. A 90 MHz figure
is judged by its own repeatability and by the physics.

## Why these phases and not others

The ADC clock is 22.5 MHz against a 20 MHz limit, and with `TRACKTIM` at
0 its tracking and transfer times shrink with the ADC clock period
*(derived, check)*. That is the mechanism by which crosstalk, amplitude
at the top rates and linearity could move, so the phases that judge
signal quality at the top rates (C and D) are the ones that matter. The
sample-rate ladder alone never varies the ADC clock, which is MCK/4 at
every trigger rate.

The knob for the mechanism exists on all three tracks, `=<tracktim>,<settling>A`,
and reaches the converter at every stream start. It is a reported
experiment and not a control: `hardware.md` records that it left the
sustained rates identical to the sample at 78 MHz, so a null from it
cannot tell a blind check from a knob that does nothing.

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
| No tolerance is written before its repeatability is measured: eight runs of the metric on this board, the first run of each axis dropped (`run == 0`; `tools/phase0.py` numbers runs from 0), the spread is the tolerance floor | `measurement-suite.md`, `CLAUDE.md` |
| Measure after about one minute powered. On the reflash axis every run follows a flash, so the tool waits a minute after each flash and discards one throwaway run before the recorded one | `measurement-suite.md` |
| A key that becomes a gate takes its spread across board sessions, because an in-place repeat is one session and bounds only the variation inside it. Report the ratio between the axes, as `--axis both` does | `measurement-suite.md` |
| Every 90 MHz repeat run writes to a fresh `--out`, and `--report` refuses rows whose `provenance.mck_hz` differs; the existing `records/phase0-*.jsonl` rows are all 78 MHz | owner |
| A tolerance comes from `repeat.suggest_tolerance`: a new draw falls outside the range of n draws with probability 2/(n+1), a quarter for seven *(derived)*. A one-sided gate is median minus (or plus) the tolerance, and a quantised key passes `floor=` (one timer tick, 22.2 ns, for a rise) | `host/repeat.py` |
| The amplitude, crosstalk and silent-level values in `tests/baseline.json` are absolute bounds on gain and multiplexer bleed that date from 2026-08-22 at 78 MHz on another board. They keep gating as guards against gross failure; a failure at 90 MHz is a finding and is never widened away. Their headroom is large (Track B at 200 kHz: A0 window median 1371.8 against a floor of 1340, A1 0.13 codes against a ceiling of 12 *(one session, unrecorded; check)*), so they cannot show that 90 MHz moved the analog behaviour, and phase G re-derives each | owner |
| One threshold per property across the ladder. A rate that misses it is the finding, not a reason for a per-rate threshold | here |
| Break each new or changed check on the thing it guards. Mutate a deep copy of the captured stream, never the stimulus: a feed-rate change trips the underrun check first. A mutation fails the checks of its own family and none outside it | `CLAUDE.md` |
| An unmeasured figure is marked *(check)* | `CLAUDE.md` |
| Promote a figure once, through `--calibrate` and `baseline.measured.json` | `measurement-suite.md` |
| Declare the conditions: board serial, commit, wiring, shield. `bench.json` `wiring` carries the facts, "A2 bare, shield stacked" with the jumpers; no separate note field exists | `host/provenance.py` |
| A null result says what the instrument could have detected | `CLAUDE.md` |

## Phases

Each edit has one owner, named in the phase's goal. A phase's **code
exit** stands alone, against an interim or synthetic threshold. The
**gate exits** wait for phase G. Order: A, B, then C to F, then G, then H.

| phase | goal | work on existing code | code exit that can fail |
|---|---|---|---|
| **A. Rates from the clock** | No tool or test holds a rate that was exact only at 78 MHz. Owns rate constants and the single MCK home | The scan and the hand cases in the two tables below. MCK has one home, `measure.py`: `eqtime.py` and `daemon/rates.py` read their own copy of the variable today, and the daemon already imports `measure`. Tools take MCK from the identity line or refuse when it differs | A board-free test shows each tool's rate arithmetic equals `measure.hz_for(rc)` with `DUE_MCK_HZ` at both clocks; a literal planted in a tool, a test and a dictionary key each fail the scan; the scan's file count is asserted |
| **B. Repeat tooling** | The rules above exist in `tools/phase0.py` and `host/repeat.py`. Owns those two files | Drop `run == 0` of each axis; make `--report` refuse mixed clocks; make the reflash axis wait a minute and discard a throwaway run; add the scope-free entries as their phases land (`m_loop` keys, the phase D fit, `settletime rise`; today `METRICS` holds only the scope metrics and the noise ones). `phase0.py --track` accepts `a` and `b` only, so Track C gets no spread | Board-free: a synthetic series with a planted first-run outlier loses it; rows of two clocks are refused; the reflash path waits |
| **C. The ladder gets tone and crosstalk** | The matched loop is judged on signal quality at every rate. Owns the checks in `m_loop` and `_ladder_run`, including `m_loop`'s 1340 | `tests/test_rates.py` runs the ladders `TWO_CH` and `ONE_CH` and asserts rate, gaps and underruns inside `_ladder_run`, which asserts before it returns. Split a seam so the tone and window-purity checks from `test_integrity.py` take a result, with `tone = hz_for(rc) / 256`; the A1 check runs on `TWO_CH` only, since A1 is not captured on one channel. `m_loop` moves to the matched `hz_for(rc)` rates and the same tone; it asks for `dac_sps=200000, adc_hz=400000` today. At RC 780 a 2 s run leaves 7 windows after the 1 s settle, so one bad window fails a 0.9 fraction: lengthen the run until that is not the case | On a deep copy of the result, scale `series[CH_A0]` by 0.9 and the amplitude checks fail and nothing outside that family does; scale only a few windows and the fraction check fails; add to `CH_A1` a tone of three times the crosstalk ceiling and the crosstalk check fails at any phase. **Instrument control:** pair A0 with the bare A2 (`=2C`, restore `=1C`) and run the crosstalk check against `CH_A2`; it must fail, because A2 follows A0 at about 56% of its amplitude *(78 MHz reference, check)*. The check is shown able to see a real coupling path |
| **D. DC transfer** | Gain and offset of the loop in one fit | `test_dc_transfer_tracks_the_code` is one test per code, runs only at 200 kHz, and gates each against `calibration.json`'s span through `cal.dac_span_mv()`, which never checks the board. Replace the per-code millivolt band with one fit in codes, at the DAC's 200 kHz with the ADC at 200 kHz and again at RC 86 (a DC level needs no DAC rate, which avoids the heaviest duplex row). Two checks: a regression gate on this board's own slope and offset, and a loose physics bound against the nominal 2/3 whose width is the datasheet's gain error *(check)*. The `calibration.json` slope, 0.67053, is a reference from another board. No DNL | A code set with one level shifted by a stated number of codes leaves a residual above the fit's own noise and fails |
| **E. Rise and settling** | A scope-free rise figure, or a bound. Owns the `settletime.py` logic | Take the ADC request from the timer clock so its RC is prime and refuse to report when fold coverage is below 1.0. Remove the `agrees` verdict and key from `settletime.py` and `m_settling`: the stored 789-938 ns range is a scope reading at what was probably the unconfigured bias *(check)* and is printed with that caveat only. The gate is coverage 1.0, `settletime.py control` reading FLAT and the period-scan margin. The bench cannot time a tail to one code, so a bound is an acceptable result | A board-free unit test: RC 222 against a 225 DAC is refused. **Instrument control:** `settletime.py rise --ibctl 0,0` against the default, then `--ibctl 2,1` to restore and the readback `acr=0000010a`. The rise at 0,0 exceeds the rise at 2,1 by more than max(2 ticks, its in-place spread). The tool does not restore the bias itself and `play.c` applies it to every loop run, so a missing restore taints phases C and D. The 78 MHz factor in `records/acr-rise.jsonl` is printed as a reference and never a target |
| **F. Noise** | The loop's noise on a held code. Owns the protocol | `phase0.py noise-fast` at 90 MHz is the figure, since it alone has a protocol on record (Tracks A and B). Hold the code at mid-scale. The 0.80 codes in `hardware.md` has no protocol on record, is marked *(check)* and is not a target. Cross-rate comparison after decimation is a reported result, not an exit: `docs/noise.md` reads 0.845 codes at 200 ksps and 0.657 at 453 ksps in the same 0-100 kHz band, because there is no anti-alias filter | Synthetic noise of known rms added to the captured series moves the figure by the root-sum-square |
| **G. Thresholds from spreads** | The gate exit of C to F, and the re-derivation of the baseline amplitude values | Run the repeat tooling of phase B at the ends of the ladder as well as at 200 kHz, on the reflash axis for every key that becomes a gate. Each tolerance comes from `repeat.suggest_tolerance`. Needs the code of C to F | A recorded spread per key, rate and axis; a key whose spread exceeds its proposed gate is reported, not gated. The gates: phase C's thresholds, phase D's slope and offset tolerances, phase E's rise bound and phase F's figure |
| **H. Not in the tree** | The pieces nothing covers | See below | Each has a mutation on a deep copy of the captured stream |

### Phase A: the scan

| item | rule |
|---|---|
| Where | A board-free test in the existing tree-scanning tests; `tests/test_doc_references.py` has the normaliser and the floor pattern. It reads `tests/`, `host/`, `tools/` and `gui/` |
| What it parses | Integer constants in code, found by parsing, so prose, docstrings and comments are not scanned. Underscores and floats are normalised |
| Rule one | An integer n is flagged when n = 39e6 // rc for some integer rc >= 1 and n != 45e6 // rc for every rc. 453488 flags and 200000 does not |
| Rule two | The clock constants 39_000_000 and 78_000_000 flag, and so do integer keys of dictionary literals that are rates |
| Exclusions | About a dozen values that are not rates (a seed default, fixture counts and similar), each with a reason; the scan refuses to pass below a floor of files examined |
| Cannot see | Rates that are no divisor at either clock, and period lattices; listed by hand below |

### Phase A: the hand cases

| case | owner | defect |
|---|---|---|
| `tools/settletime.py` | phase E | 202,000 is no rate at either clock; the defect is coprimality of the fold; `rc_dac=195` |
| `tools/metrics.py` | phase A for constants, C for checks | `LADDER_RC`, `m_playback`'s 39 MHz divisor, `m_noise`'s 453,488 fallback |
| `tools/dso_metrics.py` | phase A | rate-keyed presets and a 78 MHz DAC ceiling |
| `tools/noisetool.py` | phase A | the preset table |
| `tools/clock_calib.py` | phase A | `MCK_NOMINAL_HZ` |
| `tests/test_loop_overruns.py` | phase A | its ADC rate is no longer the ceiling; take ADC and DAC rates from `hz_for` |
| `tools/issue5_metric.py` | phase A | its period-21 lattice is tied to the RC 195 trigger; it refuses any other trigger until the 90 MHz period is derived |

## Phase H: what does not exist

Searched in `tests/`, `tools/` and `host/` for SINAD, THD, SFDR, INL and
ENOB: only the building blocks in `host/noise.py` exist. Each new test
takes its own eight runs before it gates anything.

| missing | built from | note |
|---|---|---|
| Coherent-sine SINAD, THD and ENOB | `host/noise.py` spectrum, Welch and line-split | The loop's SINAD includes the DAC's staircase and noise; the figure says so |
| A board test that gates the noise figure | `tools/noise_metrics.py`, phase G's spread | No board noise test exists; `baseline.json` has no noise key |
| Amplitude against tone | `run_loop(tone=...)` at varying `dac_sps`, `window_amplitudes`, whole cycles per window | The loop samples at a fixed phase in each hold, so a run reports the step response at that delay and the amplitude depends on the phase between the two timers; control it and record it. Do not divide out a hold's sinc. A DAC rate above the ADC's raises the USB traffic, so the underrun and overrun gates hold on those rows. `tools/gen_sweep.py` runs one trigger rate and is not the base |
| ADC channel skew, A0 against A1 | the internal generator | The loop measures the DAC1-after-DAC0 lag plus the A1-before-A0 spacing as one figure. `drivers/gen.c` tags slot 0 DAC0 and slot 1 DAC1 in either layout, so `=0N`/`=1N` moves the signal and leaves both delays where they are: it does not separate them. The ADC-only figure is derived, one conversion is about 21.5 ADC clocks, half of the 43 per pair in `baseline.json`, so about 0.96 us at 22.5 MHz *(derived, check)*, and is measured only if the ADC's sequence order can be reversed, a firmware change not planned here. A1 is AD6 and converts before A0, which is AD7. `dso_metrics skew` measures DAC0 against its own DAC1 sync and is not the reference |
| Crosstalk against tone, and the bare A2 pin | `test_the_other_channel_stays_flat`, `tools/bleed_cadence.py`, `tools/wiring_probe.py` | Phase C varies the tone with the rate; this row varies it at a fixed rate. `run_loop` can drive DAC1 through `build_ramp_tagged` |

The `=<n>N` command is bound on all three tracks. `tools/wiring_probe.py`
and `tools/gen_sweep.py` refuse boards that are not Track B, and that
gate is out of date under the tracks' parity rule; lifting it is a
prerequisite for any row that rests on them. The suite's default is
Tracks A and B. Track C is run as an extra gate through `pytest` and gets
no repeat spread, because `phase0.py` does not drive it.

## Not planned here

| item | why it is not a phase |
|---|---|
| The wrap displacement at 90 MHz | The campaign metric is pinned to a period-21 lattice measured against the RC 195 trigger. At RC 225 the comb period follows RC and would fall off the lattice and read small. The period has to be derived, and the metric shown to fire with the refresh bit restored, before any campaign runs *(check)* |
| Runs past 150 s | The soak tools in `tools/` are close-wedge soaks, not long-capture integrity runs. The 150 s capture in `hardware.md` has no record behind it *(check)* |
| Per-code DNL, absolute volts, the DAC's own INL | Need a meter or the bench scope; see `measurement-suite.md` |
| Reversing the ADC's sequence order | A firmware change; it is what would separate ADC skew from the DAC lag |
| Duplex at the top rate on Windows | The only duplex loss figure is a 78 MHz reading from another bench *(check)* |

## Open decisions

| decision | default until answered |
|---|---|
| Who gates and who reports? | Board tests gate; `tools/metrics.py` reports. Both run without a scope |
| Which rates carry the phase C tone checks? | The whole existing ladder, at one threshold from phase G |
