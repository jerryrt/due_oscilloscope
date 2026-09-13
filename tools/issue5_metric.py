#!/usr/bin/env python3
"""The issue #5 comb metric: severity restricted to the lattice sites.

    .venv/bin/python tools/issue5_metric.py
    .venv/bin/python tools/issue5_metric.py --fws 5

Needs no board. Reads `records/issue5-campaign-*.jsonl`.

## Why `total_abs` is not the quantity

`total_abs` sums every position of the fold, so it carries the artifact
**and** the noise floor. At FWS 6 the floor is most of it, and the floor
moves while the artifact does not. Across the three campaign arms:

    arm                 on-lattice range   off-lattice range
    linux-x1 (-run 31)        1.4%               66.2%
    windows-desk              2.7%              110.3%
    mac-bench                 0.5%               85.7%

So a `total_abs` difference between two sessions, or two benches, is
mostly a statement about the floor. `mac-bench` found this from the
correlation with the broadband (+0.94 on their arm against +0.12 for the
comb) and this bench found it from the stability; the two arguments are
independent and the stability one is the safer of them, because a
**correlation on a bimodal arm is not a dependence**: `windows-desk`'s
comb correlates +0.973 with `total_abs` while its range is 2.7%, purely
because two widely separated modes make any slightly-differing quantity
track the hugely-differing one.

## What this measures instead

The sum of |deviation| over the sites on the period-21 lattice - the
large population, median |dev| about 29 codes against 2 for everything
else, replicated on two boards to 2%. `LATTICE` is the ten points that
carry sites; 222 and 243 are on the comb and unoccupied on every arm.

It orders the benches differently from `total_abs`, which is the point:

    arm            jumpers   seven-site   ten-site   total_abs
    mac-bench      copper       193.52     238.16      398.1
    linux-x1       copper       193.75     235.30      395.0
    windows-desk   iron         189.75     210.03      398.7

Those are the median-profile route (`comb_from_profile`). The table the
tool prints leads with the site-list route, which differs by up to 3% -
217.23 against 210.03 on the ten-site sum for `windows-desk` - and prints
both, so a figure quoted from here must say which.

    windows / copper mean      0.980      0.887
    copper pair                0.999      1.012
    three-bench spread         1.021      1.134

**The seven-site figure is the metric and the ten-site one is reported
beside it as a warning.** This file first proposed the ten, and the 9.6%
iron-below-copper gap that came with it is mostly `75` and `180` - two of
the three sites that move with the mode. On the seven that hold still the
gap is **2.0%**, the two copper benches agree to **0.1%**, and the
within-bench range is 0.28-0.75%.

So the first version of this metric was part artifact and part mode
occupancy: the same defect it was written to fix in `total_abs`, one level
down. `windows-desk` found it.

**What that is not.** Three boards, one arm each, n = 1 per jumper
material, board and material perfectly confounded, and the comparison
was made after every arm had been read. It is not evidence about
material. What it is: a readout whose noise floor is known in advance,
so a jumper-material A-B-A on one board can be powered before it is run -
**2.0% against 0.28-0.75%**, not the 9.6% the ten-site version promised.

The exchange sites may be the better readout than any sum: they differ
between benches by factors of 2-4 and move with the mode only on iron.
`windows-desk`'s observation, and it is theirs to pursue.

## The one thing to check before trusting a figure from this

A run whose comb has collapsed is not a low-severity run. `linux-x1`'s
run 31 reads `total_abs` 353.5 against a peer median of 395.0 - 11% low -
while its on-lattice sum is **66.12 against 234.00**, a collapse to 28%.
On a metric that is mostly floor, an artifact that nearly vanished barely
registered. `--per-run` prints both so that case is visible rather than
averaged away.
"""
import argparse
import glob
import json
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RECORDS = os.path.join(ROOT, "records")

import issue5_modes as modes  # noqa: E402

#: The period-21 comb's occupied points at FWS 6. The full lattice is
#: 12 + 21k for k = 0..11; 222 and 243 carry no site on any arm, so the
#: metric is defined over the ten that do. Keeping the unoccupied two in
#: would add nothing and hide nothing - they are listed here so that a
#: reader can see the metric is a subset of a stated lattice rather than
#: a set fitted to the data.
LATTICE_FULL = [12 + 21 * k for k in range(12)]
OCCUPIED = [12, 33, 54, 75, 96, 117, 138, 159, 180, 201]
UNOCCUPIED = [b for b in LATTICE_FULL if b not in OCCUPIED]

