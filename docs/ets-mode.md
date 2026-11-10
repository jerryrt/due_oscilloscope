# ETS mode: capturing a repeating PRBS and drawing its eye

A repeating pattern, sampled once per microsecond, is folded onto its own
period so that the samples of many repeats fill in one detailed picture.
`docs/ets.md` holds the sampling model and its limits; this document is how to
run it, what it has been shown to do, and what it cannot do. The code is
`host/etsplan.py`, `host/etsperiod.py` and `host/eqtime.py` with the tools in
the table below, and the measurements are indexed in `records/README.md`.

Figures marked *(check)* are unmeasured: derived, or read from another
document.

## How to run it

| | DAC RC | ADC RC | why |
|---|---|---|---|
| **Two boards**, each with its own crystal | odd, **29** (1.55 Msym/s) | even, **46** (44, 48 and 50 also work at DAC RC 29) | an even ADC RC leaves nothing for the ADC start snap to correct; an odd DAC RC keeps the pattern period coprime with every even ADC RC |
| **One board**, one clock | **28** (the playback floor, 1.607 Msym/s) | odd and coprime with the period, **45** | the fold has to reach every tick; the odd-sample offset is corrected on the host |

`ets_cross.py plan` prints the pair and says why; `both`, `sweep` and `capture`
refuse a pair the planner rejects unless `--force` is given.

```sh
tools/ets_cross.py plan                      # the pair, and what it costs
tools/ets_cross.py both --seconds 16 --eye-out eye.json --label "DUT2 1.55M"
tools/ets_eye_page.py eye.json --out eye.html   # one or two eyes, one page
```

`both` plays a 1 V PRBS7 from the host on one board (`--play-dut`), captures A0
on the other (`--cap-dut`), finds the clock ratio from the samples, folds, and
writes the eye. Both boards are pinned with `DUE_DUT`. Run it twice and drop the
first run. A capture counts only if `model_adequate` is true and
`lattice_gcd` is at most 2; the row says so.

## What it has been shown to do

| claim | result | record |
|---|---|---|
| The DAC emits a 1 V PRBS7 at its top rate and it repeats | every rate from 200 kHz to RC 28 (1,607,142 symbols/s) folds to the pattern, eye 99.8-99.9% open, residual 1.3 codes, the converter's noise | `ets-phase0-montreal5-b.jsonl` |
| The host can feed it while capturing | 0 underruns, every byte played, 3.2 MB/s out and 2 MB/s in, on Linux | same |
| The fold agrees with a scope | rise 137-139 ns against 134-135 ns on the Rigol, swing 998 against 984-991 mV | `ets-phase0-montreal5-b-scope.jsonl` |
| The clock ratio of a second board is found from the samples | -2.52 to -2.33 ppm on `linux-x1`'s pair; on `montreal5`'s capture with an offset emulated, +-40 to 250 ppm comes back to 0.0001 ppm | `ets-cross-linux-x1.jsonl`; `tests/test_etsperiod.py` |
| An independent clock removes the tick grid | 100% of the 2.2 ns bins hold samples against 10% on one clock | `ets-cross-linux-x1.jsonl`, `ets-eye-linux-x1.json` |
| The ADC start snaps to its own clock | odd and even samples put an edge exactly 22.2 ns (one tick) apart, rising and falling; an even ADC RC shows 0.0 ns | `ets-cross-linux-x1.jsonl` |
| An odd DAC RC with an even ADC RC is well conditioned | block scatter 0.20-0.24 ticks at ADC RC 44, 46 and 48, adequately modelled, time axis known to 0.12-0.18 ns, rise 136.3-136.5 ns, fall 127.5-127.7 ns | `ets-odd-linux-x1.jsonl` |
| What the ADC adds to an edge | a floor of 42.4 ns on rise and 45.4 ns on fall, an upper bound that includes the DAC's own response | `ets-floor-linux-x1.jsonl` |

## Why the pairing rule

The pattern repeats every `P = 127 * rc_dac` ticks, and the ADC samples at ticks
`k * rc_adc`.

**Even ADC RC.** The ADC clock is 22.5 MHz and the timers run at 45 MHz, so an
ADC clock edge comes every 2 ticks and the start snaps to the next one. With an
odd RC the triggers alternate between the two phases, and the odd samples are
taken one tick (22.2 ns) earlier than the even ones; pooled, they blur every edge
by that tick. With an even RC every trigger lands at the same phase.

**Coprime with the period.** A sample at tick `k * rc_adc` falls at position
`(k * rc_adc) mod P`, so with `g = gcd(rc_adc, P)` the whole-tick positions
reached are only multiples of `g`. An edge is about 6 ticks wide, so at `g = 4` a
short block sees one or two points across it and its position is poorly known.
On perfect synthetic data the block scatter is 0.19-0.26 ticks at `g` of 1 and 2
and 1.1 at 4, with neighbouring residuals correlated at 0.55.
`etsperiod.MAX_LATTICE_GCD` holds the limit at 2.

