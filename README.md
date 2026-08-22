# due_oscilloscope

A 12-bit oscilloscope and signal generator built on the Arduino Due
(Atmel SAM3X8E, Cortex-M3 @ 84 MHz), streaming samples over USB to a host
for FFT/DSP and visualisation.

The board does acquisition and generation only. All signal processing and
rendering happens on the host, where numpy/scipy are available and the
missing FPU on the Cortex-M3 stops mattering.

## Documents

| Document | Contents |
|---|---|
| [docs/scope.md](docs/scope.md) | Goals, phases, targets, non-goals |
| [docs/hardware.md](docs/hardware.md) | SAM3X8E and Due facts, measured USB topology |
| [docs/toolchain.md](docs/toolchain.md) | arduino-cli track and CMake/arm-gcc track |
| [docs/architecture.md](docs/architecture.md) | DMA datapath, timebase, buffering |
| [docs/protocol.md](docs/protocol.md) | Host streaming frame format |
| [docs/debugging.md](docs/debugging.md) | Probeless bring-up strategy |
| [docs/rtos.md](docs/rtos.md) | Bare-metal and FreeRTOS integration |
| [docs/usb.md](docs/usb.md) | Measured transport ceilings and host I/O policy |
| [docs/status.md](docs/status.md) | What works, measured figures, recorded mistakes |
| [docs/HANDOFF.md](docs/HANDOFF.md) | Current state and next objectives |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Commit conventions |
| [CLAUDE.md](CLAUDE.md) | Agent working instructions |

## Status

**The complete loop works, solidly**: the host streams a waveform to
the DAC over bulk OUT while simultaneously capturing it back from the
ADC over bulk IN, on Track B's bare-metal UOTGHS stack. Verified: zero
underruns, zero sequence gaps, zero CRC errors, and tone amplitude at
the theoretical maximum (1371 +/- 2 codes) in every 40 ms window of a
run. See [docs/status.md](docs/status.md).

| Measurement | Result |
|---|---|
| Matched loop up to 453,488 sps each way | 1371 +/- 2 codes in every window, `under=0`, gapless |
| AWG play-only up to 1.383 Msps (DACC hardware limit) | `under=0` at a 2.81 MB/s DMA-fed stream |
| Full-rate pair: DAC 907 k + capture 907 k aggregate | runs with `under=0`; purity work remains (see handoff) |
| USB via endpoint DMA (IN / OUT / duplex) | **32.0 / 26.6 byte-perfect / 16.95 MB/s** |

Both tracks stream the ADC's full in-spec output continuously over
plain CDC; Track A is the reference oracle, Track B the project. The
transport was never the limit — most of what looked like device faults
were host-side measurement bugs, all recorded in
[docs/status.md](docs/status.md).

## Design in one paragraph

Timer Counter outputs trigger the ADC and the DAC in hardware, so
capture is deterministic and generation phase-stable (the host-fed
playback path runs the DAC on its own timer channel). The ADC's PDC
channel writes conversions into a ring of SRAM buffers; the playback
ring feeds the DACC the same way in reverse. The CPU never touches
sample data in the design's end state — playback already reaches it
(the ring is filled by UOTGHS endpoint DMA), and converting the capture
side's remaining FIFO copy is the current objective. A jumper from DAC0 to A0
closes the loop so each half validates the other without any front-end
hardware.
