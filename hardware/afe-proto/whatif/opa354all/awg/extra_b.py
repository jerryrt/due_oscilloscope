#!/usr/bin/env python3
"""What-if opa354all, AWG extras (B): AN-1 of an OPA354 DAC0 follower, isolation from existing types with the series
resistor AT the pin (datasheet Sec 7.3.7 / Fig 7-6, SBOS233H p19), the trace on the far side of it.

Loads as run.py's case_buf (assumptions *(check)*): pin pad + package Cpin at the op-amp pin; the trace (5 / 10 / 15 pF)
beyond the resistor; the PA-3 branch (Rinj 249, 10 pF trace + 2 x 10 pF switch source sides, switch on: Ron 3.7, 10 pF,
node N 4.5 k to Vmid + 2 pF).  Rg grows by the series resistor so the output zero stays at Vmid (Rsh is in the slope).
Each candidate also reports AW-3 bandwidth (hi-Z, 50 ohm), AW-6 and the DC gain.
"""
import os, sys, json
ARGS = sys.argv[1:]
sys.argv = ['run.py', '--variant=buf']
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import numpy as np
import run as R

_T = '_'.join(ARGS) or 'all'
R.NETDIR = os.path.join(HERE, 'netlists_extra_b', _T); R.RAWDIR = os.path.join(HERE, 'raw_extra_b', _T)
OUT = {}
OP = os.environ.get('WI_OP', 'OPA354')


def worst(extra, cpin, traces=(5e-12, 10e-12), ns=(0,)):
    w = None
    for tr in traces:
        for n in ns:
            x = R.buf_pm_worst(cpin, extra=dict(dict(Cbs=tr, inj=n), **extra), tag='pmb')
            if w is None or x['pm'] < w['pm']: w = dict(x, trace=tr, n=n)
    return w


def cand(rsh, rinj=249.0, cpin=1e-12):
    ex = dict(Rsh=rsh, Rg=953.0 + rsh, Rinj=rinj, bufop=OP, opamp=OP)
    if rsh == 0:     # no resistor at the pin: the trace is at the pin itself, as run.py's case_buf
        ex = dict(Rsh=0.0, Rinj=rinj, bufop=OP, opamp=OP)
        f = lambda trs, ns: min((R.buf_pm_worst(tr + cpin, extra=dict(ex, inj=n), tag='pmb')['pm'] for tr in trs for n in ns))
        normal, cal, m15 = f((5e-12, 10e-12), (0,)), f((5e-12, 10e-12), (1, 2)), f((15e-12,), (0, 1, 2))
    else:
        normal = worst(ex, cpin)['pm']; cal = worst(ex, cpin, ns=(1, 2))['pm']; m15 = worst(ex, cpin, traces=(15e-12,), ns=(0, 1, 2))['pm']
    q = R.P(**dict(ex, Cbs=10e-12 if rsh else 0.0, Cbo=cpin if rsh else 10e-12 + cpin))
    bw = {}
    for ld in ('hiz', 'r50'):
        f_, h = R.ac_resp(dict(q, load=ld), tag='bwb'); bw[ld] = R.bw_stats(f_, h)
    nz = R.aw6_total(q, tag='nzv')
    return dict(normal=normal, cal=cal, pin15=m15, bw_hiz_MHz=bw['hiz']['f3db'] / 1e6, bw_r50_MHz=bw['r50']['f3db'] / 1e6,
                peak_db=max(bw['hiz']['peak_db'], bw['r50']['peak_db']), gain=bw['hiz']['dc'], aw6_uV=nz['total_uV'])


if __name__ == '__main__':
    res = {}
    grid = [(0.0, 249.0, 1e-12), (22.0, 249.0, 1e-12), (49.9, 249.0, 1e-12), (99.8, 249.0, 1e-12), (49.9, 249.0, 3e-12), (99.8, 249.0, 3e-12),
            (249.0, 0.0, 1e-12)]
    if ARGS: grid = [g for g in grid if f'{g[0]:g}' in ARGS]
    if 'bare' in ARGS:
        for cp in (1e-12, 5e-12, 10e-12):
            b = R.buf_pm_worst(cp, extra=dict(inj=None, Rsh=0.0, Rinj=0.0, bufop=OP, opamp=OP), tag='pmb')
            res[f'bare follower, attenuator only, {cp*1e12:g} pF at the pin'] = dict(pm=b['pm'], fc=b['fc'])
            print(cp, b['pm'], flush=True)
    for rsh, rinj, cpin in grid:
        k = f'Rsh {rsh:g} at the pin, Rinj {rinj:g}, Cpin {cpin*1e12:g} pF'
        res[k] = cand(rsh, rinj, cpin); print(k, res[k], flush=True)
    OUT['iso'] = res
    os.makedirs(R.RAWDIR, exist_ok=True)
    json.dump(OUT, open(os.path.join(HERE, f'extra_b_{OP}_{_T}.json'), 'w'), indent=1, default=float)
