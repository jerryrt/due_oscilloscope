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

**The sites sit on a spacing of 21, which is a fact this project
already had and had filed under the wrong heading.**
`tools/acr_issue5.py` records "the phases sit on a lattice of 21 and a
lattice is what a periodic process looks like when the run start is
arbitrary" - written about phases drawn *across* captures. They are not
drawn across captures: 117 and 138 are 21 apart, and 177, 198, 219 are
21 apart, all of them **within one capture**. windows-desk's 156 is 39
from 117, the same offset that separates 138 from 177. Two combs of
period 21, offset by 3 in bin terms, rather than one wandering phase.
Stated as the arithmetic of five sites on one bench and one on another,
which is not enough to call it the mechanism.

**Both tracks show the same sites, offset by ten fold bins - which is
the oracle earning its keep.** Track A and Track B flashed in turn on
one board in one session, `tools/issue5_sites.py -n 12` each:

| Track A | Track B | offset |
|---|---|---|
| 107, -3.4 .. -2.3 | 117, -2.0 .. -1.7 | -10 |
| 188, +2.7 .. +3.1 | 198, +2.0 .. +2.4 | -10 |
| 209, -1.5 .. -1.3 | 219, -1.4 .. -1.1 | -10 |

Same positions, same magnitudes, same signs, from **two independent
register programmings of the same silicon**. Three sites landing on one
constant offset is not a coincidence a 256-bin fold offers cheaply, and
the offset itself is the obvious thing - the two tracks begin capturing
at slightly different points in the generator's table cycle, which
shifts every phase by the same amount and nothing else.

That is the strongest evidence yet for this issue's "a DAC output pin,
not a splice" attribution: firmware is the one thing that differs
between the arms, and it does not move the artifact. Two caveats kept
with it - only 3 of Track B's 5 sites have a Track A counterpart (138
and 177 have none at 128 and 167), and the ten-bin offset is inferred
from those three coincidences rather than measured against the table
directly.

**And windows-desk closed the other half of the same question from the
other direction.** Their board's strong sites are {96, 156, 177}
against this board's {117, 198, 219} - *different positions, same
firmware*. Put the two experiments together:

| held fixed | varied | positions |
|---|---|---|
| board | firmware (Track A vs B) | **same**, to a constant fold offset |
| firmware | board | **different** |

So the site positions are a property of **the board**, not of the
design and not of the code. That is as close to "analog, and specific
to this piece of silicon" as this issue can get without an instrument
inside the DAC, and neither bench could have established it alone.

What *does* travel between boards is the co-movement: their 96 and 117
correlate at r = +0.90 and both anti-correlate with 156, the same rigid
coupling this bench measured at |r| = 0.97-0.99. **The structure is the
design's; the positions are the board's** - **and the second half of
that sentence was retracted the next day. Read the next section before
quoting this one.**

### What the lattice of 21 is not, and the four ways it was asked

The wrap displacement sits on a comb of period 21, and the useful work
of one session was excluding things rather than finding the mechanism.
Every arm below varies **one** thing, and each was needed - a spacing
could have followed the table while ignoring the fold.

| varied | result |
|---|---|
| **fold** length, 256 against 512 | 21 does not follow it, so not an aliasing artifact |
| **table** length, ramp period 256/512/1024 | 21 does not follow it, so not the table |
| **wall-clock rate**, halved with the sampling geometry held | 21 does not follow it, so **not a frequency** - no supply, clock, or anything with a period in seconds |
| **ADC channels**, 2 against 1 | the comb is there at one channel, 20 gaps of exactly 21, so the multiplexer need not move |
| **position within one capture** | step 0 in 30 of 30 transitions, 44 of 46 sites matching, so **not a marching event** |
| **the other DAC channel**, A1 read at a 2.6x margin | ~~no comb, so the period counts DAC0 writes~~ - **withdrawn, see below** |
| **the DAC:ADC ratio**, 1 / 2 / 3 / 4 with the ADC held fixed | the gap is 21 / 21 / **7** / 5 bins, so it is **not a fixed number of DAC0 updates** - see below |

Two of those need their own note, because they were each published
wrong first.

#### The ratio arm, and the unit it settles

The ratio axis was a labelled hole: above ratio 1 the converter samples
one held level several times, the repeats disagree as a function of the
held voltage, and that buries the artifact. Both differencing pairings
were spent.

**The way through is not to difference at all.** Differencing is
`pair_fold`'s trick and exists to keep a profile flat; the host-fed
reader takes a neighbour residual and never needed it. Decimate to one
sample per DAC update - the same position in every hold - and the series
is back in its ratio-1 shape, with whatever the repeats disagree about
never read at all. `tools/issue24_hold.py`.

Ratio 3 is settable exactly, which is what makes the arm work: rates
come from RC, and RC 585 is three times the ADC's RC 195, so the hold is
exactly three samples. "66,667 Hz is not an integer divider" is the
wrong way to ask.

| ratio | gap | = DAC updates | = ADC samples |
|---|---|---|---|
| 1 | 21 bins | 21 | 21 |
| 2 | 21 | 21 | 42 |
| **3** | **7** | **7** | **21** |
| 4 | 5 | 5 | 20 |

