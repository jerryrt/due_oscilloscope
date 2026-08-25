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

Reports per run, and the empty gap around the threshold so the threshold
stays auditable - see measure.level_census().
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
    ap.add_argument("--tag", type=int, default=measure.CH_A0)
    args = ap.parse_args()

    board = measure.Board(settle=3.0)
    rows = []
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
            rows.append(c)
            print(f"run {i}: splices={c['count']:6d}  "
                  f"max_step={c['max_step']:6.1f}  "
                  f"levels={c['levels']:7d}  "
                  f"empty {c['gap'][0]}..{c['gap'][1]} around "
                  f"{args.threshold:g}", flush=True)
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
    # A threshold sitting on an occupied bin is a number to re-derive,
    # not a result to quote.
    tight = [r for r in rows if r["gap"][1] - r["gap"][0] < 4]
    if tight:
        print(f"WARNING: the void around {args.threshold:g} is under 4 codes "
              f"wide on {len(tight)} run(s); re-derive the threshold before "
              f"quoting these counts")


if __name__ == "__main__":
    main()
