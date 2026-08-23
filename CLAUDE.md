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
3. **The two toolchains share no source.** Track A (arduino-cli) is a
   reference oracle; Track B (CMake + arm-gcc) is the project. Do not
   attempt to unify them.
4. **`drivers/` stays RTOS-agnostic.** Bare-metal and FreeRTOS builds
   link identical driver code and differ only in `main()`.
5. **Never present discontinuous data as continuous.** Overruns are
   counted and flagged in the frame header. A silent splice becomes
   corrupted data that gets mistaken for a real signal.
6. **Never printf from an ISR.** Ring-buffer and drain outside the
   real-time path. A printf costs ~3.5 ms against a 0.95 us conversion.

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
- **Cortex-M3 has no data cache**, so DMA buffers need no cache
  maintenance. Advice written for Cortex-M7 parts does not apply.
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
  routes samples through it**: `sketches/bringup/usbdma.cpp` takes the
  two bulk endpoints away from the core and programs the UOTGHS DMA
  channels, leaving enumeration and control transfers with the core.
  The fact above is why that file exists, not a description of what
  Track A does now.
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
  it.** macOS's `close()` waits for in-flight write URBs; a NAKing pipe
  never completes them and the host process hangs in `close()` holding
  the port. The main loop drains and discards OUT when no consumer owns
  it - do not remove that.
- **There is no CPU pinning on macOS.** Predictable host-side streaming
  comes from the QoS class plus the Mach time-constraint band, wrapped
  in `host/rt.py`.

## Ports on the development host

| Role | Path (example, changes with topology) | Notes |
|---|---|---|
| Flash + control + debug | `/dev/cu.usbmodem14201` | Programming port, Full Speed |
| Sample data | `/dev/cu.usbmodemB_011` | Native port, High Speed; Track B's stack reports serial `B-01` |

Paths are enumeration-dependent and change whenever a cable moves; the
table is an example, not a reference. Discover with
`python3 host/ports.py`, which identifies the control port by the fact
that it answers. Always `/dev/cu.*`, never `/dev/tty.*`. Opening the
control port resets the board over NRSTB and re-enumerates the native
port, so open control first and re-glob the native node after.

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

# Track A: reference oracle
# build.f_cpu MUST match the runtime clock: micros() divides by it.
arduino-cli compile --fqbn arduino:sam:arduino_due_x_dbg \\
                    --build-property build.f_cpu=78000000L sketches/bringup
arduino-cli upload  --fqbn arduino:sam:arduino_due_x_dbg \
                    -p "$(python3 host/ports.py | awk '/control/{print $3}')" \
                    sketches/bringup

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
5. Replace the printf sink with the USB path — done; playback runs on
   endpoint DMA, and on Track B capture IN does too - the processor no
   longer touches sample data at all. Track A still copies; see
   objective 1b in `docs/HANDOFF.md` for why
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
