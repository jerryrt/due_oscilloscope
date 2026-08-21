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

**Track A verified end to end.** `arduino-cli` 1.5.1, `arduino:sam`
1.6.12, gcc 4.8.3 and bossac 1.6.1 are installed and confirmed running on
this host (macOS 12.7.6, Intel x86_64). `sketches/blink` compiles,
uploads over the programming port, and runs on the board.

Track B (CMake + modern arm-gcc) is not yet set up. Next step is the BSP:
UART printf, LED heartbeat, and the HardFault handler, before any ADC
code.

One design decision was settled by reading the core source rather than
guessing: the Arduino CDC stack copies into the endpoint FIFO a byte at a
time and never uses the UOTGHS DMA, so `SerialUSB` cannot carry the
sample path. Track B drives the USB DMA directly. See
`docs/architecture.md`.

## Design in one paragraph

A single Timer Counter output triggers both the ADC and the DAC, so
generation and capture are phase-coherent. The ADC's PDC channel writes
conversions into a ring of SRAM buffers; the UOTGHS built-in DMA ships
those same buffers to the host over a bulk IN endpoint. The CPU never
touches sample data, only pointers. A jumper from DAC0 to A0 closes the
loop so each half validates the other without any front-end hardware.
