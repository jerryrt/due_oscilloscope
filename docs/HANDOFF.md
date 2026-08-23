# Handoff

Read this first, then `docs/status.md` (what works, measured figures,
recorded mistakes) and `docs/usb.md` (transport ceilings and host I/O
policy). If you are here to build the test suite, the whole plan is in
`docs/testing.md` - start there and read this for the environment.

## Where the work stands (2026-08-23, end of session)

The board is a working instrument with a front end on top of it. What
changed this session is that the host side grew a spine: a daemon that
owns the ports, a socket API with its own test suite, and a Qt window
that draws from it.

**The daemon.** `host/daemon/` owns both ports and the real-time
feeder and serves clients over TCP - `docs/daemon-api.md` is the
reference, `docs/frontend.md` says why it is a separate process.
Frames cross verbatim, so `measure.parse_frames` reads a socket and a
serial port identically. `python3 -m daemon --fake` runs it with no
hardware at all, which is what front end work should be built against.

**The front end.** `gui/` is G1: a live trace with min/max decimation,
timebase and channel controls, and a health panel built first rather
than last. Run it with `.venv-gui/bin/python -m gui --spawn-fake`.

**Capture no longer touches the processor** (Track B). Each capture
buffer carries 32 bytes of headroom, so a finished frame is 4096
contiguous bytes sent by one DMA per packet. That closes the last
violation of invariant 1. It did **not** improve purity, which was the
reason the objective existed - see objective 1 below and the A/B in
`docs/status.md`. Track A still copies, deliberately.

**The daemon runs free-threaded.** With four busy Python threads in
its process, the GIL build underran playback 13 times and read 132
frames where a quiet run reads ~890; the free-threaded build of the
same version underran zero times and read 891. It is stdlib only, so
it needs no free-threaded wheels: `python3.14t -m venv` is the whole
setup.

**Latency is measured, not inferred.** `host/jitter.py` records the
device read gap, the fan-out cost and the feeder's write interval in
log-2 microsecond buckets, and the daemon reports them in `status`.
Every scheduling argument in this project used to be conducted in
units of "13 underruns"; it can now be conducted in milliseconds.

### The suite

`pytest --track=both -q`: **244 passed, 2 skipped, 4 xfailed, 4
xpassed in 12:11**. About 12 minutes for both tracks, of which the
board-free tests are seconds.

| Venv | Interpreter | Runs |
|---|---|---|
| `.venv` | 3.14.6 | the suite - `--track=a|b|both`, `-m smoke` for a ~2 min pass |
| `.venv-gui` | 3.13.14 | the GUI and `tests/test_gui.py` (PySide6 is `<3.14`) |
| `.venv-ft` | 3.14.6 free-threaded | the daemon, and the suite when checking it there |

The GUI tests skip in `.venv` rather than failing, because that venv
deliberately has neither Qt nor numpy.

### Things that were believed and turned out to be wrong

Three, all disproved with measurement rather than argument, and all
worth not re-deriving:

- **The capture CPU copy was not limiting purity.** A/B in loop mode
  at the full-rate pair: median window 1291-1298 codes on DMA against
  1292-1306 on the copy, `resync=2` either way.
- **Objective 0a is not a clock-drift problem.** Two separate "6%
  drift" figures were measurement artifacts - see 0a.
- **The slew test's margin was never exercised** while the test was an
  xfail, so it inherited a number that the mechanism it measures
  exceeds routinely.

Work is on `main` and pushed. The board was last flashed with
**Track B**.

Three things separated out of the lost-sample defect in the previous
session remain objectives 0a to 0c: the rate starvation is a different
mechanism, what is left of the sample loss is the host's, and the
suite wedged once in `close()`.

Track A is level with Track B where it counts - same command letters,
same output format, same refusals, same wire format, same throughput -
and differs in one implementation detail: Track B's capture path is on
endpoint DMA and Track A's still copies, because Track A cannot pin a
buffer to an SRAM bank under the Arduino core's linker (objective 1b). Its bulk endpoints were taken away from the Arduino core and
put on UOTGHS DMA; the core still enumerates. Typical figures are
OUT ~27, IN ~31-32, duplex ~15-16 MB/s, but **the run-to-run spread is
35-59%, not the ~5% this file used to claim**: five 4 s runs per mode
gave IN 19.8-30.5, OUT 17.9-28.2, duplex 8.2-20.0. The suite's floors
are set from the minima for that reason, and a single benchmark run is
not evidence of a change. See "Track A parity" in `docs/status.md`.

