# Phase 3: the stock clock tree, measured (image6a)

`fw/image6/main.c` = image5 plus `clock_init()` and a clock meter. Sequence,
from stock V2.33 (docs/04 section 3): VOS1 (`PWR_D3CR |= 0xC000`, wait
VOSRDY), HSE on, PLL1 from HSE with M=5 N=160 P=2 Q=4 R=2 (VCO 800 MHz,
RGE 4-8 MHz range, wide VCO), flash latency 4, HPRE /2, APB1-4 /2, then
SYSCLK = PLL1. Every wait is bounded; on failure the image stays on HSI and
reports it. `FLASH_ACR` is written as latency only (`WRHIGHFREQ` left at 0,
which matters for flash programming and not for reads *(check)*). PLL3 and
USBSEL are not programmed: the ULPI core is clocked by the PHY.

## The meter
Reference is the host's USB start-of-frame, not the Due (no wiring needed, and
a USB host's SOF comes from its own crystal). Every 8000 SOFs the device
differences three counters: the CPU cycle counter (DWT), TIM5 (APB1 timer
clock, expected 200 MHz) and TIM2 counting TIM3's update event (TIM3 reload
199 at 200 MHz, expected 1 MHz; TIM2 clocked from TIM3 TRGO through ITR2
*(check the ITR mapping: it counted, so it is right here)*). Read with
`tools/h7_usb_probe.py clocks`.

## Measured, linux-x1, 2026-11-02
| quantity | per 8000 SOFs | nominal | ratio |
|---|---|---|---|
| CPU cycles | 400,001,698 | 400,000,000 | 1.0000042 |
| TIM5 | 200,000,850 | 200,000,000 | 1.0000042 |
| TIM3 update (via TIM2) | 1,000,004 | 1,000,000 | 1.0000040 |

Stable over three reads, windows 6 to 9. The SOF rate is therefore 8 kHz
(window = 1 s). The three ratios agree to 0.2 ppm, as they must (one clock),
and the +4.2 ppm is the sum of the HSE crystal's error and this host's SOF
error, which cannot be separated here; CLAUDE.md records a 17.5 ppm spread
between hosts' USB controllers. It is far below anything the converter
timebase needs to care about, and it says the trigger-rate mechanism used for
the ADC (TIM3 update as TRGO) produces its programmed rate.

## USB at the new clocks
The stream (image5 behaviour) is unchanged and clean at 400 MHz: 40.8 MB/s
against 40.3 at 64 MHz, 3 runs of 15 s, 0 gaps, 0 bad CRC, 0 bad payload in
the two runs after the first. The first run after enumeration begins 2048 bytes
into a frame (reported as one resync); it has now happened on both images and
the cause is not established *(check)*. 40.8 MB/s at a 6x faster CPU says the
re-arm loop was not the limit; the host path or the link is.
