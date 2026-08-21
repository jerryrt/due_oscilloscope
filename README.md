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
| [CONTRIBUTING.md](CONTRIBUTING.md) | Commit conventions |
| [CLAUDE.md](CLAUDE.md) | Agent working instructions |

## Status

**Both tracks stream end to end over USB.** See
[docs/status.md](docs/status.md).

| Trigger | Aggregate | Track A (Arduino CDC) | Track B (bare-metal CDC) |
|---|---|---|---|
| 200 kHz | 400 ksps | 0.807 MB/s, ratio 1.001 | 0.806 MB/s, ratio 1.000 |
| 400 kHz | 800 ksps | 0.871 MB/s, ratio 0.540 | 1.613 MB/s, ratio 1.000 |
| 488 kHz | 976,744 sps | 0.946 MB/s, ratio 0.480 | **1.969 MB/s, ratio 1.000** |

Track B carries the ADC's entire output continuously with no gaps. The
CDC ceiling turned out to be an implementation limit in the Arduino
core's byte-at-a-time FIFO copy, not a property of CDC.

## Design in one paragraph

A single Timer Counter output triggers both the ADC and the DAC, so
generation and capture are phase-coherent. The ADC's PDC channel writes
conversions into a ring of SRAM buffers; the UOTGHS built-in DMA ships
those same buffers to the host over a bulk IN endpoint. The CPU never
touches sample data, only pointers. A jumper from DAC0 to A0 closes the
loop so each half validates the other without any front-end hardware.
