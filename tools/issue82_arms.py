#!/usr/bin/env python3
"""The one-hold level errors, under the console knobs that move the DAC core.

A hold is the two ADC samples of one DAC level. Its level error is the
second difference against its neighbours, which a moving sine barely
touches (0.8 codes of curvature at most) and noise touches at about 1.2
codes sd. What is measured is the rate, per second, of holds whose error
exceeds 6, 10 and 15 codes - the heavy tail - on A0 and on A1 apart. A
solo arm (every table entry DAC0) has a hold of one sample and is read
per sample instead.

Arms are console only and run in one board session, the baseline first
and again after the bias arms so a drift over the session cannot pass
for an effect:

    sg dialout -c '.venv/bin/python tools/issue82_arms.py --bench linux-x1'
"""
import argparse
import json
import os
import statistics
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "host"))
import measure      # noqa: E402
import provenance   # noqa: E402

ARMS = [
    ("baseline",        ["=0N", "=1J", "=2,1I"]),
    ("sync-off",        ["=0N", "=0J"]),
    ("solo",            ["=0N", "=3J"]),
    ("dc0-square1",     ["=3N", "=1J"]),
    ("all-dc",          ["=3N", "=0J"]),
    ("bias-0-0",        ["=0N", "=1J", "=0,0I"]),
    ("baseline-again",  ["=0N", "=1J", "=2,1I"]),
    ("bias-3-3",        ["=0N", "=1J", "=3,3I"]),
]
RESTORE = ["=0N", "=1J", "=2,1I"]
THRESH = (6, 10, 15)


def edge_parity(x, jump=2000):
    """A square's edges settle the pairing outright: the new level's first
    sample is the first sample of a hold. None if the channel has no edges."""
    starts = [i % 2 for i in range(1, len(x)) if abs(x[i] - x[i - 1]) > jump]
    if len(starts) < 8:
        return None
    even = sum(1 for s in starts if s == 0)
    if even not in (0, len(starts)):
        raise ValueError(f"edges disagree on the hold parity: {even} even of {len(starts)}")
    return 0 if even else 1


def parity(vals, known=None):
    """Which two samples form a hold. On a flat channel the two choices
    tie and a guess reads the DAC's update transient as a hold error, so
    a tie is refused unless the caller knows the answer - A1's parity is
    the complement of A0's, since the two channels update on alternate
    triggers."""
    if known is None:
        known = edge_parity(vals)
    if known is not None:
        return known, statistics.median(abs(vals[i] - vals[i + 1])
                                        for i in range(known, len(vals) - 1, 2))
    med = {off: statistics.median(abs(vals[i] - vals[i + 1])
                                  for i in range(off, len(vals) - 1, 2))
           for off in (0, 1)}
    if abs(med[0] - med[1]) < 2.0:
        raise ValueError(f"hold parity is a tie ({med[0]} vs {med[1]}); "
                         f"pass the parity known from the other channel")
    off = min(med, key=med.get)
    return off, med[off]


