#!/usr/bin/env python3
"""#5's last untried draw-event candidate, with a human doing the cycle.

Table rebuild, NRSTB reset and amplitude excursion are all excluded. A
power cycle is the one candidate left, and it has stayed untried on both
benches because it needs hands - this bench's hub advertises per-port
power and ignores the request (68e9d7a), so it needs them here too.

Two things about the design, both learned the hard way on this issue.

**A control arm comes first.** The configuration drifts on its own, so a
change measured after a cycle means nothing without a same-duration arm
with no cycle in it. Arm order is baseline, wait, control, then the
cycles - so a cycle can never be credited with drift already underway.

**Positions, not p(on).** The gate is redrawn at every stream start at
p ~ 0.2 (15118da), so comparing "how often the comb appears" between
arms of a dozen captures is nearly powerless. The SITE POSITIONS are the
stable thing - reproducible to a tenth of a code and unchanged across
115 captures - so eight captures per arm resolves a change in them
easily. That is why this asks for more cycles rather than longer arms.

The operator is never asked to synchronise with the tool: it watches for
the device nodes to vanish and return, so the cycle can happen whenever
it happens.

    .venv/bin/python tools/issue5_powercycle.py --arms 6 --per-arm 8
"""
import argparse
import collections
import glob
import json
import os
import statistics
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "host"))
import measure  # noqa: E402


def nodes():
    return set(glob.glob("/dev/cu.usbmodem*"))


def await_cycle(timeout=900.0):
    """Block until the board goes away and comes back.

    Returns True on a real cycle. The disappearance is what makes it a
    cycle rather than a reset - this is the check tools/powercycle.py
    grew after a hub claimed to cut power and did not.
    """
    start = nodes()
    print("\n>>> POWER CYCLE NOW: unplug the board, ~15 s, plug it back "
          "in. Waiting...", flush=True)
    end = time.time() + timeout
    gone = False
    while time.time() < end:
        time.sleep(0.5)
        now = nodes()
        if not gone and not (now & start):
            gone = True
            print("    board disappeared", flush=True)
        elif gone and now:
            time.sleep(3.0)
            print(f"    board back: {sorted(nodes())}", flush=True)
            return True
    print("    timed out waiting for a cycle", flush=True)
    return False


def arm(label, n, seconds, bench, out):
    """One arm: n captures, site table each, in one board session."""
    board = measure.Board(settle=3.0)
    rows = []
    try:
        board.stop()
        board.drain_console(0.5)
        for i in range(1, n + 1):
            res = measure.run_capture(board, preset="M", seconds=seconds)
            ps = res.stream
            vals = ps.series.get(measure.CH_A0)
            if not vals:
                print(f"  {label} {i}: no samples", flush=True)
                continue
            start = ps._index_at(measure.CH_A0, measure.SETTLE_US)
            fold = measure.pair_fold(list(vals[start:]))
            found, mad = measure.fold_sites(fold.get("profile") or [])
            bins = sorted(b for b, _v, _z in found)
            gaps = collections.Counter(bins[k + 1] - bins[k]
                                       for k in range(len(bins) - 1))
            row = {"arm": label, "run": i, "bench": bench,
                   "t": time.strftime("%Y-%m-%dT%H:%M:%S"),
                   "hold_ok": bool(fold.get("hold_ok")),
                   "mad": round(mad, 4), "gaps21": gaps.get(21, 0),
                   "sites": [[b, round(v, 2)] for b, v, _z in found[:8]]}
            rows.append(row)
            print(f"  {label} {i:2d}: "
                  + ", ".join(f"{b}:{v:+.2f}" for b, v, _z in found[:5]),
                  flush=True)
            board.stop()
            board.drain_console(0.3)
    finally:
        try:
            board.stop()
        finally:
            board.close()
    if out:
        with open(out, "a") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
    return rows


def summarise(all_rows):
    print("\nsite positions by arm (value range, times seen):")
    arms = []
    for r in all_rows:
        if r["arm"] not in arms:
            arms.append(r["arm"])
    seen = sorted({b for r in all_rows for b, _v in r["sites"]})
    strong = [b for b in seen
              if sum(1 for r in all_rows
                     if any(bb == b for bb, _v in r["sites"]))
              >= max(3, len(all_rows) // 6)]
    print("arm        " + "  ".join(f"{b:>14d}" for b in strong))
    for a in arms:
        rs = [r for r in all_rows if r["arm"] == a]
        cells = []
        for b in strong:
            vs = [v for r in rs for bb, v in r["sites"] if bb == b]
            cells.append(f"{statistics.median(vs):+6.2f} x{len(vs):<2d}"
                         if vs else "        .     ")
        print(f"{a:10s} " + "  ".join(f"{c:>14s}" for c in cells))
    print("\n  positions identical across every arm -> a power cycle does "
          "not redraw them, and the candidate list is exhausted")
    print("  positions change ONLY after a cycle, not across the control "
          "-> the draw event is found")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arms", type=int, default=6,
                    help="total arms: baseline, control, then cycles")
    ap.add_argument("--per-arm", type=int, default=8)
    ap.add_argument("-s", "--seconds", type=float, default=3.0)
    ap.add_argument("--settle", type=float, default=60.0,
                    help="wait between baseline and control, matching "
                         "roughly what a cycle costs in wall clock")
    ap.add_argument("--bench", default=os.environ.get("DUE_BENCH", "macos"))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    all_rows = []
    print("=== arm S1: baseline ===", flush=True)
    all_rows += arm("S1-base", args.per_arm, args.seconds, args.bench,
                    args.out)
    print(f"\n=== waiting {args.settle:.0f} s, no cycle (drift control) "
          f"===", flush=True)
    time.sleep(args.settle)
    print("=== arm S2: control, no cycle ===", flush=True)
    all_rows += arm("S2-ctrl", args.per_arm, args.seconds, args.bench,
                    args.out)

    for k in range(1, args.arms - 1):
        if not await_cycle():
            break
        print(f"=== arm C{k}: after power cycle {k} ===", flush=True)
        all_rows += arm(f"C{k}-cyc", args.per_arm, args.seconds,
                        args.bench, args.out)
    if all_rows:
        summarise(all_rows)
    if args.out:
        print(f"\nwrote {len(all_rows)} rows to {args.out}")


if __name__ == "__main__":
    main()
