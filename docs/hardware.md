# Hardware Reference

Target: **Arduino Due**, Atmel/Microchip **SAM3X8E**, ARM Cortex-M3 @ 84 MHz.

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
| Device path | `/dev/cu.usbmodem141301` | `/dev/cu.usbmodem1411401` |
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

Device paths are enumeration-dependent and may change. The programming
port has a serial number (`1344A47403035101C8E8`) and can be matched on
it; the native port does not report one.

Always use `/dev/cu.*`, never `/dev/tty.*`, for host-side serial clients
on macOS. The native port ignores baud rate entirely (CDC).

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
| Aggregate rate | **976,744 sps** *(measured, see below)* |
| Max ADC clock | ~22 MHz *(check)* |
| Input range | 0 V to ADVREF (3.3 V). No negative, no overvoltage |

```
ADCClock = MCK / ((PRESCAL + 1) x 2)
PRESCAL = 1  ->  84 MHz / 4 = 21 MHz     (just under the ~22 MHz max)
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
with an op-amp, or raising `TRACKTIM` — but raising `TRACKTIM` cuts
aggregate throughput. At ~30 cycles/conversion the aggregate falls to
about 700 ksps, i.e. ~58 ksps/channel across twelve channels.

This tradeoff, not USB bandwidth, is the most likely determinant of the
real per-channel rate.

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
| Output range | **546 mV to 2760 mV** *(measured on this board)* |
| Drive | High output impedance; needs a buffer op-amp for any real load |

The non-rail-to-rail output surprises everyone. `analogWrite(DAC0, 0)`
produces 546 mV on this board, not ground.

Measured through the DAC0->A0 loopback, both tracks agreeing to within
+/-2 ADC codes:

| DAC code | Measured |
|---|---|
| 0 | **546 mV** (theory: 1/6 x 3.3 V = 550 mV) |
| 4095 | **2760 mV** (theory: 5/6 x 3.3 V = 2750 mV) |
| Usable span | 2214 mV, i.e. 2747 ADC codes |

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

Measured on this machine. The native port currently sits behind two
chained hubs:

```
USB 3.0 Bus
  USB2.1 Hub (0x14100000)
    Arduino Due Prog. Port (0x14130000)  Full Speed
    USB2.1 Hub (0x14110000)
      Arduino Due            (0x14114000)  High Speed
```

The Due is the only active device on the chain, so contention is not a
concern here. For absolute throughput benchmarking, connect the native
port directly to the host to avoid measuring the hub chain.
