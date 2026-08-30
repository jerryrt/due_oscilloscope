#!/usr/bin/env python3
"""Which lattice did each capture draw? Board-free, over the records.

96c92c5 established two lattices on the host-fed path, drawn per capture
and mutually exclusively: one locked to DAC updates, which gives a gap
of 21 at every hold, and one locked to ADC conversions, which gives 21
divided by the hold. At hold 1 they coincide by construction.

The point of this tool is that the classification must be PER CAPTURE.
A pooled census averages over draws, and on this defect that is not a
measurement of what is present - it is a sample of what was drawn. Four
published conclusions on issues #5 and #24 were withdrawn for exactly
that, mine included.

Internal-path bins are DAC0 levels, because pair_fold differences within
the hold: gen NORMAL holds each level for two A0 conversions, so 21 ADC
conversions is 10.5 levels and shows as alternating tens and elevens,
while 21 DAC updates shows as twenty-ones. Host-path bins are DAC0
updates after group_average, so the same rule reads directly.

    .venv/bin/python tools/issue24_draws.py
    .venv/bin/python tools/issue24_draws.py --glob 'records/issue24-*.jsonl'
"""
import argparse
import collections
import glob
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The port-fight block; see records/README.md.
EXCLUDE = {"macos-long2"}


def classify(g):
    """Sub-combs of a 21 lattice count as update-locked.

    A lattice of 21 routinely arrives as two interleaved combs whose
    gaps sum to 21 - 8+13, 4+17 - so counting only literal 21s
    undercounts it badly.
    """
    upd = sum(g.get(k, 0) for k in (21, 4, 17, 8, 13))
    conv = g.get(10, 0) + g.get(11, 0)
    if conv >= 3 and upd >= 3:
        return "BOTH"
    if conv >= 3:
        return "conversion-locked"
    if upd >= 3:
        return "update-locked"
    return "no sites" if not g else "weak"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--glob", default="records/issue5-*.jsonl")
    args = ap.parse_args()
    per, pooled, n = collections.Counter(), collections.Counter(), 0
    for path in sorted(glob.glob(os.path.join(ROOT, args.glob))):
        for line in open(path):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("bench") in EXCLUDE:
                continue
            chans = ([("A0", r["a0"]), ("A1", r.get("a1") or {})]
                     if "a0" in r else [("A0", r)])
            for _tag, d in chans:
                key = "sites_table" if d.get("sites_table") else "sites"
                b = sorted(s[0] for s in (d.get(key) or [])
                           if isinstance(s, list))
                if len(b) < 2:
                    continue
                n += 1
                g = collections.Counter(b[i + 1] - b[i]
                                        for i in range(len(b) - 1))
                pooled.update(g)
                per[classify(g)] += 1
    print(f"channel-captures classified: {n}\n")
    for k, v in per.most_common():
        print(f"   {k:20s} {v:4d}   ({100 * v / n:.0f}%)" if n else "")
    print("\npooled gap census:", dict(pooled.most_common(8)))
    print("\n  quote the per-capture table, not the pooled census - the "
          "pooled one is a sample of draws")


if __name__ == "__main__":
    main()
