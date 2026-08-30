#!/usr/bin/env python3
"""Which lattices can a given #24 arm actually tell apart?

This issue has now spent two days on arms that could not answer the
question they were run for, and every time the reason was the same
shape: two candidate readings predicting the same number in that
configuration. First "21 ADC conversions" and "105 us", which are
identical at any fixed ADC rate. Then "a quarter of the wrap" and
"957 us", identical for the same reason one level up.

**And one more, which is the instrument rather than the rates.**
`issue24_hold.py` reads a *decimated* series - one sample per DAC
update, `vals[offset::hold]` - so a spacing that is not a whole number
of DAC updates cannot appear as a fractional gap. It appears as
whatever the surviving sites are spaced by, and that is frequently 21
whichever lattice is underneath.

So this answers the question before the board is used, by construction
rather than by argument: build a series that certainly contains a known
lattice, push it through the same `decimate()` the tool uses, and print
what comes out. If two readings print the same number, that arm cannot
separate them and no number of captures will.

    python3 tools/issue24_visible.py
    python3 tools/issue24_visible.py --holds 1,2,3 --conversions 21

The headline result, and it was expensive to learn the other way:
**only holds divisible by 3 separate a 21-conversion lattice from a
21-update one.** 21 = 3 x 7, so decimating by 3 keeps every site of the
conversion lattice and maps it to a gap of 7, while at holds 1, 2, 4 and
5 both readings give 21 and the arm is degenerate.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from issue24_hold import decimate                        # noqa: E402

N = 20000


def predicted_gap(model, period, hold, dac_hz=None):
    """The gap a decimating reader reports, in DAC updates.

    Closed form, checked against the simulation below for every hold
    this issue has used. Cheap enough that no arm ever needs running to
    find out whether it could have answered the question.

      conversion-locked   period / gcd(period, hold)
          Sites sit every `period` ADC conversions; decimation keeps
          those at raw indices divisible by `hold`, i.e. the multiples
          of lcm(period, hold), and dividing back into update space
          gives period/gcd. The gcd is the whole story: it is why 21
          conversions reads as 7 at hold 3 and as 21 everywhere else.

      update-locked       period
          The decimated index *is* the update number, so the gap is the
          period at every hold. No rate in it, and no hold either.

      time-locked         seconds * dac_hz
          The only one of the three carrying a rate, which is what makes
          a gap that moves with the ADC rate at a fixed hold diagnostic.
    """
    from math import gcd
    if model == "conversion":
        return period / gcd(int(period), int(hold))
    if model == "update":
        return float(period)
    if model == "time":
        return period * dac_hz            # period in seconds
    raise ValueError(model)


def _gaps(marks, hold, offset, want=6):
    dec = decimate(marks, hold, offset)
    idx = [i for i, v in enumerate(dec) if v]
    return [b - a for a, b in zip(idx, idx[1:])][:want]


def conversion_lattice(period, hold, offset):
    """Every `period` ADC conversions, as the decimating reader sees it."""
    return _gaps([1 if i % period == 0 else 0 for i in range(N)],
                 hold, offset)


def update_lattice(period, hold, offset):
    """Every `period` DAC updates, as the decimating reader sees it."""
    return _gaps([1 if ((i // hold) % period == 0 and i % hold == 0) else 0
                  for i in range(N)], hold, offset)


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--holds", default="1,2,3,4,5,6")
    ap.add_argument("--conversions", type=int, default=21,
                    help="period of the conversion-locked candidate")
    ap.add_argument("--updates", type=int, default=21,
                    help="period of the update-locked candidate")
    args = ap.parse_args()
    holds = [int(h) for h in args.holds.split(",") if h.strip()]

    print(f"conversion-locked = every {args.conversions} ADC conversions")
    print(f"update-locked     = every {args.updates} DAC updates")
    print(f"\n{'hold':>5} {'conversion':>12} {'update':>10}   verdict")
    for hold in holds:
        c = conversion_lattice(args.conversions, hold, 0)
        u = update_lattice(args.updates, hold, 0)
        cv = c[0] if c else None
        uv = u[0] if u else None
        verdict = ("SEPARATES" if cv != uv else
                   "degenerate - this arm cannot answer it")
        print(f"{hold:>5} {str(cv):>12} {str(uv):>10}   {verdict}")

    # A second, independent signature. Where gcd(period, hold) > 1 the
    # conversion lattice can only land on some of the decimation
    # offsets, so finding sites at ALL of them there rules that period
    # out on its own - without needing the gap at all. Where it draws at
    # every offset anyway, the check says nothing and is marked so.
    print("\nThe closed form, checked against the simulation above:")
    bad = []
    for hold in holds:
        c = conversion_lattice(args.conversions, hold, 0)
        want = predicted_gap("conversion", args.conversions, hold)
        got = c[0] if c else None
        if got is not None and abs(got - want) > 1e-9:
            bad.append((hold, got, want))
    print(f"   period/gcd(period, hold) reproduces the simulated gap at "
          f"every hold tested"
          if not bad else f"   MISMATCH: {bad}")

    print("\nPer-offset, a second and independent signature:")
    for hold in holds:
        live = [o for o in range(hold)
                if conversion_lattice(args.conversions, hold, o)]
        note = ("   <- restricted, so sites at EVERY offset here rule "
                f"out period {args.conversions}"
                if len(live) < hold else
                "   (draws everywhere - this check is uninformative here)")
        print(f"  hold {hold}: a {args.conversions}-conversion lattice "
              f"draws at offsets {live} of {list(range(hold))}"
              + (note if hold > 1 else ""))


if __name__ == "__main__":
    main()
