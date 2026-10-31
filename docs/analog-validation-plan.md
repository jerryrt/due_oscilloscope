# Re-taking the converters' analog figures at 90 MHz

**Status: plan. Nothing here is measured unless a row says so.**
[measurement-suite.md](measurement-suite.md) is the catalogue of what
this project measures about the converters and how a figure earns the
word baseline. This document does not repeat it. It says what the move
to a 90 MHz master clock changes, which rows of that catalogue are
re-taken on this bench, and which small pieces do not exist yet.

The only analog instrument on this bench is the DAC-to-ADC loop - DAC0
to A0, DAC1 to A1, A2 bare, a shield stacked on the board, no
oscilloscope. Every figure from an image at 78 MHz is an old reference:
another bench, another board, mostly unrecorded. It is read with a grain
of salt and **never as the arm a 90 MHz figure is compared against**. A
90 MHz figure is judged by its own repeatability and by the physics.

## What the loop can and cannot judge

| fact | consequence |
|---|---|
| The DAC's reference is the ADC's, so the loop is ratiometric | Codes are the unit. Volts and absolute rate need something from outside; `host/calibration.py` carries the one record, for the board it names |
| The DAC reaches about 676-3422 codes (`docs/noise.md`, measured levels; nominal 683-3413) | Gain and linearity are judged over that span only |
| A0 and A1 are one converter behind a multiplexer | The ADC's INL is common to both channels, so comparing them cannot separate it; what it separates is DAC0 from DAC1 |
| The loop cannot separate the DAC's noise from the ADC's | A noise figure is the loop's, and is named so |
| Per-code DNL needs a meter | Not attempted; see "What this bench cannot measure" in `measurement-suite.md` |
| Tone and sample rate are different things | A table of N points at `fs_dac` gives `f = fs_dac * c / N`. Keep the DAC rate an integer multiple of the ADC rate so the staircase's images fold onto the tone *(derived, confirm on the bench)* |
| The ADC clock is MCK/4 at every trigger rate | A rate ladder varies the sample rate, not the converter clock |
| The 789-938 ns rise is a scope reading at 78 MHz, never recorded | A loop figure is recorded beside it and does not replace it |

## Rules for every phase

| rule | source |
|---|---|
| Break each new or changed check on purpose and watch it fail | `CLAUDE.md` |
| Drop the first run of a repeated measurement, by index | `CLAUDE.md` |
| A threshold comes from a 90 MHz measurement and is never widened to pass | `tests/baseline.json` header |
| One threshold per property. A rate that misses it is the finding, not a reason for a per-rate threshold | here |
| An unmeasured figure is marked *(check)* | `CLAUDE.md` |
| Promote a figure through `--calibrate` and `baseline.measured.json`, once | `measurement-suite.md` |
| Declare the conditions: board serial, commit, shield, wiring | `host/provenance.py` |
| A null result says what the instrument could have detected | `CLAUDE.md` |

## Phases

