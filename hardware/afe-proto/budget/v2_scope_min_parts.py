#!/usr/bin/env python3
"""How few parts can the v2 scope network use (D27: one part per value is preferred)?

Enumerates every network built from the Basic 0603 values in ../v2/jlc-basic.csv with one part or two in series per
resistor, keeps those with fewer than six parts and screens them with v2_scope's own checks (5 V span 70 to 75 % of
full scale, nominal R_in within 1 % of 1 Mohm, the low and high pin margins at 1 % parts, mV per code).  Result on
2026-11-12: every single-part triple fails the span and R_in screen; 4 parts: 11 screened, 0 pass; 5 parts: 130
screened, 0 pass.  The six-part set of v2_scope.py is the smallest that meets every check.  Parallel pairs are not
enumerated.    python3 -I v2_scope_min_parts.py
"""
import itertools, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v2_scope as S

v, basic = S.values()
a0, voff0, r1, r2, r3 = S.ideal()
B = [S.builds(v, x, 400) for x in (r1, r2, r3)]
found = {}
for c in itertools.product(*B):
    n = sum(len(x[1]) for x in c)
    if n >= 6:
        continue
    a, voff, rin = S.net(*(x[0] for x in c))
    span = 5 * a / S.AREF_NOM
    if not (S.SPAN_FS[0] <= span <= S.SPAN_FS[1]) or abs(rin / S.RIN - 1) > S.RIN_TOL:
        continue
    am, vm, rinm, lo, hi = S.worst(*(x[0] for x in c), n=4000)
    sp = 5 * am / S.AREF_NOM
    mvc = S.AREF_HI / 4096 / am.min() * 1e3
    ok = (sp.min() >= S.SPAN_FS[0] and sp.max() <= S.SPAN_FS[1] and lo.min() >= S.MARGIN
          and hi.max() <= S.AREF_LO - S.MARGIN and mvc <= 1.8)
    found.setdefault(n, []).append(ok)
for n in sorted(found):
    print(f'{n} parts: {len(found[n])} screened, {sum(found[n])} pass every check')
print('single-part triples: none reach the span and R_in screen' if 1 not in found and 3 not in found else '')
