# The wrap displacement: what it was, what caused it, what the chase cost

Issue #5 ran from 2026-08-25 to 2026-09-13, 150 comments, three
benches. It was closed once on a tolerance and reopened the same day by
the condition it had set for itself. This page is what a reader needs
from it: the defect in one screen, the cause and the chain of evidence
that established it, and what the nineteen days teach about diagnosing
the next one.

## The defect

The board's own generator plays a 256-point sine from flash through the
DAC while the ADC captures it (preset `M`). Folded at the table, the
captured waveform shows a fixed set of table entries whose first sample
is displaced by up to 35 codes, always the same entries, spaced 21
apart. It is not a splice, not the host, not the wire, and not one
sample: it is a comb.

| what a user sees | scale |
|---|---|
| a few samples per DAC-table wrap read up to 35 codes off, against ~25 codes of standing noise | visible on the internal generator and on host-fed playback alike |
| both DAC channels carry it, in their own updates | A0 and A1 |
| present on three identical boards, three hosts, both firmware tracks, every compiler tried | the silicon, given the register value it was programmed with |

`docs/issue5-impact.md` says what that costs the instrument.

## The cause

**A DACC refresh conversion collides with the triggered conversion.**
`DACC_MR_REFRESH(1)` makes the controller re-convert each channel's held
value every 1024 DACC clocks (datasheet 45.7.2, "Refresh Period = 1024 x
REFRESH / DACC Clock"); with two channels enabled that is one refresh
conversion through the single DAC core every **512 DACC clocks**
(MCK/2, so 13.13 us). A conversion occupies the core for 25 clocks
(datasheet 45.6.1). A trigger that arrives while a refresh is converting
is served late, and the ADC - which samples A0 a fixed interval after
the same trigger - catches DAC0 still settling toward its new level. The
displaced sample reads about **0.70 of the local DAC step** short, on all
three boards (max residual 2.3 codes on +-35), which is why the folded
profile has the shape of the waveform's slope.

**Why 21.** The trigger period at the pinned preset is RC = 39 MHz /
200000 = **195** DACC clocks, and a DAC0 entry occupies two triggers:

    390 * 21 = 8190 = 16 * 512 - 2

Every 21 entries the trigger returns to within 2 clocks of the same
refresh phase, so a collision window ~20 clocks wide catches every 21st
entry for ten or eleven entries in a row and then none - the comb, and
its length. The period is the alias of the trigger against the 512-clock
event, computed from RC alone, and it changes when RC does.

**Why it does not smear.** 512 x 195 is a multiple of 512, so the phase
at table entry 0 is the same on every wrap and a fold at the table is
coherent for any number of wraps. The same identity holds for any
integer RC.

### The chain of evidence

| step | instrument | result |
|---|---|---|
| the shape | fit `-f * step(bin)` to the seven clean sites of the campaign's FWS 6 profiles | f = 0.695, 0.67-0.77 across sites, three boards; `records/issue5-campaign-*` |
| the period, on records already in the tree | place a fixed ~20-clock window with only its rotation fitted, `tools/issue5_alias_sweep.py::fit_rotation` | RC 98: **22 of 22** positions (P = 1024 places 11, P = 4096 places 4); RC 292: comb of 7, 24/24; RC 390: 24/24; DAC RC 520 and 584 (both congruent to a divisor of 512): comb of **64**, 8/8. `records/issue24-holdavg-macos.jsonl` |
| the period is 512, not 1024 or 4096 | the RC 98 site lists repeat every 256 triggers, which is `512 / gcd(98, 512)` | 0.93-1.00 of sites on every comb-bearing run |
| the prediction, registered before any row | `tools/issue5_alias_sweep.py::predict`, five presets on the frozen image, console commands only | RC 195 -> 21, 186 -> 11, 196 -> 17, 190 -> 31, 192 -> 4 |
| the hardware test, three boards | the same tool, run 1 dropped by index | every period lands on every board; a 21-grid fits at no rate but 195 (Jaccard 0.04-0.11 against 0.55-0.92); the window's rotation is the same number on all three boards at every rate. `records/issue5-alias-sweep-*` |

Two rival readings die on the same rows: "the lattice is a count of 21"
(which had been the settled reading) and "round(4096 / RC)", which
predicts 21 at RC 192 where the board gives 4.

### What the window is, and what is still open

The collision window has a width and a position, and they are set by
different things.

| axis | set by | evidence |
|---|---|---|
| width | flash wait states, through the DAC-start-to-ADC-start gap (`h_mimic` starts TC0, waits `K`, starts TC1) | RC 195 combs at FWS 6 and not at 4 or 5; RC 190 combs at FWS 5 and doubles each tooth at FWS 6 |
| position | the image and the rate; not the bench, not the run | identical fitted rotation on three benches at every rate, and on every sharp run of a block |
| per-capture draw | a **mode** at fixed position: a sharp comb, or a dense 60-80-site profile | RC 196 at FWS 6 on all three boards; the shape of the campaign's two run-level severity modes |

What the dense mode is has not been established. The `K` sweep at fixed
rate - 39 clocks per microsecond, no reflash - is the arm that can say.

## What the chase cost, and why

Nine mechanisms were proposed and refuted before the tenth; each of the
refutations was sound and most of the proposals were reasonable. The
cost was not wrong measurements. It was that the arithmetic that
answered the question needed no measurement and was not done, and that
the measurements which then confirmed it had been in the tree for two
weeks under a different question.

| what was believed | why | what was true | the error |
|---|---|---|---|
| one sample per wrap is displaced | `fold_profile` reports its largest bin | ten or eleven per wrap, on a comb | **summarising a profile by its argmax.** Two benches read the same statistic and disagreed about what moved |
| closed: 1-8 codes under 25 of noise | the bound held on the bench that closed it | 14.4 codes on the same bench eleven days later, 38 under clang | **closing on a bound, not a mechanism.** The trip condition the closure recorded was the one thing about it that worked |
| the site set is a comb, R = 1.000 | every stored row held six sites | 30-65 strong sites, of which the ten largest happen to be the comb | **storing a summary.** Six slots were a cap read as an incidence, and a pre-registered prediction named two positions as missing that were only unrecorded |
| the period is 105 us | 21 x 195 x 2 clocks | RC 98 reads 21 and 26 where a fixed period predicts 41.8 - so the time reading was withdrawn and "a count of 21" became settled | **a refuted form taken for a refuted model.** The modular form of the same period predicts 21 and 26 exactly; nobody asked what other form gave the numbers |
| the unit is 21 DAC updates, or 21 ADC conversions | at hold 3 the comb is 7 either way | neither: an alias, which is both a count and a time | **a false dichotomy held open for two weeks.** Written and withdrawn three times |
| the mechanism is instruction fetch timing | wait states move the sites | true, and one layer short: fetch timing sets the width of a window whose period is the refresh | **a knob that moves the effect was taken for its cause.** `=<us>K` had existed since day two and was read as a table-phase knob rather than the sub-trigger margin it is |
| the board, the wire, the jumper metal, the compiler | each comparison moved the figure | each comparison varied many things at once; the one-knob arm on one image was the one that worked | already a rule in `CLAUDE.md`, learned there on this issue, and not applied to the knob that mattered |
| severity is `total_abs` | it is what the tool printed | at FWS 6 it measures the noise floor; the comb sum moves 0.18% while it moves 10% | **a metric adopted because it was printed.** Count is noise, size is signal |
| the window position differs by host | one bench resolved a rate's comb and another did not | the fitted rotation was identical in both benches' rows | **attributing to the bench before diffing the shared statistic.** Corrected within the hour by the other bench reading the rows |
| a "dominant gap" scores the prediction | it was the registered scalar | it depends on the unmodelled window width and scored MISMATCH on a confirmed period | **registering a summary scalar.** The position-level fit was the honest statistic and was in the same tool |

Two things stand out from the table. **Nobody converted 21 into clocks
until the last day** - `195 * 21 = 4095 = 8 * 512 - 1` is one line, and
the handoff that finally asked for it ranked it first. And **the
datasheet chapter for the peripheral was not read until the last day**
either: the 512, the 25-clock conversion, the four-word FIFO and the
refresh sentence are all in section 45, and the mechanism claim on file
("fetch timing, measured") had made looking there feel unnecessary.

## What to do differently

| rule | why | where it lives |
|---|---|---|
| **Before proposing a mechanism for a number, write it in every clock the system has** - MCK, MCK/2, ADC clock, the table, the PDC block, every peripheral timer | it is arithmetic, it is free, and here it was the answer | this page |
| **Register a model as code that predicts positions, and score positions** | a summary scalar can be right for the wrong reason and wrong for the right one; `fit_rotation` beside `predict` in one tool is the shape | `tools/issue5_alias_sweep.py` |
| **Run a candidate against every record in the tree before asking for board time** | the confirming rows were two weeks old and recorded for another question | `records/` is indexed by issue; read it by quantity |
| **When a form of a model is refuted, ask what other form gives the same numbers before settling on its rival** | the time reading died correctly and took the right period with it | this page |
| **The knob must be the model's parameter** | one knob on one image is the rule; `K` moved the effect for two weeks while being read as the wrong parameter | `CLAUDE.md`, "look for the knob" |
| **Store whole profiles; read count and size apart; never a pooled median across a two-state position** | each of these was paid for | `docs/issue5-campaign.md`, "Reading the result" |
| **Diff the shared statistic across benches before writing "differs by bench"** | the rotation was in both benches' rows | this page |
| **Read the peripheral's datasheet chapter before the tenth hypothesis** | section 45 held the number | `docs/datasheets/` |
| **Close on a mechanism. A bound buys time and a reopening** | the trip condition was right to exist and it fired | this page |