**Odd DAC RC.** 127 is odd, so `P` has the parity of `rc_dac`. At RC 28, `P` is
3,556 = 4 * 889: every even ADC RC shares at least a factor of 2 with it, and RC
44 and 48 share 4. At RC 29, `P` is 3,683 = 29 * 127: every even ADC RC from 44 to
50 is coprime with it. The cost is a symbol rate of 1.55 Msym/s instead of
1.607.

**On one clock** coprimality is a hard requirement, because the fold would
otherwise miss ticks, and with an even period it forces an odd ADC RC. On two
boards it only conditions the block tracker; the clock drift fills the positions
over a long capture anyway.

## How a capture is read

* **The pattern is known, so the unknown is the clock ratio.** Short blocks of
  samples are matched against the pattern's ideal waveform to find where in the
  pattern each sits, and that phase is tracked over the capture
  (`etsperiod.track_clock_ratio`). A search that scores whole-capture folds on
  candidate periods does not work for a known pattern: bins as wide as a symbol
  cannot tell a period 8 ticks out by the end of the window from the right one.
* **The phase is fitted as a smooth curve, not a line.** Two crystals do not hold
  a ratio: it moved 0.12 ppm over four of `linux-x1`'s runs, half a tick of phase
  curvature over 16 s, which a line leaves as blur on every edge. The degree
  (1 to 6) is chosen by BIC and isolated bad blocks are dropped and counted. On
  `linux-x1`'s captures the fitted wander is 0 to 0.21 ticks, so a line sufficed
  there; the model is the safeguard for a pair that wanders more.
* **The fit is judged by the structure of its residuals,** not their size: a
  smooth curve through a phase jump leaves a run of one sign. A capture with
  neighbouring residuals correlated above 0.35, more than 5% outliers, or a
  common factor above 2 is `model_adequate: false` and no fold on it should be
  trusted.
* **The block estimator reads the correlation peak from a parabola.** Samples
  sit on whole ticks, so the correlation between whole-tick shifts is piecewise
  linear, and a triangle formula on its peak leaves a sawtooth of about 0.4
  ticks. A parabola through the top five points gives 0.19-0.31 ticks on perfect
  data against 0.56-0.64. The fold was never affected: a sawtooth averages out of
  a fitted line.
