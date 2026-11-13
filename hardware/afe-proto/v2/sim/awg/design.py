#!/usr/bin/env python3
"""v2 AWG, DC design: the resistor choice and the Monte Carlo and hard corners of the DC map (AW-1, AW-2, AW-7, PW-3 top end).

    python3 -I design.py            # prints the search result for the chosen topology and the numbers for VALUES
    from design import dc_mc, corner_stats, VALUES

The stage (section 'The circuit' of design.md): both halves of the TPH2502 are paralleled as one non-inverting stage.  The
DAC0 pin reaches the + inputs through Rbin into Rbpl to ground (a divider, kin = Rbpl/(Rbin+Rbpl) of about 0.95), and the
inverting node has Rf to the output and Rg2 to the AWG's own offset source Vo (the +3.3 V rail through 2.2 ohm + 20 uF); there
is no Rg1 to ground:

    Vout = Gs0 * kin * Vdac - K * Vo,   Gs0 = 1 + Rf/Rg2 (+ Rf/Rg1, omitted),   K = Rf / Rg2.

WHY THE DIVIDER (found in this study, design.md): with no divider K cannot exceed Gs0 - 1, and the output at the DAC window top
is then at least Vo + Gs (Vwin_top - Vo), about 2.3 V at the gain AW-1 needs, above the 2.2275 V the supply-pin rating allows.
The divider lets K exceed Gs - 1 by attenuating the signal before the gain.

Resistors are JLC Basic (../../jlc-basic.csv, 1 %).  numpy only.  Every figure is arithmetic on the equations above;
the transfer is checked against ngspice by run.py.
"""
import csv, itertools, os
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
CSV = os.path.join(HERE, '../../jlc-basic.csv')

# LM27762 datasheet rails at the limits (sim/awg/run.py ds_rails): weak and strong corners
RAIL_P = (3.2205, 3.4172)      # 1 % Basic LM27762 feedback (../powercal/design.md section 1), not version 1's 0.1 % figures
RAIL_N = (-2.0525, -1.9549)
VREF3030 = (3.000 * 0.998, 3.000 * 1.002)       # REF3030E initial accuracy +-0.2 % (datasheet, v2/parts.md) *(drift not added)*
AREF = (3.20, 3.30)
# DAC window: scenario A = theory 1/6..5/6 of AREF with +-30 mV centring uncertainty (sim/awg/run.py dc_mc, kept);
# scenario B = the board as measured, 0.578..2.771 V at AREF 3.27 V (docs/hardware.md), scaled with AREF, +-5 mV residual.
# Section limits: AW-1 <= 92 %, AW-2 <= 1.5 mV per code.
OUT_LO, OUT_HI = -1.6, 1.6        # AW-1 (owner ruling 2026-11-13): +-1.6 V symmetric, guaranteed.  It was -1.5 .. +1.63 V; the +-1.75 V request was refused by this same arithmetic (design.md section 'The +-1.75 V request'); commandable top with 4 % kept free at the hard corners 1.631 V
TOP_END_LIM = (0.060 - 0.015) * 49.5  # PW-3: window top end <= (60 mA supply pin - 15 mA IQ max of the dual) x 49.5 ohm = 2.2275 V
RAIL_REACH_LO = -1.9226                 # ngspice (run.py): where the stage clips into high impedance at the weak negative rail -1.9549 V (the macro stops 32 mV short of it)
USE_LIM, LSB_LIM = 0.92, 1.5e-3
VOS_MAX = 0.5e-3          # TPH2502 VOS max (datasheet p3)

VALUES = dict(Rf=3000.0, Rg1=float('inf'), Rg2=3000.0, Rvr=100.0, Rbin=2700.0, Rbpl=27e3)   # the design (design.md)


def catalogue(kind='resistor'):
    out = {}
    with open(CSV) as f:
        for r in csv.DictReader(f):
            if r['kind'] != kind or r['basic'] != 'yes':
                continue
            v = r['value']
            m = {'R': 1.0, 'k': 1e3, 'M': 1e6}
            if v.endswith('R'): x = float(v[:-1])
            elif v.endswith('k'): x = float(v[:-1]) * 1e3
            elif v.endswith('M'): x = float(v[:-1]) * 1e6
            else: continue
            out.setdefault(x, []).append((r['package'], r['lcsc']))
    return out