#: Three occupied points move with the severity mode on `windows-desk`,
#: by factors of 2-4, and barely at all on the two copper benches. A sum
#: that includes them is therefore part artifact and part mode
#: occupancy - which is the exact defect this file was written to fix in
#: `total_abs`, reproduced one level down. Found by `windows-desk`.
EXCHANGE = [75, 180, 201]

#: The metric. The seven occupied points that hold still.
LATTICE = [b for b in OCCUPIED if b not in EXCHANGE]


def split(row, lattice=LATTICE):
    """(on-lattice sum, off-lattice sum) of |deviation| over the sites.

    Site-list based, so it needs no profile and works on any row that
    stores a complete site list. It is NOT valid on the truncated
    `issue5-onimage-*` rows, where the list is the strongest six and
    would therefore be almost entirely on-lattice by construction.
    """
    on = sum(abs(x) for b, x, _z in row["sites"] if b in lattice)
    off = sum(abs(x) for b, x, _z in row["sites"] if b not in lattice)
    return on, off


def comb_from_profile(rows, lattice=LATTICE):
    """The same quantity by a second route: |median profile| at the points.

    `split()` sums per run over the site list and the caller takes a
    median; this sums the median profile. They are different estimators
    of one thing and they agree to 3% on all three campaign arms - 234.00
    against 235.30, 217.23 against 210.03, 238.06 against 238.16.

    It is here because **two benches computed "the comb sum" and got
    238.1 and 193.2**, a 19% disagreement on the metric this file
    proposes. Several different 7-of-10 subsets of the lattice reproduce
    193 to within a code, so the definition cannot be recovered by
    fitting it to the number - which is the reason a proposed metric
    needs an implementation in the tree rather than a figure in a
    comment. `tests/test_issue5_metric.py` holds the two routes equal so
    a third definition cannot quietly appear here.
    """
    # median of |deviation|, NOT |median of deviation|. This function
    # used the second, and `site_dev` below uses the first, so one file
    # held two conventions. They agree on a unimodal arm and diverge on
    # a bimodal one: on `windows-desk` they read 210.03 and 217.98,
    # 7.95 apart, all of it at two sites - phase 201 (1.63 against 8.07)
    # and phase 75 (1.91 against 3.42).
    #
    # abs-of-median is simply wrong for "how big is the artifact":
    # phase 201 CHANGES SIGN between that bench's two modes, so the
    # median of the signed values sits near zero and the site reports as
    # absent while being 8 codes in every run. A statistic that cancels
    # a site for flipping is measuring the sign, not the size.
    return sum(
        statistics.median(
            [abs(r["profile"][b] - statistics.median(r["profile"]))
             for r in rows])
        for b in lattice)


def site_dev(rows, b):
    """Median |deviation| at one position over EVERY run.

    Not `median(|x| for runs where b is a stored site)`. A site list is
    thresholded at z >= 6, so taking a median over only the runs where a
    position cleared it silently selects which runs contribute - and on
    `windows-desk` that drops mostly high-mode runs, so position 75 read
    5.22 (its low-mode value) where the all-runs figure is 3.42. The
    published "180 is half on iron" comparison was 5.22 against 8.6 and
    should have been 3.42 against 8.6.

    That is the same defect as the six-site truncation this whole arm was
    run to escape: a threshold deciding which data reaches a median.
    Found by `windows-desk`.
    """
    return statistics.median(
        [abs(r["profile"][b] - statistics.median(r["profile"])) for r in rows])


def rng(xs):
    """Peak-to-peak as a fraction of the median - the stability figure."""
    m = statistics.median(xs)
    return (max(xs) - min(xs)) / m if m else float("nan")


