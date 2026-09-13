# The issue #5 three-bench campaign

One experiment, run identically on three benches, analysed in the time
domain and the frequency domain. This document is the protocol and the
reading; `tools/issue5_campaign.py` is the protocol made executable, and
it refuses rather than running a variant.

Read `CLAUDE.md` first. Two of its rules decide the shape of everything
below: a figure is drawn by the image, so a cross-bench comparison is
only a comparison while the binary holds still; and a check that cannot
fail is worse than no check.

## Why the existing rows cannot answer it

The first three-bench arm is in `records/issue5-onimage-*.jsonl` and its
headline result is that at flash wait state 6 all three benches draw the
same six cycle positions. That result stands as far as it goes. What it
does not do is describe the site set, and the reason is in the
instrument rather than the board.

`tools/issue5_sites.py` stored each run's six strongest sites. `found` is
ordered by descending deviation, so a run with more than six kept the
largest and dropped the rest, with nothing in the row to say it had. At
wait state 6 **every row of every bench** did that — 120 runs, no
exceptions. The dropped total is recoverable, because the severity was
summed over all the sites before the list was cut:

    hidden = site_abs - sum of |deviation| over the sites the row stored

which is `issue5_onimage_compare.censored()`. Applied to the committed
rows at wait state 6:

| arm | severity | in the six stored sites | dropped | ≥ sites dropped |
|---|---|---|---|---|
| `linux-x1` | 396.3 | 189.1 (48%) | 121.3 | 4.4 |
| `windows-desk` | 445.5 | 176.7 (40%) | 216.6 | 11.0 |
| `mac-bench`, probe-free 2 | 343.6 | 189.9 (55%) | 89.9 | 3.2 |

The last column is a lower bound: every dropped site is no larger than
the smallest one kept, so the dropped total over that smallest is a
floor on how many there were. So the published set is the strongest six
of a set with at least ten members, and **how many members differs by
bench** — windows-desk, the high-severity arm, drops the most.

One consequence is visible in the old records and reads as physics.
Positions 180 and 247 were never once recorded in the same run, on any
of the five arms, across 120 runs. Five other positions outrank both in
every run, so the two were competing for the sixth and last slot and
whichever was larger that run is the one written down. An either/or in
the data that is an artifact of the slice.

The severity figures are untouched by this: `total_abs` sums all 256
positions and never consults the site list. What the truncation costs is
the set, not the size.

## The frequency-domain reading

The site table says which positions and nothing about spacing. Asked
that question, the wait-state-6 set answers immediately: 12, 33, 117,
138, 159 and 180 are each 12 more than a multiple of 21. Folded onto
period 21 they fall on one phase.

`tools/issue5_spectrum.py` measures it. Its primary statistic is the
circular resultant of the site positions folded onto a candidate period,

    R(p) = | (1/n) Σ exp(2πi·bᵢ/p) |

maximised over every period from 3 to 128. R = 1 is a perfect comb and
scattered positions give about 1/√n. Circular rather than a linear
spread, for the reason `CLAUDE.md` gives about jitter: positions either
side of a wrap have no linear centre.

| bench | FWS | positions | phases mod 21 | R |
|---|---|---|---|---|
| `linux-x1` | 6 | 12, 33, 117, 138, 159, 180 | {12: 6} | **1.000** |
| `windows-desk` | 6 | same | {12: 6} | **1.000** |
| `mac-bench` | 6 | same | {12: 6} | **1.000** |
| `linux-x1` | 4 | 75, 159, 180, 219, 240 | {9: 2, 12: 3} | 0.905 |
| `linux-x1` | 5 | 134, 155, 251 | {8: 2, 20: 1} | 0.394 |
| `windows-desk` | 5 | 16, 39, 50, 134, 155, 251 | {8: 3, 16: 1, 18: 1, 20: 1} | 0.091 |

Wait state 6 is one comb on all three benches. Wait state 4 is two
phases of the same period — and one of them, 12, is wait state 6's. Wait
state 5 does not sit on it.

Two things about that table are easy to get wrong and are worth stating
before anyone quotes it.

