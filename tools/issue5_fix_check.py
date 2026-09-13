#!/usr/bin/env python3
"""Two readings the refresh-policy fix is judged by, on the board as it is.

`droop`: with the stream as the only refresh, does a held level decay
between rewrites? All-DC table, A0 on DAC0, at 5, 20 and 200 ksps -
the mean within-hold pair difference (s0 - s1) is what a decaying level
looks like, and the sd is the noise the refresh transient adds or does
not. `steps`: what `level_census` still counts once nothing is locked
to the table wrap - the scattered first-of-hold population, with its
count, its largest step, the fold's z and the table phase of each event.

    sg dialout -c '.venv/bin/python tools/issue5_fix_check.py droop --arm fix'
    sg dialout -c '.venv/bin/python tools/issue5_fix_check.py steps --arm fix'

Rows append to records/issue5-fix-<reading>-<bench>.jsonl with the
image's provenance, so an arm is attributable to the constant it was
built with.
"""
import argparse
import json
import os
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "host"))
import measure      # noqa: E402
import provenance   # noqa: E402


def capture(board, preset, seconds):
    res = measure.run_capture(board, preset=preset, seconds=seconds)
    ps = res.stream
    vals = ps.series.get(measure.CH_A0) or []
    start = ps._index_at(measure.CH_A0, measure.SETTLE_US)
    return vals[start:]


def droop(board, args, prov, out):
    board.cmd("=3N")            # all-DC: nothing swings anywhere
    board.drain_console(0.5)
    try:
        for hz in (5000, 20000, 200000):
            for run in range(1, args.runs + 1):
                v = capture(board, f"={hz},{hz}M", args.seconds)
                if len(v) < 100:
                    print(f"{hz}: no samples")
                    continue
                pairs = [v[i] - v[i + 1] for i in range(0, len(v) - 1, 2)]
                row = {"reading": "droop", "arm": args.arm, "hz": hz, "run": run,
                       "n": len(v), "mean": round(statistics.fmean(v), 2),
                       "sd": round(statistics.pstdev(v), 3),
                       "pair_mean": round(statistics.fmean(pairs), 3),
                       "pair_sd": round(statistics.pstdev(pairs), 3), **prov}
                out.write(json.dumps(row) + "\n")
                print(f"{args.arm} {hz:6d} Hz run {run}: mean {row['mean']:8.2f} "
                      f"sd {row['sd']:6.3f} pair(s0-s1) mean {row['pair_mean']:+7.3f} "
                      f"sd {row['pair_sd']:6.3f}", flush=True)
    finally:
        board.cmd("=0N")
        board.drain_console(0.5)


def steps(board, args, prov, out):
    for run in range(1, args.runs + 1):
        v = capture(board, args.preset, args.seconds)
        c = measure.level_census(v)
        fold = measure.pair_fold(v)
        idx = [i for i in range(len(v) - 1)
               if abs(v[i + 1] - v[i]) > measure.STEP_SPLICE_CODES]
        events = [w for k, w in enumerate(idx) if k == 0 or w - idx[k - 1] > 4]
        row = {"reading": "steps", "arm": args.arm, "preset": args.preset,
               "run": run, "n": len(v), "census_count": c["count"],
               "max_step": c["max_step"], "periodic": c["periodic"],
               "events": len(events), "hold_ok": bool(fold.get("hold_ok")),
               "fold_z": round(fold["z"], 1), "fold_peak": round(fold["peak"], 1),
               "phases": [i % 512 for i in events][:200], **prov}
        out.write(json.dumps(row) + "\n")
        print(f"{args.arm} run {run}: census {c['count']} (max {c['max_step']:.0f}, "
              f"periodic {c['periodic']}), events {len(events)}, fold z "
              f"{fold['z']:.1f} peak {fold['peak']:+.1f}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("reading", choices=("droop", "steps"))
    ap.add_argument("--arm", required=True, help="fix, ctl, r2, trackA-fix ...")
    ap.add_argument("--bench", default=os.environ.get("DUE_BENCH", "linux-x1"))
    ap.add_argument("--preset", default="=200000,200000M")
    ap.add_argument("-n", "--runs", type=int, default=3)
    ap.add_argument("-s", "--seconds", type=float, default=3.0)
    args = ap.parse_args()
    path = os.path.join(ROOT, "records",
                        f"issue5-fix-{args.reading}-{args.bench}.jsonl")
    board = measure.Board(settle=3.0)
    try:
        board.stop()
        board.drain_console(0.5)
        prov = provenance.run_fields(board)
        print("provenance: " + ", ".join(f"{k}={v}" for k, v in prov.items()))
        with open(path, "a", encoding="utf-8") as out:
            (droop if args.reading == "droop" else steps)(board, args, prov, out)
    finally:
        board.stop()
        board.close()
    print(f"rows -> {path}")


if __name__ == "__main__":
    main()
