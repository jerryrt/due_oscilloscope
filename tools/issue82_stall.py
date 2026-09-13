#!/usr/bin/env python3
"""Stall the main loop mid-capture and read the DAC tails inside the stall.

`=<ms>S` busy-waits the main loop; interrupts and both converters keep
running. A stall longer than the capture ring (four frames, 20 ms at
200 ksps) overflows it, and the four frames received just before the
resulting overrun are the ring's contents - samples converted while the
loop was stopped and, after the first frame, while USB was idle. So the
overrun is the window's own anchor and needs no clock.

The reading is the rate of one-hold level errors (second difference of
hold levels beyond 6 and 10 codes) inside those windows against the rest
of the same capture, on A0 and A1 apart. Six stalls of 60 ms in an 8 s
capture. Rows: records/issue82-stall-<bench>.jsonl.

    sg dialout -c '.venv/bin/python tools/issue82_stall.py --bench linux-x1'
"""
import argparse
import json
import os
import statistics
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "host"))
import measure      # noqa: E402
import provenance   # noqa: E402

FRAME = 1016     # samples per channel per frame


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


def parity(x):
    """The unambiguous case only; a flat channel ties and must take the
    other channel's complement instead of a guess."""
    e = edge_parity(x)
    if e is not None:
        return e
    med = {o: statistics.median(abs(x[i] - x[i + 1]) for i in range(o, len(x) - 1, 2))
           for o in (0, 1)}
    if abs(med[0] - med[1]) < 2.0:
        raise ValueError(f"hold parity is a tie ({med[0]} vs {med[1]})")
    return min(med, key=med.get)


def holds(x, off):
    return [(x[i] + x[i + 1]) / 2.0 for i in range(off, len(x) - 1, 2)]


def rates(x, windows, off):
    L = holds(x, off)
    E = [L[h] - (L[h - 1] + L[h + 1]) / 2.0 for h in range(1, len(L) - 1)]
    edges = {h for h in range(1, len(L)) if abs(L[h] - L[h - 1]) > 1000}
    ok = lambda h: 1 <= h < len(L) - 1 and not any((h + k) in edges for k in range(-3, 4))
    inside = [h for lo, hi in windows for h in range(lo, hi) if ok(h)]
    near = lambda h: any(lo - 3 * FRAME <= h < hi + 3 * FRAME for lo, hi in windows)
    outside = [h for h in range(100000, len(L) - 1) if ok(h) and not near(h)]
    out = {}
    for name, hs in (("inside", inside), ("outside", outside)):
        for t in (6, 10):
            c = sum(1 for h in hs if abs(E[h - 1]) > t)
            out[f"{name}_{t}"] = round(1000.0 * c / max(1, len(hs)), 2)
        out[f"{name}_holds"] = len(hs)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench", default=os.environ.get("DUE_BENCH", "linux-x1"))
    ap.add_argument("--stalls", type=int, default=6)
    ap.add_argument("--ms", type=int, default=60)
    ap.add_argument("-s", "--seconds", type=float, default=8.0)
    args = ap.parse_args()
    out = os.path.join(ROOT, "records", f"issue82-stall-{args.bench}.jsonl")
    board = measure.Board(settle=3.0)
    try:
        board.stop()
        board.drain_console(0.5)
        prov = provenance.run_fields(board)
        for c in ("=0N", "=1J", "=2,1I", "=4q"):
            board.cmd(c)
            board.drain_console(0.3)

        def stalls():
            time.sleep(1.5)
            for _ in range(args.stalls):
                board.cmd(f"={args.ms}S")
                time.sleep(0.9)
        th = threading.Thread(target=stalls, daemon=True)
        th.start()
        res = measure.run_capture(board, preset="=200000,200000M",
                                  seconds=args.seconds)
        th.join()
        ps = res.stream
        gaps = [f for f, _t, o in ps.overrun_steps if o > 0]
        p0 = parity(ps.series.get(measure.CH_A0))
        p1 = 1 - p0
        try:
            p1 = parity(ps.series.get(measure.CH_A1))   # the square's edges, when there is one
        except ValueError:
            pass
        windows = [((f * FRAME) // 2 - 2 * FRAME, (f * FRAME) // 2) for f in gaps]
        row = {"bench": args.bench, **prov, "t": time.strftime("%Y-%m-%dT%H:%M:%S"),
               "stalls": args.stalls, "ms": args.ms, "gap_frames": gaps,
               "a0": rates(ps.series.get(measure.CH_A0), windows, p0),
               "a1": rates(ps.series.get(measure.CH_A1), windows, p1),
               "a0_parity": p0, "a1_parity": p1}
        with open(out, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
        for ch in ("a0", "a1"):
            r = row[ch]
            print(f"{ch}: per 1000 holds >6: inside {r['inside_6']} outside {r['outside_6']}"
                  f" | >10: inside {r['inside_10']} outside {r['outside_10']}"
                  f"  (holds {r['inside_holds']}/{r['outside_holds']})")
        print(f"gaps at frames {gaps}; rows -> {out}")
    finally:
        board.stop()
        board.close()


if __name__ == "__main__":
    main()
