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
| `calibration.json` | 546 - 2760 mV | `adc_derived_*`, kept as history |
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
| firmware identity - track, `FW_VERSION`, `CTL_VERSION`, `FRAME_VERSION`, and the commit the image was built from | "The binary selects which state issue #5 draws." Points across a reflash are not comparable |
| host OS and version | tier 1 is Windows; every existing figure is macOS's |
| `host/` revision (git describe) | a recorded pass outlived the `measure.py` that produced it once already |
| wiring | per desk, and declared in `bench.json` rather than assumed. DAC1 has been on A1, on a scope's EXT TRIG, and unconnected, on different desks and on the same desk at different dates - and "A1 free" read off the wrong desk turns a driven pin into a noise control |
| probe ratio per channel, as fitted *and* as told | ×10 vs ×1 changed the EXT window by 10× and cost three runs |
| instrument `*IDN?` | "the bench is not promised to keep the same scope" |
| trigger source, coupling, level | an EXT level is discovered, not assumed |
| generator state - shape, points, sync | `CTL_OP_GEN` reports it; the console prints it |
| **which instrument read the counters** (`via`) | control reads one in 146 us; the `B`/`O` fallback costs 13.14 and 15.40 ms of blocked main loop **taken while the sample path is running**. Two experiments, not two tolerances. Issue #51, and it was unanswerable after the fact precisely because no record carried this |

The probe row is the awkward one and should be honest about it: the
scope reports what it has been **told**, not what is fitted, and there
is no way to ask. The suite records both the told value and a
sanity-check against a known-amplitude output, and flags a mismatch
rather than pretending to know.

### An arm structure cannot vary time since reset

**Opening the control port resets the board**, and this is measured
rather than inherited from the docstring that says so. `uptime_ms`
rides the control channel's heartbeat and the command port is the
native port's *second* CDC function, so the board can be asked without
touching NRSTB (`tools/uptime_reset_probe.py`):

    65812 -> 67847 over 2 s idle -> 2884 after a measure.Board open
    climbs while idle 3/3 · went backwards on open 3/3

The idle pair is the control and it is not decoration: without it,
*"uptime went backwards"* and *"this counter does not mean what I think
it means"* are the same reading.

**So every run of every tool that opens a `measure.Board` starts at
uptime zero.** An experiment whose arms are separate runs of such a
tool cannot vary time since reset at all - the arms may differ in rest,
in whether a flash happened, and in what ran before, but not in that.
Issue #48 spent two sessions on arms labelled 0, 12, 15 and 63 minutes
since reset that were, on this bench, all zero.

**This is macOS's measurement, not the project's.** The reset is NRSTB
driven by the 16U2 off DTR, and whether a host asserts DTR on open
belongs to the host stack - the same seam every other platform
difference lives on. Run the probe on your own bench rather than
inheriting this one; if it says NO RESET there, the axis is real there
and that difference is worth more than either result alone.

**What can vary it is one run.** A single held `Board` and N
consecutive reps makes the rep index a continuous time-since-reset axis
that no arm structure can confound. `tools/issue48_withinrun.py` reads
such a record back, and tests it with a rank test rather than a
first-half/second-half split - halving is a bin chosen after seeing the
data.

### The unit of independence is the board session, not the capture

**A tool that takes N captures inside one `measure.Board` has not made N
independent draws**, and treating it as though it had is the same error
as counting a bench's repeated runs as a second bench. It cost a
published claim on 2026-08-31 and it took two hours to find.

The shape it makes is specific and convincing. Two instruments, same
image, same preset, same command sequence, apparently disagreeing:

    issue5_sites, N captures in ONE session       0 breaches / 40
    test_integrity, one capture per pytest run    7 breaches / 37

    Fisher on captures, the wrong unit            p = 0.013
    Fisher on sessions, the right unit            p = 1.00

The first number is **0 of two sessions**, not 0 of 40, and at the
second arm's ~19% per-session rate two clean sessions is a p = 0.66
outcome. The instruments never disagreed. A mechanism was invented to
explain the discrepancy - that writing `EEFC_FMR` moved the board into a
different regime - and it survived for an hour on data that never
contained a discrepancy at all.

**What follows for a harness.** A within-session manipulation is fine
and is often the *right* design: `tools/issue5_sites.py --fws-plan`
alternates blocks inside one session precisely so a session-level drift
lands on every arm equally, and its site-set result is unaffected by any
of this. What must not be done is quoting the *incidence* from such a
run as though each capture were a draw. **A within-session arm bounds
what varies within a session; only repeated sessions bound what varies
between them.**