**The period reported is the largest that ties, and that is deliberate.**
A set congruent modulo 21 is congruent modulo 7 and modulo 3 as well, and
R is exactly 1.000 at all three. The smallest is a true statement that
predicts nothing ("the sites are multiples of 3"); the largest is the
generator. Reporting the smallest was this tool's first behaviour, and it
described the result above as "period 3". No *multiple* of a true period
ties — positions congruent mod 21 split into two phases mod 42 — so
taking the largest does not run away upward.

**The p-value is scan-corrected and it is 0.006, not 5e-05.** The
statistic is a maximum over ~126 candidate periods, so the null is
charged the same scan: 0.0055 of 20,000 uniform six-position draws reach
R = 1 somewhere in it, mostly at period 3, which is easy. A sharper test
exists — R at a period fixed in advance, `fixed_period_pvalue`, which
puts this set at 5e-05 — and it is **not valid on the rows that found
the period**. It is the test the next arm pre-registers.

That correction cost a rewrite. The first version of the p-value
conjoined "and at a period at least this long" onto the null condition,
which reads as a sharper test and is not a p-value: for a uniform set the
maximum R already exceeds the null's about half the time, so the extra
condition cuts the count further and the number came out small on noise.
Six of twenty-five uniform draws scored below 0.05 on it. It was the
control in `tests/test_issue5_spectrum.py` that caught it, not reading.

### What a comb implies, and what it does not

A disturbance periodic in wall time averages away under a fold over
hundreds of cycles. One that survives the fold is locked to the table
index. And 21 does not divide 256, so a free-running period-21
disturbance would land four positions further on at each wrap and smear
too — surviving therefore also implies it is re-synchronised when the
table wraps.

`docs/awg.md` attributes issue #5's mechanism to instruction fetch
timing, and flash wait states are instruction fetch timing, which is
consistent with the comb being sharpest at the highest wait state. **No
candidate mechanism is named here.** Four models died on #48 for being
argued rather than measured, and this document is not going to add a
fifth.

**And the comb is measured on the visible half.** The six positions that
make R = 1.000 are the six a row had room for. If the sites those rows
dropped are off the lattice, the comb is weaker than it looks.

## The pre-registered prediction, and its refutation

The period-21 lattice through those six positions has twelve points
inside one pass of the table:

    12, 33, 54, 75, 96, 117, 138, 159, 180, 201, 222, 243

The sites occupy six. The prediction was that if the comb is the
structure and the old rows were merely truncated, **the sites they
dropped are the other six** — 54, 75, 96, 201, 222 and 243 — and that a
dropped site anywhere else refutes it. Registered before the arm that
tests it existed and asserted in `tests/test_issue5_spectrum.py`.

**Position 8 is not on the lattice**, and older postings that name it
are quoting a generator that ran one step past the end of the cycle and
wrapped. 8 is at phase 8 of period 21 against the comb's 12, so a site
there would score **against** the structure the prediction tests for —
which makes it the one position whose presence or absence says nothing
either way. `tests/test_issue5_spectrum.py` asserts that every lattice
point is congruent to the offset and inside one cycle, so a wrap cannot
reach a prediction again.

**The prediction is refuted on all three benches**, by the criterion as
registered. The arms store whole profiles, so the dropped sites are now
visible: most of them are off the lattice, and two of the six predicted
points — 222 and 243 — carry no site at all on any bench.

**What survives is sharper than what was predicted.** The artifact has
two populations. Sites on the lattice are an order of magnitude larger
than sites off it, and lattice occupancy falls monotonically down the
strength ranking — every bench's strongest few sites are on the comb,
and by the thirtieth site it is no better than chance. So **the comb is
the large sites, not the site set**, which is a different statement
from the one registered and is therefore exploratory until an arm
designed to test it says so.

Two consequences for anyone quoting the frequency-domain table above.
The fixed-period test at 21 gives a very small p on the six strongest
sites and nothing at all on the full strong-site set, so **naming the
test without naming the set leaves the answer to be chosen afterwards**
— a registration has to name both. And the "180 and 247 never co-occur"
result was the six-site slice and nothing else: with whole profiles
stored they co-occur in essentially every run.

