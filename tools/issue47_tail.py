#!/usr/bin/env python3
"""Is the ~450 kB deficit a loss, or a tail?

The 30-rep co-occurrence arm turned up a bimodal deficit at RC 32:
either 0-896 B, or about 450,000 B, with nothing between. 450 kB is 6%
of a 3 s feed, and **underruns are 0 in every one of those runs** - so
the DAC ring never starved, which a 6% loss spread through the stream
could not manage. That puts the missing bytes at a boundary rather than
through the middle.

CLAUDE.md's cheap question decides it, and it is the same one that
settled objective 0i in ten minutes after months on the wrong suspect:

    is the count proportional to how long you ran?

    a loss rate      450 kB at 3 s -> ~1.35 MB at 9 s
    a fixed tail     450 kB at 3 s ->  ~450 kB at 9 s

Three durations, several reps each, everything else held. Nothing here
is new instrumentation - it is the existing deficit read at three
window lengths.

    python3 tools/issue47_tail.py --reps 6
"""
import argparse, json, statistics, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "host"))
import measure


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reps", type=int, default=6)
    ap.add_argument("--rc", type=int, default=32)
    ap.add_argument("--seconds", type=float, nargs="+", default=[1.0, 3.0, 9.0])
    ap.add_argument("--drain", type=float, default=1.5)
    ap.add_argument("--out", default="records/issue47-tail-macos.jsonl")
    a = ap.parse_args()

    hz = measure.hz_for(a.rc)
    board = measure.Board(settle=3.0)
    rows = []
    print(f"RC {a.rc} = {hz} sps, drain {a.drain}s\n")
    for secs in a.seconds:
        big = []
        for i in range(1, a.reps + 1):
            r = measure.run_play(board, dac_sps=hz, seconds=secs,
                                 drain_s=a.drain)
            d = r.host_deficit
            row = dict(bench="macos", host="macOS 12.6", track="b", issue=47,
                       test="deficit-vs-duration", run=i, rc=a.rc,
                       dac_sps=hz, seconds=secs, drain_s=a.drain,
                       host_tx_bytes=r.host_tx_bytes,
                       dev_bytes_in=r.play.bytes_in,
                       host_deficit_bytes=int(d),
                       pct=round(100 * d / r.host_tx_bytes, 3)
                           if r.host_tx_bytes else None,
                       underruns=r.play.underruns)
            rows.append(row)
            big.append(d)
            print(f"  {secs:4.1f}s run {i}: tx {r.host_tx_bytes:9,d}  "
                  f"deficit {d:7,d} B ({row['pct']}%)  und {r.play.underruns}")
        nz = [x for x in big if x > 100000]
        print(f"  -> {secs}s: {len(nz)}/{len(big)} large; "
              f"median large {statistics.median(nz) if nz else 0:,.0f} B\n")

    print("  VERDICT: a loss rate scales the large deficit with duration; "
          "a fixed tail does not.")
    with open(a.out, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    print(f"wrote {len(rows)} rows to {a.out}")


if __name__ == "__main__":
    main()
