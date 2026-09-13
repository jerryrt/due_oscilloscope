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


def parity(vals):
    best = None
    for off in (0, 1):
        m = statistics.median(abs(vals[i] - vals[i + 1])
                              for i in range(off, len(vals) - 1, 2))
        if best is None or m < best[0]:
            best = (m, off)
    return best[1], best[0]


def tail(vals, hold):
    """Rate/s of level errors beyond each threshold, at 200 ksps."""
    if hold == 2:
        off, spread = parity(vals)
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
    return ({t: round(sum(1 for x in keep if abs(x) > t) / secs, 1) for t in THRESH},
            round(spread, 2), len(keep))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench", default=os.environ.get("DUE_BENCH", "linux-x1"))
    ap.add_argument("-n", "--runs", type=int, default=2)
    ap.add_argument("-s", "--seconds", type=float, default=5.0)
    args = ap.parse_args()
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
                r0, s0, n0 = tail(a0[start:], hold)
                r1, s1, n1 = tail(a1[start:], 2)
                row = {"arm": name, "cmds": cmds, "run": run, "hold": hold,
                       "t": time.strftime("%Y-%m-%dT%H:%M:%S"),
                       "bench": args.bench, **prov,
                       "a0_tail": r0, "a0_pair_spread": s0, "a0_holds": n0,
                       "a1_tail": r1, "a1_pair_spread": s1, "a1_holds": n1}
                with open(out, "a", encoding="utf-8") as f:
                    f.write(json.dumps(row) + "\n")
                print(f"{name:15s} run {run}: A0 tail/s {r0}  A1 tail/s {r1}"
                      f"  (pair spread {s0}/{s1})", flush=True)
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