The 900 ksps loop runs on both: `--dac-sps 906976 --adc-hz 453488` is
906,976 conversions per second, because two channels convert
round-robin. Single-channel capture now exists too (`--adc-channels 1`,
or `=<dac>,<adc>,1` on the console) and both tracks run a matched loop
at its ceiling of 886,363 sps each way with `under=0`.

Track B runs the complete instrument loop on one channel pair:

```
HOST -> USB bulk OUT -> DAC0 -> jumper -> A0 -> ADC -> USB bulk IN -> HOST
```

Endpoint DMA works (the historical one-transfer stall is fixed), the
playback ring is fed by DMA with no CPU byte-copy, and every measured
regime is validated by the tone-amplitude oracle (theoretical maximum
~1370.5 ADC codes for a full-scale sine), not by counters alone:

| Regime | State | Evidence |
|---|---|---|
| Matched loop up to 453,488 sps each way (ADC in-spec ceiling) | under=0, gaps=0, median window 1371 | at 200 ksps the loop is now byte-exact end to end: `play_bytes_in` equals the host's `write()` count and a host-fed ramp has no discontinuities |
| AWG play-only up to 1.393 Msps (DACC hardware ceiling, RC 28) | **runs; not reliably clean** | 5 runs each: RC 195/98/44/39 are 5/5 under=0, RC 65 is 0/5, RC 32 is 3/5, RC 28 is 1/5. See objective 0a |
| Full-rate pair: DAC 906,976 + capture 906,976 aggregate | **runs, under=0**, both tracks | windows 1074-1345 (B), 1028-1338 (A) |
| Transport via endpoint DMA | measured | IN 32.0 / OUT 26.6 byte-perfect / duplex 16.95 MB/s |
| Two-channel DAC (tag-interleaved) | routing verified | purity open, see objective 4 |

The `~1.7 MB/s "gated OUT" cap` that once blocked full-rate duplex is
explained and gone: it was DMA/FIFO re-arm latency times transfer
granularity, removed by multi-slot DMA spans with mid-flight progress
publishing.

## Current firmware/host design, in one pass

- **Playback**: host streams 16-bit tagged samples over bulk OUT; a
  32-slot (32 KB) ring in SRAM bank 1 is filled by endpoint DMA
  (multi-slot spans, `BUFF_COUNT` progress publishing, stream variant
  without END_TR so short packets never fragment a span); DACC + PDC
  drain it at TIOA1's rate; underrun repeats a buffer and is counted,
  never concealed. Progress is read from **one** snapshot of
  `DEVDMASTATUS` per pass - byte count and channel-enabled both come
  out of that single read, and `play_bytes_in` follows it continuously
  so it can be compared against the host's `write()` count byte for
  byte. `play_partial` counts spans that ended off a slot edge and
  must stay zero.
- **Capture**: TIOA0-triggered ADC, PDC ping-pong into a 4-buffer ring,
  frames (32 B header + 2032 samples = 4096 B). **Track B sends them by
  endpoint DMA**: each buffer carries the header in 32 bytes of
  headroom in front of its payload, so a finished frame is contiguous
  and goes out in packet-sized transfers the processor never reads. The
  ring is pinned to SRAM bank 1 for that reason - see the hard-won
  facts. **Track A still copies** (objective 1b).
- **Host feed** (`host/loopback.py`): real-time thread (`host/rt.py`,
  QoS + Mach time-constraint; XNU has no core pinning), clock-paced at
  the DAC byte rate with a 20 KB lead, blocking writes of whole
  512-byte packets only. Safe because the DMA-fed ring drains the tty
  queue at wire speed, so the macOS pressure-drop condition cannot
  form. The older TIOCOUTQ empty-queue gate was correct for the
  manual-FIFO device and is obsolete; do not resurrect it without
  re-reading `docs/usb.md`.
- **Rates**: `=<dac>[,<adc>]` before `L`/`P` on the console;
  `--dac-sps/--adc-hz` on `loopback.py`. Refusals name the limit.

## Next objectives, in order

