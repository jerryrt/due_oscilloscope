# Agent Instructions

Working notes for AI agents on this repository. Read `docs/scope.md` and
`docs/architecture.md` before making non-trivial changes.

## What this project is

A 12-bit oscilloscope and signal generator on the Arduino Due
(SAM3X8E, Cortex-M3 @ 84 MHz). The board acquires and generates; the
host does all DSP and visualisation.

Status: **full loop working and solid.** Both tracks stream the ADC's
complete in-spec output gaplessly; Track B additionally runs host-fed
DAC playback and simultaneous capture (HOST -> DAC0 -> A0 -> HOST) with
zero underruns and tone amplitude at the theoretical maximum in every
measurement window. See `docs/status.md` for numbers and
`docs/HANDOFF.md` for the current objectives.

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
  12 Msps.
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
  the endpoint FIFO a byte at a time and spins on `TXINI`. `SerialUSB`
  therefore cannot carry the sample path without breaking invariant 1.
  Endpoints are already 512-byte and 2-bank, so there is nothing to tune
  there either. Verified from core source; see `docs/hardware.md`.
- **macOS's CDC-ACM output path drops ~128-byte chunks under pressure**,
  silently, with `write()` having counted them and every counter on
  both sides green. Never free-run writes into saturation. The safe
  feed policy depends on the device side - clock-paced with a bounded
  lead against the current DMA-fed ring, empty-queue-gated against a
  manual-FIFO device. See `docs/usb.md`.
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
   endpoint DMA, capture IN is the last CPU copy (see `docs/HANDOFF.md`)
6. Host application — capture/loopback/bench tools done; GUI pending
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
