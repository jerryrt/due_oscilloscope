#!/usr/bin/env python3
"""Issue #83 V1a: does REFRESH(1) collide at a 56-clock write interval?

Scores `tools/issue47_ratio.py` rows by the rule registered on #83 before
any row existed, as amended there by the lead's acceptance:

- a block is the ratio tool at RC 28 then RC 39, 25 reps each, on one
  image; blocks run in the registered order of refresh values;
- run 1 of every (block, RC) is dropped by index;
- n is the device-side deficit in 256ths, `(1 - ratio) * 256`, read
  against nominal. A draw of mode n is a counted run within half a unit
  of n. RC 28's second mode is n = 2 and RC 39's positive control n = 6.

Outcomes, in the registered words:

- COLLIDES AT 56: at least one n=2 draw at RC 28 in EACH REFRESH(1)
  block, and none in any REFRESH(0) block;
- NO DRAW AT 56 ON THIS IMAGE, INCIDENCE UNKNOWN: no n=2 draw at RC 28 on
  either image while RC 39 draws n=6 in every REFRESH(1) block. The
  registration's "threshold between 56 and 78" is reported this way,
  because a null is only worth what the incidence could have detected;
- UNINFORMATIVE: RC 39 draws no n=6 in some REFRESH(1) block, or a
  REFRESH(0) block draws n=2 at RC 28;
- anything else matches no registered outcome, and says so.

    .venv/bin/python tools/issue83_v1a_score.py \
        records/issue83-v1a-ratio-linux-x1.jsonl --order 1,0,1,0
"""
import argparse
import collections
import json
import sys

RCS = (28, 39)
REPS = 25
MODE_RC28 = 2
MODE_RC39 = 6


def n_of(ratio):
    return (1.0 - ratio) * 256.0


def is_draw(ratio, n):
    return abs(n_of(ratio) - n) < 0.5


def load(path, order):
    with open(path, encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]
    per_block = REPS * len(RCS)
    if len(rows) != per_block * len(order):
        raise SystemExit(f"{len(rows)} rows, registered {len(order)} blocks of "
                         f"{per_block}")
    blocks = []
    for b, v in enumerate(order):
        blk = rows[b * per_block:(b + 1) * per_block]
        for j, rc in enumerate(RCS):
            part = blk[j * REPS:(j + 1) * REPS]
            if [r["rc"] for r in part] != [rc] * REPS:
                raise SystemExit(f"block {b + 1}: rows {j * REPS + 1}-"
                                 f"{(j + 1) * REPS} are not RC {rc}")
            if [r["run"] for r in part] != list(range(1, REPS + 1)):
                raise SystemExit(f"block {b + 1} RC {rc}: runs are not 1-{REPS}")
        builds = {r["fw_build"] for r in blk}
        if len(builds) != 1:
            raise SystemExit(f"block {b + 1} spans images {sorted(builds)}")
        build = next(iter(builds))
        if (v == 0) != ("+" not in build):
            raise SystemExit(f"block {b + 1} is REFRESH {v} on build {build}")
        blocks.append((b + 1, v, build, blk))
    for _, va, ba, _ in blocks:
        for _, vc, bc, _ in blocks:
            if (ba == bc) != (va == vc):
                raise SystemExit("image identity does not match refresh value "
                                 "across blocks")
    return blocks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("record")
    ap.add_argument("--order", default="1,0,1,0")
    args = ap.parse_args()
    order = [int(x) for x in args.order.split(",")]
    blocks = load(args.record, order)

    draws28, draws39 = {}, {}
    print("counted runs (run 1 dropped by index): n = (1 - ratio) * 256")
    for blk, v, build, rows in blocks:
        for rc, mode, store in ((28, MODE_RC28, draws28), (39, MODE_RC39, draws39)):
            counted = [r for r in rows if r["rc"] == rc and r["run"] != 1]
            ns = [n_of(r["ratio"]) for r in counted]
            hist = collections.Counter(round(n) for n in ns)
            hits = sum(is_draw(r["ratio"], mode) for r in counted)
            worst = max(abs(n - round(n)) for n in ns)
            und = sum(1 for r in counted if r["underruns"])
            lost = sum(r["host_deficit_bytes"] for r in counted)
            store[blk] = hits
            print(f"  block {blk} REFRESH {v} {build:>20s} RC {rc}: n={len(counted)} "
                  f"modes {dict(sorted(hist.items()))}  n={mode} draws {hits}  "
                  f"worst residual {worst:.3f}  runs with underruns {und}  "
                  f"host bytes lost {lost}")

    r1 = [blk for blk, v, _, _ in blocks if v == 1]
    r0 = [blk for blk, v, _, _ in blocks if v == 0]
    control = all(draws39[b] > 0 for b in r1)
    r0_draws = sum(draws28[b] for b in r0)
    r1_each = all(draws28[b] > 0 for b in r1)
    r1_none = all(draws28[b] == 0 for b in r1)

    print("\nREGISTERED VERDICT")
    print(f"  RC 39 n={MODE_RC39} in every REFRESH(1) block: {control} "
          f"({[draws39[b] for b in r1]})")
    print(f"  RC 28 n={MODE_RC28} draws, REFRESH(1) blocks {[draws28[b] for b in r1]}, "
          f"REFRESH(0) blocks {[draws28[b] for b in r0]}")
    if not control or r0_draws:
        print("  UNINFORMATIVE")
    elif r1_each:
        print("  COLLIDES AT 56")
    elif r1_none:
        print("  NO DRAW AT 56 ON THIS IMAGE, INCIDENCE UNKNOWN")
    else:
        print("  MATCHES NO REGISTERED OUTCOME: some REFRESH(1) blocks draw at "
              "RC 28 and some do not")
    return 0


if __name__ == "__main__":
    sys.exit(main())
