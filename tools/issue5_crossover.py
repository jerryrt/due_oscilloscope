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


#: SECONDARY STATISTICS, registered before any crossover row was read,
#: on `windows-desk`'s analysis and verified here against the committed
#: rows before being accepted.
#:
#: The primary statistic sums all twelve lattice points raw. Three of
#: them - 75, 180 and 201 - move with `windows-desk`'s FWS 6 mode, and
#: two - 222, 243 - are empty. So W0's sd of 2.67 is that bench's mode
#: split rather than session noise, and under the primary statistic W1
#: can move ~5.2 from occupancy alone with no wire effect. Not enough to
#: cross a 17.30 cut by itself, but it is noise the alternatives do not
#: carry. Verified: on their arm the primary reads 215.49 / 220.72 by
#: mode against a pooled sd of 2.61, while the seven-site sum reads
#: 189.74 / 189.65, sd 0.14.
#:
#: (a) SEVEN-SITE. The lattice minus the two empty points and the three
#: that exchange, each position taken against that run's median profile:
SEVEN = [12, 33, 54, 96, 117, 138, 159]
SEVEN_BASE = {"linux-x1": 193.77, "windows-desk": 189.68,
              "mac-bench": 193.43}
SEVEN_SD = {"linux-x1": 0.432, "windows-desk": 0.139, "mac-bench": 0.373}
#: gap 4.08, so material predicts D_seven = 8.16 with the cut at 4.08.
#: A smaller effect than the primary's 17.30 and a much smaller noise:
#: 4.08 against sd 0.14-0.43 is a better ratio than 17.30 against 2.67.
SEVEN_GAP = SEVEN_BASE["linux-x1"] - SEVEN_BASE["windows-desk"]
SEVEN_CUT = SEVEN_GAP

#: (b) PER-SITE EXCHANGE, the sharpest readout this design has. The
#: three sites that carry most of the primary's gap, median |deviation|
#: off the profile:
#:
#:                  75      180      201
#:     linux-x1    8.62    31.26     1.61     (copper)
#:     mac-bench   8.66    33.73     2.21     (copper)
#:     windows     3.41    16.76     8.04     (iron)
#:
#: If the WIRE carries the exchange, then after the swap the windows
#: board on copper goes to about 8.6 / 31-34 / 2, and the linux board on
#: iron goes to about 3.4 / 16.8 / 8. If the DIE carries it each board
#: holds its own row. On the windows board these are reported PER MODE,
#: because 75, 180 and 201 are exactly the sites its modes move.
EXCHANGE = [75, 180, 201]
EXCHANGE_COPPER = {75: 8.64, 180: 32.50, 201: 1.91}   # linux+mac mean
EXCHANGE_IRON = {75: 3.41, 180: 16.76, 201: 8.04}

#: THREE STATISTICS IS THREE CHANCES, and that is stated rather than
#: hidden. The primary is the twelve-point D and it decides the headline;
#: (a) and (b) are secondary, each with its cut fixed above. They are not
#: interchangeable readings of one claim - a result where (b) exchanges
#: and (a) does not says the wire moves the three exchange sites and not
#: the stable seven, which is a sharper finding than either alone. What
#: is not allowed is choosing among them afterwards.


