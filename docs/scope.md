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

### Phase 1 — Loopback bring-up (complete)

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
- [x] TC-triggered ADC with PDC ping-pong
- [x] TC-triggered DAC playback (flash table via gen, host-fed via play)
- [x] Actual trigger rate verified: ratio 1.000 up to RC 86, silent 2:1
      decimation past it; dropped samples counted in every frame header

What Phase 1 deliberately does **not** prove: noise, loading, or cable
effects. A two-inch jumper with a shared ground hides all of those. They
belong to Phase 3.

### Phase 2 — Host streaming (complete except live plot)

- [x] USB bulk streaming of capture buffers (see `docs/protocol.md`)
- [x] Sustained USB throughput measured: full in-spec ADC rate
      (1.83 MB/s) gapless on both tracks; transport ceilings far above
      it (see `docs/usb.md`)
- [x] Host application: deframe, sequence continuity, Goertzel tone
      verification (`host/receive.py`, `host/loopback.py`)
- [ ] Live plot / GUI - planned as a client/server split: a streaming
      daemon owning the ports and real-time threads, a GUI as a
      separate process over a local socket

A successor instrument - faster, more channels, or streaming over
USB 3 - is sketched in `docs/hardware-next.md`: what the host software
would keep, what has to be rebuilt, and the four questions that decide
which option applies.

### Phase 3 — Analog front end

Only after the digital path is proven:

- Input: protection clamps, switchable attenuator, mid-rail bias for
  bipolar signals, buffer op-amp per channel
- Output: op-amp stage to rescale the awkward 0.55–2.75 V DAC window,
  plus a reconstruction filter
- Anti-aliasing filters — one per active channel

### Phase 3.5 — Arbitrary waveform generator (working at 200 ksps)

Turn the board into a signal generator as well as a scope: the host
generates a waveform and streams it down to the DAC, instead of the DAC
replaying a table baked into firmware.

This is the mirror image of the capture path and reuses its shape: a ring
of buffers, PDC moving samples without the CPU in the data path, and an
explicit failure counter. The failure mode is the dual of overrun -
**underrun**, where the DAC needs a buffer the host has not supplied yet.
Underrun must be counted and reported, never concealed by silently
repeating the previous buffer.

Targets, from measurements already taken:

| Quantity | Measured | Implied data rate |
|---|---|---|
| DACC ceiling | 1,539,700 conv/s | 3.08 MB/s inbound |
| DAC matched to ADC | 976,744 conv/s | 1.95 MB/s inbound |
| ADC ceiling | 976,744 sps | 1.95 MB/s outbound |

So a symmetric full-duplex instrument needs about **3.9 MB/s combined**,
and pushing the DAC to its own ceiling while capturing needs about
**5.0 MB/s**. Duplex has since been measured at 2.77 in + 2.47 out =
**5.25 MB/s combined** with equal contention (see `docs/usb.md`), so
the symmetric instrument fits; the DAC-at-ceiling case needs the
direction balance biased toward OUT, or endpoint DMA.

Deliverables:

- [x] Bulk OUT path read on the device; playback ring fed from it
- [x] DACC driven by PDC from that ring, with underrun counted
- [x] Host sender streaming a generated waveform (`host/loopback.py`,
      with the empty-queue write policy `docs/usb.md` explains)
- [ ] Maximum sustained playback rate - 200 ksps verified solid; the
      push toward the DACC ceiling is a current objective
- [x] Full duplex: capture and playback simultaneously - the working
      loop runs 0.40 MB/s OUT + 0.84 MB/s IN with zero underruns
- [x] End-to-end proof through the loopback: host-sent 1 kHz sine comes
      back on A0 at 1371 +/- 2 codes (theoretical 1370.5) in every
      window; A1 flat

The loopback made this self-checking exactly as intended - including
catching the failures that were *host-side* all along (stale kernel
buffers, CDC-ACM write drops; see `docs/status.md`).

### Phase 4 — RTOS variant

The same drivers linked against a FreeRTOS application, to compare
against the bare-metal build. See `docs/rtos.md`.

## Performance targets

Derived in `docs/architecture.md`; summarised here. The project now
runs MCK at 78 MHz so the ADC clock sits inside its datasheet limit
(see `docs/hardware.md`, "Operating point"); the 84 MHz figures are
kept for comparison.

```
MCK                     78 MHz            (84 possible, ADC clock then 5% over spec)
ADCClock (PRESCAL=1)    19.5 MHz          (datasheet max 20 MHz - in spec)
Conversion              ~21.5 ADC clocks  (measured, minimal TRACKTIM)
Aggregate rate          ~907,000 sps      (RC 86; 976,744 at MCK 84)
```

The SAM3X8E has **one** ADC behind a 16:1 multiplexer, not twelve ADCs.
Channels are sampled round-robin, so channel count divides the aggregate
rate rather than multiplying throughput.

| Channels | Per-channel | Nyquist | Realistic usable BW |
|---|---|---|---|
| 1 | 907 ksps | 453 kHz | ~140 kHz |
| 2 | 453 ksps | 227 kHz | ~75 kHz |
| 12 | 75.6 ksps | 37.8 kHz | ~20-30 kHz |

Per-channel figures are the ~907 ksps in-spec aggregate at MCK 78
divided by channel count. The 2-channel row is confirmed on hardware:
453,488 Hz per channel declared, 453,489 measured, ratio 1.000.

**Aggregate data rate is ~1.81 MB/s regardless of channel count**
(907 ksps x 2 bytes). Twelve channels costs no extra USB bandwidth; it
costs per-channel sample rate. 12-bit packing would reduce this to
1.36 MB/s at the cost of the channel tag.

Expect the practical per-channel rate to land lower than the table —
raising `TRACKTIM` to suppress multiplexer crosstalk on high-impedance
sources cuts aggregate throughput. Plan for **50–85 ksps/channel** in a
12-channel configuration.

## Success criteria

Phase 1 is complete when the host can plot a DAC-generated waveform
captured through A0, with a reported dropped-sample count of zero over a
sustained run, and a measured figure for DAC range and USB throughput.

**Met** (verification is spectral rather than plotted: Goertzel
amplitude at the sent frequency, per device-time window): zero drops
over sustained runs, DAC range 546-2760 mV measured, transport
ceilings measured in all three directions. The waveform now even
originates on the host, which is Phase 3.5's bar, not Phase 1's.

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

1. ~~Sustained USB CDC throughput.~~ **Resolved by measurement**:
   **1.969 MB/s, gapless, at the ADC's full 976,744 sps.** Both tracks
   reach it, over ordinary CDC:

   | Trigger | Required | Track A | Track B |
   |---|---|---|---|
   | 200 kHz | 0.80 MB/s | 0.806, ratio 1.000 | 0.806, ratio 1.000 |
   | 400 kHz | 1.60 MB/s | 1.613, ratio 1.000 | 1.613, ratio 1.000 |
   | 488 kHz | 1.95 MB/s | 1.969, ratio 1.000 | 1.969, ratio 1.000 |

   An earlier answer here put the ceiling at 0.93 MB/s and concluded that
   continuous full-rate capture over CDC was impossible. That was wrong.
   The cap came from calling `(bool)SerialUSB` in the service loop, and
   `Serial_::operator bool()` ends with `delay(10)`. Time measured inside
   the write itself corresponds to about 8.9 MB/s. See
   `docs/status.md`.

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
