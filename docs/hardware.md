# Hardware Reference

Target: **Arduino Due**, Atmel/Microchip **SAM3X8E**, ARM Cortex-M3
rated 84 MHz — **run at MCK 78 MHz in this project** so the ADC clock
stays inside its datasheet limit (see "Operating point" below).

Figures marked *(verified)* were read from this development host or are
unambiguous. Figures marked *(check)* need confirmation against the
SAM3X8E datasheet before code depends on them.

## Core

| Item | Value |
|---|---|
| Core | Cortex-M3, 84 MHz, **no FPU**, **no data cache** |
| Flash | 512 KB |
| SRAM | 96 KB, split 64 KB + 32 KB across two banks |
| NVIC priority bits | 4 (16 levels) *(check)* |
| Logic level | 3.3 V — **not 5 V tolerant** |

No data cache is a genuine simplification: DMA buffers need no cache
maintenance, unlike Cortex-M7 parts such as the SAME70.

## USB ports

Both ports are exposed and serve different roles. Verified on this host:

| | Programming port | Native port |
|---|---|---|
| Device path (example; moves with cables) | `/dev/cu.usbmodem14201` | `/dev/cu.usbmodemB_011` |
| USB ID | `2341:003d` | `2341:003e` |
| Bridge | ATmega16U2 | SAM3X UOTGHS (on-die) |
| `Device Speed` | 1 = Full Speed *(verified)* | **2 = High Speed** *(verified)* |
| `bcdUSB` | 0x0110 *(verified)* | **0x0200** *(verified)* |
| `bMaxPacketSize0` | 8 *(verified)* | 64 *(verified)* |
| Interfaces | class 2 + class 10 (CDC-ACM) | class 2 + class 10 (CDC-ACM) *(verified)* |
| Role in this project | Flashing, printf debug | Sample data streaming |

The native port **already enumerates at High Speed**. There is no switch
to enable; the Arduino core does not force Full Speed. Any throughput
shortfall lives in the CDC-ACM stack above the PHY, not in the PHY.

Device paths are enumeration-dependent and change whenever a cable
moves; discover them with `python3 host/ports.py`. The programming port
has a serial number (`1344A47403035101C8E8`) and can be matched on it.
The Arduino core's native port reports no serial; Track B's bare-metal
stack reports `B-01`, which is why its node enumerates as
`usbmodemB_011`.

Always use `/dev/cu.*`, never `/dev/tty.*`, for host-side serial clients
on macOS. The native port ignores baud rate entirely (CDC).

**Linux has no callout node**, so `/dev/ttyACM0` is the only node and
there is no `cu.*` to prefer. Opening it asserts DTR and RTS, and on
the Due that is the documented NRSTB reset. It is **not** an erase:
measured on `linux-x1` with DTR alone, RTS alone and both, the board
survives every arm and answers `v`. A Linux bench that keeps landing
in SAM-BA has a boot-bit problem, not a modem-line problem - see
`docs/linux.md`.

### CDC endpoint configuration *(verified from core source)*

Read from `arduino:sam@1.6.12`. The endpoints are **already optimally
sized and banked**; there is no gain available from reconfiguring them.

| Item | Value | Source |
|---|---|---|
| `EPX_SIZE` | **512** | `system/libsam/include/uotghs_device.h:37` |
| `EP0_SIZE` | 64 | `uotghs_device.h:36` |
| Bulk IN / OUT packet size | **512 bytes** | `EP_TYPE_BULK_IN/OUT`, `uotghs_device.h` |
| Bulk IN / OUT banking | **2 banks** (double-buffered) | `UOTGHS_DEVEPTCFG_EPBK_2_BANK` |
| Descriptor (HS config) | 512 | `CDC.cpp:75-76`, `_cdcInterface` |
| Descriptor (other-speed) | 64 | `CDC.cpp:92-93`, `_cdcOtherInterface` |

The 64-byte figures belong to `_cdcOtherInterface`, the
`other_speed_configuration` descriptor reported for the Full-Speed
fallback. The active High-Speed configuration uses 512 throughout.

### The Arduino CDC path does not use DMA *(verified)*

`UDD_Send()` in `system/libsam/source/uotghs_device.c` spins on `TXINI`
and then copies into the endpoint FIFO **one byte at a time**:

