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
import provenance  # noqa: E402


def sites(profile, z_min=measure.FOLD_Z_DIRTY):
    """The whole profile's sites, via the shared reading.

    This lived here as its own copy until the host-fed path needed the
    same reading; it is `measure.fold_sites` now, so both #5's internal
    arm and #24's host-fed arm are read by one rule rather than by two
    that could drift apart. The profile goes in **as it is** - see that
    function on why neighbour-subtracting a pair_fold profile invents
    sites either side of a real one.
    """
    return measure.fold_sites(profile, z_min=z_min)


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
    ap.add_argument("--fws-plan", default="",
                    help="flash wait states per block, e.g. "
                         "4x6,5x6,6x6,6x6,5x6,4x6 - all inside one board "
                         "session, and counterbalanced so a drift over "
                         "the session cannot masquerade as an FWS "
                         "effect. FWS changes instruction fetch timing, "
                         "which #5 is a lottery over; the readback is "
                         "checked because `=<n>q` is silent when it "
                         "does not take")
    ap.add_argument("--preset", default="M",
                    help="capture preset, e.g. '=200000,200000M' to pin "
                         "both clocks. Bare 'M' leaves whatever the "
                         "board booted with, which is not comparable "
                         "across benches")
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
    fws_plan = []
    if args.fws_plan:
        for part in args.fws_plan.split(","):
            f, n = part.lower().split("x")
            fws_plan.extend([int(f)] * int(n))
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
        # Issue #53: ask the board, never write a literal - and this
        # tool wrote no provenance at all. Its rows carried `bench` from
        # a command-line string and nothing else, so a site table taken
        # here could not be attributed to a track, a commit or an image.
        # That is the tool #5 is argued with, and #5's site is a lottery
        # over code layout, so `fw_layout` is not decoration on these
        # rows - it is the variable.
        #
        # Collected once, before the loop, rather than per capture: it
        # is a console query, and invariant 8 keeps console traffic out
        # of a running sample path. The image cannot change mid-session.
        prov = provenance.run_fields(board)
        print("provenance: " + ", ".join(f"{k}={v}" for k, v in prov.items()),
              flush=True)
        for i in range(1, args.runs + 1):
            amp = plan[i - 1] if i <= len(plan) else None
            if amp is not None and (i == 1 or plan[i - 2] != amp):
                measure.set_gen(board, "sine",
                                points=measure.GEN_TABLE_POINTS, amp=amp)
            fws = fws_plan[i - 1] if i <= len(fws_plan) else None
            if fws is not None and (i == 1 or fws_plan[i - 2] != fws):
                board.cmd(f"={fws}q")
                txt = board.drain_console(0.5) or ""
                if f"fws: {fws}" not in txt:
                    raise SystemExit(
                        f"run {i}: FWS readback {txt.strip()[:60]!r} - "
                        f"asked for {fws}. `=<n>q` is silent when it does "
                        f"not take, so this stops rather than recording "
                        f"runs under an unknown wait-state count.")
            if i in regen:
                measure.set_gen(board, "sine",
                                points=measure.GEN_TABLE_POINTS,
                                amp=measure.GEN_AMP_FULL)
            res = measure.run_capture(board, preset=args.preset,
                                      seconds=args.seconds)
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
                   "bench": args.bench, "regen": i in regen, **prov,
                   "amp": amp, "fws": fws, "preset": args.preset,
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
                  f"{('a%d' % amp) if amp is not None else '':>5}"
                  f"{('f%d' % fws) if fws is not None else '':>3}: "
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

    # Per-FWS site tables. The cross-bench comparison on #5 is quoted
    # per FWS, so pooling them here would hide exactly the structure the
    # comparison is about.
    if fws_plan and rows:
        for f in sorted({r["fws"] for r in rows if r["fws"] is not None}):
            sub = [r for r in rows if r["fws"] == f]
            strong = []
            for b in sorted({b for r in sub for b, _v, _z in r["sites"]}):
                k = sum(1 for r in sub
                        if any(bb == b for bb, _v, _z in r["sites"]))
                if k >= max(2, len(sub) // 2):
                    strong.append((b, k))
            print(f"\nFWS {f}: n={len(sub)}, strong sites "
                  f"(>= {max(2, len(sub) // 2)} of {len(sub)}): "
                  + (", ".join(f"{b}({k})" for b, k in strong) or "none"))
            print(f"  bare list: {[b for b, _k in strong]}")

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
