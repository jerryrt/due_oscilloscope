#!/usr/bin/env python3
"""Is the 15/16 rate specific to RC 32, or does every rate have one?

At RC 32 the DACC intermittently converts at **exactly 15/16** of the
rate it was programmed for. Measured entirely device-side, so no host
clock is involved:

    run_us    ~3,003,000 us in BOTH modes - the same window
    consumed   7,150 buffers normally, 6,703 and 6,702 in the two
               affected runs.  6702/7150 = 0.93748
    underruns  0 in every run, affected ones included

Zero underruns is what makes this the converter and not the host. If the
host had merely discarded 6% of the stream, a ring clocked at the
programmed rate would drain by ~76,000 samples/s - 445 buffers over 3 s
against a 32-slot ring - and starve loudly. It did not, so the ring was
being emptied more slowly, which only the timer can do.

`tests/test_integrity.py` already carries OVERSUPPLIED = {44, 39} with
the comment "feeding a converter that runs slow", and CLAUDE.md records
those two at 1.6% slow on Windows as well. That is a different number
from 6.25%, and it is *persistent* where this is intermittent, so the
two are not obviously the same effect.

This sweeps the ladder and reports the device-side ratio per run, so
the question "does every rate have a slow mode, and is its ratio a
round binary fraction too" is answered by a table rather than by
argument. 15/16 is exact enough to be a divider rather than a drift.

**`nearest_fraction` is a hint, not a reading.** It is
`Fraction.limit_denominator(64)` applied to a *measured* ratio, so it
fits the noise as readily as the signal: RC 39 comes back as 42/43 at
limit 64 and 83/85 at limit 128, and neither is a fact about the device.
Only RC 32's 15/16 survives being checked properly - its seven events
have sd 0.000049 and sit within 1e-4 of the fraction. For every other
rate, **read the ratio and compare it against candidate fractions
yourself**; do not quote this column.

    python3 tools/issue47_ratio.py --reps 8
"""
import argparse, json, os, platform, statistics, sys, pathlib
from fractions import Fraction
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "host"))
import measure

PLAY_BUF_SAMPLES = 512          # drivers/play.h - `consumed` is buffers


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reps", type=int, default=8)
    ap.add_argument("--rcs", type=int, nargs="+", default=[28, 32, 39, 44, 56])
    ap.add_argument("--seconds", type=float, default=3.0)
    ap.add_argument("--bench", default=os.environ.get("DUE_BENCH"),
                    help="which bench this is; defaults to $DUE_BENCH")
    ap.add_argument("--out", default=None,
                    help="defaults to records/issue47-ratio-<bench>.jsonl")
    a = ap.parse_args()

    # The bench and host are read, not hard-coded. This tool shipped
    # with bench="macos" and host="macOS 12.6" written into every row
    # and a matching default filename, so running it on windows-desk
    # appended twelve Windows rows to mac-bench's record under
    # mac-bench's label - which is the one thing CLAUDE.md says a figure
    # must never lose. Caught and reverted, and the shape fixed here so
    # the next bench cannot repeat it.
    bench = a.bench or platform.node() or "unknown-bench"
    host = f"{platform.system()} {platform.release()}"
    out = a.out or f"records/issue47-ratio-{bench}.jsonl"


    board = measure.Board(settle=3.0)
    rows = []
    for rc in a.rcs:
        hz = measure.hz_for(rc)
        print(f"\n=== RC {rc}: nominal {hz:,} sps ===")
        ratios = []
        for i in range(1, a.reps + 1):
            r = measure.run_play(board, dac_sps=hz, seconds=a.seconds,
                                 drain_s=1.5)
            if r.play.consumed is None:
                # Objective 0c: close() wedges, measure.close_native()
                # releases it with a software detach, and the native
                # port then RE-ENUMERATES under a new path. The Board
                # holds the old one, so every later run reports "no
                # counters" - not a device fault and not a rate
                # property, but it silently truncated two sweeps here
                # before it was recognised. Rediscover and retry once.
                print("    (no counters - re-discovering ports after a "
                      "0c detach, then retrying this run)")
                board = measure.Board(settle=4.0)
                r = measure.run_play(board, dac_sps=hz, seconds=a.seconds,
                                     drain_s=1.5)
            cons = r.play.consumed
            us = r.play.raw.get("runus")
            if not us or not cons:
                print(f"  run {i}: no counters"); continue
            dev = cons * PLAY_BUF_SAMPLES / (us / 1e6)
            ratio = dev / hz
            ratios.append(ratio)
            fr = Fraction(ratio).limit_denominator(64)
            d = int(r.host_deficit)
            rows.append(dict(bench=bench, host=host, track="b",
                             issue=47, test="device-rate-ratio", rc=rc,
                             run=i, dac_sps=hz, seconds=a.seconds,
                             consumed_bufs=cons, run_us=us,
                             device_sps=round(dev, 1), ratio=round(ratio, 6),
                             nearest_fraction=f"{fr.numerator}/{fr.denominator}",
                             fraction_is_a_hint=True,
                             host_deficit_bytes=d,
                             pct_lost=round(100 * d / r.host_tx_bytes, 3)
                                      if r.host_tx_bytes else None,
                             underruns=r.play.underruns))
            print(f"  run {i}: device {dev:>10,.0f} sps   ratio {ratio:.5f} "
                  f"(~{fr})   lost {d:>8,} B   und {r.play.underruns}")
        # Report the MEASURED quantity first. An earlier version led with
        # a count of runs below 0.99, and that threshold - picked to
        # separate an obvious 6% effect at RC 32 - hid a real 0.79%
        # deficit at RC 30, 31 and 49 for an afternoon. The median was
        # printed on the same line and read past. A derived count is a
        # convenience; the ratio is the result.
        if ratios:
            med = statistics.median(ratios)
            print(f"  -> MEDIAN RATIO {med:.5f}  ({100 * (1 - med):+.2f}% "
                  f"against nominal)")
            if med < 0.999:
                print(f"     that is a real deficit at this rate, whatever "
                      f"the count below says")
            slow = [x for x in ratios if x < 0.99]
            print(f"  -> {len(slow)}/{len(ratios)} slow; "
                  f"median ratio {statistics.median(ratios):.5f}"
                  + (f"; median slow ratio {statistics.median(slow):.5f} "
                     f"(~{Fraction(statistics.median(slow)).limit_denominator(64)})"
                     if slow else ""))

    with open(out, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    print(f"\nwrote {len(rows)} rows to {out}")


if __name__ == "__main__":
    main()