```c
while (UOTGHS_DEVEPTISR_TXINI != (UOTGHS->UOTGHS_DEVEPTISR[ep] & ...)) {}
for (i = 0, ptr_dest += ul_send_fifo_ptr[ep]; i < len; ++i)
        *ptr_dest++ = *ptr_src++;
```

The only references to the UOTGHS DMA registers in the whole core are two
lines in `USBCore.cpp` that zero `UOTGHS_DEVDMACONTROL`. **The built-in
USB DMA is never used.**

Consequence: `SerialUSB` makes the CPU touch every sample byte, with a
blocking spin-wait per packet. That is incompatible with this project's
zero-copy invariant, so the Track B data path must drive UOTGHS DMA
directly rather than build on the core's CDC. See `docs/architecture.md`.

## ADC

| Item | Value |
|---|---|
| Resolution | 12-bit |
| Converters | **One**, behind a 16:1 input multiplexer |
| Channels on Due headers | 12 (A0–A11) |
| Aggregate rate | **976,744 sps at MCK 84; ~907 ksps at the MCK 78 operating point** *(measured, see below)* |
| Max ADC clock | **20 MHz** *(datasheet Table 46-28)* |
| Input range | 0 V to ADVREF (3.3 V). No negative, no overvoltage |

```
ADCClock = MCK / ((PRESCAL + 1) x 2)
PRESCAL = 1  ->  84 MHz / 4 = 21 MHz     (ABOVE the 20 MHz datasheet max)
```

### Measured ceiling *(this board)*

Swept the TC compare value with two channels enabled, counting completed
PDC buffers against a synchronised microsecond window:

| TC RC | Trigger Hz | Aggregate sps | Ratio |
|---|---|---|---|
| 88 | 477,272 | 954,544 | 1.000 |
| 87 | 482,758 | 965,516 | 1.000 |
| **86** | **488,372** | **976,744** | **1.000** |
| 85 | 494,117 | 988,234 | **0.500** |
| 84 | 500,000 | 1,000,000 | **0.500** |

**Maximum aggregate is 976,744 sps**, not the nominal 1 Msps - about
2.3% short. Per conversion that is 1.024 us, or ~21.5 ADC clocks at
21 MHz, against the ~20 usually quoted.

Settings used: `PRESCAL=1`, `TRACKTIM=0`, `SETTLING=0`, `TRANSFER=1`.
Relaxing tracking to suppress crosstalk lowers this further.

### Operating point: MCK 78 MHz, fully in spec

The project runs the master clock at **78 MHz**, not the Due's usual 84,
so that the ADC clock lands inside its datasheet limit.

The crystal and Table 46-22 leave very little choice. `FIN` must be
8-16 MHz, so with a 12 MHz crystal `DIVA` can only be 1, making
`PLLA = 12 MHz x (MULA+1)` a multiple of 12 within 96-192 MHz. With the
master clock prescaler at /2, MCK is therefore a multiple of 6:

| MULA | PLLA | MCK | ADC clk (/4) | Verdict |
|---|---|---|---|---|
| 12 | 156 MHz | **78** | **19.5 MHz** | **in spec** |
| 13 | 168 MHz | 84 | 21.0 MHz | 5% over |
| 14 | 180 MHz | 90 | 22.5 MHz | 12.5% over, MCK over rated 84 |

80 MHz, which would give exactly 20.0 MHz, is unreachable: it needs
`DIVA = 3` and an `FIN` of 4 MHz, below the 8 MHz minimum.

### What the in-spec clock costs, measured

| Quantity | MCK 84 (out of spec) | **MCK 78 (in spec)** | Ratio |
|---|---|---|---|
| ADC clock | 21.0 MHz | 19.5 MHz | 0.929 |
| ADC aggregate ceiling | 976,744 sps | **906,738 sps** | 0.928 |
| DACC ceiling | 1,539,704 conv/s | **1,423,890 conv/s** | 0.925 |
| GPIO set+clear pair | 107.29 ns | 115.87 ns | 1.080 |

**Spec compliance costs 7.2% of sample rate.** That is far cheaper than
the alternative of keeping MCK at 84 and dividing harder: `PRESCAL = 2`
gives a 14 MHz ADC clock and drops the aggregate near 650 ksps, a third
of the rate.

Both converters scale linearly with MCK, which settles what limits them:

- ADC: 21.5 clocks per conversion at both clocks, so it is ADC-clock
  limited.