The DAC-update column reads 21, 21, 7, 5, so the comb is **not** a fixed
count of DAC0 updates. Ratio 3 decides it - seven bins is seven DAC
updates against twenty-one conversions, and 21/3 = 7 exactly, gap 7
appearing 48 times against 14 six times. The ADC column is ~21 three
times over: ratio 2 reads 42 because 21/2 = 10.5 cannot be a bin
spacing, and ratio 4 reads 20 because 21/4 = 5.25 gives gaps of 5 with
6s making up the difference.

**Ratio 4 loses the comb entirely, and that survives its power control** -
5.5x the averaging (n/bin 195 to 1075) and still no 21, with sites
recurring as near-equal pairs five bins apart.

**A control of mine that did not survive, recorded because it was
published twice.** I read the two hold offsets as agreeing on site
positions and called it evidence the artifact is locked to the DAC
update. Checked against the records rather than the console line, they
share 3-6 sites of 8 in one session and **0 of 8 in each of two others**.
The inference is withdrawn. Disagreement is what a per-conversion comb
predicts - `gcd(2,21) = 1`, so each offset solves `2d + o = c (mod 21)`
for a different residue - so the dominant behaviour supports the
conversion reading, and the session that agreed is the unexplained one.

**Not settled against the gen-versus-host cut above**, which has a
two-path independence this lacks. The honest statement is that the
ADC-conversion reading fits every arm and the DAC-update reading fits
only the arms where the ratio hides the difference.

**"21 DAC0 writes rather than conversions" cannot be inferred from the
two arms disagreeing about what a bin is.** 21 is odd, so a period of 21
*conversions* puts events at DAC0-level indices 0, 10.5, 21, 31.5, and
the half-integers are DAC1 conversions an A0 fold cannot see. What
survives is 0, 21, 42 - a comb of 21, exactly what the other hypothesis
predicts. A1 is what separates them.

**Both channels carry the comb, and the claim that only DAC0 does was
withdrawn twice over.** The first reading had A1 blind - see the floor
below. The second had A1's floor fixed and still concluded "no comb on
A1", from three captures in which A0 drew one and A1 did not. That is a
statement about A1's draw, not about what A1 can carry: **A1 has its own
gate.** Over 46 sync-off captures A0 draws a comb in 8 and A1 in **16** -
A1 more often - and the two co-occur twice against 2.8 expected under
independence. So each channel carries a comb of 21 in its own updates,
drawn independently of the other, and the period is not DAC0-specific.

The transferable form: **on a gated defect, an absence is evidence only
when the number of captures is large against the gate's own rate.** A
noise floor is not the only way for an instrument to be blind, and
`tools/issue5_a1.py` now reports draws per channel over every capture
rather than reading the ones where the other channel happened to fire.

**And A1 could not see it for two rounds.** A1 reads a full-scale square
where A0 reads a sine, so its MAD runs ~1.8x higher and its detection
floor sat *above* the ~1 code comb. Its silence meant nothing. The
margin was bought by making A1 flat - `--sync off` puts DC on DAC1 and
A1's standard deviation falls from 1372.5 codes to 1.0 - not by
averaging longer. `tools/issue5_a1.py` prints both floors beside the
comb's amplitude and refuses the conclusion below 2:1, because at 12 s
captures the floor was 0.98 against a 1.04 code comb and "detectable by
6%" is the same mistake one step further along.

### The second lattice is a count. The time reading is dead.

**Settled since the section below was written, by two benches moving the
ADC rate in opposite directions:**

| bench | arm | time-locked predicts | measured |
|---|---|---|---|
| windows-desk | ADC 100,000 / DAC 100,000 | 10.50 | **21.000**, MAD 0.102, n/bin 2151 |
| macOS | ADC 397,959 / DAC 397,959 | 41.79 | **21**, 130 of them, zero 41/42 |

One went down in ADC rate and one went up; both land on 21 where a
fixed period predicts something else. So the lattice is a **count**, and
105 microseconds - proposed here and withdrawn the same night - is
buried by measurement rather than by its author's doubt.

What remains is the two-lattice picture with both members counts: 21 DAC
updates and 21 ADC conversions, each drawn in its own captures. The
ledger of refutations, ranked by whether they replicated:

| reading | refuted by | replicated |
|---|---|---|
| time-locked | macOS RC 98 h1, windows ADC 100k h1 | yes, both directions |
| update-locked | RC 195 h3 | yes - macOS 258 sevens of 375 with one 21, linux-x1 87 of 139 with zero |
| conversion-locked | RC 292 h2 only | **no** - macOS mode 7.000 against linux-x1's 14.08 at identical rates |

**Rank arms by whether they replicate, not by whether they are yours.**
Every wrong turn on this issue has been a single arm read as settled,
and the one still unreplicated is the one refuting conversion-locked.

One reading trap that survives all of it. A DECIMATING reader cannot
show a fractional spacing: 10.5 cannot be a bin gap, so alternate sites
land on the discarded phase and the survivors sit 21 apart, which looks
like the update lattice and is not. A non-decimating reader shows the
same captures as alternating 10s and 11s. Both are correct about what
they measured; only the second can see the distinction.

### The second lattice: a time or a count, and still undecided

