#!/usr/bin/env python3
"""Issue #83: score a refresh threshold arm by the rule registered on the issue.

An arm is `tools/issue5_alias_sweep.py --fws 6 -n 7` over a set of presets,
run as whole blocks on images of one tree that differ only in
`GEN_REFRESH_STREAM`, in a registered order. A block joins the record only
once all its rows are complete, so a row's block is its position; the
guards below refuse a record where that does not hold.

Classification, as registered before any row existed:

- run 1 of every (block, RC) is dropped by index; `hold_ok` false is
  excluded and counted;
- everything is compared within one RC, against the pooled counted runs of
  every REFRESH 0 block at that RC;
- FLOOR: the block's counted total_abs range overlaps that pool;
- LIFTED: every counted run above the pool's maximum, and the block median
  at least 1.5x the pool's median;
- MARGINAL: no overlap, under 1.5x.

Three verdicts, one per arm:

- the ladder (default): a rung where the two blocks of one value classify
  differently is UNSTABLE, a rung where REFRESH 1 is not lifted is
  UNINFORMATIVE, both are left out, and T for a value is the lowest rung
  from which that rung and every longer one are lifted;
- the bracket (`--pairs 2:480,544;4:960,1088`): for each value, the lower
  rung must be FLOOR and the upper NOT FLOOR (lifted or marginal). A rung
  where that value's blocks disagree about floor is UNSTABLE, a rung where
  REFRESH 1 is floor is UNINFORMATIVE; either leaves the value unscored;
- the step shape (`--steps 3:704,...,784;4:960,...,1040`, V1d): a value
  whose blocks disagree about any of its rungs, or whose REFRESH 1 control
  is floor at any of them, is UNINFORMATIVE. Otherwise its rungs, in
  increasing interval, are read by step_reading() against 512 x value.

    .venv/bin/python tools/issue83_threshold_score.py \
        records/issue83-threshold-sweep-linux-x1.jsonl
    .venv/bin/python tools/issue83_threshold_score.py \
        records/issue83-bracket-linux-x1.jsonl \
        --order 2,0,4,1,4,0,2 --per-block 28 --pairs "2:480,544;4:960,1088"
"""
import argparse
import collections
import json
import os
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LADDER_ORDER = "2,0,4,1,3,2,0"    # registered on #83 for the ladder
LADDER_PER_BLOCK = 70             # 10 presets x 7 runs
THRESHOLD_CLOCKS = 512            # per refresh value, the reading under test
RANK = {"floor": 0, "marginal": 1, "lifted": 2}