This is `linux-x1`'s rule from the same day - *two benches sharing an
instrument do not share its precision* - one level further down: **one
bench sharing an instrument with itself does not get N independent
draws by running it N times.**

### And when a load is the variable, record it per run

Three arms on 2026-08-31 were spoiled by load that had already stopped
before the arm finished: CPU burners with a fixed duration that expired
mid-run, and once a foreground command that timed out and took the
burners it had started as its own children. Each produced a clean null
that read as a result.

**`uptime` at the end of a run is not a witness** - a load average is a
lagging mean and recovers slowly enough to look plausible either way.
**Per-run wall time is**, and it costs nothing: on that bench the same
test read 10.5-11.0 s unloaded, 11.4-11.8 s at 1x oversubscription and
12.2-12.6 s at 2x, cleanly separated. A null whose runs all sat at the
loaded time is a null about the load; a null whose runs drifted toward
the idle time is a null about nothing.

Put the load *inside* the same script as the arms, and clean up with a
`trap ... EXIT INT TERM` rather than a line at the end, so an
interruption cannot leave either the load or a patched tree behind.

## Phase 0: measure the ruler before the thing

**No tolerance gets written until its own repeatability has been
measured.** Run each metric N=7 times and record the spread. That spread
is the tolerance floor. Built, and it is `tools/phase0.py` over
`host/repeat.py`:

    python3 tools/phase0.py settle --runs 7 --axis both
    python3 tools/phase0.py settle --report      # no bench needed

Records land in `records/phase0-<metric>.jsonl`, one JSON line per run,
**flushed and fsynced before the next run starts**. That is not caution:
`--calibrate` wrote at session end, a session hung at 90%, and twelve
minutes of bench time produced nothing at all.

There is already evidence this is not a formality:

- slew read 1.991 / 1.893 / 2.110 V/us across three timebases in one
  run, a ±5% spread from the *instrument*, not the converter
- Vpp at the ceiling read 1.54 / 1.88 / 1.58 / 1.88 V across adjacent
  rates, because the scope's Vpp on a degraded waveform is unstable
- `status.md` said the transport spread was "about 5%"; interleaved
  across a reflash, IN spans 40% while OUT and duplex hold to 1%
- the wrap fold's "worst bin" is 9.5× the median, and nobody yet knows
  whether that is the defect or the half-cycle of fold smear

### What a Phase 0 entry carries

The tolerance, and **the evidence that produced it**: `n`, the observed
spread, and the axis it was taken on. Agreed on issue #6, and the reason
is that a tolerance alone throws the evidence away - so "was seven
enough" stays answerable by whoever reads it next instead of evaporating
into a single number. A metric whose spread later grows then shows up as
a changed spread rather than only as a failing assertion.

The derived tolerance says how it was derived, too: twice the observed
half-width, which is **a stated choice and not a measurement**. Seven
points bound the seven points. Two hypotheses on this project looked
like clean signal at four and died at the fifth.

Where a metric reports its own resolution - `settle` returns the sample
interval and the screen level it measured with - the tolerance is
floored on it, so it can never claim to be finer than the ruler that
took it.

### The axis is a result, not an input

**Across a reflash** is the second axis. Some metrics should be
identical (slew, span) and some are known not to be (issue #5's draw
changes with the binary).

The first version of this rule said reflash-interleaved was the primary
axis, and that was too strong: OUT and duplex hold to ~1% in place and
the interleaving bought them nothing, while IN needed it. So both
spreads are measured for every metric and each metric's own numbers
decide which axis its tolerance comes from. `phase0.py --axis both`
prints the ratio per key: near 1 means that key does not care about the
binary, well above 1 means it does. That makes the axis choice
reviewable instead of asserted.

### Its first subject, and what happened

Phase 0 was pointed at the 118 µs settling tail, and **the tail did not
survive contact with it.** The figure is retracted; see `settle` in
`tools/dso_metrics.py` and the commit that withdrew it.

The mechanism is worth keeping because it will happen again. The
DS1102E clamps its vertical offset at ±2 V once the gain is 250 mV/div
or finer. `settle` asked for −2.814 V at 5 mV/div, the instrument held
−2.000 V, and every sample in the record was a rail - 8 distinct values
in 65,526 samples. The "tail" was the low rail's 11,775 samples, which
is 117.75 µs at 10 ns, and it was "reproducible to the sample across
three runs" because the trigger sits at a fixed position in the record.
Everything that made it mysterious follows from that: it did not scale
with overdrive, it did not scale with the step, and every band from 10
codes to 0.5 answered identically, because a rail is outside all of
them.

