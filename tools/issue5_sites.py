#!/usr/bin/env python3
"""How many samples per wrap are displaced, and which of them flips?

Two benches read the same statistic and disagreed. This bench saw the
landing phase alternate between 138 and 177 with the magnitude following
it; windows-desk saw the phase hold at 156 while the value flipped,
sign included. Both were reading `fold_profile`'s `peak_phase`, which is
an **argmax** - so a single number cannot tell "the artifact moved" from
"there are two artifacts and the bigger one shrank".

This reports the whole folded profile instead of its maximum. Every bin
whose neighbour residual clears the same z the suite uses is a site, and
the run-by-run table of sites answers the question directly:

  * sites appear and disappear      -> the artifact moves
  * sites always present, values move -> the artifact is several fixed
                                         samples, and their values flip

    .venv/bin/python tools/issue5_sites.py -n 12

`pair_fold` remains the instrument; only the reading changes.
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


def sites(profile, z_min=measure.FOLD_Z_DIRTY):
    """Every bin that stands out, not just the largest.

    Read off the profile directly, and **not** off `spike`'s neighbour
    residual. `spike` subtracts each bin's neighbours because
    fold_profile has to survive a waveform underneath it; after
    pair_fold's differencing within the DAC hold there is no waveform
    left, so the profile is already flat and the subtraction only adds
    a shadow. A single spike of A becomes A at its own bin and -A/2 at
    each neighbour, and reading that as three sites is how 176 and 178
    were briefly reported here alongside a real site at 177.
    """
    centre = statistics.median(profile)
    devs = [abs(v - centre) for v in profile]
    mad = statistics.median(devs) * 1.4826 or 1e-9
    out = [(b, profile[b] - centre, abs(profile[b] - centre) / mad)
           for b in range(len(profile))
           if abs(profile[b] - centre) / mad >= z_min]
    out.sort(key=lambda t: -abs(t[1]))
    return out, mad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--runs", type=int, default=12)
    ap.add_argument("-s", "--seconds", type=float, default=3.0)
    ap.add_argument("--regen", default="",
                    help="run numbers (e.g. 9-16) to precede with a "
                         "set_gen, so a table rebuild can be tested as "
                         "the event that draws the configuration - all "
                         "inside one board session, because opening the "
                         "control port resets the board and a reset is "
                         "itself a candidate")
    ap.add_argument("--amp-plan", default="",
                    help="amplitude per block, e.g. 256x6,64x4,256x8 - "
                         "all inside one board session, so an excursion "
                         "to a reduced amplitude can be tested as the "
                         "event that redraws the site set. Compare the "
                         "blocks at the same amplitude either side of it")
    ap.add_argument("--bench", default=os.environ.get("DUE_BENCH", "macos"))
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    regen = set()
    if args.regen:
        for part in args.regen.split(","):
            if "-" in part:
                a, b = part.split("-")
                regen.update(range(int(a), int(b) + 1))
            else:
                regen.add(int(part))
    plan = []
    if args.amp_plan:
        for part in args.amp_plan.split(","):
            a, n = part.lower().split("x")
            plan.extend([int(a)] * int(n))
    board = measure.Board(settle=3.0)
    rows = []
    try:
        board.stop()
        board.drain_console(0.5)
        for i in range(1, args.runs + 1):
            amp = plan[i - 1] if i <= len(plan) else None
            if amp is not None and (i == 1 or plan[i - 2] != amp):
                measure.set_gen(board, "sine",
                                points=measure.GEN_TABLE_POINTS, amp=amp)
            if i in regen:
                measure.set_gen(board, "sine",
                                points=measure.GEN_TABLE_POINTS,
                                amp=measure.GEN_AMP_FULL)
            res = measure.run_capture(board, preset="M", seconds=args.seconds)
            ps = res.stream
            vals = ps.series.get(measure.CH_A0)
            if not vals:
                print(f"run {i}: no samples", flush=True)
                continue
            start = ps._index_at(measure.CH_A0, measure.SETTLE_US)
            fold = measure.pair_fold(list(vals[start:]))
            found, mad = sites(fold.get("profile") or [])
            # A threshold-free total, so the conservation question -
            # do the sites share a budget, or move independently? -
            # does not depend on which of them happened to clear z.
            prof = fold.get("profile") or []
            pmed = statistics.median(prof) if prof else 0.0
            total_abs = sum(abs(v - pmed) for v in prof)
            row = {"run": i, "t": time.strftime("%Y-%m-%dT%H:%M:%S"),
                   "bench": args.bench, "regen": i in regen,
                   "amp": amp,
                   "total_abs": round(total_abs, 2),
                   "site_abs": round(sum(abs(v) for _b, v, _z in found), 2),
                   "argmax_phase": fold.get("peak_phase"),
                   "argmax_peak": round(fold.get("peak", 0.0), 2),
                   "hold_ok": bool(fold.get("hold_ok")),
                   "mad": round(mad, 4),
                   "sites": [[b, round(v, 2), round(z, 1)]
                             for b, v, z in found[:6]]}
            rows.append(row)
            print(f"run {i:2d}{'*' if i in regen else ' '}"
                  f"{('a%d' % amp) if amp is not None else '':>5}: "
                  f"argmax {row['argmax_phase']:3d} "
                  f"({row['argmax_peak']:+7.2f})  total|dev| "
                  f"{row['total_abs']:7.1f}  sites "
                  + ", ".join(f"{b}:{v:+.2f}" for b, v, _ in found[:5]),
                  flush=True)
            board.stop()
            board.drain_console(0.3)
    finally:
        try:
            if plan:
                measure.set_gen(board, "sine",
                                points=measure.GEN_TABLE_POINTS,
                                amp=measure.GEN_AMP_FULL)
            board.stop()
        finally:
            board.close()

    # The table the question actually needs: every phase ever seen, and
    # what it read in each run. A blank is a site that was not there.
    seen = sorted({b for r in rows for b, _v, _z in r["sites"]})
    if seen and rows:
        print("\nrun  " + "  ".join(f"{b:>8d}" for b in seen))
        for r in rows:
            by = {b: v for b, v, _z in r["sites"]}
            print(f"{r['run']:3d}  " + "  ".join(
                (f"{by[b]:+8.2f}" if b in by else "       .") for b in seen))
        print("\npresent in n runs of %d:" % len(rows))
        for b in seen:
            vs = [v for r in rows for bb, v, _z in r["sites"] if bb == b]
            print(f"  phase {b:3d}: {len(vs):2d}/{len(rows)}  "
                  f"values {min(vs):+.2f} .. {max(vs):+.2f}")

    if len(rows) > 2:
        tot = [r["total_abs"] for r in rows]
        print(f"\ntotal |deviation| over the whole profile: "
              f"{min(tot):.1f} .. {max(tot):.1f}, "
              f"median {sorted(tot)[len(tot) // 2]:.1f}")
        # Co-variation, on the sites present often enough to have one.
        common = [b for b in seen
                  if sum(1 for r in rows
                         if any(bb == b for bb, _v, _z in r["sites"]))
                  >= max(4, len(rows) // 2)]
        if len(common) > 1:
            series = {}
            for b in common:
                series[b] = [next((v for bb, v, _z in r["sites"] if bb == b),
                                  0.0) for r in rows]
            print("pairwise correlation of site values across runs:")
            for i2 in range(len(common)):
                for j in range(i2 + 1, len(common)):
                    x, y = series[common[i2]], series[common[j]]
                    n = len(x)
                    mx, my = sum(x) / n, sum(y) / n
                    sxy = sum((a - mx) * (b2 - my) for a, b2 in zip(x, y))
                    sxx = sum((a - mx) ** 2 for a in x)
                    syy = sum((b2 - my) ** 2 for b2 in y)
                    r_ = sxy / ((sxx * syy) ** 0.5) if sxx and syy else 0.0
                    print(f"  {common[i2]:3d} vs {common[j]:3d}: r = {r_:+.2f}")

    if args.json:
        with open(args.json, "a") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
        print(f"\nwrote {len(rows)} rows to {args.json}")


if __name__ == "__main__":
    main()
