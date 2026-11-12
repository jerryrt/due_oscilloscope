#!/usr/bin/env python3
"""Second search (coordinator's request): AW-7 offset margin >= 5 mV (|out at Vdac 1.67 V| <= 55 mV at every stacked corner), gain margin >= 0.02
(1.12 .. 1.18), AW-1 position-aware <= 92 %, Rf/Rg2 at the 3.3k/5.1k scale (REF load low).  Rbin and Rbpl may be a single Basic 0603 resistor or a
series pair of two (a series pair of 1 % parts stays within 1 %).  With the offset filter fitted (100 ohm in series with Rg2, as the Rvr term).  Prefers values already on version 1's board.   python3 -I search2.py"""
import itertools, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, design

BOARD = {100e3, 330e3, 470e3, 300e3, 75e3, 1e3, 270., 680., 22., 4.7e3, 1.0}      # Basic types on version 1's board (kicad/design.py)
singles = sorted(x for x in design.catalogue() if x >= 1.0)
pool = {}
for x in singles:
    pool[round(x, 1)] = ((x,), )
for a, b in itertools.combinations_with_replacement(singles, 2):
    v = round(a + b, 1)
    if v > 400e3 or v < 2e3: continue
    if v not in pool: pool[v] = ((a, b),)
    else:
        old = pool[v][0]
        if len(old) == 2:           # prefer the pair with more board types
            sc = lambda p: sum(1 for q in p if q in BOARD)
            if sc((a, b)) > sc(old): pool[v] = ((a, b),)
vals = np.array(sorted(pool))
RF = [x for x in singles if 2e3 <= x <= 6.8e3]; RG = [x for x in singles if 3e3 <= x <= 10e3]
RS = 100.0                                    # the fitted offset filter's series resistor adds to Rg2 at DC (Rg2_eff = Rg2 + 100 ohm)
KP = [(rf, rg) for rf in RF for rg in RG if 0.58 <= rf / (rg + RS) <= 0.72]
VB = vals[vals <= 120e3][:, None]; VP = vals[None, :]
SUM = VB + VP; KIN = VP / SUM
ok0 = (SUM >= 28.28e3) & (KIN >= 0.66) & (KIN <= 0.78)
out = []
for rf, rg in KP:
    K = rf / (rg + RS); G = (1 + K) * KIN
    m = ok0 & (G >= 1.14) & (G <= 1.19) & (np.abs(G * 1.67 - K * 3.0) <= 0.045)
    for a, b in zip(*np.nonzero(m)):
        out.append((rf, rg, float(VB[a, 0]), float(VP[0, b])))
print(len(out), 'candidates after the nominal filter', file=sys.stderr)
# fast pre-filter, vectorised: o167 and the gains over the 32 resistor-corner combinations x reference x VOS
A = np.array(out)
rf0, rg0, rbi0, rbp0 = A[:, 0], A[:, 1], A[:, 2], A[:, 3]
o_lo = np.full(len(A), 9.0); o_hi = np.full(len(A), -9.0); g_lo = np.full(len(A), 9.0); g_hi = np.zeros(len(A))
for sg in itertools.product((-1, 1), repeat=5):
    rf = rf0 * (1 + 0.01 * sg[0]); rg = rg0 * (1 + 0.01 * sg[1]); rv = RS * (1 + 0.01 * sg[2]); rbi = rbi0 * (1 + 0.01 * sg[3]); rbp = rbp0 * (1 + 0.01 * sg[4])
    Gs0 = 1 + rf / (rg + rv); kin = rbp / (rbi + rbp); K = rf / (rg + rv)
    g = Gs0 * kin
    for vo in design.VREF3030:
        for vs in (-1, 1):
            o = Gs0 * (kin * 1.67 + vs * 1e-3) - K * vo
            o_lo = np.minimum(o_lo, o); o_hi = np.maximum(o_hi, o)
    g_lo = np.minimum(g_lo, g); g_hi = np.maximum(g_hi, g * (1 + rf / rg) / Gs0)
