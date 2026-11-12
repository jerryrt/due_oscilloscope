import os, sys, json
sys.argv = ['run.py', '--variant=buf']
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import numpy as np
import run as R
R.NETDIR = os.path.join(HERE, 'netlists_extra_d'); R.RAWDIR = os.path.join(HERE, 'raw_extra_d')
out = {k: R.vmid_buffer_pm(v[0])['pm'] for k, v in R.VMID_OUTPUTS.items()}
# with 5 / 10 pF of trace at the bare output (the AWG Vmid follower drives Rg 953 through a trace)
for c in (5e-12, 10e-12, 1e-9):
    out[f'bare + {c*1e12:g} pF'] = R.vmid_buffer_pm(f'Ct out 0 {c}')['pm']
# linearity-detector guard: a straight line reads 0, a 2.0 mV step reads about half of it after the fit
x = np.linspace(0.578, 2.771, 1000); y = 0.999 * x + 0.003
for lab, yy in (('straight', y), ('2 mV step at 2.0 V', y + 2e-3 * (x > 2.0))):
    c = np.polyfit(x, yy, 1); out['inl guard ' + lab + ' (mV)'] = float(np.abs(yy - np.polyval(c, x)).max() * 1e3)
print(json.dumps(out, indent=1)); json.dump(out, open(os.path.join(HERE, f"extra_d_{os.environ.get('WI_OP','OPA354')}.json"), 'w'), indent=1)
