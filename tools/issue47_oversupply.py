#!/usr/bin/env python3
"""Is the RC 32 loss the host discarding, or the converter running slow?

The duration sweep settled that the large deficit is a *rate*: 145,664 B
at 1 s and 446,656 B at 3 s, a ratio of 3.07, at a near-constant 5.87 to
6.12% of what the host wrote. That rules out the startup burst and the
undrained tail, which were the two cheap explanations.

It leaves two that are not cheap, and they are told apart by the
device's own clock rather than by anything host-side:

  HOST DISCARD    the device wanted every byte and never saw some.
                  Its update rate matches the nominal rate, and the
                  missing bytes are simply gone - macOS's documented
                  behaviour, but an order of magnitude larger than the
                  0.45-0.85% on record.

  OVERSUPPLY      the DACC is converting slower than the rate asked
                  for, so the host writes more than the device can
                  take and the surplus is shed. The device's own
                  `consumed / run_us` then sits ~6% BELOW nominal, and
                  underruns stay at 0 because a ring that is over-fed
                  never starves.

`tests/test_integrity.py` already models the second for RC 44 and 39 -
the `OVERSUPPLIED` set, "feeding a converter that runs slow" - and
CLAUDE.md records those two running 1.6% slow on Windows as well, so
the effect is the device's and not a host artefact. RC 32 is in
`RESIDUAL` instead, on the strength of a 384 B loss. If its device rate
comes back ~6% low in exactly the runs that lose 6%, it belongs in both.

The discriminator is one number per run and needs no new firmware:

    device_sps = consumed / (run_us / 1e6)      vs      nominal

    python3 tools/issue47_oversupply.py --reps 12
"""
import argparse, json, statistics, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "host"))
import measure


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reps", type=int, default=12)
    ap.add_argument("--rc", type=int, default=32)
    ap.add_argument("--seconds", type=float, default=3.0)
    ap.add_argument("--out", default="records/issue47-oversupply-macos.jsonl")
    a = ap.parse_args()

    hz = measure.hz_for(a.rc)
    board = measure.Board(settle=3.0)
    rows = []
    print(f"RC {a.rc}: nominal {hz:,} sps\n")
    for i in range(1, a.reps + 1):
        r = measure.run_play(board, dac_sps=hz, seconds=a.seconds,
                             drain_s=1.5)
        d = int(r.host_deficit)
        cons = r.play.consumed
        us = r.play.raw.get("runus")
        dev = cons / (us / 1e6) if us else None
        pct_lost = 100 * d / r.host_tx_bytes if r.host_tx_bytes else 0.0
        pct_slow = 100 * (1 - dev / hz) if dev else None
        rows.append(dict(bench="macos", host="macOS 12.6", track="b", issue=47,
                         test="oversupply-vs-discard", run=i, rc=a.rc,
                         dac_sps=hz, seconds=a.seconds, drain_s=1.5,
                         host_tx_bytes=r.host_tx_bytes,
                         dev_bytes_in=r.play.bytes_in,
                         host_deficit_bytes=d, pct_lost=round(pct_lost, 3),
                         consumed=cons, run_us=us,
                         device_sps=round(dev, 1) if dev else None,
                         pct_slow=round(pct_slow, 3) if pct_slow else None,
                         underruns=r.play.underruns,
                         abandoned=r.play.raw.get("abandoned")))
        print(f"  run {i:2d}: lost {pct_lost:5.2f}%   device "
              f"{dev:,.0f} sps ({pct_slow:+.2f}% vs nominal)   "
              f"und {r.play.underruns}")

    lossy = [x for x in rows if x["pct_lost"] > 1.0]
    clean = [x for x in rows if x["pct_lost"] <= 1.0]
    print(f"\n  {len(lossy)} lossy, {len(clean)} clean")
    for name, grp in (("lossy", lossy), ("clean", clean)):
        if grp:
            sl = [g["pct_slow"] for g in grp if g["pct_slow"] is not None]
            ls = [g["pct_lost"] for g in grp]
            print(f"  {name:5s}: lost {statistics.fmean(ls):5.2f}%   "
                  f"device slow by {statistics.fmean(sl):+.2f}%")
    if lossy and clean:
        a_ = statistics.fmean(g["pct_slow"] for g in lossy)
        b_ = statistics.fmean(g["pct_slow"] for g in clean)
        print(f"\n  VERDICT: if the lossy runs are ~6% slow and the clean "
              f"ones are not, it is OVERSUPPLY (difference {a_ - b_:+.2f}%).")
        print(f"           if both sit at the same device rate, the host "
              f"is DISCARDING.")

    with open(a.out, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    print(f"\nwrote {len(rows)} rows to {a.out}")


if __name__ == "__main__":
    main()