Two things had already been built to catch exactly this and both were
defeated:

- the on-screen filter, by taking rails from raw `min`/`max` - one stray
  sample at 2025.0 mV sat above a rail resting at 2022.0, so 53,745 rail
  samples passed as signal
- `_apply()`, which returns what the instrument actually holds and says
  "quantised, or clamped" in its own docstring - the return value was
  discarded one line above the analysis that trusted it

`settle` now checks the offset readback against the request, finds rails
by weight rather than by extreme, and refuses a record with fewer than
16 distinct values on screen. Any one of the three kills the artifact.

### And then Phase 0 was pointed at the corrected metric

Which is the point of having it: a metric that no longer reports an
artifact is not thereby a metric that reports anything. Fourteen runs,
seven in place and seven across a reflash, `records/phase0-settle.jsonl`.

**The reflash axis bought nothing.** Every key's spread ratio came in at
2.0 or below and most below 1.0 - the in-place spread was the larger one
on nearly every column. So `settle`'s tolerances, if it ever earns any,
come from the cheap axis. That is the second metric to say so, after OUT
and duplex, and it is why the axis is a result rather than a rule.

**The metric was not repeatable at all**: 82% run-to-run spread on the
band columns and on the length of the analysed record, with nothing
changed between runs. Two causes, both found by looking at the runs the
harness had written down rather than by re-measuring.

*The level was a coin flip.* `final` was the median of the coarse
record's last 40%, and a 655 µs record inside a 1.28 ms half period sits
on whichever level it sits on. One run in seven picked the square's
*low* level, and everything downstream then measured a different thing -
`final_v` spread 560 mV over seven runs of an unchanged generator.

*The level also had to be right to ±20 mV before it could be seen at
all.* The whole screen is 40 mV at 5 mV/div, and the coarse estimate is
a percentile of a record that includes the overshoot. `settle` now takes
the high level deliberately - it is the one the rising-edge trigger
settles onto - and finds it at a gain where it cannot be off screen
before stepping down.

Both fixes were checked the way they were found, with another seven
runs, and the order they were made in is worth keeping because the first
one alone did not work:

| method | `final_v` spread | record-length spread |
|---|---|---|
| as found | *(the record was a rail)* | 82% |
| level refined, still chosen by the coarse median | 560 mV - one flip in seven | 82% |
| level chosen deliberately, then refined | **0.8 mV** | **12%** |

Refining a level does nothing about choosing the wrong one, and n=7
caught the flip at the same one-in-seven rate on both sides of the first
fix. `records/phase0-settle-levelrefine.jsonl` is that middle row.

**What no fix reaches is the band.** The residual about the level is
**20.4 codes rms after 64× averaging** *(scope, pre-`623d4dc`; the ADC
now folds the same pin to 0.28 codes and `host/eqtime.py` settles the
question a different way)*, and every band `settle` offers -
0.5 to 10 codes - is below it. A time to enter a band smaller than the
noise is the time the noise happened to fall inside it, which is what
those columns were reporting. The tool now prints the residual above the
table and refuses to draw its "something is disturbing this pin"
conclusion for a band underneath it.

So the honest state of Tier A's settling row: **this bench cannot time a
settling tail to one code on this pin.** The instrument that could is
the ADC - averaged, it out-resolves the scope by a wide margin, which is
Tier 3 of the calibration argument below and is not built.

**One thing worth chasing, written down as a hypothesis and not a
figure.** In a single capture, windowed by distance from the edge, the
mean offset from the settled level goes −4.3 → −3.9 → −1.0 codes over
0-2, 2-5 and 5-20 µs, with the rms falling 6.6 → 6.1 → 4.4. That is the
shape a real tail would have. It is also n=1, with windows anchored to
the longest on-screen run rather than to the edge itself, on a bench
whose residual is four times the effect. It is a reason to build the
measurement properly, not a result.

**And this is what Phase 0 is for.** The tail was the only observation
in that chase that survived a discriminating test, and it was reported
as "reproducible to the sample across three runs" - the strongest
possible language over three back-to-back runs on one flash in one
thermal state. It cost one run and one look at the capture's own values
to fall over.

### Tier 3 is in use, and it is scope-free

The calibration argument below says the averaged ADC out-resolves the
scope by a wide margin and is the right instrument for anything
measuring differences. `docs/noise.md` is the first measurement built on
that, and it needs no instrument at all: how many of the converter's
twelve bits this board actually leaves it, what each digital load costs
in bits, and which spectral lines are real rather than folded.

