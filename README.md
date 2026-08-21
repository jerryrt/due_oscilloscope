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

Pre-implementation. Documentation captures the design agreed during
pre-flight discussion; no firmware has been written yet.

Next step is toolchain installation (see `docs/toolchain.md`), then BSP
bring-up: UART printf, LED heartbeat, and the HardFault handler, before
any ADC code.

## Design in one paragraph

A single Timer Counter output triggers both the ADC and the DAC, so
generation and capture are phase-coherent. The ADC's PDC channel writes
conversions into a ring of SRAM buffers; the UOTGHS built-in DMA ships
those same buffers to the host over a bulk IN endpoint. The CPU never
touches sample data, only pointers. A jumper from DAC0 to A0 closes the
loop so each half validates the other without any front-end hardware.
