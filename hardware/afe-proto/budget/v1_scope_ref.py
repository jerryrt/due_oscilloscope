#!/usr/bin/env python3
"""AFE version 1 after D18, Step 1: the scope channel's one range (+-5 V, usable +-6 V) centred from the REF3030E, by
arithmetic.  Copied from v2_scope.py (the v2 range, -1.5..+3.5 V); only the range parameters differ.

Topology studied (a proposal, not settled): no per-channel buffered Vmid.  The input reaches a follower's + input
through a three-resistor network,

    IN --R1--+-- N --> follower (one half of a dual; V2-2)
             |
            R2 to GND,  R3 to VR (the REF3030E, 3.0 V)

so  a = Rp/R1,  Voff = VR*Rp/R3,  Rp = R1||R2||R3,  R_in = R1 + R2||R3 = R1/(1 - a)  (VR an AC ground).

The REF3030E only ever *sources* into R3 while N stays below VR; above it (an input past about +4 V with the clamp
holding N near the +3.3 V rail) it sinks (N - VR)/R3, which is a few microamps: whether the REF3030E may sink that is
a (check) for the datasheet.

Limits quoted from docs/afe-v2.md 3.1 (most of them *derived* there):
  span     a 5 V span occupies 70..75 % of full scale at nominal AREF
  margin   usable -2.0..+4.0 V keeps the pin in [0 + 80 mV, AREF - 80 mV] at AREF 3.20, with 1 % parts and a +-30 mV
           centring error
  SC-3     R_in 1 Mohm within 1 %
  PR-1     +-12 V: the clamp current through R1 is printed for the protection design
Resistors: 1 % (V2-3); value set E96 until hardware/afe-proto/v2/jlc-basic.csv lists the Basic values, then that file.

Run: python3 -I hardware/afe-proto/budget/v2_scope.py      (numpy; exit 0 if every check passes)
"""
import csv
import itertools
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
BASIC = os.path.join(HERE, '..', 'v2', 'jlc-basic.csv')

AREF_LO, AREF_HI, AREF_NOM = 3.20, 3.30, 3.25     # afe.md SC-2 / AW-1; nominal taken as the window's middle (check)
MARGIN, CENTRE_ERR = 0.080, 0.030
SPAN_FS = (0.70, 0.75)                             # SC-4: the +-5 V span (10 V) occupies 70..75 % of full scale
USABLE = (-6.0, 6.0)                                # SC-2: usable +-6 V
CENTRE_IN = 0.0                                    # the input's centre is 0 V
VR, VR_TOL = 3.0, 0.002                            # REF3030E initial accuracy 0.2 % (check against the datasheet)
TOL = 0.01                                         # V2-3: Basic 1 %
RIN, RIN_TOL = 1e6, 0.01                           # SC-3
TC = 100e-6                                        # expected thick-film tempco, per K (afe-v2 V2-3, check per part)

E96 = [100, 102, 105, 107, 110, 113, 115, 118, 121, 124, 127, 130, 133, 137, 140, 143, 147, 150, 154, 158, 162, 165,
       169, 174, 178, 182, 187, 191, 196, 200, 205, 210, 215, 221, 226, 232, 237, 243, 249, 255, 261, 267, 274, 280,
       287, 294, 301, 309, 316, 324, 332, 340, 348, 357, 365, 374, 383, 392, 402, 412, 422, 432, 442, 453, 464, 475,
       487, 499, 511, 523, 536, 549, 562, 576, 590, 604, 619, 634, 649, 665, 681, 698, 715, 732, 750, 768, 787, 806,
       825, 845, 866, 887, 909, 931, 953, 976]


def parse(s):
    s = s.strip()
    for u, m in (('R', 1), ('k', 1e3), ('K', 1e3), ('M', 1e6)):
        if u in s:
            a, b = s.split(u)
            return (float(a or '0') if '.' in a else float((a or '0') + '.' + (b or '0'))) * m
    return float(s)


