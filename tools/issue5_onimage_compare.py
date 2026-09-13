#!/usr/bin/env python3
"""#5 across benches on one image: site incidence and severity, per FWS.

    python3 tools/issue5_onimage_compare.py

Reads every `records/issue5-onimage-*.jsonl` and compares them. Needs no
board: the captures are already taken.

THE COMPARISON IS ONLY A COMPARISON IF THE IMAGE IS ONE IMAGE. `CLAUDE.md`
establishes that #5's site set and its severity are both drawn by the
binary - Jaccard 0.154 between two code generators against 0.885 for one
image against itself - so this refuses unless every row agrees on
`fw_repo_rev`, `fw_layout`, `fw_build_env`, `preset` and `track`. A
mixed set is not a bench comparison and will not be printed as one.

READ EACH FIGURE AGAINST THE BENCH'S OWN CEILING, never against the
other bench's and never against a number from another arm. The ceiling
here is block A against block B of the same wait state inside one
session, which carries the same drift a cross-bench comparison does. A
bench whose own ceiling is low at some wait state cannot contribute a
difference at that wait state: windows-desk's FWS 5 blocks disagree with
each other (Jaccard 0.500) as much as the two benches do.

A SITE SET IS A THRESHOLD OVER AN INCIDENCE, and the threshold can
manufacture a disagreement. `issue5_sites.py` prints membership at
">= 12 of 24"; a phase drawn in 11 runs on one bench and 13 on another
is one site apart by that reading and identical by any honest one. So
this prints the cut-off's sensitivity and the per-site counts, and the
counts are what a claim should quote.
"""
import collections
import itertools
import json
import math
import os
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RECORDS = os.path.join(ROOT, "records")
#: Matches `issue5_sites.py`'s own ">= 12 of 24" reading.
CUT = 0.5


def load():
    """Every on-image record, keyed by the bench its rows name.

    TWO FILES CLAIMING ONE BENCH IS REFUSED, not merged and not
    last-one-wins. The glob is a prefix, so a second session's rows
    filed as `issue5-onimage-<bench>-fws5.jsonl` would sort after the
    arm's and silently replace it - and the replacement would be a
    partial session, whose block-to-block ceiling means something else
    entirely. A bench comparison that quietly swapped one bench's data
    is the failure this whole tool exists to prevent one layer up.

    File a second session under a name that does not start with
    `issue5-onimage-`, as `records/issue5-fws5-repeat-windows-desk.jsonl`
    does.
    """
    out, whose = {}, {}
    for name in sorted(os.listdir(RECORDS)):
        if not (name.startswith("issue5-onimage-")
                and name.endswith(".jsonl")):
            continue
        with open(os.path.join(RECORDS, name)) as fh:
            rows = [json.loads(l) for l in fh if l.strip()]
        if not rows:
            continue
        bench = rows[0]["bench"]
        if bench in out:
            sys.exit(f"REFUSING: {name} and {whose[bench]} both carry "
                     f"bench {bench!r}. One of them would silently "
                     f"replace the other. File a second session under a "
                     f"name that does not start with 'issue5-onimage-'.")
        out[bench], whose[bench] = rows, name
    return out


def counts(rows):
    return collections.Counter(b for r in rows for b, _v, _z in r["sites"])


def members(rows, frac=CUT):
    c = counts(rows)
    return {b for b, n in c.items() if n >= frac * len(rows)}


def jaccard(a, b):
    return len(a & b) / len(a | b) if (a | b) else 1.0


