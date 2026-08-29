# The signal generator

Two generators, two reasons. Everything below is measured on this bench
unless it says otherwise.

| | source | path | reached by |
|---|---|---|---|
| **streamed** | host | `HOST -> USB -> play.c ring -> PDC -> DACC` | `measure.build_selected`, `run_play`, `run_loop` |
| **internal** | device | `gen table -> PDC -> DACC`, no USB at all | `=<shape>,<pts>W` on the console |

The streamed one is arbitrary: the host authors every sample, so any
shape it can compute is a shape the board can emit. The internal one
keeps running when no host is attached, which is what a deployed board
needs, and it costs nothing on the wire.

Both exist on both tracks. Track B is `drivers/gen.c` and `drivers/play.c`;
Track A is `sketches/bringup/gen.cpp` and `sketches/bringup/play.cpp`.
Independent source, identical feature and identical printed format.
Invariant 3 shares the wire contract and keeps register programming
apart, naming `gen` among the internals that stay independent, so these
two files are on the right side of that line: Track A's sine comes from
libm and Track B's from a fixed-point Bhaskara approximation, and the
two agreeing on the analog output is then evidence rather than a
tautology.

## Shapes

| code | name | streamed | internal |
|---|---|---|---|
| 0 | sine | yes | yes |
| 1 | square | yes | yes |
| 2 | ramp (rising sawtooth) | yes | yes |
| 3 | triangle | **no** | yes |
| 4 | DC | yes | yes |

Triangle is internal-only today. That is debt with a date on it, not a
property of the path: `measure.build_selected` is one chain and a
`build_triangle` alongside `build_square` closes it.

The ramp divides by `period`, not by `period - 1`, so the last point sits
one step below full scale and the wrap is the same step as every other.
Ending at 4095 would make the wrap a step of zero and put a one-sample
flat spot in the only waveform that has none.

## Resolution, and what it costs

This is the trade a bench AWG makes, and it is not hidden. The trigger
fixes the *update* rate; resolution decides how many updates one cycle
spends:

```
f = trigger_hz / (2 * points)
```

The 2 is DACC TAG mode - every other update belongs to DAC1. Points must
divide the 256-point table, so powers of two from 2 to 256 and nothing
else: a count that does not divide it leaves a partial cycle at the PDC
wrap, which is a phase step in the analog output once per reload, and
invariant 5 exists to refuse exactly that. A request that is not a legal
count **rounds down** and the device reports what it adopted, rather than
refusing and making the caller guess which values exist.

Measured, trigger 200 kHz, square (`tools/dso_sweep.py --internal`):

| points asked | adopted | expected | measured | Vpp |
|---|---|---|---|---|
| 300 | 256 | 390.6 Hz | 391.0 Hz | 2.44 V |
| 256 | 256 | 390.6 Hz | 391.0 Hz | 2.44 V |
| 128 | 128 | 781.2 Hz | 781.0 Hz | 2.46 V |
| 100 | 64 | 1,562.5 Hz | 1,560.0 Hz | 2.46 V |
| 64 | 64 | 1,562.5 Hz | 1,560.0 Hz | 2.48 V |
| 16 | 16 | 6,250 Hz | 6,250 Hz | 2.44 V |
| 4 | 4 | 25,000 Hz | 25,300 Hz | 2.44 V |
| 2 | 2 | 50,000 Hz | 50,000 Hz | 2.44 V |

Full amplitude at every resolution including the top: the DAC is not the
limit here, the table is.

### Two points a cycle is the clock, not just the coarsest setting

At two points the table holds **one sample per half cycle**, so the
output toggles on every DAC0 update and the waveform *is* the update
clock divided by two. Nothing on this path is faster: a third point per
cycle is a *slower* wave, not a quicker one. It is the top rung and it
belongs in every sweep - leaving it out stops one step short of the
ceiling the sweep exists to find.

TAG mode spends every other update on DAC1, so DAC0 updates at
trigger/2 and the square lands at **trigger/4**. Giving up the sync and
tagging every sample for DAC0 would double that, which is what the
streamed path already does - a trade, not a defect.

Measured across every trigger the generator's TIOA0 will take:

