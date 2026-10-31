# Re-evaluating the converters' analog performance at 90 MHz

**Status: plan. Nothing here is measured yet unless a row says so.**
The master clock is 90 MHz (see [hardware.md](hardware.md), "Operating
point"), and the DAC-to-ADC loop is the only analog instrument this bench
has: DAC0 jumpered to A0, DAC1 to A1, no scope attached. The aim is to
re-measure noise, linearity, response, settling, skew and crosstalk at
the new rates by **improving the tests and tools that already exist**.
A new test is added only where a row below says nothing exists.

## What the loop can and cannot judge

| fact | consequence for every phase |
|---|---|
| The DAC is the stimulus and its reference is the ADC's | The loop is ratiometric. It compares the two converters; it cannot give an absolute voltage or an absolute rate |
| The DAC spans about 0.55-2.75 V, about 690-3450 codes | Gain and linearity are judged over two thirds of the ADC's range. The ends need another source |
| DAC and ADC are both 12-bit, and the DAC's own linearity is unknown | A loop INL is DAC plus ADC. Separating them needs the scope-referenced `lin` metric in `tools/dso_metrics.py`, or a meter |
| The DAC's rise time is 789-938 ns at 78 MHz *(not re-measured at 90)* | A step is not a step to a 0.96 us conversion; a clean sine stops well below the ADC's Nyquist at 1 Msps |
| Tone and sample rate are different things | A table of N points played at `fs_dac` gives `f = fs_dac * c / N`. Choose the DAC rate an integer multiple of the ADC rate so the staircase's images fold onto the tone *(derived, confirm on the bench)* |
| Both timers divide 45 MHz | Exact rates and coherent sampling are available; the matched-loop ladder is in [status.md](status.md) |

## Rules for every phase

| rule | where it comes from |
|---|---|
| Break each new or changed check on purpose and watch it fail | `CLAUDE.md` |
| Drop the first run of a repeated measurement, by index | `CLAUDE.md` |
| A threshold comes from a measurement and is never widened to pass | `tests/baseline.json` header |
| An unmeasured figure is marked *(check)* | `CLAUDE.md` |
| Board tests pass on tracks A, B and C | `docs/testing.md` |
| A null result says what the instrument could have detected | `CLAUDE.md` |

## Phases

| phase | goal | existing work to improve | exit evidence |
|---|---|---|---|
| **0. Instruments correct at 90 MHz** | Every standing tool computes rates from the timer clock; one noise protocol is chosen | Replace hard-coded 39 MHz in `tools/metrics.py` (`m_playback`), `dso_sweep.py`, `bench.py`, `clock_calib.py`, `issue5_alias_sweep.py`, `issue24_holdavg.py`, `soak0c_portable.py` and the `issue48_*` tools with `measure.TC_CLOCK_HZ`; replace the 453,488 fallback in `noisetool.py`; add a tree scan so a hard-coded timer clock cannot return (extend an existing tree-scan test if one fits) | Each tool runs at 90 MHz and its figures agree with 78 MHz where physics says they must. The three noise figures in the tree (0.80 and 1.65 codes, and about 25 codes of DAC standing noise) are explained as different protocols, or one is wrong |
| **1. Rate ladder in the board tests** | The analog tests stop being single-rate | `tests/test_integrity.py` (tone amplitude, recovered frequency, A1 crosstalk, DC transfer) runs only at 200 kHz and 200 kHz. Parametrize over 1 MHz (one channel), 500 kHz, 250 kHz, 100 kHz and 10 kHz, DAC an integer multiple of the ADC rate, at least 10 points per cycle. A measured threshold per rate goes in `tests/baseline.json` | Every row passes on A, B and C; a deliberately wrong threshold fails |
| **2. DC transfer and linearity** | Gain, offset and loop INL/DNL, labelled as the loop's | Extend `test_dc_levels_are_monotonic` and `test_dc_transfer_tracks_the_code` to fit gain and offset over the span and report step statistics. Keep `dso_metrics lin` and `transfer` as the DAC reference where a scope is attached | Gain, offset and INL recorded at two rates; the scope gap stated |
| **3. Noise against rate** | Noise in codes and noise-free bits at each ladder rate, with spread | Add a rate parameter to `noisetool dc`, `tools/noise_metrics.py` (repeatable through `phase0.py`) and `m_noise`; gate the pinned figure in a board test | A figure per rate with its repeat spread, in `baseline.json` |
| **4. Rise and settling** | Scope-free rise and settling at 90 MHz | Re-run `tools/settletime.py` and `m_settling`; the stored 789-938 ns scope range is a sanity check, not a verdict | Rise and settling recorded; the stored range changed only if the measurement disagrees |
| **5. What has no test today** | The four gaps below, each built on existing helpers | See the next table | Each has a mutation check |
| **6. Baseline and docs** | Recalibrate and record | `tests/baseline.json`, [status.md](status.md), [noise.md](noise.md) | The generated report matches the baseline; scope-only items listed as open |

## Phase 5: nothing exists today

Checked by search of `tests/`, `tools/` and `host/` for SINAD, THD, SFDR,
INL, ENOB and response sweeps: only the board-free noise arithmetic in
`host/noise.py` and the scope-only skew in `dso_metrics.py` come close.

| missing | built from | note |
|---|---|---|
| Coherent-sine SINAD, THD and ENOB | `host/noise.py`, the phase 1 tones | The loop's SINAD includes the DAC's staircase and noise; say so in the figure |
| ADC amplitude against tone | the same sweep | The DAC's sine amplitude falls off before the ADC's Nyquist at 1 Msps, so the top of the band needs an external source |
| Board-only channel skew, A0 against A1 | `measure.run_loop`, `eqtime` | `dso_metrics skew` is the scope reference; expect about 0.96 us between channels *(check)* |
| Crosstalk against rate and tone, including the bare A2 pin | `test_integrity.py`'s A1 check, `tools/wiring_probe.py` | A bare pin follows A0 at about 56% of its amplitude, so "is it quiet" cannot tell bare from wired |

## Open decisions

| decision | default until answered |
|---|---|
| Is reconciling the three noise figures part of phase 0? | Yes, because nothing in phase 3 is pinned until one protocol is chosen |
| Are the phase 5 tests suite tests or `tools/metrics.py` entries only? | Suite tests marked so a bench without a scope still runs them |
| Which rates are in the ladder? | The five in phase 1 |
