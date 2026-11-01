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
| No tolerance is written before its repeatability is measured: run the metric `--runs 8` on this board and drop the first run of each axis (`run == 0`; `tools/phase0.py` numbers runs from 0), which leaves seven; the spread is the tolerance floor. The drop applies to new records; re-reporting an old one gives a different summary | `measurement-suite.md`, `CLAUDE.md` |
| Measure after about one minute powered. On the reflash axis every run follows a flash, so the tool waits a minute after each flash and discards one throwaway run before the recorded one | `measurement-suite.md` |
| A key that becomes a gate takes its spread across board sessions, because an in-place repeat is one session and bounds only the variation inside it. Report the ratio between the axes, as `--axis both` does | `measurement-suite.md` |
| Every 90 MHz repeat run writes to a fresh `--out`, and `--report` refuses rows whose `provenance.mck_hz` differs; the existing `records/phase0-*.jsonl` rows are all 78 MHz | owner |
| A tolerance comes from `repeat.suggest_tolerance`: a new draw falls outside the range of n draws with probability 2/(n+1), a quarter for seven *(derived)*. A one-sided gate is median minus (or plus) the tolerance, and a quantised key passes `floor=` (one timer tick, 22.2 ns, for a rise) | `host/repeat.py` |
| The amplitude, crosstalk and silent-level values in `tests/baseline.json` are absolute bounds on gain and multiplexer bleed that date from 2026-08-22 at 78 MHz on another board. They keep gating as guards against gross failure; a failure at 90 MHz is a finding and is never widened away. The crosstalk ceiling sits about 90 times above the current reading and the amplitude floor about 2% below it (Track B at 200 kHz: A0 window median 1371.8 against 1340, A1 0.13 codes against 12), so they can show only gross failure and not that 90 MHz moved the analog behaviour; phase G read each against 384 rows and left them as they were (`records/g-*`); the earlier readings were one session *(unrecorded; check)* | owner |
| One threshold per property across the ladder. A rate that misses it is the finding, not a reason for a per-rate threshold | here |
| Break each new or changed check on the thing it guards. Mutate a deep copy of the captured stream, never the stimulus: a feed-rate change trips the underrun check first. A mutation fails the checks of its own family and none outside it | `CLAUDE.md` |
| A change to a test or tool made for time or cost leaves every check as it was: `tools/assertion_fingerprint.py --check` against the commit before shows no changed test | `docs/testing.md` |
| A wait or run length in code the plan touches names a level from `host/pacing.py`; a value that is under test is a named `*_S` constant with its reason, declared in `tests/test_pacing.py` | `docs/testing.md` |
| An unmeasured figure is marked *(check)* | `CLAUDE.md` |
| Promote a figure once, through `--calibrate` and `baseline.measured.json` | `measurement-suite.md` |
| Declare the conditions: board serial, commit, wiring, shield. `bench.json` `wiring` carries the facts, "A2 bare, shield stacked" with the jumpers; no separate note field exists | `host/provenance.py` |
| A null result says what the instrument could have detected | `CLAUDE.md` |

## Phases

Each edit has one owner, named in the phase's goal. A phase's **code
exit** stands alone, against an interim or synthetic threshold. The
**gate exits** were fixed by phase G. Order: A, B, then C to F, then G, then H.

