#!/usr/bin/env python3
"""Is #48's mode fixed for a whole playback, or re-decided inside one?

Three constraints are established (#48, `tools/issue48_withinrun.py`):
the two mode *ratios* are the silicon and agree across benches to six
decimals; the *incidence* is not and differs 8.5-27.7 % across three
benches; and the selection shows **no serial correlation between reps**,
which bounds the dwell of any selecting state at about one rep.

That last one is in tension with the first. A rep is one playback of a
few seconds, and within it the ratio is a single clean value - spread
0.00009 across 14 draws of the deep mode. So inside a run the state
does not move, and between runs it does not persist.

The resolution those two force is that the state is **re-drawn when
playback starts** rather than free-running. This tests it the cheap way
CLAUDE.md already names: *is the effect proportional to how long you
ran?*

    fixed at start   -> the gap between modes is the same at 1 s and 9 s,
                        and no run lands between them
    re-decided mid-run -> a long run averages the two and intermediate
                        ratios appear, more of them the longer it runs

**Durations are interleaved, never blocked.** A drift over the session
then lands on all three arms rather than on the last one - the same
reason `issue48_lattice.py` interleaves by rep and not by rate. Blocking
is how #48 acquired an axis it did not have.

One held `measure.Board` for the whole thing, because opening one
resets the board (`tools/uptime_reset_probe.py`).

    python3 tools/issue48_dwell.py --rc 36 --reps 12
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
TC_CLOCK_HZ = 39_000_000


def one(board, rc, seconds):
    sps = TC_CLOCK_HZ // rc
    r = measure.run_play(board, dac_sps=sps, seconds=seconds,
                         ramp=measure.RAMP_STEP)
    raw = r.play.raw
    consumed, runus = raw.get("consumed"), raw.get("runus")
    if not consumed or not runus:
        return None
    delivered = consumed * PLAY_BUF_SAMPLES / (runus / 1e6)
    return {"rc": rc, "nominal_sps": sps, "seconds": seconds,
            "ratio": delivered / sps, "under": raw.get("under"),
            "consumed": consumed, "runus": runus, "via": r.play.via}


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rc", type=int, default=36)
    ap.add_argument("--reps", type=int, default=12)
    ap.add_argument("--seconds", default="1,3,9",
                    help="durations, interleaved within each rep")
    ap.add_argument("--bench", default=os.environ.get("DUE_BENCH"))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    durs = [float(x) for x in args.seconds.split(",") if x.strip()]

    board = measure.Board(settle=3.0)
    prov = provenance.run_fields(board)
    rows = []
    try:
        for rep in range(args.reps):
            # Reverse on odd reps so a monotone session drift cannot
            # land on one duration more than another.
            order = durs if rep % 2 == 0 else list(reversed(durs))
            for secs in order:
                row = one(board, args.rc, secs)
                if row is None:
                    continue
                row.update(rep=rep, bench=args.bench, issue=48,
                           test="is-the-mode-fixed-for-the-run", **prov)
                rows.append(row)
                print(f"rep {rep:>3} {secs:>4g}s: ratio {row['ratio']:.6f}  "
                      f"under {row['under']}", flush=True)
                board.stop()
    finally:
        board.stop(); board.close()

    out = args.out or os.path.join(
        ROOT, "records", f"issue48-dwell-{args.bench or 'unknown'}.jsonl")
    with open(out, "w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    print(f"\nwrote {len(rows)} rows to {out}")

    # Rep 0 by index, and underrun reps are draws from neither mode.
    clean = [r for r in rows if r["rep"] != 0 and not r["under"]]
    print(f"\n{'dur':>5} {'n':>4} {'deep':>10} {'shallow':>10} "
          f"{'gap':>9} {'gap*256':>8} {'between':>8}")
    for secs in durs:
        vals = sorted(r["ratio"] for r in clean if r["seconds"] == secs)
        if len(vals) < 4:
            print(f"{secs:>5g} {len(vals):>4} - too few")
            continue
        # Split at the largest gap: the modes are found, not assumed.
        gaps = [(vals[i + 1] - vals[i], i) for i in range(len(vals) - 1)]
        biggest, at = max(gaps)
        lo, hi = vals[:at + 1], vals[at + 1:]
        deep, shal = statistics.mean(lo), statistics.mean(hi)
        # A run is "between" if it sits more than a quarter of the gap
        # away from both mode centres - the signature of averaging.
        q = biggest / 4.0
        between = sum(1 for v in vals
                      if abs(v - deep) > q and abs(v - shal) > q)
        print(f"{secs:>5g} {len(vals):>4} {deep:>10.6f} {shal:>10.6f} "
              f"{biggest:>9.6f} {biggest*256:>8.3f} {between:>8}")

    print("\nSame gap at every duration and `between` = 0 says the mode is "
          "fixed when playback starts.\nA gap that shrinks with duration, "
          "or runs landing between the modes, says it is re-decided\nwhile "
          "the run is going.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
