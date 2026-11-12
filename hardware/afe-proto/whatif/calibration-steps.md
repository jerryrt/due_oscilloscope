# Version 1 calibration: step list and time estimate

Version 1 (hands-off ratio switch U12), one range (+-5 V, D18), ADS1115 on I2C (D15), 1 % Basic parts (D19), the
data-taking and warm-up rules of `docs/afe.md` PA-3 and D21 (origin/main, a5e9ef9 and 6d8c698). Circuit: `kicad/design.py`:
ADS1115 AIN0 = sense tap (R7/R8 100k + 100k, k = 1/2), AIN1 = VREF, AIN2 = TAP5 (2.4375 V), AIN3 = TAP2 (0.75 V); U12 (D9):
S1 = TAP5, S2 = VREF. Every figure is sourced or marked *(check)*; "assumed" means no measurement or document gives it.

## Rates used (sources)

| quantity | value | source |
|---|---|---|
| ADS1115 conversion time T | 1/DR: 1.163 ms at 860 SPS, 7.8125 ms at 128 SPS, 125 ms at 8 SPS; DR error +-10 %, so T up to 1.111 x nominal (1.292 ms at 860) | datasheet 7.3.6, Electrical Characteristics |
| ADS1115 settling | "settle within a single cycle": one conversion after an input change is already clean; in continuous mode conversions run back to back | datasheet 7.3.6, 7.4.2.2 |
| ADS1115 noise, +-4.096 V | 125 uV rms at every rate from 8 to 860 SPS (860 SPS: 267 uV pk-pk) | datasheet Table 6-1 |
| ADS1115 INL | 1 LSB max **at 8 SPS and +-2.048 V only**; not given at 860 or 128 SPS, or at +-4.096 V | datasheet *(check)* |
| ADS1115 RDY | the design leaves ALERT/RDY unused (`design.py`), so conversion boundaries are not signalled | `design.py` |
| I2C read | about 0.1 ms per read, 0.3 ms for start-conversion + read, at 400 kHz | derived from clocks; bus speed not set in the design *(check)* |
| Control query | 1.0 ms (`CTL_OP_TEMP` included); capture start/stop 0.22 s | PA-3 / D21 text (measured on `linux-x1` per the spec lead) |
| Due ADC | 523,256 Hz trigger = 1,046,510 sps aggregate at the ceiling; **200 kHz where capture and playback together are loss-free** | CLAUDE.md (RC 86; duplex loss starts at 1.71 MB/s combined, the front end pins 200 kHz) |
| Due noise floor | 0.8 to 0.85 codes rms = 2.9 mV rms at the input (3.47 mV per code) | `afe.md` 4.1 / SC-6; `values.md` SC-4 |
| AWG settling | 396 ns for a DAC step; tee and cable RC about 13 ns (cable capacitance assumed) | `sim/awg/report.md`; *(check)* |

## The sweep pairing: dwell, data rate, conversions per level

A step lands at a random phase in the free-running ADS1115's conversion cycle, so the conversion in progress at the step
mixes the old and new level. The next conversion starts after the step and is clean (single-cycle settling). The worst case
puts the step just after a start: the straddler ends T later, the clean one 2T after the step. So **every level has at
least one whole clean conversion only if dwell D >= 2 x T_max**, where T_max is T at the datasheet's -10 % rate. Reading the
latest result no more than D - 2T_max before the next step guarantees it is a clean one, whatever the phase.

