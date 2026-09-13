# Handoff: root-cause analysis of issue #5, from the data

Paste the block below as the opening prompt of a new session. It is written
to be self-contained: it names where the data is, what is solid, what is
shaky, and — the point — what has **not** been attempted.

---

You are picking up issue #5 on the `due_oscilloscope` project, on the
`linux-x1` bench. **Your job is root-cause analysis.** A three-bench
measurement campaign ran to completion on 2026-09-13 and produced a lot of
characterisation and **no mechanism**. Patterns exist; none is explained.
Do not re-measure what is already measured — read the data and try to
explain it.

## Read first, in this order

1. `CLAUDE.md` — especially "Facts that are easy to get wrong", and the
   existing #5 mechanism claim: `docs/awg.md` attributes the defect to
   **instruction fetch timing**. That claim predates all of this data and
   has never been tested against it.
2. `docs/issue5-campaign.md` — the protocol and, under **"Reading the
   result"**, the method rules. Those rules were each paid for; breaking
   one costs a result.
3. `analysis/README.md` — the data's column conventions. Generate the data
   first:
   ```sh
   .venv/bin/python tools/issue5_export.py     # -> analysis/*.csv
   ```
4. Issue **#5**'s last ~20 comments for how the conclusions were reached
   and what was withdrawn, and standing pages **#32** (this bench) and
   **#71** (cross-bench).

## What the data is

Nine arms, three boards, one frozen firmware image (`1b2a2d1`, container
build, Track B), one preset (`=200000,200000M`), 72 analysed runs each,
whole 256-point fold profiles stored per run.

| table | rows | one row per |
|---|---|---|
| `analysis/runs.csv` | 1042 | capture — provenance, wire, leg, wait state, totals |
| `analysis/profiles.csv` | 165,888 | (run, position) — `dev_signed` and `dev_abs` |
| `analysis/positions.csv` | 6912 | (arm, wait state, position) — aggregates, `pos_mod_21`, `on_lattice21` |

Three boards × three legs: `campaign` (baseline), `crossover` (jumper wires
exchanged between the `linux-x1` and `windows-desk` boards), `return` (same
physical pairs put back). **`mac-bench` was untouched in all three legs and
is the drift control.** The `onimage` arms are superseded — they stored six
sites and no profile.

## What is solid

- **Two severity populations at FWS 6.** On-lattice sites ≈ 29 codes,
  everything else ≈ 2 codes — a 15× separation, replicated on three boards
  to about 2%.
- **A period-21 lattice.** 8 of the 10 large FWS 6 positions are at
  `12 + 21k`: 12, 33, 54, 96, 117, 138, 159, 180.
- **The between-board difference is the board.** Seven fixed comb sites read
  193.75 / 189.75 / 193.52 and move by at most 0.5 across every leg. The
  jumper material is **not** it (crossover `D = −16.68`, `NEITHER`).
- **A small reversible per-board response to its own specific wire pair.**
  `linux-x1`'s twelve-point sum: 235.51 → 250.52 → 235.83 against a control
  that moved 0.32. Handling excluded; metal not established (one pair per
  material).
- **Between-session repeatability of the comb sum is 0.43 on 238 (0.18%).**
- **`total_abs` is not a usable statistic at FWS 6.** The *untouched* board's
  severity swung 398.1 → 359.2 → 362.1 — 10% — while its comb sums moved
  0.43.
- **Count is noise, size is signal.** On an untouched board a site's run
  count swings 8–16 of 24 while its size-when-large holds to 0.3.

## What is shaky, and do not inherit it as fact

- **The comb is 8 of 10, not 10 of 10, and R is 0.75–0.94, not 1.000.** The
  R = 1.000 figure on issue #5 came from arms that stored only each run's six
  strongest sites — which are, by construction, the six largest and happen
  to lie on the lattice. **169 and 247 are large and off-lattice**
  (`mod 21` = 1 and 16). Significance is p = 6e-04 on one board and 0.07 on
  the other two.
- **The full strong site set is not a comb at all** — 30–65 positions per
  arm, R below 0.4.
- **A pre-registered prediction was refuted**: positions 54 and 96 were
  named as "missing from the comb" and were never missing, only unrecorded.
