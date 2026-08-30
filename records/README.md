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