**The section that follows claimed 105 microseconds and is WITHDRAWN.**
It is kept because the reasoning is right up to the point where it
fails, and because the arm that refutes it is worth as much as the arm
that suggested it. Read the retraction at the end of the section before
quoting any of it.

#### The original claim, which does not hold

Every arm on this issue was taken at **ADC RC 195** - 200,000
conversions a second, where 21 conversions is exactly 105 us. The count
and the time were never separable, so "21 ADC conversions" and "105 us"
fitted every measurement equally and nobody had reason to prefer one.

RC 292 at hold 2 separates them: it puts the DAC at 66,780 Hz against RC
195 at hold 3's 66,666 - the same DAC rate to 0.17 per cent - with the
ADC at 133,561 instead of 200,000.

| arm | gap (updates) | in conversions | in time |
|---|---|---|---|
| RC195 hold 1 | 21 | 21 | **105.00 us** |
| RC195 hold 2 | 10.5 | 21 | **105.00 us** |
| RC195 hold 3 | 7 | 21 | **105.00 us** |
| **RC292 hold 2** | **7** | **14** | **104.82 us** |

The conversion count is not invariant. The time is, to 0.2 per cent.

Both benches' existing data already said so in a unit nobody had
converted. windows-desk's ratio-3 gap of 7 at DAC 66,666 is 105.00 us,
and their ratio-4 census - gaps of 5 dominant with 6s making up the
difference, mean 5.25 at DAC 50,000 - is 105.00 us exactly. The 5-and-6
alternation IS a non-integer gap of 5.25. Six arms, two benches, two
boards, one number.

**So the two lattices are:**

- **update-locked** - 21 DAC updates, invariant to rate, which is 105 us
  at 200 kHz and 315 us at 66 kHz. Device-side: present with no host in
  the DAC path.
- **time-locked** - about 105 us, invariant to both rates. Seen only on
  the host-fed path, 0 in 432 internal captures.

They coincide at 200 kHz, which is the rate this issue was born at and
the reason one number described both for so long.

Offered as somewhere to look and NOT as a finding: 8192 MCK cycles at 78
MHz is 105.026 us. A 13-bit counter at MCK would fit and there is no
independent evidence of one. What matters is that 105 us is a number
worth searching the datasheet and the USB stack for, which "21" never
was - and since the lattice is host-fed-path-only, the USB side is where
to start.

#### Why it fails, and what is actually left

RC 98 at hold 1 puts the DAC at 397,959 Hz. There the three candidate
readings separate cleanly: 21 DAC updates predicts a gap of 21, 21 ADC
conversions also predicts 21 (one update IS one conversion at hold 1),
and 105 us predicts 41.8, so 41 or 42.

**Thirty-eight captures. Gaps of 41 or 42: zero. Gap 21: 130.**

At the per-capture draw rate of about 0.2 that is a probability of
0.0002, so it is not a missed draw. And the arm is healthy - underruns
0, occmin 24, the same as RC 195 - so it is not a starved feed either.

So the position is:

- Every arm at **RC 195** fits "21 ADC conversions" and "105 us"
  equally, because at a fixed ADC rate they are the same prediction.
  Nothing taken there can decide it, and nearly everything was taken
  there.
- **RC 292 at hold 2** gave 7 updates, which fits 105 us (7.0) and not
  21 conversions (10.5). But its DOMINANT gap was 64, at 47 occurrences
  against the 7's 42, and 64 is 512/8 - a plausible artifact of the fold
  length rather than a feature of the signal. That arm is not clean.
- **RC 98 at hold 1** refutes 105 us outright.

**So the unit is undecided, and "21 ADC conversions" is the reading with
more support.** What is established is narrower and worth stating on its
own: at a fixed ADC rate, the gap in DAC updates is 21 divided by the
hold, over holds 1 to 4 and on two benches.

The lesson is the one this issue keeps teaching in new clothes. Four
arms agreeing did not mean four independent confirmations - they shared
a fixed ADC rate, which made them one arm repeated. The RC 292 result
looked like the fifth, independent one and turned out to rest on a
minority feature of a census whose majority is probably a fold artifact.
**Count the assumptions the arms share before counting the arms.**

### Only one of the two lattices is device-side

The section below establishes two lattices drawn per capture. They do
not have the same provenance, and this issue's device-side argument
reaches only one of them.

Classified per capture across every committed record, both benches, no
new bench time:

| record set | captures | conversion-locked | update-locked | weak |
|---|---|---|---|---|
| internal (`issue5-*`, hold 2) | 432 | **0** | 90 | 342 |
| host, macOS (`issue24-*`) | 172 | **38** | 35 | 94 |
| host, windows-desk | 106 | **31** | 39 | 32 |

Both benches' host records draw both; neither bench's internal records
draw the conversion-locked one at all. So the **update-locked** lattice
is device-side - present with no host in the DAC path, which is the
argument #24 rests on - and the **conversion-locked** lattice has only
ever been seen when the host feeds the DAC, on two boards and two hosts.

The standing device-side conclusion therefore holds for one lattice and
never reached the other. Nobody had separated them to notice.

**`tools/issue24_draws.py` needed three fixes before it could say this,
and every one of them had manufactured a null.** They are worth knowing
because the same three shapes are available to any tool that reads these
records:

- It read one of the several site formats the record files use and
  **silently skipped the rest**, dropping exactly the host-path rows
  that carry the conversion-locked draws. Unreadable rows are now
  reported by file and count, and are explicitly not scored as
  absences.
- It scored every capture against **hold 2's** conversion signature, so
  every hold-3 capture drawing 7s - which is 21/3 - was classified
  "weak". The rule is derived from each row's own hold now.
- The internal-path files carry **no hold field**, so they defaulted to
  hold 1, where the two lattices coincide by construction and the
  conversion count is zero whatever the data says. That default made
  the result true by arithmetic. The internal path is a hold of 2,
  because gen NORMAL alternates DAC0/DAC1 while A0 converts every
  trigger.

The finding survives all three. It did not survive the first version,
which reported zero conversion-locked captures on the host path as well.

### There are two lattices, and they are drawn per capture

The section below this one records the unit as unsettled, with three
constraints that did not fit one model. They fit two.

Sixty captures on the host-fed path, twenty at each of holds 1, 2 and 3,
classified by **which lattice each capture drew** rather than by a
pooled census. Pooling averages over draws, and that is precisely what
produced contradictory answers from one configuration:

| hold | conversion-locked | update-locked | weak | none |
|---|---|---|---|---|
| 1 | *(coincide)* | 6 | 12 | 2 |
| **2** | **5** (gaps 10/11) | **4** (gaps 21) | 11 | 0 |
| 3 | **17** (gaps 7) | **0** | 2 | 1 |

At hold 2 individual captures draw **either** lattice and **none draws
both**. So there are two, drawn per capture and mutually exclusively:
one locked to DAC updates, which gives 21 at every hold, and one locked
to ADC conversions, which gives 21 divided by the hold.

**At hold 1 the two coincide by construction** - one DAC update is one
ADC conversion - which is why nothing separated them until the ratio
axis opened, and why every arm before that was blind to the distinction.

That reconciles the constraints below without anyone having measured
wrongly. The hold-2 tens and elevens were real and so were the
twenty-ones that appeared in their place on more captures; the internal
path's 21 over 243 channel-captures is real; the ratio-3 sevens are real
and are the conversion-locked lattice read at the hold where the two
units finally differ by three.

**The methodological form, which cost four retractions to arrive at.**
On a defect whose configuration is redrawn at every stream start, a
census pooled over a handful of captures is not a measurement of what is
present - it is a sample of what was drawn. Classify per capture and
report the distribution. "21 DAC0 updates" was published and withdrawn
twice, and "21 ADC conversions" once, all from pooled counts over four
to twelve captures.

Two things unexplained and not smoothed over. The update-locked lattice
is **absent at hold 3** - 0 of 20, against 4 of 20 at hold 2 - and
nothing here accounts for that. And "weak" is the largest class at holds
1 and 2, 12 and 11 of 20, so most captures draw neither lattice clearly
and the classifier reports a minority in each; only hold 3 has a lattice
dominating its own arm.

Two further arms, both negative, are worth keeping so they are not
re-run. The **TAG interleave is not what separates the host and internal
paths**: `measure.build_ramp_tagged` puts gen NORMAL's DAC0/DAC1
alternation on the host path with transport, instrument, fold and rates
all held, and six paired runs are indistinguishable from plain. And the
readers are not equivalent on the internal path - `pair_fold` with
`fold_sites` reads MAD 0.12 and sites 138/198/219 where an averaged hold
with `masked_sites` reads MAD 0.43 and 175/198/209, so the averaging
reader is the worse instrument there and its numbers should not be
compared with the differencing one's.

### The unit the comb counts, and the three constraints on it

Open, and worth stating precisely because it has been answered three
different ways.

The question is whether the lattice counts **DAC updates** or **ADC
conversions**. Most arms cannot tell: at ratio 1 they are the same
number, and at any *odd* period a comb of 21 conversions and a comb of
21 updates both come out of a DAC-indexed fold as a comb of 21.

Three measurements bear on it and they do not currently fit one model.

1. **Ratio 3, host path, decimating reader** (windows-desk). RC 585 is
   exactly three times the ADC's RC 195, so the hold is exactly three
   with no rounding. The gap is 7 bins = 7 DAC updates = **21 ADC
   conversions**. One path, one variable, and the ratio where the two
   units finally disagree by more than a factor the other arms could
   separate.
2. **Ratio 2, internal path, non-decimating reader.** `gen` NORMAL
   alternates DAC0 and DAC1 while A0 converts every trigger, so the
   internal path IS a hold of two - it has never been independent of the
   host path here, only differently read. Over 243 channel-captures on
   both benches the gap census is **21 x358, 11 x5, 10 x1**. Under 21
   ADC conversions, a reader that discards nothing should show
   alternating gaps of 10 and 11, because 21 conversions is 10.5 levels.
   It does not.
3. **Offset agreement at ratio 2** (windows-desk). The artifact appears
   at whichever sample of the hold is read, values matching to a tenth
   of a code.

(1) and (2) reconcile if the artifact only manifests at a fixed position
within the hold, since then half its firings are invisible at hold 2 and
the survivors sit 21 levels apart. (3) says the opposite - both
positions carry it.

The arm that would settle it is **ratio 3 with a non-decimating reader**:
21 conversions puts sites at levels 0, 7, 14, 21 and 21 updates puts
them at 0, 21, and at ratio 3 a reader that discards no phase separates
those cleanly.