- DACC: 54.6 MCK cycles per conversion at 84 MHz and 54.8 at 78, so it
  is **MCK-limited rather than analog-limited**. Its rate can be traded
  directly against master clock.

The trigger compare value at the cliff is **RC 86 at either clock**,
because the timer clock and the ADC clock scale together. `ACQ_MIN_RC`
is therefore correct without reference to MCK.

### Build requirement

`micros()` in the Arduino core divides by `F_CPU`, a compile-time
constant, so a clock change that the build does not know about silently
skews every timing measurement. Track A must be built with:

```sh
cmake -B build-a -DCMAKE_TOOLCHAIN_FILE=cmake/arm-none-eabi-toolchain.cmake \
      -DCMAKE_BUILD_TYPE=Release -DBUILD_TRACK_A=ON
cmake --build build-a --target firmware_track_a
```

`build.f_cpu` and `build.ldscript` are lines in `cmake/track_a.cmake`
now, so neither can be silently forgotten (#55). `tools/sketch.sh`
passed them as arduino-cli properties until 2026-08-31 and is deleted.

The firmware prints both values at start-up and warns if they disagree,
so a stale build property is caught immediately rather than corrupting
results quietly.

### Measured against the datasheet

Checked against `docs/datasheets/Atmel-SAM3X-SAM3A-Series-Datasheet.pdf`
(11057B, 28-May-12).

| Parameter | Datasheet | Measured / used | Verdict |
|---|---|---|---|
| ADC `fS` sampling frequency | 0.05 to **1 MHz** (Table 46-28) | 976,744 sps | within spec, 97.7% |
| ADC `fADC` clock frequency | 1 to **20 MHz** (Table 46-28) | **21 MHz** | **out of spec by 5%** |
| ADC `IBCTL` | "00 below 500 kHz, **01 between 500 kHz and 1 MHz**" (§46.7) | never set (00) | **not per datasheet** |
| Feature summary | "16-channel 12-bit 1Msps ADC" | - | consistent |

**Two problems, both ours.**

The ADC clock is over the maximum. `PRESCAL = 1` gives
`84 MHz / 4 = 21 MHz`, and the datasheet ceiling is 20 MHz. An earlier
version of this document said "~22 MHz max", which was wrong and is what
justified the choice. The prescaler is coarse:
`ADCClock = MCK / ((PRESCAL+1) x 2)`, so the options either side are
21 MHz (`PRESCAL=1`, out of spec) and **14 MHz** (`PRESCAL=2`, in spec).

Running fully in spec therefore caps the aggregate near **650 ksps**, not
976,744. The measured ceiling is real and reproducible, but it is
achieved 5% outside the guaranteed operating range, and that has to be a
deliberate decision rather than an accident.

`IBCTL` (in `ADC_ACR`) is also left at reset. The datasheet directs
`IBCTL = 01` for sampling above 500 kHz, which is where this project
operates. Not setting it does not stop conversions, and the loopback
linearity looks clean, but it is outside the documented configuration.

### DAC: the datasheet says very little

| Source | Statement |
|---|---|
| Feature summary | "One 2-channel 12-bit **1MSPS** DAC" |
| §45.2 DACC Embedded Characteristics | resolution, channels, triggers, PDC, FIFO - **no conversion rate** |
| §46.9 12-bit DAC Characteristics | startup time, output impedance 30 ohm, current - **no maximum sampling rate** |

So the only rate figure for the DAC anywhere is the headline 1 MSPS, and
it is not qualified as per-channel or aggregate, nor backed by an entry
in the electrical tables.

Measured here: **1,539,704 conversions/s aggregate**, which is 154% of
that headline. In TAG mode conversions alternate between channels, so
per channel it is 770 ksps - comfortably under 1 MSPS. The most likely
reading is that the headline figure is per channel and that the shared
conversion engine saturates near 1.54 Msps, but the datasheet does not
say so.

The measurement itself is independently confirmed: driven at a 3 MHz
trigger, the emitted tone appears at 3007 Hz, and 1,539,704 / 512 =
3007.2 Hz exactly. A tone at the trigger rate would have been 5859 Hz,
which measured 2.2 codes against 860.6. So the saturation is real and
`ENDTX` was counting genuine conversions, not merely PDC transfers.

### Trigger overrun is silent

**`ADC_ISR.GOVRE` and `RXBUFF` both read zero while half the triggers are
being dropped.** When a trigger arrives before the ADC is ready it is
simply ignored: no flag, no counter, no error. The failure is a clean 2:1
decimation that looks like correctly acquired data at half the rate.

The only way to detect it is to compare the measured conversion rate
against the configured one. Firmware must therefore refuse a trigger
period below the measured floor rather than trusting status bits, and
the host should verify the rate independently. See `docs/protocol.md`.

Channels convert **round-robin, not simultaneously**. Consecutive
conversions are ~1.02 us apart (measured), so in a 12-channel sequence A11 lags A0
by roughly 10.5 us. The skew is deterministic and correctable in host
DSP, but this is not simultaneous sampling and must not be treated as
such for phase measurements.

### Channel numbering *(verified from the device header)*

**The Arduino `A0..A7` labels map to ADC channels in DESCENDING order.**
Bare-metal code assuming `A0 == AD0` reads the wrong pin.

| Label | Pin | Channel | | Label | Pin | Channel |
|---|---|---|---|---|---|---|
| A0 | PA16 | **AD7** | | A6 | PA3 | AD1 |
| A1 | PA24 | **AD6** | | A7 | PA2 | AD0 |
| A2 | PA23 | AD5 | | A8 | PB17 | AD10 |
| A3 | PA22 | AD4 | | A9 | PB18 | AD11 |
| A4 | PA6 | AD3 | | A10 | PB19 | AD12 |
| A5 | PA4 | AD2 | | A11 | PB20 | AD13 |

`AD14` is PB21 (digital pin 52). `AD8`/`AD9` are PB12/PB13, not broken
out as analog labels.

This also affects skew correction. The sequencer converts enabled
channels in ascending *channel index* order, so a full sweep runs
`A7, A6, ... A0, A8, A9, A10, A11` - **not** label order.

Also note: `DAC0` (PB15) and `DAC1` (PB16) have **no ADC channel**. The
Arduino `variant.cpp` lists `ADC12`/`ADC13` on those rows, which is
misleading; the device header puts AD12 on PB19 and AD13 on PB20. The
CMSIS device header is authoritative.

Useful register bits:

- `ADC_EMR.TAG` — puts the channel index in `ADC_LCDR[15:12]`, making the
  stream self-describing at no cost. Enable it.
- `ADC_MR.USEQ` + `ADC_SEQR1/2` — arbitrary channel order or repeats.
- `ADC_MR.TRGSEL` — hardware trigger source (TIOA outputs, PWM, external).
- `ADC_MR.FREERUN` — **avoid** for anything feeding an FFT; its rate
  jitters with the ADC state machine and smears spectral bins.
- `TRACKTIM` / `SETTLING` / `STARTUP` — the crosstalk-versus-throughput
  knob, see below.
- `ADC_ISR.GOVRE`, `ADC_OVER` — overrun detection. Must be surfaced to
  the host, never silently dropped.

### Multiplexer crosstalk

One shared sample-and-hold means residual charge from the previous
channel contaminates the next. With high-impedance sources this is
severe and presents as noise. Mitigations are buffering each channel
with an op-amp, or raising `TRACKTIM` — but raising `TRACKTIM` was
expected to cut aggregate throughput: at ~30 cycles/conversion the
aggregate would fall to about 700 ksps, i.e. ~58 ksps/channel across
twelve channels. *(check)* **Measured 2026-08-26, it does not fall at
all.** `TRACKTIM(15)` with `SETTLING(3)` sustains every rate from rc 200
to rc 86 — 390 to 907 ksps aggregate — with `govre=0`, no overrun frames
and rates identical to `TRACKTIM(0)` to the sample, while ADC_MR read
back from the peripheral carries the field. `TRACKTIM` sets a *minimum*
tracking time and the converter is idle for longer than that at every
rate here; at rc 86, where the minimum would have to lengthen the cycle,
the hardware declines to. So this is not a usable knob on tracking in
this design, and not a throughput cost either. See `docs/HANDOFF.md`,
"Track and settling do nothing".

That tradeoff was expected to be the determinant of the real
per-channel rate, ahead of USB bandwidth. On the measurement above it is
not a tradeoff at all: the converter's own 20-clock conversion sets the
ceiling, and `ACQ_MIN_RC` is where it lands.

**Measured baseline** (DAC0->A0, DAC1->A1 loopback, one channel held at
mid scale while the other swings full range):

| Case | Bleed |
|---|---|
| DAC1 held, DAC0 swung full range | **+/-1 code** |
| DAC0 held, DAC1 swung full range | **+/-1 code** |

Against a 2747-code full swing that is about 0.04%, indistinguishable
from LSB dither, and both tracks agree.

**This does not retire the crosstalk risk.** The measurement was taken
under the most favourable conditions available: maximum `TRACKTIM` and
`SETTLING`, software-triggered single conversions with milliseconds
between them, and a DAC output driving the pin directly, which is a
low-impedance source. Crosstalk bites when tracking time is short and the
source impedance is high. What this establishes is a clean baseline and
the absence of any gross wiring or analog fault - not that the fast
configuration will behave.

## DAC

| Item | Value |
|---|---|
| Resolution | 12-bit |
| Channels | 2 (DAC0, DAC1) |
| Output range | **578 mV to 2771 mV** *(scope on the pin; `calibration.json`)* |
| Drive | High output impedance; needs a buffer op-amp for any real load |

**Issue #5 lives on this pin.** Once per DAC table wrap one sample read
from a DAC output is displaced by up to ~80 codes, which is -49 dB
against full scale where the part is specified at -64 to -80 dB THD. It
is an AWG defect and does not affect ordinary ADC inputs. See
`docs/issue5-impact.md` for what it bounds and `docs/HANDOFF.md` for the
investigation.

The non-rail-to-rail output surprises everyone. `analogWrite(DAC0, 0)`
produces about 578 mV on this board, not ground.

Measured through the DAC0->A0 loopback, both tracks agreeing to within
+/-2 ADC codes:

| DAC code | Measured through the loop | Theory at ADVREF 3270 |
|---|---|---|
| 0 | **546 mV** | 1/6 x 3270 = 545 mV |
| 4095 | **2760 mV** | 5/6 x 3270 = 2725 mV |
| Usable span | 2214 mV, i.e. 2747 ADC codes | 2180 mV |

> **These are the loop's numbers, not the pin's, and the difference is a
> measurement in its own right.** A scope on the same pin reads
> **578-2771 mV** (`calibration.json`), which is 32 mV higher at the
> bottom: the loop folds the *ADC's* offset into what it reports as the
> *DAC's* span. Use the scope pair for anything absolute - an output
> stage designed against the bottom of this column would be designed
> against 32 mV that belongs to the other converter.
>
> The theory column also used to divide by 3.3 V. ADVREF is measured at
> **3270 mV** by two independent routes agreeing to 0.1 mV, so the
> nominal endpoints move with it.

Linearity is excellent: 171-172 ADC codes per 256 DAC codes, consistent
to within a couple of codes across the whole range. So the part matches
the 1/6-to-5/6 rule closely, and any output stage can be designed against
these numbers rather than against the datasheet's typicals.

### Measured update-rate ceiling *(this board)*

Swept with the DACC on its own timebase (TC0 channel 1, TIOA1) and the
achieved rate counted from `ENDTX` completions, which needs no help from
the capture path:

| TC RC | Trigger Hz | Measured conv/s | Ratio |
|---|---|---|---|
| 28 | 1,500,000 | 1,500,022 | **1.000** |
| 24 | 1,750,000 | 1,533,364 | 0.876 |
| 21 | 2,000,000 | 1,539,704 | 0.769 |
| 14 | 3,000,000 | 1,539,704 | 0.513 |

**The DACC saturates at about 1,539,700 conversions per second.** Beyond
that the measured rate is flat regardless of trigger frequency, so it is
a hard ceiling rather than a gradual degradation.

In TAG mode one trigger yields one conversion, so that figure is the
total across both channels: 1.54 Msps on a single channel, or 770 ksps
each when both are driven.

Note it is **57% higher than the ADC's 976,744 sps ceiling**. Generation
is not the bottleneck in a loopback.

Caution when adding a second TC channel: each channel has its own
peripheral ID. `ID_TC0` is TC0 channel 0 and `ID_TC1` is TC0 channel 1,
so clocking only `ID_TC0` leaves channel 1 dead and TIOA1 never toggles.

Two efficiency features worth using:

- `DACC_MR.WORD` — PDC transfers 32-bit words carrying two samples,
  halving DMA transaction count.
- `DACC_MR.TAG` — bits [13:12] of each half-word select DAC0 or DAC1, so
  a **single** PDC stream drives both channels.

## Timer Counter

Nine channels (3 blocks x 3). A TIOA output can trigger both the ADC and
the DACC, which is how generation and capture are kept phase-coherent.
See `docs/architecture.md`.

## DMA engines

Three independent movers, which is what makes real parallelism possible:

1. **PDC** — per-peripheral, attached separately to ADC and DACC.
   Pointer/counter pairs with a next-pointer for gapless chaining.
   Counters are **16-bit**, capping a single buffer at 65535 transfers.
2. **UOTGHS built-in DMA** — the USB device has its own per-endpoint DMA
   with **linked-list descriptors** (`DEVDMANXTDSC`, `DEVDMAADDRESS`,
   `DEVDMACONTROL`). A circular descriptor chain ships buffers with no
   CPU involvement at all.
3. **DMAC** — a separate 6-channel central controller. Present on the
   SAM3X8E (smaller SAM3 parts lack it). Free for mem-to-mem work.

## On-board LED

Pin 13 = **PB27**. Unlike the Uno, the Due's SPI lives on the ICSP
header, so PB27 carries no SPI conflict and is genuinely free.

```c
PMC->PMC_PCER0 = (1u << ID_PIOB);   /* clock PIOB  (check ID in sam3x8e.h) */
PIOB->PIO_PER  = PIO_PB27;          /* PIO controls the pin */
PIOB->PIO_OER  = PIO_PB27;          /* output */
PIOB->PIO_SODR = PIO_PB27;          /* on  */
PIOB->PIO_CODR = PIO_PB27;          /* off */
```

Available immediately after reset with one PMC write and no clock
configuration. See `docs/debugging.md` for how it is used.

## The Arduino core and this project do not compose silently

Track A runs on the Arduino core but programs the ADC, the DAC, the
timers and the USB endpoints itself. The core does the same to the same
registers, on its own schedule, and **where the two overlap the core
wins quietly**. Three instances in one week, each found by a measurement
or by output that could not be true, never by reading the sketch:

- **`analogRead()` against `ADC_EMR_TAG`.** `acq_init()` turns TAG on so
  the streaming path can demultiplex; `analogRead()` reads LCDR without
  masking it and returns `tag|value` - `A0 = 24584` on a 12-bit
  converter - and the tag says the value came from the channel the
  sequencer happened to finish last. `acq_read_one()`/`acq_read_pair()`
  replace it.
- **The core rebuilding endpoint configuration.** It re-enables each
  endpoint's interrupt and clears AUTOSW at every bus reset and
  `SET_CONFIGURATION`, which stalls a DMA transfer in flight for good.
  `usbdma_keepalive()` exists to notice and undo that.
- **`serialEventRun()`.** The core calls it after every `loop()` and it
  polls `available()` on all four hardware UARTs to dispatch a
  `serialEvent()` handler. This sketch opens one and defines no handler,
  so it was ~1.5 us of an 8.6 us pass - **17%** - spent outside `loop()`
  where the profiler cannot reach. The symbol is weak; the sketch
  defines its own empty one.

**The rule that follows: where a sketch reaches past the abstraction to
a peripheral, it must stop using the abstraction for that peripheral.**
Half-and-half is the state that fails, because the core's half is
written against assumptions the sketch has already invalidated.

CLAUDE.md's "Arduino is an abstraction layer, not a different
architecture" is right and this is its corollary. Nothing above was
prevented by the core - each was fixed by taking the register, which is
also why "the core will not let us" stays a claim to be tested rather
than believed.

Track B has none of these by construction: there is no second party
programming its peripherals.

## Safety notes

- **No input protection exists.** No series resistors, no clamp diodes,
  no 5 V tolerance on any pin. 5 V on an input can destroy the SAM3X8E,
  often partially — one dead channel, board otherwise working, which is
  a miserable failure to diagnose.
- A scope touches unknown signals by definition, so protection must be
  built in hardware (Phase 3), not relied upon as operator discipline.
- Phase 1 loopback is exempt: the DAC cannot exceed ~2.75 V, so the
  jumper is safe without any protection circuitry.

## Development host topology

The topology changes whenever cables move (it has, more than once), so
check with `system_profiler SPUSBDataType` rather than trusting a
snapshot here. Two measured facts survive any topology:

- Hub chains do not measurably limit throughput at this project's
  rates: moving the native port from behind two chained hubs to a root
  port changed IN by under 1% and OUT not at all.
- The Due should be the only active device on its chain when
  benchmarking absolute ceilings.
