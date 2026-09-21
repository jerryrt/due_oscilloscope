# How much of the converter this board leaves you

The Due wires a 78 MHz Cortex-M3, a high-speed USB PHY and two DMA
engines to the same ground and the same 3.3 V rail as its converters,
and ADVREF - the reference the ADC *and* the DAC share - comes off that
rail. That is not a defect to fix. It is what the hardware is, and a
high-accuracy instrument would not be built this way.

What it must not be is a guess. This is the measured cost, in bits, so
that an AFE, an external converter or a layout change can later be
judged by how far the number moves rather than by how it looks.

    python3 tools/noisetool.py dc          one held level, in bits
    python3 tools/noisetool.py activity    what each digital load costs
    python3 tools/noisetool.py alias       which spectral lines are real
    python3 tools/phase0.py noise-fast --runs 7    its repeatability

**No instrument is needed for any of it.** The ADC is the instrument:
one code is 0.80 mV against the DS1102E's 3.1 mV at its best usable
gain, and it takes 453,488 samples a second. `docs/measurement-suite.md`
already called this Tier 3; this is the first thing to use it. Which
also means these figures can be re-taken on any bench, by anyone, and
compared - which is what makes them a standard rather than a reading.

## The figure of merit, and why it is bits

Millivolts do not survive a hardware change. Put a 16-bit converter with
a different span on the same signal and a figure in millivolts is
incomparable, which defeats the purpose of measuring at all.

Bits do survive it. An ideal N-bit converter has quantisation noise of
1/sqrt(12) LSB rms and nothing else, so observed noise converts directly
into the resolution an ideal converter would need in order to be this
noisy. Two conventions, both reported:

    effective bits   = N - log2(rms_lsb * sqrt(12))
    noise-free bits  = N - log2(rms_lsb * 6.6)

The first is the rms-equivalent resolution. The second is the vendors'
convention - 6.6 sigma spans 99.9% - and answers a different question:
how many bits are steady enough to *read off a display* rather than to
average down.

Everything in `host/noise.py` takes volts and bits with the LSB size as
a parameter, never Due codes, for the same reason `host/trace.py` takes
seconds and volts: a constant tuned against one converter is a constant
that silently misreports the next one.

## What this board measures at

A0, driven by DAC0 holding a fixed code, macOS/DSO bench, Track B,
**firmware at or after `623d4dc`**. That qualifier is load-bearing: see
the retraction below.
`records/phase0-noise-fast-after-623d4dc.jsonl`.

| | |
|---|---|
| noise | **1.65 codes rms** (1.61-1.75), about 1.3 mV |
| effective resolution | **9.49 bits of 12** (9.40-9.52) |
| noise-free resolution | **8.56 bits of 12** |
| against an ideal converter | **5.7x** the quantisation floor |
| repeatability, n=7 in place | **0.116 bits** |

So about **two and a half bits of twelve are gone**, and the bottom two
to three bits of any single reading are noise. Averaging recovers them at
the usual sqrt(N), which is what makes the ADC still the finest
instrument on this bench - and what `host/eqtime.py` relies on to fold a
settling curve down to 0.28 codes.

### Everything above was 8.2-8.4 bits until the firmware was current

**Retracted, and the mechanism is not this bench.** The figures first
published here were taken on a build five minutes older than `623d4dc`,
*"dac: make the sync's amplitude settable, and clear it of the
disturbance"*. Reflashed from current `main`, on the same board and the
same desk:

| | before `623d4dc` | after |
|---|---|---|
| noise | 3.27 codes rms | **1.65** |
| effective resolution | 8.50 bits | **9.49** |
| spread over 7 runs | 0.50 bits | **0.116** |

A whole bit recovered, and the spread down more than fourfold.