def values():
    """Resistor values available, ohms: the Basic 0603 parts of the catalogue when it exists, E96 otherwise."""
    if os.path.exists(BASIC):
        with open(BASIC) as f:
            v = sorted({parse(r['value']) for r in csv.DictReader(f)
                        if r['kind'] == 'resistor' and r['basic'].strip().lower() == 'yes' and r['package'] == '0603'})
        v = [x for x in v if x > 0]
        if v:
            print(f'value set: {len(v)} Basic 0603 resistor values from {os.path.relpath(BASIC)}')
            return np.array(v), True
    print('value set: E96 1 % (the Basic catalogue is not written yet: every choice below is provisional)')
    return np.array([m * 10 ** d for d in range(3, 7) for m in E96], dtype=float), False


def builds(v, x, k=8):
    """Ways to make about x: one part, or two in series (V2-3 / MC-12: one value first, then combinations).
    Returns [(ohms, (parts...))], nearest first, a second part costing a little."""
    out = [(y, (y,)) for y in v]
    vv = v[(v >= x * 0.05) & (v <= x * 1.05)]
    for i, a in enumerate(vv):
        for b in vv[i:]:
            out.append((a + b, (max(a, b), min(a, b))))
    out.sort(key=lambda c: abs(c[0] - x) / x + 0.002 * (len(c[1]) - 1))
    return out[:k]


def fmt(parts):
    return ' + '.join(f'{p/1e6:g}M' if p >= 1e6 else f'{p/1e3:g}k' for p in parts)


def net(r1, r2, r3, vr=VR):
    rp = 1 / (1 / r1 + 1 / r2 + 1 / r3)
    return rp / r1, vr * rp / r3, r1 + 1 / (1 / r2 + 1 / r3)


def ideal():
    a = (SPAN_FS[0] + SPAN_FS[1]) / 2 * AREF_NOM / 10.0
    voff = AREF_NOM / 2 - a * CENTRE_IN
    r1 = RIN * (1 - a)
    rp = a * r1
    r3 = VR * rp / voff
    r2 = 1 / (1 / (r1 * a / (1 - a)) - 1 / r3)
    return a, voff, r1, r2, r3


def nearest(v, x, k=3):
    i = np.searchsorted(v, x)
    return sorted(set(v[max(0, i - k):i + k]), key=lambda y: abs(y - x))[:k]


def worst(r1, r2, r3, n=200_000, seed=20261112):
    """Monte Carlo, uniform +-1 % (bounded, so stricter than gaussian) and VR +-0.2 %, plus the +-30 mV centring term."""
    rng = np.random.default_rng(seed)
    f = 1 + rng.uniform(-TOL, TOL, (3, n))
    vr = VR * (1 + rng.uniform(-VR_TOL, VR_TOL, n))
    a, voff, rin = net(r1 * f[0], r2 * f[1], r3 * f[2], vr)
    lo = voff + a * USABLE[0] - CENTRE_ERR
    hi = voff + a * USABLE[1] + CENTRE_ERR
    return a, voff, rin, lo, hi


