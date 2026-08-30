# Agent Instructions

Working notes for AI agents on this repository. Read `docs/scope.md` and
`docs/architecture.md` before making non-trivial changes, and
`docs/testing.md` before touching the host tools or adding tests.

## What this project is

A 12-bit oscilloscope and signal generator on the Arduino Due
(SAM3X8E, Cortex-M3). The board acquires and generates; the host does
all DSP and visualisation.

**MCK is 78 MHz, not the Due's usual 84** - see "Facts that are easy to
get wrong". Every RC in this project divides 39 MHz. The header used to
say 84 and was quoted from here into two other documents, so correct
this line rather than working around it.

Status: **full loop working, with a front end on it, and a
re-validation debt.** Both tracks stream the ADC's complete in-spec
output gaplessly, and both run host-fed DAC playback with simultaneous
capture (HOST -> DAC0 -> A0 -> HOST) at zero underruns and tone
amplitude at the theoretical maximum. Both move bulk data by UOTGHS
endpoint DMA and reach the full-rate pair; Track A keeps the Arduino
core for enumeration only.

**But "zero underruns" is not the guarantee it reads as.** Until
2026-08-23 the host's USB stack was silently discarding 0.45-0.85% of
what `write()` counted on the playback path, and an underrun counter
stays at zero through exactly that. The feed is fixed - a constant
512-byte write, `Feeder.WRITE_SIZE` - but most figures measured above
200 ksps predate the fix and have not been re-read against byte
conservation. See objective 0h in `docs/HANDOFF.md` before quoting
any of them.

The host side is a daemon that owns the ports (`host/daemon/`) and a Qt
window that draws from it (`gui/`), and both have test suites that need
no board. See `docs/status.md` for numbers, `docs/frontend.md` and
`docs/daemon-api.md` for the host architecture, and `docs/HANDOFF.md`
for the current objectives.

## Ask what the buffer was doing before blaming the transport

Objective 0i - playback underruns at the top of the AWG ladder - was
open across many sessions. It was attributed in turn to feed policy,
write size, scheduling, real-time thread priority, host driver
buffering, and the difference between three operating systems. Two hosts
were characterised in detail. A closed-loop rate feed was designed to
fix it.

The cause was `PLAY_PRIME_BUFS = 4`: the DAC's timer started once four
of thirty-two ring slots held data. At the top rate that is 1.4 ms of
runway. Raising it to 24 takes the underruns to **zero at every rate on
the ladder**, byte conservation untouched, and the ring stops living at
the ENDTX guard - occmin goes from 2 to about 21.

**One constant. The diagnosis that found it took ten minutes.**

Run the same rate for 1 s, 3 s and 9 s. At RC 28 all three produced
21-24 underruns. Nine times the duration, the same count - so it was
never a leak, it was a burst at the start, and only the state of the
ring at t=0 could explain it. Everything downstream of that question was
answered by one grep.

