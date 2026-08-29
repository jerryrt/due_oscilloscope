#!/usr/bin/env python3
"""Is `Feeder.WRITE_SIZE` still a rule, or a stale workaround?

`docs/HANDOFF.md` calls the 0-series re-validation "the oldest real debt
here", and one half of it is a claim only this platform can test:

    macOS loses 0.45-0.85% of what write() counted, at every rate above
    200 ksps, unless every write is the same size. A constant 512 bytes
    is lossless; "whatever is due" is not, even when every write it
    emits is 512 or 1024.

Everything about the feed is designed around that, and it has not been
re-read since the constant-size feed landed. `Feeder` still carries both
paths for exactly this comparison - `write_size=None` is the constant
size, `write_size=0` the legacy due-sized one - so the A/B costs nothing
but bench time.

    .venv/bin/python tools/writepolicy.py --rcs 195,98,65

Counterbalanced ABBA within each rate rather than swept: the host's byte
loss is intermittent and the die warms, so a block of one policy
followed by a block of the other compares the half-hour as much as the
policy. RC 44 and 39 are excluded by default - their converters run slow
and shed the surplus however it is written, so they cannot answer a
question about write policy.
"""
import argparse
import json
import os
import statistics
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "host"))
import measure  # noqa: E402

ARMS = {"const": None, "due": 0}


def one(board, rc, arm, seconds):
    hz = measure.hz_for(rc)
    res = measure.run_play(board, dac_sps=hz, seconds=seconds, drain_s=1.5,
                           write_size=ARMS[arm])
    if res.refused:
        return None
    deficit = res.host_deficit
    tx = res.host_tx_bytes
    return {"rc": rc, "hz": hz, "arm": arm, "tx": tx,
            "in": res.play.bytes_in if res.play else None,
            "deficit": deficit,
            "pct": round(deficit / tx * 100, 4) if tx else None,
            "chunks": deficit // 128 if deficit % 128 == 0 else None,
            "mod128": deficit % 128,
            "under": res.play.underruns if res.play else None,
            "drained": bool(res.drained),
            "t_wall": time.time()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rcs", default="195,98,65")
    ap.add_argument("--rounds", type=int, default=2)
    ap.add_argument("--seconds", type=float, default=3.0)
    ap.add_argument("--bench", default=os.environ.get("DUE_BENCH", "macos"))
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    rcs = [int(x) for x in args.rcs.split(",")]
    board = measure.Board(settle=3.0)
    rows = []
    try:
        board.stop()
        board.drain_console(0.5)
        for rc in rcs:
            for r in range(args.rounds):
                order = (("const", "due", "due", "const") if r % 2 == 0
                         else ("due", "const", "const", "due"))
                for arm in order:
                    row = one(board, rc, arm, args.seconds)
                    if row is None:
                        print(f"  RC {rc} {arm}: refused", flush=True)
                        continue
                    row["round"] = r
                    rows.append(row)
                    print(f"RC {rc:3d} ({row['hz']:7d} sps) {arm:5s}: "
                          f"deficit {row['deficit']:8d} B "
                          f"({row['pct']:6.3f}%)  "
                          f"{'' if row['mod128'] == 0 else 'NOT A CHUNK  '}"
                          f"under={row['under']}", flush=True)
                    board.stop()
                    board.drain_console(0.3)
    finally:
        try:
            board.stop()
        finally:
            board.close()

    print()
    for rc in rcs:
        print(f"RC {rc} ({measure.hz_for(rc)} sps):")
        for arm in ARMS:
            v = [r for r in rows if r["rc"] == rc and r["arm"] == arm]
            if not v:
                continue
            pct = [r["pct"] for r in v]
            print(f"  {arm:5s}  n={len(v)}  deficit "
                  f"{min(r['deficit'] for r in v)}-"
                  f"{max(r['deficit'] for r in v)} B, "
                  f"{min(pct):.3f}-{max(pct):.3f}%, "
                  f"median {statistics.median(pct):.3f}%")

    if args.json:
        with open(args.json, "a") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
        print(f"\nwrote {len(rows)} rows to {args.json}")


if __name__ == "__main__":
    main()
