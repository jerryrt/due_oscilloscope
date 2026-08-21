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

**Both tracks stream end to end.** See [docs/status.md](docs/status.md).

| | Track A | Track B |
|---|---|---|
| Toolchain | arduino-cli 1.5.1, gcc 4.8.3 | CMake 4.4.2, xPack gcc 15.2.1 |
| Transport | USB CDC, 0.8 MB/s gapless | UART (bare-metal USB not enumerating yet) |
| Tone measured | 1371.9 codes | 1371.5 codes |

Independent implementations agreeing to 0.03% is the point of keeping two
tracks.

Known issue: the bare-metal UOTGHS stack does not enumerate. Every
device-side register reads correct and one bus reset is serviced, but no
SETUP follows. Details and what has been ruled out are in
[docs/status.md](docs/status.md).

## Design in one paragraph

A single Timer Counter output triggers both the ADC and the DAC, so
generation and capture are phase-coherent. The ADC's PDC channel writes
conversions into a ring of SRAM buffers; the UOTGHS built-in DMA ships
those same buffers to the host over a bulk IN endpoint. The CPU never
touches sample data, only pointers. A jumper from DAC0 to A0 closes the
loop so each half validates the other without any front-end hardware.