def arms():
    out = {}
    for path in sorted(glob.glob(os.path.join(RECORDS,
                                              "issue5-campaign-*.jsonl"))):
        with open(path, encoding="utf-8") as fh:
            rows = [json.loads(l) for l in fh if l.strip()]
        # Run 1 by index, never by a filter on what it does wrong.
        rows = [r for r in rows if r["run"] != 1]
        if rows:
            out[rows[0]["bench"]] = rows
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fws", type=int, default=6)
    ap.add_argument("--per-run", action="store_true",
                    help="every run, so a collapsed comb is visible rather "
                         "than averaged into a median")
    args = ap.parse_args()

    data = arms()
    if not data:
        print("no records/issue5-campaign-*.jsonl")
        return 1
    if any(not r.get("sites") or "n_sites" not in r
           for rows in data.values() for r in rows):
        print("REFUSING: some rows carry no `n_sites`, so their site list "
              "may be the truncated six. This metric would then be almost "
              "entirely on-lattice by construction.", file=sys.stderr)
        return 2

    print(f"FWS {args.fws}, run 1 dropped by index")
    print(f"  metric  = the seven fixed comb sites {LATTICE}")
    print(f"  excluded: {EXCHANGE} move with the severity mode on iron; "
          f"{UNOCCUPIED} carry no site\n")
    print(f"{'bench':16s} {'n':>3} {'on-lattice':>11} {'range':>7} "
          f"{'off-lattice':>12} {'range':>7} {'total_abs':>10} "
          f"{'via profile':>10} {'ten-site':>9}")
    meds = {}
    for bench, rows in sorted(data.items()):
        v = [r for r in rows if r["fws"] == args.fws]
        if not v:
            continue
        on = [split(r)[0] for r in v]
        off = [split(r)[1] for r in v]
        tot = [r["total_abs"] for r in v]
        meds[bench] = statistics.median(on)
        alt = (comb_from_profile(v) if all(r.get("profile") for r in v)
               else float("nan"))
        ten = statistics.median([split(r, OCCUPIED)[0] for r in v])
        print(f"{bench:16s} {len(v):3d} {statistics.median(on):11.2f} "
              f"{100 * rng(on):6.1f}% {statistics.median(off):12.2f} "
              f"{100 * rng(off):6.1f}% {statistics.median(tot):10.1f} "
              f"{alt:10.2f} {ten:9.2f}")
        # A collapsed comb inflates the range figure and would be read as
        # an unstable bench: linux-x1 reads 72.7% with run 31 in and 1.4%
        # without it, against mac-bench's 0.5%. Naming the runs rather
        # than dropping them - a run whose artifact vanished is the most
        # interesting row in the arm, not a nuisance to filter.
        med = statistics.median(on)
        bad = [r["run"] for r, o in zip(v, on) if o < 0.5 * med]
        if bad:
            keep = [o for o in on if o >= 0.5 * med]
            print(f"{'':16s}     ^ that range is run(s) {bad} with a "
                  f"COLLAPSED comb; without them {100 * rng(keep):.1f}%")
    if len(meds) > 1:
        m = list(meds.values())
        print(f"\n  cross-bench spread of the comb: {min(m):.1f} .. {max(m):.1f} "
              f"= {max(m) / min(m):.3f}x")
        print(f"  worst within-bench range above is the noise floor an A-B-A "
              f"would be read against.")

    # The three excluded sites, per bench, so "iron lowest on the
    # artifact" cannot be read as one claim when it is two: 2.0% on the
    # fixed comb, plus a large difference at three sites that move with
    # the mode on iron and not on copper. windows-desk's suggestion, and
    # only their bench separates the two.
    print(f"\n  the excluded exchange sites, median |dev| over ALL runs")
    print(f"  (from the profile, not the site list - a threshold would "
          f"select which runs contribute)")
    print(f"{'':22s} " + "  ".join(f"{b:>8}" for b in EXCHANGE))
    for bench, rows in sorted(data.items()):
        v = [r for r in rows if r["fws"] == args.fws]
        if not v or not all(r.get("profile") for r in v):
            continue
        print(f"{bench:22s} " + "  ".join(f"{site_dev(v, b):8.2f}"
                                          for b in EXCHANGE))
        # A pooled cell hides the very thing this table exists to show.
        # 180 is 13.72 in every windows-desk low-mode run and 19.70 in
        # every high-mode one, and no run sits at the pooled 16.74.
        c = modes.classify([r["total_abs"] for r in v])
        if c.get("modes") == 2:
            lo = [r for r in v if r["total_abs"] < c["cut"]]
            hi = [r for r in v if r["total_abs"] >= c["cut"]]
            for nm, g in ((f"  lo (n={len(lo)})", lo), (f"  hi (n={len(hi)})", hi)):
                print(f"{nm:22s} " + "  ".join(f"{site_dev(g, b):8.2f}"
                                               for b in EXCHANGE))

    if args.per_run:
        print()
        for bench, rows in sorted(data.items()):
            v = sorted((r for r in rows if r["fws"] == args.fws),
                       key=lambda r: r["run"])
            if not v:
                continue
            med = statistics.median([split(r)[0] for r in v])
            print(f"{bench}:")
            for r in v:
                on, off = split(r)
                flag = "  <-- comb collapsed" if on < 0.5 * med else ""
                print(f"   run {r['run']:3d}  on {on:8.2f} ({on / med:5.3f} of "
                      f"median)  off {off:8.2f}  total_abs "
                      f"{r['total_abs']:7.1f}{flag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