def tail(vals, hold, known_parity=None):
    """Rate/s of level errors beyond each threshold, at 200 ksps.
    Returns (rates, pair spread, holds counted, parity used)."""
    if len(vals) < 8:
        return ({t: 0.0 for t in THRESH}, 0.0, 0, None, None)
    if hold == 2:
        off, spread = parity(vals, known_parity)
        lv = [(vals[i] + vals[i + 1]) / 2.0
              for i in range(off, len(vals) - 1, 2)]
    else:
        off, spread = 0, 0.0
        lv = list(vals)
    e = [lv[h] - (lv[h - 1] + lv[h + 1]) / 2.0 for h in range(1, len(lv) - 1)]
    # A1 carries a square in some arms: keep clear of its edges.
    big = {h for h in range(1, len(lv)) if abs(lv[h] - lv[h - 1]) > 1000}
    keep = [x for h, x in enumerate(e, 1)
            if not any((h + k) in big for k in range(-3, 4))]
    secs = len(vals) / 200000.0
    # The tail's scale in codes per e-fold - an exponential's mean excess
    # over a threshold - is what compares across boards; a count beyond a
    # fixed threshold moves 10x for a 25% change in it.
    excess = [abs(x) - 4.0 for x in keep if abs(x) > 4.0]
    scale = round(statistics.fmean(excess), 2) if len(excess) >= 20 else None
    return ({t: round(sum(1 for x in keep if abs(x) > t) / secs, 1) for t in THRESH},
            round(spread, 2), len(keep), off, scale)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench", default=os.environ.get("DUE_BENCH", "linux-x1"))
    ap.add_argument("-n", "--runs", type=int, default=2)
    ap.add_argument("-s", "--seconds", type=float, default=5.0)
    ap.add_argument("--parity", type=int, choices=(0, 1), default=None,
                    help="the hold parity to use on both channels; skips "
                         "the tie check, which cannot tell an ambiguous "
                         "pairing from a quiet board where both fit")
    args = ap.parse_args()
    if args.parity is not None:
        print(f"parity forced: {args.parity}")
    out = os.path.join(ROOT, "records", f"issue82-arms-{args.bench}.jsonl")
    board = measure.Board(settle=3.0)
    try:
        board.stop()
        board.drain_console(0.5)
        prov = provenance.run_fields(board)
        print("provenance: " + ", ".join(f"{k}={v}" for k, v in prov.items()))
        for name, cmds in ARMS:
            for c in cmds:
                board.cmd(c)
                board.drain_console(0.3)
            hold = 1 if name == "solo" else 2
            for run in range(1, args.runs + 1):
                res = measure.run_capture(board, preset="=200000,200000M",
                                          seconds=args.seconds)
                ps = res.stream
                a0 = ps.series.get(measure.CH_A0) or []
                a1 = ps.series.get(measure.CH_A1) or []
                start = ps._index_at(measure.CH_A0, measure.SETTLE_US)
                r0, s0, n0, p0, sc0 = tail(a0[start:], hold,
                                           known_parity=args.parity)
                # A1's pairing comes from its own edges when it carries a
                # square; only without one is A0's complement taken, and
                # the complement is not a law - whether a channel's sample
                # sees the update at its own trigger depends on where the
                # update lands against that channel's sample instant,
                # which differs between A1 (sampled first) and A0.
                if a1:
                    kp = args.parity
                    if kp is None:
                        kp = edge_parity(a1[start:])
                    if kp is None and hold == 2 and p0 is not None:
                        kp = 1 - p0
                    r1, s1, n1, p1, sc1 = tail(a1[start:], 2, known_parity=kp)
                else:
                    r1, s1, n1, p1, sc1 = ({t: 0.0 for t in THRESH}, 0.0, 0, None, None)
                row = {"arm": name, "cmds": cmds, "run": run, "hold": hold,
                       "t": time.strftime("%Y-%m-%dT%H:%M:%S"),
                       "bench": args.bench, **prov,
                       "a0_tail": r0, "a0_pair_spread": s0, "a0_holds": n0,
                       "a1_tail": r1, "a1_pair_spread": s1, "a1_holds": n1,
                       "a0_parity": p0, "a1_parity": p1,
                       "a0_scale_codes": sc0, "a1_scale_codes": sc1}
                with open(out, "a", encoding="utf-8") as f:
                    f.write(json.dumps(row) + "\n")
                print(f"{name:15s} run {run}: A0 tail/s {r0} scale {sc0}  A1 tail/s {r1} "
                      f"scale {sc1}  (parity {p0}/{p1}, pair spread {s0}/{s1})", flush=True)
    finally:
        try:
            for c in RESTORE:
                board.cmd(c)
                board.drain_console(0.3)
            board.stop()
        finally:
            board.close()
    print(f"rows -> {out}")


if __name__ == "__main__":
    main()