Until then, quote the unit as unsettled. "21 DAC0 updates" was published
here twice and withdrawn twice, once for the odd-period degeneracy and
once for reading a comparison channel that has a gate of its own.

### The draw happens at every stream start

The comb is on in some captures and absent in others, and this was read
for a long time as a configuration drawn rarely and drifting on
tens-of-minutes scales. Both readings put on and off captures in one
session; they differ in **order**.

Twenty consecutive captures, classified by structure rather than by
count - three or more gaps of exactly 21 is the comb, one large site is
not:

    .XX......X.X........
    n=20  on=4  off=16  runs=7
    expected if independent 7.40 (sd 1.35)  ->  z = -0.30

No clustering. With the segment measurement above - a comb-on capture
has it on in every segment and a comb-off capture in none - the
configuration is **drawn at stream start, independently each time**, at
p(on) about 0.2.

Read that with its power: n=20 with 4 on gives an sd of 1.35, so it
detects heavy clustering and little else, and a z near zero is a failure
to detect clustering rather than a demonstration of independence.

**It re-reads three of this issue's null results.** The table rebuild,
the NRSTB reset and the amplitude excursion were each tested as
something that might redraw an otherwise-stable configuration, and each
returned nothing. If the configuration is redrawn at every stream start
regardless, none of those experiments could have shown anything whatever
the candidate did - one explanation for three nulls rather than three
independent exclusions. The exclusions are not wrong; the inference that
the draw is rare does not follow from them.

It also sizes the power-cycle test, which is the last candidate
standing: a power cycle has to beat a per-stream draw to be visible, so
the protocol wants at least a dozen captures per arm compared by the
*rate* p(on), not one site set per arm.

### A channel held at DC still carries displaced samples

With `--sync off` DAC1 is a constant code, and A1 is then the flat
channel `flat_census`'s docstring has always assumed - it is not one in
preset M by default, where the sync is a full-scale square.

Flat, and with DAC0 driven, A1 still shows persistent displaced samples
of about 8 codes at fixed positions. On a channel whose output never
moves.

That refines "a changing output is needed" rather than contradicting it:
that was measured on `all-DC`, where **neither** channel moves. What is
needed is a changing output *somewhere*, not on the channel that shows
the artifact.

**And the size tracks what the ADC is doing.** Interleaved 2 against 3
channels, ten captures each, on the folded profile's total absolute
deviation: A0 rises 1.43x when a third channel is added, with nothing
about A0's own neighbourhood changed - its predecessor is A1 in both.
A1 rises 1.27x. That arm was built to test ADC multiplexer crosstalk and
is confounded for that purpose, because a third channel is also 50% more
conversions per second; what it does establish is that the magnitude
depends on total ADC activity. This issue attributes the artifact to a
DAC output on the strength of it being present with no host in the DAC
path - which excludes the host, not the converter reading the pin.

### The offset was measured, and it is not the fold's rotation

Every position above is a **bin number in a frame whose zero is where
the capture happened to start**, and the table two paragraphs up leans
on that frame in both rows. The caveat kept with it - "the ten-bin
offset is inferred from those three coincidences rather than measured
against the table directly" - has now been cashed, and it did not pay
what was expected.

`tools/issue5_absphase.py` measures the rotation instead of assuming
it. The reference costs no wiring: `shape_code` builds the sine as
`2048 + sin(2*pi*i/period)`, so table index 0 is the rising mid-scale
crossing, and folding the *level* series - the mean of each held DAC
pair, the same pairing `pair_fold` differences within - recovers it.

**Two estimators, and `align_ok` requires them to agree.** The crossing
estimate reads two bins and this waveform gives it a reason to be
wrong: the DAC is not rail-to-rail, the sine's trough is asked for at
code 23, and a compressed trough raises `(max+min)/2` and drags the
crossing with it. Track B's first series had its trough attestation 5
bins out. `phase0` is now the argument of the k=1 DFT bin, over all
256, with the crossing kept as the cross-check.

One board, both images, rotation and sites measured together:

| image | `phase0` | sites (table coordinates) |
|---|---|---|
| Track A | **13** | 94, 175, 196 |
| Track B | **12** | 105, 126, 165, 186, 207 |

**The rotations are one bin apart. The sites are eleven apart.** A's 175
is B's 186, A's 196 is B's 207, A's 94 is B's 105. Parity differs
between the tracks and cannot account for it - `pair_fold`'s level and
difference series index from the same offset, so the frame cancels in
`bin - phase0`.

So "the two tracks begin capturing at slightly different points in the
generator's table cycle, which shifts every phase by the same amount
and nothing else" is **measured and wrong**. The capture start differs
by one bin; the eleven is real displacement.

That refutes the **first** row of the table above, not the second.
Firmware *does* move the site positions, so the board-held arm is not a
control any more, and "the positions are the board's" has lost the
experiment it rested on rather than been contradicted by a new one. The
cross-board observation stands as an observation.

Twice now on this issue, three sites landing on one constant offset has
been read as agreement. It is a displacement of eleven that happens to
be constant.