**Start here**: objective 0a. It is the oldest thing still open, the
mechanism is now narrowed to the device rather than the feed, and the
next experiment is written out under it. Everything else on this list
is either a smaller job or waits on hardware.

If you would rather build than debug, the alternative is **G2** on the
front end - trigger, measurements, FFT - which needs no board at all
(`--spawn-fake`) and cannot be blocked by the cable in objective 2.

Objectives 0a to 0c are what came out of the lost-sample defect when it
was taken apart. None of them is that defect; each was folded into it
before and is now separate, with its own evidence.

0a. **Playback starves at RC 65, 32 and 28** while the rates either side
   of them are clean. A feed-policy problem, not a bandwidth ceiling:
   during starvation the host's tty output queue is empty (median 0 B),
   so the device drains everything written the moment it is written and
   the host is simply never far enough ahead. The feeder's 20 KB lead
   is spent once at startup and never rebuilt, and whether a run keeps
   a cushion is decided in its first milliseconds and holds for the
   whole run. Larger leads (24 and 28 KB), a single-write opening
   burst, and a larger device prime threshold (4 -> 16 buffers) each
   changed nothing.

   **It is not a rate deficit, and not a clock mismatch.** At RC 65 the
   host fed a 2% surplus over what the DAC needs and still underran 7
   to 10 times a run; pacing against the device's own clock cannot help
   a feed that is already ahead. A feeder that over-fed into saturation
   underran zero times in 4 of 4 runs and armed ~3,525 spans against
   ~237 - so the span pattern, not the average rate, is what separates
   the two. That fix is not shipped: writing until the queue blocks is
   the saturation that makes macOS drop 128-byte chunks. Full write-up,
   including two drift figures that turned out to be measurement
   artifacts, in `docs/status.md`.

   **The next experiment, stated so it can be run without re-deriving
   it:** hold a bounded lead measured against the device's consumption
   rather than against the kernel queue - target 70-80% ring occupancy
   - and watch the span count. If spans stay high while the queue
   stays shallow, the mechanism is confirmed and the policy is safe to
   ship. If spans collapse the moment the queue drains, the arming
   policy in firmware is what needs changing, not the feed.

   Do not reach for the device clock to do it. That was tried and the
   arithmetic is in `docs/status.md`: the device's timestamps lag by
   however deep the kernel buffer is, so pacing on them silently
   over-feeds, and over-feeding is saturation - which is where macOS
   drops 128-byte chunks.

   The `spans` counter added with the lost-sample fix is a new handle
   on it: a starving run arms few, large DMA spans (RC 32, failing: 464
   in 3 s) and a healthy one arms many small ones (RC 32, clean:
   6,610). Tracked as `STARVES` in `tests/test_rates.py`, xfail and
   non-strict, so it reports on every run and turns green by itself.
   The 2026-08-22 pass xpassed RC 65 on three of the four ladder
   entries that carry it - Track A one-channel and AWG, Track B AWG -
   and still xfailed Track B one-channel. That is the intermittency
   this objective describes, not a change in it.

0b. **macOS drops 128-byte chunks from the tty output queue** under
   load, having counted them in `write()`. Long documented in
   `docs/usb.md` as a hazard; now *measured*, because the device's byte
   accounting is exact: a run that skips is short by whole multiples of
   128 bytes and the device never received them. Roughly one 3 s run in
   eight with a build or the suite running alongside, none in 22 runs on
   a quiet machine. Reported by `test_host_fed_ramp_loses_no_samples` as
   an xfail that names the host; an arbitrary-sized jump fails the same
   test outright, because that would be the device losing data again.

