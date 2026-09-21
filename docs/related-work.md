# Related work: instruments worth reading before the front end

**Status: a reading list with a purpose.** Each entry says what the
project is, what to read in it, and which part of this project it
informs. Figures quoted from memory of the published material are marked
*(check)*; verify against the project's own documentation before sizing
anything against them.

Read `docs/scope.md` for the phases these map onto, `docs/hardware-next.md`
for the successor-chip question, and `docs/noise.md` ("Within holds") for
the measurement that makes the front end the next step.

## The short version

| project | converters | what it is | read it for |
|---|---|---|---|
| Digilent OpenScope MZ | the PIC32MZ's own ADC; generator DAC *(check)* | the closest published shape to this project's next phase, on a stronger chip | input stage topology, offset and attenuation, calibration procedure, the instrument protocol |
| Digilent Analog Discovery | external ADC and DAC behind an FPGA | a commercial instrument with a published front-end block diagram | how a ±25 V input reaches a 3 V converter, the reasoning rather than the parts |
| ScopeFun | external ADC and DAC behind an FPGA | an open-hardware oscilloscope with full sources | a complete converter-plus-front-end board, the reference and supply sections |
| Girino | the ATmega's own 10-bit ADC | an Arduino oscilloscope on a proto shield | the minimum front end that is still one: offset, gain, a buffer |

Two of the four use external converters, and both are FPGA designs where
the converter is the point of the hardware. The two microcontroller
designs use the chip's own converters and do their analog work in the
front end. No published project pairs an Arduino Due with external
converters on a shield, and `docs/architecture.md` says why this one
should not: the datapath is built around the SAM3X's PDC feeding the
internal converters, and an external one over SPI replaces that path
rather than extending it.

## OpenScope MZ, and the gap to it

The chip is stronger than the SAM3X8E on every axis that matters here:
200 MHz against 84, 512 KB of RAM against 96, a hardware FPU against
none, and several ADC modules reaching tens of megasamples aggregate
against one converter at 1 Msps. The comparison is therefore a fuller
instrument on a bigger chip, not more done with less.

| area | OpenScope MZ | this project | the gap is |
|---|---|---|---|
| input range and protection | about ±20 V, attenuator, offset, buffer, clamps *(check)* | 0 to 3.3 V, nothing in front of the pin | Phase 3, not built |
| sample rate | single-digit MS/s per channel *(check)* | about 900 ksps aggregate | silicon |
| record length | buffered captures in RAM | gapless streaming to the host, no length limit | a different architecture, the stronger one for continuous capture |
| triggering | edge and level in firmware, a scope display | none in the front end | a missing feature |
| generator | one channel, 10-bit, about 10 MS/s, about ±3 V *(check)* | 12-bit, up to 1.4 MS/s, 0.55 to 2.75 V, no output stage | resolution here, rate and range there; the output stage is Phase 3 |
| supplies, logic analyser, WiFi | present | out of scope | product features |
| calibration | a defined per-unit procedure | a direction and a profile format | the reference part |
| layout | an instrument PCB with planes and decoupling | a Due and jumper wires | the pickup `docs/noise.md` measures |
| software | browser UI, documented JSON protocol, works out of the box | daemon with a documented API, an early Qt window | a product's front end against a bench tool's |

What is closable is on this project's own roadmap and starts on the
shield: the input stage, the output stage, the anti-alias filter, the
reference and calibration, and a trigger. What is not closable is the
converter's rate, which is the successor question in `docs/hardware-next.md`.

Where this project is ahead: the CPU never touches sample data and the
capture streams gaplessly over USB DMA at a measured tens of MB/s; two
independent firmware tracks act as oracles for each other with the wire
contract shared as source; every figure carries its bench, image, board
and instrument; and the generator has twelve bits.

## What to take from each into the shield

- **Reference first.** The Due brings `AREF` to the header. A precision
  reference with its own decoupling on the shield addresses one of the
  two coupling paths `docs/noise.md` leaves open, and it is the part the
  calibration direction needs. OpenScope's calibration procedure is the
  model for how a unit measures itself against it.
- **A buffered, band-limited input.** Every design above drives its
  converter from a low-impedance source through a filter. Here the pin
  sees a bare wire, which is the other coupling path. The buffer is also
  the anti-alias filter Phase 3 lists, and it needs bandwidth at 3.3 V
  single supply that keeps the analog path from becoming the ceiling
  below the converter's 900 ksps.
- **Protection, attenuation and bias** as in `docs/scope.md`, Phase 3.
- **An output stage** for the DAC's 0.55 to 2.75 V window, with a
  reconstruction filter.

Each stage is judged with `tools/gen_sweep.py` before and after, on the
board with the most residual, by the within-hold rate and the largest
excursion. That is the instrument the front end is built to satisfy, not
a bandwidth figure copied from a catalogue.

## Where to find them

Digilent's reference site carries the OpenScope MZ and Analog Discovery
reference manuals and the OpenScope firmware and hardware sources.
ScopeFun publishes its hardware and firmware on GitHub under its own
name. Girino is an Instructables project. Search by name; links here
would rot.
