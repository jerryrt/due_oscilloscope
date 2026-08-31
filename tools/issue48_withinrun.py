#!/usr/bin/env python3
"""Does #48's mode incidence drift *within a single run*?

The incidence of the deep mode at a bimodal rate has looked like it
drifts. It was attributed to rest, then to time since reset, and the
arms that separated those were four separate runs of the measuring
tool - which is the problem this asks around.

**Every run of a lattice tool opens a `measure.Board`, and on macOS that
asserts NRSTB and resets the board** (`tools/uptime_reset_probe.py`,
3/3). So an arm structure built from separate runs cannot vary time
since reset at all here: every arm starts at zero.

What can vary it is *one* run. A single held `Board`, N consecutive
reps, and the rep index is minutes-since-reset as a continuous axis
that no arm structure can confound. This reads that record back.

    python3 tools/issue48_lattice.py --rcs 36 --reps 64 --out R.jsonl
    python3 tools/issue48_withinrun.py R.jsonl

**Modes are found, not assumed.** Ratios are clustered by gap so the
tool does not need to be told what n=4 and n=6 look like on this bench
- a rate that turns out single-moded says so instead of inventing a
split.

**The test is Mann-Whitney U on rep index**, deep-mode reps against the
rest. Not a first-half/second-half Fisher: halving is an arbitrary bin
chosen after seeing the data, and the question "do deep reps happen
earlier" has a rank test that needs no bin at all. The halves are
printed too, because they are what the other benches have already
reported and a comparison should be like for like.

**Rep 0 is dropped by index.** Not by a filter on what a first run is
thought to do wrong - a `mac-bench` first run at RC 48 once sat on a
mode no later run took, with `underruns = 0`, and passed every filter
written to catch a disturbed first cycle.

Reps with underruns are reported but kept out of the mode fit: an
underrun perturbs `consumed / run_us` directly, so such a rep is not a
draw from either mode.
"""
import argparse
import json
import math
import sys
from collections import Counter


def load(path):
    rows = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def cluster(values, gap):
    """Split sorted values wherever the step exceeds `gap`."""
    vals = sorted(values)
    groups, cur = [], [vals[0]]
    for v in vals[1:]:
        if v - cur[-1] > gap:
            groups.append(cur)
            cur = [v]
        else:
            cur.append(v)
    groups.append(cur)
    return groups


def mannwhitney(a, b):
    """Two-sided U test. Returns (U_a, z, p). No ties expected: the
    values are rep indices and those are unique."""
    n1, n2 = len(a), len(b)
    if not n1 or not n2:
        return None, None, None
    allv = sorted([(v, 0) for v in a] + [(v, 1) for v in b])
    ranks = {}
    i = 0
    while i < len(allv):
        j = i
        while j + 1 < len(allv) and allv[j + 1][0] == allv[i][0]:
            j += 1
        r = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[k] = r
        i = j + 1
    r1 = sum(ranks[k] for k, (_, g) in enumerate(allv) if g == 0)
    u1 = r1 - n1 * (n1 + 1) / 2.0
    mu = n1 * n2 / 2.0
    counts = Counter(v for v, _ in allv)
    n = n1 + n2
    tie = sum(t ** 3 - t for t in counts.values())
    var = n1 * n2 / 12.0 * ((n + 1) - tie / float(n * (n - 1)))
    if var <= 0:
        return u1, None, None
    z = (u1 - mu) / math.sqrt(var)
    p = math.erfc(abs(z) / math.sqrt(2.0))
    return u1, z, p


def runs_test(seq):
    """Wald-Wolfowitz on a binary sequence. Returns (runs, expected, z, p).

    This is the question the rank test cannot ask. The rank test says
    whether the deep mode happens *earlier*; this says whether it
    happens in *clumps*.

    They separate two families of mechanism. Anything that varies
    slowly - a temperature, a settling, a state that accumulates over a
    run - makes consecutive reps agree, which is fewer runs than chance
    and a negative z. An independent per-rep draw gives z near zero
    whatever the incidence is.

    A null result here is only worth as much as its power, so quote the
    power with it. Simulated at N=61 and stationary p=0.23, two-state
    Markov, 20k trials: a state with a mean dwell of 2.0 reps is caught
    with probability 0.72, 2.5 reps with 0.91, and 3.3 reps with 0.96 -
    but 1.3 reps only with 0.05. So "no clustering" bounds the dwell of
    any selecting state at roughly one rep; it does not reach below
    that.
    """
    n1 = seq.count(1)
    n2 = len(seq) - n1
    n = len(seq)
    if n1 < 2 or n2 < 2:
        return None, None, None, None
    r = 1 + sum(1 for i in range(1, n) if seq[i] != seq[i - 1])
    exp = 2.0 * n1 * n2 / n + 1.0
    var = 2.0 * n1 * n2 * (2.0 * n1 * n2 - n) / (n * n * (n - 1))
    if var <= 0:
        return r, exp, None, None
    z = (r - exp) / math.sqrt(var)
    return r, exp, z, math.erfc(abs(z) / math.sqrt(2.0))