**What survives is the structure.** In table coordinates Track A sits on
residues {7, 10} mod 21 and Track B on {18, 0} - the same two combs of
period 21 offset by 3, moved bodily by 11 - and both benches' published
sets sit on two such combs as well. Nothing has dented that.

A site can now also be quoted as the code the converter was asked for,
via `measure.gen_sine_code()`: Track B's 126 -> 2149, 186 -> 23,
207 -> 139. **That excludes the obvious analog hypothesis.** Two sites
sit within 140 codes of the bottom of a converter that is not
rail-to-rail, which invites a nonlinearity argument - but DNL is a
function of *code*, and the sites hold their table *index* across a 4x
amplitude change while the code at a fixed index moves with it. A
fixed-code converter nonlinearity cannot be it. Whatever this is, it is
indexed by position in the update sequence, not by output voltage.

**The strong sites are rigidly coupled, and the earlier "two
independent populations" reading here was wrong.** Twelve Track B
captures in one session, with site 138 swinging -5.11 to +2.14 across
them:

    138 vs 198   r = -0.99
    138 vs 219   r = +0.99
    198 vs 219   r = -0.97

One mechanism moves all of them, redistributing between sites rather
than switching them on and off. The earlier reading came from a stretch
where the configuration happened to be static, so there was no variance
to correlate and the near-zero coefficients meant "nothing moved", not
"nothing is linked". **Correlate only across a stretch where the thing
actually varies** - the same trap as bounding a drifting probability,
one section down.

**Two populations by amplitude, and the fork "do the sites move
together or independently" has an answer for each.** 24 captures inside
one board session, 8 of them preceded by a `set_gen` table rebuild:

- The **strong sites do not move**. 198 read +12.24 to +12.76 and 138
  read -1.17 to -1.85 in all 24, rebuild or not.
- A **weak comb switches on as a unit**. {50, 71, 92, 113} appear
  together at about +1.0 each in 6 captures of 24 and are absent in the
  rest, and the profile's total absolute deviation - a threshold-free
  number that does not care which sites cleared z - is bimodal with
  them: ~38-44 when the comb is off, ~60-64 when it is on. The strong
  sites are untouched either way.

So sites move together *within* a population and the populations are
independent of each other. That is one mechanism gating the weak comb,
not many separate events, and something else entirely holding 198.

**The configuration is drawn per capture, and the odds drift.** This
looked like stability for a while - the 198-dominant set held across 56
consecutive captures - and "stable" is the wrong word for it. Earlier
the same day the two sets alternated roughly evenly within twelve
captures; later a single capture in the middle of a suite run drew the
138-dominant set while the five captures around it drew 198. So it is
one draw per capture whose probability moves on a scale of tens of
minutes, not a state that is entered and held. Designing an experiment
against "it is stable now" is how a drifting probability gets read as
an effect.

Three things that are **not** the draw event, all tested rather than
assumed. A table rebuild is not - the eight rebuild captures above are
indistinguishable from the sixteen without, **and windows-desk
reproduced that on their board**, 24 captures with runs 9-16 rebuilt
and the three strong sites holding position and value through all of
them. Nor is the NRSTB reset that opening the control port performs.
Nor is an amplitude excursion. A power cycle is the one candidate never
tried on either bench, so "a fresh draw across reboots" is narrowed
three times over rather than refuted.

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

**Each site answers the amplitude question differently, which is the
strongest evidence they are not one phenomenon.** Moving only the
internal generator's amplitude and reading per site rather than by
argmax:

| site | 256/256 | 128/256 | 64/256 | behaviour |
|---|---|---|---|---|
| 198 | +12.2 .. +12.7 | - | +1.7 .. +1.9 | scales **with** the signal |
| 138 | -1.3 .. -1.8 | - | -1.1 .. -1.6 | **independent** of it |
| 177 | 14.1 .. 14.5 | 28.07, 28.11 | 35.4, 36.2 | grows as the signal **shrinks** |

`hold_ok` is true throughout, so the pairing is cancelling the
staircase at every amplitude and the readings stand.

Three sites, three dependencies: one proportional, one flat, one
inverse. **This paragraph previously said "the displacement is not
proportional to the signal - it grows as the signal shrinks", which was
site 177 measured by argmax and stated as a property of the artifact.**
It is a property of one site. On the host-fed ramp the same question
reads additive - changing `RAMP_STEP` moves the per-sample step by 2x
while `n * slope * step` stays at ~28-30 codes - and that too is one
number over an unknown mixture of sites.

**The draw event is still not found, and an amplitude excursion is not
it.** Eighteen captures in one session, six at full amplitude, four at
quarter, eight at full again: site 198 reads +12.24 to +12.71 before
and +12.37 to +12.68 after, and 138 is unchanged across all of it. That
retires the lead recorded here that "having run at reduced generator
amplitude" coincided with the strong-site set changing - it does not.
Together with the table rebuild and the NRSTB reset, three candidates
are now excluded and none proposed.

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

## The playback rate ladder does not deliver every rate it accepts

Measured on `mac-bench` (macOS 12.6, Track B), 8 runs per rate, 3 s
each, drained. Every figure here is the **device's own**
`consumed x PLAY_BUF_SAMPLES / run_us` against nominal, so no host
clock is in it.