- Flip counts of two-state verdicts carry **no** information at these
  sample sizes: one arm's split-half count spans 11–73 of 768.

## The unexplained patterns — this is the work

1. **Why 21?** Nobody has converted it to physical units. 21 fold positions
   = 21 DAC table entries = 42 ADC conversions at this preset. Express that
   in MCK cycles, in TC RC counts, in flash wait states, in PDC transfer
   sizes, in DACC refresh intervals — and see whether any lands on a
   constant in `drivers/` or on the ADC/DAC divider arithmetic. `MCK is
   78 MHz`, `ACQ_MIN_RC = 86`, `GEN_TABLE_POINTS = 256`, `SETTLE_US = 1e6`.
   **The single highest-value unattempted calculation.**
2. **Why does the comb close?** 21 does not divide 256, so a free-running
   period-21 disturbance would advance 4 positions per table wrap and smear
   away under a fold over hundreds of cycles. It does not smear — so it must
   be **re-synchronised at the table wrap**. What re-synchronises?
3. **Why FWS 6 ≫ FWS 4/5?** Severity 394 against 41 and 34. Flash wait
   states are instruction fetch timing, which is the existing mechanism
   claim. But the *site positions* also change with wait state and the
   lattice is cleanest at 6 — is that more fetch stalls, or a different
   mechanism becoming visible?
4. **Two run-level severity modes** on 2 of 3 boards, interleaving run by run
   (not blocks, not drift). The mode difference is **structured**: 53
   positions on 8 residues mod 21, with DFT lines at the 5th and 10th
   harmonics of period 21 under a one-cycle-per-table envelope. What has two
   states per run and is re-drawn per capture?
5. **169 and 247** — large, off-lattice, unexplained. Is there a second
   lattice, or are these something else?
6. **`linux-x1` campaign run 31**: the comb collapsed to 28%, and
   **phase-gated** — the first five lattice points went to ≈0 while the last
   five survived with a graded recovery. One run in 72, no analogue in 48
   more, and no counterpart on the other boards. A time-localised cause
   cannot do this (the fold would scale all phases together), so the
   amplitude depended on **table position** in that run.
7. **Phase 16 at FWS 5 is a binary switch** — two quantised states, 0.26-code
   spread within each, nothing between.
8. **The board-bound difference**: 193.75 / 189.75 / 193.52 on the seven fixed
   sites, stable to 0.5 across every leg. Three identical boards, one image.
   What differs between dies that is this reproducible?
9. **Possible link to #48**, untested: that defect's DACC deficits are
   quantised in **1/256ths** and this one's sites sit on a **period-21**
   lattice in a 256-point table. Both involve `DACC_MR_REFRESH` territory.
   Nobody has looked for a common divisor story.

## Traps, each of which cost a result during the campaign

- **A difference is readable only against a baseline measured at the same
  resolution and by the same procedure.** Per-position changes have one —
  the untouched board's per-position drift. Use it. Per-position drift is
  wildly non-uniform: median 0.02 codes, max 9.32 at FWS 4.
- **Name the estimator at the call site.** Four conventions for "the value at
  a position"; two benches produced disagreeing numbers for one quantity
  four times in one afternoon, and every time both numbers were correct.
- **Never a pooled median across a two-state position.** Read count and
  size-when-large separately. A pooled median crossing a state boundary
  looks exactly like a size change.
- **Drop run 1 by index, never by a filter on what it does wrong.**
- **Break a new check on purpose before trusting it**, and **a null is worth
  what the experiment could have detected**.
- **Do not invent numbers.** Mark uncertain figures *(check)*.

## Constraints

- **Firmware is frozen at `1b2a2d1`** for cross-bench comparability. If a
  mechanism test needs a firmware change, say so and ask — do not assume the
  freeze is liftable.
- Three other agents work this repository. `main` moves; pull before you
  branch and before you commit; read #31, #32, #34 and #71.
- Anything needing hardware belongs to a bench owner. Ask; do not assume.

## What would count as progress

A mechanism that predicts something not yet measured, and a way to test it
that does not need new hardware. Failing that, **a candidate killed with
evidence** is worth as much — four models died on #48 that way and the
issue is better for it. What is not progress is another characterisation
pass over the same nine arms.