0c. **The suite wedged once in `close()` after the duplex DMA bench**,
   on 2026-08-22, and it is unexplained. All 134 tests reported and
   none failed; the session then hung in `close()` on the native port
   for 50 minutes with the board's heartbeat still flashing and both
   USB activity LEDs dark - the device had stopped draining bulk OUT,
   which is the hazard `docs/usb.md` describes: macOS's `close()` waits
   for in-flight write URBs and `tcflush` cannot recall them.

   **Not reproduced**: eight consecutive duplex-dma and out-dma benches
   afterwards closed in 0.00 s each. So this is a candidate, not a
   cause - but a specific one. `usb_cdc_dma_mode()` stops both DMA
   channels and flips AUTOSW and **never issues `EPRST`**, while the
   fact recorded below says stopping the channel is not enough and the
   endpoint must be reset too. Track A implements exactly that
   (`ep_reset_fifo()` in `sketches/bringup/usbdma.cpp`); Track B has no
   `EPRST` anywhere. A DMA stopped mid-bank leaves a bank nothing
   frees, and the endpoint then NAKs for good.

   Deliberately not "fixed" on that reasoning alone: `EPRST` also
   clears the data toggle, and `usb_cdc_dma_mode()` runs at every
   playback and bench start and stop, so a wrong guess here breaks the
   link everywhere. Reproduce it first - a long soak of bench mode
   switches is the obvious way - then fix it against a failure that can
   be seen to go away.

   It did not recur in the 2026-08-22 two-track pass, which ran the
   same benches on both tracks and closed in the usual time. Still
   unreproduced, so the reasoning above stands unchanged.

0e. **One gross ramp failure on Track A, seen once, unexplained.** On
   2026-08-22 `test_host_fed_ramp_loses_no_samples[a]` failed with
   73,314 losses of **exactly 10 bytes each** - not the host's 128-byte
   signature, and far too many to be the beat in 0f. Every loss being
   the same size says something systematic, not noise. It has since
   passed 9 runs on Track A, one of them xfailing with the ordinary
   host signature, so it is not reproducible on demand. Recorded rather
   than dismissed: if it returns, capture the run's raw stream before
   anything else, because the pattern is the whole evidence.

0f. **The slew alarm was the sampling beat, and the margin was wrong.**
   Closed, and written up in `docs/status.md`. Kept here for the rule
   it produced: **a threshold that has only ever run under an xfail has
   not been tested.** When the xfail comes off, the numbers it was
   hiding need re-deriving rather than inheriting.

0g. ~~**The firmware does not refuse a DAC rate past the DACC
   ceiling.**~~ **Fixed on both tracks.** `play_start` now refuses
   below `PLAY_MIN_RC` (28) and both consoles name the limit the way
   the ADC path always has. `tests/test_contract.py` holds it: RC 28 is
   accepted, RC 27 and RC 20 are refused, and a refusal must contain
   the word "max". Original entry follows.

   **The firmware does not refuse a DAC rate past the DACC ceiling.**
   `=906976,906976,2L` is refused with the limit named - `# loop: ADC
   906976 Hz x2 ch refused (max 453488)` - which is the behaviour the
   documentation describes. But `=1950000,200000,2P` is *accepted*:
   RC 20, well past the ~1.393 Msps the DACC can convert at ~54.7 MCK
   cycles per conversion. Observed on both tracks while testing the
   daemon's refusal path.

   It matters more now than it did. `host/daemon/rates.py` refuses it,
   so nothing gets through the daemon - but that makes the host the
   only check rather than a courtesy, and a console user still walks
   straight into it. Refuse it in firmware, on both tracks, naming the
   limit the way the ADC path already does.

0d. **The pytest suite** - built, and it is the instrument that found
   all four defects on this page. `docs/testing.md` is the design and
   records what building it found. About 5 minutes per track, ~138
   tests for both. `--track=a|b|both`, `--reflash` to force a flash,
   `-m smoke` for a ~2 minute iteration pass.

1. **Capture IN over endpoint DMA** - **done on Track B**, and its
   premise was wrong. The design was as sketched here: 32 B of headroom
   per capture buffer, PDC on the payload, CPU writing only the header.
   What it did not do is improve purity - measured against the old
   firmware in loop mode at the full-rate pair, the two paths are
   indistinguishable and both show resync=2. Whatever limits purity
   there is not the copy.

   Two things had to be measured to make it safe, and the first version
   lost samples while looking perfect: transfers are packet-sized and
   the capture ring is pinned to bank 1, because a 4096-byte transfer
   from bank 0 costs 439 ADC overruns per 4 s at the full rate. Full
   table in `docs/status.md`.

   **Track A still copies**, deliberately: it cannot pin a buffer to a
   bank under the Arduino core's linker, and without that the same port
   measures 81 overruns per run against zero today. Adopting it there
   needs a verified placement mechanism first.
1a. **G2 on the front end**: trigger (edge, level, pulse; auto, normal,
   single), automatic measurements, FFT with a window choice. The
   decode, ring and reduction are already Qt-free in `gui/stream.py`
   and tested there, so this is mostly new views over existing data.
   Needs no board.