| phase | goal | work on existing code | code exit that can fail |
|---|---|---|---|
| **A. Rates from the clock** | No tool or test holds a rate that was exact only at 78 MHz. Built | `host/clock.py` is the one home of the clock, standard library only because the fake daemon runs without pyserial, and `measure`, `eqtime` and the daemon's rates import it. `tests/test_rates_from_clock.py` is the scan. `Board.require_clock` refuses a board whose identity reports another clock, and `run_loop`, `run_play`, `run_capture` and `run_bench` call it | The scan fails on a stale rate planted in a tool, a test, a host file and a dictionary key, and on a clock constant; a test imports the converted tools at 78 and at 90 MHz and checks each follows the clock; a refusal test fails when the comparison is dropped or the answer is not cached |
| **B. Repeat tooling** | The rules above exist in `tools/phase0.py` and `host/repeat.py`. Built; phases C, D and E each add their own `METRICS` entry, through `phase0.adapt` for a metric of the shape `fn(board, args)` | `repeat.summarise_all` drops `run == 0` of each axis and says how many; `repeat.refuse_mixed_clocks` refuses a record at two clocks, and `phase0` will not append to another clock's record or report a mixed one; after a flash `phase0` waits `repeat.WARMUP_S` and throws one run away; `--rc` repeats a noise metric at one ladder rate; `--track` accepts `c`; the default is `--runs 8`, and `--keep-first` reproduces the old summary | Board-free tests with fakes: a planted first-run outlier and an ordinary-looking first run both lose, rows of two clocks are refused, the reflash path waits and discards, `--rc` reaches the metric; each is broken on purpose. On the board: three runs on each axis at RC 120 recorded 375,000 Hz and the clock on every row, with the reflash rows 83 s apart |
| **C. The ladder gets tone and crosstalk** | The matched loop is judged on signal quality at every rate. Built | Every loop rung of the matched-loop ladders in `tests/test_rates.py` (`_ladder_run`) plays a tone of rate/256 (`ladder_tone`: 32 whole cycles in each 8192-sample window at any RC) for at least ten windows after the settle (`ladder_seconds`). A0 must reach the amplitude floor in those windows, and on a two-channel rung `assert_crosstalk` in `tests/helpers.py` requires A1 to carry no tone; `tests/test_integrity.py` calls the same function. Thresholds are the `amplitude` entries of `tests/baseline.json`, which phase G confirmed against the spreads. `loop_once` and `m_loop` in `tools/metrics.py` run the same matched loop (RC 225, 200 kHz, by default), and `tools/phase0.py` has a scope-free `loop` metric that `tests/test_loop_metric.py` holds without a board | `tests/test_ladder_checks.py` breaks the checks on purpose: five mutations of the real helpers on synthetic captures each fail a test. **Instrument control:** `test_the_crosstalk_check_sees_a_real_coupling_path` in `tests/test_rates.py` pairs A0 with the bare A2 (`=2C`), runs the same check on A2, and requires it to fail; `=1C` is restored in a `finally`. The A2 median is 760.6 codes at RC 200 (`control_a2_rc200` in `tests/baseline.measured.json`, written by `--calibrate`). Board, Track B at 90 MHz: all 15 rungs pass, with a tone median of 1371.8-1375.5 codes at every rung from 57 kHz to 1.02 MHz. `test_rates.py`, `test_ladder_checks.py`, `test_integrity.py` and `test_loop_overruns.py` with `--reflash` give 81 passed on each of Tracks A, B and C, about 3 minutes each |
| **D. DC transfer** | Gain and offset of the loop in one fit. Built | `dc_fit` and `assert_dc_fit` in `tests/helpers.py` fit A0 codes against DAC code. `test_dc_transfer_is_one_line` in `tests/test_integrity.py` runs the fit on the codes 512, 1024, 2048, 3072 and 3583, with the DAC at 200 kHz and the ADC at 200 kHz (RC 225) and again at RC 86 (a DC level needs no matched DAC rate, so the load is lighter than the `TWO_CH` RC 86 row the ladder already runs). Three checks, with thresholds in the `dc_transfer` section of `tests/baseline.json`: a regression gate on this board's slope and offset (0.6703 and 674.4 codes, tolerance 0.001 and 2.7); a loose physics bound on the slope against the nominal 2/3 (5%, provisional *(check)* pending the datasheet's gain error; the measured slope sits 0.54% off); and the residual, worst level at most 4 codes. `test_dc_levels_are_monotonic` is kept, because a positive slope does not say the levels are in order. No DNL. The `calibration.json` slope, 0.67053, is a reference from another board. This board measures 0.67008-0.67044 across Tracks A, B and C, both ADC rates and two sessions, with offset 674.0-674.7 codes, residual rms 0.14-0.42 and worst 0.56. A whole run can sit 2-3 codes off at any one level, in either direction: the whole 16384-sample settled window shifts by a constant, and its first and last quarters agree to 0.1 code. Measured, 4 of 60 level readings in forward sweeps and 0 of 60 reversed (p about 0.06, so no order effect is claimed), the largest -3.2 codes. The mechanism is not established; an analog state held for a run is a candidate and untested. The tolerances were widened twice on evidence, once for the spread across sessions and once for this level offset, so the gate passes one level 3.2 codes off at every level and fails 8 codes at every level. Phase G left them unchanged, and a failing DC sweep is confirmed by one fresh sweep (`confirm_dc_fit`) before the test fails | `tests/test_dc_fit.py` holds both edges with the recorded values; tightening the residual limit fails 6 of its tests and loosening the slope tolerance fails 2. **Board, measured:** the DC tests pass on Tracks A, B and C (3 passed each, about 46 s), and four further Track B repeats were all green |
| **E. Rise and settling** | A scope-free rise figure, with its spread. Owns the `settletime.py` logic. Built | `coprime_adc_rc(period_ticks, want_rc)` in `tools/settletime.py` picks the nearest ADC RC (at least 86) coprime with the waveform period, 2 x points x the DAC RC, because the fold reaches every phase only then; the tool prints the DAC RC, the period and the ADC request. A DAC request of 200 kHz is RC 225, and at 8 points the chosen ADC RC is 221 (203,619 Hz); a fixed 202 kHz request gives RC 222, which shares a factor of 3 with 225. `require_full_coverage` refuses any figure, for rise, settle and control, when fold coverage is below 1.0. The tool returns no verdict against the scope: the stored 789-938 ns range is printed as reference only, probably taken at an unconfigured bias *(check)*. The gate is coverage 1.0, `settletime.py control` reading FLAT and the period-scan margin. The bench cannot time a tail to one code, so the result is a figure with its spread | `tests/test_settletime_guard.py` (6 tests, no board) holds it: RC 222 against 225 is refused, a partial fold gives no rise, and the result has no verdict key; each of four mutations fails a test. **Instrument control:** `settletime.py rise --ibctl 0,0` against the default, then `--ibctl 2,1` to restore and the readback `acr=0000010a`; the rise at 0,0 must exceed the rise at 2,1 by more than the larger of two ticks (44.4 ns) and the in-place sd. The tool does not restore the bias itself, and `play.c` applies it to every loop run, so a missing restore taints every later loop run. **Board, Track B at 90 MHz:** `control` reads FLAT (held level 2047.49 codes, 1.008 codes rms across phase, span 10.98). Default-bias rise over 6 runs, run 0 dropped by index: 12, 12, 12, 12, 14 ticks kept (tick 22.2 ns), mean 12.4 ticks (about 275 ns), sd 0.89 ticks (about 19.8 ns), coverage 100% (225 samples per position) in all six, period-scan margin 32.9x and 32.7x where printed. `--ibctl 0,0` rises 38 ticks (844 ns) on all three runs with `DACC_ACR` 00000000; restored at `--ibctl 2,1` it reads 14 ticks and `acr=0000010a`, confirmed on the console `?`. The difference is 25.6 ticks (about 569 ns), 13 times the threshold. `records/acr-rise.jsonl` holds the reference only, never a target: windows-desk at 78 MHz, 38 ticks (974.36 ns) at 00000000 and 14 ticks (358.97 ns) at 0000010a, a ratio of 2.714 against 2.71 here (844/311) with the same tick counts |
| **F. Noise** | The loop's noise on a held code. Owns the protocol. Built | `tools/phase0.py noise-fast` at the 90 MHz default is the figure, since it alone has a protocol on record (Tracks A and B). It holds code 2048 at RC 86 (523,255 Hz, bin 127.748 Hz) and reads a 4096-sample window for 2.0 s per run; the summary drops run 0 by index. The 0.80 codes in `hardware.md` has no protocol on record, is marked *(check)* and is not a target. The cross-rate comparison after decimation stays a reported result, not an exit: `docs/noise.md` reads 0.845 codes at 200 ksps and 0.657 at 453 ksps in the same 0-100 kHz band, because there is no anti-alias filter, and this protocol's figure is at RC 86 only. `add_known_noise` and `rss_response` in `tools/noise_metrics.py` add noise of known rms to a captured series and give the root-sum-square it should produce | `tests/test_noise_rss.py` (7 tests, no board) holds it: 0.5, 1.0 and 2.0 codes of known noise on a synthetic capture move `rms_lsb` to the root-sum-square within 5 standard errors (a chosen multiplier, not a measured figure), and a tone leaves the floor unchanged while noise moves it by the root-sum-square. Four mutations (noise at 2x, rms taken about 0, floor set to the total power, halved divisor) each fail tests. An n against n-1 divisor change moves the figure by 5e-6 at about 100,000 samples and cannot be detected, so it is not claimed. **Board, 90 MHz, 8 runs per track, run 0 dropped, n=7:** Track A rms 0.8015 codes (0.46% spread), 639.9 uV, noise-free bits 9.597, floor rms 0.7975 codes. Track B rms 0.7980 codes (0.67% spread), 637.1 uV, noise-free bits 9.603, floor rms 0.7933. Mean code 2047.44 and 2047.43, span 9 codes, no spectral line (`n_lines` 0). The tracks differ by 0.44%, within the 0.67% spread. Track C and the reflash axis are measured for noise in phases G and H. Records: `records/phase0-noise-fast-90mhz-a.jsonl` and `records/phase0-noise-fast-90mhz-b.jsonl`, build 20c26fc, clock 90,000,000 on every row |
| **G. Thresholds from spreads** | The gate exit of C to F, and the re-derivation of the baseline amplitude values. Built; no gate in `tests/baseline.json` changed | `repeat.MIN_KEPT` is 7. `phase0.py --report` refuses a key with fewer than seven kept runs (`thin_keys`) or a record at mixed clocks, and prints a proposed gate per key; `--gates` with a JSON file of gates reports a key whose spread exceeds its gate (`over_gate`) and never gates. `phase0.py` takes a comma list of metrics (`loop,dc-fit,rise,noise-fast`); one reflash cycle (flash, 60 s warm-up, throwaway run) serves every metric and each writes `<out>-<metric>.jsonl`. `dc-fit` is `metrics.dc_fit_once` and `rise` is `settletime.rise_once`. `confirm_dc_fit` in `tests/helpers.py` repeats a failing DC sweep once, and the test fails only if both fail; the retry is recorded in the calibration | `tests/test_dc_fit.py` holds that a persistent 8-code shift fails both sweeps at every level; four mutations failed tests, and a board mutation of 8 codes failed on Track B. **Board, linux-x1, 90 MHz, build d7ece10:** 40 records `records/g-<track>-<rc>-<axis>-<metric>.jsonl`, 384 rows, all at clock 90,000,000. In place: 8 runs, 7 kept, Tracks A, B and C at RC 225 (200 kHz) and RC 86. Reflash: 3 chunks of 4 runs, run 0 of each chunk dropped by index, 9 kept, Tracks C, A and B at RC 225 and Track B at RC 86. Rise ignores `--rc`, so its RC 86 sets repeat one measurement. **What the spreads showed.** Tone median 1371.9-1372.1 on every track and rate (all rows 1369.2-1382.9), so the 1340 floor holds with at least 29 codes margin; window fraction is 1.0 in all 78 rows, so the data cannot say whether 0.9 is tight. Crosstalk medians 0.096-0.31 against the ceiling 12, about 40x below; it is left unchanged because it can only miss a fault and not flake, other benches may couple differently, and what it is meant to catch is not established. DC slope and offset references hold (medians 0.67031-0.67044 and 674.19-674.54), and the worst residual row is 3.09 codes against the limit 4. Noise rms is 0.79-0.88 codes by set, 3 to 9.5 times wider on the reflash axis than in place at RC 225 (1.26x at RC 86 on Track B); the noise gate in phase H bounds it. Rise is 12 ticks (266.7 ns) on every set with a spread of one quantum (2 ticks) on both axes. **One finding.** 2 of 78 kept rows (Track B in place at RC 225, Track C reflash at RC 225) had one DC level (512) about 6 codes off for the whole run; the mechanism is not established. Widening the slope and offset tolerances enough to pass them would stop the gate catching an 8-code shift at an end level, so the gate values stand and the confirm step handles those rows. No gate changed because the data supported each as it stood |
| **H. Board gates for what phases C to G measured** | The noise figure, SINAD, amplitude and crosstalk against tone, and the loop's A1-after-A0 lag, each gated on the board. Built | `tests/test_noise_board.py`, `tests/test_sinad_board.py`, `tests/test_tone_sweep_board.py` and `tests/test_loop_skew_board.py`, with `noise.sinad`, `noise_metrics.sinad_once`, `metrics.tone_sweep_once` and `metrics.loop_skew_once` behind them; see below | Each gate has a no-board test of its logic and a board mutation that failed both measurements; the four board gates (13 tests) pass on Tracks A, B and C |

