#!/usr/bin/env python3
"""Is the TAG interleave what makes the two paths disagree?

The host-fed path and the internal generator give different answers for
what the issue-24 comb counts, with readers that discard nothing on both
sides: 21 ADC conversions on the host path (6ac6c8a, confirmed on both
tracks by f2ceb31) and 21 DAC0 updates internally over 243
channel-captures.

One structural difference is left between them. `gen` NORMAL interleaves
DAC0 and DAC1, so the converter writes the other channel between two
captured samples of one DAC0 level; `build_ramp` tags every entry DAC0
and nothing happens in that gap.

So put the interleave on the host path. `build_ramp_tagged` alternates a
ramp on DAC0 with a constant on DAC1, which is gen NORMAL's structure
with the host's waveform, and everything else is held: same transport,
same instrument, same fold, same rates.

    plain, hold 2    gaps 10/11  -> counts ADC conversions
    tagged           gaps 10/11  -> the interleave is NOT the difference
    tagged           gaps 21     -> it IS, and the two paths are one
                                    phenomenon after all

Rates are chosen so the tagged arm reproduces the internal path exactly:
DACC at 200 kHz consumes two entries per DAC0 update, giving DAC0 at
100 kHz, and the ADC at 200 kHz gives two A0 samples per DAC0 update.
The plain arm runs DAC0 at 100 kHz directly for the same geometry.

    .venv/bin/python tools/issue24_taginterleave.py -n 6
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
import measure                        # noqa: E402
from issue24_fold import masked_sites   # noqa: E402
from issue24_holdavg import group_average  # noqa: E402


def read(vals, start, period):
    """One value per DAC0 update, then sites. Discards no phase."""
    tail = list(vals[start:])
    if len(tail) < 8 * period:
        return None
    got = group_average(tail, 2, period)
    if not got:
        return None
    spread, off, avg = got
    found = masked_sites(avg, period)
    bins = sorted(s[0] for s in (found[0] if found else []))
    gaps = collections.Counter(bins[k + 1] - bins[k]
                               for k in range(len(bins) - 1))
    return {"n_sites": len(bins), "sites": bins[:24],
            "gaps": dict(gaps.most_common(6)),
            "group_spread": round(spread, 2), "align": off,
            "mad": round(found[1], 4) if found else None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--runs", type=int, default=6)
    ap.add_argument("-s", "--seconds", type=float, default=12.0)
    ap.add_argument("--step", type=int, default=measure.RAMP_STEP)
    ap.add_argument("--bench", default=os.environ.get("DUE_BENCH", "macos"))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    period = 4096 // args.step          # DAC0 updates per wrap
    tagged, _ = measure.build_ramp_tagged(step=args.step)
    board = measure.Board(settle=3.0)
    rows = []
    try:
        board.stop()
        board.drain_console(0.5)
        for i in range(1, args.runs + 1):
            for arm in ("plain", "tagged"):
                if arm == "tagged":
                    res = measure.run_loop(board, dac_sps=200000,
                                           adc_hz=200000, channels=2,
                                           wave=tagged,
                                           seconds=args.seconds)
                else:
                    res = measure.run_loop(board, dac_sps=100000,
                                           adc_hz=200000, channels=2,
                                           ramp=args.step,
                                           seconds=args.seconds)
                ps = res.stream
                vals = ps.series.get(measure.CH_A0) or []
                start = ps._index_at(measure.CH_A0, measure.SETTLE_US)
                out = read(vals, start, period)
                if not out:
                    print(f"run {i} {arm}: short", flush=True)
                    continue
                row = {"run": i, "arm": arm, "bench": args.bench,
                       "t": time.strftime("%Y-%m-%dT%H:%M:%S"),
                       "period": period, **out}
                rows.append(row)
                print(f"run {i} {arm:6s}: sites {out['n_sites']:3d} "
                      f"spread {out['group_spread']:5.1f} "
                      f"mad {out['mad']}  gaps {out['gaps']}", flush=True)
                board.stop()
                board.drain_console(0.3)
    finally:
        try:
            board.stop()
        finally:
            board.close()

    print("\ngap census per arm, bins = DAC0 updates:")
    for a in ("plain", "tagged"):
        tot = collections.Counter()
        for r in rows:
            if r["arm"] == a:
                tot.update(r["gaps"])
        print(f"  {a:6s}: {dict(tot.most_common(6))}")
    print("\n  tagged shows 10s/11s -> the interleave is not the difference")
    print("  tagged shows 21s     -> it is, and the paths are one thing")
    if args.out:
        with open(args.out, "a") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
        print(f"wrote {len(rows)} rows to {args.out}")


if __name__ == "__main__":
    main()