def dc_mc(v, scen, aref, n=40000, tol=0.01, src='ref', seed=1, vo_fixed=None):
    """Monte Carlo of the DC map.  Returns arrays gain, off (output at the window centre), use, edge, lsb, plus the
    DAC-pin volts that command OUT_HI / OUT_LO.  src: 'rail' (offset from +3.3 V) or 'ref' (REF3030E)."""
    r = np.random.default_rng(seed)
    t = lambda x, tl=tol: x * (1 + r.uniform(-tl, tl, n))
    Rf, Rg1, Rg2 = t(v['Rf']), t(v['Rg1']), t(v['Rg2']) + t(v.get('Rvr', 0.0))
    Gs0 = 1 + Rf * (1 / Rg1 + 1 / Rg2)
    # the DAC reaches the + input through Rbin into Rbpl to ground
    Rbin, Rbpl = t(v.get('Rbin', 0.0)), t(v.get('Rbpl', 1e12))
    kin = Rbpl / (Rbin + Rbpl)
    Gs = Gs0 * kin
    K = Rf / Rg2
    if vo_fixed is not None:
        Vo = np.full(n, vo_fixed)
    elif src == 'rail':
        Vo = r.uniform(*RAIL_P, n)
    else:
        Vo = r.uniform(*VREF3030, n)
    if scen == 'A':
        lo, hi = aref / 6, 5 * aref / 6
        shift = r.uniform(-0.030, 0.030, n)
    else:
        k = aref / 3.27
        lo, hi = 0.578 * k, 2.771 * k
        shift = r.uniform(-0.005, 0.005, n)
    vos = r.uniform(-1, 1, n) * VOS_MAX * 2           # two op-amp halves, both worst-case in the same direction
    # the DAC's actual window sits shifted by `shift` against its nominal; the output map does not move
    lo, hi = lo + shift, hi + shift
    out = lambda vd: Gs0 * (kin * vd + vos) - K * Vo
    gain = Gs
    c = (lo + hi) / 2
    span = hi - lo
    off0 = out(0.0)
    vd_hi, vd_lo = (OUT_HI - off0) / gain, (OUT_LO - off0) / gain
    use = (vd_hi - vd_lo) / span
    edge = np.maximum(np.abs(vd_hi - c), np.abs(vd_lo - c)) / (span / 2)
    # the window ends of the real DAC; the commanded output at each end
    return dict(gain=gain, off=out(c), use=use, edge=edge, lsb=span / 4096 * gain,
                out_lo=out(lo), out_hi=out(hi), vd_hi=vd_hi, vd_lo=vd_lo)


def corner_stats(v, tol=0.01, th=None, tl=None, arefs=AREF, scens='AB', rails=VREF3030, vos_mv=VOS_MAX * 2):
    """Every tolerance at once.  Rf, Rg2, Rvr, Rbin, Rbpl (and Rg1 if present) each at +-tol, AREF at both ends, both DAC-window
    scenarios with the centring shift at both signs, the offset rail at both limits, the offset voltage of two halves at both
    signs.  Returns the extremes over all corners and the corner (as a dict) that gives the highest window top end.
    th, tl: the commanded ends (default OUT_HI, OUT_LO)."""
    th = OUT_HI if th is None else th; tl = OUT_LO if tl is None else tl
    names = ['Rf', 'Rg2', 'Rvr', 'Rbin', 'Rbpl'] + (['Rg1'] if np.isfinite(v.get('Rg1', np.inf)) else [])
    best = dict(top=-9); bestlo = dict(bot=9)
    ex = dict(top=-9, top_ac=-9, topmin=9, bot=9, botmax=-9, edge=0, use=0, lsb=0, tg=9, wbot=9, botg=-9)
    for sg in itertools.product((-1, 1), repeat=len(names)):
        w = {k: v[k] * (1 + tol * s) for k, s in zip(names, sg)}
        Rg2 = w['Rg2'] + w['Rvr']
        Gs0 = 1 + w['Rf'] * (1 / Rg2 + (1 / w['Rg1'] if 'Rg1' in w else 0.0))
        # above the offset filter's corner its capacitor shorts Rvr: Rg2 alone sets the gain (the shelf), Gac >= Gs0
        Gac = 1 + w['Rf'] * (1 / w['Rg2'] + (1 / w['Rg1'] if 'Rg1' in w else 0.0))
        kin = w['Rbpl'] / (w['Rbin'] + w['Rbpl']); K = w['Rf'] / Rg2
        for scen in scens:
            for aref in arefs:
                for sh in (-1, 1):
                    for vo in rails:
                        for vs in (-1, 1):
                            if scen == 'A': lo, hi = aref / 6 + 0.030 * sh, 5 * aref / 6 + 0.030 * sh
                            else: k_ = aref / 3.27; lo, hi = 0.578 * k_ + 0.005 * sh, 2.771 * k_ + 0.005 * sh
                            vos = vs * vos_mv
                            oh = Gs0 * (kin * hi + vos) - K * vo; ol = Gs0 * (kin * lo + vos) - K * vo
                            sp = oh - ol; c = (oh + ol) / 2
                            oh_ac = ol + (Gac / Gs0) * sp      # a pulse train: DC mean at the window bottom, peaks at the top code, amplified by the AC gain
                            ex['top_ac'] = max(ex['top_ac'], oh_ac)
                            ex['topmin'] = min(ex['topmin'], oh); ex['bot'] = min(ex['bot'], ol); ex['wbot'] = ex['bot']
                            ex['botmax'] = max(ex['botmax'], ol)
                            ex['edge'] = max(ex['edge'], max(abs(th - c), abs(tl - c)) / (sp / 2))
                            ex['use'] = max(ex['use'], (th - tl) / sp); ex['lsb'] = max(ex['lsb'], sp / 4096)
                            ex['botg'] = max(ex['botg'], ol + 0.04 * sp)   # lowest commandable bottom (4 % kept free)
                            ex['tg'] = min(ex['tg'], oh - 0.04 * sp)       # highest commandable top with 4 % of the window kept at each end
                            if ol < bestlo['bot']:
                                bestlo = dict(bot=ol, w=dict(w), scen=scen, aref=aref, sh=sh, vo=vo, vos=vos, lo=lo, hi=hi, oh=oh)
                            if oh > ex['top']: ex['top'] = oh
                            if oh > best['top']:
                                best = dict(top=oh, w=dict(w), scen=scen, aref=aref, sh=sh, vo=vo, vos=vos, lo=lo, hi=hi, ol=ol)
    ex['corner'] = best; ex['corner_lo'] = bestlo
    return ex