### Phase A: the scan

| item | rule |
|---|---|
| Where | `tests/test_rates_from_clock.py`, modelled on `tests/test_pacing.py`: `ast` parsing, a `(file, value)` allowlist with a reason each, a floor of files examined, and a planted case of every kind that must be found. The timing scan reads `host/`, `gui/` and `tests/` only; this one also reads `tools/` |
| What it parses | Integer constants in code, found by parsing, so prose, docstrings and comments are not scanned. Underscores and floats are normalised |
| Rule one | An integer n is flagged when n = 39e6 // rc for some integer rc >= 1 and n != 45e6 // rc for every rc. 453488 flags and 200000 does not |
| Rule two | The clock constants 39_000_000 and 78_000_000 flag. A dictionary literal any of whose keys rule one flags is reported whole, so its other keys are reviewed with it |
| Exclusions | `EXCLUDED` in the scan, each a file and a value with its reason: counts and seeds that are not rates, synthetic signals whose rate is arbitrary, and the clocks that analysis tools and parser tests name on purpose. The scan fails when an exclusion matches nothing and refuses to pass below a floor of files examined |
| Cannot see | Rates that are no divisor at either clock, and period lattices; listed by hand below |

### Phase A: the hand cases

Rates a literal scan cannot see, and what became of each.

