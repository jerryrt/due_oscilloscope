# Measurement records

One JSON line per run, written by `tools/phase0.py`, flushed and fsynced
before the next run starts. Each line carries the values, the arguments,
and the provenance block that makes it attributable - firmware identity,
host, `host/` revision, wiring, instrument, probe ratio as *told*.

Read one with `python3 tools/phase0.py <metric> --report`, which needs no
bench. The summary it prints is derived and deliberately not committed:
a derived file in the tree is a second home for a number that already
has one.

## What is here

| file | method | what it is evidence for |
|---|---|---|
| `phase0-settle.jsonl` | current | `settle` as the tool now runs it - 7 runs in place |
| `phase0-settle-levelrefine.jsonl` | level found by refinement, still *chosen* by the coarse median | that refining faithfully refines the wrong level: one run in seven landed on the square's low level |
| `phase0-settle-asfound.jsonl` | as found on 2026-08-27, before the guards | the 118 us "settling tail", and the 82% run-to-run spread underneath it. 7 in place, 7 across reflashes |

The names carry the method because the method changed between them, and
a spread taken across two methods is not a spread.
`docs/measurement-suite.md` has the argument and the verdict.

## Rows that are known bad, and why they are still here

A record is append-only. A row that turned out to be corrupt is
annotated rather than deleted, because a gap in a series is worse than a
labelled bad row: the gap invites the next reader to wonder what was
there, and the label tells them.

| file | rows | what happened |
|---|---|---|
| `issue5-a1-macos.jsonl` | `bench` = `macos-long2` | The pytest suite was run against the board while this series was capturing. The ports fought and the captures are corrupt - equal-and-opposite pairs of *thousands* of codes, 128 bins apart, where the same instrument reads single codes everywhere else. Excluded by name in `tools/issue24_outliers.py`. |

**If you write a tool that walks these files, exclude that `bench` value.**
The corruption is large and would dominate any statistic it entered.

The mechanism is worth knowing beyond the one block: a second process
opening the ports mid-capture does not fail loudly, it produces
plausible-looking numbers. Do not run the suite against a board another
tool is holding.

## Rows whose `track` field is wrong, and how to read them

**Nine record-writing tools carried `track="b"` as a literal until
2026-08-30** (`a263a75`, `1e3d270`, issue #53). They did not ask the
board what was on it, so **every Track A run they wrote is labelled
Track B**. The tools ask now, via `provenance.run_fields()`; these
files predate that.

A missing field is a gap. A wrong one is a trap, because a reader has
no reason to distrust it — so these are named here rather than left to
be discovered.

| file | rows | actually |
|---|---|---|
| `issue48-tracka-macos.jsonl` | 24 | **Track A**, `mac-bench` |
| `issue48-lattice-tracka-macos.jsonl` | 32 | **Track A**, `mac-bench` |
| `issue44-gaps-mac-bench-trackA.jsonl` | 40 | **Track A**, `mac-bench` |

**For these files the filename and the `bench` value are authoritative
over the `track` field.** They are not rewritten, and the reason is
narrower than the section above: correcting them would mean asserting
provenance for runs **nobody now present was there for**. They are
earlier macOS sessions' work, not this one's.

**linux-x1's file was in this table and is not any more, and the
difference is instructive.** `issue44-gaps-linux-x1-trackA.jsonl` had
the same two faults - `track: "b"` on Track A data, and the track
smuggled into `bench` - and they **corrected it** rather than
annotating it, to `issue44-gaps-linux-x1-a.jsonl` with `bench:
linux-x1` and `track: "a"` (`ec97aae`). That is the right call *for
them*: they took the runs that evening and can vouch for what was on
the board. It is not available to me for the three above.

So the rule is not "annotate rather than correct". It is **correct what
you witnessed, annotate what you inherited** - and say which you did.

**Why the `bench` value is doing the work.** Because `track` could not
be recorded, whoever ran these put the condition in the bench name —
`mac-bench-trackA`, `linux-x1-trackA`. That is a sensible workaround
and it is why the data is recoverable at all. It also means **`bench`
is not reliably a bench**: `records/` holds 32 values that name a
condition rather than a desk (`mac-bench-refresh2`, `macos-rc98`,
`macos-draws`, …), so **grouping by `bench` across these files will
split one desk into several**. `CLAUDE.md`'s rule that a figure without
its bench is not comparable with anything still holds; what has to be
checked first is whether the field says which desk or which arm.

**And a desk can be renamed under you.** `macos-dso` and `mac-bench` are
the same desk: it declared itself `macos-dso` in `bench.json` while a
DS1102E sat on it, and was renamed on 2026-09-01 when the scope went
away and the name stopped being true. So 83 rows across
`noise-codes.jsonl`, `noise-activity.jsonl` and `metrics.jsonl` say
`macos-dso` and everything that desk writes from now on says
`mac-bench`. **They are joinable and nothing in the files says so.**

The same swap moved DAC1 from the scope's EXT TRIG to **A1**, so
`A1 free` is true of the `macos-dso` rows and false of the `mac-bench`
ones. A noise figure that used A1 as its quiet reference is measuring a
driven pin on one side of that date and a floating one on the other -
`wiring` and `wiring_since` are the only fields that carry it, and rows
that predate `collect()` carry neither.

**One claim leans on a file in this table.** `issue48-tracka-macos.jsonl`
is the Track A arm behind `fe4ec0b` — *"the oracle agrees - RC 32's
15/16 is the silicon, not a track"* — and the `2/24` in `CLAUDE.md`'s
*"Track A 2/24 against Track B 7/32, p = 0.16"*. The finding is very
probably sound: the filename, the `bench` value and the commit message
all say Track A, and whoever ran it knew which binary was on the board.
**But do not recompute that statistic from the `track` field**, which
would silently pool both arms as Track B.