#: THE RETURN LEG'S READOUT, registered while linux-x1's return arm was
#: capturing and before any of its rows were read.
#:
#: The question the return leg answers is whether the crossover's
#: changes REVERSE when the original wire goes back. Reversible means
#: the wire or its seating; not reversible means the board changed for
#: a reason the wires neither caused nor undid, and the crossover
#: cannot speak to the material from that leg at all.
#:
#: WHICH POSITIONS MAY CARRY THAT, and this is the part that needed
#: measuring rather than choosing. Per-position drift is NOT uniform.
#: Between mac-bench's two untouched arms the median position moves
#: 0.03 - and the worst moves 9.45:
#:
#:     FWS 4   max 9.45   p99 1.90   p95 0.18   median 0.025
#:     FWS 5   max 6.79   p99 0.17   p95 0.11   median 0.036
#:     FWS 6   max 3.89   p99 3.50   p95 2.56   median 0.044
#:
#: So a position is eligible evidence only if it moved by more than
#: 3x what the UNTOUCHED board drifted AT THAT SAME POSITION, floored
#: at 0.30 so a position with near-zero drift cannot be made eligible
#: by arithmetic.
#:
#: Applied to the crossover, this disqualifies two of the six positions
#: linux-x1 proposed. FWS 4 pos 219 moved -14.24 on their board and
#: -9.45 on mac-bench's untouched one, same sign; pos 240 moved -5.81
#: against -3.51. Their whole FWS 4 result - the wait state they
#: reported as moving MOST - has ZERO eligible positions. Pos 109 at
#: FWS 6 is out too, drifting +2.51 untouched against their -3.17.
#:
#: What survives:
#:     linux-x1      FWS 5: 134          FWS 6: 180, 75, 169, 201
#:     windows-desk  FWS 5: 134, 50, 39, 251
#:                   FWS 6: 247, 201, 180, 75
#:
#: Three of linux-x1's five survivors are lattice points, which is what
#: the comb sum's 0.19 session repeatability already implied: the comb
#: is the part that does not drift, and the floor is the part that does.
#:
#: AND WINDOWS-DESK'S BOARD DID MOVE. Both benches, this one included,
#: wrote "only linux-x1's board moved" from the registered statistics -
#: their exchange sites and seven-site sum barely shifted. Drift-
#: corrected per position they have MORE eligible movers than linux-x1.
#: It does not revive the material hypothesis, because none of the
#: movement is toward the other wire's row, but the sentence was wrong.
RETURN_DRIFT_MULT = 3.0
RETURN_DRIFT_FLOOR = 0.30

#: AND THE READOUT IS COUNT-AND-SIZE, NOT THE POOLED MEDIAN.
#: windows-desk's proposal, adopted after testing it against the control
#: rather than on its face - and it changes the eligibility list above
#: in both directions, which is why it earns its place.
#:
#: A pooled median at one position conflates two things: how OFTEN the
#: site is large, and how large it is WHEN large. Reported separately,
#: with mac-bench's untouched pair beside them:
#:
#:   FWS 4 pos 219   untouched  count 11->15   size  9.68 -> 9.69
#:                   linux-x1   count  8->14   size  7.96 ->14.45
#:   FWS 4 pos 240   untouched  count 24->24   size  4.51 -> 1.00
#:                   linux-x1   count 23->24   size  6.90 -> 1.14
#:   FWS 5 pos 134   untouched  count 11->17   size  1.23 -> 1.07
#:                   linux-x1   count 24->24   size  2.24 -> 5.06
#:   FWS 6 pos 169   untouched  count 24->24   size 20.32 ->21.84
#:                   linux-x1   count 23->24   size 18.35 ->30.39
#:
#: Position 219 is REINSTATED and 240 stays disqualified, and the
#: decomposition is what separates them. At 219 the untouched board
#: moved the same way on COUNT (11->15 against 8->14) and held on SIZE
#: (9.68->9.69 against 7.96->14.45), so the count is drift and the size
#: is not. At 240 the untouched board's size fell 4.51->1.00 against
#: linux-x1's 6.90->1.14 - same direction, same magnitude - so that
#: position is drift in the component that matters.
#:
#: The previous registration disqualified 219 on the pooled median and
#: would have thrown away a real signal. Recorded rather than quietly
#: amended: a per-position control was the right idea and the wrong
#: statistic, and it took another bench's decomposition to see it.
#:
#: So eligibility is judged on EACH COMPONENT against the untouched
#: board's move in that same component at that same position. A
#: position may be eligible on size and not on count.
#: AND THE COUNT MUST BE A STATE, NOT SITE PRESENCE. windows-desk's
#: second correction, and it settles 240 the other way from 735c3b8.
#:
#: Counting "how many runs list this position as a site" mixes large
#: and small runs into the size column, because a site can be listed
#: and small. The threshold-free version: pool that position's per-run
#: |profile| over BOTH arms, cut at the largest gap, and report the
#: count above it, the median size when large, and the median when
#: small. Measured that way, with the untouched board beside each:
#:
#:   FWS 4 pos 219   untouched  large 11->15   size-large  9.78-> 9.73
#:                   linux-x1   large  8->14   size-large  7.99->14.42
#:   FWS 4 pos 240   untouched  large 13-> 9   size-large  4.88-> 4.79
#:                   linux-x1   large 15->10   size-large  7.06-> 5.22
#:   FWS 6 pos 169   untouched  large 11->16   size-large 21.75->22.00
#:                   linux-x1   large 23->24   size-large 18.36->30.38
#:
#: 240 IS REINSTATED. 735c3b8 struck it because the untouched size fell
#: 4.51 to 1.00 - but that was the mixture, not the size. Under the
#: state rule the untouched size-large is 4.88 -> 4.79, flat, while
#: linux-x1's falls 7.06 -> 5.22. And the COUNT falls on both boards,
#: 13->9 untouched against 15->10, so the count is drift and the size
#: is not. Exactly what windows-desk predicted before computing it.
#:
#: So both FWS 4 positions are eligible on SIZE and neither on count,
#: and the ruling in 589329e that "FWS 4 has zero eligible positions"
#: was an artifact of the statistic twice over - first the pooled
#: median, then site-presence counting. The control was never wrong;
#: what it was applied to was wrong, twice, and another bench caught
#: both.
#:
#: Eligible on size: 219 and 240 at FWS 4, 134 at FWS 5, 169 and 180
#: at FWS 6. Eligible on count: none - every count move is matched on
#: the untouched board.
RETURN_COMPONENTS = ("large_count", "size_when_large", "size_when_small")
#: The state cut is the largest gap in the position's pooled values
#: across the two arms being compared, so it is a property of the
#: comparison and must be recomputed per comparison, never carried.


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