| case | state |
|---|---|
| `tools/settletime.py` | Derived from the timer clock; the ADC request is chosen coprime with the waveform period (phase E) |
| `tools/metrics.py`, `tools/noisetool.py`, `tools/dso_metrics.py`, `tools/clock_calib.py` and the issue-48, issue-24 and soak tools | Derived from `hz_for` and the host's clock |
| `tests/test_loop_overruns.py` and four more tests | Derived from `hz_for`; the overrun guard runs at the real RC 86 ceiling |
| `tools/issue5_metric.py` | Refuses rows recorded at another clock (`unfit_clocks`); its period-21 lattice is the RC 195 comb at MCK 78 and the 90 MHz period has not been derived. Rows with no recorded clock predate the field and are 78 MHz |
| `tools/issue5_alias_sweep.py` | Its registered trigger set is in Hz at MCK 78 and is an exclusion; redefining it is the 90 MHz campaign, not planned |

## Phase H: the board gates

Each item is a metric that `phase0.py` records and a board test that
gates it against a `tests/baseline.json` key. A failing measurement is
confirmed by one fresh measurement (`confirm_measurement` in
`tests/helpers.py`), and the test fails only if both fail. Every bound
is provisional *(check)* until more sessions and benches have measured.

| item | built from | note |
|---|---|---|
| Noise gate | `tests/test_noise_board.py`, `tools/noise_metrics.py`, baseline key `noise` | Held code 2048 at RC 225 and RC 86. The rms ceiling is 1.04 codes, the largest recorded 0.8976 times 1.15; the line power fraction ceiling is 0.05; the floor is 0.9 of the 0.2887 codes quantisation floor, which catches a flat or stale capture |
| Coherent-sine SINAD, THD and ENOB | `noise.sinad` in `host/noise.py`, `noise_metrics.sinad_once`, metric `sinad`, `tests/test_sinad.py` (8, no board), `tests/test_sinad_board.py`, baseline key `sinad` | `noise.sinad` takes coherent windows only and refuses a non-integer cycle count. The loop reads SINAD about 61 dB (median 61.02 over 69 rows), ENOB about 9.84 and THD about -77.3 dB, and the figure includes the DAC's staircase and the converter's noise. Bounds: `sinad_db_min` 59.85, `enob_min` 9.65, `thd_db_max` -75.55, `noise_floor_rms_lsb_max` 0.97, signal band 966.11-974.6. The signal band comes from all 69 kept rows; the other keys exclude rows more than 4 MADs from their set. One spike row reads 44.2 dB with a noise floor of 5.97 codes; its cause is not established |
| Amplitude and crosstalk against tone | `metrics.tone_sweep_once`, metric `tone-sweep`, `tests/test_tone_sweep.py`, `tests/test_tone_sweep_board.py`, `tests/test_tone_sweep_gate.py`, baseline key `tone_sweep` | N = 256, 64, 16 and 8 samples per cycle at 200 kHz, which is 781.25 Hz to 25 kHz and 32 to 1024 cycles per 8192-sample window. Amplitude medians are 1371.5-1372.1 at every N: no hold roll-off appears, because the loop samples at a fixed phase in each hold. Crosstalk medians are about 0.13 codes with spikes (`xtalk_n8` 2.5-4.4 codes on all three tracks, 4 of 23 Track A rows), so its bound is the largest of all rows times 1.15. `amp_min_n8` is below the 1340 ladder floor. Read the per-N keys in `tests/baseline.json` |
| Skew, A1 after A0 | `metrics.loop_skew_once`, metric `loop-skew` (`skew` stays the scope metric), `tests/test_loop_skew.py`, `tests/test_loop_skew_board.py`, `tests/test_loop_skew_gate.py`, baseline key `loop_skew` | Drives one sine on DAC0 and DAC1 (`build_sine_both`) and reads the phase difference of the fundamental. The figure is a whole multiple k of the trigger period 1/fs, k = 1 in 52 of 69 rows and k = 2 in 17, on every track and at both rates, because a held staircase hides sub-hold shifts. So it checks that DAC1 is written one or two triggers after DAC0 and does not separate the ADC skew; the roughly 0.96 us A1-before-A0 spacing needs the reversed ADC sequence order, not planned. Why k varies between runs and across a reflash is not established. Gate: k in {1, 2}, deviation from k/fs at most 25 ns (the largest among the 63 rows outside the six that exceed it is 17.99 ns), phase spread across windows at most 0.00248 deg |
| Crosstalk against tone, and the bare A2 pin | `test_the_other_channel_stays_flat`, `tools/bleed_cadence.py`, `tools/wiring_probe.py` | Crosstalk against tone is the A1 key of the tone sweep above. The bare A2 pin has no gate |

