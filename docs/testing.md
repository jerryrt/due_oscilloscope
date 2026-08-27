# Test Suite: design and implementation guide

**Status: implemented, and since extended past the hardware.** The
original four files still talk to a real board for everything about
signals, timing and transport. Three more do not, deliberately:
`test_daemon_protocol.py`, `test_daemon_api.py` and `test_jitter.py`
judge framing, ownership, refusals, backpressure and recording, which
are not properties of the Due, and `test_gui.py` drives the front end
headlessly in the GUI venv. They cost seconds and run first, so a
protocol regression fails before anything has been flashed.

That is not a retreat from the no-simulator rule. The synthetic device
produces frames in the device's own format - same header, same CRC,
same sequence numbers - and `measure.parse_frames` is what checks they
arrived intact, so the real parser is exercised on synthetic bytes
rather than a second definition of the format being written.

`host/measure.py` plus `tests/`. Run it with

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest --track=b -q
```

pytest is not stdlib, so the suite needs the venv. Everything under
`host/` stays stdlib only: those tools have to run from the system
interpreter during bring-up.

This document remains the design. Read `docs/HANDOFF.md` first for the
board, ports and build environment.

### What building it found

Four defects, none of which the manual runs had shown, all four now
fixed. They are written up in `docs/status.md`; briefly: the native port
took 51 s to open because `SET_LINE_CODING` was answered before its
data stage, the console silently dropped commands sent while it was
printing, the frame header declared the requested rate rather than the
one the hardware makes, and host-fed playback lost samples that no
counter on either side saw.

The fourth is why the suite exists. `seq_gaps=0 crc_bad=0 under=0`
was true for every one of those runs, and the DAC was still skipping
forward a few times a second. It took a ramp - a waveform where every
sample encodes its own position - to turn "the output jumped" into "313
bytes never arrived", and the fact that every loss was smaller than one
ring slot to name the cause: two reads of a DMA status register where
there should have been one. The instrument that found it,
`measure.build_ramp` / `ramp_discontinuities`, is worth reaching for
again the next time a counter says everything is fine.

It also left the suite able to say *which side* lost data. With the
device's byte accounting exact, an arbitrary-sized forward jump is the
device and a whole 128-byte chunk is macOS's output path, so
`test_host_fed_ramp_loses_no_samples` fails outright for the first and
reports an xfail naming the host for the second.

### One rule added while building it

**Every rate is `hz_for(RC)` for an integer RC, never a round decimal
number.** The trigger is a TC compare against RC and the DAC update is
the same timer on another channel, so `39 MHz / RC` is the entire set of
rates the hardware has; asking for anything between two of them just
rounds down. The ladders are therefore RC and the Hz are derived, and
`test_every_ladder_rate_is_a_real_divider_value` checks that they
round-trip.

Two decisions are settled and are not open for re-litigation:

1. **Refactor first.** The measurement logic moves into a library; the
   three CLI scripts become thin wrappers over it. Tests import the
   library. They do not shell out and parse stdout.
2. **All four test files** get built: rates, integrity, channels,
   transport.

## Why a suite at all

Both tracks now run the full instrument loop and the numbers are good,
but every regression so far has been caught by a human noticing an odd
figure in a manual run. Several were caught late, and two were caught
only because a *different* measurement disagreed. The counters alone
have lied more than once: a clean `seq_gaps=0 crc_bad=0 under=0` run has
coexisted with a badly degraded signal, and a whole-run tone average has
reported a collapse that was not happening.

So the suite exists to make the oracles automatic, and to make the two
tracks check each other without a person holding both sets of numbers in
their head.

## 0. Ground rules

Each of these cost real time to learn. They are requirements on the
suite, not style preferences.

| Rule | Why |
|---|---|
| Judge tone purity **per window**, never whole-run | At 453,488 sps the whole-run Goertzel reads 232 against a theoretical 1370.5 while nearly every window reads above 1360. A phase discontinuity cancels the average. |
| Prove **freshness** on every measurement | Stale kernel-buffered frames from a previous run once manufactured a "frozen DAC" that cost a full session. |
| Express rates as **RC**, not Hz | Rates that do not divide 39 MHz truncate in RC and shift every derived frequency. |
| Never scale a measured ceiling arithmetically | Halving the two-channel RC 86 gives 43, which is off the cliff. The measured one-channel floor is 44. |
| Assert **refusals**, not only successes | An over-fast trigger is silently halved with no status bit set. The guard is the only thing between that and corrupt data presented as clean. |
| Tolerances come from **measured spread** | Measure the spread, do not assume it. The ~5% recorded here was wrong: five runs per mode give 35-59% on the DMA benchmarks, so the floors come from the minima and are justified by what they must catch, not by how close they sit to the typical figure. |

## 1. Constants the tests need

Measured on this board at MCK 78. Do not re-derive these; re-measure
them if they are ever in doubt.

| Quantity | Value | How to re-measure |
|---|---|---|
| MCK | 78 MHz | banner |
| TC clock (TIMER_CLOCK1) | 39 MHz = MCK/2 | - |
| ADC clock | 19.5 MHz = MCK/4 | banner |
| 2ch floor | **RC 86** -> 453,488 Hz/ch, 906,976 aggregate | `t` |
| 2ch cliff | RC 85 -> ratio 0.500 | `t` |
| 1ch floor | **RC 44** -> 886,363 sps | `=0,0,1t` |
| 1ch cliff | RC 43 -> ratio 0.500 | `=0,0,1t` |
| ADC clocks per conversion | 22 isolated, 43 per 2ch pair | derived from the two cliffs |
| DACC top exact rate | RC 28 -> 1,392,857 sps | `d` |
| Full-scale sine amplitude | ~1370.5 codes | theoretical |
| DAC output span | 546-2760 mV (not rail to rail) | `s` |
| Frame | 32 B header + 2032 samples = 4096 B | `frame.h` |
| USB OUT / IN / duplex | ~27 / ~31-32 / ~15-16 MB/s, ~5% spread | `G` `T` `Y` |

One-channel capture is **slower** in conversions per second than two
(886,363 against 906,976): a two-channel trigger converts its pair back
to back and amortises the per-trigger overhead a lone conversion pays in
full. A test that assumes one channel runs at twice the two-channel
trigger rate encodes a bug.

## 2. Prerequisite refactor

`host/ports.py` and `host/rt.py` are already importable libraries and do
not change. `host/loopback.py`, `host/receive.py` and `host/usbbench.py`
are `main()` monoliths that print; their measurement logic moves to
`host/measure.py`.

**Nothing about the measurement behaviour may change in this step.** The
clock-paced feeder with its 20 KB lead, the real-time thread promotion,
the freshness drain and the whole-packet write discipline are all
load-bearing and hard-won - see `docs/usb.md` before touching any of
them. Verify the refactor by running each CLI before and after and
diffing the output.

```python
# host/measure.py

