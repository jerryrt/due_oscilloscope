#!/usr/bin/env python3
"""#47: does the short feed co-occur with the byte deficit?

windows-desk ran this and could not answer it, for a reason that is
itself the finding: on Windows the deficit is 0 in **every** run,
including their one short-feed run. A variable with no variance cannot
correlate with anything, so their arm is a constant rather than a null.

But it is not wasted, because it settles the direction that needs no
correlation at all: their short feed happened on a host that discards
nothing, so **the shortfall does not require the discard**. Whatever
puts the feed into its low mode is present with the deficit identically
zero.

What remains is the other direction - on a host where the deficit IS
non-zero, does it land in the short runs? That host is this one. RC 32
carries the RESIDUAL xfail (384 B, 3 chunks) and it is the same rate
#47 is about, so the two quantities vary together here and nowhere else.

Both come out of ONE `run_play`, so this is co-occurrence within a run
rather than a comparison across two tests - the same discipline
windows-desk used and named.

**`--bench` is not cosmetic.** windows-desk ran a sibling of this tool
with `bench="macos"` baked in and appended twelve Windows rows to the
macOS record file under the macOS label. On a cross-bench question that
is the one error that makes data actively misleading rather than merely
absent - so bench comes from `--bench`, then `$DUE_BENCH`, then the
hostname, and the output file is named after it.

    python3 tools/issue47_cooccur.py --reps 24
"""
import argparse, json, os, platform, statistics, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "host"))
import measure
import provenance


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reps", type=int, default=24)
    ap.add_argument("--rc", type=int, default=32)
    ap.add_argument("--seconds", type=float, default=3.0)
    ap.add_argument("--bench", default=os.environ.get("DUE_BENCH"),
                    help="which bench this is; defaults to $DUE_BENCH")
    ap.add_argument("--out", default=None,
                    help="defaults to records/issue47-cooccurrence-<bench>.jsonl")
    a = ap.parse_args()

    bench = a.bench or platform.node() or "unknown-bench"
    host = f"{platform.system()} {platform.release()}"
    out_path = a.out or f"records/issue47-cooccurrence-{bench}.jsonl"

    hz = measure.hz_for(a.rc)
    want = hz * 2.0
    board = measure.Board(settle=3.0)
    # What the board actually is, and what produced it (issue #53).
    prov = provenance.run_fields(board)
    rows = []
    print(f"RC {a.rc} = {hz} sps, threshold {0.95*want:,.0f} B/s\n")
    for i in range(1, a.reps + 1):
        # drain_s is NOT optional here. `host_deficit`'s own docstring
        # says it is only meaningful on a run drained long enough, and
        # CLAUDE.md says 55-450 KB sits in the CDC driver below the tty
        # layer. Run without it and 5 runs in 30 report a ~453,000 B
        # 'deficit' that is the pipeline, not a loss - a whole number
        # of 128-byte chunks, so even the test suite's chunk check
        # would wave it through. I took exactly that reading before
        # adding this line.
        r = measure.run_play(board, dac_sps=hz, seconds=a.seconds,
                             drain_s=1.5)
        assert r.drained, "undrained: the deficit column would be pipeline"
        fed = r.host_tx_bytes / r.elapsed_s
        d = r.host_deficit
        short = fed < 0.95 * want
        row = dict(bench=bench, host=host, **prov, issue=47,
                   test="short-feed-vs-byte-deficit-one-run", run=i,
                   rc=a.rc, dac_sps=hz, seconds=a.seconds,
                   feed_target_mbs=want / 1e6, fed_mbs=round(fed / 1e6, 4),
                   pct_of_target=round(100 * fed / want, 1),
                   feed_short=bool(short), host_deficit_bytes=int(d),
                   underruns=r.play.underruns, drained=True)
        rows.append(row)
        print(f"  run {i:2d}: {100*fed/want:5.1f}% of target  "
              f"{'SHORT' if short else '  ok '}  deficit {d:6d} B  "
              f"underruns {r.play.underruns}")

    sh = [r for r in rows if r["feed_short"]]
    ok = [r for r in rows if not r["feed_short"]]
    dall = [r["host_deficit_bytes"] for r in rows]
    print(f"\n  {len(sh)} short of {len(rows)}; "
          f"deficit range {min(dall)}-{max(dall)} B, "
          f"{sum(1 for x in dall if x)} runs non-zero")
    if not any(dall):
        print("  !! deficit is 0 in every run - this arm is a CONSTANT here "
              "too, and cannot answer the question either")
    elif sh and ok:
        ms = statistics.fmean(r["host_deficit_bytes"] for r in sh)
        mo = statistics.fmean(r["host_deficit_bytes"] for r in ok)
        print(f"  mean deficit: short {ms:.1f} B   ok {mo:.1f} B")
    elif not sh:
        print("  !! no short run occurred - the intermittency did not "
              "reproduce in this many reps; no co-occurrence readable")

    with open(out_path, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    print(f"\nwrote {len(rows)} rows to {out_path}")


if __name__ == "__main__":
    main()
