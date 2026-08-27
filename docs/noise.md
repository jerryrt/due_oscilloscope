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
**These figures were taken through a firmware disturbance that has since
been fixed, on a bench with a free neighbour on the mux.** A second
bench measures 3x quieter; see "A second board, on a second host" below,
and re-take these before treating any of them as the board's.

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

Taken 2026-08-27 on `windows-desk`: a different Due, Windows 11 on
AMD64, Track B. `records/phase0-noise-fast.jsonl` holds both benches and
the `bench` field separates them.

**The first version of this section reported a 1.64-bit difference and
called it "another bench". That was three variables reported as one, and
most of what follows is the work of taking them apart.** Two are now
removed or measured; about 1.4 bits is left and is not explained.

### The firmware was not the same, and that mattered

Both boards reported `fw 0.2.0`. The `build` strings did not: 11:34:35
there, 07:34:13 here, with `2e74fbb`, `f38523b` and `623d4dc` landing in
between - all three on the DAC and its sync, which is exactly the path
the `gen-dc` arm holds a level on. A version string is not a build, and
this is the second time in this project that `FW_VERSION_STR` has been
the same across two things that were not.

Reflashed here from `main` at `6f17a8e`, and the effect is not on the
level but on the **shape of the distribution**:

| this board, n=7 in place | before reflash | after |
|---|---|---|
| noise | 0.813 **or** 1.061 codes | 0.956 |
| spread | 0.248 codes / 0.38 bits | **0.004 codes / 0.006 bits** |

Before, it sat in one of two states and flipped between runs with
nothing changed. After, seven runs agree to three decimal places. **What
this document previously called "repeatability, n=7 in place: 0.50 bits"
is not repeatability. It is two states.**

And the same signature is in the macOS record: sorted, its seven runs
are 3.128 3.167 3.171 3.274 3.457 | 4.345 4.426 - a gap 2.7x wider than
the widest cluster. That bench's firmware predates `623d4dc`, the commit
whose subject is "clear it of the disturbance", by five minutes.

**Prediction, and the cheapest thing anyone can do next: reflash the
macOS bench from current `main` and re-run `noise-fast --runs 7`. If the
spread collapses the way it did here, every figure in the table above is
measured through a disturbance that has since been fixed.**

### A bare neighbour in the sequence costs 0.347 bits

The other bench has A1 free; this one has DAC1 on A1. That is not a
detail: the ADC converts a pair through one sample-and-hold, so what the
*other* channel is doing lands in this one.

Measured here by switching the capture pair between A0+A1 (driven) and
A0+A2 (bare), interleaved, five rounds, on the reflashed board:

    A1 driven   0.952-0.956 codes    10.272-10.279 bits
    A2 bare     1.210-1.216 codes     9.926-9.932 bits
    paired      -0.347 +- 0.002 bits  (n=5, sd 0.004)

So a bench with a free neighbour reads about a third of a bit worse, and
comparing one to the other without accounting for it is comparing two
different circuits. This also sharpens the finding below: an unused
channel does not merely read its neighbour, it **costs** its neighbour.

### What is left is 1.4 bits and is not explained

| n=7 each, after reflash | windows-desk | macOS / DSO bench |
|---|---|---|
| noise | 0.956 codes rms | 3.27 |
| effective resolution | 10.27 bits | 8.50 |
| spread in place | 0.006 bits | 0.50 (two states) |

1.77 bits apart. The neighbour accounts for 0.35 of that. The firmware
is no longer a difference on this side and may be worth something on the
other. **That leaves about 1.4 bits between two boards of the same
design running the same firmware, which is too much to accept as a board
tolerance and is not currently explained.**

Board and host still change together here, so this cannot say which.
What would settle it, cheapest first: reflash the macOS bench and re-run
(above); move one board to the other host; measure ADVREF's own noise
rather than its level, since it is the reference both converters share
and nothing here has ever looked at it.

Until then the honest reading of the headline table at the top of this
document is **"what one bench measured through a firmware disturbance
with a free neighbour"**, not "what this board does".

### What reproduced anyway

**The playback cost.** Two interleaved five-round sweeps here against
the two there:

| sweep | playback vs internal |
|---|---|
| windows-desk, first | -0.184 +- 0.076 bits |
| windows-desk, second | -0.256 +- 0.115 bits |
| macOS, first | -0.292 +- 0.074 bits |
| macOS, second | -0.234 +- 0.078 bits |

Four sweeps, two boards, two hosts, all inside one standard error. The
absolute floor is a property of a bench and does not travel; this does.
It is also the argument for the paired method rather than for the
instrument: it survived a bench whose floor was 3x lower, two states in
the firmware, and a different neighbour on the mux.

**The rate arm is still unresolved, and this bench nearly sold the
opposite.** The first sweep here returned `+0.030 +- 0.004 bits` for
200 k -> 453 k - resolved at seven standard errors and tempting to
publish. The second, same board and session, returned "not resolved,
< 0.285". Quoted as unresolved. In hindsight the first sweep was
measuring which of the two firmware states each round happened to be in.

**Nothing narrowband.** This bench shows lines where the other showed
none, but `alias` finds zero at 200 ksps and five at 453 k with nothing
stationary across the two. They clear the floor here only because the
floor is lower. Same conclusion, better supported.

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