**9.5 effective bits of 12** on current firmware, broadband with no
drift and no mains; every digital-activity arm is bounded under 0.07
bits and none is resolved. `tools/noisetool.py`, `host/noise.py`,
repeatability through `tools/phase0.py noise-fast`.

Both of those numbers replaced earlier ones - 8.2-8.4 bits and a
0.26-bit playback cost - which were measured on a build five minutes
older than a DAC fix. The playback figure had reproduced across two
boards and two hosts before it was withdrawn, because both benches ran
the same firmware: **two benches test the board and the host, not the
build.** `docs/noise.md`.

Being scope-free is what makes it a standard rather than a reading: any
bench can re-take it, including one with no DS1102E, and the figures
compare directly.

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
| settling to a code band | **retracted** - the record was a rail | blocked below, and the method now refuses rather than reports |
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

## Calibration: the ADC is the fine instrument, the scope is the true one

The Due's ADC has **four times the resolution of the scope** at the
scope's best usable gain - 0.806 mV per code against 3.1 mV per screen
level at 0.1 V/div - and it samples fast enough that averaging takes the
statistical part far below a code. What it does not have is a scale
anyone can trust. That is the classic transfer-standard arrangement, and
it is worth building deliberately.

| instrument | resolution | absolute scale | independent? |
|---|---|---|---|
| Due ADC | 0.806 mV/code, far finer averaged | unknown - ADVREF is a regulator, not a reference | no: it is the thing under test |
| DS1102E | 3.1 mV/level at 0.1 V/div, better averaged | its own calibration, plus an asserted probe ratio | yes |
| 6.5-digit meter *(not on this bench)* | microvolts | traceable | yes |

### The loop is ratiometric, and that is the whole lever

**The DAC's reference is ADVREF, the ADC's reference** - datasheet Table
46-39's note, recorded in `docs/HANDOFF.md`. One shared node, so a DAC
code produces a fixed fraction of ADVREF and the ADC reads it as a
fraction of the same ADVREF. The code-to-code ratio is therefore
**immune to what the 3.3 V rail actually is** - and, by exactly the same
token, **blind to it**. The board cannot measure its own reference, ever,
by any amount of cleverness.

The scope supplies precisely that missing number, and the first
measurement already did:

| route | ADVREF |
|---|---|
| loop slope (0.67053 ADC codes per DAC code) against the scope's DAC span | 3270.3 mV |
| the ADC's codes-per-millivolt against the scope, directly | 3270.2 mV |
| what `host/` and `tests/` have assumed all along | 3300.0 mV |

Two independent routes agreeing to 0.1 mV, and the assumption is high by
**0.91%**. So the "+0.91% ADC gain error" the first fit reported is very
likely not the ADC's error at all - it is the assumed reference. Nothing
on the board could have told those apart.

### Three tiers, and only one of them needs an instrument

**Tier 1 - absolute, occasional, external.** The scope (or a meter)
pins ADVREF and the DAC's span. Slow, needs a bench, and only has to be
redone when the hardware, the wiring or the instrument changes.

**Tier 2 - ratiometric self-check, any time, no instruments.** Sweep the
DAC through its codes, capture the loop, compare against the stored
curve. Immune to rail drift by construction, so what it catches is
*shape*: drift, damage, a reflash that changed the analog path, and any
nonlinearity that was not there before. This is the one a deployed board
can run on its own, and it is cheap enough to run at every boot.

**Tier 3 - the ADC as a fine relative voltmeter.** Once Tier 1 has
supplied the scale, the averaged ADC out-resolves the scope by a wide
margin and becomes the right instrument for anything measuring
*differences*: linearity residuals, settling tails, drift over
temperature. `dso_metrics lin` is quantiser-limited at ~11 codes and the
ADC would not be.

### What self-calibration can and cannot fix

**Can:** rail drift (ratiometrically, for free); repeatability and
shape, against a stored curve; and - with the SAM3X's on-chip
temperature sensor - conditioning a stored calibration on temperature,
so a board can at least notice it is outside the conditions its
calibration was taken in.

**Cannot:** absolute scale. There is no on-chip voltage reference on the
SAM3X to bootstrap from, so ADVREF's value has to come from outside and
be *stored*. Today that store is `tests/baseline.json`, which is a host
file; a deployed board would want it in its own flash, reported over
`CTL_OP_IDENTITY` or a sibling opcode, so the board can say what
calibration it is carrying.

**Cannot, and this is the subtle one:** a linear fit cannot calibrate
out a nonlinearity, and issue #5 is a suspected nonlinearity. Gain and
offset are two numbers; INL is a curve. Correcting the loop with two
numbers and then using the corrected loop to hunt issue #5 would be
fitting the artifact into the correction.

