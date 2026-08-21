# Project Scope

## Goal

Turn an Arduino Due into a usable dual-purpose instrument:

- **Signal capture** — multi-channel 12-bit acquisition, DMA-driven,
  streamed to a host over USB.
- **Signal generation** — 12-bit DAC output, DMA-driven, phase-coherent
  with the capture timebase.

All FFT/DSP and visualisation runs on the host (macOS/PC). The firmware's
only job is to move samples in and out of the SAM3X8E as efficiently as
the silicon allows, and to report honestly when it cannot keep up.

## Division of labour

| Side | Responsibility |
|---|---|
| Due (SAM3X8E) | Timebase, ADC sequencing, DAC playback, DMA, framing, drop detection |
| Host | Deframing, continuity checking, FFT/DSP, triggering UI, visualisation |

The Cortex-M3 has no FPU. Any on-target DSP would be integer-only and
slow, while the host has numpy/scipy for free. This split is deliberate
and should not erode.

## Phases

### Phase 1 — Loopback bring-up (in progress)

Jumpers from **DAC0 to A0** and **DAC1 to A1** close the loop. The
second channel is not decorative: it is what makes multiplexer crosstalk
and inter-channel skew measurable at all. The board generates a
waveform it already knows and captures it back, so each half validates
the other with no front-end hardware at all.

Safe by construction: the DAC tops out around 2.75 V, comfortably inside
the ADC's 0–3.3 V window. Nothing on that wire can overvoltage anything.

Deliverables:

- [x] BSP: clock init, UART printf, LED heartbeat, HardFault reporting
- [x] Loopback proven on both channels, both tracks agreeing to +/-2 codes
- [x] Real DAC endpoints measured: **546 mV to 2760 mV**
- [x] ADC linearity: 171-172 codes per 256 DAC codes, flat across range
- [x] Multiplexer crosstalk baseline: +/-1 code at slow tracking
- [ ] TC-triggered ADC with PDC ping-pong
- [ ] TC-triggered DAC playback
- [ ] End-to-end latency, actual trigger rate, dropped-sample count

What Phase 1 deliberately does **not** prove: noise, loading, or cable
effects. A two-inch jumper with a shared ground hides all of those. They
belong to Phase 3.

### Phase 2 — Host streaming

- USB bulk streaming of capture buffers (see `docs/protocol.md`)
- **Measure actual sustained USB throughput** — this is the single
  unknown that determines whether continuous capture is viable
- Host application: deframe, verify sequence continuity, FFT, live plot
- Burst (scope) mode first; continuous (spectrum) mode second

### Phase 3 — Analog front end

Only after the digital path is proven:

- Input: protection clamps, switchable attenuator, mid-rail bias for
  bipolar signals, buffer op-amp per channel
- Output: op-amp stage to rescale the awkward 0.55–2.75 V DAC window,
  plus a reconstruction filter
- Anti-aliasing filters — one per active channel

### Phase 4 — RTOS variant

The same drivers linked against a FreeRTOS application, to compare
against the bare-metal build. See `docs/rtos.md`.

## Performance targets

Derived in `docs/architecture.md`; summarised here.

```
MCK                     84 MHz
ADCClock (PRESCAL=1)    21 MHz            (datasheet max ~22 MHz)
Conversion              ~21.5 ADC clocks  (measured, minimal TRACKTIM)
Aggregate rate          976,744 sps       (measured ceiling, not 1 Msps)
```

The SAM3X8E has **one** ADC behind a 16:1 multiplexer, not twelve ADCs.
Channels are sampled round-robin, so channel count divides the aggregate
rate rather than multiplying throughput.

| Channels | Per-channel | Nyquist | Realistic usable BW |
|---|---|---|---|
| 1 | 976 ksps | 488 kHz | ~150 kHz |
| 2 | 488 ksps | 244 kHz | ~80 kHz |
| 12 | 81.4 ksps | 40.7 kHz | ~20-30 kHz |

Per-channel figures are the measured 976,744 sps aggregate divided by
channel count. The 2-channel row is confirmed on hardware.

**Aggregate data rate is 1.95 MB/s regardless of channel count**
(976,744 sps x 2 bytes). Twelve channels costs no extra USB bandwidth; it
costs per-channel sample rate. 12-bit packing would reduce this to
1.47 MB/s at the cost of the channel tag.

Expect the practical per-channel rate to land lower than the table —
raising `TRACKTIM` to suppress multiplexer crosstalk on high-impedance
sources cuts aggregate throughput. Plan for **50–85 ksps/channel** in a
12-channel configuration.

## Success criteria

Phase 1 is complete when the host can plot a DAC-generated waveform
captured through A0, with a reported dropped-sample count of zero over a
sustained run, and a measured figure for DAC range and USB throughput.

## Non-goals

- On-target FFT or filtering
- Simultaneous (non-multiplexed) sampling — the silicon cannot do it
- Matching commercial scope bandwidth; ~100–200 kHz single-shot is the
  realistic ceiling for this hardware
- 5 V tolerance anywhere — the SAM3X8E has none
- Sharing source between the arduino-cli and CMake tracks

## Open questions

Carried forward; each needs measurement or a datasheet check, not a
guess.

1. Sustained USB CDC throughput on this host — unknown until measured.
   Community reports scatter across 0.5–2 MB/s, which straddles the
   2.1 MB/s target.
2. ~~CDC bulk endpoint `wMaxPacketSize`.~~ **Resolved**: 512 bytes,
   2-bank, read from `arduino:sam@1.6.12` source. Already optimal; no
   tuning available. See `docs/hardware.md`.
3. Whether SRAM bank 0 and bank 1 sit on separate bus-matrix slaves.
   **Partially answered**: the memory map is confirmed from Atmel's
   linker script. Bank 0 is 64 KB and bank 1 is 32 KB, made contiguous
   by an alias at `0x20070000`; bank 0 is also visible at `0x20000000`.
   `linker/sam3x8e_flash.ld` now exposes them as separate regions with a
   `.sram1` section for explicit placement. Whether they are distinct
   bus-matrix *slaves*, and therefore whether placement actually removes
   contention, still needs the datasheet's bus matrix chapter and a
   measurement.
4. Exact ADC conversion cycle count under the chosen `TRACKTIM` and
   `SETTLING` values.