| phase | goal | existing work to improve | exit evidence that can fail |
|---|---|---|---|
| **0. Rates computed from the clock** | No tool or test fixes a rate that was exact only at 78 MHz | A tree scan is the authority, modelled on the one in `tests/test_calibration.py`, with prose and synthetic signals excluded. Three are known to matter: `tests/test_loop_overruns.py` (its ceiling rate is now RC 99, not the ceiling), `tools/settletime.py` (its 202 kHz request lands on RC 222 and folds one sixth of the phases) and `tools/dso_metrics.py` (rate-keyed presets and a 78 MHz DAC ceiling). Tools that compute rates take MCK from the identity line or refuse when it differs from `measure.MCK_HZ` | A board-free test shows each tool's rate arithmetic equals `measure.hz_for(rc)` with `DUE_MCK_HZ` set to both clocks; a hard-coded rate planted in a tool fails the scan |
| **1. The existing ladder gets tone and crosstalk** | The matched loop is judged on signal quality at every rate, not on stream health only | `tests/test_rates.py` runs the RC ladders (two channels RC 780-86, one channel RC 390-44) and asserts rate, gaps and underruns. Add the tone and window-purity checks from `test_integrity.py` to its `_ladder_run`, and the A1-carries-no-tone check on two-channel rows. Keep Hz derived from RC. Count windows per run at the slow end and lengthen it until the window fraction means something | `run_loop(scale=0.9)` makes the amplitude check fail; a tone planted on A1 makes the crosstalk check fail |
| **2. DC transfer** | Gain and offset of the loop in one fit | `test_dc_transfer_tracks_the_code` is one test per code; `test_dc_levels_are_monotonic` holds the order. Fit across the codes in one test and compare the slope with `loop_slope_adc_per_dac_code` in `calibration.json`. Report in codes; convert to mV only with a calibration record for the board in hand. No DNL | A bent transfer (a code set with one level shifted) fails the fit |
| **3. Noise** | The loop's noise on a held code, in codes and noise-free bits | `phase0.py noise-fast` is the protocol, because it alone has a record and a repeatability figure (Track A and B only). Hold the code at mid-scale. When rates are compared, decimate or filter to a shared band first, as `docs/noise.md` shows the raw rms compares bandwidths | A planted noise term of known size is recovered; a held-code run with the ADC input open reads differently |
| **4. Rise and settling** | A scope-free rise and settling figure with full phase coverage | `tools/settletime.py`: choose the ADC request from the timer clock so its RC is prime, and refuse to report when fold coverage is below 1.0. Its agreement window against the stored scope range is wide enough to hide a coarse fold, so coverage is the check that matters | RC 222 is refused; the agreement test cannot pass a fold that covers one sixth |
| **5. Not in the tree** | The pieces nothing covers | See below | Each has a mutation |
| **6. Other 90 MHz checks the loop can run** | The two items `hardware.md` lists as unmeasured | The wrap displacement runs through `docs/issue5-campaign.md`; runs past 150 s through the existing soak tools | Per those documents |

## Phase 5: what does not exist

Searched in `tests/`, `tools/` and `host/` for SINAD, THD, SFDR, INL and
ENOB: only the building blocks in `host/noise.py` exist.

| missing | built from | note |
|---|---|---|
| Coherent-sine SINAD, THD and ENOB | `host/noise.py` spectrum, Welch and line-split | The loop's SINAD includes the DAC's staircase and noise; the figure says so |
| A board test that gates the noise figure | `tools/noise_metrics.py` | No board noise test exists; `baseline.json` has no noise key |
| Amplitude against tone | `tools/gen_sweep.py` and `gen_sweep_analyse.py`, which already walk the frequency ladder at a fixed rate | The DAC's sine falls off before the ADC's Nyquist at the top rates, so the top of the band needs an external source |
| ADC channel skew, A0 against A1 | the internal generator, where DAC1 lags DAC0 by one trigger period by construction | Vary the rate to separate that lag from the conversion spacing, about 0.96 us at 90 MHz *(derived, check)*. `dso_metrics skew` measures DAC0 against its own DAC1 sync, not ADC skew, and is not the reference. `run_loop` cannot drive DAC1: the host builders tag every sample DAC0 |
| Crosstalk against tone, and the bare A2 pin | `test_the_other_channel_stays_flat`, `tools/bleed_cadence.py`, `tools/wiring_probe.py` | A bare pin follows A0 at about 56% of its amplitude, so quiet does not mean unwired |

`tools/wiring_probe.py` and `tools/gen_sweep.py` run on Track B only, so
the rows that rest on them are Track B rows and say so. The suite's
default is Tracks A and B; Track C is run as an extra gate.

## Open decisions

| decision | default until answered |
|---|---|
| Are the Phase 5 tests suite tests or `tools/metrics.py` entries? | Suite tests, so a bench without a scope still runs them |
| Which rates carry the Phase 1 tone checks? | The whole existing ladder, at one threshold |