def mannwhitney(x, y):
    """Two-sided U, normal approximation with tied ranks."""
    n1, n2 = len(x), len(y)
    if not n1 or not n2:
        return float("nan")
    allv = sorted([(v, 0) for v in x] + [(v, 1) for v in y])
    rank = {}
    i = 0
    while i < len(allv):
        j = i
        while j + 1 < len(allv) and allv[j + 1][0] == allv[i][0]:
            j += 1
        r = (i + j) / 2 + 1
        for k in range(i, j + 1):
            rank[k] = r
        i = j + 1
    r1 = sum(rank[k] for k, (_v, g) in enumerate(allv) if g == 0)
    u1 = r1 - n1 * (n1 + 1) / 2
    u = min(u1, n1 * n2 - u1)
    sd = math.sqrt(n1 * n2 * (n1 + n2 + 1) / 12)
    return math.erfc(abs((u - n1 * n2 / 2) / sd) / math.sqrt(2))


def main():
    benches = load()
    if len(benches) < 2:
        print(f"only {len(benches)} bench(es) have rows; need two to compare")
        return 1

    print("PROVENANCE")
    keys = set()
    for b, rows in sorted(benches.items()):
        r = rows[0]
        keys.add((r["fw_repo_rev"], r["fw_layout"], r["fw_build_env"],
                  r["preset"], r["track"]))
        print(f"  {b:14s} n={len(rows):3d}  build={r['fw_repo_rev']}  "
              f"layout={r['fw_layout']}  {r['fw_build_env']}  "
              f"preset={r['preset']}  track={r['track']}")
    if len(keys) != 1:
        print("\nREFUSING: these rows are not one image, one preset and one "
              "track, so a difference between them is not attributable to "
              "the bench. #5 is drawn by the binary.")
        return 2
    print("  -> one image, one preset, one track")

    for fws in sorted({r["fws"] for rows in benches.values() for r in rows
                       if r["fws"] is not None}):
        print(f"\n{'=' * 70}\nFWS {fws}")
        sets, sev, blocks = {}, {}, {}
        for b, rows in sorted(benches.items()):
            v = sorted([r for r in rows if r["fws"] == fws],
                       key=lambda r: r["run"])
            sets[b], sev[b] = members(v), [r["total_abs"] for r in v]
            h1, h2 = v[:len(v) // 2], v[len(v) // 2:]
            t1 = statistics.median([r["total_abs"] for r in h1])
            t2 = statistics.median([r["total_abs"] for r in h2])
            blocks[b] = (jaccard(members(h1), members(h2)),
                         min(t1, t2) / max(t1, t2))
            print(f"  {b:14s} sites {sorted(sets[b])}")
            print(f"  {'':14s} median total|dev| "
                  f"{statistics.median(sev[b]):8.1f}     own ceiling: "
                  f"Jaccard {blocks[b][0]:.3f}, severity {blocks[b][1]:.3f}")

        for a, b in itertools.combinations(sorted(benches), 2):
            va = [r for r in benches[a] if r["fws"] == fws]
            vb = [r for r in benches[b] if r["fws"] == fws]
            print(f"\n  {a} vs {b}")
            print("    cut-off sensitivity  " + "  ".join(
                f">={int(f * 100)}%: {jaccard(members(va, f), members(vb, f)):.3f}"
                for f in (0.25, CUT, 0.75)))
            ca, cb = counts(va), counts(vb)
            phases = sorted(set(ca) | set(cb))
            print(f"    {'phase':>8}" + "".join(f"{p:>6}" for p in phases))
            print(f"    {a[:8]:>8}" + "".join(f"{ca[p]:>6}" for p in phases))
            print(f"    {b[:8]:>8}" + "".join(f"{cb[p]:>6}" for p in phases))
            print(f"    (of {len(va)} and {len(vb)} runs)")
            ma, mb = statistics.median(sev[a]), statistics.median(sev[b])
            note = ""
            worst = min(blocks[a][1], blocks[b][1])
            if min(ma, mb) / max(ma, mb) >= worst:
                note = ("  - inside the weaker bench's own block-to-block "
                        "ratio, so it is not a bench difference")
            print(f"    severity {ma:.1f} vs {mb:.1f}, ratio "
                  f"{min(ma, mb) / max(ma, mb):.3f}, Mann-Whitney p = "
                  f"{mannwhitney(sev[a], sev[b]):.2e}{note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
