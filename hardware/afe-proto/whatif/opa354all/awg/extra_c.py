#!/usr/bin/env python3
"""What-if opa354all (C): why the OPA354 DAC0 follower reads low, and the +IN capacitor option (12 pF, an existing type)."""
import os, sys, json
ARGS = sys.argv[1:]
sys.argv = ['run.py', '--variant=buf']
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import run as R
_T = '_'.join(ARGS) or 'base'
R.NETDIR = os.path.join(HERE, 'netlists_extra_c', _T); R.RAWDIR = os.path.join(HERE, 'raw_extra_c', _T)
OP = os.environ.get('WI_OP', 'OPA354')
res = {}
base = dict(inj=None, Rsh=0.0, Rinj=0.0, bufop=OP, opamp=OP)
for lab, ex in (('Rbin 680 (design), bare, 1 pF', dict(Rbin=680.0)), ('Rbin 1 ohm, bare, 1 pF', dict(Rbin=1.0)),
                ('Rbin 680 + 12 pF at +IN, bare, 1 pF', dict(Rbin=680.0, Cbin=12e-12))):
    w = R.buf_pm_worst(1e-12, extra=dict(base, **ex), tag='pmc'); res[lab] = dict(pm=w['pm'], grid=w['grid']); print(lab, w['pm'], w['grid'], flush=True)
# the design's loads with 12 pF at +IN (Rinj 249 branch, pin 5-10 pF, switches off / on; 15 pF)
d = dict(Rsh=0.0, Rinj=249.0, bufop=OP, opamp=OP)
for cb in ([12e-12, 24e-12] if 'cb' in ARGS else []):
    g = {}
    for cp in (5e-12, 10e-12, 15e-12):
        for n in (0, 1, 2):
            g[f'{cp*1e12:g}/{n}'] = R.buf_pm_worst(cp, extra=dict(d, inj=n, Cbin=cb), tag='pmc')['pm']
    f_, h = R.ac_resp(R.P(**dict(d, Cbin=cb, Cbo=10e-12, load='r50')), tag='bwc'); bw50 = R.bw_stats(f_, h)['f3db']
    f_, h = R.ac_resp(R.P(**dict(d, Cbin=cb, Cbo=10e-12, load='hiz')), tag='bwc'); bwh = R.bw_stats(f_, h)['f3db']
    nz = R.aw6_total(R.P(**dict(d, Cbin=cb)), tag='nzc')['total_uV']
    res[f'design + {cb*1e12:g} pF at +IN'] = dict(grid=g, normal=min(g[f'{c}/0'] for c in (5, 10)), cal=min(g[f'{c}/{n}'] for c in (5, 10) for n in (1, 2)),
                                               pin15=min(g[f'15/{n}'] for n in (0, 1, 2)), bw_r50_MHz=bw50 / 1e6, bw_hiz_MHz=bwh / 1e6, aw6_uV=nz)
    print(cb, res[f'design + {cb*1e12:g} pF at +IN'], flush=True)
json.dump(res, open(os.path.join(HERE, f'extra_c_{OP}_{"_".join(ARGS) or "base"}.json'), 'w'), indent=1, default=float)