| trigger | DAC0 updates | half period | expected | measured | Vpp | of max |
|---|---|---|---|---|---|---|
| 50,000 | 25,000/s | 40.00 us | 12,500 Hz | 12,500 Hz | 2.440 V | 100.0% |
| 100,000 | 50,000/s | 20.00 us | 25,000 Hz | 25,000 Hz | 2.420 V | 99.2% |
| 200,000 | 100,000/s | 10.00 us | 50,000 Hz | 50,000 Hz | 2.440 V | 100.0% |
| 400,000 | 200,000/s | 5.00 us | 100,000 Hz | 100,000 Hz | 2.420 V | 99.2% |
| 453,488 | 226,744/s | 4.41 us | 113,372 Hz | 114,000 Hz | 2.420 V | 99.2% |

**The ceiling is the trigger, not the converter.** Frequency tracks
trigger/4 exactly and amplitude never leaves 99.2-100% of maximum, right
up to 113 kHz - where the half period is still 4.41 us against a
789-938 ns rise. What does change is the *shape*: at 113 kHz the square
is visibly trapezoidal, the slew taking about a fifth of each half
period, with a glitch spike at each transition. `dso_metrics.py clock`.

### 113 kHz is not the DAC's limit, and it is not close to it

Every ordinary path leaves the DACC triggered from **TIOA0**, the ADC's
timer, so that generation and capture are phase-coherent - and TIOA0 is
capped by `ACQ_MIN_RC` = 86 at 453,488 Hz. That cap is the *ADC's*
in-spec floor. `=<dac>M` is the one path that selects TIOA1 and takes an
arbitrary rate, and with the DAC off the ADC's leash it goes more than
three times further. Square at 2 points, `dso_metrics.py ceiling`:

| dac_hz | DAC0 updates | half period | expected | measured | Vpp |
|---|---|---|---|---|---|
| 400,000 | 200,000/s | 5.000 us | 100,000 Hz | 100,000 Hz | 2.420 V |
| 800,000 | 400,000/s | 2.500 us | 200,000 Hz | 205,000 Hz | 2.420 V |
| 1,200,000 | 600,000/s | 1.667 us | 300,000 Hz | 303,000 Hz | 2.420 V |
| **1,392,857** | 696,428/s | 1.436 us | 348,214 Hz | **357,000 Hz** | 2.380 V |
| 1,800,000 | 900,000/s | 1.111 us | 450,000 Hz | 375,000 Hz | 2.360 V |
| 2,200,000 | 1,100,000/s | 0.909 us | 550,000 Hz | 375,000 Hz | 2.400 V |
| 2,800,000 | 1,400,000/s | 0.714 us | 700,000 Hz | 375,000 Hz | 2.380 V |

Frequency follows `dac_hz / 4` exactly up to the DACC's own measured
ceiling and then **pins at 375 kHz and stops**. That is the converter
saturating, not the amplitude failing - Vpp stays at 97.5-100%
throughout, because what it still produces is full-swing, just fewer
transitions than were asked for. It is the same 1,392,857 updates/s
`drivers/play.h` records from the playback path, seen from the analog
side for the first time.

### Solo: give up DAC1 and the sync, and take the last factor of two

`=3J` tags **every** table entry for DAC0, so the converter updates it
on every trigger instead of every other one, the table holds 512
waveform points instead of 256, and the output frequency doubles:
`f = trigger_hz / points` rather than `trigger_hz / (2 * points)`.

The cost is the sync, and with it the bench trigger and the
demultiplexing check. That is a real trade rather than a strictly better
mode - but it is the right trade for exactly one shape, because a
square's own edge triggers a scope better than any sync does: 0.007 us
of jitter against the sync's 1.471.

Square at two points, `dso_metrics.py ceiling --solo`:

| dac_hz | DAC0 updates | half period | expected | measured | Vpp | of max |
|---|---|---|---|---|---|---|
| 800,000 | 800,000/s | 1.250 us | 400,000 Hz | 407,000 Hz | 2.400 V | **100.0%** |
| 1,200,000 | 1,200,000/s | 0.833 us | 600,000 Hz | 592,000 Hz | 1.960 V | 81.7% |
| 1,392,857 | 1,392,857/s | 0.718 us | 696,428 Hz | - | 1.640 V | 68.3% |
| 1,600,000 | 1,600,000/s | 0.625 us | 800,000 Hz | 755,000 Hz | 1.880 V | 78.3% |
| 2,000,000 | 2,000,000/s | 0.500 us | 1,000,000 Hz | **749,000 Hz** | 1.540 V | 64.2% |
| 3,000,000 | 3,000,000/s | 0.333 us | 1,500,000 Hz | 746,000 Hz | 1.580 V | 65.8% |