* **`time_axis_sigma_ns`** is the fitted curve's own standard error: how well
  the time axis of the fold is known, whatever the bin width (0.12-0.18 ns on
  `linux-x1`'s pair). It is a statistical figure and excludes anything the model
  cannot see.
* **The capture starts before the feed.** The DAC sits at its idle level for 2 to
  12 ms first; those blocks are skipped (`MIN_SCORE`) or trimmed (`steady_range`)
  and the row records it.
* **Rise and fall are read on isolated transitions,** where both neighbours have
  settled. The fold reads a synthetic single-pole edge about 5% low.
* **Each check was broken on purpose before it was trusted:** a fold on the wrong
  clock relation must collapse the eye (1.4% open), a 20 ppm period error must
  too, a sign flip, a missing wander term and a missing adequacy rule must each
  fail a test, and a shared clock must leave the fine bins empty.

## The ADC's share of an edge

A DAC edge is slew limited and shrinks with the step; what the ADC's
track-and-hold and the DAC's small-signal response add does not. Rise squared
against step squared is a line whose intercept is that floor
(`ets_cross.py sweep`, `fit_floor`). On `linux-x1` (DAC RC 28 into ADC RC 46):

| swing | rise, 10-90% | fall, 10-90% |
|---|---|---|
| 999 mV | 136.75 ns | 127.61 ns |
| 699 mV | 98.89 ns | 91.59 ns |
| 499 mV | 76.59 ns | 73.24 ns |
| 350 mV | 62.65 ns | 61.89 ns |
| 250 mV | 54.42 ns | 55.52 ns |
| 175 mV | 48.60 ns | 52.02 ns |
| **floor** | **42.4 ns** (rms 0.8 ns) | **45.4 ns** (rms 1.7 ns) |

The floor is an upper bound on what the ADC adds, since it holds the DAC's own
response too, and with the fold's 5% low reading it is 42 to 48 ns. It sits below
the 50-54 ns `docs/ets.md` reads off the datasheet's tracking-time formula. So
the ADC input passes at least about 8 MHz (0.35 / 45 ns); how much more is not
known, because the DAC's fastest edge is about 49 ns.

## What it cannot do

* **Time placement is not bandwidth.** A time axis known to 0.12 ns tells where
  each sample belongs; it does not let a signal through. The edge in the eye is
  the one the DAC and ADC produce, about 137 ns at 1 V and 49 ns at 175 mV, and
  finer bins draw it more cleanly without adding detail. Nothing above roughly
  8 MHz has been verified, and a 10 GHz waveform (100 ps) is beyond both the
  front end and the 0.12 ns placement.
* **Only a signal that repeats exactly, with a known pattern.** Random data and
  single events are not covered, and a repeating signal of unknown pattern needs a
  way to learn its template, which does not exist here.
* **Only edge shape and level noise.** The fold assumes exact repetition, so it
  cannot show random jitter that varies cycle to cycle.
* **Range and speed.** The ADC range is 0 to 3.3 V, so anything else needs the
  analog front end. A picture takes 16 s of capture and about a minute of host
  computing.
* **Vertical thickness** is the converter's noise, about 1.3 codes.

## Not established

* Tracks A and C, and hosts other than Linux. Duplex USB loss was seen on Windows
  at 1.7 MB/s combined before the playback fixes.
* More than one pair of boards, and wander over minutes or with temperature.
* How the 42 ns floor splits between the DAC and the ADC. The `linux-x1` bench has
  no scope, and the Rigol's probe on `montreal5` reads x1 in software with the
  physical switch unknown, which would bound its own rise near 58 ns.
* A signal from an outside device: every capture so far is a Due's own DAC.
* The ADC's aperture jitter, and its input bandwidth above the floor.

## Tools

| tool | what it does |
|---|---|
| `host/etsplan.py` | the pairing rule: `plan` picks the pair, `check_pair` says what is wrong with one |
| `host/etsperiod.py` | the block tracker, the phase model and its adequacy rule, the folds |
| `host/eqtime.py` | the integer-tick fold and its helpers, for the same-board path |
| `tools/ets_phase0.py` | same board: a PRBS7 through the loop, folded, optionally against the Rigol (`loop`, `both`, `selftest`) |
| `tools/ets_cross.py` | two boards: `plan`, `both`, `play`, `capture`, `analyze`, `resolution`, `sweep`, `eye` |
| `tools/ets_eye_page.py` | one or two eye files to a standalone page, with provenance |
| `tests/test_etsplan.py`, `tests/test_etsperiod.py`, `tests/test_ets_eye_page.py` | board-free; each rule fails a test when broken |

## Phases

| phase | what | status |
|---|---|---|
| **0. Validate** on one board | `ets_phase0.py` against the Rigol | done, see above. The pass thresholds (fold and scope within 5%, duplex loses nothing) were chosen after the data was seen |
| **1. Host library** | planner, tracker, folds, eye builder, tests | done |
| **2. External clock** | second board's DAC into the capturing board's A0 | done on `linux-x1` |
| **3. Track B mode** | the daemon runs an ETS capture on one channel until stopped, with a progressive fold; the front end shows the folded waveform and the eye. The planner and its checks belong here | next |
| **4. Other hosts** | `ets_phase0.py loop` on Windows and macOS, for the duplex load | not started |
| **5. Device PRBS** | only if phase 4 shows loss | not started |
| **6. Tracks A and C** | the same fold; should need no host change | not started |
| **7. AFE wide path** | the wide path of the AFE requirement draft, against the same signals | when the AFE exists |

## A device-held pattern: the RAM

If a host cannot feed the pattern, it can live on the device and play from RAM
with no USB in the path, as the generator's table does.

| item | figure |
|---|---|
| Bank 0 (64 KiB) after `.data` and `.bss` | 8,712 B free, stack and heap included *(Track B map; where the stack sits is unchecked)* |
| Bank 1 (32 KiB) | 16,384 B free; the capture ring takes the other 16,384 B *(check that nothing else is placed there)* |
| Today's generator table | 512 entries, 1,024 B |
| A pattern at 1 sample per symbol, 2 B each | PRBS7 254 B, PRBS9 1,022 B, PRBS10 2,046 B, PRBS11 4,094 B, PRBS13 16,382 B |

PRBS7 to PRBS10 fit in bank 0 with room to spare. PRBS11 leaves about 4.6 KB for
stack and heap, so it belongs in bank 1, whose use by the DMA masters is
unchecked.

What it needs from the firmware: a table whose length is the pattern's period
(today the wrap is fixed at the table length and points must divide 256, so a
127-symbol period does not fit), and a PRBS shape built from an LFSR when the
generator is configured, which is setup work and not on the sample path. That is
a new shape value in the shared wire contract and the same console surface on all
three tracks.

## Conditions on the signal

The DAC's window is about 0.55 to 2.75 V, which holds a 1 V swing. With probes
fitted the line at a quarter of the sample rate appears on Track C and is absent
on Tracks A and B, so Track B is the clean start. A playback ring that is
under-run, or a capture that drops a frame, shifts every later sample's phase;
`eqtime.check_contiguous` refuses such a run.
