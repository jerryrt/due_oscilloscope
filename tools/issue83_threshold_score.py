#!/usr/bin/env python3
"""Issue #83: score the refresh threshold sweep by the rule registered on the issue.

The sweep is `tools/issue5_alias_sweep.py --fws 6 -n 7` over ten presets,
RC 195 to 2600, run as seven whole blocks on seven images of one tree that
differ only in `GEN_REFRESH_STREAM`, in the registered order 2, 0, 4, 1, 3,
2, 0. A block joins the record only once its 70 rows are complete, so a
row's block is its position; the guards below refuse a record where that
does not hold.

The rule, as registered before any row existed:

- run 1 of every (block, RC) is dropped by index; `hold_ok` false is
  excluded and counted;
- everything is compared within one RC, against the pooled counted runs of
  both REFRESH 0 blocks at that RC;
- FLOOR: the block's counted total_abs range overlaps that pool;
- LIFTED: every counted run above the pool's maximum, and the block median
  at least 1.5x the pool's median;
- MARGINAL: no overlap, under 1.5x;
- a rung where the two blocks of one refresh value classify differently
  is UNSTABLE and left out; a rung where REFRESH 1 is not lifted is
  UNINFORMATIVE and left out;
- T for a value is the lowest rung from which that rung and every longer
  one are lifted, one marginal allowed immediately below it.

Where T does not exist the tool says why, and reports the onset - the
first lifted rung after the last floor - separately, labelled as outside
the registered rule.

    .venv/bin/python tools/issue83_threshold_score.py \
        records/issue83-threshold-sweep-linux-x1.jsonl
"""
import argparse
import collections
import json
import os
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ORDER = [2, 0, 4, 1, 3, 2, 0]    # registered on #83
PER_BLOCK = 70                   # 10 presets x 7 runs


def load(path):
    with open(path, encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]
    if len(rows) % PER_BLOCK:
        raise SystemExit(f"{len(rows)} rows is not whole blocks of {PER_BLOCK}")
    if len(rows) // PER_BLOCK > len(ORDER):
        raise SystemExit(f"{len(rows) // PER_BLOCK} blocks, registered order has {len(ORDER)}")
    builds = collections.defaultdict(set)
    for i, r in enumerate(rows):
        builds[i // PER_BLOCK + 1].add(r["fw_build"])
    for blk, bs in builds.items():
        if len(bs) != 1:
            raise SystemExit(f"block {blk} spans images {sorted(bs)}")
        v, b = ORDER[blk - 1], next(iter(bs))
        if (v == 0) != ("+" not in b):
            raise SystemExit(f"block {blk} is REFRESH {v} on build {b}")
    for a in builds:
        for c in builds:
            if (builds[a] == builds[c]) != (ORDER[a - 1] == ORDER[c - 1]):
                raise SystemExit(f"blocks {a} and {c}: image identity does "
                                 f"not match refresh value")
    return rows


def classify(ta, floor):
    if min(ta) <= max(floor):
        return "floor"
    return "lifted" if statistics.median(ta) >= 1.5 * statistics.median(floor) else "marginal"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("record", nargs="?", default=os.path.join(
        ROOT, "records", "issue83-threshold-sweep-linux-x1.jsonl"))
    args = ap.parse_args()
    rows = load(args.record)

    data = collections.defaultdict(list)
    excluded = collections.Counter()
    for i, r in enumerate(rows):
        blk = i // PER_BLOCK + 1
        key = (blk, ORDER[blk - 1], r["rc"])
        if r["run1"]:
            continue
        if not r["hold_ok"]:
            excluded[key] += 1
            continue
        data[key].append((r["total_abs"], r["n_sites"]))

    rcs = sorted({r["rc"] for r in rows})
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
    for rc in rcs:
        fl = floor_at(rc)
        print(f"RC {rc:4d}  interval {2 * rc:4d} clocks  floor median "
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

    print("\nREGISTERED VERDICTS")
    if len(blocks_of[0]) == 2:
        b1, b2 = blocks_of[0]
        sep = [rc for rc in rcs
               if classify([x for x, _ in data[(b1, 0, rc)]], [x for x, _ in data[(b2, 0, rc)]]) != "floor"
               or classify([x for x, _ in data[(b2, 0, rc)]], [x for x, _ in data[(b1, 0, rc)]]) != "floor"]
        print(f"  REFRESH 0 blocks separate at: {sep or 'no rung'}")
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
            lo = 2 * seq[t - 1][0] if t else None
            print(f"      T{v} = {2 * seq[t][0]} clocks, step bracket ({lo}, {2 * seq[t][0]}]"
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
                      f"{2 * seq[last_floor + 1][0]} clocks, after floor through "
                      f"{2 * seq[last_floor][0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