1b. **Capture over endpoint DMA on Track A**, which currently still
   copies. The port is written and measured - 81 ADC overruns per 4 s
   at the full rate - and blocked on placement: Track A links against
   the Arduino core's script and cannot pin a buffer to bank 1, which
   is what makes it clean on Track B. Needs a verified placement
   mechanism first, not a `--section-start` guess that would overlap
   whatever the allocator put there.

2. **Replace the marginal native-port cable** before attributing any
   further purity variance to software. It failed hard twice on
   2026-08-21 (VBUS present, D+/D- dead: enumerates nowhere) and the
   run-to-run variance has the signature of link-level retransmits.
3. **The second pair** (DAC1 -> A1 as an independent instrument pair).
   Bandwidth is trivial after the DMA work; the loop code needs
   two-channel waveforms and per-channel analysis.
4. **Two-channel DAC purity.** Tag routing is verified correct
   (975 Hz only on A0, 1500 Hz only on A1 at 97.5 ksps/channel), but
   dual mode shows two unexplained signatures with all counters clean:
   A0 phase jumps aligned to ring-slot boundaries, A1 steps at an
   exact 32-sample period. Retest after objectives 1-2; either may
   explain both.
5. **Equivalent-time reconstruction**: DAC and ADC dividers share MCK,
   so coprime RC values walk the ADC's sample phase through the DAC
   waveform in 25.6 ns steps - a sampling-scope view of the DAC
   through the slow ADC. The single-channel capture mode it needed now
   exists; what remains is the host reorder script.
6. **`usb_cdc_write`/DMA bank overcommit when the host stops
   draining** (status.md "Next" item 0): flood counters read far above
   the wire; harmless in normal operation, meaningless benches.
7. **MCK 40 for a capture-only scope mode** - investigated and shelved,
   recorded so it is not re-derived. `PMC_MCKR_PRES_CLK_3` makes MCK a
   multiple of 4, so MCK 40 with `PRESCAL=0` reaches exactly 20.0 MHz
   of ADC clock against today's 19.5 - the only in-spec way to clear
   900 ksps on a single channel (predicted 909,090, and 930,232
   aggregate for two). It is not worth it for the loop: the DACC is
   MCK-limited at ~54.7 cycles per conversion (measured, see
   hardware.md), so halving MCK roughly halves the AWG to ~730 ksps,
   below the new ADC ceiling. Only interesting as a runtime-switchable
   capture-only mode. **Trap if anyone tries it:** `ACQ_MIN_RC` is
   MCK-independent only while `PRESCAL=1` keeps the timer clock at
   twice the ADC clock. With `PRESCAL=0` they are equal and every cliff
   RC halves - 86 becomes 43, 44 becomes 22 - so the guard must be
   expressed in ADC clocks (22 isolated, 43 per pair) and derived from
   the live clock ratio.

## Hard-won facts the next session must not rediscover

- **Asking the board for its banner while it plays costs eleven
  underruns.** Every time, measured. The banner is a long console
  print, the main loop is inside it, and `play_service()` does not run
  while it is. `B`, the short counters report, costs none. The rule the
  daemon now follows: **on a poll path, ask the device nothing** - its
  `status` is answerable from the host alone and the device
  description is cached, because it used to be fetched per call.
- **Measure a firmware change against the firmware it replaces, not
  against expectation.** Capture over DMA streamed with no gaps, no CRC
  failures and no stalls while losing 439 ADC conversions per 4 s run.
  Reflashing the old build took three minutes and was the only reason
  that was attributed to the change rather than to the board.
- **The two SRAM banks are separate enough for placement to matter**,
  which `docs/scope.md` had listed as an open question. USB DMA reading
  the same bank the ADC's PDC writes costs 439 overruns per 4 s at the
  full rate; the other bank halves it; packet-sized transfers remove
  the rest. Track B therefore pins capture to bank 1 and playback to
  bank 0 - a swap, not a shrink.
- **A frame is 4096 bytes because the header sits in front of the
  payload**, in the same allocation. `acq_slot_t` is that struct, and
  `_Static_assert` holds both its size and the frame's 512-byte
  alignment. Growing the header silently breaks every short-packet rule
  in `docs/protocol.md`.
