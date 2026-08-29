#!/usr/bin/env python3
"""Which period does #24's artifact actually belong to?

#24 says "one sample per DAC table wrap", and every reading behind it
folded the host-fed capture at `4096 / RAMP_STEP`. At the default step
of 8 that period is **512 samples - which is exactly
`PLAY_BUF_SAMPLES`**, the playback DMA ring slot. So at the default
settings "once per table wrap" and "once per playback buffer" are the
same fold and have never been told apart.

This separates them the cheap way: one capture, folded twice - at the
ramp's own period and at 512 - with `RAMP_STEP` swept so the two
periods differ. Nothing about the board changes between the two folds,
so the comparison cannot be blamed on drift, warm-up or the draw.

  step 16 -> ramp period  256, half a playback buffer
  step  8 -> ramp period  512, exactly one (the default, and degenerate)
  step  4 -> ramp period 1024, two of them

Read the **spacing** rather than the absolute positions. The lattice of
21 is what has survived every reading on both benches, and a spacing
fixed in *samples* across three table lengths is a property of the
timing rather than of the table, while a spacing that scales with the
table is the opposite.

    .venv/Scripts/python.exe tools/issue24_period.py -n 4 \\
        --steps 16,8,4 --out records/issue24-period-windows.jsonl

Interleaved by step within one board session, because a sequential
block per step cannot separate the step from the weather - this
artifact's configuration drifts on tens-of-minutes scales and that has
manufactured an effect on this issue twice.
"""
import argparse
import json
import os
import statistics
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "host"))
import measure  # noqa: E402

PLAY_BUF_SAMPLES = 512          # drivers/play.h, quoted not guessed


def fold_at(tail, period):
    """Neighbour-residual fold at one period, wrap located and masked.

    Returns (sites, mad, wrap, n_per_bin) or None when the capture is
    too short for the period - which is the trap `pair_fold` has too:
    a fold over fewer than a few wraps returns something shaped like an
    answer.
    """
    if len(tail) < 4 * period:
        return None
    base = statistics.median(tail)
    sums = [0.0] * period
    counts = [0] * period
    for i, x in enumerate(tail):
        b = i % period
        sums[b] += x - base
        counts[b] += 1
    if min(counts) == 0:
        return None
    means = [sums[b] / counts[b] for b in range(period)]
    resid = [means[b] - (means[(b - 1) % period]
                         + means[(b + 1) % period]) / 2.0
             for b in range(period)]
    drops = [means[b] - means[(b - 1) % period] for b in range(period)]
    w = min(range(period), key=lambda b: drops[b])
    masked = {(w + k) % period for k in (-2, -1, 0, 1, 2)}
    keep = [b for b in range(period) if b not in masked]
    if len(keep) < 8:
        return None
    sites, mad = measure.fold_sites(resid, keep=keep, absorb=True)
    return sites, mad, w, min(counts)


def spacings(sites, period, limit=12):
    """Gaps between site positions, as the lattice test wants them read.

    Sorted by position rather than by magnitude, and taken only over the
    sites strong enough to be sites - a lattice claimed over the tail of
    a threshold is a lattice found in noise.
    """
    bs = sorted(b for b, _v, _z in sites[:limit])
    return [bs[i + 1] - bs[i] for i in range(len(bs) - 1)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--runs", type=int, default=4,
                    help="runs per step")
    ap.add_argument("-s", "--seconds", type=float, default=3.0)
    ap.add_argument("--steps", default="16,8,4")
    ap.add_argument("--dac-sps", type=int, default=200000)
    ap.add_argument("--bench", default=os.environ.get("DUE_BENCH", "macos"))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    steps = [int(s) for s in args.steps.split(",") if s.strip()]
    board = measure.Board(settle=3.0)
    rows = []
    try:
        board.stop()
        board.drain_console(0.5)
        for i in range(1, args.runs + 1):
            for step in steps:               # interleaved, not blocked
                ramp_period = 4096 // step
                res = measure.run_loop(board, dac_sps=args.dac_sps,
                                       adc_hz=200000, channels=2,
                                       ramp=step, seconds=args.seconds)
                ps = res.stream
                vals = ps.series.get(measure.CH_A0) or []
                start = ps._index_at(measure.CH_A0, measure.SETTLE_US)
                tail = list(vals[start:])
                row = {"run": i, "t": time.strftime("%Y-%m-%dT%H:%M:%S"),
                       "bench": args.bench, "ramp_step": step,
                       "ramp_period": ramp_period,
                       "play_buf": PLAY_BUF_SAMPLES,
                       "dac_sps": args.dac_sps,
                       "seq_gaps": ps.seq_gaps, "crc_bad": ps.crc_bad,
                       "under": res.play.underruns if res.play else None}
                for label, per in (("ramp", ramp_period),
                                   ("play", PLAY_BUF_SAMPLES)):
                    got = fold_at(tail, per)
                    if got is None:
                        row[label] = None
                        continue
                    sites, mad, w, n = got
                    row[label] = {
                        "period": per, "wrap": w, "mad": round(mad, 4),
                        "n_per_bin": n, "n_sites": len(sites),
                        "sites": [[b, round(v, 3), round(z, 1)]
                                  for b, v, z in sites[:12]],
                        "spacings": spacings(sites, per)}
                rows.append(row)
                r_, p_ = row.get("ramp"), row.get("play")
                print(f"run {i} step {step:2d} (ramp period {ramp_period:4d}"
                      f", play {PLAY_BUF_SAMPLES}):", flush=True)
                for label, d in (("ramp", r_), ("play", p_)):
                    if not d:
                        print(f"    {label:4s}: too short for the period")
                        continue
                    top = ", ".join(f"{b}:{v:+.1f}"
                                    for b, v, _z in d["sites"][:6])
                    print(f"    {label:4s} period {d['period']:4d} "
                          f"wrap={d['wrap']:4d} sites={d['n_sites']:3d} "
                          f"spacings={d['spacings'][:8]}  {top or '-'}",
                          flush=True)
                board.stop()
                board.drain_console(0.3)
    finally:
        try:
            board.stop()
        finally:
            board.close()

    print("\nspacing census - how often each gap appears, per step:")
    for step in steps:
        got = [r for r in rows if r["ramp_step"] == step and r.get("ramp")]
        tally = {}
        for r in got:
            for g in r["ramp"]["spacings"]:
                tally[g] = tally.get(g, 0) + 1
        top = sorted(tally.items(), key=lambda kv: -kv[1])[:6]
        print(f"  step {step:2d} (ramp period {4096 // step:4d}, "
              f"{len(got)} runs): {top}")

    if args.out:
        with open(args.out, "a") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
        print(f"\nwrote {len(rows)} rows to {args.out}")


if __name__ == "__main__":
    main()
