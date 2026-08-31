#!/usr/bin/env python3
"""#48 from the host's side, on a bench whose host tells the truth.

Every figure on issue #48 so far comes from the device's own arithmetic
- `consumed * PLAY_BUF_SAMPLES` over the device's own `runus` - and
deliberately so: no host clock is in it, which is what keeps three
different CDC stacks out of the answer. `tools/issue48_lattice.py` is
that instrument and this does not replace it.

But on a **backpressuring** host there is a second, independent view of
the same quantity, and nobody is reading it.

    device side    consumed * 512 / runus        no host term in it
    host side      host_tx_bytes / elapsed       no device counter in it

The two share no term. If the DACC converts below the rate it was
programmed for, a host that blocks the writer cannot feed faster than
the converter takes, so the host's own byte rate falls by the same
fraction. Two instruments with nothing in common agreeing is worth more
than either alone, and this issue has spent a great deal of effort
excluding the data path - a host-side confirmation of a device-side
deficit is the cross-check that argument is missing.

**This only works where the host backpressures.** On macOS the stack
buffers ahead and sheds the surplus, so `host_tx_bytes` reads ~100% of
nominal at every rate and measures nothing: the shedding is exactly what
destroys the signal. Windows and native Linux block the writer instead.
So this tool is meaningful on windows-desk and linux-x1 and is not
meaningful on mac-bench - which is stated here rather than left for
somebody to discover from a flat column of 1.000.

It was found by a test failure rather than looked for:
`test_awg_ladder_play_only[b-32]` asserts the host fed >= 95% of nominal,
on the reasoning that `under=0` proves nothing if the device was never
asked for the rate. That premise inverts on a backpressuring host - it
fed 94.5% because the device took 94.5% - and the guard fires on correct
behaviour at exactly the rates #48 is about.

    python3 tools/issue48_hostfeed.py --reps 6
    python3 tools/issue48_hostfeed.py --rcs 32,39,44 --reps 8
"""
import argparse
import json
import os
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "host"))
import measure  # noqa: E402

PLAY_BUF_SAMPLES = 512
TC_CLOCK_HZ = 39_000_000          # SystemCoreClock / 2 at MCK 78 MHz

#: Two bytes per sample on the wire.
BYTES_PER_SAMPLE = 2


def both_ratios(board, rc, seconds):
    """One run, read twice - once by the device, once by the host."""
    sps = TC_CLOCK_HZ // rc
    r = measure.run_play(board, dac_sps=sps, seconds=seconds,
                         ramp=measure.RAMP_STEP)
    raw = r.play.raw
    consumed, runus = raw.get("consumed"), raw.get("runus")
    if not consumed or not runus:
        return None
    dev = (consumed * PLAY_BUF_SAMPLES / (runus / 1e6)) / sps

    fed = getattr(r, "host_tx_bytes", None)
    secs = getattr(r, "elapsed_s", None)
    host = None
    if fed and secs:
        host = (fed / secs) / (sps * BYTES_PER_SAMPLE)
    return {"rc": rc, "nominal_sps": sps, "dev_ratio": dev,
            "host_ratio": host, "under": raw.get("under"),
            "consumed": consumed, "runus": runus,
            "host_tx_bytes": fed, "elapsed_s": secs}


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rcs", default="28,32,34,37,39,40,44,48,50,52,56")
    ap.add_argument("--reps", type=int, default=6)
    ap.add_argument("--seconds", type=float, default=3.0)
    ap.add_argument("--bench", default=os.environ.get("DUE_BENCH", "linux-x1"))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    rcs = [int(x) for x in args.rcs.split(",") if x.strip()]

    board = measure.Board(settle=3.0)
    rows = []
    try:
        # Interleaved by rep, not blocked by rate, so a drift over the
        # run lands on every rate rather than on the last few.
        for rep in range(args.reps):
            for rc in rcs:
                row = both_ratios(board, rc, args.seconds)
                if row is None:
                    continue
                row.update(rep=rep, bench=args.bench, track="b")
                rows.append(row)
                h = row["host_ratio"]
                print(f"rep {rep} RC {rc:>3}: dev {row['dev_ratio']:.5f}  "
                      f"host {'   n/a' if h is None else f'{h:.5f}'}  "
                      f"under {row['under']}")
                board.stop()
    finally:
        board.stop(); board.close()

    out = args.out or os.path.join(ROOT, "records",
                                   f"issue48-hostfeed-{args.bench}.jsonl")
    with open(out, "w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")

    # Drop rep 0 by index, never by a filter on what rep 0 does wrong -
    # CLAUDE.md, and it has cost this project a claim already.
    later = [r for r in rows if r["rep"] > 0]
    print(f"\nwrote {len(rows)} rows to {os.path.relpath(out, ROOT)}")
    print(f"first rep dropped by index; {len(later)} rows analysed\n")
    print(f"{'RC':>4} {'sps':>9} {'device':>9} {'host':>9} {'diff':>9}  n")
    for rc in rcs:
        d = [r["dev_ratio"] for r in later if r["rc"] == rc]
        h = [r["host_ratio"] for r in later
             if r["rc"] == rc and r["host_ratio"] is not None]
        if not d:
            continue
        md = statistics.median(d)
        mh = statistics.median(h) if h else None
        sps = TC_CLOCK_HZ // rc
        print(f"{rc:>4} {sps:>9} {md:>9.5f} "
              f"{'      n/a' if mh is None else f'{mh:>9.5f}'} "
              f"{'      n/a' if mh is None else f'{mh - md:>+9.5f}'}  {len(d)}")
    print("\nThe two columns share no term. Agreement is the finding;")
    print("a host column flat at 1.000 means this host sheds rather than")
    print("blocks, and the measurement does not apply here.")


if __name__ == "__main__":
    main()
