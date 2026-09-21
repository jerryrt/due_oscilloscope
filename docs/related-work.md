# Related work: instruments worth reading before the front end

**Status: a reading list with a purpose.** Each entry says what the
project is, what to read in it, and which part of this project it
informs. OpenScope MZ figures are from Digilent's reference manual; the other
projects' figures are from memory and marked *(check)*.

Read `docs/scope.md` for the phases these map onto, `docs/hardware-next.md`
for the successor-chip question, and `docs/noise.md` ("Within holds") for
the measurement that makes the front end the next step.

## The short version

| project | converters | what it is | read it for |
|---|---|---|---|
| Digilent OpenScope MZ | the PIC32MZ's own ADC modules, interleaved; an R-2R ladder on ten GPIO pins for the generator | the closest published shape to this project's next phase, on a stronger chip | input stage topology, the 3 V reference with feedback, PWM offsets, the calibration procedure, the instrument protocol |
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
| input range and protection | ±20 V, 1 MΩ, attenuator, PWM-driven offset, buffer | 0 to 3.3 V, nothing in front of the pin | Phase 3, not built |
| sample rate and bandwidth | 6.25 MS/s per channel, 12-bit; flat to 1 MHz, 2 MHz at −3 dB | about 900 ksps aggregate; no anti-alias filter yet | silicon, and Phase 3 |
| record length and host link | 32,640 samples per channel, shipped over an FT232RQ serial bridge at 1.25 MBaud (139 kB/s); the chip's own Hi-Speed USB unused | gapless streaming over the chip's Hi-Speed USB by DMA, 1.8 MB/s today, tens of MB/s measured | a different architecture, the stronger one for continuous capture |
| triggering | edge and level in firmware, a scope display | none in the front end | a missing feature |
| generator | one channel, 10-bit R-2R ladder of 1% resistors at 10 MS/s, 3 V peak-to-peak with ±1.5 V offset, missing codes possible, calibrated by lookup table | 12-bit DAC, up to 1.4 MS/s, 0.55 to 2.75 V, no output stage | resolution and monotonicity here, rate and range there; the output stage is Phase 3 |
| supplies, logic analyser, WiFi | present | out of scope | product features |
| calibration | a 3 V external reference with feedback for the ADC, and a per-unit procedure that reads each output code back through a feedback network | a direction and a profile format | the reference part |
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

## Shield-class front ends on a chip's own converters

The direction the shield takes - a buffered, band-limited input, a
precision reference on the reference pin, protection, attenuation and
offset, an output stage for the DAC, all on a board stacked over a
microcontroller that keeps using its internal converters - has been
built several times. These are the ones whose design files are open,
with what each contributes. Figures are from memory and marked
*(check)* unless the file was read.

| project | chip and converters | open files | what it contributes here |
|---|---|---|---|
| EspoTek Labrador | an XMEGA with its own 12-bit ADC and DAC, USB Full Speed *(check)* | KiCad schematics and PCB on GitHub, CC BY-NC-SA | the closest architectural twin: internal converters, a discrete front end, a streaming USB link. Read its input divider, offset and buffer, and its generator output stage |
| PSLab, Pocket Science Lab | a PIC24 with its own 12-bit ADC, programmable-gain amplifiers in front *(check)* | KiCad hierarchical schematics on GitHub, Apache and GPL | a per-channel programmable gain stage and a reference, with KiCad simulation of the analog blocks recorded on its blog |
| Scoppy front-end shield for RP2040 | the Pico's own 12-bit ADC, a front-end board stacked on it | design files shared on PCBWay and a build log | the same shape as this shield exactly: a stacked front end feeding a bare ADC pin, attenuator, offset, buffer |
| Digilent OpenScope MZ | the PIC32MZ's own ADC modules | schematic sheets in the reference manual, `docs/datasheets/openscope-mz/` | the input driver into the ADC pin (68 Ω series, 470 pF shunt), the 3 V shunt reference buffered onto the reference pin, PWM offset injection |
| Girino | an ATmega's own 10-bit ADC | Instructables | the minimum: offset, gain, a buffer on a proto shield |

### Read from the schematics: what each stage would give the shield