- **The GIL couples the daemon's own work to its real-time threads.**
  Four busy Python threads in the process: 13 underruns and 132 frames
  read against ~890 on the GIL build, none and 891 free-threaded. Load
  in *other* processes is the scheduler's business and is unaffected.
- **A drain loop with no bound never returns** when the producer is
  faster than the display. It hung the GUI's first test run for ten
  minutes. The daemon is built to drop toward a slow client and count
  it, so leaving frames queued is the designed behaviour.
- **Do not derive a ring's write position from a running total.** It is
  correct until one append is larger than the ring, and then the window
  silently returns samples that are not the newest.
- **A threshold that has only ever run under an xfail has not been
  tested.** When the xfail comes off, the numbers it was hiding need
  re-deriving rather than inheriting.
- **Both "the device clock drifts 6%" figures were artifacts.** The
  first anchored on a frame that was already 0.19 s old; the second
  lagged by however deep the kernel buffer was. The device clock is
  right to a tenth of a percent - 600,725 sps measured against a
  declared 600,000 once the pre-roll is removed.
- **Never analyse a capture without proving it is fresh.** Stale
  kernel-buffered frames from a previous run manufactured a "frozen
  DAC" that cost a full session. Sequence numbers near zero and device
  timestamps spanning the host window are the proof; `loopback.py`
  enforces both.
- **macOS CDC-ACM drops ~128-byte chunks from a pressured tty queue**,
  silently, with `write()` having counted them. The current safe feed
  relies on the DMA ring keeping the queue shallow; if the device side
  ever reverts to manual FIFO, the empty-queue gate becomes necessary
  again.
- **macOS `close()` on a tty waits for in-flight write URBs.** The
  device must always drain bulk OUT when nothing consumes it (the main
  loop does), or host processes hang in `close()` holding the port.
- **A DMA transfer in flight when its endpoint is rebuilt is dead**, and
  stopping the channel is not enough: a stopped IN DMA leaves a bank
  partially filled and never validated, so the next transfer stalls the
  same way. `EPRST` the endpoint too. This presented as an intermittent
  one-transfer stall, about one run in two.
- **Read `DEVDMASTATUS` once and decode it, never twice.** Byte count
  and channel-enabled share the register, so two reads ask two
  different instants whether the transfer finished and how far it got.
  They disagree exactly when it finishes between them, and the playback
  ring then resumed its next span behind data already in SRAM and
  overwrote it: samples lost, always forward, always less than one
  slot, with every counter on both sides clean. It cost a fortnight and
  was blamed on macOS. `play_partial` counts the impossible case and
  the suite asserts it is zero.
- **Two transliterations of one algorithm are not two implementations.**
  Track A's `play.cpp` is deliberately identical to Track B's `play.c`,
  so "both tracks fail the same way, and they share no source" argued
  for a host fault when it was evidence of a design fault. Before
  reasoning from a cross-track agreement, check what the tracks
  actually share.
- **Never arm bulk OUT with `END_TR_EN` for streaming.** It ends the
  transfer on any short packet, host pacing produces those constantly,
  and a 2048-byte buffer then absorbs ~347 bytes per arm. It cost ~30%
  of OUT throughput on both tracks and looked like a Track A problem.
- **Measure loop rate with no traffic.** Under load the arming path is
  skipped whenever a channel is busy, so the loop counter reads up to
  17x faster than the loop really is, and points at the wrong culprit.
- **UOTGHS DMA needs AUTOSW**; a `DEVEPTCFG` write while EPEN is clear
  is silently ignored on this part; endpoint config is rebuilt on
  every bus reset and SET_CONFIGURATION so the driver must reapply the
  mode. Each of these alone recreates the one-transfer stall. All three
  apply to Track A's DMA layer too, where the core does the rebuilding
  and there is no hook to catch it - hence the polled keepalive.
- **Judge loop purity per window, never per run.** The whole-run
  Goertzel at 453,488 sps reads 232 codes against a theoretical 1370.5
  while nearly every 50 ms window reads above 1360: a phase
  discontinuity cancels the average. A per-run number is the wrong
  instrument and will report a collapse that is not happening.
- **The board resets whenever the programming port is opened** (NRSTB),
  which also re-enumerates the native port under a possibly new name:
  open control first, keep it open, re-glob and retry the native open.
  The device cannot time its own benchmarks; the host keeps the clock.
