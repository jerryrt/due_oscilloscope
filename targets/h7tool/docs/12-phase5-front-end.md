# Phase 5a: the front-end shift register works; the gain table, measured

## The bug that hid it (image7a to 8c)
`adc_init` configured PI9 (shift clock) and PI4 (latch) before the GPIOI clock
was enabled (the USB pin setup, later in `Reset_Handler`, enables it), so
those two pins never became outputs and the 74HCT595 never received a clock or
a latch. Read back from the unit: `GPIOI MODER` had both pins analog.
Everything about "gain and coupling had no effect" in docs/10 was this. Fixed
in image8d by enabling GPIOI in `adc_init`. The readback request is OUT/IN
0x05 (`h7_usb_probe.py pins`).

## What the register does (schematic D268-5 + measurement)
The schematic's scope module has Q0-Q2 on the gain mux select (A, B, C), Q3 on a
solid-state relay for CH1 coupling, Q4-Q6 and Q7 the same for CH2 (matching
docs/05 5.3). Measured: with Q3 = 1 CH1 passes the DAC0 step (DC); with Q3 = 0 it
reads the zero level (about 32,870) whatever DAC0 does (AC). `0x88` = both DC,
gain 0 (the stock's start state).

## Gain table (linux-x1, 2026-11-02)
Method: both channels AC-coupled at the same gain code, a 1 kHz sine from both
Due DACs at a per-gain amplitude (1.0 V peak down to 0.04 V), 1.5 s capture at
1 Msps, noise taken from the same capture with a flat DAC output and
subtracted in quadrature, codes per volt = rms x sqrt(2) / amplitude. Volts
from the H7 session's DAC0 fit (0.53722 mV/code; assumed for DAC1; the
amplitude uncertainty is common to all rows).

| gain code | CH1 codes/V | CH2 codes/V | factory (docs/05) | CH1 ratio | CH2 ratio | noise std CH1 / CH2 (codes) |
|---|---|---|---|---|---|---|
| 0 | 2319 | 2301 | 2285 | 1.015 | 1.007 | 69 / 89 |
| 1 | 4632 | 4602 | 4585 | 1.010 | 1.004 | 68 / 88 |
| 2 | 9266 | 9224 | 9199 | 1.007 | 1.003 | 73 / 93 |
| 3 | 18594 | 18489 | 18433 | 1.009 | 1.003 | 86 / 100 |
| 4 | 37292 | 37099 | 36982 | 1.008 | 1.003 | 126 / 123 |
| 5 | 74679 | 74240 | 74017 | 1.009 | 1.003 | 204 / 164 |
| 6 | 149486 | 148484 | 148187 | 1.009 | 1.002 | 368 / 258 |
| 7 | 298139 | 295882 | 296687 | 1.005 | 0.997 | 628 / 425 |

All eight codes switch the gain, the steps are the factory's (x2 per code), and
both channels land within 1.5 % of the factory table at every code. The
nearly constant CH1 ratio (about 1.009) points at the common volts reference
rather than the front end. The noise at the input grows with the gain as it
must when the dominant source is the Due's DAC (about 20 mV rms); the
H7's own noise floor needs a quiet source and is not measured here.
Range limits seen: at gain code 5 and above a DC level from this DAC
(0.56-2.75 V) is off range, so those codes are usable here only AC-coupled.

## Still open in phase 5
Calibration from the factory table applied on the host (the table is dumped in
`h7tool_backup`, location in the stock's flash/RAM struct not found, docs/05);
the offset of each gain code (the zero is near 32,800 but moves with gain);
skew between channels.
