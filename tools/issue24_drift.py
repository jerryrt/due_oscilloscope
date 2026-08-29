#!/usr/bin/env python3
"""Are the sites fixed, or is one event marching through the fold?

Every reading on issues #5 and #24 folds a whole capture, and a fold is
an aggregate. It cannot tell "several fixed positions" from "one
position moving", because both put weight in several bins - and this
issue's history is a list of aggregates that proposed findings the
underlying profile then withdrew.

The arithmetic that prompted this. One capture's comb ran 4, 25, ...,
256, then jumped 71 to 327, 348, ..., 495: spacing 21 throughout except
one slip of 8. And **512 mod 21 is 8**. That is exactly what a single
event advancing 21 samples per wrap looks like when the wrap is 512
long and it has gone round once - not two combs, one trajectory.

So: split one capture into segments, fold each separately, and look at
where the sites are in each. Fixed sites hold their bins segment to
segment. A marching event advances by a constant step, and the step is
the thing worth knowing.

The cost is sensitivity - each segment has 1/K of the wraps, so the
per-bin noise floor rises by sqrt(K) - which is why this is a
complement to the whole-run fold and not a replacement for it. K is
chosen so a segment still holds enough wraps to see a site that the
whole-run fold already found.

    .venv/bin/python tools/issue24_drift.py -n 4 --segments 8
"""
import argparse
import json
import os
import statistics
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "host"))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import measure                      # noqa: E402
from issue24_fold import masked_sites   # noqa: E402


def step_between(a, b, period):
    """Smallest signed advance taking site set `a` to site set `b`.

    Scored by how many sites line up, not by any one of them, so a site
    that drops out below threshold cannot set the answer. Returns
    (step, matched, of) - and `matched` is what says whether to believe
    it.
    """
    if not a or not b:
        return None, 0, 0
    best = (None, -1)
    for s in range(period):
        hit = sum(1 for x in a if ((x + s) % period) in b)
        if hit > best[1]:
            best = (s, hit)
    step = best[0]
    if step > period // 2:
        step -= period
    return step, best[1], len(a)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--runs", type=int, default=4)
    ap.add_argument("-s", "--seconds", type=float, default=3.0)
    ap.add_argument("--segments", type=int, default=8)
    ap.add_argument("--dac-sps", type=int, default=200000)
    ap.add_argument("--adc-hz", type=int, default=200000)
    ap.add_argument("--step", type=int, default=measure.RAMP_STEP)
    ap.add_argument("--bench", default=os.environ.get("DUE_BENCH", "macos"))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    period = 4096 // args.step
    board = measure.Board(settle=3.0)
    rows = []
    try:
        board.stop()
        board.drain_console(0.5)
        for i in range(1, args.runs + 1):
            res = measure.run_loop(board, dac_sps=args.dac_sps,
                                   adc_hz=args.adc_hz, channels=2,
                                   ramp=args.step, seconds=args.seconds)
            ps = res.stream
            vals = ps.series.get(measure.CH_A0) or []
            start = ps._index_at(measure.CH_A0, measure.SETTLE_US)
            tail = list(vals[start:])

            whole = masked_sites(tail, period)
            wbins = sorted(s[0] for s in (whole[0] if whole else []))

            # Segment on whole wraps, so every segment shares the fold's
            # phase and the bins mean the same thing in each.
            wraps = len(tail) // period
            per = max(1, wraps // args.segments)
            segs = []
            for k in range(args.segments):
                lo, hi = k * per * period, (k + 1) * per * period
                if hi > len(tail):
                    break
                got = masked_sites(tail[lo:hi], period)
                segs.append(sorted(s[0] for s in (got[0] if got else [])))

            steps = []
            for k in range(len(segs) - 1):
                st, hit, of = step_between(segs[k], segs[k + 1], period)
                steps.append({"from": k, "step": st, "matched": hit,
                              "of": of})

            row = {"run": i, "t": time.strftime("%Y-%m-%dT%H:%M:%S"),
                   "bench": args.bench, "period": period,
                   "wraps": wraps, "wraps_per_segment": per,
                   "whole_sites": wbins,
                   "segment_sites": segs, "steps": steps}
            rows.append(row)
            print(f"run {i}: {wraps} wraps, {per} per segment, "
                  f"whole-run sites {len(wbins)}", flush=True)
            for k, s in enumerate(segs):
                print(f"   seg {k}: {len(s):3d} sites  "
                      + (", ".join(str(x) for x in s[:12])
                         + (" ..." if len(s) > 12 else "")), flush=True)
            good = [d for d in steps if d["of"] and d["matched"] >= 2]
            if good:
                print("   step segment-to-segment: "
                      + ", ".join(f"{d['step']}({d['matched']}/{d['of']})"
                                  for d in good), flush=True)
            board.stop()
            board.drain_console(0.3)
    finally:
        try:
            board.stop()
        finally:
            board.close()

    allsteps = [d["step"] for r in rows for d in r["steps"]
                if d["of"] and d["matched"] >= 2 and d["step"] is not None]
    if allsteps:
        c = {}
        for s in allsteps:
            c[s] = c.get(s, 0) + 1
        print("\nsegment-to-segment steps, most common first:")
        for s, n in sorted(c.items(), key=lambda t: -t[1])[:8]:
            print(f"   step {s:+5d}  x{n}")
        print(f"median {statistics.median(allsteps):+.1f} over "
              f"{len(allsteps)} transitions")
    else:
        print("\nno segment pair had enough matched sites to fit a step")
    if args.out:
        with open(args.out, "a") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
        print(f"wrote {len(rows)} rows to {args.out}")


if __name__ == "__main__":
    main()
