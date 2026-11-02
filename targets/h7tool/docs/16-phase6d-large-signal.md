# Phase 6d: the swing cap raised in steps (large-signal behaviour)

Done on the owner's instruction, 2026-11-02. Method: `h7_awg_sweep.py large` with `H7_OBS=1` (VOUT on CH1,
Due disconnected from the H7, shared ground). The host-enforced cap (`h7_awg.set_swing_limit`) is raised through
+-4, +-6, +-8 and +-9.5 V in turn, each step's checks (DC within 0.3 V of the stock calibration, 10 kHz sine within
5 % and under 3 % THD) gating the next. The ceiling is `HARD_LIMIT_CODES` = 1600 codes (about +-9.6 V), under the
+-10 V the output stage is specified for and inside the scope input's +-13.8 V; it is not raised by this run, and the
script returns the cap to 330 codes when it ends. The firmware reads no codes (invariant 1). The observer is the H7's
own CH1 at gain 0, so every volt below is its reading, not a reference instrument's.

## Erratum: the first run of this test used a flawed capture window
The first version of this document (commit 365be80) came from captures that included the output being shut down
after the measurement: the cleanup ran before the capture was sliced, so the tail (output parked at 0 V) was in the
data, sometimes cut off by a frame gap and sometimes not. That lowered every fitted amplitude by about 0.03-0.05 dB,
inflated some distortion figures slightly, and produced the one bad edge row (40 ns at +-6 V). The window is fixed,
every ETS capture is now integrity-checked (split-half agreement) and recorded, and the whole test was rerun; every
measurement below was valid on the first try. The records are in `../records/awg.jsonl` (build 12, observer CH1).

## Results (rerun, 5 MS/s update for the sine and square, 1 MS/s for DC)
| cap | DC: mV difference from the stock calibration at -V, 0, +V | 10 kHz sine peak (ideal), dB, THD | 50 kHz | 100 kHz | 10 kHz square: span, 10-90 % rise / fall |
|---|---|---|---|---|---|
| +-4 V (668 codes) | +27 / +19 / +10 | 3.968 V (3.997), -0.06, 0.06 % | 3.457 V, 0.46 % | 2.522 V, 2.87 % | 7.98 V, 4240 / 4200 ns |
| +-6 V (1002) | +32 / +19 / 0 | 5.949 V (5.995), -0.07, 0.05 % | 5.139 V, 2.10 % | 3.118 V, 9.16 % | 11.96 V, 6080 / 6000 ns |
| +-8 V (1337) | +41 / +20 / +9 | 7.935 V (7.999), -0.07, 0.07 % | 6.210 V, 7.94 % | 3.189 V, 10.82 % | 15.97 V, 8080 / 7960 ns |
| +-9.5 V (1587) | +43 / +18 / -1 | 9.420 V (9.495), -0.07, 0.08 % | 6.438 V, 10.45 % | 3.199 V, 11.12 % | 18.95 V, 9560 / 9440 ns |
Observer noise on a DC level is 28-33 mV rms. No underruns, no rejected capture.

## What it shows
- **Static level:** the output follows the stock calibration to within 0-43 mV from -9.5 V to +9.5 V (about 0.4 %
  of 10 V), with no clipping or compression. This is consistency between the stock calibration and the H7's own
  reading of VOUT, not an absolute accuracy: the observer and the calibration share their origin.
- **Low frequency, full swing:** a 10 kHz sine is clean at every step: -0.06 to -0.07 dB against ideal, THD 0.05-0.08 %.
- **Large signals are slew limited.** The 100 kHz tone saturates near 3.2 V peak however hard it is driven
  (3.12, 3.19, 3.20 V at 6, 8 and 9.5 V), the 50 kHz tone's amplitude and THD degrade as the cap rises, and the
  square's edge time grows with its span. Two independent figures give the slew rate: the square edges,
  0.8 x span / rise (rising / falling) = 1.51 / 1.52, 1.57 / 1.59, 1.58 / 1.60 and 1.59 / 1.61 V/us at +-4 / +-6 / +-8 / +-9.5 V, and the saturated 100 kHz fundamental
  (3.19 V is a triangle of 3.93 V peak, 2.5 us a quarter period) = 1.57 V/us. About **1.55-1.6 V/us** *(derived)*.
  That equals the OPA4171's typical 1.5 V/us (distributor listings; the TP2274 is listed at 20 V/us), so the
  OPA4171 is a likely fit for this unit; it is an inference from the number, not a reading of the chip.
- **The two limits:** below about +-2 V peak the response is the linear roll-off near 85 kHz (docs/15); above it the
  slew rate limits full-power bandwidth to f_max = slew / (2 pi A): roughly 26 kHz at +-9.5 V, 31 kHz at +-8 V,
  41 kHz at +-6 V, 62 kHz at +-4 V *(derived from the 1.55 V/us figure)*. The measured onsets fit: 50 kHz at +-4 V
  needs 1.26 V/us and is at THD 0.46 %; at +-6 V it needs 1.9 V/us and is at 2.1 %.
- The 5.6 us edge quoted in doc 13 for a +-1.8 V square came from a 400 ns observer and a 256-point table at
  250 kS/s; it is superseded by these ETS figures.

## Not covered
Absolute amplitude and level accuracy against a reference instrument; amplitudes beyond the 1600-code ceiling (the
stage's rails sit at about +-12.2 V); the 0-20 mA output; step settling at small amplitude; whether the slew limit
moves with temperature or load (VOUT drove only an H7 scope input, 1 MOhm).