## The arm

    .venv/bin/python tools/issue5_campaign.py --check   # preflight
    .venv/bin/python tools/issue5_campaign.py

One command, the same on every bench. It captures nothing itself — it
preflights and hands off to `tools/issue5_sites.py`, which owns the
capture loop, because two capture loops would be two homes for one
protocol and three arms that had drifted would be three near-misses of
one experiment.

### What is pinned

| pinned | value | why |
|---|---|---|
| firmware commit | `1b2a2d1`, the freeze | #5's site set and severity are drawn by the binary |
| image | the **container** build of Track B, `4126e6d5…` | three host toolchains are two code generators (#78) |
| provenance | `matched by commit` | a board that is not is unattributable, however right `v` looks |
| preset | `=200000,200000M` | bare `M` leaves whatever the board booted with |
| FWS plan | `4x13,5x12,6x12,6x12,5x12,4x12` | counterbalanced inside one session, the one #5 design immune to between-arm drift |
| n analysed | 24 per wait state | every published ceiling was taken at 24, and a Jaccard's ceiling moves with n |
| run 1 | **discarded by index** | first-run outliers on all three benches, and a filter on what run 1 does wrong has already missed one |
| stored per run | the whole 256-point profile, and every site | the gap this arm exists to close |
| the analog path | `--probes` and `--jumpers`, per session, no default | see below |

The plan asks for 13 runs in the first block so that 24 survive the
discard. The previous arm took 72, analysed 72, and carried its first
run into every figure.

### The analog path has to be declared

`bench.json` has a field for what is **wired** to a board and, until this
campaign, none for what is **clipped onto** it or what the wire is made
of. `mac-bench`'s first arm ran with two undeclared oscilloscope probes
on A0 and A1 while `wiring_source` read `declared`, and
`tools/wiring_probe.py` passes with probes fitted because a probe does
not change which DAC reaches which pin. Removing them moved every
severity figure on that bench — down 86–94 at FWS 4, 80–82 at FWS 5 and
61–63 at FWS 6 — so the probes were **masking** a difference as well as
adding one.

The one declared analog difference between the benches is the loopback
jumpers' metal: `windows-desk` iron, `linux-x1` and `mac-bench` copper,
at roughly the same length. It reached the record only as prose on an
issue.

So `issue5_campaign.py` refuses without `--probes` and `--jumpers`, before
it opens the board, and records both on every row.

**They are arguments and not `bench.json` fields, and that is a ruling
rather than a preference.** A standing `probes` field was considered and
refused: a probe goes on for an investigation and comes off again, so the
field would be empty almost always, maintained for a while, and then
silently stale — the same failure this project collects everywhere else,
where the failure is indistinguishable from success. An argument cannot
go stale, survives a swap in the middle of a session, and lands in the
rows, which is where provenance belongs.

This tool's first version required them in `bench.json` and was wrong by
an hour.

### What this arm does not separate

Three benches are three dies. A between-bench difference on one binary
is board, jumper material, or USB IN DMA timing on the device — the #5
arm takes the host out of the DAC path explicitly (`h_mimic` calls
`play_stop()` first, then `gen_prepare_tioa1()`, and the capture starts
with `with_gen = false` because the generator already owns the DACC), so
the only host route left is that the host's reading sets the timing of
the device's USB IN DMA transfers, which `stream_core.c` holds to 512 B
for exactly that reason.

The severity spread across benches — 342.7 to 445.5 on the old rows —
is one of those three and this campaign is not the experiment that says
which.

## The three boards share one desk

They are not in three rooms, and nothing in this document said so until
the crossover needed it. The three hosts are separate machines; the
three Dues sit on one bench surface, reachable by one pair of hands.

That is worth writing down for two reasons beyond the obvious. It means
ambient temperature, mains and local EMI are **shared**, so the list
above — board, jumper material, USB IN DMA timing — is complete rather
than merely the part anyone thought of; an environment term would
otherwise belong on it. And it makes an experiment available that the
three-separate-benches reading hides: the wires can be **exchanged
between two boards**, which is strictly stronger than removing and
refitting them on one.

## The crossover, and what it settled

The design the paragraph above used to propose was an A-B-A on one
copper bench. Co-location replaced it with a crossover: the `linux-x1`
board's copper and the `windows-desk` board's iron were **exchanged**,
the `mac-bench` board was left untouched as a control, and all three
were re-read. Then the original wires went back on both and all three
were read a third time. `tools/issue5_crossover.py` holds the
registration, the statistics and the decision rules, all fixed before
each arm was captured.

**The material is not the cause.** Under the material hypothesis the
two boards' values must exchange; they did not. The primary statistic
landed outside both predictions, and the seven stable lattice sites did
not move on any board. The large between-bench difference — one board
reading about half the others at the strongest comb site — **stayed
with the board** through both legs.

**The control is what makes that readable.** The untouched board's comb
sum held across all three readings to well inside its registered
tolerance, which also produced a figure the project did not have:
**between-session repeatability of the comb sum, about 0.2 codes on
238.** No arm before this campaign stored a profile, so it could not be
measured, and the tolerance had to be guessed from within-session
spread. It was three times looser than the truth.

**Something smaller is real, reversible, and not the metal.** Both
swapped boards changed at specific positions and both came back when
their own wires returned, recovering most of each excursion. Both
owners confirmed by eye that the **same physical pair** went back. A
re-seat is a fresh random contact and could reproduce one position by
luck, not five; so the effect belongs to the individual pair of wires,
including whatever of its geometry reproduces on re-insertion. One pair
of each material cannot separate *this iron pair* from *iron*, and no
further arm of this design can.

So there are two findings and they must be kept apart. The bench
difference is the board. The wire does something smaller, reversibly,
that is not the bench difference and is not attributable to the metal.

## What the crossover cost to read correctly

Every analytical step was registered before its rows existed, and
several were still wrong — in the statistic rather than the data.
`tools/issue5_crossover.py` carries each correction at the rule it
changed. The one that generalises furthest: **a difference is only
readable against a baseline measured at the same resolution and by the
same procedure.** Per-position change has one, the untouched board's
drift at that position, and it caught a wait-state result that had
already been published and withdrawn on a worse statistic. A
verdict-flip count does not, and three benches each published something
from one before all three retracted it.

The other, which cost four separate disagreements in an afternoon:
**name the convention at the call site.** "The per-run value at a
position" has four readings — centred or raw, signed or magnitude —
and two benches used three of them for one quantity. Each time both
numbers were correct and the name was the defect.

## Reading the result

`tools/issue5_report.py` regenerates the report page from whatever is in
`records/`; `tools/issue5_onimage_compare.py` does the per-wait-state
cross-bench comparison and now refuses to read a truncated site set
against a complete one, because a short list disagrees at every position
it could not reach.

Four reading rules carried forward from the first arm, each of which cost
something:

- **Per wait state, never pooled.** On one image in one session a wait
  state redraws the site set as thoroughly as a different compiler does.
- **The ratio against the bench's own block-to-block ceiling, never the
  p.** Mann-Whitney reads overlap, not medians, so the p inverts against
  the ratios: the closer pair scored the smaller p.
- **Per-site counts, not threshold memberships.** A site set is a
  threshold over an incidence, and the threshold manufactures
  disagreements — one position was 8 of 24 on one bench and 23 of 24 on
  another, present on both and a member on one.
- **Quote a repeatability with its sample size.** A Jaccard ceiling at
  n=12 is not comparable with one at n=24.

### A difference needs a baseline taken the same way

A change is readable only against a baseline measured at the same
resolution, by the same procedure, on something nothing was done to.

| difference | its baseline | readable |
|---|---|---|
| a position's size across a manipulation | the untouched board's size at that same position and wait state, across its own repeated arms (`control_tolerance` in `tools/issue5_crossover.py`) | **yes.** Drift is not uniform: between two untouched `mac-bench` arms the median position moved 0.03 codes and the worst 9.45, so a single tolerance for every position is wrong at nearly all of them |
| how many positions' two-state verdict flips between two arms | one arm's own runs, split in half | **no.** On `windows-desk`'s copper arm the split-half count ran from 11 to 73 of 768 cells depending only on how the runs were divided, and every between-arm count on three benches fell inside that range. Not evidence at 12 runs a side |
| how many runs a site spends in its large state | the untouched board's count at that position, which swings across roughly 8 to 16 of 24 runs on `mac-bench` with nothing done | **against that swing, and it is noise.** A count change is never the finding by itself, and `RETURN_MIN_COUNT` is its floor. Unlike the flip count this one has a baseline; the baseline says it carries nothing |

`docs/noise.md` makes the neighbouring point for arm-level figures:
pooling across a hidden variable manufactures modes.

### Name the estimator

"The value at a position" has four conventions:

| convention | per-run value |
|---|---|
| centred magnitude | `abs(profile - median(profile))` |
| centred signed | `profile - median(profile)` |
| raw magnitude | `abs(profile)` |
| raw signed | `profile` |

Two correct numbers under one name disagree when they rest on different
conventions or different site sets, and the defect is the name:

| one name | two readings | where they part |
|---|---|---|
| a site's size across runs | median of the magnitudes 8.07, magnitude of the median 1.63 - `windows-desk`, FWS 6, position 201 | the site changes sign between that board's two modes, so signed values cancel before the magnitude is taken |
| the comb sum | ten lattice sites put `windows-desk` 9.6% below the two copper benches; the seven that do not move with the mode put it 2.0% below | 75, 180 and 201 move with `windows-desk`'s FWS 6 mode and barely at all on the other two boards |

A figure states its convention and its site set, and two figures for one
quantity are checked for both before either is called wrong. The
crossover tool names the convention at each call site: `comb_sum` and
`state_split` take raw magnitude, `seven_sum` takes centred magnitude.
On these rows centring moves the comb sum by 0.02 codes, and the
registered constants keep the convention they were computed with.

### Reading one position

A position's values across runs answer two questions, and one number
cannot hold both: how **often** the site sits in its large state, and
how **large** it is when there.

| component | what it is | what moves it |
|---|---|---|
| count | runs in the large state | occupancy, and sampling |
| size when large | median over those runs | the site itself |
| size when small | median over the rest | the floor under it |

A pooled median follows the count, not the size, whenever the count
crosses half the runs. Centred magnitude, `windows-desk` across its
jumper swap:

| position | pooled median | count of 24 | size when large |
|---|---|---|---|
| FWS 5, 134 | 0.17 -> 13.31 | 9 -> 14 | 10.15 -> 13.37 |
| FWS 6, 247 | 15.15 -> 23.79 | 12 -> 13 | 23.59 -> 23.91, and 6.69 -> 6.68 when small |

The first looks like a site appearing and is a site that grew by a
third. The second looks like a site growing by half and did not move in
either state.

`state_split` and `score_return` in `tools/issue5_crossover.py` read a
position this way.

### When a position has two states

| rule | why |
|---|---|
| Two states only if `issue5_modes.classify` calls the position's per-run values two modes | A largest-gap cut with no minimum per side makes one run a "state", whose median is the distribution's maximum. The cut also moves with which arms are pooled: `linux-x1`'s three legs at FWS 6 position 169 give counts 14/14/1 under a per-comparison cut and 23/24/24 under a three-arm cut, and a different verdict under each |
| The two-state verdict must hold in every leg compared, or the position is read on the pooled median | A single arm's verdict depends on which runs were drawn |
| A degenerate split is reported as one | A one-run "median" read as a size is an extreme value mistaken for a state |

`two_state_guarded` in `tools/issue5_crossover.py` applies the first two
rules, and it is the rule for any readout registered after it. The
crossover's return verdicts were registered before it and are scored by
`state_split`, whose `MIN_STATE_SIDE` only refuses a side with fewer than
four runs; `--check` prints the guarded reading beside each of those
verdicts so a reader can see which ones the guard would refuse.