def fisher(a, b, c, d):
    """Two-tailed Fisher exact on [[a,b],[c,d]]."""
    def logf(n):
        return math.lgamma(n + 1)

    def prob(a_, b_, c_, d_):
        return math.exp(logf(a_ + b_) + logf(c_ + d_) + logf(a_ + c_)
                        + logf(b_ + d_) - logf(a_) - logf(b_) - logf(c_)
                        - logf(d_) - logf(a_ + b_ + c_ + d_))

    p0 = prob(a, b, c, d)
    row1, row2 = a + b, c + d
    col1 = a + c
    total = 0.0
    for x in range(0, min(row1, col1) + 1):
        y, z_, w = row1 - x, col1 - x, row2 - (col1 - x)
        if y < 0 or z_ < 0 or w < 0:
            continue
        p = prob(x, y, z_, w)
        if p <= p0 * (1 + 1e-9):
            total += p
    return min(total, 1.0)


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("record")
    ap.add_argument("--gap", type=float, default=0.002,
                    help="ratio gap that separates two modes")
    ap.add_argument("--keep-first", action="store_true",
                    help="do not drop rep 0 (say why if you use this)")
    args = ap.parse_args()

    rows = load(args.record)
    if not rows:
        print("empty record", file=sys.stderr)
        return 2

    by_rc = {}
    for r in rows:
        by_rc.setdefault(r["rc"], []).append(r)

    for rc, rs in sorted(by_rc.items()):
        rs.sort(key=lambda r: r["rep"])
        print(f"=== RC {rc} — {len(rs)} reps ===")

        vias = {r.get("via") for r in rs}
        if vias == {None}:
            print("instrument: NOT RECORDED - a pre-#51 record, so which "
                  "instrument produced these figures is unknown")
        else:
            print(f"instrument: {sorted(v for v in vias if v)}")

        dropped = []
        if not args.keep_first:
            first = [r for r in rs if r["rep"] == 0]
            if first:
                dropped.append(f"rep 0 (by index, always)")
                rs = [r for r in rs if r["rep"] != 0]

        under = [r for r in rs if r.get("under")]
        if under:
            print(f"reps with underruns, kept out of the mode fit: "
                  f"{[r['rep'] for r in under]}")
            rs = [r for r in rs if not r.get("under")]

        if dropped:
            print("dropped: " + ", ".join(dropped))
        if len(rs) < 8:
            print("too few clean reps to say anything\n")
            continue

        groups = cluster([r["ratio"] for r in rs], args.gap)
        print(f"modes found: {len(groups)}")
        for g in groups:
            print(f"  ratio {sum(g)/len(g):.6f}  n={len(g):>3}  "
                  f"spread {max(g)-min(g):.6f}")
        if len(groups) < 2:
            print("single-moded over these reps — no incidence to drift. "
                  "That is 'no second mode seen', not 'no second mode'.\n")
            continue

        # The deep mode is the lowest-ratio cluster: most conversions lost.
        deep = set(groups[0])
        deep_reps = [r["rep"] for r in rs if r["ratio"] in deep]
        rest_reps = [r["rep"] for r in rs if r["ratio"] not in deep]
        print(f"\ndeep mode at ratio {sum(groups[0])/len(groups[0]):.6f}: "
              f"{len(deep_reps)} of {len(rs)} reps "
              f"({100.0*len(deep_reps)/len(rs):.1f}%)")
        print(f"deep reps at index: {deep_reps}")

        u, z, p = mannwhitney(deep_reps, rest_reps)
        if z is None:
            print("no rank test possible")
        else:
            print(f"\nMann-Whitney U on rep index: U={u:.1f} z={z:+.3f} "
                  f"p={p:.4f} (two-sided)")
            print("  " + ("deep reps sit EARLIER in the run"
                          if z < 0 else
                          "deep reps sit LATER in the run")
                  + f" — {'significant' if p < 0.05 else 'NOT significant'} "
                    f"at 0.05")

        seq = [1 if r["ratio"] in deep else 0 for r in rs]
        nr, exp, rz, rp = runs_test(seq)
        if rz is None:
            print("\nruns test: too few of one mode")
        else:
            print(f"\nWald-Wolfowitz runs test: {nr} runs, {exp:.1f} "
                  f"expected, z={rz:+.3f} p={rp:.4f}")
            if rz < -1.96:
                print("  CLUSTERED - consecutive reps agree more than "
                      "chance, so a slowly-varying state is selecting "
                      "the mode")
            elif rz > 1.96:
                print("  ALTERNATING - more runs than chance")
            else:
                print("  no serial correlation: consistent with an "
                      "INDEPENDENT draw per rep. At N=61 and p=0.23 this "
                      "test catches a state dwelling 2.5 reps with "
                      "probability 0.91 and 1.3 reps with 0.05, so it "
                      "bounds such a state at about one rep and no lower")
            print(f"  mode sequence: "
                  f"{''.join('D' if x else 'S' for x in seq)}")

        mid = (min(r["rep"] for r in rs) + max(r["rep"] for r in rs)) / 2.0
        h1d = sum(1 for x in deep_reps if x <= mid)
        h1n = sum(1 for r in rs if r["rep"] <= mid)
        h2d = len(deep_reps) - h1d
        h2n = len(rs) - h1n
        pf = fisher(h1d, h1n - h1d, h2d, h2n - h2d)
        print(f"\nhalves, for comparison with the other benches' figures:")
        print(f"  first  half: {h1d}/{h1n} = {100.0*h1d/h1n:.1f}%")
        print(f"  second half: {h2d}/{h2n} = {100.0*h2d/h2n:.1f}%")
        print(f"  Fisher exact two-tailed p = {pf:.4f}")
        print("  (the halving is an arbitrary bin; the rank test above "
              "needs none and is the one to quote)\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
