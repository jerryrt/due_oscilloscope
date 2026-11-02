# Plan: the H7-TOOL as a 16-bit scope target

Decided 2026-11-02: the work lives in this repository as a hardware
target (not a Due track); the board has its own USB VID/PID; the
sample stream is a new frame version (`lib/wire/frame16.h`, version 4).
Facts below come from docs 01-05; items marked *(check)* are not read
from a source or measured.

## Rules that carry over
Invariants 1, 2, 5, 6, 7 and 8 of `CLAUDE.md` apply. Invariant 1 reads
"the CPU never touches sample data, and the buffers are non-cacheable"
(M7 data cache). Every image keeps the timer return to the boot loader
until a USB command can do it. Safety rules for flashing: `README.md`.

## Identity
USB 2.0 high speed, one port, composite device with a sample-stream
bulk IN function and a control function, mirroring the Due's two CDC
functions. Bench VID/PID `1209:0001` *(check: confirm it is still the
open test pair)*; a shipping identity needs an allocated pair. The
host's board finder must key on this pair, not on Arduino's.

## Phases (each ends in a gate)
1. **Enumerate.** EP0 with our own descriptors, then the composite
   layout; a vendor request returns the OTG_HS hardware-config
   registers (DMA architecture, FIFO depth, endpoint count) so sizing
   comes from the chip. Gate: `lsusb -v` shows it; no `-110`/`-71`.
2. **Bulk IN by DMA.** Counted pattern in a non-cacheable buffer sent as
   v4 frames. Gate: gapless on the bench, sequence and header CRC
   checked, byte conservation; rate compared with the Due's measured
   figure, quoted only once measured.
3. **Clock and timebase.** PLL1 400 MHz in the stock order, flash wait
   states first; a TIM3 update at a known rate. Gate: measured against
   the host's USB SOF (8 kHz) - no wiring, independent of the chip's own
   clock - not trusted from register arithmetic. Done: docs/09.
4. **ADC -> DMA -> USB, CH1 (ADC1) then CH2 (ADC3); done in docs/10, 11, with the
   accuracy question open.** 16-bit, TIM3-triggered, circular
   DMA into D2 SRAM at 0x3002xxxx (MPU non-cacheable). Gate: a DC level
   from the Due's DAC reads right against the stock calibration; no
   sequence gaps at the highest rate USB sustains.
5. **Front end, CH2, calibration (zero, noise, skew and matching measured: docs/12, 17, 18; scale still +-1 % without a reference voltage).** Gain/coupling shift register (PG5,
   PI9, PI4), ADC3 for CH2, calibration applied on the host. Gate:
   voltages across ranges against a reference (the Due only inside its
   0.55-2.75 V window).
6. **Generator (done through host-fed playback, update-rate ladder and ETS: docs/13, 14, 15).** PE3 supply, then TIM6 + DMA1 Stream5 playing a host
   fed buffer; no load and a capped code first. Gate: output measured
   on the scope input.
7. **Control channel and host.** Identity, status, counters; the
   daemon and GUI take the v4 parser and a device table. Gate: a trace
   from the H7 with no special-casing.
8. **Later.** 250M module, housekeeping channels.

## Open
Code-to-volts mapping and any oversampling shift (host side, from the
control channel); channel bit assignment in v4 `channel_mask`; whether
the Due ever moves to v4 (separate decision); the unit currently sits
in the boot loader with stock V2.33 not running.
