# Phase 5c: both channels on the same signal (image11m, build 13)

Wiring (owner, 2026-11-02): VOUT on BOTH CH1 and CH2, shared ground, Due disconnected from the H7. Method:
`h7_awg_sweep.py stepb`, both channels acquired at once (planar frames, 2 Msps each), measured zero codes and
the factory scale (`h7_cal.Calibration.load_measured`, docs/17), VOUT driven by host-fed playback. Records:
`../records/awg.jsonl` (kinds `dc2`, `skew`).

## A firmware defect this measurement exposed (fixed in build 13)
The first run gave channel phase differences of -0.1, +9.3, +0.1, +0.3 and +47 degrees across five tones, and two of the
"skews" were +519 ns and +524 ns - exactly one ADC period (520 ns). The two ADCs were started by two register writes about
a microsecond apart, which can straddle a TIM3 trigger, so CH2's k-th sample could be one trigger later than CH1's, and
the pairing changed from run to run. Fixed: with more than one channel, `acq_start` waits until TIM3 has just wrapped and
writes both ADSTARTs back to back, inside one trigger period. The measurement now refuses to run on a build below 13.
A DC row that came back NaN in the same run was a short capture printed as a result; DC rows are now validated and retried.

## DC, both channels at once (mV; difference from the stock VOUT calibration in brackets)
| code | stock | CH1 | CH2 | CH2 - CH1 |
|---|---|---|---|---|
| 2036 | -5 | -2 (+3) | 0 (+5) | +2 |
| 2203 / 1869 | +994 / -1004 | +1011 (+17) / -1023 (-19) | +1005 (+11) / -1017 (-13) | -6 / +6 |
| 2536 / 1536 | +2986 / -2997 | +3014 (+28) / -3026 (-30) | +3007 (+20) / -3015 (-18) | -8 / +12 |
| 3036 / 1036 | +5978 / -5986 | +6030 (+52) / -6034 (-49) | +6020 (+42) / -6025 (-40) | -10 / +9 |
| 3536 / 536 | +8970 / -8975 | +9057 (+86) / -9048 (-73) | +9040 (+69) / -9021 (-46) | -17 / +27 |
The differences from the stock VOUT calibration are close to odd-symmetric: the ADC scale (factory, applied to a measured zero) reads
the stock VOUT calibration about 0.9 % high on CH1 and 0.65 % on CH2, with offsets of +6 and +12 mV. CH1 and CH2 differ from each other by
0.25 % in scale. Which of the two factory calibrations (scope ADC or VOUT) is right is not decided here; it needs a reference voltage.

## CH2 against CH1 on a 200-code sine, 5 MS/s update (ETS, one capture per frequency)
| f kHz | CH2/CH1 amplitude (volts) | phase CH2 - CH1 | as a time |
|---|---|---|---|
| 10 | 0.9913 | -0.110 deg | -30.6 ns |
| 50 | 0.9890 | -0.016 | -0.9 |
| 100 | 0.9909 | -0.786 | -21.8 |
| 200 | 0.9877 | +0.319 | +4.4 |
| 250 | 0.9858 | +2.660 | +29.6 |
Skew: the phase differences are within +-0.8 degree up to 200 kHz and 2.7 degrees at 250 kHz, i.e. within about +-30 ns, 
with no clean trend with frequency. A least-squares line through the origin gives +16 ns with 0.9 degree residual. So CH1 and CH2
are sampled within about 30 ns of each other (a small fraction of the 500 ns sample period); this measurement cannot resolve less,
and repeatability across repeated captures was not measured. Before the fix the pairing was random by whole samples (520 ns).
Amplitude: CH2 reads 0.986-0.991 of CH1 for sines (0.994-0.998 for DC), falling slightly with frequency (-0.55 % from 10 to 250 kHz):
CH2's input is a little slower or lower in gain, small against the AWG's roll-off.

## Effect on earlier documents
Doc 11's two-channel DC checks are unaffected (levels, not timing). Its "simultaneity by construction" note was not true before
this fix for time-aligned use of the two planes; it is true to within the skew above after it.
