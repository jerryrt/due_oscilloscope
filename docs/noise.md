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

A0, driven by DAC0 holding a fixed code, on the macOS bench, Track B.
`records/phase0-noise-fast.jsonl` and `records/noise-activity.jsonl`.
A second bench has since measured 3x quieter; see "A second board, on a
second host" below before treating any figure here as the board's
rather than this bench's.

| | |
|---|---|
| noise | **3.6-4.0 codes rms**, about 2.9-3.2 mV |
| effective resolution | **8.2-8.4 bits of 12** |
| noise-free resolution | **7.2-7.5 bits of 12** |
| against an ideal converter | **12-14x the quantisation floor** |
| repeatability, n=7 in place | 0.50 bits spread on effective bits |

So roughly **four bits of a twelve-bit converter are gone**, and the
bottom 4-5 bits of any single reading are noise. Averaging recovers
them at the usual sqrt(N), which is what makes the ADC still the finest
instrument on this bench.

This agrees with what the scope says about the same pin from the other
side: ~15-20 mV peak recorded in `CLAUDE.md`, against 3 mV rms here,
which is 5-6 sigma. Two instruments, two methods, one pin, consistent -
and that agreement is the reason to believe either.

## A second board, on a second host

Taken 2026-08-27 on `windows-desk`: a different Arduino Due, Windows 11
on AMD64, Track B fw 0.2.0, same frame geometry, same `noisetool.py`.
`records/phase0-noise-fast.jsonl` now holds both benches; the `bench`
field in each row separates them.

**Board and host changed together.** Nothing here says which of the two
the difference belongs to, and the honest reading is "another bench",
not "another board".

| n=7 each | windows-desk | macOS / DSO bench |
|---|---|---|
| noise | **1.05 codes rms** (0.81-1.06) | 3.27 (3.13-4.43) |
| effective resolution | **10.14 bits** (10.12-10.51) | 8.50 (8.06-8.56) |
| noise-free resolution | **9.21 bits** (9.19-9.58) | 7.57 (7.13-7.63) |
| against an ideal converter | **3.6x** the quantisation floor | 11.3x |
| repeatability, in place | 0.38 bits | 0.50 bits |
| held level | 2052.7 codes | 2050.1 |
| lines per run | median 3, up to 7 | 0 in 7 of 7 |

**The ranges do not overlap**, by 1.56 bits at their closest: 3.1x less
noise and 1.64 bits more resolution than the bench this measurement was
designed on. Repeatability is slightly better too, so this is not the
quieter bench merely being sampled at a lucky moment.

Four bits of twelve are gone on that bench. Here it is closer to two.

### What reproduced, and what that is worth

**Host-fed playback costs the same.** Two independent five-round
interleaved sweeps here, against the two already recorded there:

| sweep | playback vs internal |
|---|---|
| windows-desk, first | **-0.184 +- 0.076 bits** |
| windows-desk, second | **-0.256 +- 0.115 bits** |
| macOS, first | -0.292 +- 0.074 bits |
| macOS, second | -0.234 +- 0.078 bits |

Four sweeps, two boards, two hosts, all four inside one standard error
of each other. That is the figure to carry forward: the absolute floor
is a property of a bench and does not travel, but the *cost of feeding
the DAC over USB* does.

It is also the argument for the paired method rather than for the
method. On the bench where the floor is 3x lower the paired difference
came out the same, which is what a real difference does and what an
artefact of the noisier bench's wander would not.

**The rate arm is still not resolved, and this bench nearly fooled me.**
The first sweep here returned `+0.030 +- 0.004 bits` for 200 k -> 453 k -
resolved at seven standard errors, and tempting to report. The second
sweep, same board, same session, returned "not resolved, < 0.285". Two
sweeps of the same arm, one apparently resolved to four decimal places
and one not resolved at all. **The quoted result is unresolved**, and
the reason the doc above asks for two sweeps is that one of them will
occasionally do this.

**Nothing narrowband, again.** This bench does show lines where the
other showed none - median 3 per run, up to 7 - but they fail the
two-rate test: `alias` finds zero lines at 200 ksps and five at 453 k,
with nothing stationary across the two. They appear here and not there
because the broadband floor is 3x lower, so the estimator's tail now
clears it. The conclusion is unchanged and better supported: broadband,
no discrete aggressor, nothing to notch.

### What could not be repeated here

**The free-A1 finding.** "An unused ADC channel reads its neighbour"
needs an unused channel, and this bench has DAC1 wired to A1 - its own
`s` sweep tracks DAC1 to within ~10 mV mid-range, and A1 does not move
when DAC0 swings full scale. A1 here reads 2057.9 codes against A0's
2052.8, which looks like the 4.3-code offset recorded there and is not:
it is a driven pin sitting where its own DAC put it. Coincidence, not
replication, and worth saying because the numbers agree.

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

## What the digital side does cost, measured

**Host-fed playback costs about 0.26 bits.** Feeding the DAC from the
host over USB - the bulk OUT path, its DMA and the playback ring -
against the internal generator holding the same level with no USB in the
DAC path at all.

Two independent five-round sweeps, and both are quoted because one of
them alone would be a single measurement of a difference:

| sweep | playback vs internal | rate 200k -> 453k |
|---|---|---|
| first | **-0.292 +- 0.074 bits** | not resolved, < 0.187 |
| second | **-0.234 +- 0.078 bits** | not resolved, < 0.131 |

Resolved at three to four standard errors in each, agreeing within one
standard error of each other, and the rate arm unresolved in both.

That number needed a change of method, not a better instrument. Run in
blocks - all of one arm, then all of the other - the same difference
read -0.15 bits against a run-to-run spread of 0.50 and was
indistinguishable from nothing. The level of this board's noise wanders
about 40% between runs with nothing changed, and that wander is common
to both arms *within a round*: interleaving the arms and comparing
inside each round cancels it. `noise.paired_delta()`.

This is the same lesson issue #6 records from the other direction: a 42%
throughput gap between the two firmware tracks evaporated when the arms
were interleaved instead of blocked. **On this board, a comparison
between two conditions is measured in rounds or it is not measured.**

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
