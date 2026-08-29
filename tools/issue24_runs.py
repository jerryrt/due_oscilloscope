#!/usr/bin/env python3
"""Is the comb's gate drawn per stream, or does it drift on a slower clock?

Both put on and off captures in one session; they differ in ORDER. A
per-stream draw is independent, so on/off alternates about as often as
coin flips. Drift is autocorrelated, so the sequence clusters into long
blocks and the number of runs falls below chance.

Wald-Wolfowitz, exact expectation, normal approximation for the tail -
n is small so the z is quoted with that said rather than dressed up.
"""
import json, math, sys, collections

rows = [json.loads(l) for l in open(sys.argv[1]) if '"macos-seq"' in l]
rows.sort(key=lambda r: r["run"])

seq = []
for r in rows:
    sites = r.get("sites") or []
    bins = sorted(s[0] for s in sites)
    gaps = collections.Counter(bins[i+1]-bins[i] for i in range(len(bins)-1))
    # "The comb is on" = a lattice, not a count. Three or more gaps of
    # exactly 21 is the structure; a big single site is not.
    on = gaps.get(21, 0) >= 3
    seq.append(1 if on else 0)
    print(f"run {r['run']:2d}  sites {len(bins):3d}  gaps21 {gaps.get(21,0):3d}  "
          f"{'ON ' if on else 'off'}")

n = len(seq)
n1, n0 = sum(seq), n - sum(seq)
runs = 1 + sum(1 for i in range(n-1) if seq[i] != seq[i+1])
print("\nsequence:", "".join("X" if s else "." for s in seq))
print(f"n={n}  on={n1}  off={n0}  runs={runs}")
if n1 and n0:
    mu = 2*n1*n0/n + 1
    var = (2*n1*n0*(2*n1*n0 - n)) / (n*n*(n-1))
    sd = math.sqrt(var) if var > 0 else 0.0
    z = (runs - mu)/sd if sd else 0.0
    print(f"expected runs if independent: {mu:.2f} (sd {sd:.2f})")
    print(f"observed {runs}  ->  z = {z:+.2f}")
    print("  z well below 0 = clustered = drift")
    print("  z near 0        = independent = drawn per stream")
else:
    print("one arm empty - the gate did not change state; no test possible")


# Read the result with its power in hand. With n=20 and only 4 captures
# on, the expected-runs sd is 1.35, so this test detects heavy
# clustering and little else. A z near zero is a FAILURE TO DETECT
# clustering, not a demonstration of independence, and the difference
# matters here because a null result is exactly what three earlier
# draw-event candidates returned.