@dataclass
class ChannelStats:
    tag: int; n: int; lo: int; hi: int; mean: float

@dataclass
class LoopResult:
    frames: int; first_seq: int; last_seq: int
    seq_gaps: int; crc_bad: int; max_overrun: int
    elapsed_s: float; dev_span_s: float
    declared_rate_hz: int; channel_mask: int
    per_channel: dict[int, ChannelStats]
    windows: dict[int, list[tuple[float, float]]]   # tag -> (dev_t, amplitude)
    settled: dict[int, list[int]]                   # tag -> samples, for slew
    play: PlayCounters      # bytes_in produced consumed underruns
                            # isr endtx svc rebuilds act_in act_out
    host_tx_bytes: int; host_rx_bytes: int

def run_loop(board, *, dac_sps, adc_hz, channels=2, tone=1000.0,
             seconds=3.0, dc=None) -> LoopResult
def run_capture(board, *, preset, seconds, expect_hz) -> CaptureResult
def run_bench(board, *, mode, seconds) -> BenchResult
def sweep_rates(board, *, channels) -> list[SweepRow]   # parses `t`
def sweep_dac(board) -> list[SweepRow]                  # parses `d`
def profile(board) -> dict[str, int]                    # parses `Q`
```

### The Board object matters more than it looks

```python
class Board:
    def flash(self, track: str) -> None      # retry on SAM-BA
    def cmd(self, text: str) -> None         # write to the control port
    def drain_console(self, secs) -> str
    native: str                              # re-globbed after reset