**Evidence.** 27 records `records/h-<track>-<rc>-<ip|rf>-<metric>.jsonl`,
build bf8af90, clock 90,000,000, linux-x1. In place: 8 runs, 7 kept, on
Tracks A, B and C at RC 225 and RC 86. Reflash: 3 chunks of 4 runs, run 0
of each chunk dropped by index, 9 kept, at RC 225 on A, B and C. The four
board gates (13 tests) pass on Tracks A, B and C, 5 further Track B
repeats passed, and each gate's board mutation failed both measurements.

The `=<n>N` command is bound on all three tracks. `tools/wiring_probe.py`
and `tools/gen_sweep.py` refuse boards that are not Track B, and that
gate is out of date under the tracks' parity rule; lifting it is a
prerequisite for any row that rests on them. Track C runs through
`phase0.py --track c` and the board tests run on Tracks A, B and C.

## Not planned here

| item | why it is not a phase |
|---|---|
| The wrap displacement at 90 MHz | The campaign metric is pinned to a period-21 lattice measured against the RC 195 trigger. At RC 225 the comb period follows RC and would fall off the lattice and read small. The period has to be derived, and the metric shown to fire with the refresh bit restored, before any campaign runs *(check)* |
| Runs past 150 s | The soak tools in `tools/` are close-wedge soaks, not long-capture integrity runs. The 150 s capture in `hardware.md` has no record behind it *(check)* |
| Per-code DNL, absolute volts, the DAC's own INL | Need a meter or the bench scope; see `measurement-suite.md` |
| Reversing the ADC's sequence order | A firmware change; it is what would separate ADC skew from the DAC lag |
| Duplex at the top rate on Windows | The only duplex loss figure is a 78 MHz reading from another bench *(check)* |