| RC | nominal sps | slow runs | device ratio | nearest simple fraction |
|---|---|---|---|---|
| 28 | 1,392,857 | 0 / 7 | 1.0000 | — |
| 32 | 1,218,750 | **1 / 8** | **0.937504** | 15/16 = 0.937500 |
| 39 | 1,000,000 | 8 / 8 | 0.976518 | *(see below)* |
| 44 | 886,363 | 8 / 8 | 0.984288 | *(see below)* |
| 56 | 696,428 | 0 / 8 | 1.0000 | — |

Three things follow, and the third is the one to design against.

**RC 39 and 44 run slow on every run.** This is the effect
`tests/test_integrity.py` already carries as `OVERSUPPLIED = {44, 39}`,
"feeding a converter that runs slow", and which `docs/windows.md`
reproduces on Windows. It is the device's, it is persistent, and the
host's "lost" bytes at those rates are surplus it wrote for a converter
that could not take them - **oversupply, not loss**. RC 44's 1.57% here
matches the 1.6% already on record.

**RC 32 has an intermittent version of the same thing**, and that is new.
One run in eight, and 8 of 52 across every arm taken this session, the
converter runs at 0.937504 of nominal - 15/16 to four decimal places,
over a `run_us` window identical to the fast runs, **with zero
underruns**. The zero is what places it in the converter rather than the
host: had the host merely discarded 6%, a ring clocked at the programmed
rate would drain by ~76,000 samples/s - 445 buffers over 3 s against a
32-slot ring - and starve loudly. It does not. The ring is being emptied
more slowly, and only the timer does that.

It is **not** the neighbouring RC. RC 34 is 5.882% slow and this is
6.250%, so "the timer got programmed one step out" does not fit.

**The ladder is not monotonic, which rules out a ceiling.** 28 and 56
deliver in full, 39 and 44 never do, and 32 usually does. A maximum
update rate would make the fast rates suffer and the slow ones safe;
this is the opposite at both ends. Whatever selects the affected rates is
not "too fast for the DACC", and sizing a design against the nominal rate
at RC 39 or 44 will be 1.6-2.3% wrong every time.

**The affected rates are a contiguous band with soft edges.** Ten rates,
8 reps each, underrun-free runs only:

| RC | nominal sps | slow runs | ratio |
|---|---|---|---|
| 28 | 1,392,857 | 0/7 | full rate |
| 30 | 1,300,000 | 0/7 | full rate |
| **32** | 1,218,750 | **1/8** | 0.93750 |
| 34 | 1,147,059 | **8/8** | 0.98431 |
| 36 | 1,083,333 | **8/8** | 0.98428 |
| 39 | 1,000,000 | **8/8** | 0.97653 |
| 44 | 886,364 | **8/8** | 0.98428 |
| **48** | 812,500 | **1/8** | 0.96858 |
| 52 | 750,000 | 0/8 | full rate |
| 56 | 696,429 | 0/8 | full rate |

So the band is **RC 32 to 48** - about 812,500 to 1,218,750 sps - and it
is clean on both sides of that, at 28/30 above and 52/56 below. The
*edges* of the band, RC 32 and RC 48, are the intermittent ones; the
middle is persistent on every run. That is the shape of a window a
process falls into rather than a threshold it crosses, and any mechanism
proposed for this has to produce both the band and its soft edges.

It also means the affected range is most of the useful high-rate span,
which is worth knowing before sizing anything against a nominal rate
between 812 k and 1.22 M sps.

**Only RC 32's fraction is a reading; the others are not.** The table
above used to name 125/128 for RC 39 and 63/64 for RC 44. Those came out
of `Fraction.limit_denominator(64)` applied to a *measured* ratio, which
fits noise as readily as signal - windows-desk showed that raising the
limit to 128 gives 83/85 and 125/127 for the same numbers. A fraction
that changes when you change the search is not a fact about the device.
**Read the ratio.** RC 32's 15/16 is different in kind: its seven events
have a standard deviation of 0.000049 and every one sits within 1e-4 of
the fraction.

**Reproduced on a second host at every rate.** windows-desk, 9 reps per
rate, Track B, device-side only: RC 28 0/9, RC 32 3/9 slow at 0.93742,
RC 39 9/9 at 0.97647, RC 44 9/9 at 0.98426, RC 56 0/9. Same two
always-slow rates, same intermittent one, same two clean ones, same
values. Every row has `host_deficit` 0, because Windows applies
backpressure rather than discarding - which is why it is the better
bench for this and why one host was not enough.

**The mechanism is `DACC_MR_REFRESH`, and it explains the whole table.**
One field in `play_start()`, changed from `REFRESH(1)` to `REFRESH(2)`,
ABBA on one board in one session:

| RC | `REFRESH(1)` | `REFRESH(2)` | p |
|---|---|---|---|
| 28 | full rate | full rate | — |
| 32 | 7/32 slow at 15/16 | **0/32** | 0.0054 |
| 39 | **8/8** slow at 0.97653 | **0/8** | 0.000078 |
| 44 | **8/8** slow at 0.98428 | **0/8** | 0.000078 |
| 56 | full rate | full rate | — |

Combined 3.3e-11. The seven RC 32 events have sd 0.000049 and every one
sits within 0.0001 of 15/16 - a constant hit repeatedly, not a
distribution.