```

Opening the control port asserts NRSTB and resets the board, which also
re-enumerates the native port under a possibly new name. Today every
measurement pays that: a reset, a 3 s settle and a re-glob, about 15 s
of fixed cost. A **session-scoped Board that opens the control port once
and keeps it open** turns that into roughly half a second per test. That
single decision is what makes a sixty-test suite finish in minutes
instead of half an hour, so build it that way from the start.

## 3. Layout

```
tests/
  conftest.py          # --track, Board fixture, freshness + window helpers
  baseline.json        # calibrated thresholds for THIS board
  test_contract.py     # refusals, header self-consistency   (fast, first)
  test_rates.py        # domain 1
  test_integrity.py    # domain 2
  test_channels.py     # domain 3
  test_play_counters.py # the device's own instruments, not the signal
  test_transport.py    # USB benchmarks                      (slow)
host/measure.py        # extracted library
```

`pytest --track=a|b|both`, defaulting to both. Track is a session
fixture that flashes once and yields a `Board`. Markers: `smoke`,
`slow`, `awg`, `scope`, `track_a`, `track_b`.

## 4. Domain 1 - sample rate, low to high

Ladders in RC, every entry an exact divisor of 39 MHz:

| Mode | RC ladder | Range |
|---|---|---|
| 2ch loop | 780, 390, 200, 195, 130, 98, 88, **86** | 50k - 453,488/ch |
| 1ch loop | 390, 195, 98, 65, 50, 45, **44** | 100k - 886,363 |
| AWG play-only | 195, 98, 65, 44, 39, 32, **28** | 200k - 1,392,857 |

Per rate: `seq_gaps == 0`, `crc_bad == 0`, `under == 0`,
`measured_rate` within 0.5% of declared.

Plus a **rate-exactness** test, which is the one that catches
truncation: `header.sample_rate_hz == 39_000_000 // RC`.

The AWG ladder is play-only (`P`), with no capture running, so a DAC
fault cannot be masked by, or blamed on, the capture path.

## 5. Domain 2 - signal integrity

The most important domain and the easiest to under-build. Counters have
been clean while the signal was wrong.

| Test | Assertion | Catches |
|---|---|---|
| Tone amplitude per window | median >= threshold, >=90% of windows above | real purity |
| **Slew limit** | max abs delta between consecutive same-tag samples <= analytic `2*pi*f*A/fs` | spliced data, without the Goertzel - tests invariant 5 directly |
| Demux / crosstalk | 2ch with DAC1 at mid scale: A1 tone < a few codes | channel tags read wrong |
| Tag hygiene | every sample tag is in the configured mask; header `channel_mask` agrees | channel confusion |
| DC transfer | `--dc` sweep tracks the code; span ~546-2760 mV | analog path, needs no tone |
| Frequency accuracy | recovered peak == tone sent | a rate error hiding behind good amplitude |
| **Negative control** | playback stopped -> A0 shows **no** tone | stale data; this is the test that would have caught the "frozen DAC" |
| Freshness | `first_seq` near 0 and device timestamps span the host window | shared helper on *every* measurement, not a standalone test |

The slew test is worth building first. It needs no spectral analysis, it
is cheap, and it fails loudly on exactly the failure the protocol exists
to prevent: data spliced across two points in time that still passes its
header CRC.

### The device-waveform gate, re-verified after the pair_fold fix (2026-08-26)

`b96368e` changed `pair_fold()` to try both parities *after* the gate in
`test_device_generated_waveform_is_continuous` had been rewritten to
depend on it, so the gate was resting on an instrument that had moved
under it. Re-measured on Track B `main`, four captures at preset `M`
plus four suite runs:

| | parity 0 | parity 1 |
|---|---|---|
| `pair_spread` (median abs difference) | **1.00 codes** | 24.00 codes |
| fold z | 43-60 | 1.2 |
| fold peak | -5.3 to -5.6 codes | +42.6 to +43.2 codes |

