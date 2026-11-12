# What-if: a BNC-tee calibration in place of the PA-3 injection (2026-11-11)

The four TMUX1119 injection switches and the 249 ohm injection branch are
replaced by a manual calibration: a BNC tee from the AWG output into both
scope inputs. The precision ADC reads the tee node through a sense divider,
and the Due reads both channels. The circuit is the 1 Mohm design (760k /
330k / 760k, 0.1 % 25 ppm/K, OPA354, range switch across RF). The owner
approved it on 2026-11-11 with four conditions, the ADS124S08, and a 0.1 %
fit share on ±5 V. Numbers are in results/*.json. Every check was broken
on purpose (guards in each file).

| script | what it gives |
|---|---|
| run.py | ngspice: DF-3 before and after calibration, 200 Monte Carlo draws and 6 corners per scenario |
| report.py | summary.json, the DF-3 tables |
| inl_study.py | Due INL in the fit and in the channel ratio |
| sense.py | the AWG-sense path, and C3-f for one off switch |
| sc2.py | SC-2 and SC-11 margin by a corner search |
| ads.py | the ADS124S08 sense options |

## Results

| item | ±5 V | ±1.25 V | limit |
|---|---|---|---|
| DF-3 after tee calibration, 0.1 % divider, INL not cancelled, 64 points (corner / MC min) | 47.5 / 50.6 dB | 50.9 / 55.7 dB | ≥ 44 dB |
| the PA-3 injection it replaces, with its own INL term | 44.8 dB | 44.5 dB | ≥ 44 dB |
| fit gain error (99.9 %, INL 1.2 LSB): 64 / 256 / 1024 points | 0.139 / 0.071 / 0.036 % | 0.029 / 0.016 / 0.008 % | |
| sense ratio measured on board (ADS INL max) + drift over 10 K | 0.033 % | 0.033 % | |
| fit + sense at 1024 / 256 points (linear sum; RSS) | 0.069 % (0.049 % RSS) | 0.048 % | 0.1 % / 0.05 % |
| 1 % Basic divider: before calibration, DC | 25.5 dB | 28.6 dB | ≥ 30 dB, fails |
| 1 % Basic divider: SC-2 / SC-11 margin | 98.9 mV | 63.9 mV | ≥ 80 mV, fails |

The ratio is measured at each calibration: a TMUX1119 moves the sense
divider's bottom end from Vmid to the 3.0 V ladder top while the AWG holds
one level. Trusted instead, a fixed 0.1 % ratio leaves 0.097 % plus 1.6 mV
of offset. The MCP3564's 2.08 Mohm input would load the 50 kohm tap by
2.35 %, ±0.97 %, so it would need a follower. The ADS124S08 does not, at its
typical 1 nA/V *(check: no maximum is given)*.

## Sense point against AW-4's 49.9 ohm

The model sensed after the 49.9 ohm, at the BNC, and that is the
recommendation: the measured node is the tee node. What is left unmeasured
is the cable, tee and contact resistance: 0.12 ohm against 990 kohm is
1.2e-7 *(check: no cable chosen)*. Sensed ahead of the 49.9 ohm, the drop
into the tee load would be a gain error of 0.035 % (2 x 100k divider) or
0.027 % (three 100k, k = 1/3), correctable only for the tee's load.

The divider then sits on the connector. With k = 1/2, AW-8 puts the tap at
−0.24 V, inside the −0.3 V absolute limit; with k = 1/3 it stays at
+0.38 V. The clamp current at −5 V forced is about 21 µA. The divider is a
permanent 200k or 300k load on the AWG output, to Vmid.

## Warm-up before calibration

It cannot be derived. PW-7 sets a hard minimum of about 15 s. The REF3030
datasheet gives a turn-on settling of 120 µs / 2 ms (an electrical start-up
only), thermal hysteresis of 25 ppm typ / 100 ppm max, and 24 / 40 ppm of
long-term stability over the first 1000 h. The op-amp and ADS124S08
datasheets give no warm-up drift. The board's heating is unknown: a rough
estimate (16 g of FR4, about 9 K/W in still air, 0.3 W) gives about 3 K with
a time constant of about 3 min *(check)*. After the tee calibration the gain
drifts at about 0.007 %/K on ±5 V, so calibrating cold uses part of EN-1's
±10 K window rather than costing accuracy.

Until it is measured: wait at least 15 s, then calibrate once the ADS
internal temperature changes by less than 0.1 K/min, or after 15 min.

Proposed VT: from a cold power-on at normal load, log once a second for
60 min the ADS internal temperature, the REF3030 as the Due reads it, a
held tee level on both channels and both ranges, and the ratio
self-calibration's k. Run it 3 times and drop the first. The warm-up figure
is the time until each channel's calibrated gain stays within 0.01 % of
its 60 min value. Record the rise and the time constant on each of the
three Dues.

## Procedure

1. Fit a BNC tee on the AWG output and run two equal cables to CH1 and CH2.
   Use no termination.
2. Wait for warm-up (above).
3. The host steps the AWG over ±1.0 V, or ±1.15 V if the DAC window
   allows. At each level the Due reads both channels at once (1e5 samples)
   and the ADC reads the tap and the divider's bottom end.
4. Measure the sense ratio (about 1 s) and re-read the ladder (PA-9).
5. Calibrate ±1.25 V with 256 points (about 1 min) and ±5 V with 1024
   points (about 4 min). At 0.13 to 0.27 s per point (derived from powercal
   C4-c, check), the whole run takes 6 to 7 min.

Repeat at first use and after any change of more than 10 K since the last
calibration (EN-1).

## Update: precision-ADC INL at the AWG node (re-run, 2026-11-11)

The fit and sense figures above modelled the precision ADC's INL at the AWG
as 84 µV (the MCP3564's level). Re-run with datasheet maxima
(results/inl_adc.json). Sense divider k = 1/3 unless stated; AWG ±1.0 V;
256 points on ±1.25 V, 1024 on ±5 V. Linear sum of fit, on-board ratio
measurement and 10 K drift; the range is per-point INL to an S-bow within
the AWG span (bound).

ADS124S08 (10 ppm FSR max, 60 µV at the pin, 180 µV at the AWG):
  ±1.25 V 0.069-0.086 %, ±5 V 0.092-0.109 %.
ADS1220 (15 ppm FSR max with the PGA enabled; ±4 ppm typ, no maximum,
with the PGA disabled; 90 µV at the pin, 270 µV at the AWG):
  ±1.25 V 0.088-0.113 %, ±5 V 0.111-0.136 %.

The ratio measurement dominates: 0.037 % (ADS124S08) and 0.056 %
(ADS1220) at k = 1/3, because (1-k)/k = 2 levers the INL error. More fit
points do not reduce it.

With k = 1/2 (2 x 100k):
  ADS124S08: ±5 V 0.074 % (0.091 % at the bound), ±1.25 V 0.051 %.
  ADS1220:   ±5 V 0.085 % (0.111 % at the bound), ±1.25 V 0.063 %.
  Cost: the AW-8 reset puts the tap at -0.24 V, inside the -0.3 V
  absolute limit, outside the ADS124S08's operating range (no reading is
  taken during a reset).

Recommended: ADS124S08, k = 1/2, 1024 points on ±5 V. An ADS1220 build
needs k = 1/2 and 2048 points on ±5 V (4096 at the bound), about 5-18 min.