def load(path, order, per_block):
    with open(path, encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]
    if len(rows) % per_block:
        raise SystemExit(f"{len(rows)} rows is not whole blocks of {per_block}")
    if len(rows) // per_block > len(order):
        raise SystemExit(f"{len(rows) // per_block} blocks, registered order has {len(order)}")
    builds = collections.defaultdict(set)
    for i, r in enumerate(rows):
        builds[i // per_block + 1].add(r["fw_build"])
    for blk, bs in builds.items():
        if len(bs) != 1:
            raise SystemExit(f"block {blk} spans images {sorted(bs)}")
        v, b = order[blk - 1], next(iter(bs))
        if (v == 0) != ("+" not in b):
            raise SystemExit(f"block {blk} is REFRESH {v} on build {b}")
    for a in builds:
        for c in builds:
            if (builds[a] == builds[c]) != (order[a - 1] == order[c - 1]):
                raise SystemExit(f"blocks {a} and {c}: image identity does "
                                 f"not match refresh value")
    return rows


def intervals(rows):
    """Write interval per RC: the row's own figure, 2 x RC for rows before it.

    Under SOLO a DAC0 write is RC clocks, not 2 x RC, so the sweep records
    it and this reads it back rather than re-deriving it.
    """
    iv = {}
    for r in rows:
        w = r.get("write_interval_clocks", 2 * r["rc"])
        if iv.setdefault(r["rc"], w) != w:
            raise SystemExit(f"RC {r['rc']} carries two write intervals, "
                             f"{iv[r['rc']]} and {w}: score each sync mode apart")
    return iv


def classify(ta, floor):
    if min(ta) <= max(floor):
        return "floor"
    return "lifted" if statistics.median(ta) >= 1.5 * statistics.median(floor) else "marginal"


def parse_pairs(text):
    pairs = {}
    for part in text.split(";"):
        v, rcs = part.split(":")
        lo, hi = (int(x) for x in rcs.split(","))
        if not lo < hi:
            raise SystemExit(f"pair for REFRESH {v}: lower rung {lo} is not below {hi}")
        pairs[int(v)] = (lo, hi)
    return pairs


def parse_steps(text):
    steps = {}
    for part in text.split(";"):
        v, rcs = part.split(":")
        rungs = [int(x) for x in rcs.split(",")]
        if rungs != sorted(set(rungs)) or len(rungs) < 3:
            raise SystemExit(f"steps for REFRESH {v}: rungs must be three or more, "
                             f"increasing: {rungs}")
        steps[int(v)] = rungs
    return steps


def step_reading(seq, threshold):
    """Read one value's rungs, registered on #83 for V1d before any row.

    `seq` is [(interval, class, ratio)] in increasing interval, `ratio` the
    value's pooled counted median over the REFRESH 0 median at that rung.
    The shape must be monotone - floor rungs, then marginal, then lifted -
    before any reading applies. The three readings are disjoint: STEP AT
    needs every rung below the threshold floor, STEP BELOW a non-floor rung
    below it, and RAMP two or more marginal rungs where both steps allow
    one. Every other shape is named rather than scored.
    """
    cls = [c for _, c, _ in seq]
    if any(RANK[b] < RANK[a] for a, b in zip(cls, cls[1:])):
        return "NON-MONOTONE"
    nf, nm, nl = cls.count("floor"), cls.count("marginal"), cls.count("lifted")
    if nf == len(cls):
        return "NO STEP IN WINDOW"
    if nf == 0:
        return "ONSET BELOW WINDOW"
    if nl == 0:
        return "NOT LIFTED BY THE TOP RUNG"
    if (all(c == "floor" for iv, c, _ in seq if iv < threshold)
            and all(c == "lifted" for iv, c, _ in seq if iv > threshold)):
        return "STEP AT 512 x VALUE"
    if nm <= 1:
        if seq[nf][0] < threshold:
            return "STEP BELOW 512 x VALUE"
        return "STEP ABOVE 512 x VALUE"
    ratios = [r for _, c, r in seq if c == "marginal"]
    if all(b >= a for a, b in zip(ratios, ratios[1:])):
        return "RAMP"
    return "RAMP NOT RISING"


REGISTERED_READINGS = ("STEP AT 512 x VALUE", "STEP BELOW 512 x VALUE", "RAMP")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("record", nargs="?", default=os.path.join(
        ROOT, "records", "issue83-threshold-sweep-linux-x1.jsonl"))
    ap.add_argument("--order", default=LADDER_ORDER,
                    help="registered refresh value per block, comma separated")
    ap.add_argument("--per-block", type=int, default=LADDER_PER_BLOCK)
    ap.add_argument("--pairs", default=None,
                    help="bracket verdict, e.g. '2:480,544;4:960,1088'")
    ap.add_argument("--steps", default=None,
                    help="step-shape verdict, e.g. '3:704,720,736;4:960,976,992'")
    args = ap.parse_args()
    if args.pairs and args.steps:
        raise SystemExit("--pairs and --steps are two different arms")
    order = [int(x) for x in args.order.split(",")]
    rows = load(args.record, order, args.per_block)

    data = collections.defaultdict(list)
    excluded = collections.Counter()
    for i, r in enumerate(rows):
        blk = i // args.per_block + 1
        key = (blk, order[blk - 1], r["rc"])
        if r["run1"]:
            continue
        if not r["hold_ok"]:
            excluded[key] += 1
            continue
        data[key].append((r["total_abs"], r["n_sites"]))

    rcs = sorted({r["rc"] for r in rows})
    iv = intervals(rows)
    blocks_of = collections.defaultdict(list)
    for blk, v, _ in data:
        if blk not in blocks_of[v]:
            blocks_of[v].append(blk)
    if not blocks_of[0]:
        raise SystemExit("no REFRESH 0 block: nothing to read a floor against")

    def floor_at(rc):
        return [x for b in blocks_of[0] for x, _ in data[(b, 0, rc)]]

    print("counted total_abs: median [min-max], median sites, class against the REFRESH 0 pool")
    state = {}
    ratio = {}
    for rc in rcs:
        fl = floor_at(rc)
        print(f"RC {rc:4d}  interval {iv[rc]:4d} clocks  floor median "
              f"{statistics.median(fl):6.1f}  max {max(fl):6.1f}")
        for v in sorted(blocks_of):
            cls = []
            for b in blocks_of[v]:
                d = data[(b, v, rc)]
                ta = [x for x, _ in d]
                c = classify(ta, fl) if v else "-"
                cls.append(c)
                ex = excluded[(b, v, rc)]
                print(f"   REFRESH {v} block {b}: n={len(ta)} {statistics.median(ta):7.1f} "
                      f"[{min(ta):.1f}-{max(ta):.1f}] sites {statistics.median([s for _, s in d]):.0f} "
                      f"{c}" + (f"  (hold_ok false: {ex})" if ex else ""))
            if v:
                state[(v, rc)] = cls
                pooled = [x for b in blocks_of[v] for x, _ in data[(b, v, rc)]]
                ratio[(v, rc)] = statistics.median(pooled) / statistics.median(fl)

    print("\nREGISTERED VERDICTS")
    r0 = blocks_of[0]
    sep = [rc for rc in rcs for a in r0 for c in r0 if a != c
           and classify([x for x, _ in data[(a, 0, rc)]], [x for x, _ in data[(c, 0, rc)]]) != "floor"]
    print(f"  REFRESH 0 blocks separate at: {sorted(set(sep)) or 'no rung'}")

    if args.pairs:
        return bracket(parse_pairs(args.pairs), rcs, state, iv)
    if args.steps:
        return steps(parse_steps(args.steps), rcs, state, ratio, iv)
    return ladder(rcs, state, blocks_of, iv)


def bracket(pairs, rcs, state, iv):
    for v, (lo, hi) in pairs.items():
        for rc in (lo, hi):
            if rc not in rcs or (v, rc) not in state or (1, rc) not in state:
                raise SystemExit(f"REFRESH {v} or the REFRESH 1 control has no rows at RC {rc}")
    uninformative = [rc for rc in sorted({x for p in pairs.values() for x in p})
                     if any(c == "floor" for c in state[(1, rc)])]
    print(f"  REFRESH 1 floor (uninformative rungs): {uninformative or 'none'}")
    for v, (lo, hi) in sorted(pairs.items()):
        lo_c, hi_c = state[(v, lo)], state[(v, hi)]
        unstable = [rc for rc, cl in ((lo, lo_c), (hi, hi_c))
                    if len({c == "floor" for c in cl}) > 1]
        desc = (f"RC {lo} ({iv[lo]} clocks) {'/'.join(lo_c)}, "
                f"RC {hi} ({iv[hi]} clocks) {'/'.join(hi_c)}")
        if unstable or lo in uninformative or hi in uninformative:
            print(f"  REFRESH {v}: UNSCORED - {desc}; unstable {unstable or 'none'}, "
                  f"uninformative {[rc for rc in (lo, hi) if rc in uninformative] or 'none'}")
            continue
        ok = lo_c[0] == "floor" and hi_c[0] != "floor"
        print(f"  REFRESH {v}: {'CONFIRMED' if ok else 'REFUTED'} - {desc}")
    return 0


def steps(spec, rcs, state, ratio, iv):
    for v, rungs in spec.items():
        for rc in rungs:
            if rc not in rcs or (v, rc) not in state or (1, rc) not in state:
                raise SystemExit(f"REFRESH {v} or the REFRESH 1 control has no rows at RC {rc}")
    for v, rungs in sorted(spec.items()):
        threshold = THRESHOLD_CLOCKS * v
        unstable = [rc for rc in rungs if len(set(state[(v, rc)])) > 1]
        control_floor = [rc for rc in rungs if any(c == "floor" for c in state[(1, rc)])]
        line = "  ".join(f"{iv[rc]}:{'/'.join(c[0].upper() for c in state[(v, rc)])}"
                         f"({ratio[(v, rc)]:.2f}x)" for rc in rungs)
        print(f"  REFRESH {v}, threshold {threshold} clocks: {line}")
        if unstable or control_floor:
            print(f"      UNINFORMATIVE - blocks disagree at RC {unstable or 'none'}, "
                  f"REFRESH 1 floor at RC {control_floor or 'none'}")
            continue
        seq = [(iv[rc], state[(v, rc)][0], ratio[(v, rc)]) for rc in rungs]
        reading = step_reading(seq, threshold)
        tag = "" if reading in REGISTERED_READINGS else "  (matches no registered reading)"
        print(f"      {reading}{tag}")
    return 0


def ladder(rcs, state, blocks_of, iv):
    uninformative = [rc for rc in rcs if 1 in blocks_of and state[(1, rc)][0] != "lifted"]
    verdict = "OVERALL UNINFORMATIVE" if len(uninformative) > len(rcs) / 2 else "control holds"
    print(f"  REFRESH 1 not lifted (uninformative rungs): {uninformative or 'none'} - {verdict}")

    for v in sorted(k for k in blocks_of if k >= 2):
        unstable = [rc for rc in rcs if len(set(state[(v, rc)])) > 1]
        seq = [(rc, state[(v, rc)][0]) for rc in rcs
               if rc not in uninformative and rc not in unstable]
        t = None
        for i in range(len(seq)):
            if all(s == "lifted" for _, s in seq[i:]):
                t = i
                break
        line = " ".join(f"{rc}:{s[0].upper()}" for rc, s in seq)
        print(f"  REFRESH {v}: {line}   unstable {unstable or 'none'}")
        if t is not None:
            below = [s for _, s in seq[:t]]
            broken = [s for s in below[:-1] if s != "floor"]
            lo = iv[seq[t - 1][0]] if t else None
            print(f"      T{v} = {iv[seq[t][0]]} clocks, step bracket ({lo}, {iv[seq[t][0]]}]"
                  f"  {'MONOTONE' if not broken else 'NON-MONOTONE below T: ' + str(broken)}")
        else:
            not_lifted_top = [rc for rc, s in seq if s != "lifted"
                              and any(s2 == "lifted" for rc2, s2 in seq if rc2 < rc)]
            print(f"      T{v} undefined by the rule: rungs above a lifted rung that are not "
                  f"lifted: {not_lifted_top}")
            last_floor = max((i for i, (_, s) in enumerate(seq) if s == "floor"
                              and all(s2 == "floor" for _, s2 in seq[:i + 1])), default=None)
            if last_floor is not None and last_floor + 1 < len(seq):
                print(f"      onset (outside the registered rule): first non-floor at "
                      f"{iv[seq[last_floor + 1][0]]} clocks, after floor through "
                      f"{iv[seq[last_floor][0]]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