So `OVERSUPPLIED = {44, 39}` in `tests/test_integrity.py`, and its
comment "feeding a converter that runs slow", have an explanation: the
converter is spending conversion slots on refresh cycles. It has been
in the suite as a documented xfail since before this was measured.

**The control is what makes it readable.** "The mode vanished under
REFRESH(2)" would have been worth nothing on a bench that had changed
track, firmware and the #41 reorder the same morning. Putting REFRESH(1)
back and watching all three rows return is the experiment.

**The analog cost is 0.18 mV, and it did not need a scope.** A0 is
jumpered to DAC0, so the converter under test is already wired to an
instrument, and the refresh rate is exactly known - which makes it a
Goertzel. Measured on a DC held at 5,000 sps, slow on purpose so refresh
fires between updates:

| image | refresh line | magnitude |
|---|---|---|
| `REFRESH(1)` | MCK/2048 = 38,086 Hz | 0.207-0.217 codes |
| `REFRESH(2)` | MCK/4096 = 19,043 Hz | 0.146 codes |

**The line halves when REFRESH doubles**, which is what identifies it as
the refresh rather than a bin someone chose. The whole ripple is 0.22
codes = **0.18 mV** at ADVREF 3270; doubling the period at most doubles
the droop, so the worst case is ~0.4 codes against 0.97-1.76 codes of
held-level noise.

**And during playback refresh protects nothing.** At every rate on the
ladder the sample stream rewrites the DAC 18 to 37 times more often than
the refresh cycle does, so while streaming its entire effect is the
conversion slots it costs. Refresh earns its keep only when the DAC is
left holding - which `play_stop()` deliberately allows, leaving DACC_MR
and the channels enabled.

That sizes the objection; it does not decide the constant, which is
still a firmware choice with a real function behind it.

**Two measurement traps, both of which nearly became findings.**
`stream_start()` passes `with_gen = true`, so capture presets 1-5 run the
internal generator into DAC0 and are not an idle DAC - a first attempt
reported a held DC of sd **1372 codes**, the figure this document
already gives for a full-scale square. And "the first channel with
enough samples" is ADC channel 6 = **A1**, carrying DAC1's sync at sd
555; **A0 is channel 7**.

**A pre-registered prediction failed here and the failure is on the
record.** The reasoning that found the register was that
`2048 x REFRESH / MCK` is an integer number of conversion periods at RC
32 - exactly 32.000 - so refresh would recur at a fixed phase and cost
a fixed number of slots per cycle. That predicted REFRESH(2) would move
the mode rather than remove it.

(The period is **2048** x REFRESH, not the 1024 first published here.
The measured refresh line settles it: 38,086 Hz = MCK/2048 at
REFRESH(1), halving to 19,043 Hz at REFRESH(2). RC 32 remains the only
rate on the ladder where the ratio is a whole number, so the coincidence
that found the register survives the correction - at twice the count,
which would make the measured 1/16 loss two slots per refresh rather
than one.) It removes it entirely, at every rate, including two where the
ratio was never an integer. So the integer-ratio story is **not** the
mechanism; it pointed at the right register for the wrong reason, and
"why RC 32 is intermittent where 39 and 44 are persistent" is again
unexplained.

**What is not established.** Why those rates, and what produces a ratio
that keeps landing on a binary fraction. `DACC_MR_REFRESH(1)` in
`play_start()` is a candidate worth checking - the refresh cycle
re-writes the output periodically and can take a conversion slot - but
nothing here tests it, and the three fractions are quoted as
*consistent with* rather than *equal to*: RC 39 and 44 sit 1.7 sd from
theirs, which several other fractions would also satisfy. Only RC 32's
15/16 is exact enough (0.2 sd) to be more than a coincidence of digits.

**One defect, two expressions - confirmed on two hosts.** `windows-desk`
ran the RC 32 arm and found 3 of 12 runs at 0.93738-0.93751 with
**0 bytes lost in every run**, slow ones included. Same fraction, second
operating system, so the slow converter is the device's and not
macOS-conditioned.

Their zero column is what separates the device behaviour from the host
accounting, which neither bench could do alone:

| host | what a 15/16 converter looks like |
|---|---|
| macOS | buffers ahead, sheds the surplus: a **6% byte loss** |
| Windows | applies backpressure, feeds less: a **93.6% short feed** |

Those are the same number. `test_awg_ladder_play_only`'s 95% assertion
fires only on the host where the loss channel is closed, which is why
issue #47 was filed as a host feed defect on `windows-desk` and as a
byte deficit here. It is neither. **The macOS "loss" at RC 32 is not
loss** - it is this, rendered by a stack that counts bytes it will not
deliver.

Do not pool the two slow modes. There is also a **first-cycle** mode -
run 1 after a rate change, ratio ~0.95 with 30-360 underruns - seen on
both benches. It is not this, and averaging the two turns three clean
0.9374s into a "mean 0.9518". Discard cycle 1 explicitly; a per-rate
block that keeps it carries one outlier per rate.

Reproduce with `tools/issue47_ratio.py`. **One trap:** `consumed` counts
*buffers*, not samples. Read as samples it reports 2,380 sps against a
nominal 1,218,750 - wrong enough to be obvious, which is the only reason
it was caught before it became a conclusion.
