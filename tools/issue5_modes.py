#!/usr/bin/env python3
"""Split an issue #5 arm's runs into severity modes, per wait state.

    .venv/bin/python tools/issue5_modes.py records/issue5-campaign-*.jsonl

**Registered before the campaign rows it will read were opened.** It
was written from the `issue5-onimage-*` rows only, and committed before
`windows-desk` read its campaign arm or anyone's.

## Why

At flash wait state 6 the onimage rows are not one population on every
bench. `windows-desk` has 16 runs at a median total_abs of 446.7 and 8
at 350.7; `mac-bench` probe-free 1 has 10 at 463.7 and 14 at 338.8. The
modes interleave run by run, so they are not blocks.

A median over such a session measures **how many runs sat in each
mode**, not the size of the effect. The cross-bench spread quoted at FWS
6 - 342.7 to 445.5 - was read as board or jumper material, and
`mac-bench`'s high mode sits *above* `windows-desk`'s while the low
modes are 338.8 against 350.7. That is the shape occupancy gives and a
board difference does not.

It does **not** explain `linux-x1`, whose FWS 6 is one mode at 396.3,
between the other two benches' pairs. So this is not offered as the
answer to the spread; it is a reading that has to be made before a
median is compared with anything.

## The rule

total_abs, per wait state, run 1 discarded **by index**. Sort the runs.
Among the gaps that leave at least `MIN_SIDE` runs on each side, take
the largest. It is a mode boundary when both hold:

  * the gap is at least `GAP_MAD` times the larger within-side MAD, and
  * the gap is at least `GAP_REL` of the median.

One gap, so it finds at most two modes. A third would show as a wide
side; it is not looked for.

What it can and cannot see, measured by `tests/test_issue5_modes.py`:
0 of 2,000 fires on each of five unimodal nulls, one of them
`linux-x1`'s shape (23 runs near 396 and one at 353.5). Two modes 95
apart fire every time, at 15:9 and at 19:5 occupancy. Two modes 30 apart
at a within-mode sd of 2 fire 97% of the time, and **15 apart fire
never**.

**The detection limit is not a distance, and this docstring said it
was.** It read "a pair of modes closer than about 20 units is read as
one", which holds only at the within-mode sd the controls were drawn
at. The rule scales the gap by the within-side MAD, so a noisier side
raises the bar: `linux-x1`'s FWS 4 campaign arm has nothing between
42.0 and 59.0, 14 runs below and 10 above, modes 21 apart - and reads
**one mode**, because its low side's MAD of 2.40 puts the gap at 7.07x.
Its onimage arm, with a *smaller* gap of 15.7 and a MAD of 1.38, splits.
So a one-mode verdict is not a null. Read it with the gap, the ratio and
the sorted runs beside it; `main` prints all three. The threshold is
left as registered, because retuning it after rows were read would undo
the registration it belongs to.

## Registered predictions for the `windows-desk` campaign arm

From the onimage rows of the same bench: commit `1b2a2d1`, the
container build, xPack 15.2.1 - which is the image the campaign pins.
Those rows carry no `fw_sha256`, so "the same image" rests on the
container build being byte-reproducible, not on a hash in the row.

  P1. FWS 6 is two modes by the rule above. Refuted if it is one.
  P2. If two, the low mode's median lies in [333, 368] and the high
      mode's in [424, 469] - the onimage medians 350.7 and 446.7, each
      +/-5%.
  P3. The mode is written in the sites. In at least 90% of high-mode
      runs |dev| at 180 exceeds |dev| at 247, and in at least 90% of
      low-mode runs the reverse. The onimage rows' sixth slot is exactly
      this comparison; 1 run in 24 broke it.
      **Registered for this bench only.** It holds on `mac-bench`
      probe-free 1 (10/10 and 0/14) and fails on `mac-bench` probe-free
      2, whose FWS 6 also splits - 13 runs at 342.1, 11 at 384.0 - with
      180 over 247 in both modes. So a split without the exchange
      exists, and a mode is not defined by it.
  P4. Consequently, in at least 90% of low-mode runs the six strongest
      sites include one off the period-21 lattice (247 is 16 mod 21),
      and in at least 90% of high-mode runs all six are on it.
  P5. FWS 5 is two modes as well, as it was on four of five onimage
      arms.

No cross-bench prediction is registered. `mac-bench` has not run the
arm, and `linux-x1`'s single FWS 6 mode fits neither of this bench's.
"""
import argparse
import json
import statistics
import sys

MIN_SIDE = 4
GAP_MAD = 10.0
GAP_REL = 0.05

#: The period-21 comb through 12, one cycle of 256 bins. Twelve points;
#: 264 is not one of them (see `issue5_spectrum.lattice`).
LATTICE = frozenset(range(12, 256, 21))


def _mad(xs):
    m = statistics.median(xs)
    return statistics.median([abs(v - m) for v in xs])


