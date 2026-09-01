"""#24's fourth candidate: is the site instability the DRIVE PATH or the
WAVEFORM SHAPE?

issue24_two_readings.py eliminated three of the four explanations for
windows-desk's #24 site sets being near-disjoint (0.019 at hold 2)
while the #5 internal-gen arm reproduces at 0.73 on the same bench:

  the hold        - no: hold_ok 12/12 at hold 2, still 0.019
  the instrument  - no: same captures read both ways, same answer
  the bench       - no: this bench's own #5 arm reads 0.7296

What was left is the signal source, and "signal source" is two things
at once:

  DRIVE PATH   host-fed play buffer  vs  the on-board generator
  SHAPE        a rising sawtooth     vs  a sine

The #5 arm is internal + sine. The #24 arm is host-fed + ramp. Both
differ, so neither has been isolated. This runs internal + RAMP, which
is the missing cell: same drive path as #5, same shape as #24.

  internal sine   0.7296  (have it, records/issue5-sites-windows.jsonl)
  internal ramp   THIS
  host-fed ramp   0.0186  (have it, issue24-two-readings-hold2)

PRE-REGISTERED before the first run:

  A. internal ramp reproduces (>= 0.5)
     -> SHAPE is not the variable; the DRIVE PATH is. #24's instability
        belongs to the host-fed play buffer, and that is a host-side
        story - buffer boundaries, refill timing - not a DAC one.

  B. internal ramp is near-disjoint (<= 0.1)
     -> the DRIVE PATH is not the variable; the SHAPE is. A sawtooth's
        per-wrap discontinuity is what makes sites unstable, and #5 and
        #24 differ because one has a wrap and the other does not.

  C. intermediate (0.1 - 0.5)
     -> both contribute; report as such and do not pick one.

THE WRAP CONFOUND, named before it can be discovered afterwards: a
sawtooth has a full-scale step once per table, and that step is at a
fixed bin, so it is a site that reproduces trivially. It would inflate
the ramp's Jaccard toward A for a reason that has nothing to do with
the defect. fold_sites' own docstring flags it - "the full-scale step
puts a residual either side of it that dwarfs anything else".

So this reports Jaccard THREE ways and the pre-registration is read
against `drop_top`, which is the one with the wrap removed:

  all       every site
  drop_top  each run's largest-magnitude site removed (the wrap)
  z_high    only sites at z >= 20, where the wrap lives anyway

If the three disagree, that disagreement IS the finding and no single
number should be quoted.

Interleaved shape by shape, never blocked: a drift over the run then
lands on both shapes rather than on whichever ran second.
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


def jaccard(a, b):
    a, b = set(a), set(b)
    union = a | b
    if not union:
        return None          # both runs found nothing; not a pair
    return len(a & b) / float(len(union))


def pairwise(site_sets):
    vals = []
    for i in range(len(site_sets)):
        for j in range(i + 1, len(site_sets)):
            v = jaccard(site_sets[i], site_sets[j])
            if v is not None:
                vals.append(v)
    if not vals:
        return None
    return {"n_pairs": len(vals), "mean": round(statistics.mean(vals), 4),
            "min": round(min(vals), 4), "max": round(max(vals), 4)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--reps", type=int, default=10,
                    help="reps per shape; shapes are interleaved")
    ap.add_argument("-s", "--seconds", type=float, default=3.0)
    ap.add_argument("--preset", default="M")
    ap.add_argument("--shapes", default="sine,ramp")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    shapes = [s.strip() for s in args.shapes.split(",") if s.strip()]
    board = measure.Board(settle=3.0)
    rows = []
    try:
        board.stop()
        board.drain_console(0.5)
        prov = provenance.run_fields(board)
        print("provenance: " + ", ".join("%s=%s" % (k, v)
                                         for k, v in prov.items()), flush=True)
        print("preset %s, %d reps per shape, interleaved, pair_fold at %d"
              % (args.preset, args.reps, measure.GEN_TABLE_LEN), flush=True)
        last_shape = None
        for rep in range(1, args.reps + 1):
            for shape in shapes:                 # interleaved, not blocked
                if shape != last_shape:
                    measure.set_gen(board, shape,
                                    points=measure.GEN_TABLE_POINTS,
                                    amp=measure.GEN_AMP_FULL)
                    last_shape = shape
                res = measure.run_capture(board, preset=args.preset,
                                          seconds=args.seconds)
                ps = res.stream
                vals = ps.series.get(measure.CH_A0) or []
                if not vals:
                    print("rep %2d %-8s: no samples" % (rep, shape), flush=True)
                    continue
                start = ps._index_at(measure.CH_A0, measure.SETTLE_US)
                fold = measure.pair_fold(list(vals[start:]))
                prof = fold.get("profile") or []
                found, mad = measure.fold_sites(prof)
                row = {"rep": rep, "shape": shape,
                       "t": time.strftime("%Y-%m-%dT%H:%M:%S"),
                       "issue": 24, "also": [5],
                       "team": "windows-platform-team", "bench": "windows-desk",
                       "preset": args.preset, "period": measure.GEN_TABLE_LEN,
                       "hold_ok": bool(fold.get("hold_ok")),
                       "pair_spread": (round(fold["pair_spread"], 3)
                                       if fold.get("pair_spread") is not None
                                       else None),
                       "mad": round(mad, 4),
                       "seq_gaps": ps.seq_gaps, "crc_bad": ps.crc_bad,
                       "n_sites": len(found),
                       "sites": [[b, round(v, 3), round(z, 1)]
                                 for b, v, z in found[:16]]}
                row.update(prov)
                rows.append(row)
                top = ", ".join("%d:%+.1f" % (b, v) for b, v, _z in found[:4])
                print("rep %2d %-8s hold_ok=%-5s n=%-3d %s"
                      % (rep, shape, row["hold_ok"], len(found), top),
                      flush=True)
    finally:
        try:
            board.close()
        except Exception:
            pass

    print()
    summary = {"issue": 24, "also": [5], "test": "drive-path-vs-shape",
               "team": "windows-platform-team", "bench": "windows-desk",
               "preset": args.preset, "period": measure.GEN_TABLE_LEN,
               "reps": args.reps, "shapes": shapes}
    for shape in shapes:
        got = [r for r in rows if r["shape"] == shape
               and not r["seq_gaps"] and not r["crc_bad"]]
        allsets, droptop, zhigh = [], [], []
        for r in got:
            s = r["sites"]
            allsets.append([b for b, _v, _z in s])
            # largest MAGNITUDE first is fold_sites' own order, so the
            # wrap is s[0] when it is present at all.
            droptop.append([b for b, _v, _z in s[1:]])
            zhigh.append([b for b, _v, z in s if z >= 20.0])
        summary[shape] = {
            "n": len(got),
            "hold_ok_true": sum(1 for r in got if r["hold_ok"]),
            "n_sites": [r["n_sites"] for r in got],
            "jaccard_all": pairwise(allsets),
            "jaccard_drop_top": pairwise(droptop),
            "jaccard_z_high": pairwise(zhigh),
        }
    print(json.dumps(summary, indent=2))

    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
            fh.write(json.dumps(summary) + "\n")
        print("wrote %s" % args.out)


if __name__ == "__main__":
    main()