**The selection rule is not close on device data - the two parities are
24x apart, identically on every run.** That is the separation the rule
assumes: within a held DAC level the difference is noise, across a level
boundary it is a whole DAC step. A rule that picked the smaller of two
similar numbers would be a coin flip and the gate would be unstable; it
is not.

Two things follow that are worth writing down. **Parity 0 is what wins
here, which is what the pre-fix code assumed** - so at preset `M` on this
board the fix changes nothing, and the gate's recorded verdicts before
and after it are comparable. The fix's effect was on the layout sweep's
sine arms, where the trim landed on the other side. And **the wrong
parity does not merely misreport, it reports something plausible**: z 1.2
at +43 codes, which is a DAC step wearing the artifact's units. `hold_ok`
refuses it at 24 against a limit of 4, which is the guard doing its job
rather than the measurement failing.

The gate itself is stable across seven consecutive runs: `hold_ok` true,
xfail on issue #5 every time, peak -5.4 to -5.6 codes at phase 192, z
41-60 against a control z of 2.7-4.1. The census count under it moves
between 0, 1 and 5 steps over 45 codes run to run, which is exactly why
the gate stopped thresholding that number and started identifying the
state instead.

## 6. Domain 3 - channels and ceilings

Cheap, mostly contract, so it runs before the long streaming tests.

- 2ch accepts RC 86 and **refuses** RC 85; 1ch accepts RC 44 and
  **refuses** RC 43. Assert the refusal is reported on the console and
  that the loop does not start.
- Aggregate conversion rates: 2ch -> 906,976, 1ch -> 886,363, and
  explicitly assert `1ch_aggregate < 2ch_aggregate`.
- `t` and `=0,0,1t` parsed: ratio ~1.000 for every row above the cliff,
  and the first row past it reads 0.500 or REFUSED.
- Matched full-rate loop in both modes, on both tracks.

## 7. Thresholds

`pytest --calibrate` runs the ladders and writes `tests/baseline.json`;
tests assert against it with a tolerance band. Commit it, labelled as
this board's figures - it is a record of one board, not a datasheet.

Divergences between the tracks go in an explicit `KNOWN_DIFFERENCES`
table with the cause written down, **never** as a loosened global
tolerance. Current entry:

| Case | Track A | Track B | Cause |
|---|---|---|---|
| Capture resyncs, 2ch full-rate pair, 6 s | 1241 | 21 | Track A's capture IN still goes through the core's blocking `USBD_Send`, which stalls the service loop long enough for the capture ring to lap. Objective 1 removes it. |

Keeping it in a table means it stays visible and closes itself when
capture IN moves to endpoint DMA, instead of silently widening a
tolerance that then hides the next regression.

## 8. Runtime budget

Roughly 5 minutes per track, 12 for both including flashes. `-m smoke`
should stay near 2 minutes for iteration. Transport benchmarks are
`slow`: about 40 s each, with ~5% spread.

## 9. Risks

- **The native cable is marginal.** It failed hard twice on 2026-08-21,
  VBUS present and D+/D- dead. Add `test_link_health` first in the run
  so a physical fault is diagnosed rather than blamed on firmware.
- **Flashing is flaky.** SAM-BA drops happened twice in one session. The
  fixture needs retry with the port given explicitly, or the suite
  reports false failures.
- **Opening the control port resets the board.** Any test that opens it
  independently of the session Board invalidates whatever was running.
- **`test_host_fed_ramp_loses_no_samples` is intermittent, and its rate
  drifts by era.** Measured 2026-08-26 rather than guessed: 5 of 8, then
  2 of 8, then 1 of 8 in sequential batches on the same firmware - and
  **0 of 10 against 1 of 10 when the two firmwares were interleaved with
  a reflash between arms.** So the failure is real, unexplained, and
  *not* attributable to anything changed that day; the sequential
  batches were measuring the hour, not the build. It fails on byte
  conservation with losses that are not whole 128-byte chunks
  (`[10, 12, 10, ...]` bytes), which the assertion reads as the device
  losing data it received.

  **The lesson is the method, not the number.** Two sequential batches
  of eight disagreed with each other by a factor of two and a half. Any
  claim about this test - including "my change broke it" and "my change
  fixed it" - needs the arms interleaved, exactly as a firmware A/B
  does. See `tools/ab.py` for why.

