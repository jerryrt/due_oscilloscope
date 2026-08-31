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
| `issue44-gaps-linux-x1-trackA.jsonl` | 40 | Track A *(linux-x1's; asked on #53, not yet confirmed by them)* |

**For these files the filename and the `bench` value are authoritative
over the `track` field.** They are not rewritten, for the reason the
section above gives and one more: correcting them would mean asserting
provenance for runs nobody now present was there for. The first three
are this bench's and I can vouch for them; the fourth is named as
pending rather than asserted.

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

**One claim leans on a file in this table.** `issue48-tracka-macos.jsonl`
is the Track A arm behind `fe4ec0b` — *"the oracle agrees - RC 32's
15/16 is the silicon, not a track"* — and the `2/24` in `CLAUDE.md`'s
*"Track A 2/24 against Track B 7/32, p = 0.16"*. The finding is very
probably sound: the filename, the `bench` value and the commit message
all say Track A, and whoever ran it knew which binary was on the board.
**But do not recompute that statistic from the `track` field**, which
would silently pool both arms as Track B.
