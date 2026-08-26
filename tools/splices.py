"""Count the splices in a device-generated capture, run after run.

The measurement issue #5 needed and did not have. `M` drives the DAC
from the device's own flash sine, so the host is out of the DAC path
entirely and anything discontinuous in what comes back was made on the
board - which is what a stale IN transfer racing the ADC's PDC over the
same buffer produces.

Why a separate instrument rather than the suite's continuity test: that
test judges the maximum step against slew_limit(), a continuous-sine
derivative, and the device's sine is a staircase - each DAC level held
for exactly two ADC samples, stepping up to ~38 codes against an
analytic 16.85. The "3x margin" was therefore 1.3x of real headroom, and
a defect that moved the maximum from 39 to 58 could only make that test
wobble. The count moves from 0 to 780 over the same firmware change.
Count the steps; do not judge the maximum.

    python3 tools/splices.py -n 4

**Both channels are censused, and the flat one is the sensitive one.**
`M` drives DAC1 with DC 2048, so A1 is a flat line and a displaced
sample is unmistakable there; A0 carries the sine and needs the
staircase census. This matters because the two thresholds are far apart:
on macOS the displacement is 26-32 codes, which forms its own level on
A0 and lands *under* STEP_SPLICE_CODES = 45. Ten runs reported 0 splices
on A0 across a period when six runs in ten were dirty on A1 - the tool
said "does not reproduce" about a board that was reproducing it. Judge
by whichever channel is above its threshold, never by A0 alone.

Reports per run, and the empty gap around each threshold so both stay
auditable - see measure.level_census() and measure.flat_census().
"""
import argparse, os, sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "host"))
import measure  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--runs", type=int, default=4)
    ap.add_argument("-s", "--seconds", type=float, default=3.0)
    ap.add_argument("--preset", default="M")
    ap.add_argument("--threshold", type=float,
                    default=measure.STEP_SPLICE_CODES)
    ap.add_argument("--flat-threshold", type=float,
                    default=measure.FLAT_DEV_CODES)
    ap.add_argument("--tag", type=int, default=measure.CH_A0,
                    help="staircase channel, censused by level_census")
    ap.add_argument("--flat-tag", type=int, default=measure.CH_A1,
                    help="flat channel, censused by flat_census; "
                         "-1 to skip it")
    args = ap.parse_args()

    board = measure.Board(settle=3.0)
    rows, flats = [], []
    try:
        board.stop()
        board.drain_console(0.5)
        for i in range(1, args.runs + 1):
            res = measure.run_capture(board, preset=args.preset,
                                      seconds=args.seconds)
            ps = res.stream
            vals = ps.series.get(args.tag, [])
            start = ps._index_at(args.tag, measure.SETTLE_US)
            c = measure.level_census(vals[start:], threshold=args.threshold)
            # A stream that never started censuses as zero splices, which
            # is the one way this tool can report a clean run from no data
            # at all. The device refuses to start when a previous stop
            # left an IN transfer running, so that case is reachable.
            want = args.seconds * ps.declared_rate_hz * 0.5
            if c["levels"] < want * 0.5:
                raise SystemExit(
                    f"run {i}: only {c['levels']} levels from "
                    f"{len(vals)} samples at {ps.declared_rate_hz} Hz - "
                    f"the stream did not run, so its zero means nothing. "
                    f"Check the console for a refusal.")
            rows.append(c)
            print(f"run {i}: splices={c['count']:6d}  "
                  f"max_step={c['max_step']:6.1f}  "
                  f"levels={c['levels']:7d}  "
                  f"empty {c['gap'][0]}..{c['gap'][1]} around "
                  f"{args.threshold:g}", flush=True)

            if args.flat_tag >= 0:
                fv = ps.series.get(args.flat_tag, [])
                fs = ps._index_at(args.flat_tag, measure.SETTLE_US)
                fv = fv[fs:]
                # The levels guard above cannot be reused here: a flat
                # channel has no levels to count, and asking it for some
                # is what made --tag 6 abort with "the stream did not
                # run" on a stream that ran perfectly well. Liveness on
                # this channel is the sample count.
                if len(fv) < want * 0.5:
                    raise SystemExit(
                        f"run {i}: only {len(fv)} samples on the flat "
                        f"channel at {ps.declared_rate_hz} Hz - the stream "
                        f"did not run, so its zero means nothing.")
                f = measure.flat_census(fv, threshold=args.flat_threshold)
                flats.append(f)
                print(f"        flat  events={f['count']:6d}  "
                      f"max_dev={f['max_dev']:6.1f}  "
                      f"sd={f['sd']:5.2f}  "
                      f"period={f['period']}"
                      f"{' PERIODIC' if f['periodic'] else ''}  "
                      f"empty {f['gap'][0]}..{f['gap'][1]} around "
                      f"{args.flat_threshold:g}", flush=True)

            board.stop()
            board.drain_console(0.3)
    finally:
        try:
            board.stop()
        finally:
            board.close()

    counts = [r["count"] for r in rows]
    print(f"\n{len(rows)} runs of {args.seconds:g}s at preset {args.preset}: "
          f"splices {min(counts)}-{max(counts)}, "
          f"max step {max(r['max_step'] for r in rows):.1f}")
    if flats:
        fc = [f["count"] for f in flats]
        print(f"  flat channel: events {min(fc)}-{max(fc)}, "
              f"dirty on {sum(1 for x in fc if x):d} of {len(fc)} runs, "
              f"max deviation {max(f['max_dev'] for f in flats):.1f}")
        periods = {f["period"] for f in flats if f["periodic"]}
        if periods:
            print(f"  periodic at {sorted(periods)} - the issue #5 "
                  f"signature is a metronome at GEN_TABLE_LEN, not a splice")

    # A threshold sitting on an occupied bin is a number to re-derive,
    # not a result to quote.
    def warn(name, rs, thr):
        tight = [r for r in rs if r["gap"][1] - r["gap"][0] < 4]
        if tight:
            print(f"WARNING: the {name} void around {thr:g} is under 4 codes "
                  f"wide on {len(tight)} run(s); re-derive the threshold "
                  f"before quoting these counts")
    warn("step", rows, args.threshold)
    warn("flat", flats, args.flat_threshold)


if __name__ == "__main__":
    main()