- **`test_matched_full_rate_loop[b-2-906976-453488]` and
  `test_awg_ladder_play_only[b-32]` also fail occasionally** - and the
  second one is characterised below and is **not** Track B's: it fails
  the same way on Track A, one
  sequence gap or one uncounted repeat, at the top of the ladder where
  `docs/HANDOFF.md` already records an intermittent residual and
  oversupply. Neither has been characterised the way the ramp test now
  has. Do not quote any of this as "known flakiness" to wave away a
  failure there - the next one should be read before it is re-run.

  **The next one was read, 2026-08-26.** `test_awg_ladder_play_only[b-32]`
  failed in a full run at **2.283 MB/s against the 2.438 MB/s that
  1,218,750 sps needs** - 93.7% against a 95% gate, so a 1.3-point miss
  rather than a collapse. It is the *host* short of the rate, not the
  device: `under=0`, and the assertion exists precisely because a device
  that was never asked for the rate cannot underrun.

  **Then it passed 6 of 6 standalone, 8 s each, on the same binary and
  the same host minutes later.** So whatever this is, it is not an
  intrinsic ceiling at RC 32 - it depends on running inside a full
  suite. Two hypotheses that are *not* it, both checked rather than
  assumed: `rt.promote()` is not a no-op on Windows (it does
  `timeBeginPeriod(1)` and `SetThreadPriority`), and the `Feeder` thread
  does promote itself - `Feeder._run` calls it first thing.

  **Characterised the same day, and the useful finding is that the rate
  is bimodal.** Read `fed_mbs` from `--calibrate` instead of pass/fail -
  the test records it on passing runs too - and it lands in one of two
  tight clusters and never between them:

  | mode | `fed_mbs` | against the 2.438 needed | gate at 0.95 |
  |---|---|---|---|
  | high | **2.431-2.434** | 99.8% | passes |
  | low | **2.281-2.283** | 93.6% | fails |

  Fourteen runs, seven of each arm of the A/B below, plus three failures
  seen in full-suite runs at 2.282274, 2.282930 and 2.283142 - a spread
  of 0.04% across three different sessions and two different suite
  compositions. **A scheduling or jitter story predicts a distribution;
  two clusters 6.3% apart with nothing between them means something
  discrete is switching.** That is the thing to chase, and it is not
  "occasional flakiness".

  **A hypothesis that died, recorded because the way it died is the
  point.** `test_jitter.py` immediately before `test_rates.py`
  reproduces it in 110 s, where `test_rates.py` alone does not and
  `test_census.py` before it does not either - so it looked specific to
  that file, and `test_jitter.py` is pure computation that builds
  histograms. Cyclic-GC pressure was the obvious mechanism, and
  disabling the collector made the first four measurements separate
  perfectly: 2.282/2.283 with it on, 2.432/2.433 with it off.

  **Interleaved to five rounds, it fell apart.** `gc=off` produced 2.281
  in round 4, and pooled the low mode appears 3 of 7 times with the
  collector on and 1 of 7 with it off - not separable at that n. The
  first four points were the exact trap the ramp-test entry above warns
  about, on the same suite, three paragraphs later. **Interleave before
  believing, including when the first numbers look decisive - especially
  then.**

  Two mechanisms are ruled out by direct check rather than by argument:
  `rt.promote()` is not a no-op on Windows (it does `timeBeginPeriod(1)`
  and `SetThreadPriority`), and `Feeder._run` promotes its own thread
  before its first write.

  **And it is host-side, which is now shown rather than inferred: the
  same low mode appears on Track A.** `test_awg_ladder_play_only[a-32]`
  fed 2.282286 MB/s in a full Track A run - inside the 2.281-2.283
  cluster the Track B failures sit in, matching to 0.05%. The two tracks
  share no firmware source, enumerate through different USB stacks, and
  reach the DAC by different code; what they share is this host and this
  feeder. **So the entry above should not be read as a Track B
  property**, and any explanation that starts in the firmware has to
  account for two independent implementations landing on the same two
  numbers.
