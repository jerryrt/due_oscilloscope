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

## Component 2: the analog stage (needs the owner's wiring)
Whether the supply comes up and the stage swings as the stock's pairs say is
not yet measured: there is no on-board monitor of VOUT (the "load voltage" ADC
channel is the target-load sense, not VOUT).
