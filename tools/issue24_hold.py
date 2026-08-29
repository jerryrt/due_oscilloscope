#!/usr/bin/env python3
"""#24's ratio axis, with a fold that survives a held level.

The ratio arm is a labelled hole on #24: above DAC:ADC ratio 1 the
converter samples one held level several times, those repeats do not
agree in a way differencing removes, and the residual buries a 1-10
site artifact. Both obvious pairings - difference the first two of a
hold, difference the last two - were tried and neither is readable.

**The third option is not to difference at all.** Differencing is
`pair_fold`'s trick and it exists to cancel a staircase from a profile
that has to stay flat. The host-fed reader does not need it: it takes a
*neighbour residual* of the folded profile, which is what lets it work
with a sawtooth still underneath (`issue24_fold.masked_sites`). So:

  1. **Decimate** to one sample per DAC update - take the same position
     within every hold - which puts the series back in exactly the shape
     it has at ratio 1, one captured value per table entry.
  2. Fold at the ramp period and read sites off the neighbour residual,
     with the wrap masked, exactly as at ratio 1.

Whatever the repeats disagree about is then not in the series at all,
because only one of them is ever read. And the ADC effect that killed
the differencing arms is a function of the held *voltage*, so it is a
function of table index, so it lands in the same fold bin every wrap and
becomes part of the smooth profile the neighbour residual subtracts.

**Every hold offset is reported, and none is chosen.** A
DAC-update-locked artifact must appear at whichever sample of the hold
you read; picking the offset that looks best would be selecting the
answer, which on this artifact is how two benches spent a day reading an
argmax. If the offsets disagree, that is the finding and it is not a
site table.

    .venv/Scripts/python.exe tools/issue24_hold.py -n 6 --holds 1,2,4

Ratio is set by holding the ADC rate fixed and moving the DAC rate, so
the capture side is identical across arms and only the ratio moves -
`35ccd6a` already showed DAC rate alone does not move the spacing.
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
sys.path.insert(0, os.path.join(ROOT, "tools"))
from issue24_fold import masked_sites, wrap_relative  # noqa: E402


def decimate(vals, hold, offset):
    """One captured sample per DAC update, taken at a fixed position."""
    return list(vals[offset::hold]) if hold > 1 else list(vals)


def spacings(sites, limit=12):
    bs = sorted(b for b, _v, _z in sites[:limit])
    return [bs[i + 1] - bs[i] for i in range(len(bs) - 1)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--runs", type=int, default=6)
    ap.add_argument("-s", "--seconds", type=float, default=3.0)
    ap.add_argument("--holds", default="1,2",
                    help="captured samples per DAC update; the ADC rate "
                         "is held fixed and the DAC rate divided")
    ap.add_argument("--adc-hz", type=int, default=200000,
                help="per-channel A0 rate. 200000 is where the "
                     "artifact is known visible; at 400000 the "
                     "fold MAD rises ~6x and buries it, which "
                     "makes any null there unreadable")
    ap.add_argument("--step", type=int, default=measure.RAMP_STEP)
    ap.add_argument("--bench", default=os.environ.get("DUE_BENCH", "macos"))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    holds = [int(h) for h in args.holds.split(",") if h.strip()]
    period = 4096 // args.step
    board = measure.Board(settle=3.0)
    rows = []
    try:
        board.stop()
        board.drain_console(0.5)
        for i in range(1, args.runs + 1):
            for hold in holds:                 # interleaved, not blocked
                # `adc_hz` is the per-channel A0 rate, not the aggregate
                # across the two channels, so there is no factor of two
                # here. Dividing by one anyway is how the first run of
                # this tool shipped a "hold 1" arm that was really hold 2
                # and so had no ratio-1 control in it at all - the fold
                # found nothing in every arm and the null meant nothing.
                # `n_per_bin` is the tell: it doubles with `adc_hz`.
                dac_sps = args.adc_hz // hold
                res = measure.run_loop(board, dac_sps=dac_sps,
                                       adc_hz=args.adc_hz, channels=2,
                                       ramp=args.step, seconds=args.seconds)
                ps = res.stream
                vals = ps.series.get(measure.CH_A0) or []
                start = ps._index_at(measure.CH_A0, measure.SETTLE_US)
                tail = list(vals[start:])
                row = {"run": i, "t": time.strftime("%Y-%m-%dT%H:%M:%S"),
                       "bench": args.bench, "hold": hold,
                       "adc_hz": args.adc_hz, "dac_sps": dac_sps,
                       "ramp_step": args.step, "period": period,
                       "seq_gaps": ps.seq_gaps, "crc_bad": ps.crc_bad,
                       "offsets": []}
                print(f"run {i} hold {hold} (adc {args.adc_hz}, "
                      f"dac {dac_sps}):", flush=True)
                for off in range(hold):
                    dec = decimate(tail, hold, off)
                    got = masked_sites(dec, period)
                    if got is None:
                        print(f"    offset {off}: too short", flush=True)
                        row["offsets"].append(None)
                        continue
                    sites, mad, n, wrap = got
                    entry = {
                        "offset": off, "mad": round(mad, 4),
                        "n_per_bin": n, "n_sites": len(sites),
                        "wrap": wrap,
                        "sites": [[b, round(v, 3), round(z, 1)]
                                  for b, v, z in sites[:12]],
                        "sites_table": [[wrap_relative(b, wrap, period),
                                         round(v, 3), round(z, 1)]
                                        for b, v, z in sites[:12]],
                        "spacings": spacings(sites)}
                    row["offsets"].append(entry)
                    top = ", ".join(f"{b}:{v:+.1f}"
                                    for b, v, _z in entry["sites"][:5])
                    print(f"    offset {off}: sites={len(sites):3d} "
                          f"mad={mad:.3f} n/bin={n:4d} "
                          f"spacings={entry['spacings'][:8]}  {top or '-'}",
                          flush=True)
                rows.append(row)
                board.stop()
                board.drain_console(0.3)
    finally:
        try:
            board.stop()
        finally:
            board.close()

    print("\nspacing census per hold (all offsets pooled):")
    for hold in holds:
        tally = {}
        for r in rows:
            if r["hold"] != hold:
                continue
            for e in r["offsets"]:
                if e:
                    for g in e["spacings"]:
                        tally[g] = tally.get(g, 0) + 1
        top = sorted(tally.items(), key=lambda kv: -kv[1])[:6]
        print(f"  hold {hold}: {top}")

    if args.out:
        with open(args.out, "a") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
        print(f"\nwrote {len(rows)} rows to {args.out}")


if __name__ == "__main__":
    main()