- **Two tests now fail only inside a full run, and it is worth
  watching whether that is one thing or two.**
  `test_awg_ladder_play_only[*-32]` is characterised above.
  `test_daemon_api.py::test_the_fanout_cost_is_recorded_per_frame`
  joined it on 2026-08-27: `assert 33 <= (30 + 2)`, off by one on a
  tolerance, in a full Track B run. It passed 6 of 6 standalone and 47
  of 47 with its own file, three times each, on the same tree.

  They have almost nothing else in common - one is a host feed rate
  against real hardware, the other is board-free accounting over a fake
  device - so **do not assume a shared cause**. What they share is that
  neither reproduces outside a long session, which is the property that
  makes both expensive to chase and is why both are written down rather
  than re-run until green. The suite grew ~27 tests on 2026-08-26 when
  the bench-scope work landed, which changes ordering and timing for
  everything after it; that is a candidate and not a finding.

- **`--calibrate` writes only at session end, so a run that hangs at
  90% yields nothing.** Collect per file instead - one pytest session
  per test file, each flushing its own `baseline.measured.json` - and
  merge. A full calibrated run took twelve minutes and produced no data
  at all on 2026-08-27; the per-file sweep produced 51 keys and every
  file completed.

  `tests/baseline.measured.json` is also not in `.gitignore`, so it can
  be committed by accident. It is meant for a human to promote into
  `baseline.json`, never to land as it is.

- **After force-killing a suite, heal the ports before running anything
  else.** A killed pytest can leave a process holding the control port,
  and every later run then fails with `could not open port 'COM7':
  Access is denied` - which looks exactly like a board fault and is not.
  Measured on 2026-08-27: one force-kill made five consecutive per-file
  runs error out at fixture setup in 0.05 s each, reading as five broken
  files rather than one unreleased port. Killing the two stray processes
  was enough; the reflash in the healing order below was not needed.

- **Never truncate a suite run's output.** The first of those two was
  lost to a `| tail -3` on the pytest invocation, which threw away the
  traceback and left nothing to diagnose; the re-run was green and the
  evidence was gone for good. Run with `-rf --tb=short` and keep the
  whole thing.
- **The native port can accept an open and never return from it**, and
  that is not the same as being absent. Measured on Windows after a
  NRSTB reset: `ports.native_nodes()` lists the node, Device Manager
  reports it healthy, and `CreateFile` blocks - so a caller with a
  generous deadline still hangs, because control never comes back to
  test the deadline. Seen as `OSError(22)`, Windows `ERROR_SEM_TIMEOUT`,
  and as error 31 on the sibling node.

  `Board.open_native()` runs each attempt in a daemon thread and
  abandons it after `attempt_timeout`, re-globbing every pass, for up to
  45 s. An abandoned thread leaks a handle in a process that is about to
  exit; that is a straight trade against hanging the run.

- **Healing, in the order to try it.** Any of these is acceptable - the
  bench is a test rig, not a patient.
  1. **Close what you opened.** `measure.Board` is a context manager;
     use `with`. A script that dies holding the control port makes every
     later run fail with "Access is denied" on it, and that looks
     exactly like a board fault. Most of one session's "unstable
     enumeration" was this.
  2. **Kill any stray process** still holding a node. A blocked open in
     an abandoned process holds the port until that process exits.
  3. **Reflash.** `tools/flash.py` does a 1200-baud touch and a full
     re-enumeration and reliably clears a device that has stopped
     answering. Verified: five consecutive capture cycles afterwards,
     4.8 s each, byte-identical.

## 10. Implementation order

Each step builds and is independently verifiable, in the same spirit as
the bring-up order.

1. `host: extract the measurement library from the CLI tools` - add
   `host/measure.py`, make the three scripts wrappers. Verify by
   diffing each CLI's output before and after.
2. `tests: add the pytest harness and board fixture` - conftest, the
   session Board with a held control port, flashing with retry, and
   `test_link_health`.
3. `tests: cover channel modes and ceiling refusals` - domain 3 first;
   it is cheap and catches contract regressions before the long tests
   have run.
4. `tests: cover the rate ladders` - domain 1.
5. `tests: cover signal integrity` - domain 2, slew test first.
6. `tests: cover USB transport` - domain 4, marked slow.
7. `tests: record the calibrated baseline for this board`.
