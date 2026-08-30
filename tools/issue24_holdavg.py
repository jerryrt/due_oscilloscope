#!/usr/bin/env python3
"""The host path read without discarding a phase, at any hold.

issue24_hold.py decimates - it takes one sample per DAC update at a
chosen offset - and that is what made the ratio axis readable at all.
But decimation cannot see a site that lands on a discarded phase, and at
a hold of 2 a comb of 21 ADC conversions puts every other site exactly
there: 21 is odd, so conversion 21 is on offset 1 and conversion 42 on
offset 0.

That matters because the two candidate units predict different things
for a reader that discards nothing:

    hold 2, comb of 21 ADC conversions -> sites at updates 0, 10.5, 21,
            31.5 ... which a non-discarding reader shows as ALTERNATING
            gaps of 10 and 11
    hold 2, comb of 21 DAC updates     -> gaps of 21

The internal path already answers this, because pair_fold discards
nothing and gen NORMAL is itself a hold of 2: over 243 channel-captures
the census is 21 x358, 11 x5, 10 x1. This asks the same question of the
host path, where windows-desk's ratio-3 arm reads 21 conversions.

**Averaging, not differencing.** Every sample of a hold contributes to
its own update, so no phase is discarded and no level is cancelled - the
sawtooth survives, which is fine, because masked_sites subtracts each
bin's neighbours and was built for a waveform underneath. Differencing
was the wrong tool here twice (6d4a979, 5847c7d); averaging is what the
host reader actually wants.

A separate file from issue24_hold.py on purpose - windows-desk is
working in that one.

    .venv/bin/python tools/issue24_holdavg.py -n 6 --holds 1,2,3
"""
import argparse
import collections
import json
import os
import statistics
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "host"))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import measure                       # noqa: E402
from issue24_fold import masked_sites  # noqa: E402

# The ADC's RC, so a hold can be exact. Rates come from RC on this
# device, not from Hz - 66,667 Hz is not a divider but RC 585 is exactly
# three times RC 195, and that is how ratio 3 is settable at all.
ADC_RC = 195


def group_average(vals, hold, period):
    """One value per DAC update, using every sample of the hold.

    The alignment is chosen the way pair_fold chooses its parity: by
    whichever grouping makes the samples within a group most alike,
    because a slice trimmed at a settle time lands anywhere in the group
    and a misaligned grouping averages across a DAC step.
    """
    best = None
    for off in range(hold):
        n = (len(vals) - off) // hold
        if n < 4 * period:
            continue
        spread = statistics.median(
            [max(vals[off + k * hold:off + (k + 1) * hold])
             - min(vals[off + k * hold:off + (k + 1) * hold])
             for k in range(0, min(n, 4000))])
        if best is None or spread < best[0]:
            avg = [sum(vals[off + k * hold:off + (k + 1) * hold]) / hold
                   for k in range(n)]
            best = (spread, off, avg)
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--runs", type=int, default=6)
    ap.add_argument("-s", "--seconds", type=float, default=12.0)
    ap.add_argument("--holds", default="1,2,3")
    ap.add_argument("--adc-hz", type=int, default=200000)
    ap.add_argument("--step", type=int, default=measure.RAMP_STEP)
    ap.add_argument("--bench", default=os.environ.get("DUE_BENCH", "macos"))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    period = 4096 // args.step
    holds = [int(x) for x in args.holds.split(",")]
    board = measure.Board(settle=3.0)
    rows = []
    try:
        board.stop()
        board.drain_console(0.5)
        for i in range(1, args.runs + 1):
            for hold in holds:
                # RC scales exactly; Hz would not.
                dac = (39_000_000 // (ADC_RC * hold))
                res = measure.run_loop(board, dac_sps=dac,
                                       adc_hz=args.adc_hz, channels=2,
                                       ramp=args.step, seconds=args.seconds)
                ps = res.stream
                vals = ps.series.get(measure.CH_A0) or []
                start = ps._index_at(measure.CH_A0, measure.SETTLE_US)
                got = group_average(list(vals[start:]), hold, period)
                if not got:
                    print(f"run {i} hold {hold}: short", flush=True)
                    continue
                spread, off, avg = got
                found = masked_sites(avg, period)
                sites = sorted(s[0] for s in (found[0] if found else []))
                gaps = collections.Counter(sites[k + 1] - sites[k]
                                           for k in range(len(sites) - 1))
                row = {"run": i, "t": time.strftime("%Y-%m-%dT%H:%M:%S"),
                       "bench": args.bench, "hold": hold, "dac_sps": dac,
                       "adc_hz": args.adc_hz, "period": period,
                       "group_spread": round(spread, 2), "align": off,
                       "n_sites": len(sites),
                       "gaps": dict(gaps.most_common(6)),
                       "sites": sites[:24]}
                rows.append(row)
                print(f"run {i} hold {hold} (dac {dac}): sites "
                      f"{len(sites):3d} spread {spread:5.1f}  gaps "
                      f"{dict(gaps.most_common(4))}", flush=True)
                board.stop()
                board.drain_console(0.3)
    finally:
        try:
            board.stop()
        finally:
            board.close()

    print("\ngap census per hold, non-decimating reader:")
    for h in holds:
        tot = collections.Counter()
        for r in rows:
            if r["hold"] == h:
                tot.update(r["gaps"])
        print(f"  hold {h}: {dict(tot.most_common(6))}")
    print("\n  hold 2 showing 10s and 11s -> the comb counts ADC conversions")
    print("  hold 2 showing 21s          -> it counts DAC updates")
    if args.out:
        with open(args.out, "a") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
        print(f"wrote {len(rows)} rows to {args.out}")


if __name__ == "__main__":
    main()
