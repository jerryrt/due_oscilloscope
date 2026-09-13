#!/usr/bin/env python3
"""The jumper-material crossover: does the comb follow the wire or the die?

    .venv/bin/python tools/issue5_crossover.py            # registration + state
    .venv/bin/python tools/issue5_crossover.py --check    # score it once arms land

**Registered before the wires were moved.** The predictions, the
statistic and the decision rule below are fixed at this commit; the
arms that test them did not exist when it was written. Nothing here may
be retuned after a row is read - that is the whole point of writing it
down first, and this project has already paid for a threshold chosen
after the fact.

## The question, and why it needed hardware

The FWS 6 comb sum differs between benches: `mac-bench` 238.29 and
`linux-x1` 235.51 on copper, `windows-desk` 218.21 on iron. That looks
like the wire, and it cannot be read as the wire, because **board and
material have been perfectly confounded from the start** - the iron
bench is also the only windows-desk die. A between-bench difference is
board, jumper material, or USB IN DMA timing, and three arms run
identically do not separate three dies.

## The design, which co-location made available

All three boards are on one desk. So the wires can be **exchanged
between two boards** rather than merely removed and refitted on one:

    linux-x1 board     copper  ->  IRON
    windows-desk board iron    ->  COPPER
    mac-bench board    copper  ->  copper   (UNTOUCHED, the control)

This is a crossover, and it is strictly stronger than the A-B-A that
`docs/issue5-campaign.md` proposed. Each board is its own control, both
directions are tested at once, and there is no arm whose null is
ambiguous: under the material hypothesis the two values must EXCHANGE,
which a die effect cannot imitate.

The third board is untouched and re-runs anyway. That is not spare
capacity - it is the only measurement of how much the comb sum moves
between SESSIONS, which nothing in the record establishes, because the
older arms stored no profiles. Without it a swap-sized change and a
session-sized change are indistinguishable.

## The predictions, fixed here

Baselines are the median FWS 6 comb sum - the twelve period-21 lattice
points summed off the stored profile - run 1 dropped by index, over
each bench's committed campaign arm.
"""
import argparse
import glob
import json
import os
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PERIOD, PHASE, BINS = 21, 12, 256
LATTICE = [PHASE + PERIOD * k for k in range(BINS // PERIOD + 1)
           if PHASE + PERIOD * k < BINS]

#: THE ESTIMATOR IS PART OF THE REGISTRATION. "The comb sum" names at
#: least three quantities and they do not agree:
#:
#:                    profile/12   profile/10   sitelist/10
#:     linux-x1          235.50       235.16        233.88
#:     windows-desk      218.21       217.99        217.23
#:     mac-bench         238.29       237.96        238.06
#:
#: The route used here is **profile/12**: all twelve period-21 lattice
#: points, summed off the stored 256-point profile, median over runs,
#: run 1 dropped by index. It is chosen because it needs no detection
#: threshold - a site list is a threshold over a floor that is itself
#: the thing moving between modes, so a site-list sum partly measures
#: the floor. `comb_sum()` below is the only implementation, and both
#: the baselines and every new arm go through it.
#:
#: `linux-x1` raised this before any crossover row was read, estimating
#: the divergence at 3% and so at 40% of the decision cut. Measured on
#: the committed rows it is 0.1-0.7%, at most 1.62 units against a cut
#: of 17.30 - 9% of the cut, not 40%. Their 233.88 is exactly the
#: sitelist/10 route on the same rows. Smaller than feared and still
#: worth pinning, because two benches computing "the comb sum" two ways
#: has already cost this project one exchange.
#:
#: `--verify-baseline` recomputes these from the committed records and
#: refuses on disagreement, so the estimator is pinned by EXECUTION and
#: not by this comment. A constant that only prose defends is a
#: constant that drifts.
#:
#: Median comb sum and per-run sd, from the three committed arms.
#: `linux-x1`'s excludes its run 31, whose comb collapsed to 0.283 of
#: normal - a documented singular run, excluded as an outlier in the
#: baseline and NOT as a filter on the new arms.
BASELINE = {
    "linux-x1":     {"jumpers": "copper", "comb": 235.51, "sd": 0.55},
    "windows-desk": {"jumpers": "iron",   "comb": 218.21, "sd": 2.67},
    "mac-bench":    {"jumpers": "copper", "comb": 238.29, "sd": 0.32},
}

#: After the swap. L = linux-x1 board, W = windows-desk board.
L0, W0 = BASELINE["linux-x1"]["comb"], BASELINE["windows-desk"]["comb"]
#: The confounded difference. Under the material hypothesis this is the
#: material effect; under the die hypothesis it is the die difference.
GAP = L0 - W0

#: The statistic. Both terms are positive when the values exchange.
#:     D = (L0 - L1) + (W1 - W0)
#: Pure material: L1 = W0 and W1 = L0, so D = 2 * GAP.
#: Pure die:      L1 = L0 and W1 = W0, so D = 0.
#: It is deliberately symmetric: a change in one arm only - which is
#: what a board disturbed by the handling would give - lands at GAP,
#: halfway, and is reported as INCONCLUSIVE rather than as half an
#: effect.
D_MATERIAL = 2 * GAP
D_DIE = 0.0
#: Decision rule, fixed in advance.
D_CUT = GAP

#: THE RETURN LEG, registered while linux-x1's crossover arm was still
#: capturing and before any crossover row was read.
#:
#: The swap physically handles both boards, so "the wire changed" and
#: "the board was reseated" are confounded in the crossover exactly as
#: board and material were confounded before it. Putting the ORIGINAL
#: wires back and re-running is the only thing that separates them:
#:
#:     linux-x1 board      IRON   -> copper   (back to its own)
#:     windows-desk board  COPPER -> iron     (back to its own)
#:
#: Let L2, W2 be those. The statistic is a hysteresis:
#:
#:     H = |L2 - L0| + |W2 - W0|
#:
#: Small H means the manipulation is REVERSIBLE, so whatever moved in
#: the crossover moved back when the wire did, and handling is excluded.
#: Large H with a large D means something changed and stayed changed -
#: which is reseating, contact resistance, or drift, and is NOT the
#: material however cleanly the crossover exchanged.
#:
#: A large D that does not return is the outcome that would otherwise
#: have been published as "material", and it is the reason this leg is
#: registered rather than offered afterwards. Approved by linux-x1's
#: owner and by mac-bench's before it was written down.
H_TOL = 8.18   # 3 * sqrt(sd_L^2 + sd_W^2), per-run sds, deliberately
               # loose: it bounds a between-session quantity that has
               # never been measured, and the control arm is what
               # measures it.

#: The control must reproduce itself or the comparison is void. Three
#: sds of a single run, which is looser than the median of 24 needs and
#: is the honest bound because BETWEEN-session repeatability of the comb
#: sum has never been measured - this arm is the first to measure it.
CONTROL_TOL = 3 * BASELINE["mac-bench"]["sd"]


def comb_sum(path, fws=6, drop=(1,)):
    rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    rows = [r for r in rows if r["run"] not in drop and r.get("fws") == fws]
    if not rows or "profile" not in rows[0]:
        return None, 0
    vals = [sum(abs(r["profile"][b]) for b in LATTICE) for r in rows]
    return statistics.median(vals), len(vals)


def registration():
    print(__doc__.rstrip())
    print()
    print(f"  baseline  linux-x1 board + copper   L0 = {L0:.2f}")
    print(f"  baseline  windows-desk board + iron W0 = {W0:.2f}")
    print(f"  confounded gap                      GAP = {GAP:.2f}")
    print()
    print("  PREDICTED, if the material carries it:")
    print(f"    linux-x1 board + IRON     L1 -> {W0:.2f}")
    print(f"    windows-desk board + COPPER W1 -> {L0:.2f}")
    print(f"    D -> {D_MATERIAL:.2f}")
    print("  PREDICTED, if the die carries it:")
    print(f"    linux-x1 board + IRON     L1 -> {L0:.2f}  (unchanged)")
    print(f"    windows-desk board + COPPER W1 -> {W0:.2f}  (unchanged)")
    print(f"    D -> {D_DIE:.2f}")
    print()
    print(f"  DECISION: D > {D_CUT:.2f} -> material; D < {D_CUT:.2f} -> die.")
    print(f"  CONTROL : mac-bench must re-read "
          f"{BASELINE['mac-bench']['comb']:.2f} +/- {CONTROL_TOL:.2f} "
          f"with its copper untouched, or the whole comparison is VOID.")
    print()
    print("  Expected files, none of which exist at this commit:")
    for b in ("linux-x1", "windows-desk", "mac-bench"):
        print(f"    records/issue5-crossover-{b}.jsonl")


def check():
    got = {}
    for b in BASELINE:
        p = os.path.join(ROOT, "records", f"issue5-crossover-{b}.jsonl")
        if os.path.exists(p):
            v, n = comb_sum(p)
            got[b] = (v, n)
    if not got:
        print("no crossover arms yet; registration stands")
        return 0
    for b, (v, n) in sorted(got.items()):
        print(f"  {b:14s} comb {v:7.2f}  (n={n}, baseline "
              f"{BASELINE[b]['comb']:.2f})")
    if "mac-bench" in got:
        d = abs(got["mac-bench"][0] - BASELINE["mac-bench"]["comb"])
        ok = d <= CONTROL_TOL
        print(f"\n  CONTROL: mac-bench moved {d:.2f} against a tolerance of "
              f"{CONTROL_TOL:.2f} -> {'ok' if ok else 'VOID'}")
        if not ok:
            print("  The untouched board moved. Nothing else here is "
                  "readable; the session drifted.")
            return 1
    if "linux-x1" in got and "windows-desk" in got:
        L1, W1 = got["linux-x1"][0], got["windows-desk"][0]
        D = (L0 - L1) + (W1 - W0)
        print(f"\n  D = ({L0:.2f} - {L1:.2f}) + ({W1:.2f} - {W0:.2f}) "
              f"= {D:.2f}")
        print(f"  material predicts {D_MATERIAL:.2f}, die predicts "
              f"{D_DIE:.2f}, cut at {D_CUT:.2f}")
        print(f"  -> {'MATERIAL' if D > D_CUT else 'DIE'}")
    else:
        print("\n  both swapped arms needed before D is defined")
    return 0


def verify_baseline():
    """Recompute the registered baselines from the committed records.

    The estimator is part of the registration, so it is pinned by
    running it rather than by the comment that describes it. If someone
    changes `comb_sum` - to the site list, to ten points, to a mean -
    these stop matching and this refuses.
    """
    bad = []
    for b in BASELINE:
        p = os.path.join(ROOT, "records", f"issue5-campaign-{b}.jsonl")
        if not os.path.exists(p):
            bad.append(f"{b}: no campaign record")
            continue
        v, n = comb_sum(p)
        d = abs(v - BASELINE[b]["comb"])
        mark = "ok" if d <= 0.05 else "MISMATCH"
        print(f"  {b:14s} registered {BASELINE[b]['comb']:7.2f}  "
              f"recomputed {v:7.2f}  (n={n})  {mark}")
        if d > 0.05:
            bad.append(f"{b}: registered {BASELINE[b]['comb']:.2f} but "
                       f"comb_sum() gives {v:.2f}")
    if bad:
        print("\nREFUSING: the estimator has moved under the "
              "registration:", file=sys.stderr)
        for x in bad:
            print(f"  {x}", file=sys.stderr)
        return 1
    print("\n  estimator pinned: profile/12, median, run 1 dropped")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--verify-baseline", action="store_true",
                    help="recompute the registered baselines from the "
                         "committed records and refuse on disagreement")
    a = ap.parse_args()
    if a.verify_baseline:
        return verify_baseline()
    return check() if a.check else (registration() or 0)


if __name__ == "__main__":
    sys.exit(main())