keep = (o_lo >= -0.0705) & (o_hi <= 0.0705) & (g_lo >= 1.10) & (g_hi <= 1.20)
A = A[keep]
rf0, rg0, rbi0, rbp0 = A[:, 0], A[:, 1], A[:, 2], A[:, 3]
edge = np.zeros(len(A)); botg = np.full(len(A), -9.0); tg = np.full(len(A), 9.0)
for sg in itertools.product((-1, 1), repeat=5):
    rf = rf0 * (1 + 0.01 * sg[0]); rg = rg0 * (1 + 0.01 * sg[1]); rv = RS * (1 + 0.01 * sg[2]); rbi = rbi0 * (1 + 0.01 * sg[3]); rbp = rbp0 * (1 + 0.01 * sg[4])
    Gs0 = 1 + rf / (rg + rv); kin = rbp / (rbi + rbp); K = rf / (rg + rv)
    for scen in 'AB':
        for aref in design.AREF:
            for sh in (-1, 1):
                if scen == 'A': lo, hi = aref / 6 + 0.030 * sh, 5 * aref / 6 + 0.030 * sh
                else: k_ = aref / 3.27; lo, hi = 0.578 * k_ + 0.005 * sh, 2.771 * k_ + 0.005 * sh
                for vo in design.VREF3030:
                    for vs in (-1, 1):
                        vos = vs * 1e-3
                        oh = Gs0 * (kin * hi + vos) - K * vo; ol = Gs0 * (kin * lo + vos) - K * vo
                        sp = oh - ol; c = (oh + ol) / 2
                        edge = np.maximum(edge, np.maximum(np.abs(1.0 - c), np.abs(-1.0 - c)) / (sp / 2))
                        botg = np.maximum(botg, ol + 0.04 * sp); tg = np.minimum(tg, oh - 0.04 * sp)
keep = (edge <= 0.9205) & (botg <= -1.0) & (tg >= 1.0)
out = [tuple(x) for x in A[keep]]
print(len(out), 'candidates after the vectorised AW-1 pre-filter (position-aware <= 92 %)', file=sys.stderr)
print(len(out), 'candidates after the vectorised corner pre-filter (offset +-70.5 mV, gain 1.10..1.20 incl. the shelf)', file=sys.stderr)
res = []
for rf, rg, Rbin, Rbpl in out:
    v = dict(Rf=rf, Rg1=float('inf'), Rg2=rg, Rvr=RS, Rbin=Rbin, Rbpl=Rbpl)
    e = design.corner_stats(v)
    if (e['gmin'] >= 1.10 and e['gmax'] <= 1.20 and e['gacmax'] <= 1.20 and e['edge'] <= 0.92 and e['use'] <= 0.92 and e['botg'] <= design.OUT_LO and e['tg'] >= design.OUT_HI
            and e['o167min'] >= -0.075 and e['o167max'] <= 0.075):
        parts = pool[round(Rbin, 1)][0] + pool[round(Rbpl, 1)][0] + (rf, rg)
        new = sorted({q for q in parts if q not in BOARD})
        res.append((len(new), max(e['o167max'], -e['o167min']), e['edge'], rf, rg, Rbin, Rbpl, e, new, pool[round(Rbin, 1)][0], pool[round(Rbpl, 1)][0]))
import pickle
pickle.dump([(r[3], r[4], r[5], r[6], r[7], r[8], r[9], r[10]) for r in res], open('search2.pkl', 'wb'))
def fmt(r):
    e = r[7]
    return (f'Rf {r[3]:g} Rg2 {r[4]:g} Rbin {r[5]:g}{r[9]} Rbpl {r[6]:g}{r[10]}  gain {e["gmin"]:.3f}..{e["gmax"]:.3f} (AC {e["gacmax"]:.3f})  edge {e["edge"]*100:.2f}%  o167 {e["o167min"]*1e3:+.1f}..{e["o167max"]*1e3:+.1f}  AC top {e["actop"]:.3f}  new {sorted(set(float(q) for q in r[8]))}')
strict = [r for r in res if r[7]['gmin'] >= 1.12 and r[7]['gacmax'] <= 1.18 and r[1] <= 0.055]
print(len(strict), 'sets meet the strict asks: gain 1.12..1.18 (DC and AC), offset +-55 mV, AW-1 position-aware <= 92 %')
for r in sorted(strict, key=lambda r: (r[0], r[2]))[:12]: print('strict, fewest new types:', fmt(r))
for r in sorted(strict, key=lambda r: r[2])[:12]: print('strict, lowest edge:', fmt(r))
print('--- gain margin 0.02 only, best offset')
g2 = [r for r in res if r[7]['gmin'] >= 1.12 and r[7]['gacmax'] <= 1.18]
for r in sorted(g2, key=lambda r: r[1])[:5]: print(fmt(r))
print('by edge margin')