**The lesson, and it generalises past this bug.** A rate-dependent defect
that does not scale with duration is a startup condition. Ask how full
the buffer is when the consumer starts *before* characterising the
producer, the transport, or the operating system - those are expensive
to measure and this is one constant to read. The sessions spent on host
driver behaviour were not wasted (they settled objectives 0c and 0a/0b,
which were real and are macOS's) but they were spent on the wrong
suspect for this.

The cheap question first: **is the count proportional to how long you
ran?**

## Invariants

Violating any of these is a design regression, not a style preference.

1. **The CPU never touches sample data.** PDC writes the buffer, USB DMA
   reads the same buffer. No memcpy, no per-sample loops, no payload
   checksums. If a change makes the CPU read the sample stream, it is
   wrong.
2. **No on-target DSP.** The Cortex-M3 has no FPU. FFT and filtering
   belong on the host.
3. **The two toolchains share no *hardware* source, and are peers in
   everything else.** Track A (arduino-cli) is a reference oracle; Track
   B (CMake + arm-gcc) is the project. Register programming stays
   independent - `usbdma`/`usb_cdc`, `acq`/`adc`/`dac`/`gen`/`play`
   internals, clock, fault - because two independent programmings of the
   same silicon is what makes a behavioural divergence point at one of
   them, and that is the whole value of the oracle.

   **The wire contract is shared source, and this rule used to say
   otherwise.** It read "share no source", full stop, and that
   over-reached: the argument above is about registers and does not
   transfer to a frame layout or a CRC. Two hand-copies written from the
   same `docs/control-protocol.md` by the same author are not
   independent - they are two homes for one misreading, plus drift.

   It is rescoped on evidence, not taste. The tracks were already
   sharing protocol source by hand-copying it, and it had already gone
   wrong twice: Track A's `frame.h` was missing `frame_crc32_update`,
   the one form the control protocol needs; and `FW_VERSION_STR` said
   0.1.0 while `FW_VERSION_MAJOR/MINOR/PATCH` said 0.2.0 - identically
   on both tracks, reaching different consumers, so one board answered
   "which firmware are you" two ways. Copying kept them in perfect
   agreement at the wrong value.

   What is shared lives in `lib/due_shared/src` and both builds compile
   it: the frame and playback-status layouts, the CRC, the control
   protocol's wire format and its whole parser, the console surface,
   and the stream framer (`stream_core.c` behind `stream_port.h`, whose
   seam a test holds equal to extraction - issue #14). `FW_TRACK` is the only
   thing left with a copy per track. **The oracle for the wire is the
   host, not the other track** - `host/control.py` and the suite parse
   it with no idea which track emitted it, which is the independence
   that actually catches a protocol bug. Full reasoning and the phases
   in `docs/shared-source.md`.

   **Per-track capabilities.** Sharing the parser is what showed that
   two opcodes - STREAM_STATS and BENCH - carry Track B's own USB stack
   counters and are not universal protocol. A track that does not
   implement an opcode answers `CTL_ERR_OPCODE`, **never a body of
   zeroes**: zero is a measurement, and a host cannot otherwise tell it
   from "not counted here".

   But they must be comparable in **design, feature set and
   performance**. Both are bare-metal on the same silicon; Arduino is an
   abstraction layer, not a different architecture, and nothing it
   provides prevents reaching the same registers. So a capability on one
   track and not the other is **debt with a date on it**, never a
   property of the track - and "the core will not let us" is a claim to
   be tested against `platform.txt` before it is believed. It has been
   wrong once already: objective 1b recorded for weeks that the Arduino
   linker could not place a buffer in SRAM bank 1, when `sram1` is
   declared in the stock `flash.ld` and `build.ldscript` is an ordinary
   build property. Tested on 2026-08-25, it took an afternoon, and
   Track A now pins its capture ring exactly as Track B does.

   From 2026-08-25 this is a gate, not an aspiration: **Track A is
   brought level before front-end work continues.**
4. **`drivers/` stays RTOS-agnostic.** Bare-metal and FreeRTOS builds
   link identical driver code and differ only in `main()`.
5. **Never present discontinuous data as continuous.** Overruns are
   counted and flagged in the frame header. A silent splice becomes
   corrupted data that gets mistaken for a real signal.
6. **Never printf from an ISR.** Ring-buffer and drain outside the
   real-time path. A printf costs ~3.5 ms against a 0.95 us conversion.
7. **Constant memory and constant time, everywhere on the working path.**
   This is bare metal: every buffer is fixed and known at build time,
   and every ISR and every main-loop pass has a bounded worst case that
   does not depend on what a host chose to send. No allocation, no
   unbounded loop, no "process everything that arrived" - a peer that
   floods an endpoint must cost a bounded slice of one pass and no
   more, because the alternative is a main loop that stops draining and
   a host wedged in `close()`.

   The shape that follows from it: **an ISR notices, the main loop
   acts.** An interrupt or DMA completion sets a flag and returns;
   parsing, checksums and replies happen in the loop where they can be
   bounded and preempted. Building one control response is a CRC32 over
   464 bytes and has no business above a 0.95 us conversion cadence.

   Only debug-only features may break this rule, and they must be
   unreachable on the deployed path. `Q`, `l`, the sweeps and the
   printf diagnostics are all in that class.
8. **printf is a debug method, not an instrument.** It is too expensive
   to use for profiling or for status polling while the board is
   working, and not by a small margin: measured with the load monitor,
   one console status command blocks the main loop for 13-20 ms (`B`
   13.14, `?` 21.48, `O` 15.40), `u` for 113 ms and the banner for
   89 ms. For every one of those milliseconds the loop drains no bulk
   OUT, which is the NAKing pipe that hangs macOS in `close()` - see
   objective 0c, where console polling during playback turned out to be
   a participant in the wedge rather than a witness to it. Twenty
   `GET_LOAD` queries over the control channel cost 0.29 ms *in total*.
   **New instrumentation goes in the metric system** (`bsp/load.c`,
   `GET_LOAD`), never in a printf, and anything read while the sample
   path is running goes over the control channel.

   The `?` figure was 20.18 ms until the ADC_MR readback landed on it on
   2026-08-26. The raw register costs 1.3 ms of UART; decoding its two
   fields on the device cost 3.8, which is why the host decodes and the
   device prints the word. **The cost of a console command is the bytes
   it puts on the wire, not the number of `printf` calls** - which is
   not what "share an existing printf to keep it free" predicts, and
   that guess was wrong when it was measured. Re-measured with `l`,
   which reproduces the `B` and `O` figures above to 0.2%.

## Facts that are easy to get wrong

Check here before reasoning from general Arduino knowledge.

- **One ADC, not twelve.** A single converter behind a 16:1 multiplexer.
  Channels sample round-robin, so channel count *divides* the aggregate:
  ~907 ksps at MCK 78 (RC 86). Twelve channels means ~75 ksps each, not
  12 Msps. One channel alone reaches only 886,363 sps (RC 44), *less*
  than the two-channel aggregate - a multi-channel trigger converts back
  to back and amortises overhead a lone conversion pays in full. The
  per-channel-count floors are measured, never scaled.
- **Aggregate data rate is ~1.81 MB/s regardless of channel count.**
  More channels cost per-channel rate, not USB bandwidth.
- **That figure is capture alone, and playback is not free on top of
  it.** Measured on `windows-desk` 2026-08-30 with the ADC trigger held
  at 402,061 Hz on two channels - 1.61 MB/s inbound, unchanged in every
  row - and only the outbound DAC feed varied:

  | DAC feed | total | device overruns |
  |---|---|---|
  | none | 1.61 MB/s | 3 at start, **no growth** |
  | 50 ksps | 1.71 MB/s | ~1 per second |
  | 100 ksps | 1.81 MB/s | ~5-6 per second |
  | 200 ksps | 2.01 MB/s | ~17 per second |

  The converter was doing identical work throughout, and the daemon's
  own read-gap maximum was 16,000 us in every row, so the host reader
  was not more starved either. **Loss appears at 1.71 MB/s combined,
  below the 1.81 the capture-only figure would let you predict**, and
  climbs steeply after. So do not size a duplex design by subtracting
  the playback rate from 1.81: full duplex costs more than the sum of
  its directions, by an amount that has not been characterised beyond
  these four points. `records/issue41-windows-duplex.jsonl`.

  Not reachable from the front end, which pins loop mode at 200 kHz
  where both arms are clean. It is reachable from the daemon API.
- **Not simultaneous sampling.** Consecutive conversions are ~0.95 us
  apart; channel skew is real and must be corrected host-side.
- **The DAC is not rail-to-rail.** Output spans roughly 0.55–2.75 V.
  Writing zero does not give ground.
- **A trace that shakes horizontally on the bench scope is the trigger,
  not the board.** About 20 mV RMS sits on DAC0 - 15 mV of it with the
  DAC not driven at all - and a scope turns that into time jitter by
  dividing it by the waveform's slew rate at the trigger level. So
  square does not shake (full-scale step), sine shakes a little
  (~45 mV/us), and the ramp shakes 30-60x worse than sine because its
  staircase rises **4.5 mV per sample**. Measured across a 12x span of
  jitter, `sd x slew` is constant at ~20 mV. Do not chase this in the
  feed, the ring or the transport - underruns were 0 on every shaky
  row, and the internal generator with no USB in the path shakes
  identically. `docs/awg.md`.
- **The GUI shakes for an unrelated reason and the two must not be
  confused.** `gui/app.py` draws the most recent N samples every 33 ms
  with **no trigger at all**, so a trace holds still only when
  `rate/tone` divides the frame's samples-per-channel. That is a missing
  front-end feature, not a signal defect.
- **The DAC tops out around 750 kHz of toggling, and stops being a
  square long before that.** Measured with `=3J` (solo: every table
  entry tagged DAC0, no sync, double rate) on TIOA1: ask for 1,000,000
  Hz and 749,000 arrives; ask for 1,500,000 and 746,000 arrives. Full
  amplitude survives only to **~400-450 kHz**, and a *recognisable
  square* only to ~100-200 kHz - at 407 kHz Vpp is still 100% and the
  waveform is already a trapezoid with no flat top. "Amplitude fell to
  68%" and "the square became a triangle" are the same number and
  different findings; quote the one that matches what the output is
  for. `docs/awg.md`.
- **Playback does not deliver every rate it accepts, and the affected
  band is wide.** Between roughly **812,500 and 1,218,750 sps** the DACC
  converts *below* the rate it was programmed for - persistently in the
  interior (RC 34/36/39/44, ratios 0.977-0.984) and intermittently at
  the two edges (RC 32 at exactly 15/16, RC 48 at 0.9686). Outside the
  band - RC 28, 30, 52, 56 - it delivers in full. Measured device-side
  from `consumed / run_us` with no host clock in it, on **two tracks**
  (Track A 2/24 against Track B 7/32, p = 0.16, so it is the silicon and
  not one track's register programming) and **two hosts**.

  **The data path is not involved.** The same deficit appears with the
  device's own table and no USB at all - preset M, DAC on TIOA1, read as
  the generator's output frequency: 0.97640 against playback's 0.97653
  at 1,000,000 sps, 0.98440 against 0.98428 at 886,363, and 1.00000 at
  two clean rates. So bulk OUT, the endpoint DMA, the ring,
  `PLAY_PRIME_BUFS` and the PDC hand-off are all excluded, and no
  host-side change can move the band.

  It is `DACC_MR_REFRESH`: setting it to 2 or 3 clears every affected
  rate, restoring 1 brings them all back, p = 3.3e-11 across the ladder.
  The ripple that refresh defends against is **0.22 codes = 0.18 mV**,
  and during playback the sample stream rewrites the DAC 18-37x more
  often than refresh does, so while streaming refresh protects nothing.
  The mechanism is **not** explained; four candidate models are dead on
  issue #48, all of them measured rather than argued away.

  **What this costs you:** `OVERSUPPLIED = {44, 39}` in
  `tests/test_integrity.py` is this, and so is the macOS "byte loss" at
  those rates - a host that buffers ahead sheds the surplus it wrote for
  a converter that could not take it, while Windows applies backpressure
  and simply feeds less. **Do not size anything against a nominal
  playback rate in that band**, and do not read a byte deficit there as
  loss. `docs/awg.md`.

- **The generator's 113 kHz ceiling is the ADC's, not the DAC's.** Every
  ordinary path triggers the DACC from TIOA0 so generation and capture
  stay phase-coherent, and TIOA0 is capped by `ACQ_MIN_RC` = 86 at
  453,488 Hz; TAG halves it again. `=<dac>M` selects TIOA1 instead and
  reaches **~357 kHz of square, measured** - and past the DACC's
  1,392,857 updates/s the frequency **pins at 375 kHz** while Vpp stays
  at 97-100%, which is the converter saturating rather than the
  amplitude failing. Four ceilings, all different, in `docs/awg.md`; do
  not size a design against the wrong one.
- **DAC1 is the bench trigger now, and DAC0 is the signal.** `=<n>J`
  puts a full-scale square on whichever DAC pin is not carrying the
  waveform, phase-locked by construction - one PDC stream, one trigger,
  so it lags the waveform by exactly one trigger period and by nothing
  else. Measured against triggering on the signal: sine **222x** less
  jitter, ramp 2.2x. It is also a *better* demux check than the old DC
  level, because a flat line is what an unwritten channel looks like and
  a square is not. **DSO tools measure CH1 = DAC0 only**; DAC1 is not on
  an analog channel any more, so the ADC (A1) is the instrument that can
  still see it.
- **Two EXT-trigger traps on the DS1102E, and both are silent.** The
  level clamps at **±1.2 V** - it accepts `1.67` and holds `1.20`, with
  the readback agreeing - so a DC-coupled x1 sync never triggers at all.
  And the probe ratio moves the usable window, which is only ~100 mV
  wide: with x10 fitted it is 0.1-0.2 V DC or 0.0-0.1 V AC, and a sweep
  at 0.0/0.3/0.6/1.0/1.2 steps over it and concludes EXT is broken.
  **Discover the level, never assume it** -
  `scope.Oscilloscope.ext_trigger_autoset()`. `None` means no signal is
  arriving, which is a cable fault.
- **A third silent DS1102E trap: the vertical offset clamps at ±2 V**
  once the gain is 250 mV/div or finer. Ask for -2.814 V at 5 mV/div and
  the instrument holds -2.000, 163 divisions out, and hands back a
  record that is entirely rail while every command succeeds. It cost a
  118 µs "settling tail" that was reproducible to the sample across
  three runs, because a rail is reproducible and the trigger sits at a
  fixed position in the record. `scope._apply()` returns what the
  instrument actually holds - "quantised, or clamped" is in its own
  docstring - so **check the readback against the request**, and read
  min/max off a long record with suspicion: one stray sample above a
  rail defeated the filter written to catch exactly this.

- **Fold to phase before calling anything jitter.** "The crossing
  nearest screen centre" flips between adjacent cycles whenever the
  trigger's phase differs from the crossing's, and reports ~100% of a
  period on a trace that is perfectly still. Circular statistics on the
  folded phase; measured, and it was wrong once here.
- **There are two generators and only one of them is arbitrary.** The
  host streams samples over USB (`build_selected`, `run_play`); the
  device also plays its own 256-point table with no USB in the path
  (`drivers/gen.c`, `sketches/bringup/gen.cpp`, `=<shape>,<pts>W`).
  Resolution is the internal generator's *frequency* knob -
  `f = trigger_hz / (2 * points)` - and points must be a power of two
  from 2 to 256 or a cycle straddles the PDC wrap. Changing it also
  changes the period the issue-#5 fold instruments must use; see
  `measure.gen_fold_len()`. `docs/awg.md`.
- **The native port already runs at High Speed.** Verified: `Device
  Speed` = 2, `bcdUSB` = 0x0200. There is nothing to enable. Throughput
  limits live in the CDC-ACM stack, not the PHY.
- **Nothing is 5 V tolerant.** No clamps, no series resistors, no
  protection of any kind.
- **Three version numbers, and none substitutes for another.**
  `FRAME_VERSION` (`frame.h`) is the sample-stream wire format,
  `CTL_VERSION` (`ctl.h`) the control-channel wire format, and
  `FW_VERSION_*` (`version.h`, one byte-identical copy per track) says
  which build is on the board when both contracts are unchanged. A host
  *refuses a pairing* on the first two and *reports* the third. Bumping
  `CTL_VERSION` is a hard break by design: the device rejects a frame
  whose version is not its own, so a mismatched host fails on the first
  exchange rather than misparsing every one after it.
- **Ask a board what it is with `v`, not with the banner.** Both tracks
  emit one identity line in one fixed format - `# id: track=B fw=0.1.0
  ctlver=2 framever=3 mck=... build=...` - and `measure.parse_identity`
  reads it. `ctlver=0` means "this track has no control channel", and
  **no track reports it any more**: Track A gained one on 2026-08-27 and
  reports `ctlver=3`, the same as Track B, because both run the same
  parser out of `lib/due_shared`. What still differs is which *opcodes*
  a track implements - an unimplemented one answers `CTL_ERR_OPCODE`
  rather than a body of zeroes. See `docs/shared-source.md`. The banner says the track only in prose and costs
  89 ms of blocked main loop; matching `"Track A"` in a paragraph is the
  old fallback and is kept only for images built before `v` existed. On
  a deployed board - native port only - the answer comes from the
  control channel's `IDENTITY`, which carries the same fields.
- **The stock Due `ram` region includes SRAM bank 1.** `flash.ld`
  declares `ram` as 0x20070000 length 0x18000 - all 96 KB - *and*
  `sram1` as 0x20080000 length 0x8000, the same 32 KB a second time. So
  `.bss` grows straight into any buffer pinned to bank 1, with no
  diagnostic, and the stack top is inside bank 1 as well. Anything
  placing a DMA buffer there under the Arduino core must shrink `ram` to
  bank 0 first; `linker/arduino_due_x_sram1.ld` does, and moves the
  stack to the top of bank 0 with it. Bank-0 space is then 64 KB for
  everything, which the sketch fits in with ~9 KB left for stack and
  heap.
- **Cortex-M3 has no data cache**, so DMA buffers need no cache
  maintenance. Advice written for Cortex-M7 parts does not apply.
- **Any write to `UOTGHS_DEVEPTCFG` re-allocates that endpoint's DPRAM.**
  There is no such thing as a harmless one: the `ALLOC` bit is in the
  same register, so changing AUTOSW rewrites it, and datasheet 40.5.1.6
  says the x+1 window then slides up and loses its data while x+2 and
  above stay where they are. Note 3 permits it when the configuration is
  unchanged - but only "as far as nothing has been written or received
  into" the higher endpoints while it happens. So: never rewrite an
  endpoint's configuration while an endpoint above it is in use, and
  re-allocate the ones above afterwards. This was inert while EP3 was
  the last endpoint and became a wedge the day EP4-EP6 appeared.
- **Pin 13 is PB27** and carries no SPI conflict on the Due.
- **MCK is 78 MHz here, not 84.** Chosen so the ADC clock is 19.5 MHz,
  inside the 20 MHz datasheet limit. Costs 7.2% of sample rate. Track A
  must be built with `--build-property build.f_cpu=78000000L` or
  `micros()` is silently wrong.
- **`A0` is ADC channel 7, not 0.** The Arduino A0..A7 labels map to
  AD7..AD0, descending. A8..A11 then map to AD10..AD13 ascending. Code
  assuming `A0 == AD0` reads the wrong pin, and sequencer conversion
  order follows channel index, so it is not label order either.
- **`DAC0`/`DAC1` pins have no ADC channel.** Arduino's `variant.cpp`
  lists `ADC12`/`ADC13` against them, which is misleading; the device
  header assigns those to PB19/PB20 (A10/A11). Trust the CMSIS device
  header over the Arduino variant table.
- **The Arduino CDC stack does not use DMA.** `UDD_Send()` copies into
  the endpoint FIFO a byte at a time and spins on `TXINI`, and the RX
  ISR does the same in reverse. `SerialUSB` therefore cannot carry the
  sample path without breaking invariant 1. Endpoints are already
  512-byte and 2-bank, so there is nothing to tune there either.
  Verified from core source; see `docs/hardware.md`. **Track A no longer
  routes samples through it, in either direction**:
  `sketches/bringup/usbdma.cpp` takes the two bulk endpoints away from
  the core and programs the UOTGHS DMA channels, leaving enumeration and
  control transfers with the core. The fact above is why that file
  exists, not a description of what Track A does now.
- **macOS's CDC-ACM output path discards bytes `write()` has counted**,
  silently, with every counter on both sides green. Two separate
  behaviours, and both are measured:
  - **Under pressure** it drops ~128-byte chunks. Never free-run writes
    into saturation.
  - **Regardless of pressure**, it loses 0.45-0.85% at every rate above
    200 ksps unless every `write()` is *the same size*. A constant 512
    bytes is lossless; "whatever is due" is not, even when every write
    it emits is 512 or 1024. The mechanism is unknown; the measurement
    is not. `Feeder.WRITE_SIZE`. Re-taken 2026-08-29 and current -
    0.605-0.633% at 397,959 sps, 0.763-0.915% at 600,000 - and it also
    costs runway, 7-12 underruns against 0. **Windows has none of it**,
    0 B on both arms at every rate, so this bullet is macOS's alone.

  The safe feed is therefore: constant-size writes, clock-paced, with a
  bounded lead against the DMA-fed ring, sleeping until the next write
  is due rather than on a fixed tick. Against a manual-FIFO device the
  old empty-queue gate applies instead. **A byte comparison against the
  device proves nothing without draining the pipeline first** - 55 to
  450 KB sits in the CDC driver below the tty layer. See `docs/usb.md`.
- **A CDC device must keep draining bulk OUT even when nothing uses
  it.** The main loop drains and discards OUT when no consumer owns it -
  do not remove that, and do not slow it down either: gating it to 1 kHz
  narrows the drain to ~2 MB/s against a host that writes ~1.8 MB/s, and
  the margin *is* the guarantee.

  **But the explanation attached to this rule is wrong, and the
  correction matters more than the rule.** It used to say macOS hangs in
  `close()` because a NAKing pipe never completes its write URBs. That
  was never measured, because the process that wedges holds both ports.
  Read over the control channel during an actual wedge, the device is
  running its main loop at 143 k passes/s and taking the drain branch on
  **every one of them**, with both banks free and nothing pending. It is
  draining an empty pipe as fast as the hardware allows while the host
  sits in `close()`. Objective 0c is host-side; stop attributing it to
  the device.
- **A wedged `close()` is recoverable in software - do not pull the
  cable.** The host is waiting on the USB pipe, and only a disconnect
  aborts that. `=<ms>Z` on the console detaches the native port and
  re-attaches it, which released a wedged close in 0.01-0.23 s on 9 of 9
  attempts. Command it from the *programming* port: detaching takes the
  control channel down with it. `z` is no substitute - that is
  `RSTC_CR_PROCRST`, a processor reset that leaves the USB pull-up
  attached and the host none the wiser, and twenty seconds of it changed
  nothing. `measure.close_native` tries this automatically before giving
  up, so a wedge costs a re-enumeration rather than the session.
- **A host that closes the port without stopping playback used to strand
  the device.** The drain guard is `!play_active() && !stream_out_in_use()`,
  and playback stayed "active" for ever with its OUT DMA armed for bytes
  nobody would send. Playback now stops itself after 500 ms with no byte
  arriving (`play_abandoned` counts it), which also changes AWG
  behaviour: a starved feed used to hold its last buffer indefinitely.
- **There is no CPU pinning on macOS.** Predictable host-side streaming
  comes from the QoS class plus the Mach time-constraint band, wrapped
  in `host/rt.py`.

## Platform tiers

| Tier | Platform | Standard |
|---|---|---|
| **1** | **Windows** | Develop, test and deploy. 100% correctness; a failure here is a bug to fix, not a platform quirk to document |
| **1** | native Linux | Bench `linux-x1`, board attached 2026-08-29. Track B suite 505 passed / 1 context-only failure; byte conservation 0 B in 40 runs at five rates; `rt.py` promotes natively. `docs/linux.md` |
| **2** | macOS | Porting target. May compromise where the OS forces it, and does. **Also the provenance of every figure in `docs/status.md` until the 0-series is re-taken** |
| **2** | WSL2 | Porting target for the *software* path only. Real Linux kernel, but no native USB - see below |

That second row carries two things and they pull in opposite directions.
macOS is where the project may compromise *going forward*, and it is
where essentially everything already measured was measured. "Tier 2, may
compromise" is a statement about which host to trust for new numbers -
it is **not** licence to discount the existing record, which is the only
record there is for most of the 0-series. Re-take a figure before
disbelieving it.

macOS's CDC-ACM stack silently discards bytes `write()` has counted, in
two separate measured ways, and that defect has been the subject of most
of the last several sessions. So the project was written on macOS and
macOS is now the one that has to keep up.

**The Windows run is in `docs/windows.md` and it settles two objectives
at once.** Objective 0c does not reproduce there - 0 wedges in 52 cycles
across two reproducers, against 9 in 30 on macOS - and neither does the
playback byte loss: 0 B lost at every rate from 200,000 to 1,392,857
sps, including the two that lose most here. Both are the same driver
behaviour, because a stack that applies backpressure to the writer
cannot silently discard. Do not attribute either to the device. A
macOS-only failure is a tier-2 compromise to record, not a defect to
chase in the firmware.

It confirms objective 0i rather than dismissing it. RC 44 and RC 39 run
1.6% slow on Windows too, by the device's own `runus`, so the slow
converter is genuinely the device's; Windows simply never oversupplies
it.

Nothing else in this file is invalidated. Everything measured here was
measured on macOS and stays true of macOS; what changes is which host's
numbers are the project's numbers. Re-taking the 0-series in
`docs/HANDOFF.md` comes before building on top of it.

**`Feeder.WRITE_SIZE` is settled, and it is a macOS workaround.** Both
benches ran `tools/writepolicy.py` on 2026-08-29, four runs per arm per
rate, ABBA within each rate. macOS due-sized writes lose 0.605-0.633% at
397,959 sps and 0.763-0.915% at 600,000 while constant-size loses 0 B in
every run; Windows loses **0 B in all 24 runs, both arms, every rate**,
because its driver blocks the writer instead of counting bytes it will
shed. So the constant-size rule is a tier-2 platform rule, the honest
high-rate byte-conservation figures are the Windows ones, and the
constant that enforces it lives in `measure.py` - above the seam the
next paragraph says all platform difference belongs in.

**All platform difference lives in `host/transport.py` and
`host/rt.py`.** Everything above them - `measure.py`, the daemon, the
front end, `tests/` - is written once. If a change needs to know the OS
anywhere else, that is the seam failing and the fix belongs in the seam.
The rule governs *branching*, not caution: a uniform conservative
policy motivated by one platform's defect may live above the seam -
`Feeder.WRITE_SIZE` is the standing, labelled example (issue #27), kept
uniform because it is measured free on the platforms that do not need
it and one feed policy keeps a feed bug reproducible on both. The
moment such a policy wants a `sys.platform` test, it moves down.
`host/` is no longer stdlib-only: it takes pyserial, which is declared
in `requirements-dev.txt`. The old rule was always "a fact about the
code, not a rule new code inherits".

### WSL2 is tier 2, and only for the software path

WSL2 runs a **real Linux kernel** (5.15.153.1-microsoft-standard-WSL2) in
a light VM - not emulation - so syscall semantics, glibc and Python are
genuinely Linux. That makes it useful, and it has already earned its
keep: it is where `rt.promote()`'s `SCHED_FIFO` path ran for the first
time anywhere, and where the `accept()` teardown bug was found.

**What it cannot do is measure this project.** WSL2 has no native USB
passthrough. A device reaches it only through `usbipd-win`, which
detaches the device on the Windows side and tunnels every URB over TCP
to `vhci-hcd` inside the VM:

    native Linux   app -> cdc_acm -> usbcore -> xHCI -> wire
    WSL2 + usbipd  app -> cdc_acm -> usbcore -> vhci-hcd -> TCP
                       -> usbipd-win -> Windows USB stack -> xHCI -> wire

`cdc_acm` is real and you get a real `/dev/ttyACM0`. What is not real is
what sits under it, and it changes precisely the properties this project
exists to measure:

- **Buffering and backpressure.** The central finding here is "macOS
  buffers 55-450 KB and discards; Windows applies backpressure". usbip
  inserts another queue between `cdc_acm` and the wire.
- **Throughput.** URBs serialise over one TCP connection, so the 30-48
  MB/s figures would measure usbip's ceiling rather than the device's.
- **Underruns and jitter.** Completion timing crosses two schedulers and
  a socket.
- **Objective 0c.** "Does `close()` hang on outstanding write URBs" would
  be testing `vhci`'s URB cancellation, not native `cdc_acm` + xHCI.

So: **valid on WSL2** - port discovery, frame parsing, header CRC,
sequence continuity, command round-trips, the daemon, the whole
board-free suite. **Not valid** - any throughput, underrun, byte-margin
or `close()` figure.

**And the trap worth naming.** A usbip-induced dropout looks exactly like
a device fault. Proving the firmware innocent of a host defect is what
most of the last several sessions went into; a tunnel that manufactures
the same symptoms is worth using only with that written down first.

**Measured, and the four bullets above were mostly wrong.** The
experiment was run - both Due devices attached to WSL2 through usbipd,
the same `bench.py` against the same board, minutes apart. Throughput is
*not* degraded (out 37.25 vs 37.3-37.9 MB/s; in 30-32 vs 30-33), byte
conservation holds at every rate, and underruns are **lower** through the
tunnel than natively on Windows - median 0 against 6 at RC 44, 0 against
8 at RC 39.

The tunnel is itself a queue in front of the device, and a queue is what
the playback ring wants. So a usbip figure is still not a Linux figure,
but the error is **optimistic, not pessimistic** - which is the worse
trap, because a host that looks good through a tunnel invites the
conclusion that it is good. "Linux buffers ahead without discarding" and
"usbip supplies the elasticity" predict the same numbers, and only a
native host separates them. Full data in `docs/windows.md`.

**A native host has now separated them, and the tunnel was innocent.**
`linux-x1` reads median **0 underruns at both RC 44 and RC 39** with no
tunnel in the path - the same as WSL2, against native Windows' 6 and 8.
The elasticity is Linux's own. That does not prove usbip contributes
nothing, and the kernels differ, but it removes the reason to suspect
it: native Linux reaches 0 unaided, so no tunnel is needed to explain 0.
Byte conservation is 0 B in all 40 runs at five rates, both write
policies. `docs/linux.md`.

Stability, not fidelity, is the real defect: the tunnel dropped twice
unprompted (`vhci_hcd: connection closed`) and needed a manual
re-attach.

Native Linux is **tier 1 and no longer deferred** as of 2026-08-29:
`linux-x1` has a board on it, and `transport.py`'s POSIX backend and
`rt.py`'s `SCHED_FIFO` path are now exercised natively rather than only
under WSL2. A WSL2 pass still does not stand in for a native one - the
stability defect above is the tunnel's and has not been seen here.

Bringing it up found one real defect in `tools/flash.py`, and it is not
Linux-specific in principle: `touch_1200()` left the programming port at
1200 baud, so `restore_115200()` - the function written to stop the next
open re-triggering the 16U2 - was itself that open. It runs after the
boot check, so flash.py reported success and left an erased board with
the GPNVM boot bit clear, 3 of 3 against a 2 of 2 no-open control.
`touch_1200()` now restores the speed on the fd it already holds.

The diagnostic trap around it is worth knowing anywhere: **a clear GPNVM
boot bit imitates dead firmware exactly** - silent console, native port
that will not enumerate, SAM-BA on every reset. `bossac -i` prints
`Boot Flash:` in one line. Read it before theorising; two mechanisms were
invented here before anyone did, and one of them was committed.
`docs/linux.md`.

## Ports on the development host

| Role | Path (example, changes with topology) | Notes |
|---|---|---|
| Flash + control + debug | `/dev/cu.usbmodem14201` | Programming port, Full Speed. Development only |
| Sample data | `/dev/cu.usbmodemB_011` | Native port, High Speed; Track B's stack reports serial `B-01` |
| Commands | `/dev/cu.usbmodemB_013` | Native port, second CDC function. **Track B only**, and nothing speaks over it yet |

**The native port is two device nodes, not one** (Track B). It presents
two CDC functions on one cable so that a deployed board needs no second
cable, and they are told apart by USB interface number - 0 and 1 carry
samples, 2 and 3 carry commands, pinned in `docs/control-protocol.md`.
Do not pick one by position: `ports.find_all_ports()` returns all three
nodes and `ports.native_order()` is the rule. Track A still has one.

Paths are enumeration-dependent and change whenever a cable moves; the
table is an example, not a reference. Discover with
`python3 host/ports.py`, which identifies the programming port by the
fact that it answers and the native pair by asking IOKit. Always
`/dev/cu.*`, never `/dev/tty.*`. Opening the control port resets the
board over NRSTB and re-enumerates the native port, so open control
first and re-glob the native nodes after.

## Do not invent numbers

Several figures remain unmeasured and are listed under "Open questions"
in `docs/scope.md` — most importantly **sustained USB throughput**, which
determines whether continuous capture is viable at all.

If a figure is not verified, say so. Do not supply a plausible-sounding
value. A guessed number that later reads as established fact is the most
expensive kind of error in this project, because designs get sized
against it and the resulting failure looks like an analog problem.

Mark uncertain figures *(check)* in documentation, matching the existing
convention in `docs/hardware.md`.

## Working alongside other agents

**You are not the only one in this repository.** Several agents work it
at once, on different machines and different benches, and they push to
the same `main` while you are mid-task. Assume `origin/main` has moved
since you last looked, because it usually has.

**There are two channels and they carry different things.**

| channel | what belongs in it |
|---|---|
| **git** | what changed and why. A commit body is where a finding *lives* - the measurement, the number, the hypothesis that died. `docs/` on `main` is where it survives the branch that produced it |
| **issues** | discussion. Anything that needs another party: a question, a proposal, dividing work so two people do not build the same thing, a measurement only their bench can take, a disagreement about method |

The split matters because they decay differently. A commit message is
read by whoever runs `git log` on that file in six months; an issue is
read by whoever is working *now*. Putting a finding only in an issue
loses it, and putting a coordination question only in a commit means
nobody answers it.

**Use issues for the things a commit cannot do.** Two examples from this
repository, both of which changed what got built:

- **#5** is a measurement dialogue across two boards and two hosts. One
  side's `all-DC` arm read null and the other's did not; the exchange
  ran for days, several hypotheses died in it, and the conclusion - that
  it was the *image*, not the board or the wiring - came out of one side
  proposing a test and the other running a cheaper one.
- **#6** splits a plan two agents had arrived at independently, so that
  the mechanical half and the analog half were not both built twice.

**Mechanics that follow from working in parallel.**

- **Pull before you branch and again before you commit.** A rebase onto
  a moved `origin/main` is routine here; a merge conflict you could have
  avoided by fetching is not.
- **Keep branches short-lived and single-purpose**, which the Branches
  section already requires - it matters more when someone else is
  pushing to the same file.
- **Notice what another agent is actively editing.** If a file is moving
  under you, say so in an issue rather than racing it. This is why
  printf stage 3 was deferred while the generator work was in flight:
  poisoning `printf` touches every driver, and the other agent was in
  those files.
- **Check the issues every time you push or pull.** Not once a session.
  A push is exactly the moment someone else's work has just become
  relevant to yours, and a pull is exactly the moment theirs landed on
  top of it - #6 was opened nineteen minutes before a push that
  answered half of it, and neither side knew until someone looked.
- **Silence is not agreement.** An unanswered issue means nobody has
  read it yet. If you offered to take something and got no reply, watch
  what they push - starting `host/provenance.py` was how one agent said
  "I have this" without answering.
- **Fix what you find in their work, and say so plainly.** A misleading
  diagnostic or a stale claim is worth a small commit and a note; it is
  not worth waiting for permission. Do not rewrite the shape of
  something they are actively building.

**Say which bench a number came from.** There is more than one, and they
differ - this one has DAC1 wired to A1, the DSO bench has it on the
scope's external trigger. `docs/HANDOFF.md`'s status table carries both.
A figure without its bench is not comparable with anything.

## Branches

**`main` is the branch, and every other branch is short-lived: used and
discarded.** Branch from current `main`, carry one change, land it, and
delete the branch locally and on the remote in the same breath. Leave
the working tree on `main` when you stop. Full rule in
`CONTRIBUTING.md`.

This is a rule here rather than a preference because a stale branch on
this project misleads in two specific ways, neither visible from inside
it. The binary selects which state issue #5 draws, so a branch that has
drifted is running different firmware *and* a different draw of an open
defect, and anything measured on it compares two things at once. And the
instruments move: `wip/track-a-control-channel` sat long enough that its
recorded "160 passed / 88 failed" had been taken with a `measure.py`
that no longer existed, so the number meant nothing by the time it was
read. **Findings belong on `main` in `docs/`, not on the branch that
produced them** - a branch is thrown away and a diagnosis should not be.

`wip/track-a-control-channel` was the one exception that predated the
rule. It landed on 2026-08-26 and is deleted, locally and on the remote.
There is no standing exception now, and the rule cost it nothing: the
diagnosis that made it mergeable was written to `docs/` on `main` before
the branch was merged, so it survives the branch.


## Commits

Linux kernel style, enforced. See `CONTRIBUTING.md`.

```
subsystem: imperative summary, no trailing period

Body at 72 columns explaining why, not how.

Signed-off-by: Jerry Tian <jerryrt@gmail.com>
```

Subsystem prefixes: `doc`, `build`, `bsp`, `adc`, `dac`, `tc`, `usb`,
`rtos`, `host`, `sketch`, `tools`.

One logical change per commit. Every commit should build.

## Build

Both tracks work. **Ask `tools/toolchain.py` where the tools are; do
not assume `PATH`.** `toolchains.json` resolves `arm-none-eabi-gcc`,
`bossac`, `arduino-cli`, `cmake` and `ninja` by pattern, and on Windows
none of them is on `PATH`: cmake and ninja come from the copies bundled
with Visual Studio, `arduino-cli` from inside the Arduino IDE
installation, and the ARM toolchain from wherever it was unpacked. On
macOS `~/.local/bin` holds `arduino-cli` and `cmake`, which is what this
line used to say without saying it was one platform's arrangement.

That mattered on 2026-08-30: an agent on `windows-desk` checked `PATH`,
guessed a couple of install directories, concluded `arduino-cli` was
absent, and told another bench that this bench could not build Track A -
which took it off a two-track firmware fix on a false premise. Both
tracks build there and `docs/windows.md` already said so.

**Every build is a full build, and it is enforced rather than
remembered.** `CMakeLists.txt`'s `enforce_clean_build` target cleans
before every build of the firmware, and `tools/sketch.py` passes
`--clean` to arduino-cli; `tests/test_clean_build.py` fails if either is
removed or if a third build path appears. The cost is 0.6 s for Track B
and 2.2 s for Track A against measurement runs of nine minutes to eight
hours - and an incremental build has already shipped a mixed-revision
image here, where the capability word carried a new bit and the
capability *report* did not, because that table sat in the file the
cache reused. Nothing in the output said so; the only tell was 8 bytes
of flash.

```sh
# Track B: bare metal
cmake -B build -DCMAKE_TOOLCHAIN_FILE=cmake/arm-none-eabi-toolchain.cmake \
      -DCMAKE_BUILD_TYPE=Release
cmake --build build -j
tools/flash.sh build/baremetal_bringup.bin

# Track A: reference oracle. Use the wrapper - the sketch needs two
# build properties and both are silent when missing. build.f_cpu MUST
# match the runtime clock, because micros() divides by it; and
# build.ldscript pins the capture ring to SRAM bank 1, whose path has to
# be computed relative to the *installed variant directory*.
tools/sketch.sh compile
tools/sketch.sh upload

# Talk to either (discover the port first; the path moves with cables)
python3 tools/serial_probe.py /dev/cu.usbmodem14201 --send h --seconds 3
```

### Python

**Everything with dependencies runs from a venv.** The test suite does
already; the GUI and any Windows serial backend will. Dependencies are
declared once, pinned, and committed; the venvs themselves are per
machine and never committed, because a venv holds absolute paths and
platform-specific wheels and does not travel.

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest --track=b -q
```

**Providing a usable, modern Python is the OS user's job**, not the
project's. The repository declares what it needs and builds a venv from
it; it does not work around an old interpreter.

On this machine that is already satisfied. **MacPorts is installed** at
`/opt/local` (`port` 2.12.5) with `python314` 3.14.6 active, and the
venv is built on `/opt/local/bin/python3.14`. There is no *Homebrew* -
which is all "no package manager" ever meant in this file, and it was
wrong as written. `/usr/bin/python3` is the Xcode Command Line Tools
3.9.6 and is no longer what anything is built on.

`host/` currently imports only stdlib - `termios` and `fcntl` rather
than pyserial, a Goertzel rather than an FFT library, `zlib.crc32`
rather than a checksum package - and there is no reason to churn
working code. Treat that as a fact about the code, not a rule new code
inherits: everything runs from the venv now, and anything that needs a
dependency may take one.

**Two venvs, two interpreters, and both exist here.** PySide6 6.9.3 is
`cp39-abi3` and declares `>=3.9,<3.14`, so it will not install on 3.14.

| venv | Interpreter | Holds |
|---|---|---|
| `.venv` | 3.14.6 (`/opt/local/bin/python3.14`) | pytest |
| `.venv-gui` | 3.13.14 (`/opt/local/bin/python3.13`) | PySide6 6.9.3, pyqtgraph 0.14.0, numpy 2.5.2, scipy 1.18.1 |

Both are installed and both import - verified, not inferred from
metadata. Neither is committed; a venv holds absolute paths and
platform-specific wheels and does not travel.

**Use the xPack toolchain, not ARM's official macOS build.** ARM's links
`cc1` against Homebrew's zstd at an absolute path and cannot run on this
host; the driver still reports a version, so the failure only appears
when something is actually compiled. See `docs/toolchain.md`.

Keep the tracks feature-equivalent. Anything added to one gets added to
the other, with the same commands and output format.

## Bring-up order

Do not reorder. Each stage is independently verifiable, which matters
because there is no debug probe.

1. BSP: clock, UART printf, LED heartbeat, **HardFault handler** — done
2. TC + ADC + PDC ping-pong, dumping buffers over UART — done
3. **Verify the actual trigger rate** — done; this is where the silent
   trigger-overrun cliff (RC 86) was found
4. DACC, closing the DAC0-to-A0 loopback — done, both directions,
   including host-fed playback
5. Replace the printf sink with the USB path — done on both tracks;
   playback and capture both run on endpoint DMA and the processor no
   longer touches sample data at all
6. Host application — capture/loopback/bench tools, a daemon owning the
   ports (`host/daemon/`, `docs/daemon-api.md`), and a Qt front end
   (`gui/`) that draws from it. See `docs/frontend.md`
7. FreeRTOS variant — not started

## Debugging context

No JTAG/SWD probe. Diagnostics rest on GPIO toggles (~12 ns, safe inside
ISRs), UART printf over the programming port (slow, never in ISRs), and
host-side counters. The HardFault handler is built first for this reason.
See `docs/debugging.md`.

## Hardware safety

Phase 1 loopback is safe by construction — the DAC cannot exceed ~2.75 V.

Any suggestion to connect external signals requires the Phase 3 front end
first: protection clamps, attenuator, mid-rail bias, buffer op-amp. Do
not propose connecting unknown signals directly to the ADC pins.
