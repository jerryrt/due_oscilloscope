# Phase 6d: the swing cap raised in steps (large-signal behaviour)

Done on the owner's instruction, 2026-11-02. Method: `h7_awg_sweep.py large` with `H7_OBS=1` (VOUT on CH1,
Due disconnected from the H7, shared ground). The host-enforced cap (`h7_awg.set_swing_limit`) is raised through
+-4, +-6, +-8 and +-9.5 V in turn, each step's checks (DC within 0.3 V of the stock calibration, 10 kHz sine within
5 % and under 3 % THD) gating the next. The ceiling is `HARD_LIMIT_CODES` = 1600 codes (about +-9.6 V), under the
+-10 V the output stage is specified for and inside the scope input's +-13.8 V; it is not raised by this run, and the
script returns the cap to 330 codes when it ends. The firmware reads no codes (invariant 1). The observer is the H7's
own CH1 at gain 0, so every volt below is its reading, not a reference instrument's.

## Results (5 MS/s update for the sine and square, 1 MS/s for DC)
| cap | DC: code reads / stock (mV difference) at -V, 0, +V | 10 kHz sine peak (ideal), THD | 50 kHz | 100 kHz | 10 kHz square: span, 10-90 % rise |
|---|---|---|---|---|---|
| +-4 V (668 codes) | +28 / +19 / +10 | 3.953 V (3.997), 0.06 % | 3.450 V, 0.46 % | 2.514 V, 2.87 % | 7.98 V, 4200 ns |
| +-6 V (1002) | +33 / +20 / +1 | 5.928 V (5.995), 0.05 % | 5.123 V, 2.10 % | 3.110 V, 9.17 % | 11.99 V, **row discarded** |
| +-8 V (1337) | +41 / +19 / +10 | 7.907 V (7.999), 0.07 % | 6.192 V, 7.94 % | 3.180 V, 10.82 % | 16.03 V, 8120 ns |
| +-9.5 V (1587) | +43 / +20 / +1 | 9.391 V (9.495), 0.09 % | 6.418 V, 10.45 % | 3.189 V, 11.12 % | 19.02 V, 9600 ns |
The +-6 V square row reads a 40 ns edge: the edge detector caught noise on that capture. It is excluded, and the
other three agree. Observer noise on a DC level is 28-33 mV rms. No underruns anywhere.

## What it shows
- **Static level:** the output follows the stock calibration to within 1-43 mV from -9.5 V to +9.5 V (about 0.4 %
  of 10 V), with no clipping or compression. This is consistency between the stock calibration and the H7's own
  reading of VOUT, not an absolute accuracy: the observer and the calibration share their origin.
- **Low frequency, full swing:** a 10 kHz sine is clean at every step: -0.09 to -0.10 dB against ideal, THD 0.05-0.09 %.
- **Large signals are slew limited.** The 100 kHz tone saturates near 3.2 V peak however hard it is driven
  (3.11, 3.18, 3.19 V at 6, 8 and 9.5 V), the 50 kHz tone's amplitude and THD degrade as the cap rises, and the
  square's edge time grows with its span. Two independent figures give the slew rate: the square edges,
  0.8 x span / rise = 1.52 / 1.58 / 1.58 V/us at +-4 / +-8 / +-9.5 V, and the saturated 100 kHz fundamental
  (3.19 V is a triangle of 3.93 V peak, 2.5 us a quarter period) = 1.57 V/us. About **1.55 V/us** *(derived)*.
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
