#!/usr/bin/env python3
"""v2 AWG: the reach beyond the guaranteed +-1.5 V, on raw DAC codes (owner intends to drive past it).  Typical, not guaranteed.

    docker/pcb/run.sh python3 -I hardware/afe-proto/v2/sim/awg/reach.py [--work DIR]     writes raw/reach.json, prints the numbers

Compression criterion: the stage output (ngspice, the derived output saturation of 11.5 ohm per rail *(check)*, nominal parts) is followed
down from the window centre along the DAC pin voltage; the last output within 5 mV of the linear map (design.py's closed form, the output
with no saturation) is the bottom of the linear range, and below it the output compresses (it is held back by the weak or nominal rail
and the 11.5 ohm per rail drop).  The same 5 mV is the criterion of run.py's 'saturation does not bind' rows.  Top: the output at the DAC's own
highest code (2.771 V at AREF 3.27 V, scaled with AREF; docs/hardware.md) from the same sweep, and the hard-corner range of the window top end
from design.corner_stats.  Into 50 ohm the BNC voltage is half the stage output.
"""
import json, os, sys, tempfile
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.normpath(os.path.join(HERE, '..', '..', '..')))
import netlist as core
import design
import run
from params import D, RAILS

work = sys.argv[sys.argv.index('--work') + 1] if '--work' in sys.argv else tempfile.mkdtemp()
core.set_workdir(work)
p = dict(Rf=D['Rf'], Rg1=D['Rg1'], Rg2=D['Rg2'], Rvr=D['Rvr'], Rbin=D['Rbin'], Rbpl=D['Rbpl'])
TOL = 5e-3
res = {}
for rails in ('nom', 'weak'):
    for load in ('hiz', 'r50'):
        vds = np.arange(0.50, 2.90 + 1e-9, 0.01)
        vo = []
        for vd in vds:
            r = run.sat_op(dict(rails=rails), load, float(vd))
            vo.append(r[0])
        vo = np.array(vo); lin = np.array([run.analytic_out(p, v, D['vref']) for v in vds])
        dev = np.abs(vo - lin)
        # bottom of the linear range: walk down from the centre (1.6745 V)
        i0 = int(np.argmin(np.abs(vds - 1.6745))); ib = i0
        while ib > 0 and dev[ib - 1] <= TOL: ib -= 1
        it = i0
        while it < len(vds) - 1 and dev[it + 1] <= TOL: it += 1
        k = 0.5 if load == 'r50' else 1.0
        row = dict(bottom_dac=float(vds[ib]), bottom_stage=float(vo[ib]), bottom_bnc=float(vo[ib] * k), top_linear_dac=float(vds[it]), top_linear_stage=float(vo[it]))
        for lab, vd in (('top_code_AREF3.20', 2.771 * 3.20 / 3.27), ('top_code_AREF3.27', 2.771), ('top_code_AREF3.30', 2.771 * 3.30 / 3.27), ('low_code_AREF3.27', 0.578)):
            r = run.sat_op(dict(rails=rails), load, float(vd))
            row[lab + '_stage'] = float(r[0]); row[lab + '_bnc'] = float(r[0] * k); row[lab + '_dac'] = float(vd)
            row[lab + '_dev_mV'] = float((r[0] - run.analytic_out(p, vd, D['vref'])) * 1e3)
        res[f'{rails}|{load}'] = row
e = design.corner_stats(design.VALUES)
res['hard_corners'] = dict(top_dc=e['top'], top_dc_lowest=e['topmin'], top_ac=e['top_ac'], bottom=e['bot'], bottom_highest=e['botmax'])
res['criterion'] = f'output within {TOL*1e3:.0f} mV of the linear map; saturation 11.5 ohm per rail derived *(check)*'
os.makedirs(os.path.join(HERE, 'raw'), exist_ok=True)
json.dump(res, open(os.path.join(HERE, 'raw', 'reach.json'), 'w'), indent=1)
for k, v in res.items():
    print(k, json.dumps(v, default=float) if not isinstance(v, dict) else {a: round(b, 3) for a, b in v.items()})
