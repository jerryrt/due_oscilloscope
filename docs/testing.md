# Test Suite: design and implementation guide

**Status: implemented.** `host/measure.py` plus `tests/`. Run it with

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
