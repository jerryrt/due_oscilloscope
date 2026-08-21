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

### Unverified

CDC bulk endpoint `wMaxPacketSize` (64 vs 512) could not be read: macOS
publishes no endpoint descriptors in the IORegistry. Read it from the SAM
core descriptor tables or via libusb.

## ADC

| Item | Value |
|---|---|
| Resolution | 12-bit |
| Converters | **One**, behind a 16:1 input multiplexer |
| Channels on Due headers | 12 (A0–A11) |
| Aggregate rate | ~1 Msps *(check exact cycle count)* |
| Max ADC clock | ~22 MHz *(check)* |
| Input range | 0 V to ADVREF (3.3 V). No negative, no overvoltage |

```
ADCClock = MCK / ((PRESCAL + 1) x 2)
PRESCAL = 1  ->  84 MHz / 4 = 21 MHz     (just under the ~22 MHz max)
21 MHz / ~20 cycles per conversion = ~1.05 Msps aggregate
```

Channels convert **round-robin, not simultaneously**. Consecutive
conversions are ~0.95 us apart, so in a 12-channel sequence A11 lags A0
by roughly 10.5 us. The skew is deterministic and correctable in host
DSP, but this is not simultaneous sampling and must not be treated as
such for phase measurements.

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

## DAC

| Item | Value |
|---|---|
| Resolution | 12-bit |
| Channels | 2 (DAC0, DAC1) |
| Output range | **~1/6 to ~5/6 of ADVREF, i.e. ~0.55 V to ~2.75 V** *(check on this board)* |
| Drive | High output impedance; needs a buffer op-amp for any real load |

The non-rail-to-rail output surprises everyone. `analogWrite(DAC0, 0)`
produces roughly 0.55 V, not ground. Measuring the true endpoints on this
specific board is a Phase 1 deliverable.

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