## What this costs in time

The suite's own cost is measured on this bench: a full Track B pass is 483 s,
and a board run through `run_loop` is its window plus about 1.15 s of fixed
overhead (`--pacing-report` prints the stages). Everything below is an estimate
from those figures *(check)* until a phase is run and timed; the reflash axis row is measured.

| phase | what it runs | estimated cost on this bench |
|---|---|---|
| C | The existing ladders, with checks added to runs they already make | no extra runs |
| D | One fit over five codes, at two rates | about 46 s for the three DC tests, measured |
| B, G in place | `--runs 8` of a metric at each ladder end | about 3 s a run, under a minute per rate |
| G across sessions | The reflash axis: a flash, the one-minute warm-up, a throwaway run and the recorded one, in chunks of four runs | 83 s a run measured for one metric; a 4-run chunk of four metrics took about 8 minutes, and a reflash set was 3 chunks |
| H | 15 tasks: in place 8 runs, reflash 3 chunks of 4 | measured: about 7-8 minutes per 4-run reflash chunk of three metrics |

The reflash axis dominates. A key shared by several metrics costs its runs
once, because one run returns every key.

Several metrics share one cycle: `phase0.py loop,dc-fit,rise,noise-fast
--axis reflash` pays the flash, the warm-up and the throwaway run once per
run index and every listed metric records one row from the board it leaves,
so four metrics cost 83 s a run and not four times that. Each metric writes
its own record, `records/phase0-<metric>.jsonl`, or `<--out>-<metric>.jsonl`
when `--out` is given with several; a failing metric records its error row
and the others still run.

## Open decisions

| decision | default until answered |
|---|---|
| Who gates and who reports? | Board tests gate; `tools/metrics.py` reports. Both run without a scope |
| Which rates carry the phase C tone checks? | The whole existing ladder, at the baseline amplitude thresholds, which phase G left as they were |