**And the old spread was never repeatability.** Sorted, those seven runs
were `3.128 3.167 3.171 3.274 3.457 | 4.345 4.426` - two clusters with a
gap 2.7x wider than either, which is a board flipping between two states
rather than a measurement scattering. The Windows bench saw the same
signature on its own board and found it the same way (issue #10). A
tolerance derived from that number would have been a tolerance on a
bimodality.

The lesson is cheap to state and was expensive to find: **a version
string is not a build.** Both benches reported `fw 0.2.0` and were four
hours and three DAC commits apart.

## What the noise is, and what it is not

Every one of these is a measured negative, and each closes off a line of
attack that would otherwise have been guessed at.

**It is not a discrete aggressor.** Zero spectral lines above the floor
in 7 runs of 7, and zero in every arm of the interleaved sweep. Nothing
here is a clock, a switching supply or a USB frame rate leaking in at
one frequency: the noise is broadband. So there is no filter to add and
no line to reclock away, and an AFE would have to lower the whole floor
rather than notch anything.

The first version of this measurement *did* report 5-7 lines per run,
at frequencies that changed every time and with a line power fraction
that ranged over 206% run to run. Those were the tail of the estimator,
not the board - a single 4,096-point window of a 900,000-sample capture
uses 0.5% of what the bench time bought. Averaging every window (Welch)
divides the estimate's variance by the number of windows, and the lines
vanished and stayed vanished.

**It is not drift.** 0.07-0.09 codes of wander across seconds, against
4 codes of fast noise. The level is steady; what moves is inside the
moment.

**It is not mains.** At 14 Hz bins - a 32,768-point window - there is
nothing at 50 or 60 Hz. Worth stating because the default 4,096-point
window *cannot* see mains at all: a bin is 111 Hz wide and 50 Hz sits
below the first usable one. A negative from the default window would
have meant nothing.

**It is not obviously the conversion rate.** Doubling the trigger rate
from 200 ksps to 453,488 - and with it the whole inbound USB stream -
is unresolved in both sweeps below, bounded at **0.19 and 0.13 bits**.

## What the digital side costs: nothing this can resolve

Two interleaved five-round sweeps on current firmware, paired within
rounds:

| arm | first sweep | second sweep |
|---|---|---|
| host-fed playback vs internal | not resolved, **< 0.043 bits** | not resolved, **< 0.072** |
| 200 k -> 453 ksps | -0.066 +- 0.015 | not resolved, < 0.037 |

Neither arm is resolved here. The rate arm came back *resolved at four
standard errors* in the first sweep and unresolved in the second, which
is why one sweep is not a result - though on a bench with a lower floor
it resolves cleanly and turns out to be bandwidth rather than a cost;
see below.

### The rate arm is bandwidth, and cannot answer what it was asked

Confirmed on the Windows bench, which bounds the playback arm at
**< 0.105 bits** over nine rounds - the withdrawal above holds on a
second board and a second host, this time with both benches on the same
build. Its first five-round sweep read `-0.209 +- 0.087`, a 2.4-sem
near-miss, and its second could not resolve the arm at all against a
0.96-bit spread; nine rounds bounded it. Three false positives in this
investigation have now come from one five-round sweep.

**The rate arm is a different matter: it resolves, and it is not a
cost.** That bench reads `-0.177 +- 0.002` across sweeps of 5, 5 and 9
rounds agreeing to 0.004 bits. Integrating the spectrum over the band
the two arms *share* says why. ENBW scaling is the same constant for
both windows and cancels:

| band | 200 ksps | 453 ksps |
|---|---|---|
| 0-100 kHz, which both rates can see | 0.845 codes | **0.657** |
| 100-226 kHz, which only the fast rate sees | - | 0.688 |
| total rms | 0.845 | 0.952 |

**The faster rate is quieter in the band both can see.** All of its
extra noise sits above 100 kHz, where the 200 ksps arm has no Nyquist to
see it with. So comparing rms across two sample rates compares two
measurement bandwidths: the arm answers "is there noise between 100 and
226 kHz" - there is, 0.688 codes of it - and not "does converting faster
cost anything".

That is the same missing anti-alias filter the `alias` section is about,
one level down, and it explains the arm's whole history: unresolved on
both benches while the firmware bimodality was larger than it, resolving
the moment that was fixed, and resolving to different magnitudes on two
benches because what it measures is each bench's own high-frequency
content.

To ask the original question the arms have to be equalised - decimate
the fast one to the slow one's bandwidth, or low-pass both to a shared
band - before they are compared. Not done.

### The 0.26-bit playback cost is withdrawn

This document previously reported **-0.234 to -0.292 bits** for host-fed
playback, from two sweeps here; the Windows bench then reproduced it at
-0.184 and -0.256 on a different board and a different host. Four
sweeps, two benches, all inside one standard error.

On firmware at `623d4dc` or later it is **not resolved, and bounded
below 0.07 bits** - five to seven times smaller than what was reported.

**Cross-bench reproduction did not save it, and the reason is worth
keeping.** Both benches were running pre-`623d4dc` firmware. Two boards
and two hosts test the board and the host; they do not test the *build*,
because the build was the thing the two benches had in common. A result
that reproduces across every variable you thought to change is only as
strong as the list of variables you thought to change.

So the honest state of the activity question is a **bound**: whatever
the digital side costs this converter, it is under 0.07 bits, and the
0.26 was a disturbance in the generator that has since been fixed.

## ADVREF: the loop cannot see it, and that is arithmetic

The obvious suspect for a noise floor is the reference, and it is the one
node both converters share. It is also the one thing this loop can never
measure, and it is worth being precise about why rather than repeating
"ratiometric".

The DAC's output is nominally 1/6 to 5/6 of ADVREF, so
`V = ADVREF * (1/6 + code/4096 * 2/3)`, and the ADC returns
`4096 * V / ADVREF`. The reference divides out:

| code | nominal | ADC reads | with ADVREF 1% high | shift |
|---|---|---|---|---|
| 0 | 545.0 mV | 682.7 | 682.7 | **+0.000** |
| 2048 | 1635.0 mV | 2048.0 | 2048.0 | **+0.000** |
| 4095 | 2724.5 mV | 3412.7 | 3412.7 | **+0.000** |

A 1% reference excursion moves the loop by zero codes **at every code**.
Against a non-ratiometric input the same excursion is worth 10-20 codes.
There is no measurement to be cleverer about: the term is divided away
before anything here sees it.

### What the loop can still say, and does

Reference noise is *multiplicative* - it scales with the output level -
while the ADC's input and comparator noise is *additive*. The DAC's span
is a 5.1x lever on the level, and that lever needs no rewiring.

Six interleaved rounds, paired within rounds, `records/noise-codes.jsonl`:

| level (codes) | 676 | 1020 | 1363 | 2050 | 2736 | 3422 |
|---|---|---|---|---|---|---|
| noise (rms) | 2.154 | 1.709 | 1.707 | **1.680** | 1.894 | 2.289 |

**Not monotonic.** It is a U with its minimum at mid-scale, and paired
against mid-scale the two ends resolve at `+0.440 +- 0.094` (bottom) and
`+0.370 +- 0.154` (top), with `+0.144 +- 0.062` at 3072 and nothing
resolvable at 1024.

Multiplicative noise rises with the level and does not come back down at
the bottom of the range. So **ADVREF's noise is not what is left in this
floor** - and the linear fit agrees from the other side: the
multiplicative term is 0.316 codes at full scale against a fit residual
of 0.220, which is not resolved.

A four-round sweep of the same thing resolved nothing at all, and an
earlier one reported "51% of the noise scales with the level" from six
points whose levels were **all identical** - the command driving the DAC
was setting an amplitude on a shape that has none. `scaling_fit()` now
refuses a fit whose level lever is under 1.5x, and prints the lever
either way.

### Where the U points instead

The noise is lowest at mid-scale and rises toward both ends of the DAC's
span - and 1/6 and 5/6 of ADVREF are exactly where that converter's
output stage is specified to stop. That makes the DAC's output stage near
its limits the first place to look, not the reference. Not chased here.

### What would actually see the reference

An input not derived from ADVREF. The board has exactly one on chip -
the ADC's internal temperature sensor, a bandgap-derived absolute whose
reading is proportional to `1/ADVREF`. It is the only route short of
external hardware, and it would also settle whether the ~0.44-bit gap
between the two benches lives in the reference.

Both tracks now enable it behind `ADC_ACR.TSON` and report it over
`CTL_OP_TEMP`, refusing while a capture is armed so sensor conversions
cannot enter the capture ring. The reading is an upper bound on
reference noise rather than a value: one channel cannot separate the
sensor's own noise from the reference's, though a comparison *between
benches* is a difference in which the sensor's contribution is common.

## An unused ADC channel reads its neighbour

Found while looking for a free control arm, and it matters well beyond
this measurement.

A1 is not connected to anything on this bench. In the same capture that
reads A0 at 2050.0 codes, **A1 reads 2054.3** - four codes away - with
25% more noise. That is not a fact about the two pins. There is one
converter behind a 16:1 mux, so an undriven input is converted through a
sample-and-hold still carrying charge from the conversion before it,
which was A0.

**An unused channel in the sequence does not read nothing. It reads a
smeared copy of the channel before it.** Anything using A1 in the same
frame as a reference is using a signal derived from A0 unless something
is actually driving A1 - which is true on the DSO bench, where DAC1 goes
to the scope's external trigger, and not true on the bench where DAC1 is
wired to A1.

## A bare pad reads its own relaxation, settled (issue #16)

**Closed 2026-08-29 with one number on two tracks and two benches.**
An unconnected analog pad, pull-up off, is an RC node: conversions
charge it toward an attractor near the previously converted channel's
level; any pause lets it sag, saturating within ~2 ms (~86 codes at
8 ms settle on A2, plus ~0.5 codes/ms of slow tail out to 40 ms), and
its absolute level walks with the read pattern (raw lo/hi: ~1700/1615
at 8 ms, down toward ~1100 at 40 ms). The `x` control arm measures
exactly this on a bare channel - **a bare-channel "control" is a
relaxation instrument, not a zero** - and reads -88/-90/-91/-93
across Track A/B x macOS/windows-desk, one number to a few codes.

The rule that survives: **drive your channels, or disregard
bare-channel codes.** A driven pin's control reads 0-2 codes
everywhere; nothing here touches a driven measurement.

It cost three instrument diffs to see one physical effect: the bleed
follows conversion *position*, not the pin; Track B's pull-up (reset
default, core-disabled on A) was worth 3.3x until b8d5509 equalized
it; and Track B's control arm hardcoded A1 while its bleed arms
honoured `=2C` (c17a576), so B's famous clean zero was the driven
pin, read by mistake - caught by the raw-level line, which can say
which pin a number was taken on when a delta cannot. When two tracks
disagree, diff the instruments before modelling the silicon - applied
three times on one issue. Conditions attest in-line now: `pioa:` pad
state, `adcmr`, raw lo/hi pairs, pair-conv retries (#23).

The one item deliberately left open when #16 closed: the 64 ms beat
in the excursion cadence (section below) was never excluded from
being USB-host-coupled; it too has never touched a driven channel.

## The die warms, so a sweep is confounded with time

Three separate measurements on this project have read as a clean
dependence and turned out to be the die warming, in one week and by
three different people. It is worth stating once here rather than a
fourth time in an issue thread.

- **The temperature sensor** (issue #11). A straight sweep across
  ADC track/settling read 998.50 -> 999.75 monotonically. That is
  ~0.4 C of warming across a 40 s sweep, not a dependence on the
  register.
- **DACC_ACR against effective resolution** (issue #13). The arms drift
  a few hundredths of a bit across a session in the direction that
  favours whichever arm ran last.
- **The settling fold** (issue #9), where the run order sets which
  configuration looks faster.

**The fix is pairing, not more repeats.** Interleave the arms ABBA
inside one session and difference within the round: a linear drift
cancels in the pair mean, and the round-to-round spread of the
*difference* is then an honest error bar. Averaging more of an
un-interleaved sweep makes a drifted number more precise, not more
correct - which is the failure mode worth naming, because a tight
confidence interval on a confounded measurement is what gets quoted.

`tools/acr_noise.py` and `tools/acr_issue5.py` are the shape: same
board, same session, arms alternated, difference reported per round.

Two corollaries.

**A first reading after a reset or a flash is not comparable with a
tenth.** The die is coldest when the board has just been power-cycled
and the run that immediately follows sits at one end of the drift.

**Report drift separately rather than letting it hide in the scatter.**
Successive-difference rms over sqrt(2) measures the noise; whole-run rms
measures noise plus drift, and the two must not be quoted under one
name.

## Pooling across a hidden variable manufactures modes

One level up from the drift trap, and the same shape: the summary
statistic is fine and the grouping is not.

Issue #5's artifact was reported here as **bimodal** - 2.7 codes or 11.7
codes on otherwise identical runs, the high mode 65% of the time - and
the second bench then measured 20 of 20 runs in one state. The
difference was not the boards. `pair_fold()` also reports
`peak_phase`, and grouping the first bench's own records by it dissolves
the modes: within a phase the spread is 0.07-0.26 codes, which is the
second bench's spread at its single phase.

So there were never two modes. There was one quantity that depends on
phase, sampled at three phases on one bench and one on the other.

**The rule: before calling a distribution bimodal, group it by every
label the instrument already reports.** `pair_fold()` was returning
`peak_phase` in the same dict the whole time. It cost a wrong model in a
commit message, an issue comment and a set of records - and the data to
refute it was inside the records themselves.

The general form is worth stating because it is not only about phase: a
mode is a claim that *no* remaining variable explains the split, and
that claim is only as good as the labels that were checked.

## The bleed excursion: the position says which channel, and a 64 ms beat says when

Issue #16, and the fourth measurement of the same quantity. `x` first
printed one draw of it; then a median and a range, which said the
quantity was spread and was read as *bimodal*; then the observations in
the order they were taken; and then the same command with the channel
pair as a variable. Two benches, both tracks, and the two halves of the
answer came from different ends.

**Which channel: the conversion position, not the pin.** A0 is ADC
channel 7, A1 is 6 and A2 is 5, and the sequencer converts by ascending
index - so in *both* pairings the watched channel converts **first** and
A0 **second**. `adc_read_pair`'s argument order only chooses which CDR
is read out afterwards. The two arms were never mirrors of one another
with the numbers exchanged: one watches the first-converted channel and
the other the second. Measured on `windows-desk`, 90 observations per
cell, both tracks: A2 shows the excursion **larger** than A1, and A0
never shows it at all - over 300 observations across two tracks and two
pairings, never past +-6 codes.

Whether the pin is *driven* sets the form rather than the presence. Both
benches that have measured this have DAC1 jumpered to A1, so A1 is
driven and recovers within the tracking time nearly always - an
occasional excursion. A2 is bare on both, cannot recover, and sits
permanently offset instead. That is this document's undriven-neighbour
finding reappearing one level down, inside `x`. **It predicts the DSO
bench**, where A1 is bare: `=1C` there should read like A2 here, a large
standing offset rather than an occasional excursion. Untested.

**When: a 64 ms beat.** Inside one invocation the loud observations
recur on a fixed cadence, and the cadence moves when the settle time
moves. Track A, `=15,<ms>x`, macOS bench:

    settle ms   observation   gap between    gap x duration
    (=<n>,<ms>x)   duration      loud ones
        2            16 ms           4              64 ms
        4            32 ms           2              64 ms
        5            40 ms           8             320 ms
        7            56 ms           8             448 ms
        8            64 ms           1              64 ms
       10            80 ms           4             320 ms
       13           104 ms           8             832 ms
       20           160 ms           2             320 ms
       40           320 ms     none in 60 observations

An observation is eight settle waits - two per arm, four arms - and the
last column is an exact multiple of **64 ms** in every row, with the
observed gap the smallest one that makes it so. Nine settings across a
20x range, one period.

At `ms` 8 the observation duration *is* 64 ms, so a run samples one
fixed phase and the prediction is all-or-nothing. Measured: one run of
15 loud observations at 162-168 codes and four runs with none. That is
the strongest single row, and it also reads the amplitude off a run that
is not sampling an edge - **~165 codes, 132 mV**. The 22/39/62/110/133
values in other runs are the window's edges, not modes, and neither
bench's "bimodal" survived a wider n.

### The control arm, and what it separates

Each arm carries a control that writes the same DAC code twice where the
real arm swings it: identical writes, waits and conversions, and the
only difference is that nothing moves. On the **driven** channel it has
never once been loud - **0** in 1,005 observations on Track A and 0 in
225 on Track B, against 10-15% on the swung arm. So the A1 excursion is
about DAC0 being at full scale, not about the reading.

**On the bare channel the control is loud too, and that is the point.**
`=2C` on the macOS bench, Track A, `=15,8x`, three runs, in order:

    A2 bleed    -170  +37  +80  +88  +90  +95  +96 ... +95
    A2 control  -140   +1  +28  +33  +35  +38  +41 ... +38
    A0 bleed      -1   -4   +2   +1   +0   +3   -1 ...  -1

Reproducible to a few codes across all three. So the bare pin carries a
**standing offset of about +37 codes that needs no swing at all**, and
the swing adds about +56 on top of it. Those are two different effects
and a command that reported only the swung arm would have quoted their
sum as one number.

It also has a **startup transient**: the first observation is -170, the
second near zero, and it converges over about four observations to the
plateau - three runs agreeing to within a few codes, so it is the pin's
charge state settling and not scatter. A bare input behind the
multiplexer takes a measurable time to reach whatever equilibrium
repeated conversions of its neighbour put it at.

Track A here plateaus at +95 against `windows-desk`'s +105 median for
the same arm, which is the closest two benches have come to agreeing on
this quantity.

### What is still open, and it is the mechanism

The position finding says which channel can show it. It does not say why
it is *periodic*, and the two do not obviously compose:

- **Nothing found has a 64 ms period.** Not the LED heartbeat - 100/900
  ms, and the main loop is blocked for the whole command so it never
  runs. Not the DACC refresh - microseconds, and `REFRESH` is an 8-bit
  field so even its maximum is a few milliseconds *(check: from the
  datasheet's 1024 x REFRESH / DACC clock, not measured here)*. Not
  anything counted in software, because the cadence tracks wall clock
  rather than the observation count, which is what the sweep measured.
  Of the ISRs that can fire while the loop is blocked - SysTick, UART,
  UOTGHS - none has one either. The USB host is **not** excluded: both
  tracks were enumerated on the native port throughout, and `=<ms>Z`
  blocks the main loop for its whole detach, so there is no way to run
  `x` while the port is down.
- **Track A used to convert the watched channel alone** - and still
  showed the excursion, which said that whatever the first-converted
  channel inherits, it was not inheriting it from A0 within a sequence.
  That instrument difference is closed below; the excursion survived
  closing it, so the observation stands and the explanation is still
  owed.

### The two tracks' `x` were three different instruments

Chasing why the tracks disagreed about the bare channel turned up three
separate differences. Two are now closed by construction and the third
is measured and open.

**The conversion sequence.** Track A converted the watched channel with
every other disabled; Track B converted the pair. Both convert the pair
now. Worth a sign flip and 3x on the `=2C` arm: +95 with a +37 control
before, -282 with -89 after.

**The conditions.** `x` inherited whatever last wrote `ADC_MR` - and
that was TRACKTIM 0 / SETTLING 0 on Track A against 15 / 3 on Track B,
the two ends of the range, because each track's `x` inherited its own
init. Tracking time is the dominant term for multiplexer bleed, so a
bleed figure taken at an inherited tracking time is a figure about the
previous command. Both tracks now set their own and restore it, exactly
as the temperature read does after issue #15, and `x` prints the
register it actually ran at rather than prose about it.

Setting them changed Track B by 22% (-1205 to -940 as TRANSFER went 2 to
1) and Track A not at all - so **tracking time was not the cause of the
disagreement**, which is worth recording as a measured negative.

**What is still different.** At identical sequence, identical `ADC_MR`
(readback `1f3f0100` on both) and an identical `micros()` settle spin:

    Track A   -282 bleed   -89 control
    Track B   -940 bleed     0 control

on the same board minutes apart. `DACC_MR` and the `DACC_ACR` bias
defaults are byte-identical across the tracks, so it is not the
converter's configuration. The leading candidate is the **pad state of
the bare pin**: Track A boots the Arduino core, which configures every
pin, and Track B does not - and what else sits on a pad is exactly what
sets an undriven input's charge behaviour. Untested.

**So a bleed figure is still not comparable across tracks**, and a model
of the mechanism built on either track's number is built on the
instrument. That is the thing to close before the mechanism.

`tools/bleed_cadence.py` is the cadence sweep; `=<n>,<ms>x` and `=<n>C`
are the two knobs. Both need no instrument and run on either track.

## One DAC conversion in a few hundred to a few thousand lands off its level

**Now and then a DAC conversion lands a few codes off its level for
exactly one hold, and the next conversion is correct.** It happens on
both DAC channels, at every code including a held DC level, with any
waveform on either channel, and at any trigger rate. The error is
sign-symmetric, exponential in size and Poisson in time, and on A0 it
is uniform over the generator table. It is a property of the converter
as this board drives it, not a firmware defect, and nothing locked to
the table wrap remains once the refresh collision is fixed
(`docs/issue5.md`).

It is what the continuity census in `tests/test_integrity.py` still
counts on preset M, because that test's step threshold sits within about
12 codes of the largest legitimate step at that preset. The census holds
the rate at `RESIDUAL_STEPS_MAX`, with no period and no lock to the wrap.

### How large, per board

A hold's error is the second difference of hold levels. The rate is per
1000 holds, so it does not depend on the trigger rate. Preset
`=200000,200000M`, FWS 4, bias `=2,1I`; `windows-desk`'s figures are
pooled over start gaps `K` 0, 1, 5, 10 and 11, which the next table says
move A1.

| board | image | channel | beyond 6 codes | beyond 10 | scale, codes per e-fold | record |
|---|---|---|---|---|---|---|
| `linux-x1` | `049c99f`, Debian GCC 14.2.1, copper jumpers | A0 | 5.9-6.9 | 1.2-1.5 | 2.1-2.4 | `records/issue82-arms-linux-x1.jsonl`, the rows carrying `a0_parity` |
| `linux-x1` | same | A1 | 4.5-5.7 | 0.7-1.0 | 1.9-2.1 | same |
| `windows-desk` | `50ae7e6`, container xPack 15.2.1, iron jumpers | A0 | 0.63 | 0.030 | 1.3 | `records/issue82-ksweep-windows-desk-edges.jsonl` |
| `windows-desk` | same | A1 | 0.24 | 0.004 | ~1.0 (30 events beyond 10) | same |

**Compare boards by the scale, not by the count beyond a threshold.** On
an exponential tail the count at a fixed threshold moves a long way for
a modest change in scale. Here a count 9-11x apart on A0 and 19-24x
apart on A1 is a scale 1.6-1.8x apart on A0 and about 2x on A1. The two
boards differ in image and in jumper material, and nothing measured
separates those from the die.
`windows-desk`'s scale is from two thresholds, `(10 - 6) / ln(rate>6 /
rate>10)`; `linux-x1`'s is the mean excess over 4 codes, in
`tools/issue82_arms.py`.

### The census margin on three boards, and what the threshold does

The continuity test prints its census on every run since `27d6a38`,
pass or fail, because the day one board failed it 5 of 5 while two
others passed on the same firmware, no bench had a figure from a
passing run to compare against. Preset M at 200 ksps, 3 s, Track B,
one afternoon, first run dropped where more than four were taken:

| board | largest step, codes | steps over 45 (allowance 100) | n |
|---|---|---|---|
| `windows-desk` | 43.5-50.0, median 45.5 | 0-31, median 1 | 9 |
| `mac-bench` | 46.5-48.0 | 5-22 | 4 |
| `linux-x1` | 65.5-75.0 | 376-474 | 8 |

The staircase's own largest step at this slope is about 38 codes, so
the two passing boards read 38 plus 6-12 of tail and the failing one
38 plus about 27. On the exponential tail above that is not the same
distribution drawn twice: an excess of 27 at the scale this table
recorded for `linux-x1`, 2.1-2.4 codes per e-fold, would be one hold
in a few hundred thousand, and the capture shows one in fifteen
hundred - a scale nearer 3.7. **The tail on that board has grown since
`049c99f`**, on an image both other boards pass with, with the wiring
confirmed electrically and no host or USB term in it (the steps are
single, Poisson-spaced and off the frame boundaries). What grew it is
open; the benches have been identically jumpered since 2026-09-12, so
the jumper material in the table above is no longer a term.

**Re-taken the same evening on all three boards at one artifact hash**
(`d82d72c`, `track_b_bringup.bin 8aad4bcb…`, Track B, six runs each with
the first dropped, board idle a minute first): `windows-desk` largest
43.0-45.5 on a direct port, `mac-bench` 44.0-45.0 behind a hub - and
twelve consecutive runs there at 43.0-45.0 - and `linux-x1` **53.0-56.0**
behind a hub, all on mains. Three boards running a binary identical to
the byte and differing by 8-12 codes on the largest step removes the
firmware from the comparison outright, and the hub with it.

**And the failing board's tail has a part that grows with use.** After
twenty minutes idle it read 56.0 and 57.0 with 91 and 94 steps, passing,
where the same board driven continuously all afternoon read 65.5-75.0
with 376-474. So its tail is the intrinsic ~1.7x above plus an activity
or thermal term of ten to twenty codes at the largest step, which is
what took it from a pass on 2026-09-15 to eight fails in a row after a
day of fuzzing, tiers and flashes, and what now leaves it passing nine
to twenty-five steps under the allowance. A healthy board shows the
same term at about three codes over ninety minutes. **A row from that
bench carries how long the board had been driven, or it is not
comparable**, and whether the term belongs to the board or to the
bench needs a second Due on that bench, which nothing in software can
substitute for.

### Rotated: the tail follows the board

The three boards were then rotated across the three benches, every
bench ending with a different board, and each bench took the same
rested row on the same pinned image before and after
(`tools/rotation_row.py`, `records/rotation.jsonl`, identity by the
SAM3X's own unique identifier). Largest step, median of five with the
first run dropped:

| board | own bench | other bench | moved with the board |
|---|---|---|---|
| `…3230323239313032` | `linux-x1` **54.5**, scale 2.35-2.40 | `mac-bench` **53.0**, scale 1.75-1.80 | -1.5 codes |
| `…3030363139303038` | `windows-desk` 45.0, scale 1.02-1.04 | `linux-x1` 45.5, scale 1.63-1.69 | +0.5 |
| `…3030393039303034` | `mac-bench` 45.0, scale 0.76-0.83 | `windows-desk` 45.5 | +0.5 |

Changing the bench moves a board by 0.5-1.5 codes; changing the board
moves a bench by 8-9. **One board carries a converter tail about twice
the other two's, and it is the board** - not the firmware, which was
byte-identical everywhere; not the Linux bench, which read 45.5 with a
healthy board in the same place; and not the test. The afternoon
figures of 65-75 on that board, taken while the host ran gates and
fuzz, remain unexplained by anything measured and were not chased.

Three things the rotation showed that must not be read as settled:
the die-temperature code compares a board only against itself (49
codes between two boards on one bench is the sensor's per-part offset);
the crossing *count* moves with the bench where the largest step does
not - 91 against 44-67 for one board - because the threshold sits inside
the distribution; and the tail *scale* carries a bench term of +35-60%
that the census does not, small beside the 2x between boards and not
explained.

**What the 45-code threshold does, read off the healthy boards:** it
sits at their largest step, not above it. `windows-desk` crosses it on
0, 1 or 2 holds per run and once on 31; `mac-bench` on 5 to 22. So the
code threshold does not separate a healthy board from the tail - the
**allowance of 100 does**, and a count near it is not a healthy board
having a bad day but a board whose tail has reached the line. Do not
tighten 45, and do not read a count under 100 as clean without its
largest step beside it; the scale is the comparable figure, as the
table above already says of the tail itself.

### What moves it

| knob | effect | measured on |
|---|---|---|
| output bias, `=<a>,<b>I` | 2-3x; `2,1` lowest of `0,0`, `2,1` and `3,3` | `linux-x1` |
| flash wait states, `=<n>q`, 4 to 6 | A1 up, A0 down: `linux-x1` 1.3x and 0.75x, `windows-desk` 2.6x and 0.64x | both |
| ADC-to-DAC start gap, `=<us>K` | about 2.4x on A1, periodic in 10 us at 200 ksps, which is one hold | `windows-desk`, not registered before it was taken |
| the waveform, a changing code against DC, the other channel, 100 against 200 ksps, `DACC_MR_MAXS`, a main-loop stall, phase against the ADC frame, SysTick and the USB frame | nothing resolved | `linux-x1` |

The start gap and the wait state both move the DAC's conversion against
the ADC's sampling instant, and the bias moves the output stage. That is
consistent with the ADC catching a conversion's settling at a varying
phase. It is not established.

### Reading it without inventing structure

| rule | why |
|---|---|
| **Take a channel's hold pairing from its own square edges or staircase, and never break a tie** | A moving waveform settles the pairing by the smaller median pair difference. A flat channel ties the two. A tie broken the wrong way pairs the last sample of one hold with the first of the next and halves every error, which read as a 20x start-gap effect, a channel "clean at DC" and "switched off at FWS 6", none of them real. `hold_parity()` in `tools/issue82_ksweep.py` refuses a tie and a capture whose edges disagree |
| **Do not derive one channel's pairing from the other's** | A0's and A1's pairings move independently with the start gap and the wait state: both 1 at `K` 5 and 10, both 0 at FWS 6 |
| **Count per hold, not per second** | A per-second rate at another trigger rate is off by the rate ratio |

## What this method cannot do

Stated here rather than discovered later, because a plausible number is
the expensive kind of error in this project.

**There is no quiet arm.** Measuring the ADC requires running the ADC
and shipping the result over USB, so every arm has digital activity in
it. What is measured is a *difference between loads*. A residual common
to all of them - and the 4-codes floor may be exactly that - is
invisible to this method entirely.

**It cannot separate the DAC's noise from the ADC's.** A0 is wired to
DAC0, so a held level carries both converters plus whatever the board
couples in between. A1 is not the control that would fix this, for the
reason above. Separating them needs a source that is not this board's
DAC.

**It cannot see below the fold.** There is no anti-alias filter anywhere
on this board, so wideband noise above 226 kHz folds into the band and
appears as part of the broadband floor. A line seen at one sample rate
is a candidate and nothing more, which is what `alias` exists for: a
real line sits still at two rates, an alias moves.

**It cannot reach mains without a long window**, and the default window
does not. Use `--window 32768`.

## What would move the number

In the order the measurements above argue for, rather than in the order
a datasheet would suggest:

1. **Nothing narrowband.** The floor is broadband with no lines, so
   notching, reclocking or moving a frequency is not the lever.
2. **A buffer and an anti-alias filter**, because folding is the one
   mechanism this bench has established is available and unmitigated.
   Everything above 226 kHz currently lands in-band.
3. **Separating the analog supply and reference from the digital rail**,
   which is the only route to a floor common to every arm - the part
   this method is blind to and cannot rule out.
4. **An external reference**, which is what finally lets any of this be
   stated in volts rather than in ratios of ADVREF to itself - and is
   the calibration direction the project now takes (`docs/scope.md`,
   open questions): one precision voltage reference per bench on a
   spare ADC pin, two ADC points per board for offset and gain, the DAC
   inheriting through the loop, applied on the host and kept per board
   under the die's own identifier. Averaging boards cannot stand in for
   it: the loop is ratiometric, the part common to every board does not
   average away, and the three boards here share one lot prefix in
   their identifiers, so their mean is the lot's, not the part's.

Each of those is judged the same way afterwards: re-run
`tools/noisetool.py activity`, interleaved, and read the paired
difference in bits.
