# The measurement suite

A plan, not a record. `docs/status.md` holds the numbers; this holds the
argument for how they get taken, what makes one trustworthy, and what
has to be built before the current ones can be called a baseline.

## Two jobs, and they want different things

**Regression.** Did this change break something? Wants identical
conditions, tolerances derived from the observed spread, automatic
pass/fail, and speed. `tests/` + `tests/baseline.json` already does
this, and its `_comment` already states the governing rule:

> Tolerances come from the observed run-to-run spread. A tolerance
> tighter than the spread is a flaky test; one much looser is not a
> test.

**Characterisation.** What *is* this device? Wants absolute numbers with
stated uncertainty, full provenance, and honesty about method. Today
this lives as hand-written prose in `docs/status.md` and in commit
messages, which is how `FW_VERSION_STR` came to say 0.1.0 while the
numbers said 0.2.0, and how a branch's "160 passed / 88 failed" outlived
the `measure.py` that produced it.

**The suite is one run feeding both.** One machine-readable record per
run, with provenance attached; an assertion layer reads it for
regression, and a report generator reads it for characterisation.
Nothing gets hand-copied into prose, because hand-copied numbers in this
project have gone wrong twice already and both times silently.

## Do not rebuild what exists

`tests/baseline.json`, the `calibration` fixture, `--calibrate` writing
`baseline.measured.json` for a human to promote, and the
`smoke`/`slow`/`awg`/`scope`/`dso` markers are the right design and are
already here. The suite extends them. Specifically it does **not**
introduce a second format, because two homes for one number is the
failure invariant 3 was rescoped over.

## The gap this plan closes

`tools/dso_metrics.py` produces the only figures this project has that
did not come from the converter under investigation - step response,
interleave skew, the frequency ceilings, linearity, the wrap fold - and
**none of them are recorded, asserted, or carry provenance.** They are
printed to a terminal and quoted from there into commit messages. That
is precisely the state `docs/status.md` was in before it was a problem.

### The example that shows why it matters

The DAC's output span, right now, has three values in this repository:

| source | span | where |
|---|---|---|
| `tests/baseline.json` | 546 - 2760 mV | `dac_mv`, ADC-derived |
| `tools/dso_metrics.py` | 520 - 2820 mV | `DAC_LO_V`/`DAC_HI_V`, a bench note |
| the scope, this session | Vmax 2.82-2.86, Vpp 2.42-2.44 V | measured, unrecorded |

They disagree by 26-60 mV. Every "codes" figure `dso_metrics` prints is
scaled by the middle one, so its linearity and noise numbers are ~4% off
in a way nothing catches. **The scope can settle this**, and the
difference between the ADC's view and the scope's view of the same pin
is not an annoyance - it is an ADC gain-and-offset measurement, the
first one this project can make against something that is not the ADC.

## Provenance: what makes a run void

A measurement without these is not a baseline point, and the harness
should refuse to record rather than record something unattributable.
The project has already paid for each of these:

| field | why it is load-bearing |
|---|---|
| firmware identity - track, `FW_VERSION`, `CTL_VERSION`, `FRAME_VERSION`, build stamp | "The binary selects which state issue #5 draws." Points across a reflash are not comparable |
| host OS and version | tier 1 is Windows; every existing figure is macOS's |
| `host/` revision (git describe) | a recorded pass outlived the `measure.py` that produced it once already |
| wiring | DAC0→A0, DAC1→**EXT TRIG** now, not A1. A2 bare unless someone says otherwise |
| probe ratio per channel, as fitted *and* as told | ×10 vs ×1 changed the EXT window by 10× and cost three runs |
| instrument `*IDN?` | "the bench is not promised to keep the same scope" |
| trigger source, coupling, level | an EXT level is discovered, not assumed |
| generator state - shape, points, sync | `CTL_OP_GEN` reports it; the console prints it |

The probe row is the awkward one and should be honest about it: the
scope reports what it has been **told**, not what is fitted, and there
is no way to ask. The suite records both the told value and a
sanity-check against a known-amplitude output, and flags a mismatch
rather than pretending to know.

## Phase 0: measure the ruler before the thing

**No tolerance gets written until its own repeatability has been
measured.** Run each metric N=7 times with nothing changed - no
reflash, no re-cable, no power cycle - and record the spread. That
spread is the tolerance floor.

There is already evidence this is not a formality:

- slew read 1.991 / 1.893 / 2.110 V/us across three timebases in one
  run, a ±5% spread from the *instrument*, not the converter
- Vpp at the ceiling read 1.54 / 1.88 / 1.58 / 1.88 V across adjacent
  rates, because the scope's Vpp on a degraded waveform is unstable
- the wrap fold's "worst bin" is 9.5× the median, and nobody yet knows
  whether that is the defect or the half-cycle of fold smear