- **Discover ports, never hardcode them** (`host/ports.py`); a stale
  path once aimed the 1200-baud erase at the wrong port.
- **Give the board time to re-enumerate before opening the native
  port.** `measure.Board(settle=3.0)` is what the suite uses and it is
  not decoration: opening the control port resets the board, and a
  native node opened too soon after that belongs to the instance going
  away. It opens successfully and then every write fails ENXIO, which
  reads as a dead device rather than a race.
- **The single-channel trigger floor is RC 44, not 43.** One channel
  reaches 886,363 conversions per second, two reach 906,976: a
  two-channel trigger converts its pair back to back and amortises the
  per-trigger overhead a lone conversion pays in full. Halving the
  two-channel compare value is the obvious move and it is wrong - RC 43
  measures ratio 0.500 with every status bit clear. `ACQ_MIN_RC_FOR()`
  is a table of measured values for that reason.
- **Trigger overrun is silent** (`ACQ_MIN_RC` 86, valid at any MCK).
  **`A0` is AD7, not AD0** (labels map descending). **The DAC is not
  rail to rail** (546-2760 mV), and a DACC channel that never converted
  since `SWRST` sits at its code-0 level - normal, not a fault.
- **Exact divisors matter**: rates that do not divide 39 MHz truncate
  in RC and shift every derived frequency; pick rates like 195000
  (RC 200), 453488 (RC 86), 906976 (RC 43), 1392857 (RC 28).
- **Periodic diagnostics alias periodic signals** (150 ms snapshots
  strobe a 1 kHz tone); pick intervals coprime to the signal.
- **Instrument the suspect region before attributing anything to it**,
  and prefer per-window analysis against device timestamps over
  whole-run averages - a handful of glitches per second hides in an
  average and shows instantly in windows.

## Environment

- macOS 12.7.6, Intel x86_64, no Homebrew - but **MacPorts is
  installed** at `/opt/local`. `/usr/bin/python3` is the Xcode CLT
  3.9.6 and nothing is built on it any more. `~/.local/bin` on `PATH`
  (holds `arduino-cli`, `cmake`, `gh`).
- **Three venvs, none committed.** A venv holds absolute paths and
  platform-specific wheels and does not travel; the pinned declaration
  is what is committed.

  | Venv | Interpreter | Holds |
  |---|---|---|
  | `.venv` | `/opt/local/bin/python3.14` (3.14.6) | pytest |
  | `.venv-gui` | `/opt/local/bin/python3.13` (3.13.14) | PySide6 6.9.3, pyqtgraph, numpy, scipy |
  | `.venv-ft` | `/opt/local/bin/python3.14t` (free-threaded) | pytest; run the daemon here |

  PySide6 declares `>=3.9,<3.14`, which is why the GUI has its own
  interpreter. The daemon imports nothing outside the standard library,
  which is why it can run on the free-threaded build at all.
- Track B: `cmake --build build -j`, flash with
  `tools/flash.sh build/baremetal_bringup.bin` (discovers the port; an
  interrupted flash leaves SAM-BA enumerated and the banner silent -
  just flash again with the port given explicitly).
- Track A: needs `--build-property build.f_cpu=78000000L` (MCK is 78).
- Use the **xPack** ARM toolchain; ARM's own macOS build cannot run
  here.
- Wiring: **DAC0 -> A0**, DAC1 -> A1.
- Remote: `origin` = https://github.com/jerryrt/due_oscilloscope.git,
  push via `gh` credential helper (already configured).
- LEDs: amber = heartbeat; TXL (PA21) flickers with USB IN traffic, RXL
  (PC30) with OUT. Both tracks, same pins, same 50 ms sampling. Track
  A's `u` prints the pin state and `B` prints the activity counters, so
  a dark indicator can be told apart from a pin nothing ever drove.
  **Heartbeat alive with both activity LEDs dark, while a host tool
  sits there making no progress, means the host is stuck in `close()`
  waiting for write URBs the device is not draining** - that is how
  objective 0c was spotted. Confirm with
  `sample <pid> 2 -mayDie | grep close`, then kill the process; the
  board itself is fine.
- Scratch scripts written this session are under the session scratchpad
  and are not part of the repo. Anything worth keeping was folded into
  `host/measure.py` or `tests/`.

## Daemon and front end

