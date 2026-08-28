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

An input not derived from ADVREF. The board has exactly one on chip - the
ADC's internal temperature sensor, a bandgap-derived absolute whose
reading is proportional to `1/ADVREF` - and it is not enabled in either
firmware. Issue #11. That is the only route short of external hardware,
and it would also settle whether the ~0.44-bit gap between the two
benches lives in the reference.

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
   stated in volts rather than in ratios of ADVREF to itself.

Each of those is judged the same way afterwards: re-run
`tools/noisetool.py activity`, interleaved, and read the paired
difference in bits.
