# Phase 5b: zero, noise and the factory calibration (inputs shorted)

Method: `h7_awg_sweep.py zeronoise` with CH1 and CH2 each wired to their adjacent GND pin (owner, 2026-11-02),
DC coupled, nothing playing, `image11l` (build 12), 3 s per point at 1 Msps (period 200 ticks) and again at 2 Msps
(period 100). Records: `../records/awg.jsonl` (kind `zero_noise`). This measures the INPUTS at 0 V; VOUT is not
involved (it is not routed to any ADC: every VOUT measurement elsewhere used an external jumper from VOUT to a scope input).

## Results at 1 Msps (the 2 Msps rows differ by about 6 codes in zero and 8 codes in noise)
| gain | CH1 zero code | factory | diff (codes) | noise rms (codes / mV) | CH2 zero code | factory | diff (codes) | noise rms (codes / mV) |
|---|---|---|---|---|---|---|---|---|
| 0 | 32875.0 | 32657.0 | +218.0 | 65.8 / 28.78 | 32853.7 | 32723.0 | +130.7 | 81.9 / 35.91 |
| 1 | 32893.7 | 32676.0 | +217.7 | 65.0 / 14.17 | 32847.8 | 32718.2 | +129.6 | 82.5 / 18.08 |
| 2 | 32928.1 | 32712.4 | +215.7 | 64.0 / 6.96 | 32870.8 | 32708.2 | +162.6 | 81.7 / 8.90 |
| 3 | 33003.1 | 32785.4 | +217.7 | 64.9 / 3.52 | 32811.7 | 32688.8 | +122.9 | 85.0 / 4.63 |
| 4 | 33151.5 | 32931.2 | +220.3 | 62.4 / 1.69 | 32760.2 | 32650.2 | +110.0 | 86.5 / 2.35 |
| 5 | 33440.6 | 33227.6 | +213.0 | 62.4 / 0.84 | 32662.8 | 32572.8 | +90.0 | 80.6 / 1.09 |
| 6 | 34058.0 | 33815.6 | +242.4 | 64.9 / 0.44 | 32485.8 | 32417.0 | +68.8 | 76.7 / 0.52 |
| 7 | 35232.1 | 34990.6 | +241.5 | 64.6 / 0.22 | 32145.3 | 32108.2 | +37.1 | 75.3 / 0.25 |

## What it shows
- **The factory zero is not this firmware's zero.** CH1 reads 215-242 codes above the factory zero at every gain code (95 mV
  at gain 0), CH2 130 codes at gain 0 falling to 37 at gain 7. For CH1 the difference is roughly constant in codes, so it
  sits behind the gain stages (the ADC's level shifting or reference), not in the input amplifier. The measured zeros are
  now data (`data/measured_zero_d428-9.json`) and `h7_cal.Calibration.load_measured()` uses them with the factory scale.
  The stock firmware must apply some other correction or ADC setting that this image does not; not investigated.
- **The noise is the H7's own, and larger than I had said.** With the input shorted the rms scatter is 65 codes (CH1) and
  82 codes (CH2) at EVERY gain code, i.e. 29-36 mV at gain 0 and 0.22-0.25 mV at gain 7 referred to the input. Earlier documents
  attributed the 30 mV scatter in DC levels to the Due's DAC (about 20 mV rms) or to "the observer's floor"; most of it is the
  scope input itself. Sample-to-sample (high-frequency) scatter is 18-23 codes; the rest is slow (hum or drift).
  At gain 7 the noise floor is 0.25 mV rms, so small signals are best measured at a high gain code.
- **VOUT at the zero code reads 0 V.** Re-based on the measured zeros, VOUT at code 2036 reads 0.000 V on CH1 and
  0.000 V on CH2 (stock calibration: -5 mV). The +14, +45 and +50 mV "offsets" quoted in docs 13-16 came from zeros I had
  fitted against the Due and were not VOUT's.
- **Scale is still uncertain by about 1 %.** With the measured zero and the factory scale (2284.9 codes/V) VOUT at the
  stock calibration's +-9.49 V code reads +9.580 V and -9.569 V (that is 0.9 % and 0.8 % high), where my earlier fitted
  scale (2310) had agreed with the stock VOUT calibration to 0.4 %. The two factory calibrations (scope ADC and VOUT)
  disagree by about 0.9 % between themselves; which is right needs a reference voltage (a DMM). Until then every volts
  figure in these documents is good to about +-1 %.
