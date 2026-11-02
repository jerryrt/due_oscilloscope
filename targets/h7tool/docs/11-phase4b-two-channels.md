# Phase 4b: CH1 and CH2 together (image8a, 8b)

`fw/image8/main.c`: image7's path for CH1 plus CH2 = ADC3 channel 1 (PC3_C) on
DMA2 stream 1 (DMAMUX request 115, mux channel 9, both inferred from the RM in
docs/05 and now seen to work), triggered by the same TIM3 update as CH1. The
version-4 payload is **planar** (`lib/wire/frame16.h`): with two channels a frame
holds 1016 samples of CH1 then 1016 of CH2, and `sample_rate_hz` is per
channel. Channel mask by vendor request OUT 0x13 (1, 2 or 3). 8b adds OUT 0x14
(SYSCFG PC3 analog-switch bit, not needed: CH2 worked without it).
The checker splits planes and reports each channel.

## Measured, linux-x1, 2026-11-02 (rev_id 0x2003, ADC clock setting 50 MHz = effective 25 MHz, docs/10)
- Integrity with both channels: 1, 2 and 2.5 Msps per channel, 5 s each:
  0 gaps, 0 lost, 0 bad CRC, 0 missed TC, 0 ADC overruns, delivered samples
  equal rate x time (12,499,848 against 12,500,020 at 2.5 Msps). Stream data
  rate at 2.5 Msps x 2 channels is 10 MB/s.
- Both channels follow their own DAC and are not swapped. DAC0/DAC1 code pairs
  (512, 3584), (3584, 512), (1536, 2560), (2048, 2048) gave CH1 means 34753,
  38573, 36058, 36664 and CH2 means 38522, 34689, 37237, 36584.
- Fits against the H7 session's DAC0 volts formula (not re-measured; DAC1 was
  assumed to follow the same one): CH1 2310 codes/V, zero at 32843, worst
  residual 23 codes; CH2 2323 codes/V, zero at 32750, worst residual 15 codes.
  Factory gain-0 value for CH1 is 2285 (docs/05); CH2 is within 1 % of it.
  Two channels agree to 0.5 %. These are DC checks against a noisy source
  (about 20 mV rms, ~46 codes) and an unverified volts reference, so they do
  not establish absolute accuracy.
- A wiring error (twice: a missing GND, then CH2) looked like dead channels both
  times; the owner found and fixed both.

## Not established
Simultaneity of the two channels: both are triggered by one TIM3 event, which
makes it true by construction, but no edge test has measured the skew (needs a
common step on both inputs). Gain and coupling control (docs/10, open). Any
rate above 2.5 Msps for two channels (docs/10 explains why the guard is there).

## Erratum (docs/18)
The two channels were NOT guaranteed to pair sample for sample before build 13: the ADCs were started by two writes that could
straddle a trigger, leaving CH2 one trigger behind CH1 in some runs. The DC checks here are unaffected. Fixed and measured in docs/18
(skew within about 30 ns).