| option | rate | T (nominal / max) | minimum dwell 2 T_max | dwell used | sweep, 1024 levels | clean conversions per level |
|---|---|---|---|---|---|---|
| (a) | 860 SPS | 1.163 / 1.292 ms | 2.58 ms | **3 ms** | **3.07 s** | 1 guaranteed, 2 in 67 % of levels (derived: 2 fit when the phase offset is under 0.67 ms) |
| (a') | 860 SPS | same | 2.58 ms | 2.4 ms (nominal 2T = 2.33) | 2.46 s | **not guaranteed**: fails at a -10 % rate (needs 2.58 ms) |
| (b1) | 250 SPS | 4.0 / 4.44 ms | 8.9 ms | 9 ms | 9.2 s | 1 |
| (b2) | 128 SPS | 7.8125 / 8.68 ms | 17.4 ms | 18 ms | 18.4 s | 1 |
| (b3) | 8 SPS (the INL-specified rate) | 125 / 139 ms | 278 ms | 280 ms | 287 s (4.8 min) | 1 |
| (c) | 128 SPS, ADS read only every 4th level | 7.8125 ms | 17.4 ms on a read level | 3 ms otherwise | 1024 x 3 ms + 256 x 15 ms = 6.9 s | 1 per read level |

**Noise is the same in every row.** 125 uV rms at the pin (Table 6-1), 250 uV referred to the AWG at k = 1/2. With one clean
conversion per level and 1024 levels, the fit's gain error from ADS noise is 250 uV / (sqrt(1024) x 0.577 V) = 0.0014 %
(derived, 1.4 % of SC-7's 0.1 % fit share), offset 7.8 uV. So the rate is chosen by time and by INL, not noise; only
8 SPS has a specified INL, and the INL is not averaged by anything but the number of levels.

**(c) does not pay.** The ADS is the reference for the AWG's level, which is DC between steps; but a level the ADS did not
read has an AWG level known only from its code, so the DAC's own DNL (datasheet +3 LSB, `sim/awg/report.md`) enters
uncorrected, and the fit reduces to the 256 read levels: 0.082 % against 0.042 % at 1024 (PA-3), for a sweep (6.9 s) slower
than (a). At 860 SPS the ADS is not the limit, so there is nothing to save by reading less often.

**Recommended: (a), 860 SPS continuous, 3 ms dwell, 1024 levels, one read of the latest conversion per level at
(step + D - 0.3 ms), so the read is one whole conversion inside the dwell** (3 - 2.58 = 0.42 ms of margin, 0.3 ms used for read
jitter). The host reads once per level, not by polling for new data, because without RDY it cannot tell a new conversion
from a repeated one. Sweep 3.07 s plus 0.22 s capture start/stop.

Open items on that pairing: the host must know each step's time on the ADS's clock to within about 0.4 ms, and nothing in the
firmware stamps it today (the control channel's clock-offset round trip is the likely route) *(check)*; a 1.0 ms
control query per read is close to the 1.16 ms period and reads would be better buffered on the device *(check)*; the ADS1115's
INL at 860 SPS is not specified (VT-21) *(check)*. Playback and capture run at 200 kHz trigger so the duplex stays below the
measured loss threshold; 3 ms is then 600 samples per channel per level, which makes the Due's noise 2.9 mV / sqrt(600) = 0.12 mV
per level, 0.0003 % on the slope (derived).

## Procedure

| # | who | step | arithmetic | time |
|---|---|---|---|---|
| 0 | user | Fit the BNC tee on the AWG output, two equal cables to CH1, CH2, no termination. Power the board and start the host's calibrate command | assumed 60 s *(check)* | 60 s |
| 0w | host | **Warm-up, measured (PA-3, D21).** Done when both: (a) `CTL_OP_TEMP` changes by under 0.1 K/min and (b) the Due's reading of one ladder tap (TAP5) against the ADS1115's reading of the same tap changes by under a third of the 0.1 % fit share, 0.033 %, per minute. Fallback 15 min (PW-7, PA-3) where either cannot be read; on v1 both can. The cold-board time is **what VT-18 measures**; estimate below. Nothing to do for a board already on and settled: the check passes at its floor | see below | 3 to 15 min, **expected about 7 *(check)*** |
| 1 | host | Handshake: `v` identity, ADS1115 config readback, VREF within tolerance, both U12 states toggle; stop with a message on any miss | about 10 ADS reads = 0.08 s + commands, assumed 0.5 s *(check)* | 0.5 s |
| 2 | host | **Ladder and AREF read.** U12 to S2 (so TAP5 is not loaded by the sense divider), AWG at 0 V. ADS reads VREF, TAP5, TAP2, 16 readings each at 128 SPS; then the Due reads A2..A7, 4096 samples per tap (the Due does not read taps while the ADS converts, PA-3). Gives the Due-ADC fit and AREF (PA-8) | ADS 48 x (7.8125 + 0.3) ms = 0.39 s; Due 24,576 / 1,046,510 = 23.5 ms (powercal C4-c) + 0.22 s start/stop | 0.63 s |
| 3 | host | **Ratio measurement**, AWG at 0 V. U12 to S1: tap, TAP5, VREF; U12 to S2: tap, VREF; 64 readings each at 128 SPS. k = (tap(S2) - tap(S1)) / (VREF - TAP5) | 5 x 64 x 8.1125 ms | 2.6 s |
| 4 | host | **Level sweep**: one host-fed DAC staircase (the firmware's playback) of 1025 levels, the first discarded (CLAUDE.md), shuffled order so drift cannot alias into slope; both scope channels captured continuously at 200 kHz; the ADS1115 free-running at 860 SPS, one read per level as above | 1025 x 3 ms = 3.08 s + 0.22 s start/stop | 3.30 s |
| 5 | host | **Drift check**: the ratio again with 16 readings, and a Due-only ladder re-read | 5 x 16 x 8.1125 ms = 0.65 s; 0.22 s + 5 ms | 0.87 s |
| 6 | host | **Fit and store.** Due-ADC code to pin volts from TAP2, TAP5, VREF; AWG voltage per level V = (tap - (1-k) VREF) / k; per channel a least-squares gain and offset of the Due's volts on V over all levels, using the per-level mean of the 600 samples. Stored per board (Due serial) as JSON: gain, offset, k, VREF, AREF, taps, build id, time, temperature code, residual figures | numpy on 1024 x 2 points, negligible *(check)*; file write assumed 0.5 s | 0.5 s |
| 7 | host | **Verify** (VT-23's residual check on the calibration's own data): hold-out residual (fit odd levels, test even), per channel rms and maximum; implied gain error under 0.1 %; k within 0.5 +- 1 % and its step-5 drift under 0.02 %; ladder fit residual under 0.5 LSB (PA-9). A miss refuses to store | within step 6 | 0 s |
| 8 | user | Remove the tee and cables | assumed 30 s | 30 s |

### The cost of the warm-up check itself

One check cycle, every 10 s *(assumed interval)*: `CTL_OP_TEMP` between captures (1.0 ms; the device refuses it while one is
armed); the ADS1115 reads TAP5, 16 readings at 128 SPS = 16 x 8.1125 ms = 0.13 s (31 uV mean noise, 0.0013 % of 2.4375 V); the Due
captures TAP5, 4096 samples (about 5 ms at one channel, 886,363 sps, CLAUDE.md) plus the 0.22 s start/stop. About 0.36 s per cycle,
3.6 % duty, with the AWG idle. A rate per minute needs a window of readings spanning minutes, so the **floor is about 3 minutes** of reads
(18 cycles, 6.5 s of work; "a few minutes" is an assumption *(check)*), whatever the board does. The criterion's resolution is far
below its limit: 0.033 % of 2.4375 V is 0.8 mV per minute against a difference resolved to tens of microvolts (derived).

**Expected end of warm-up.** `whatif/tee/report.md` estimates a self-heating rise of about 3 K with a time constant of about 3 min
*(check: a rough estimate of 16 g of FR4 at 9 K/W and 0.3 W)*. The rate is (dT/tau) e^(-t/tau); it falls below 0.1 K/min at
t = tau ln(dT / (0.1 tau)): tau 2 / 3 / 5 min gives 4.6 / 6.9 / 11.5 min *(derived from that estimate, check)*. Criterion (b)
is likely looser for the ladder's ratio (1 % parts at 100 ppm/K worst case drift 0.017 % per K, 0.336 % per 20 K, EN-1/D19, so about
0.017 % per minute at the start for the 3 K above, under 0.033 %) but the Due ADC's own drift against the ADS1115 is not known *(check)*.
So criterion (a) is the likely binding one, at about 7 min, between the 3 min floor and the 15 min fallback. VT-18 sets it.

## Totals

| total | time |
|---|---|
| host-active, steps 1 to 7 | 0.5 + 0.63 + 2.6 + 3.30 + 0.87 + 0.5 = **8.4 s** |
| warm board, tee fitted and removed (60 s + 30 s as assumed) | 8.4 + 90 = **about 98 s, 1.6 min** |
| cold board | 1.6 min + warm-up: **about 5 to 17 min, expected about 9** *(check)*; the warm-up is what VT-18 measures (floor 3 min, fallback 15 min) |

Against the earlier draft (34 s host, 2 min warm, 17 min cold) the 20 ms level-set assumption is gone: the sweep is 3.3 s instead of 29.3 s.

## Where the time goes, and what shortening costs

| rank | cost | time | if shortened | effect (SC-7 numbers) |
|---|---|---|---|---|
| 1 | Warm-up | about 7 min expected, 3 to 15 | stop before both criteria hold | the gain still moves: criterion (a) is 0.1 K/min, about 0.0017 % per minute at 0.017 % per K (derived), small against the 0.17 % allowance of 10 K; but the 3 K already ahead uses up to 0.05 % of it (EN-1, D19). Leaving the board on makes it free |
| 2 | Level sweep | 3.30 s: 3.08 s of dwell, 0.22 s capture start/stop | 256 levels: 0.77 s + 0.22 s, saves 2.3 s | fit share rises from 0.042 % to 0.082 % (PA-3), leaving 0.018 % for everything else; D21 says 256 already meets the share, the old figure for the ratio alone was 0.033 % on the old ADC. Kept at 1024. A dwell under 2.58 ms loses the guarantee of a clean conversion |
| 3 | Ratio measurement | 2.6 s (+0.65 s check) | 16 readings, saves 1.9 s | random error of k 0.009 % to 0.018 % (0.0703 % / sqrt(n), derived from 125 uV and the 0.28 V and 0.56 V spans); enters the gain 1:1. At 860 SPS the 64-reading ratio would take 0.47 s, but at an unspecified INL; its INL term is not averaged by n and not re-run for this part *(check, VT-21)* |

Handshake, fit and store (0.5 s each, assumed) and the three capture start/stops (0.66 s together) are the remainder.

## How often, and what the user does between

- Repeat at first use, and after a temperature change of more than 10 K since the last calibration (EN-1; D19 keeps 10 K, so DF-3
  after calibration is 42 dB, 43.6 dB at the signed corner, `values.md` section 3).
- The ADS1115 has no sensor, but the Due's on-die sensor (`CTL_OP_TEMP`) is read at every calibration and stored; it follows the Due's die,
  not the REF3030E or the 1 % parts, so a change in it is a proxy for the 10 K rule, not a measure *(check; VT-12 sets the threshold)*.
- Between repeats: remove the tee and cables (nothing in normal use depends on them, MC-10); leave the board powered if use is soon, so no warm-up
  is needed; the host applies the stored fit and at session start repeats step 2's Due-only ladder read (about 0.3 s, no tee) to catch the Due
  converter's drift. That does not re-check the scope inputs' dividers: only the tee run does.
- The AWG covers about 23 % of the +-5 V range, so the range's ends are an extrapolation of a +-1 V fit (PA-3); VT-23's 10 mV sweep across the whole range
  cannot be made with the tee alone.