def worst(v, n=40000, tol=0.01, src='rail'):
    res = {}
    for scen in 'AB':
        for aref in AREF:
            m = dc_mc(v, scen, aref, n=n, tol=tol, src=src)
            for k_, f in (('use', np.max), ('edge', np.max), ('lsb', np.max), ('gmin', None), ('gmax', None), ('offmin', None), ('offmax', None)):
                pass
            d = res.setdefault(scen, dict(use=0, edge=0, lsb=0, gmin=9, gmax=0, offmin=9, offmax=-9))
            d['use'] = max(d['use'], m['use'].max()); d['edge'] = max(d['edge'], m['edge'].max())
            d['lsb'] = max(d['lsb'], m['lsb'].max())
            d['gmin'] = min(d['gmin'], m['gain'].min()); d['gmax'] = max(d['gmax'], m['gain'].max())
            d['offmin'] = min(d['offmin'], m['off'].min()); d['offmax'] = max(d['offmax'], m['off'].max())
    return res


def search(top=10, tol=0.01, rvr=100.0, rf_rng=(1000, 5100), rg2_rng=(1000, 5100)):
    """Basic 1 % values, the topology of design.md (no Rg1, offset from the REF3030E through Rvr = 100 ohm and the filter capacitor): Rbin 1.8-3.3 kohm,
    Rbpl 22-56 kohm with Rbin + Rbpl >= 28 kohm (AW-5), Rf and Rg2 in the given ranges.  Keeps the sets whose hard-corner AC window top end (a pulse
    train: DC mean at the window bottom, peaks at the top code, amplified by the AC gain 1 + Rf/Rg2 that holds above the filter corner) is <= TOP_END_LIM and
    whose commanded bottom (OUT_LO) sits inside the window with 4 % kept free, sorted by the highest commandable top ('tg') they guarantee.  Returns (rows, kept)."""
    cat = sorted(catalogue()); rows = []
    for Rbin in (1800, 2000, 2200, 2400, 2700, 3000, 3300):
        for Rbpl in [x for x in cat if 22e3 <= x <= 56e3]:
            if Rbin + Rbpl < 28e3: continue
            for Rf in [x for x in cat if rf_rng[0] <= x <= rf_rng[1]]:
                for Rg2 in [x for x in cat if rg2_rng[0] <= x <= rg2_rng[1]]:
                    G = (1 + Rf / (Rg2 + rvr)) * Rbpl / (Rbin + Rbpl)
                    if not 1.6 <= G <= 1.95: continue
                    v = dict(Rf=Rf, Rg1=float('inf'), Rg2=Rg2, Rvr=rvr, Rbin=Rbin, Rbpl=Rbpl)
                    e = corner_stats(v, tol)
                    if e['top_ac'] <= TOP_END_LIM and e['botg'] <= OUT_LO:
                        rows.append((e['tg'], Rf, Rg2, Rbin, Rbpl, G, e))
    rows.sort(key=lambda r: -r[0])
    return rows[:top], len(rows)


if __name__ == '__main__':
    for lab, rr in (('large Rf/Rg2 (1-5.1 kohm)', (1000, 5100)), ('small Rf/Rg2 (0.22-0.68 kohm, the earlier values)', (220, 680))):
        rows, n = search(rf_rng=rr, rg2_rng=(100, 1200) if rr[0] < 1000 else rr)
        print(f'{lab}: {n} Basic sets keep the hard-corner AC window top end <= {TOP_END_LIM:.4f} V with OUT_LO inside the window; best by guaranteed top:')
        for tg, Rf, Rg2, Rbin, Rbpl, G, e in rows[:6]:
            print(f'  Rf {Rf:g} Rg2 {Rg2:g} Rbin {Rbin:g} Rbpl {Rbpl:g}  G {G:.3f}  DC top {e["top"]:.3f}  AC top {e["top_ac"]:.3f}  lowest top {e["topmin"]:.3f}  guaranteed top {tg:.3f}')
    e = corner_stats(VALUES)
    print('chosen:', {k: (round(float(x), 4) if not isinstance(x, dict) else '...') for k, x in e.items()})
