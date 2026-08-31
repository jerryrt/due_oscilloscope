#!/usr/bin/env python3
"""Does opening the control port reset the board? Ask the board.

#48 grew an axis it may not have: *minutes since reset*. windows-desk
compared four arms labelled 0, 12, 15 and 63 minutes since reset and
read a reversal off them. But `measure.Board`'s own docstring says
opening the control port asserts NRSTB, and `tools/issue48_lattice.py`
opens one at the top of every run - so if the docstring is right, every
arm started at uptime 0 and the axis is a label rather than a variable.

A docstring is not a measurement, which is why this exists. The board
keeps `uptime_ms` in the control channel's **heartbeat**, and the
command port is the native port's *second CDC function* - opening it
does not touch NRSTB. So the board can be asked directly:

    read uptime -> wait -> read uptime      (does it climb?)
    open a measure.Board, close it
    read uptime                             (did it go backwards?)

The first pair is the control. Without it a low second reading proves
nothing, because "uptime went backwards" and "this counter does not
mean what I think" look identical from one sample.

**It is a per-platform question, not a per-board one.** The reset is
NRSTB driven by the 16U2 off DTR, and whether a host asserts DTR on
open is the host's stack. macOS does. That is measured here and claimed
nowhere else - run it on your own bench before believing it of yours.

    python3 tools/uptime_reset_probe.py
    python3 tools/uptime_reset_probe.py --reps 3 --out records/x.jsonl
"""
import argparse
import json
import os
import platform
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "host"))
import control  # noqa: E402
import measure  # noqa: E402
import ports  # noqa: E402
import provenance  # noqa: E402


def read_uptime(path, timeout=2.0):
    """uptime_ms over the command port, which does not assert NRSTB."""
    c = control.Control(path, timeout=timeout)
    try:
        return c.heartbeat()["uptime_ms"]
    finally:
        c.close()


def identity_over_command(path, timeout=2.0):
    c = control.Control(path, timeout=timeout)
    try:
        return c.identity()
    finally:
        c.close()


def one_cycle(cmd_path, idle_s):
    """One control + treatment pair. Returns a row."""
    before = read_uptime(cmd_path)
    time.sleep(idle_s)
    after_idle = read_uptime(cmd_path)

    t0 = time.time()
    with measure.Board(settle=3.0):
        pass
    held_s = time.time() - t0

    after_open = read_uptime(cmd_path)

    climbed = after_idle - before
    return {
        "uptime_before_ms": before,
        "uptime_after_idle_ms": after_idle,
        "uptime_after_control_open_ms": after_open,
        "idle_s": idle_s,
        "control_held_s": round(held_s, 2),
        "climbed_over_idle_ms": climbed,
        "counter_climbs": climbed > 0,
        "went_backwards": after_open < after_idle,
    }


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--idle", type=float, default=2.0,
                    help="seconds between the two control readings")
    ap.add_argument("--bench", default=os.environ.get("DUE_BENCH"))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    nodes = ports.native_nodes()
    if len(nodes) < 2:
        print("no command node - this board has one CDC function "
              "(Track A before 2026-08-27), so there is no way to read "
              "uptime without opening the port under test", file=sys.stderr)
        return 2
    cmd_path = nodes[1]
    print(f"command port: {cmd_path}")

    ident = identity_over_command(cmd_path)
    fields = provenance.run_fields(ident=ident)
    if args.bench:
        fields["bench"] = args.bench

    rows = []
    for rep in range(args.reps):
        row = one_cycle(cmd_path, args.idle)
        row.update(fields)
        row["rep"] = rep
        rows.append(row)
        print(f"rep {rep}: {row['uptime_before_ms']} -> "
              f"{row['uptime_after_idle_ms']} (idle) -> "
              f"{row['uptime_after_control_open_ms']} (after open)   "
              f"climbs={row['counter_climbs']} "
              f"backwards={row['went_backwards']}")

    climbs = sum(r["counter_climbs"] for r in rows)
    back = sum(r["went_backwards"] for r in rows)
    print()
    print(f"counter climbs while idle : {climbs}/{len(rows)}")
    print(f"went backwards on open    : {back}/{len(rows)}")
    if climbs == len(rows) and back == len(rows):
        print(f"VERDICT on {platform.system()}: opening the control port "
              f"RESETS the board. Any tool that opens a measure.Board "
              f"starts its run at uptime 0.")
    elif climbs != len(rows):
        print("VERDICT: inconclusive - the counter did not climb while "
              "idle, so it is not measuring what this probe assumes.")
    else:
        print(f"VERDICT on {platform.system()}: opening the control port "
              f"does NOT reset the board.")

    if args.out:
        with open(args.out, "a") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
        print(f"wrote {len(rows)} rows to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
