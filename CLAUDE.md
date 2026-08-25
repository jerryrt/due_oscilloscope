# Agent Instructions

Working notes for AI agents on this repository. Read `docs/scope.md` and
`docs/architecture.md` before making non-trivial changes, and
`docs/testing.md` before touching the host tools or adding tests.

## What this project is

A 12-bit oscilloscope and signal generator on the Arduino Due
(SAM3X8E, Cortex-M3 @ 84 MHz). The board acquires and generates; the
host does all DSP and visualisation.

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

## Invariants

Violating any of these is a design regression, not a style preference.

1. **The CPU never touches sample data.** PDC writes the buffer, USB DMA
   reads the same buffer. No memcpy, no per-sample loops, no payload
   checksums. If a change makes the CPU read the sample stream, it is
   wrong.
2. **No on-target DSP.** The Cortex-M3 has no FPU. FFT and filtering
   belong on the host.
3. **The two toolchains share no source, and are peers in everything
   else.** Track A (arduino-cli) is a reference oracle; Track B (CMake +
   arm-gcc) is the project. Do not attempt to unify the *source* - the
   independence is what makes the oracle worth having.

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
   13.14, `?` 20.18, `O` 15.40), `u` for 113 ms and the banner for
   89 ms. For every one of those milliseconds the loop drains no bulk
   OUT, which is the NAKing pipe that hangs macOS in `close()` - see
   objective 0c, where console polling during playback turned out to be
   a participant in the wedge rather than a witness to it. Twenty
   `GET_LOAD` queries over the control channel cost 0.29 ms *in total*.
   **New instrumentation goes in the metric system** (`bsp/load.c`,
   `GET_LOAD`), never in a printf, and anything read while the sample
   path is running goes over the control channel.

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
- **Not simultaneous sampling.** Consecutive conversions are ~0.95 us
  apart; channel skew is real and must be corrected host-side.
- **The DAC is not rail-to-rail.** Output spans roughly 0.55–2.75 V.
  Writing zero does not give ground.
- **The native port already runs at High Speed.** Verified: `Device
  Speed` = 2, `bcdUSB` = 0x0200. There is nothing to enable. Throughput
  limits live in the CDC-ACM stack, not the PHY.
- **Nothing is 5 V tolerant.** No clamps, no series resistors, no
  protection of any kind.
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
    is not. `Feeder.WRITE_SIZE`.

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

## The development platform is moving to Windows (2026-08-25)

macOS's CDC-ACM stack silently discards bytes `write()` has counted, in
two separate measured ways (see the fact below), and that defect has
been the subject of most of the last several sessions. The decision is
to develop on **Windows** and treat **macOS as a porting target**.

Nothing in this file is invalidated by that. Everything measured here
was measured on macOS and stays true of macOS; what changes is which
host's numbers are the project's numbers. The first work on Windows is
to re-take the 0-series in `docs/HANDOFF.md` rather than to build on top
of it, and `Feeder.WRITE_SIZE` may turn out to be a macOS workaround
rather than a rule.

Everything in `host/` is POSIX-only today - `termios`, `fcntl`, `select`
on raw descriptors, `/dev/cu.*` globs - and `host/rt.py` promotes
nothing off macOS. `docs/frontend.md` has the backend split sketched.
`tools/soak0c_portable.py` is the only host-side tool that runs
anywhere, and it exists to answer whether the `close()` wedge is macOS's
alone.

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

Both tracks work. `~/.local/bin` must be on `PATH` (holds `arduino-cli`
and `cmake`).

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
