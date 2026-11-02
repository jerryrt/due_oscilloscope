# Phase 6: the generator, component by component (image9a)

`fw/image9/main.c`: image8 plus the DAC1 channel 1 (PA4) path to the +-10 V
stage, with the stock's order (docs/05 section 6): PE3 high enables the
TPS65130 supply, then TIM6 update triggers the DAC, fed by DMA1 stream 5 (DMAMUX
request 67) from a 256-entry halfword table in D2 SRAM (0x30030000), built once
at start. Wave types DC, sine, square, ramp. Vendor requests: OUT 0x20 (wave,
amplitude in codes), OUT 0x21 (TIM6 period), OUT 0x22 (centre code), IN 0x06
(state). Tools: `h7_usb_probe.py wave|gperiod|gcenter|gen`. Stop parks the DAC at
the centre code and switches PE3 low.

## Safety, enforced in firmware
The stage reaches +-10 V. The stock's calibration pairs (code:mV) 500:-9190,
1500:-3212, 2500:+2771, 3500:+8755 give about 5.98 mV per code and 0 V near
code 2036. The firmware refuses (does not clamp) any request whose centre
offset plus amplitude exceeds 330 codes, about +-2 V, and any TIM6 period
below 400 ticks (500 kS/s update, an unproven bound). Raising either is the
owner's decision. Nothing may be connected to VOUT except an H7 scope input.

## Component 1: the digital chain (done, no wiring needed)
Measured on the unit, linux-x1, 2026-11-02, VOUT unconnected:
- Boot: PE3 low, DAC off. A request of amplitude 500 was refused (control
  transfer stalled) and the state did not change.
- Sine, amplitude 100 codes, period 800 ticks: PE3 reads 1, `DAC_CR` 0x1017
  (EN1, TEN1, TSEL1 = 5, DMAEN1), `DMA NDTR` and `TIM6 CNT` both move, and 40
  reads of `DOR1` span 1936 to 2135 (centre 2036 +- 100) in 35 distinct values.
  So TIM6 -> DAC trigger -> DMA table is working. TSEL1 = 5 as TIM6_TRGO is from
  memory of the HAL header, and it works *(it would not move otherwise)*.
- Stop: PE3 reads 0 and DOR1 2036.

## Component 2: the analog stage (measured with VOUT wired to CH2, owner's wiring)
CH2 at gain 0, DC coupled, 2.5 Msps (zero code 32750 and 2301 codes/V from
docs/12), Due DAC1 jumper removed, GND shared. Volts below are read by the H7's
own CH2, so they include its input stage.
- **Supply and DC:** with PE3 low and the generator idle, CH2 read 36809 (about
  +1.76 V): VOUT floats with the stage unpowered, which says nothing about the
  stage. With PE3 high, centre codes 1736, 1886, 2036, 2186, 2336 read 28733,
  30788, 32854, 34917, 36983. That is 13.75 ADC codes per DAC code, i.e. 5.975
  mV per code against the stock calibration's 5.98 (pairs 500:-9190 ... 3500:
  +8755). Residual from the line: under 2 codes. Offset: VOUT reads about +50
  mV at the stock's zero code (CH2's own offset is part of that; they cannot be
  separated without a second instrument).
- **Sine, amplitude 300 codes (1.795 V ideal), 977 Hz and 1953 Hz:** fundamental
  1.800 V at both (0.3 % high), mean +0.057 V, same amplitude at both rates.
  Peaks -1.89/+2.01 V include the noise (the capture's std is about 36 mV).
- **Square, +-300 codes:** the 10-90 % edge takes 14 samples at 400 ns = 5.6 us
  for a 3.1 V span, about 0.55 V/us. That is the stage *and* CH2's input stage
  together; which one limits is not separated.
- **Ramp** present and plausible (fundamental 1.149 V against 1.8 V peak).
- Firmware guard held: with the centre left at 2336 a 300-code amplitude was
  refused.

## Not yet
Host-fed playback (USB OUT by DMA into the DAC ring), update rates above 500
kS/s, amplitudes above +-2 V, the 0-20 mA output, and any measurement with a
reference instrument.