def seven_sum(path, fws=6, drop=(1,)):
    """Secondary (a): the seven stable lattice points, median-centred."""
    rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    rows = [r for r in rows if r["run"] not in drop and r.get("fws") == fws]
    if not rows or "profile" not in rows[0]:
        return None, 0
    vals = []
    for r in rows:
        m = statistics.median(r["profile"])
        vals.append(sum(abs(r["profile"][b] - m) for b in SEVEN))
    return statistics.median(vals), len(vals)


def site_devs(path, fws=6, drop=(1,)):
    """Secondary (b): median |deviation| at each exchange site."""
    rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    rows = [r for r in rows if r["run"] not in drop and r.get("fws") == fws]
    if not rows or "profile" not in rows[0]:
        return None
    return {b: statistics.median(abs(r["profile"][b]) for r in rows)
            for b in EXCHANGE}


def site_devs_by_mode(path, fws=6, drop=(1,)):
    """Per-site medians split by the run-level mode, where there is one.

    A pooled median over a bimodal arm moves when OCCUPANCY moves, with
    no per-mode change at all, and 75/180/201 are precisely the sites
    windows-desk's modes move. Uses their classifier rather than a
    second one - two homes for one rule is the failure this project
    carves its shared-source invariant around, and a crossover scored
    against a differently-drawn mode boundary would be unreadable.
    """
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import issue5_modes
    rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    rows = [r for r in rows if r["run"] not in drop and r.get("fws") == fws]
    if not rows or "profile" not in rows[0]:
        return None
    tot = [r["total_abs"] for r in rows]
    c = issue5_modes.classify(tot)
    if c.get("modes") != 2:
        return None
    cut = c["cut"]
    out = []
    for name, grp in (("low", [r for r in rows if r["total_abs"] < cut]),
                      ("high", [r for r in rows if r["total_abs"] >= cut])):
        out.append((name,
                    {b: statistics.median(abs(r["profile"][b]) for r in grp)
                     for b in EXCHANGE}, len(grp)))
    return out


