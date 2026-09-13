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

## The pre-registered prediction

The period-21 lattice through those six positions has 13 points:

    8, 12, 33, 54, 75, 96, 117, 138, 159, 180, 201, 222, 243

The sites occupy six. If the comb is the structure and the old rows were
merely truncated, **the sites they dropped are the other seven** — 8, 54,
75, 96, 201, 222 and 243. A dropped site anywhere else refutes it.

Registered before the arm that tests it exists, and asserted in
`tests/test_issue5_spectrum.py` so it cannot be quietly adjusted
afterwards. Nothing in the current records can settle it: they kept no
profile.

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
which. The design that would is a jumper-material A-B-A on one copper
bench, and it needs jumpers fitted by hand.

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