**Three limits, and they are far apart. 1 MHz is not one of them.**

- **Frequency ceiling ~750 kHz.** Ask for 1,000,000 Hz and 749,000
  arrives; ask for 1,500,000 and 746,000 arrives. Past roughly 1.5 M
  updates/s the output pins there whatever the timer is told, which is
  the DACC's conversion limit seen from the analog side.
- **Full amplitude to ~400-450 kHz.** Vpp holds at 2.38-2.40 V through
  407 kHz and is down to 81.7% by 592 kHz.
- **A recognisable square only to ~100-200 kHz.** This is the one the
  numbers hide, and it is why the screenshots matter: at 407 kHz the
  amplitude is still 100% and the waveform is already a trapezoid with
  almost no flat top, because the 789-938 ns rise is most of a 1.25 us
  half period. By 600 kHz it is a triangle. At the DACC ceiling it is a
  triangle whose peak height varies cycle to cycle - the converter
  failing to keep up irregularly rather than uniformly.

"Amplitude fell to 68%" and "the square became a triangle" are the same
number and different findings, which is the whole argument for capturing
the screen and not only the measurements.

**Five different ceilings, and they are not the same number.** Naming
them separately matters, because a design sized against the wrong one
fails in a way that looks analog:

| what limits it | number | why |
|---|---|---|
| internal generator on TIOA0 | **113 kHz** square | the ADC's `ACQ_MIN_RC`, then halved by TAG |
| internal generator on TIOA1, sync on | **~357 kHz** square | DACC conversion, halved by TAG's other channel |
| solo, no sync, TIOA1 | **~750 kHz** toggling | DACC conversion, not halved. The hardware's own ceiling |
| solo, and still full amplitude | **~400-450 kHz** | 789-938 ns rise against the half period |
| solo, and still shaped like a square | **~100-200 kHz** | the same rise, judged on shape instead of on peak-to-peak |

All five measured. The last three are the same converter described three
ways, and which one to quote depends entirely on what the output is for:
a clock only has to cross a threshold, a reference has to reach its
rails, and a waveform has to keep its shape.

**Only the square means anything at two points.** The others collapse,
and a screenshot of a collapsed one with its own name on it is worse
than no screenshot:

| shape | codes at 2 pts | what it actually is |
|---|---|---|
| sine | 2048, 2048 | flat - both samples land on a zero crossing (Nyquist) |
| square | 4095, 0 | the clock, full amplitude |
| ramp | 0, 2048 | a half-amplitude square |
| triangle | 0, 4095 | a full-amplitude square |

`dso_sweep --internal` and `dso_metrics shots` skip the three that
collapse and say which, rather than filing them under the wrong name.

**The scope's frequency counter is not reliable below about 16 points
per cycle.** At 8 points it read 11,200 Hz for a sine and 13,800 Hz for a
triangle against a true 12,500 Hz, while reading the square and the ramp
correctly. It is counting staircase edges. Judge a coarse waveform by
its period on screen, not by `:MEAS:FREQ?`.

### The trap resolution introduces

The host's issue-#5 instruments - `fold_profile()` and `pair_fold()` in
`host/measure.py` - fold the capture at `GEN_TABLE_LEN` because 256
points has been the generator's only resolution in every build. That
stops being the right period the moment the resolution moves: it becomes
`2 * points`. `measure.gen_fold_len()` is the honest form. **Do not read
an issue-#5 sweep taken at a resolution other than 256 without saying
so.**

### Shape and layout are different axes

`gen_layout` (`=<n>N`, Track B only) is not a shape selector, however
much it reads like one. NORMAL / SWAPPED / TWOCYCLE / DC answer *which
pin* and *where the PDC wrap falls relative to the period*, and every arm
of it is an issue-#5 experiment with results recorded against it. Shape
and resolution are orthogonal to it on purpose, so those diagnostics keep
working and now work against something other than a sine.

TWOCYCLE composes with resolution rather than replacing it: at the
default 256 it builds byte-for-byte the table it has always built, so its
recorded results still describe the thing they were taken on. Resolution
128 in the NORMAL layout builds the same *waveform* by the other route,
and the two differ only in where the fold lands - which is exactly the
distinction the arm exists to make.

