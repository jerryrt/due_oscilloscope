#!/usr/bin/env python3
"""Does removing the DAC1 write change what the comb counts?

6ac6c8a leaves the host and internal paths disagreeing: the host's comb
is 21 A0 conversions and the internal path's is 42. The one structural
difference is what the DACC does BETWEEN two A0 conversions of one DAC0
level - on the internal path it writes DAC1 in TAG mode, on the host
path it does nothing.

SOLO removes exactly that. `=3J` tags every table entry DAC0, so the
converter updates DAC0 on every trigger instead of every other one, the
table holds GEN_TABLE_LEN points of waveform, and one A0 conversion
falls per DAC0 update - structurally the host path, still with no host
in the DAC path.

The comparison, both in A0 conversions:

    NORMAL   comb = 42   (21 pair_fold bins, 2 conversions each)
    SOLO     comb = 21   -> the DAC1 write was the difference
    SOLO     comb = 42   -> it was not, and the paths differ elsewhere

pair_fold cannot read SOLO: it needs a level held for two conversions
and SOLO holds none, so hold_ok goes false by construction. The raw A0
series is folded at GEN_TABLE_LEN instead, with masked_sites, whose
neighbour residual is built for a waveform underneath - here a sine
rather than a sawtooth, and the mask lands on the sine's steepest bin
rather than a wrap, which costs five bins of coverage and nothing else.

Restores the sync on exit; every other instrument on this issue assumes
the default.

    .venv/bin/python tools/issue5_solo.py -n 6
"""
import argparse
import collections
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "host"))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import measure                       # noqa: E402
from issue24_fold import masked_sites  # noqa: E402
from issue24_holdavg import group_average  # noqa: E402


def read(vals, start, period, hold):
    """Sites in one unit: A0 conversions, whichever arm.

    The first attempt folded the raw A0 series at GEN_TABLE_LEN for both
    arms, on the theory that a bin is one A0 conversion either way. It
    is - but CYCLE holds each DAC0 level for two conversions, so the raw
    profile carries the STAIRCASE, and masked_sites' neighbour residual
    removes a smooth waveform and not an alternating one. Measured: MAD
    17.5 on CYCLE against 0.49 on SOLO, 35x, and no sites found at all.
    That is why pair_fold exists.

    So the hold is averaged out first, exactly as issue24_holdavg does
    on the host path, and the gap is multiplied back by the hold to
    return to A0 conversions. Same reader, same unit, the grouping
    forced by the hardware and the conversion made explicit.
    """
    tail = list(vals[start:])
    bins = period // hold
    if len(tail) < 8 * period:
        return None
    if hold > 1:
        got = group_average(tail, hold, bins)
        if not got:
            return None
        tail = got[2]
    got = masked_sites(tail, bins)
    sites = sorted(s[0] for s in (got[0] if got else []))
    gaps = collections.Counter((sites[k + 1] - sites[k]) * hold
                               for k in range(len(sites) - 1))
    return {"n_sites": len(sites), "sites": sites[:24], "hold": hold,
            "gaps": dict(gaps.most_common(6)),
            "mad": round(got[1], 4) if got else None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--runs", type=int, default=6)
    ap.add_argument("-s", "--seconds", type=float, default=12.0)
    ap.add_argument("--arms", default="solo,cycle",
                    help="interleaved, because the configuration redraws "
                         "every capture and blocked arms cannot separate "
                         "an arm effect from the weather")
    ap.add_argument("--bench", default=os.environ.get("DUE_BENCH", "macos"))
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    board = measure.Board(settle=3.0)
    rows = []
    try:
        board.stop()
        board.drain_console(0.5)
        for i in range(1, args.runs + 1):
            arm = arms[(i - 1) % len(arms)]
            measure.set_sync(board, arm)
            res = measure.run_capture(board, preset="M", seconds=args.seconds)
            ps = res.stream
            vals = ps.series.get(measure.CH_A0) or []
            start = ps._index_at(measure.CH_A0, measure.SETTLE_US)
            # SOLO updates DAC0 every trigger, CYCLE every other one.
            out = read(vals, start, measure.GEN_TABLE_LEN,
                       1 if arm == "solo" else 2)
            if not out:
                print(f"run {i}: short capture", flush=True)
                continue
            row = {"run": i, "t": time.strftime("%Y-%m-%dT%H:%M:%S"),
                   "bench": args.bench, "arm": arm,
                   "fold": measure.GEN_TABLE_LEN, **out}
            rows.append(row)
            print(f"run {i:2d} {arm:5s}: sites {out['n_sites']:3d} "
                  f"mad {out['mad']}  gaps {out['gaps']}", flush=True)
            board.stop()
            board.drain_console(0.3)
    finally:
        try:
            measure.set_sync(board, "cycle")
            board.stop()
        finally:
            board.close()

    print("\ngap census per arm, fold bins = A0 conversions:")
    for a in arms:
        tot = collections.Counter()
        for r in rows:
            if r["arm"] == a:
                tot.update(r["gaps"])
        print(f"  {a:6s}: {dict(tot.most_common(6))}")
    print("\n  solo 21 vs cycle 42 -> the DAC1 write is the difference")
    print("  both the same       -> it is not; the paths differ elsewhere")
    if args.json:
        with open(args.json, "a") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
        print(f"wrote {len(rows)} rows to {args.json}")


if __name__ == "__main__":
    main()