Read from the design files themselves (Labrador `PCB/AltiumPCB/labrador.pdf`
and its KiCad netlist; PSLab `docs/schematics/PSLab.pdf`, sheet V6.0-beta;
Scoppy AFE 3 by MakerIoT2020, sheet 2022-10-28; OpenScope MZ sheets under
`docs/datasheets/openscope-mz/`). Fitness is against this shield's own
list - a reference on `AREF`, a buffered band-limited input into the ADC
pin, protection, attenuation and offset, an output stage for the DAC -
on a 3.3 V single supply unless a rail is worth generating.

| stage | OpenScope MZ | PSLab V6 | Labrador | Scoppy AFE 3 |
|---|---|---|---|---|
| ADC reference | **LM4040-3.0 shunt from 3.3 V, buffered by LMV324 onto VREF+; 1.5 V mid-rail from it through 0.1% resistors** | AVDD, no part | AVCC/2 internal, 1k/1k divider unbuffered | 3.3 V through 22k/22k, one LM324 section as buffer |
| ADC pin drive | **68 Ω series, 470 pF shunt, LMV116 driver** | PGA output straight to the pin | LM324 follower straight to the pin, 1k load | 220 Ω series, no shunt C |
| input attenuation and gain | 1 MΩ into LMV116, TS3A5017 mux selecting 1, 1/4, 1/8, 3/40 | 1 M / 200k inverting TL082 (gain −0.2) on ±6 V, then **MCP6S21 SPI PGA on 3.3 V** with a 10k/10k halve-and-shift | 1 M / 75k divider about the mid-rail (1:14.3), XMEGA PGA 0.5–64x | 470k / 680k divider, LM324 non-inverting stage on 5 V |
| offset and mid-rail | PWM through LM324, 10 mV steps | buffered 10k/10k mid-rail as the PGA's VREF | the divider's mid-rail on the ADC's negative input | 1.65 V from the divider |
| protection | series R into the buffer | 1 M series into a JFET input only | none | **BAT46 clamp at the divided node; 220 Ω and a Schottky to a sink section** |
| DAC output stage | MCP6H91 on ±rails, PWM offset (ladder source) | MCP4822 into LM324 "2·V − 3.3" stages on ±6 V, no series R | LM324 unity/×3 switched by a FET, **1k load and 56 Ω series, AC and DC pins** | none |
| rails | 3.3 V plus ± for the output stage | +9 / −9 by AP3015A boost and MT1470 inverter, ±6 by zener followers | boost to a variable 4.5–12 V for the LM324 | 5 V and 3.3 V only |
| calibration in hardware | readback through a feedback network | none | none | none |
| fitness for this shield | **high**: the reference and the pin driver are exactly the two stages the within-hold reading asked for, on 3.3 V, with parts in production | **medium**: the PGA block transfers as drawn; the rail generator is the model if ± rails are wanted; the input stage does not transfer | **low**: the divider form and the output-pin trick transfer; the amplifier, the reference and the differential ADC do not | **low**: the form factor and the limiter idea; an LM324 on 5 V has neither the swing nor the bandwidth |

The synthesis the table points to: OpenScope's reference and pin driver,
PSLab's PGA where variable gain is wanted, Labrador's output-pin form
for the DAC stage behind a rail-to-rail op-amp, and Scoppy's limiter at
the input. None of the four measures its front end against the
converter's own error; `tools/gen_sweep.py` is what this project adds.

Two shield-form designs go the other way and are listed so they are
not mistaken for this direction: the Digilent Analog Shield puts a
16-bit external ADC and DAC on an Arduino shield, and every FPGA
oscilloscope puts the converter on the board. Both replace the chip's
converters, which `docs/architecture.md` rules out here.

## Where to find them

Digilent's reference site carries the OpenScope MZ and Analog Discovery
reference manuals with the schematic images, behind a browser check;
the OpenScope MZ manual and its schematic sheets are kept under
`docs/datasheets/openscope-mz/`. The OpenScope MZ firmware is on GitHub
under Digilent, and the board's PCB design files are not in that
repository. The product is discontinued. Labrador is on GitHub under
espotek-org, PSLab under fossasia as pslab-hardware.
ScopeFun publishes its hardware and firmware on GitHub under its own
name. Girino is an Instructables project. Search by name; links here
would rot.
