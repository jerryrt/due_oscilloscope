#!/usr/bin/env python3
"""Does the comb of 21 land on DAC1 as well, or only on DAC0?

There is a degeneracy in how the lattice has been quoted, and it is
mine. a68e774 concluded the period is 21 *DAC0 output changes* rather
than 21 converter conversions, from the two arms disagreeing about what
a bin is: gen NORMAL gives one DAC0 level per two DACC conversions,
build_ramp gives one per one, and both read 21.

**That inference does not hold, because 21 is odd.** A period of 21
DACC conversions puts events at DAC0-level indices 0, 10.5, 21, 31.5,
42 ... - and the half-integers are DAC1 conversions, which an A0 fold
cannot see. What survives into a DAC0 fold is 0, 21, 42: a comb of 21,
exactly what 21 DAC0 writes predicts. The two hypotheses are
indistinguishable in A0 for any odd period.

A1 separates them, and on this bench the wiring is already there -
DAC1 goes to A1, and preset M drives DAC1 with a fixed level, so A1 is
a flat channel and a flat channel is the best detector this issue has.

    comb on A1  -> the period counts DACC conversions, both channels
    A1 clean    -> it is DAC0's own output stage

Same instrument as A0, one channel over: DAC1 is held for two A1
samples exactly as DAC0 is held for two A0 samples, so pair_fold's
differencing cancels the hold and leaves a one-sample artifact at full
height.

The A0 arm is folded in the same capture, so "A1 is clean" is only
reported against a capture where A0 is not - an absence measured while
the thing is absent everywhere is not evidence.

    .venv/bin/python tools/issue5_a1.py -n 12
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
import measure  # noqa: E402


def comb_gaps(bins):
    return collections.Counter(bins[i + 1] - bins[i]
                               for i in range(len(bins) - 1))


def read(vals, start):
    tail = list(vals[start:])
    if len(tail) < 8 * measure.GEN_TABLE_LEN:
        return None
    f = measure.pair_fold(tail)
    prof = f.get("profile") or []
    found, mad = measure.fold_sites(prof)
    bins = sorted(b for b, _v, _z in found)
    return {"sites": [[b, round(v, 2), round(z, 1)] for b, v, z in found[:8]],
            "n_sites": len(found), "bins": bins,
            "gaps21": comb_gaps(bins).get(21, 0),
            "hold_ok": bool(f.get("hold_ok")),
            "pair_spread": round(f.get("pair_spread", 0.0), 2),
            "mad": round(mad, 4),
            "flat_sd": round(statistics.pstdev(tail[:20000]), 2)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--runs", type=int, default=12)
    ap.add_argument("-s", "--seconds", type=float, default=3.0)
    ap.add_argument("--bench", default=os.environ.get("DUE_BENCH", "macos"))
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    board = measure.Board(settle=3.0)
    rows = []
    try:
        board.stop()
        board.drain_console(0.5)
        for i in range(1, args.runs + 1):
            res = measure.run_capture(board, preset="M", seconds=args.seconds)
            ps = res.stream
            out = {}
            for name, tag in (("a0", measure.CH_A0), ("a1", measure.CH_A1)):
                vals = ps.series.get(tag) or []
                if not vals:
                    continue
                out[name] = read(vals, ps._index_at(tag, measure.SETTLE_US))
            if "a0" not in out or "a1" not in out or not all(out.values()):
                print(f"run {i}: short capture", flush=True)
                continue
            row = {"run": i, "t": time.strftime("%Y-%m-%dT%H:%M:%S"),
                   "bench": args.bench, "a0": out["a0"], "a1": out["a1"]}
            rows.append(row)
            for name in ("a0", "a1"):
                r = out[name]
                print(f"run {i:2d} {name.upper()}: sites {r['n_sites']:3d}  "
                      f"gaps21 {r['gaps21']:3d}  sd {r['flat_sd']:7.1f}  "
                      f"hold_ok={r['hold_ok']}  "
                      + ", ".join(f"{b}:{v:+.2f}"
                                  for b, v, _ in r["sites"][:4]), flush=True)
            board.stop()
            board.drain_console(0.3)
    finally:
        try:
            board.stop()
        finally:
            board.close()

    on = [r for r in rows if r["a0"]["gaps21"] >= 3]
    print(f"\n{len(rows)} runs; A0 comb on in {len(on)}")
    if on:
        print("captures where A0 carries the comb - the only ones where "
              "A1's answer means anything:")
        for r in on:
            print(f"  run {r['run']:2d}  A0 gaps21 {r['a0']['gaps21']:3d} "
                  f"sites {r['a0']['n_sites']:3d}   ||   "
                  f"A1 gaps21 {r['a1']['gaps21']:3d} "
                  f"sites {r['a1']['n_sites']:3d}")
        tot0 = sum(r["a0"]["gaps21"] for r in on)
        tot1 = sum(r["a1"]["gaps21"] for r in on)
        print(f"\ngaps of 21, summed over those captures: "
              f"A0 {tot0}, A1 {tot1}")
        print("A1 comparable to A0 -> the period counts DACC conversions")
        print("A1 at zero          -> it is DAC0's own output stage")
    else:
        print("A0 never drew the comb, so this run says nothing about A1. "
              "Run again - p(on) is about 0.2 per stream.")
    if args.json:
        with open(args.json, "a") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
        print(f"wrote {len(rows)} rows to {args.json}")


if __name__ == "__main__":
    main()
