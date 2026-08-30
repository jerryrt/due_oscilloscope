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


def _gaps(d):
    """Gap census for one channel-capture, or None if unreadable.

    The record files do not agree on how sites are stored, and the first
    version of this tool read only one of the shapes and SILENTLY
    SKIPPED the rest. It therefore reported zero conversion-locked
    captures over the host-path records - the very rows that had
    produced them - because tools/issue24_holdavg.py writes `sites` as
    plain bin numbers and carries its own precomputed `gaps`.

    An instrument that cannot see a row must say so, not score it as an
    absence. Hence the skipped-row report, which is not optional
    decoration: a silent skip is how this issue keeps manufacturing
    nulls.
    """
    g = d.get("gaps")
    if isinstance(g, dict) and g:
        return collections.Counter({int(k): v for k, v in g.items()})
    key = "sites_table" if d.get("sites_table") else "sites"
    raw = d.get(key)
    if not raw:
        return None
    bins = []
    for s in raw:
        if isinstance(s, (list, tuple)) and s:
            bins.append(s[0])
        elif isinstance(s, (int, float)):
            bins.append(s)
    bins = sorted(bins)
    if len(bins) < 2:
        return None
    return collections.Counter(bins[i + 1] - bins[i]
                               for i in range(len(bins) - 1))


def classify(g, hold=1):
    """Sub-combs of a 21 lattice count as update-locked.

    A lattice of 21 routinely arrives as two interleaved combs whose
    gaps sum to 21 - 8+13, 4+17 - so counting only literal 21s
    undercounts it badly.

    The conversion-locked signature is HOLD-DEPENDENT and the first
    version of this hard-coded hold 2's. A comb of 21 ADC conversions
    lands at 21/hold DAC updates: 10 or 11 at hold 2, 7 at hold 3, 5 or
    6 at hold 4. Scoring every capture against 10/11 classified every
    hold-3 conversion-locked capture as "weak" - a null manufactured by
    the classifier, in a tool written to stop exactly that.

    At hold 1 the two lattices coincide by construction and no rule can
    separate them, so nothing is ever called conversion-locked there.
    """
    upd = sum(g.get(k, 0) for k in (21, 4, 17, 8, 13))
    if hold <= 1:
        conv = 0
    else:
        lo, hi = int(21 // hold), -(-21 // hold)   # floor and ceil
        conv = sum(g.get(k, 0) for k in {lo, hi})
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
    ap.add_argument("--hold", type=int, default=0,
                    help="hold for records that do not carry one. The "
                         "internal-path files do not: gen NORMAL "
                         "alternates DAC0/DAC1 while A0 converts every "
                         "trigger, so it is a hold of 2 and must be "
                         "given as one. Defaulting those to 1 sets the "
                         "conversion-locked count to zero BY "
                         "CONSTRUCTION, which is a null the tool "
                         "invents rather than measures.")
    args = ap.parse_args()
    per, pooled, n = collections.Counter(), collections.Counter(), 0
    skipped = collections.Counter()
    for path in sorted(glob.glob(os.path.join(ROOT, args.glob))):
        for line in open(path):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("bench") in EXCLUDE:
                continue
            hold = int(r.get("hold") or r.get("ratio") or args.hold or 1)
            # windows-desk's issue24_hold.py nests one entry per
            # decimation offset; each is its own reading of the capture.
            if isinstance(r.get("offsets"), list):
                chans = [(f"off{o.get('offset')}", o) for o in r["offsets"]]
            elif "a0" in r:
                chans = [("A0", r["a0"]), ("A1", r.get("a1") or {})]
            else:
                chans = [("A0", r)]
            for _tag, d in chans:
                g = _gaps(d)
                if g is None:
                    skipped[os.path.basename(path)] += 1
                    continue
                n += 1
                pooled.update(g)
                per[classify(g, hold)] += 1
    print(f"channel-captures classified: {n}\n")
    for k, v in per.most_common():
        print(f"   {k:20s} {v:4d}   ({100 * v / n:.0f}%)" if n else "")
    print("\npooled gap census:", dict(pooled.most_common(8)))
    if skipped:
        print(f"\nrows this tool could NOT read ({sum(skipped.values())}) - "
              f"these are NOT counted as absences:")
        for f, c in skipped.most_common():
            print(f"   {f:44s} {c:4d}")
    print("\n  quote the per-capture table, not the pooled census - the "
          "pooled one is a sample of draws")


if __name__ == "__main__":
    main()


def residue_classes(bins, period=21):
    """How many residue classes mod `period` a capture's sites occupy.

    #5 and docs/awg.md have described the internal path's structure as
    "two combs of period 21 offset by 3" throughout. Over 258 captures
    with four or more sites that describes 23 of them; the mode is
    THREE classes, at 162, with four to six in another 73.

    The control matters more than the count, because a capture with more
    sites occupies more classes for free. Drawing the same number of
    sites uniformly from the same circle gives a median of 7 classes at
    8 sites, 6 at 6 sites and 4 at 4; the observed median is 3 at every
    one of those. So the concentration is structure and not a by-product
    of how many sites cleared threshold.
    """
    return len({b % period for b in bins})