def classify(values):
    """Two modes or one, by the largest admissible gap."""
    s = sorted(values)
    n = len(s)
    if n < 2 * MIN_SIDE:
        return {"modes": 1, "reason": "fewer than %d runs" % (2 * MIN_SIDE)}
    gap, i = max((s[k] - s[k - 1], k) for k in range(MIN_SIDE, n - MIN_SIDE + 1))
    lo, hi = s[:i], s[i:]
    spread = max(_mad(lo), _mad(hi), 1e-9)
    two = gap >= GAP_MAD * spread and gap >= GAP_REL * statistics.median(s)
    return {"modes": 2 if two else 1, "gap": gap, "gap_over_mad": gap / spread,
            "cut": (s[i - 1] + s[i]) / 2, "n_lo": len(lo), "n_hi": len(hi),
            "median_lo": statistics.median(lo), "median_hi": statistics.median(hi)}


def _dev(row, b):
    return next((abs(v) for bb, v, _z in row["sites"] if bb == b), 0.0)


def read(rows):
    """Per wait state: the split, and the site-level predictions per mode."""
    out = {}
    for fws in sorted({r.get("fws") for r in rows if r.get("fws") is not None}):
        sub = [r for r in rows if r.get("fws") == fws and r["run"] != 1]
        c = classify([r["total_abs"] for r in sub])
        if c["modes"] == 2:
            for side, pick in (("lo", lambda r: r["total_abs"] < c["cut"]),
                               ("hi", lambda r: r["total_abs"] >= c["cut"])):
                m = [r for r in sub if pick(r)]
                top6 = [sorted(r["sites"], key=lambda t: -abs(t[1]))[:6] for r in m]
                c["runs_" + side] = [r["run"] for r in m]
                c["n180_over_247_" + side] = sum(_dev(r, 180) > _dev(r, 247) for r in m)
                c["top6_on_lattice_" + side] = sum(
                    all(b in LATTICE for b, _v, _z in t) for t in top6)
        out[fws] = c
    return out


#: Unimodal sessions the rule must not split, 24 runs each. One home for
#: them: `--null` measures against these and the tests assert on them, so
#: a null added here is both reported and guarded. `one outlier` is
#: `linux-x1`'s FWS 6 shape - one tight mode and a run 40 below - the
#: most likely wrong answer a real session offers.
NULLS = {
    "normal": lambda r: [r.gauss(400, 3) for _ in range(24)],
    "uniform": lambda r: [r.uniform(390, 410) for _ in range(24)],
    "wide normal": lambda r: [r.gauss(400, 20) for _ in range(24)],
    "skewed": lambda r: [380 * r.lognormvariate(0, 0.02) for _ in range(24)],
    "one outlier": lambda r: [r.gauss(396, 2.5) for _ in range(23)] + [353.5],
}


def null_rates(trials=2000, seed=5):
    """The rule's false-positive rate on each null, measured, not asserted.

    `mac-bench`'s first threshold for this question called two modes in
    one population 17.4% of the time, and a rate is what showed it. A
    test that asserts zero says whether the rule passed; this says by how
    much, which is what a reader needs when a threshold is proposed.
    """
    import random
    out = {}
    for name, draw in NULLS.items():
        rng = random.Random(seed)
        fired = sum(classify(draw(rng))["modes"] == 2 for _ in range(trials))
        out[name] = fired / trials
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("records", nargs="*")
    ap.add_argument("--null", action="store_true",
                    help="measure the rule's false-positive rate on the "
                         "synthetic unimodal sessions in NULLS, and print it")
    ap.add_argument("--trials", type=int, default=2000)
    args = ap.parse_args()
    if not args.records and not args.null:
        ap.error("give records to read, or --null")
    if args.null:
        print(f"false-positive rate, {args.trials} sessions per null "
              f"(MIN_SIDE {MIN_SIDE}, GAP_MAD {GAP_MAD}, GAP_REL {GAP_REL}):")
        for name, rate in null_rates(args.trials).items():
            print(f"  {name:12s} {rate:.4f}")
    for path in args.records:
        with open(path, encoding="utf-8") as fh:
            rows = [json.loads(line) for line in fh if line.strip()]
        print(path)
        for fws, c in read(rows).items():
            ranked = sorted(r["total_abs"] for r in rows
                            if r.get("fws") == fws and r["run"] != 1)
            print(f"  FWS {fws} sorted: " + " ".join(f"{v:.1f}" for v in ranked))
            if c["modes"] == 1:
                print(f"  FWS {fws}: one mode ({c.get('reason') or 'gap %.1f, %.1f x MAD' % (c['gap'], c['gap_over_mad'])})")
                continue
            print(f"  FWS {fws}: two modes, cut {c['cut']:.1f}, gap {c['gap']:.1f} "
                  f"({c['gap_over_mad']:.1f} x MAD)")
            for side in ("lo", "hi"):
                n = c["n_" + side]
                print(f"    {side}: n={n:2d} median {c['median_' + side]:6.1f}  "
                      f"|180|>|247| {c['n180_over_247_' + side]}/{n}  "
                      f"top six on lattice {c['top6_on_lattice_' + side]}/{n}  "
                      f"runs {c['runs_' + side]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