def main():
    v, basic = values()
    a0, voff0, r1, r2, r3 = ideal()
    print(f'ideal: a {a0:.4f}, offset {voff0:.4f} V, R1 {r1/1e3:.1f}k R2 {r2/1e3:.1f}k R3 {r3/1e3:.1f}k')
    best = None
    for c in itertools.product(builds(v, r1), builds(v, r2), builds(v, r3)):
        a, voff, rin = net(*(x[0] for x in c))
        span = 10 * a / AREF_NOM
        if not (SPAN_FS[0] + 0.01 <= span <= SPAN_FS[1] - 0.01) or abs(rin / RIN - 1) > RIN_TOL:
            continue
        am_, _, _, lo, hi = worst(*(x[0] for x in c), n=4000)
        sp_ = 10 * am_ / AREF_NOM
        if sp_.min() < SPAN_FS[0] + 0.004 or sp_.max() > SPAN_FS[1] - 0.004:      # a margin: 4000 draws miss the extremes
            continue
        slack = min(lo.min() - MARGIN, AREF_LO - MARGIN - hi.max())       # the worse of the two margins, V
        nparts = sum(len(x[1]) for x in c)
        cost = -slack / 0.010 + 0.5 * nparts                               # 10 mV of margin is worth two parts
        if best is None or cost < best[0]:
            best = (cost, c)
    cc = best[1]
    c = tuple(x[0] for x in cc)
    a, voff, rin = net(*c)
    print(f'chosen ({"Basic" if basic else "E96, provisional"}): R1 {fmt(cc[0][1])}, R2 {fmt(cc[1][1])}, '
          f'R3 {fmt(cc[2][1])}  ({sum(len(x[1]) for x in cc)} parts per channel)')
    print(f'  nominal: a {a:.4f}, offset {voff:.4f} V, R_in {rin/1e3:.1f}k, 10 V span = {10*a/AREF_NOM*100:.1f} % FS '
          f'at {AREF_NOM} V, input +1.0 V -> pin {voff + a:.3f} V (mid {AREF_NOM/2:.3f})')
    am, vm, rinm, lo, hi = worst(*c)
    fails = []

    def check(name, ok, detail):
        print(f'  [{"PASS" if ok else "FAIL"}] {name}: {detail}')
        if not ok:
            fails.append(name)

    sp = 10 * am / AREF_NOM
    check('span 70..75 % FS (10 V, nominal AREF, 1 % parts)', sp.min() >= SPAN_FS[0] and sp.max() <= SPAN_FS[1],
          f'{sp.min()*100:.2f} .. {sp.max()*100:.2f} %')
    # afe-v2 3.1 says SC-3 is "rebuilt from Basic values within 1 %".  Read here as the *nominal* within 1 %: with 1 %
    # parts the worst-case spread is itself about +-1 %, so a worst-case reading fails any nominal but exactly 1 Mohm.
    # The reading is a question for the owner (v2/notes.md); the spread is printed so it can be decided on numbers.
    check('SC-3 R_in nominal 1 Mohm +-1 %', abs(rin / RIN - 1) <= RIN_TOL, f'{rin/1e3:.1f} k nominal')
    print(f'  (info) R_in over 1 % parts: {rinm.min()/1e3:.1f} .. {rinm.max()/1e3:.1f} k')
    check(f'low margin: {USABLE[0]} V in, pin >= {MARGIN*1e3:.0f} mV', lo.min() >= MARGIN,
          f'worst {lo.min()*1e3:.0f} mV (slack {(lo.min()-MARGIN)*1e3:.0f} mV)')
    check(f'high margin: +{USABLE[1]} V in, pin <= AREF {AREF_LO} - {MARGIN*1e3:.0f} mV', hi.max() <= AREF_LO - MARGIN,
          f'worst {hi.max():.3f} V (slack {(AREF_LO - MARGIN - hi.max())*1e3:.0f} mV)')
    # mV per code at the input: AREF / 4096 / a  (afe-v2 3.1: at most 1.8 mV)
    mvc = AREF_HI / 4096 / am.min() * 1e3
    check('mV per code at the input <= 4 (SC-4, worst: AREF 3.30, smallest a)', mvc <= 4.0, f'{mvc:.3f} mV')
    # drift: R1 against R2||R3 in opposite directions at 100 ppm/K over EN-1's 20 K (the uncalibrated worst case)
    d = TC * 20
    a_hi, _, _ = net(c[0] * (1 - d), c[1] * (1 + d), c[2] * (1 + d))
    print(f'  gain drift, 1 % thick film at +-{TC*1e6:.0f} ppm/K opposed, 20 K: {(a_hi/a - 1)*100:.3f} % '
          f'(EN-1 asked 0.2 %; afe-v2 D-V2-3 relaxes it to this)')
    for vin in (12.0, -12.0):
        vn_open = voff + a * vin
        print(f'  PR-1 {vin:+.0f} V: unclamped node {vn_open:+.2f} V; current through R1 with N held at '
              f'{3.6 if vin > 0 else -0.3:+.1f} V: {(vin - (3.6 if vin > 0 else -0.3)) / c[0] * 1e6:+.1f} uA')
    print(f'  REF3030E load: {VR / c[2] * 1e6:.2f} uA per channel at N = 0 (sources); sinks {(3.6 - VR) / c[2] * 1e6:.2f} uA '
          f'with N clamped at 3.6 V (check its sink rating)')
    print('ALL PASS' if not fails else f'FAIL: {", ".join(fails)}')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
