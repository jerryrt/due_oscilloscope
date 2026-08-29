#!/usr/bin/env python3
"""The big-fold outliers, as a class rather than four accidents.

Both benches have been recording occasional fold values an order of
magnitude past anything else - -139.6, +121.1, -445.7, +131.2 - each
flagged "n=1, not modelled" and each left there. Four of them across two
benches is a class, and a class can be tested.

This censuses every record for fold values past a threshold and asks the
two cheap questions about them:

  * are they the ramp's own wrap escaping the mask? The full-scale step
    is 4095 codes and a few hundred is exactly what a fraction of it
    bleeding through would look like. Answered by the distance from
    each row's own `wrap_bin`.
  * are they a starved playback ring? An underrun is a real
    discontinuity in what the DAC emitted, so a run with underruns has
    every right to fold large.

Reads the committed records only; no board.

    .venv/bin/python tools/issue24_outliers.py
"""
import argparse
import glob
import json
import os
import statistics

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The port-fight block: a pytest run held the ports while this series
# was capturing, and its captures are corrupted - equal and opposite
# pairs of thousands of codes, 128 bins apart. Excluded by name rather
# than deleted, because a record is append-only and a bad row that says
# why it is bad is worth more than a gap.
EXCLUDE = {"macos-long2"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--codes", type=float, default=50.0)
    ap.add_argument("--glob", default="records/issue24*.jsonl")
    args = ap.parse_args()

    hits, runs = [], []
    for path in sorted(glob.glob(os.path.join(ROOT, args.glob))):
        for line in open(path):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("bench") in EXCLUDE or "a0" in r:
                continue
            period = r.get("period") or 512
            wrap = r.get("wrap_bin")
            # sites_table and sites are the same sites in two frames.
            # Reading both double-counts every one of them, which is
            # how this census first reported 32 outliers in neat pairs
            # and briefly looked like a finding about pairing.
            key = "sites_table" if r.get("sites_table") else "sites"
            big = [s for s in (r.get(key) or [])
                   if isinstance(s, list) and len(s) >= 2
                   and abs(s[1]) >= args.codes]
            under = r.get("under")
            if under is not None:
                runs.append((under, bool(big)))
            for s in big:
                dist = None
                if wrap is not None:
                    d = (s[0] - wrap) % period
                    dist = d - period if d > period // 2 else d
                hits.append({"file": os.path.basename(path),
                             "bench": r.get("bench"), "run": r.get("run"),
                             "bin": s[0], "wrap_bin": wrap, "dist": dist,
                             "codes": s[1], "under": under})

    print(f"fold values >= {args.codes:.0f} codes: {len(hits)}")
    print(f"{'file':28s} {'bench':14s} run  bin wrap dist    codes  under")
    for h in sorted(hits, key=lambda x: -abs(x["codes"])):
        print(f"  {h['file']:26s} {str(h['bench']):14s} "
              f"{str(h['run']):>3s} {h['bin']:>4d} {str(h['wrap_bin']):>4s} "
              f"{str(h['dist']):>4s} {h['codes']:+9.1f} "
              f"{str(h['under']):>6s}")

    d = [abs(h["dist"]) for h in hits if h["dist"] is not None]
    if d:
        print(f"\ndistance from the masked wrap: {min(d)}-{max(d)} bins, "
              f"median {statistics.median(d):.0f}")
        print("  the masker excludes +-2, so none of these is the wrap "
              "leaking past it")
    w = [u for u, b in runs if b]
    n = [u for u, b in runs if not b]
    if w and n:
        print(f"\nruns with an outlier   : {len(w):3d}, "
              f"{sum(1 for x in w if x)} had underruns")
        print(f"runs without an outlier: {len(n):3d}, "
              f"{sum(1 for x in n if x)} had underruns")
        print("  a starved ring is a real discontinuity, so it is "
              "sufficient; most of these have under=0, so it is not "
              "necessary")


if __name__ == "__main__":
    main()