A second axis matters too: **across a reflash**. Some metrics should be
identical (slew, span) and some are known not to be (issue #5's draw).
Phase 0 measures both spreads and the suite records which kind each
metric is, because a regression test that fires on every reflash is
noise and one that cannot fire on a reflash is blind.

## The catalogue, in three tiers

The tiers are about **what a figure's provenance depends on**, which is
what decides whether the macOS caveat applies to it.

### Tier A - the converter and the instrument only

The internal generator plays its own table with **no USB in the path**.
These figures do not depend on the host's USB stack, so they are the
first in this project that do not inherit the 0-series debt or the
"every figure is macOS's" caveat.

| metric | today | state |
|---|---|---|
| full-scale step: rise, slew, overshoot | 789-938 ns, 1.89-2.11 V/us, 0.96-1.80% | measured, unrecorded |
| settling to 1% | window-limited at two of three timebases | method needs a longer record |
| TAG interleave skew | -0.967 trigger periods (predicts -1.000) | measured, unrecorded |
| frequency ceiling, sync on | ~357 kHz square | measured, unrecorded |
| frequency ceiling, solo | ~750 kHz toggling | measured, unrecorded |
| full-amplitude ceiling | ~400-450 kHz | measured, unrecorded |
| square-shaped ceiling | ~100-200 kHz | **judged by eye, not by a number** |
| output span, absolute | disputed, see above | **unresolved** |
| noise floor on a held code | 20.2 mV RMS, 15.1 mV with the DAC idle | measured, unrecorded |
| linearity across the span | ~24 codes rms against an 11-code ruler | measured, quantiser-limited |
| wrap fold | worst bin 9.5× median | **no control arm yet** |

### Tier B - both converters, no host DSP

The loop, and the ADC measured against something other than itself.

| metric | state |
|---|---|
| DAC→scope→ADC three-way transfer | **not built.** The important one |
| ADC gain and offset against the scope | not built; the span dispute is the first instance |
| ADC INL against the scope | not built; ~±1 code resolution after averaging, enough for issue #5's scale |
| channel skew A0/A1 | ~0.95 us, from the ADC's own timing |
| issue #5 fold z | `pair_fold`, in `tests/test_integrity.py` |
| ramp discontinuities | `ramp_discontinuities`, in the suite |

### Tier C - the host is in the measurement

Everything here carries the platform caveat and the 0-series
re-validation debt. Already covered by `tests/`.

Throughput, byte conservation, underruns per rate, `close()` behaviour,
load monitor, daemon and GUI. Objective 0h in `docs/HANDOFF.md` gates
these.

## What to build, in order

**1. Record what already exists.** Wire `dso_metrics` into the
`calibration` fixture behind the `dso` marker, with the provenance
block. No new numbers - just stop losing the ones being taken. This is
the smallest change that removes the hand-copy path.

**2. Phase 0 repeatability.** N=7 per metric, in-place and across a
reflash, written to `baseline.measured.json`. Promote tolerances from
the observed spread. Nothing before this is a baseline; it is a
snapshot.

**3. Settle the span.** A DC sweep at high vertical gain with averaging,
against the ADC reading the same pin. Produces the absolute span, the
ADC's gain and offset, and one authoritative `dac_mv` that
`baseline.json` and `dso_metrics` both read - deleting the third copy.

**4. The three-way.** Host commands code C, the scope measures volts V,
the ADC reports code A, over a code sweep. First ADC transfer function
referenced to a non-ADC instrument. Bounded by the scope's 8 bits and
the averaging - state the floor with the result, expect ~±1 code, which
is an order finer than issue #5's 30-45 code signature.

**5. Turn the eye-judgements into numbers.** "Recognisable square" is
currently a person looking at a screenshot. A flat-top fraction - the
proportion of a half period within 5% of the final level - makes the
100-200 kHz claim a measurement. Same for the slew wall: sweep
400-700 kHz in fine steps rather than extrapolating from the step
response.

**6. Give the wrap fold a control arm.** Run the identical fold with
`sync=cycle`, where nothing is locked to the reload, and with a screen
holding a whole number of cycles. Without a control the 9.5× is not
evidence. `docs/HANDOFF.md` already says this about issue #5 sweeps
generally; it applies here.

**7. Report generator.** One command turning the recorded run into the
tables in `docs/status.md`, so the prose stops being hand-copied.

## Cadence

| tier | what | cost |
|---|---|---|
| smoke | board-free + contract + one rate | seconds |
| standard | the existing hardware suite | minutes |
| analog | Tier A, needs `--dso` | ~10 min |
| full | + Tier B sweeps and repeatability | ~1 hour |

Analog and full are not run per commit. They are run when the DAC path,
the generator or the wiring changes, and on demand before a figure is
quoted anywhere.

## What this bench cannot measure

Saying so is part of the suite, because a plausible number is the
expensive kind of error here.

- **Per-code DNL of a 12-bit converter.** The scope digitises the whole
  screen to 8 bits and averages before the quantiser, so averaging beats
  the noise and not the step size. Slicing vertically gets to ~11 codes
  per level; a real DNL needs a 6.5-digit meter and a settling delay per
  code.
- **Absolute voltage.** Everything is referenced to the DS1102E's own
  calibration and to a probe whose division ratio is asserted, not
  measured. Every span and offset figure is "as this instrument sees
  it". A calibrator would fix it; nothing here does.
- **Anything about a native Linux host.** Tier 1, deferred, still no
  board on a Linux machine.
- **Whether the 375 kHz pin is the DACC or the PDC.** The output stops
  following the table past ~1.5 M updates/s, and this bench cannot say
  which side of the DMA that happens on.
