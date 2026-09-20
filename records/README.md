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

## Rows that carry no provenance at all, and why none is being invented

**6,374 rows across 216 files carry no revision — half of everything
here — and 2,273 name no bench.** They are whole files rather than
scattered rows: in every one of those 216, *no* row has a revision,
because the tool that wrote them did not record one yet.

| | rows | of 12,791 |
|---|---|---|
| no `repo_rev` or `fw_repo_rev` | **6,374** | 50% |
| no `bench` | 2,273 | 18% |

**Nothing is being back-filled, and that is a decision rather than an
omission.** A revision could be guessed from a file's mtime or from the
commit that added it, and a bench from the filename in many cases — but
a guessed field reads exactly like a measured one, and this file exists
because a *wrong* field is worse than a missing one. These are honest
gaps.

**What they cost is specific: those rows are attributable to a
question, not to an image.** They can be read as "this is what was seen
once", never as "this is what that build did" — so they cannot be
compared against a figure taken at a known commit, and they cannot be
re-entered. A figure that matters is re-taken rather than argued from.

**The gap closes forwards.** `provenance.run_fields()` carries the
revision, the track and the image's compiler and layout onto every row
a tool writes now, and `tools/container_report.py` and the flash log
record their own. A file whose rows have none is from before its tool
did.

## One home for a row's conditions

**`provenance.conditions()` is where every field a row carries comes
from**, since 2026-09-20. Before that there were three homes -
`collect()` for the full set, `run_fields()` for the seven per-row
fields, and `via` on the measurement dataclasses - and at the call
sites 32 tools used the second, 11 the first, and two used both: two
authors independently resolved "which one" by taking both, and the
row looked complete either way. A convention that does not say which
entry point to use is not a convention. `collect()` and `run_fields()`
remain as names for one release and return the same dict; then they go.

What a row carries, beyond what the old names gave it:

| field | what it answers |
|---|---|
| `checkout`, `checkout_fs` | which tree, on which filesystem. `windows-desk`'s drvfs-against-ext4 figures - a 4x `cppcheck` difference, a 3.5x fuzz-execution difference - were comparable only because they were labelled by hand in issue comments, for a bench that ran two checkouts for weeks. Read from the mount table where there is one; null where there is not, never a guess |
| `board_serial` | which Due. The programming port's USB serial - the 16U2's per-unit string - read from the descriptor without opening a port. Not the native port's `B-01`, which the firmware reports identically on every board of a track and so names the track, not the board. Null with no programming port; a list when a bench has two boards attached |
| `suite_context` | the test that was running, when one was |
| `tool` | which tool, at which revision, wrote the row |
| `via` | which instrument took the counters, as before |
| `uptime_ms` | present only when a caller read it over the command port, so it can never be required |

**The guard is scoped to standing tools by a rule, not a list.** Every
tool under `tools/` that writes rows under `records/` must reach
`conditions()`, and the set is taken from the tree - except tools
named for an issue, `issue<N>` anywhere in the name. Those are one-shot
experiment scripts for closed investigations whose rows will not be
written again, and holding them to a new call would mean editing
frozen scripts to keep a guard green, which is how a guard becomes
expensive and eventually acquires a `-k`. A one-shot that is re-run is
re-run with what its tool recorded; a standing tool records everything.

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