def check():
    arms = {}
    for b in BASELINE:
        p = os.path.join(ROOT, "records", f"issue5-crossover-{b}.jsonl")
        if os.path.exists(p):
            arms[b] = p
    if not arms:
        print("no crossover arms yet; registration stands")
        return 0

    # --- the control gates everything, INCLUDING its own absence -------
    #
    # This printed a MATERIAL/DIE verdict when the control arm was merely
    # missing, because the control was checked only `if "mac-bench" in
    # got`. A verdict printed before its own precondition is the shape
    # this project keeps paying for - windows-desk caught it quoting
    # "-> DIE" off an unreadable run. Missing control is now VOID, which
    # is the same answer as a failed one: not yet readable.
    if "mac-bench" not in arms:
        print("  CONTROL: mac-bench crossover arm ABSENT -> VOID")
        print("  No verdict. The untouched board is what separates a "
              "swap-sized change from a session-sized one, so nothing "
              "here is readable without it.")
        return 1
    mac, n_mac = comb_sum(arms["mac-bench"])
    drift = mac - BASELINE["mac-bench"]["comb"]
    ok = abs(drift) <= CONTROL_TOL
    print(f"  CONTROL: mac-bench {BASELINE['mac-bench']['comb']:.2f} -> "
          f"{mac:.2f}, moved {drift:+.2f} against {CONTROL_TOL:.2f} "
          f"(n={n_mac}) -> {'ok' if ok else 'VOID'}")
    if not ok:
        print("  The untouched board moved. Nothing else is readable.")
        return 1

    print(f"\n  PRIMARY, profile/12")
    for b in sorted(arms):
        v, n = comb_sum(arms[b])
        print(f"    {b:14s} {BASELINE[b]['comb']:7.2f} -> {v:7.2f}  "
              f"({v - BASELINE[b]['comb']:+.2f}, n={n})")
    if "linux-x1" in arms and "windows-desk" in arms:
        L1 = comb_sum(arms["linux-x1"])[0]
        W1 = comb_sum(arms["windows-desk"])[0]
        D = (L0 - L1) + (W1 - W0)
        print(f"    D = ({L0:.2f} - {L1:.2f}) + ({W1:.2f} - {W0:.2f}) "
              f"= {D:.2f}")
        print(f"    material {D_MATERIAL:+.2f}, die {D_DIE:+.2f}, "
              f"cut {D_CUT:.2f}")
        # A verdict is only meaningful between the two predictions. D
        # far BELOW the die prediction is not evidence for the die - it
        # is an arm moving in a direction neither hypothesis allows, and
        # the registered binary did not anticipate it. Reported as its
        # own outcome rather than collapsed into DIE.
        if D > D_CUT:
            print("    -> MATERIAL")
        elif D < D_DIE - CONTROL_TOL:
            print(f"    -> NEITHER. D is {D_DIE - D:.2f} below the die "
                  f"prediction while the control moved {abs(drift):.2f}, "
                  f"so this is not drift and not an exchange. The "
                  f"registered rule would print DIE and that reading is "
                  f"wrong; see the per-arm moves above for which board "
                  f"carried it.")
        else:
            print("    -> DIE")

    print(f"\n  SECONDARY (a), seven stable sites")
    for b in sorted(arms):
        v, n = seven_sum(arms[b])
        print(f"    {b:14s} {SEVEN_BASE[b]:7.2f} -> {v:7.2f}  "
              f"({v - SEVEN_BASE[b]:+.2f}, sd {SEVEN_SD[b]:.2f})")
    if "linux-x1" in arms and "windows-desk" in arms:
        l7 = seven_sum(arms["linux-x1"])[0]
        w7 = seven_sum(arms["windows-desk"])[0]
        D7 = (SEVEN_BASE["linux-x1"] - l7) + (w7 - SEVEN_BASE["windows-desk"])
        print(f"    D_seven = {D7:+.2f}, material {2 * SEVEN_GAP:+.2f}, "
              f"cut {SEVEN_CUT:.2f} -> "
              f"{'MATERIAL' if D7 > SEVEN_CUT else 'no move'}")

    print(f"\n  SECONDARY (b), per-site exchange")
    print(f"    {'':14s} {'75':>8s} {'180':>8s} {'201':>8s}")
    print(f"    {'copper row':14s} " +
          " ".join(f"{EXCHANGE_COPPER[b]:8.2f}" for b in EXCHANGE))
    print(f"    {'iron row':14s} " +
          " ".join(f"{EXCHANGE_IRON[b]:8.2f}" for b in EXCHANGE))
    # Registered: "on the windows board these are reported PER MODE,
    # because 75, 180 and 201 are exactly the sites its modes move."
    # That was a sentence in the registration and nothing executed it,
    # so this printed a POOLED row whose change is mostly occupancy -
    # windows-desk's 75 reads 3.41 -> 5.73 pooled and 5.28 -> 5.93 /
    # 1.49 -> 1.64 per mode. Split wherever the classifier splits, not
    # only on the bench the sentence named: mac-bench has two modes too,
    # and linux-x1 acquired them in this arm.
    for b in sorted(arms):
        d = site_devs(arms[b])
        want = "iron row" if b == "linux-x1" else (
            "copper row" if b == "windows-desk" else "unchanged")
        print(f"    {b:14s} " + " ".join(f"{d[x]:8.2f}" for x in EXCHANGE)
              + f"   predicted: {want}")
        m = site_devs_by_mode(arms[b])
        if m:
            for name, dd, n in m:
                print(f"      {name:12s} " +
                      " ".join(f"{dd[x]:8.2f}" for x in EXCHANGE) +
                      f"   (n={n})")
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