### Separating the DAC's INL from the ADC's

The measurement neither instrument gives alone. Note that A0 and A1 are
**one converter behind a multiplexer**, so the ADC's INL is common to
both channels and comparing them cannot separate it - what it separates
is DAC0's INL from DAC1's, which is still worth having.

Two routes, both available here:

1. **Same code, both DACs, both channels.** Drive DAC0 and DAC1 with an
   identical sweep and read A0 and A1. The difference is the two DACs'
   relative INL; the common part is the ADC's plus whatever the two DACs
   share. Needs DAC1 back on A1, which the current wiring gives up to
   the bench trigger - so it is a wiring mode, not the default.
2. **The scope as the arbiter.** DAC code → volts → ADC code, which
   `dso_metrics transfer` already does, bounded by the scope at about
   ±4 codes over the measured range. That is not fine enough for a
   per-code DNL and **is** fine enough for issue #5, whose signature is
   30-45 codes. Worth stating plainly: **the scope can adjudicate issue
   #5.** It could not before.

### What to build for it

1. **Store the calibration where the measurement can reach it.** Done
   for `dac_mv` and `advref_mv`; `host/` still divides by a hard-coded
   3300 in places and should read the file instead.
2. **A Tier 2 self-check command.** Sweep, fold, compare to stored,
   report a single deviation figure. No instrument, no host DSP.
3. **Temperature alongside it.** The SAM3X ADC's internal sensor, read
   at the same moment, so a calibration carries the conditions it was
   taken in. `CTL_OP_TEMP` and `=<n>e` exist for this (issue #11).

   **But it reads the workload, not the room, and that limits what it
   can condition.** Measured on one image in one session, ABBA
   interleaved, no reflash: 20 s of max-rate capture against 20 s idle
   moves the reading **+1.57 +- 0.26 codes** (6.0 sigma,
   `records/temp-workload.jsonl`). That is *larger* than the 0.6-0.8
   codes two different firmware builds read apart, which is how the
   difference between the two tracks was traced to their main loops
   running at different rates rather than to anything about the sensor
   or the reference.

   So a stored calibration may condition on temperature only against
   **the same build doing the same thing**. Comparing a reading from one
   build with one from another - or an idle reading with a post-capture
   one - measures the firmware. The reading is also not comparable
   between boards as an absolute: two boards here read 39 codes apart,
   which is the part-to-part offset the sensor is known for.

   **The ambient envelope, measured and adopted as documentation rather
   than a conditioning implementation** (issue #18, owner's decision
   2026-08-29). A 5-hour soak at fixed build and activity on the
   windows-desk bench (records/temp-soak-overnight.jsonl) read the
   room through the die: worst-case calibration error **1.8 codes
   (~1.4 mV)** - a ~45-minute oscillation of up to +-1.4 codes
   tracking the building's central-AC duty cycle, over a mean that
   walked ~0.8 codes across the evening. The envelope is bench-class
   conditional (climate-controlled space, no independent thermometer;
   a swung room is unmeasured) and it is an order of magnitude under
   the DAC's ~25-code standing noise, which is why it is a documented
   envelope and not a correction: a calibration taken after warm-up is
   good to +-2 codes against ambient in this environment, and nothing
   a user can see improves by conditioning below that.

   **Procedure line that stands regardless: calibrate and measure
   after about one minute powered.** The post-flash warm-up transient
   is ~1.0 code in the first minute (die self-heating; kept in the
   soak rows deliberately) and dominates everything ambient does on
   that timescale.
4. **Re-take `dc_transfer`'s assertions against 3270 mV** rather than
   3300, and mark which figures moved.

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
- **Settling, at one code, on a level above 2 V.** The DS1102E clamps
  its vertical offset at ±2 V once the gain is 250 mV/div or finer, so
  a level that settles at 2.8 V cannot be brought on screen at 5 mV/div
  at all - and the instrument says so only if the readback is checked,
  which is how it produced a 118 µs "tail" made entirely of rail. The
  two ways round it are a smaller amplitude, which works and is what
  `settle --amp 64` does, and AC coupling, which **is not free**: its
  own highpass droops over the same window as the thing being measured,
  by an amount nobody here has measured. Measure the droop before
  trusting a number taken through it.

- **Anything about a native Linux host.** Tier 1, deferred, still no
  board on a Linux machine.
- **Whether the 375 kHz pin is the DACC or the PDC.** The output stops
  following the table past ~1.5 M updates/s, and this bench cannot say
  which side of the DMA that happens on.