## The wrap displacement, settled within tolerance (issue #5)

**Samples near the 256-point table wrap are displaced - several of
them, at fixed positions - and the issue was closed on a 1-8 code bound
rather than on a mechanism.** Both tracks show it. It closed as "one
sample"; that was the largest one.

**There is more than one displaced sample per wrap, and `peak_phase` is
an argmax over all of them.** This paragraph has been wrong twice, in
opposite directions, and both errors came from summarising a profile by
its maximum.

`fold_profile` reports the largest bin. Read the *whole* folded profile
instead - `tools/issue5_sites.py` - and a single capture shows several
fixed sites, each reproducible to about a tenth of a code:

| phase | seen in | values |
|---|---|---|
| 138 | 22/24 | -5.32 .. +1.89 |
| 198 | 18/24 | +1.96 .. +12.68 |
| 177 | 6/24 | -14.43 .. -14.17 |
| 117 | 6/24 | -2.27 .. -2.02 |
| 219 | 15/24 | -1.32 .. -0.89 |

Each run shows a subset, with its own values, and the argmax reports
whichever site currently dominates. **That is why two benches read the
same statistic and disagreed**: this bench saw the argmax alternate
between 138 and 177 and called it a phase redraw; windows-desk saw the
argmax hold at 156 while its value flipped sign and called it a value
flip. Both are the argmax following a multi-site profile whose values
move on a minutes scale. Neither "the artifact moves" nor "the artifact
is one sample whose value flips" is right.

**So every figure this issue has ever quoted is an argmax over an
unknown number of sites**, including the 1-8 codes it closed on and the
14.4 quoted for its reopening. What survives that is the thing the
tolerance argument is actually about - the largest displacement in a
wrap - which is 12.3-14.5 codes routinely today against a closing
record of 1.0-7.3. Quote the site table, not the peak.

One reading trap, since it cost a first pass here. `spike` subtracts
each bin's neighbours because `fold_profile` must survive a waveform
underneath it. After `pair_fold`'s differencing within the DAC hold
there is no waveform left, so the subtraction only adds a shadow: a
single spike of A becomes A at its bin and -A/2 at each neighbour, and
reading that as three sites reported 176 and 178 alongside the one real
site at 177. Read the profile directly on a differenced series.

**The largest site straddles `STEP_SPLICE_CODES`, and that explains a
mystery already written down.** The sine's own largest staircase step is
~38 codes and the census line is 45, so a capture whose largest site is
14.6 (38 + 14.6) crosses it and one whose largest is 5.1 does not -
measured in one session, 776 steps over 45 codes in the first case and
**0** in the second.
`tools/splices.py`'s docstring records "ten runs reported 0 splices on
A0 across a period when six runs in ten were dirty on A1", and calls it
the tool saying "does not reproduce" about a board that was
reproducing. Six in ten is how often the largest site was above the
line. A threshold sitting inside the range an artifact's amplitude
moves through reports where in that range the capture landed, not
whether the artifact is there.

**That is a trap for every A/B measurement on this artifact**, and it
has already caught one. `tools/acr_issue5.py` compares two DACC_ACR
arms by mean |peak| over a handful of captures; when the peak is an
argmax over sites whose values move between 1 and 14 codes, six
captures per arm sample that movement rather than the arm. Its 0x000
span of 2.9-14.1 codes against 0x10A's 9.7-14.4 is what two samples of
one distribution look like. Compare per site, never the mean of the
peak. It is attributed to a DAC output pin effect,
not a splice and not stream_stop: the capture-side accounting is clean
through every observation.