```sh
# the daemon: no hardware
python3 -m daemon --fake            # from host/, or PYTHONPATH=host
.venv-ft/bin/python -m daemon       # the real board, free-threaded

# the front end
.venv-gui/bin/python -m gui --spawn-fake    # starts its own fake daemon
.venv-gui/bin/python -m gui                 # a daemon already running

# their tests
.venv/bin/python -m pytest tests/test_daemon_protocol.py \
                          tests/test_daemon_api.py tests/test_jitter.py -q
.venv-gui/bin/python -m pytest tests/test_gui.py -q
```

`docs/daemon-api.md` is the socket reference: framing, the command
catalogue, ownership, backpressure, recording, and what `status`
carries. Two things about it are load-bearing rather than incidental -
`status` never touches the device, and a client that stops reading
loses frames that are counted and reported rather than slowing anyone
down.

## Track A command reference

Same letters, same output. Track A adds `d` (DAC update-rate sweep) and
`j`/`k` (independent-DAC cross-check), which Track B has never had.

Its bulk endpoints run on UOTGHS DMA under the core's enumeration
(`sketches/bringup/usbdma.cpp`). Measured: OUT 19.72 MB/s byte-perfect,
IN 31.10, duplex 15.58; full loop at 200,000 sps each way with under=0
and the tone at the theoretical maximum; full-rate pair (DAC 906,976 +
capture 453,488) with under=0.

`B` reports `spans` and `partial` on both tracks: OUT DMA transfers
armed, and the ones that ended anywhere but on a slot edge. `partial`
must be zero - a stream span is armed to land exactly on a slot
boundary and nothing may end it early, so a non-zero count is the
lost-sample defect or its next relative, and the suite asserts it.
`spans` is also the handle on the starvation in objective 0a: a
starving run arms few large spans, a healthy one many small ones.

Track A's `B` additionally reports `rebuilds`, the number of times the
core rebuilt endpoint configuration out from under the DMA mode. Zero
through a normal run.
Climbing means the link is resetting, which otherwise reads as data
corruption.

```sh
arduino-cli compile --fqbn arduino:sam:arduino_due_x_dbg \
                    --build-property build.f_cpu=78000000L sketches/bringup
arduino-cli upload  --fqbn arduino:sam:arduino_due_x_dbg \
                    -p "$(python3 host/ports.py | awk '/control/{print $3}')" \
                    sketches/bringup
```

The host tools below work against either track unchanged; the wire
format is byte-identical. `loopback.py`'s clock-paced feed is tuned for
the DMA-fed device, so against Track A it simply overruns the plateau -
which is what the underrun counter is for.

## Track B command reference

| Key | Action |
|---|---|
| `h` | banner |
| `r` `s` `x` | read A0/A1, DAC sweep, crosstalk |
| `t` | TC/ADC/PDC trigger-rate sweep |
| `1`..`5` | capture streaming presets, `5` = max in-spec (derived from clock) |
| `=<dac>[,<adc>]` | rate arguments for the next `L` or `P` |
| `L` | full loop: playback + capture (defaults 200 k/200 k) |
| `P` | playback only |
| `0` | stop everything |
| `?` `B` | stream stats; bench + playback counters |
| `F` `R` `X` | transport benchmarks via CPU FIFO: flood IN, sink OUT, duplex |
| `G` `T` `Y` | same three via endpoint DMA (**working**) |
| `V` | dump playback ring + DACC registers |
| `D` | loop diagnostic: 12 snapshots at 150 ms, printed afterwards |
| `M` | mimic loop without USB: gen sine on TIOA1 + capture |
| `u` | dump USB + endpoint + DMA registers |
| `z` | software reset |

## Host tools

```sh
python3 host/ports.py                             # discover both ports
python3 host/loopback.py --seconds 5              # loop test, 200 k defaults
python3 host/loopback.py --dac-sps 906976 --adc-hz 453488   # full-rate pair
python3 host/loopback.py --diag                   # with mid-run firmware snapshots
python3 host/usbbench.py in-dma --seconds 4       # DMA transport benchmarks
python3 host/receive.py --send 5 --seconds 5 --expect-hz 885.72
```

`receive.py --expect-hz` is the gen tone: trigger rate / 512, i.e.
885.72 Hz at the 453,488 Hz max in-spec preset.
