#!/usr/bin/env python3
"""#48's n/256 lattice, on whichever bench runs it.

mac-bench measured that the DACC delivers less than the rate it accepts,
that the deficit is quantised, and that `(1 - ratio - offset) * 256`
lands on integers - a whole number of conversions dropped out of every
256. The registered prediction held at RC 37, 38, 40 and 41 with a worst
residual of 0.013 of a unit.

The open question is whether the integers are the *device's* or this
board's. Same rates on the same integers across benches makes it the
design; different integers at the same rates is a far more interesting
answer and wants reporting immediately.

Everything here is the device's own arithmetic: `consumed` buffers times
PLAY_BUF_SAMPLES over the device's own `runus`, against the nominal
rate. No host clock is in the ratio, which is what keeps the host's
CDC behaviour - and this project has three different ones - out of it.

**The offset is per instrument and must be measured here, not copied.**
mac-bench's is theirs. It is the mean deficit over the rates their map
calls n = 0, and subtracting someone else's would move every integer.

    python3 tools/issue48_lattice.py --reps 8
    python3 tools/issue48_lattice.py --rcs 39,40,44 --reps 4
"""
import argparse
import json
import os
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "host"))
import measure  # noqa: E402
import provenance  # noqa: E402

PLAY_BUF_SAMPLES = 512
TC_CLOCK_HZ = 39_000_000          # SystemCoreClock / 2 at MCK 78 MHz

#: mac-bench's map, for comparison only - never to seed a fit.
THEIRS = {28: 0, 30: 2, 31: 2, 32: 0, 33: 3, 34: 4, 36: 4, 37: 5,
          38: 5, 39: 6, 40: 8, 41: 6, 44: 4, 48: 0, 49: 2, 50: 1,
          52: 0, 56: 0}

#: The rates their map calls clean. The offset comes from these.
CLEAN = (28, 52, 56)


def ratio_for(board, rc, seconds):
    """Delivered over nominal, by the device's clock alone."""
    sps = TC_CLOCK_HZ // rc
    r = measure.run_play(board, dac_sps=sps, seconds=seconds,
                         ramp=measure.RAMP_STEP)
    raw = r.play.raw
    consumed, runus = raw.get("consumed"), raw.get("runus")
    if not consumed or not runus:
        return None
    delivered = consumed * PLAY_BUF_SAMPLES / (runus / 1e6)
    return {"rc": rc, "nominal_sps": sps, "ratio": delivered / sps,
            "under": raw.get("under"), "consumed": consumed,
            "runus": runus, "via": r.play.via}


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rcs", default="28,34,37,39,40,44,50,52,56")
    ap.add_argument("--reps", type=int, default=8)
    ap.add_argument("--seconds", type=float, default=3.0)
    ap.add_argument("--bench", default=os.environ.get("DUE_BENCH", "linux-x1"))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    rcs = [int(x) for x in args.rcs.split(",") if x.strip()]

    board = measure.Board(settle=3.0)

    # What the board actually is, and what produced it (issue #53).

    prov = provenance.run_fields(board)
    rows = []
    try:
        # Interleaved by rep, not blocked by rate: a drift over the run
        # then lands on every rate rather than on the last few.
        for rep in range(args.reps):
            for rc in rcs:
                row = ratio_for(board, rc, args.seconds)
                if row is None:
                    continue
                row.update(rep=rep, bench=args.bench, **prov)
                rows.append(row)
                print(f"rep {rep} RC {rc:>3}: ratio {row['ratio']:.6f}  "
                      f"under {row['under']}")
                board.stop()
    finally:
        board.stop(); board.close()

    out = args.out or os.path.join(ROOT, "records",
                                   f"issue48-lattice-{args.bench}.jsonl")
    with open(out, "w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")

    by = {}
    for r in rows:
        by.setdefault(r["rc"], []).append(r["ratio"])
    clean = [1.0 - statistics.median(by[rc]) for rc in CLEAN if rc in by]
    offset = statistics.mean(clean) if clean else 0.0

    print(f"\noffset from RC {[c for c in CLEAN if c in by]} = "
          f"{offset:.6f}  (this instrument's, not a constant)")

    # A single number computed from a bimodal input is the failure mode,
    # and it is silent. Measured on linux-x1 2026-08-30: RC 28 and RC 52
    # sit at n=0 most of the time and drop to *exactly* n=2 in 2 of 9
    # and 3 of 9 reps - six low readings spanning 0.00013, so a mode and
    # not scatter. The median reports all three CLEAN rates at n=0 and
    # hides it completely; a batch that happens to draw more low reps
    # gets a larger offset, and every n in that batch shifts with it.
    #
    # So say it. The offset stays the median-based one - this warns, it
    # does not correct, because what the right offset is when a zero is
    # bimodal is a question for whoever reads this and not for a tool.
    for rc in (c for c in CLEAN if c in by):
        vals = sorted(by[rc])
        if len(vals) < 4:
            continue
        spread = vals[-1] - vals[0]
        # A clean rate should sit inside one lattice step of itself.
        if spread > 0.5 / 256.0:
            lo = statistics.median(vals[:len(vals) // 2])
            hi = statistics.median(vals[len(vals) // 2:])
            print(f"  WARNING: RC {rc} is not single-moded over "
                  f"{len(vals)} reps - spread {spread:.6f}, low half "
                  f"{lo:.6f}, high half {hi:.6f}")
            print(f"           ({(hi - lo) * 256.0:+.2f} of a lattice step "
                  f"between the halves). The offset above is drawn from "
                  f"this,")
            print(f"           so every n below moves with however many "
                  f"low reps this batch happened to draw. More reps, or "
                  f"a different zero.")
    print(f"\n{'RC':>4}{'sps':>10}{'ratio':>10}{'deficit-off':>13}"
          f"{'x256':>9}{'n':>4}{'resid':>8}   theirs")
    for rc in sorted(by):
        med = statistics.median(by[rc])
        d = 1.0 - med - offset
        x = d * 256.0
        n = round(x)
        theirs = THEIRS.get(rc)
        mark = "" if theirs is None else ("  same" if n == theirs
                                          else f"  THEIRS {theirs}")
        print(f"{rc:>4}{TC_CLOCK_HZ // rc:>10}{med:>10.6f}{d:>13.6f}"
              f"{x:>9.3f}{n:>4}{abs(x - n):>8.3f}{mark}")
    print(f"\nwrote {len(rows)} rows to {out}")


if __name__ == "__main__":
    main()