Why closed within tolerance: 1-8 codes is 0.02-0.2% of full swing, on
one sample in 256, against the ~20 mV (~25 code) standing noise the
DAC carries on *every* sample. No user of the generator can see it
without the coherent folding the suite's instruments perform
(`measure.gen_fold_len()` and the issue-#5 fold tools), and nothing
downstream depends on it. Recorded draws at closure, macOS bench,
2026-08-28 suites: -2.9 codes at phase 44 (Track A), +1.0 at 202,
+7.3 at 177, -1.8 at 117 (Track B); the windows-desk record is inside
the same bound.

The guard outlives the closure, and **until 2026-08-29 it did not
guard the thing this paragraph said it did.** The xfail asserted the
z-score discrimination and reported the amplitude; nothing anywhere
looked at the number. So a *grown* displacement did not fail a run -
it xfailed exactly like every other, and the suite stayed green while
the artifact doubled.

It had. Measured on the macOS bench on 2026-08-29 with `pair_fold`,
#5's own instrument on #5's own preset: the phase-177 state reads
**14.1-14.5 codes** across eight draws, against the `+7.3 at 177` in
the closing record above - the same state, at twice the magnitude. The
comparison is phase-matched and amplitude-matched, which is the only
way it means anything given the two-state draw. The DAC bias does not
account for it; both ACR arms draw from the same two states.

`tests/test_integrity.py` now bounds the amplitude at
`DISPLACEMENT_VISIBLE_CODES`. The trip point is the closing argument's
own criterion rather than a fresh number: what made the displacement
ignorable is that it sits under the ~25 codes of standing noise every
sample already carries, so the guard fires when it stops doing so. **A
bench that trips it should reopen #5, not raise the number.**

## The same shape on the host-fed ramp (issue #24)

**One sample per DAC table wrap comes back low by ~17-30 ADC codes on
the host-fed ramp too, and it is what the "bidirectional jitter storm"
is made of.** The ramp encodes its own position, so a single
wrong-valued sample reads as a jump out and a jump straight back at
adjacent indices - a matched forward/backward pair. Thousands of those
per window is one displaced sample per wrap, counted twice each, and
not jitter at all. Read off the codes rather than inferred:

    codes [780, 784, 791, 796, 784, 807, 812, 818, 823, 829]
    diffs [4, 7, 5, -12, 23, 5, 6, 5, 6]

with consecutive pairs at 199586, 200098, 200610, 201122, 201634 -
exactly 512 apart, one ramp wrap each.

**Two things follow, and both are traps the issue fell into first.**

*The "+-5-9 samples" is a property of `RAMP_STEP`, not of the defect.*
A fixed code error divided by a steeper ramp is fewer samples: mean
|n| reads 10.4 at step 4, 5.5 at step 8, and nothing at step 16, where
the same codes fall under the analysis's 3-sample tolerance. Quote the
codes; the sample count is an artifact of the instrument.

*It is periodic in the table, not in the clock.* Hold every rate fixed
and change only the ramp step and the spacing follows the table period
(512 captured samples at step 8, 1024 at step 4). Halve `dac_sps` and
the count halves with the wrap count - 3128 events becomes 1564, both
exactly 4 per wrap. Events per wrap are integers: 2.0, 4.0, 6.0, 8.0.
A residual spectrum has **no line at 522 Hz** - 1.4-3.8x the noise
floor there in storm and clean runs alike - and the only line present
is the wrap rate, tracking `dac_sps` at 390.6 Hz and 195.3 Hz.

The "~522 Hz, rate-invariant wall time" reading that this replaces is
worth keeping as arithmetic. Counts were divided by a nominal 3 s
window; the analysis starts at `SETTLE_US`, so the window is ~2.0 s -
782 wraps at 200 ksps, 391 at 100 ksps. A full-rate *forward* count of
1567 is 2/wrap and a half-rate *total* of 1565 is 4/wrap, and 2 x 782
and 4 x 391 are the same number. Comparing a forward count against a
total made a count that halves look like one that does not.

**Not windows-only, and the record that said so could not have said
it.** Storms fire on the macOS bench at roughly half of all draws,
including one of 223,557 events against windows-desk's 228,893. The
250-draw macOS record quoted for "zero here" carries only
`pass`/`fail_device` and has no field that could have held the class.

`tools/issue24_phase.py` is the instrument, stdlib-only so both benches
run the same one; 46 runs in `records/issue24-phase-macos.jsonl`.

**It is device-side, and the two issues are now measured in the same
units.** `tools/issue24_fold.py` runs #5's `fold_profile` statistic on
both paths, interleaved run by run in one session so warm-up and
weather cannot favour either:

| path | displacement |
|---|---|
| internal generator, no host in the DAC path (`pair_fold`, preset M) | **14.3 codes**, stable, phase 177 |
| host-fed ramp, storm draw | **30.1-31.0 codes** |
| host-fed ramp, quiet draw | 0.9-12 codes |
| control period, either path | 1.7-1.8 codes |

The artifact is therefore present at 14 codes with **no host in the DAC
path at all**, which retires every host-side lead #24 accumulated -
usbser.sys, feed backpressure, write pacing, the operating systems.
What the host-fed path adds is roughly a doubling and an on/off
behaviour: the fold reports the *average* displacement over the wraps
it folds, so a quiet draw is the artifact appearing in a minority of
wraps rather than a smaller artifact.

**The displacement is not proportional to the signal - it grows as the
signal shrinks.** Held at the phase-177 state and moving only the
internal generator's amplitude:

| generator amplitude | signal span | displacement |
|---|---|---|
| 256/256 | 2749 codes | 14.1-14.5 |
| 128/256 | 1377 codes | 28.07, 28.11 |
| 64/256 | 693 codes | 35.4, 36.2 |

So it is not a slew or settling character on this path - the ADC
catching the converter mid-transition would shrink with the slew, and
this does the opposite. It is not a fixed code offset either. On the
host-fed ramp the same question reads additive: changing `RAMP_STEP`
moves the per-sample step by 2x while `n * slope * step` stays at
~28-30 codes. Small n on the amplitude arms (1, 2, 2 draws) - treat the
direction as measured and the coefficient as not.

Still open: whether the doubling on the host-fed path is the same
effect modulated or a larger sibling, and the mechanism for either.

## The gap

**The internal generator has no control-channel command.** `=<shape>,<pts>W`
is console-only, and the console is the programming port, which is
development-only. A deployed board is native-port-only, so today it can
be told what to capture and not what to generate.

The control channel is all queries - PING, IDENTITY, COUNTERS,
OCCUPANCY, RATE_TRACE, LOAD, STREAM_STATS, BENCH - so this would be its
first write. There is a place waiting for it:
`lib/due_shared/src/ctl_wire.h` reserves **0x001x for "state the host
both reads and writes"** and that range is empty, so shape and
resolution belong at 0x0010 rather than appended to the counter range.

It is cheaper than it was. The wire format and the whole parser are
shared source now, and both tracks compile them, so a new opcode is one
implementation reaching both boards rather than two hand-copies that
drift - which is the argument invariant 3 was rescoped on. What it still
costs is a `CTL_VERSION` bump, the device-side handler on each track,
and host plus daemon support. It is not done.

## The sync output, and the bench wiring it is for

`=<n>J` puts a trigger on whichever DAC pin is not carrying the
waveform - DAC1 in the normal layout. 0 off, 1 one square per waveform
cycle, 2 one per table wrap.

**Why it is worth a pin.** Triggering a scope on the signal it is also
measuring converts the pin's amplitude noise into time jitter, divided
by the slew rate at the trigger level - the whole of the section below.
A sync edge is a full-scale step every time, so the same noise buys
almost none, and the signal channel is then measured rather than being
asked to trigger as well. It cannot drift against the waveform, either:
one PDC stream and one trigger feed both channels, so the sync lags the
waveform by exactly one trigger period - the TAG interleave - and by
nothing else.

**It is also a better demultiplexing check than what it replaces.** DAC1
used to hold mid scale, and A1 reading flat was the evidence that the
channel tags were being read right. But a flat line is also what a
channel nobody writes looks like, so DC could never tell "correctly
holding 2048" from "not driven at all". A square can. Verified through
the ADC, which is the instrument that can still see DAC1 once its probe
has moved to EXT:

| sync | A1 span | samples in the middle third | verdict |
|---|---|---|---|
| OFF | 40 codes (2041-2081) | 47.6% | flat, as before |
| CYCLE | 2780 codes | **0.0%** | a clean two-level square |
| WRAP | 2785 codes | **0.0%** | a clean two-level square |

A0 stayed the sine (22% in the middle third) throughout.

### Wiring it to a DS1102E, and the two traps

**The EXT trigger level clamps at ±1.2 V, silently.** The DAC sits at
0.52-2.82 V, so the obvious threshold is its 1.67 V midpoint - and the
instrument accepts `:TRIG:EDGE:LEV 1.67` and holds **1.20**, with the
readback agreeing and nothing reporting an error. DC-coupled at x1 the
sync therefore sits entirely above the highest reachable threshold and
**never triggers**.

**The probe ratio moves the whole window, and the window is 100 mV
wide.** Measured on this bench with a x10 probe on EXT, sweeping 25
levels x 2 slopes x 2 couplings:

| coupling | levels that trigger |
|---|---|
| DC | 0.1, 0.2 V |
| AC | 0.0, 0.1 V |

Nothing else in -1.2..+1.2 V fires, on either slope. A sweep at
0.0 / 0.3 / 0.6 / 1.0 / 1.2 steps straight over it and concludes that
EXT does not work - which it did here, for three runs.

So **the level is discovered, not assumed**:
`scope.Oscilloscope.ext_trigger_autoset()` sweeps coupling and level
until the instrument actually triggers and returns what worked. `None`
from it means no signal is reaching the input, which is a cable fault
and not a level to guess harder at.

### What the sync actually buys, measured

Internal generator, trigger 200 kHz, 20 acquisitions each, jitter as the
circular standard deviation of the waveform's phase at the trigger
point. Only the trigger source changes:

| shape | pts | trigger on the signal | trigger on the sync | |
|---|---|---|---|---|
| sine | 32 | 90.720 us | **0.408 us** | **222x better** |
| ramp | 64 | 5.633 us | **2.614 us** | 2.2x better |
| square | 32 | **0.007 us** | 1.471 us | 210x *worse* |

**The square row is not a defect in the idea, it is the x10 probe.** A
square's own edge is already a full-scale step into a 1 MOhm channel at
full amplitude, so triggering on it is as good as triggering gets. The
sync reaches EXT through a x10 divider as 230 mV against the DS1102E's
own 200 mV EXT sensitivity floor, so the sync edge is the noisiest thing
in that setup. Backed out at full scale: `sd x amplitude` = 197 mV-us,
the same form as the signal-triggered case.

**Fit a x1 probe to EXT.** 2.3 V instead of 230 mV predicts sd ~0.086 us
for the square, ~0.04 us for the sine and ~0.26 us for the ramp - the
sync then wins everywhere except against a square's own edge, which
nothing beats. AC coupling is then mandatory, not optional, because
1.67 V is past the clamp.

**Done, 2026-08-27.** With x1 fitted the autoset finds `AC coupled,
level +0.00 V` on its first candidate, and every shape triggers -
including DC, which has no edge of its own and previously needed AUTO
sweep and therefore proved nothing. The x10 numbers above are kept
because they are what made the amplitude limit visible.

### Arm the trigger once, and after the output is running

Two ordering mistakes, both of which read as a hardware fault:

- **Searching a stopped converter.** The autoset looks for an edge, so
  it must run with the output going. Called before the trigger started,
  it reported "no signal is reaching EXT" on a perfectly good cable.
- **Searching inside each measurement window.** A full-range sweep is
  ~44 s of instrument time, which is longer than the window it was
  called inside - it kept driving the instrument after the output had
  stopped and collided with the next acquisition, surfacing as
  `USBTimeoutError` rather than as the ordering bug it was. The probe
  and the sync do not change between combinations, so arm once per run
  and re-assert the found setting after that.

The level ladder searches outward from zero for the same reason: AC
coupling centres the sync on 0 V, so the first candidate is the answer
on a correctly-fitted probe.

### Measuring jitter: fold to phase first

"The crossing nearest screen centre" is not a stable ruler once the
trigger's phase differs from the crossing's. The sync rises at table
index 0 and a ramp crosses mid half a cycle later, so the nearest
crossing flips between two that are a whole period apart and the spread
reads as **96% of a period on a trace that is perfectly still** - which
is what the first run of the table above reported. Fold each crossing to
a phase and take circular statistics; the ambiguity the measurement
created goes away and the one it is trying to measure does not.

---

# Why the trace shakes horizontally on the bench scope

Reported from the bench: the trace moves sideways, "sine and ramp on some
frequency is very profound", ramp worse than sine. Reproduced, and the
cause is the instrument's trigger, not the board.

## What it is

**Amplitude noise at the trigger level, divided by how fast the waveform
crosses it.**

```
t_jitter = V_noise / (dV/dt at the trigger point)
```

## The measurement that shows it

One waveform, one rate, one framing, streamed playback at 200 ksps. Only
the ramp's step changes, and with it the slew rate at the 1.67 V trigger
level. The staircase geometry, the DAC, the USB feed and the ring are
identical throughout. 30 acquisitions each, jitter is the standard
deviation of the crossing nearest the trigger point:

| ramp step | V/div | period | slew rate | jitter sd | **sd x slew** |
|---|---|---|---|---|---|
| 2 | 0.50 | 10,240 us | 0.234 mV/us | 74.82 us | **17.53 mV** |
| 8 | 0.50 | 2,560 us | 0.937 mV/us | 27.57 us | **25.85 mV** |
| 32 | 0.50 | 640 us | 3.750 mV/us | 6.01 us | **22.52 mV** |
| 8 | 1.00 | 2,560 us | 0.937 mV/us | 23.49 us | **22.02 mV** |
| 8 | 0.30 | 2,560 us | 0.937 mV/us | 18.64 us | **17.47 mV** |

The jitter spans **12x**. The product is constant at about **20 mV**.
Underruns were 0 on every one of those rows.

Measured independently, DAC0 held at code 2048, AC coupled at 0.05 V/div:

| | Vpp | Vrms |
|---|---|---|
| board idle, DAC not driven | 118.0 mV | **15.1 mV** |
| DAC0 held at code 2048, streaming | 104.0 mV | **20.2 mV** |

20.2 mV, against the 17.5-25.9 mV the slope experiment backed out without
knowing it. Predicted ramp jitter at step 8 from the noise alone:
20.2 / 0.937 = 21.6 us; measured 27.6 us.

**Most of the noise is there with the DAC not driven at all.** It is a
probe and board floor, not something the stream creates - streaming adds
about 5 mV to a 15 mV floor.

## Why the shapes rank the way they do

Where each waveform crosses the 1.67 V trigger level:

| shape | slew at the trigger point | jitter, as a fraction of one period |
|---|---|---|
| square | full-scale step, effectively infinite | **0.0 - 0.2 %** |
| sine, 32 pts/cycle | ~45 mV/us | 0.3 - 2.7 % |
| ramp, step 8 | **0.94 mV/us** | 3.3 %, sd 27 us |

That is the whole of the reported observation, in order. Ramp is 30-60x
worse than sine because its staircase rises **4.5 mV per sample**, and
square does not shake at all because a full-scale step gives noise
nothing to work with.

Across the AWG ladder the fraction stays roughly flat - sine 0.3-2.7%,
square 0.0-0.2% - because slew rate and period both scale with the sample
rate and the ratio does not.

## What to do about it

Nothing in the firmware. This is a measurement setup property:

- **Trigger on a steep part of the waveform.** For a ramp that means a
  bigger step, which is a resolution choice - `--ramp 32` shook 12x less
  than `--ramp 2`.
- **Shorten the probe ground lead.** 15 mV of the 20 is present with the
  DAC idle.
- **The DAC has no output buffer.** Phase 3's front end is where this
  actually improves; see `docs/hardware-next.md`.
- **`DACC_ACR` is at reset, not at the datasheet's characterisation
  condition.** `=2,1I` is the Arduino core's value. Untested against this
  measurement.

## What it is not

- Not underruns. 0 on every shaky row, and `PLAY_PRIME_BUFS = 24` took
  the ladder to zero.
- Not the host feed, the ring, or the transport. The internal generator,
  with no USB in the path at all, shakes the same way for the same
  shapes.
- Not the frame or sequence path. Nothing was discontinuous.

## The GUI shakes too, and for a completely different reason

Worth writing down so the two are never confused. `gui/app.py` draws
`ring.window(n)` on a 33 ms timer: **the most recent N samples, with no
trigger and no phase alignment of any kind.** The trace's horizontal
position is therefore `(samples arrived since the last redraw) mod
(samples per cycle)`, and nothing pins it.

Board-free, 200 ksps, 2 channels, so frames deliver 1024 samples per
channel:

| tone | samples/cycle | phase step per redraw | on screen |
|---|---|---|---|
| 390.6 Hz | 512 | 0.000 | still |
| 977 Hz | 204.71 | 0.013, 0.016 | slow crawl |
| 1,000 Hz | 200 | 0.720, 0.840 | blur |
| 3,125 Hz | 64 | 0.000 | still |
| 6,250 Hz | 32 | 0.000 | still |

A still trace needs `rate/tone` to divide 1024. Every other frequency
moves on every redraw. **This is a missing feature - the front end has no
software trigger - and it is unrelated to the bench-scope finding above.**
