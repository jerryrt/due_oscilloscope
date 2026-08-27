# due_oscilloscope

A 12-bit oscilloscope and signal generator built on the Arduino Due
(Atmel SAM3X8E, Cortex-M3), streaming samples over USB to a host for
FFT/DSP and visualisation. **MCK runs at 78 MHz, not the Due's usual
84**, chosen so the ADC clock lands at 19.5 MHz inside its 20 MHz limit;
every RC in this project divides 39 MHz because of it.

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
| [docs/awg.md](docs/awg.md) | Both generators, shapes, resolution, and why a trace shakes |
| [docs/measurement-suite.md](docs/measurement-suite.md) | How a figure earns the word baseline, and what is still missing |
| [docs/debugging.md](docs/debugging.md) | Probeless bring-up strategy |
| [docs/rtos.md](docs/rtos.md) | Bare-metal and FreeRTOS integration |
| [docs/usb.md](docs/usb.md) | Measured transport ceilings and host I/O policy |
| [docs/testing.md](docs/testing.md) | On-hardware pytest suite: design, and what it found |
| [docs/frontend.md](docs/frontend.md) | Front end architecture: daemon, GUI, recording |
| [docs/daemon-api.md](docs/daemon-api.md) | The daemon's socket API |
| [docs/hardware-next.md](docs/hardware-next.md) | Options for a more powerful successor |
| [docs/status.md](docs/status.md) | What works, measured figures, recorded mistakes |
| [docs/windows.md](docs/windows.md) | Windows validation: 0c settled, byte loss is macOS's |
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

Those figures are macOS's. Read them with objective 0h in mind: the
playback path there loses 0.45-2.25% of what the host writes above
200 ksps, silently and with `under=0` throughout. It does not on
Windows - [docs/windows.md](docs/windows.md).

**And there is a front end on it.** A daemon owns the ports and the
real-time threads and serves clients over a socket
([docs/daemon-api.md](docs/daemon-api.md)); a Qt window draws from it
with min/max decimation and a health panel
([docs/frontend.md](docs/frontend.md)). Both have test suites that need
no board:

```sh
python3 -m daemon --fake                     # from host/
.venv-gui/bin/python -m gui --spawn-fake     # the front end, no hardware
.venv-gui/bin/python -m gui --spawn-file cap.due   # replay a recording
```

| Measurement | Result |
|---|---|
| Matched loop up to 453,488 sps each way | 1371 +/- 2 codes in every window, `under=0`, gapless |
| AWG play-only up to 1.383 Msps (DACC hardware limit) | `under=0` at a 2.81 MB/s DMA-fed stream |
| Full-rate pair: DAC 907 k + capture 907 k aggregate | runs with `under=0`; purity work remains (see handoff) |
| Capture path (Track B) | sent by endpoint DMA; the processor never reads a sample |
| USB via endpoint DMA (IN / OUT / duplex) | **32.0 / 26.6 / 16.95 MB/s** on macOS; bytes *offered*, see objective 0h |
| The same three on Windows 11 | IN **29 median (26-34 over 9 runs)** / OUT **37.6-37.8** / duplex **47.7-48.5 MB/s**, OUT with 0 B deficit |

**Validated on a second host.** The same firmware on Windows 11 and a
second board conserves every byte at every playback rate from 200,000 to
1,392,857 sps, captures gapless at 453,488 sps, returns the loop tone at
1370.8 codes, and never wedges in `close()`. That settles objective 0c
and points the playback byte loss at macOS's CDC driver rather than at
the device - see [docs/windows.md](docs/windows.md).

Both tracks stream the ADC's full in-spec output continuously over
plain CDC; Track A is the reference oracle, Track B the project. The
transport was never the limit — most of what looked like device faults
were host-side measurement bugs, all recorded in
[docs/status.md](docs/status.md).

## Tests

The suite runs against the real board over both USB ports; there is no
simulator, because the failures it exists to catch have no software
model. It needs pytest, which is not stdlib, so **the Python side runs
from a venv**:

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest --track=b -q      # or --track=a, or both
.venv/bin/python -m pytest -m smoke -q       # the fast subset
```

Everything under `host/` stays stdlib only and runs from the system
interpreter: those tools are used during bring-up on a machine with no
package manager. Only the tests need the venv.

See [docs/testing.md](docs/testing.md).

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
