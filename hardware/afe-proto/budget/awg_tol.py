#!/usr/bin/env python3
"""AW-7 'as built' (gain 1.10-1.20, offset within +-60 mV) against the AWG
network's resistor tolerance.  Pure arithmetic (stage equations of
docs/architecture.md); op-amp offset ignored here (OPA365 0.2 mV, check).
The offset budget is the whole +-60 mV, of which the DAC window's centre
error also takes a share (not modelled; sim/awg/run.py's dc_mc carries it),
so this is a necessary test only.
Values are those of sim/awg/run.py (Rf = 249 + 49.9 in series, Rx 330k);
pass others as Ra=.. Rb=.. Rx=.. Rf=.. Rg=.. on the command line.
Run: python3 -I budget/awg_tol.py   (exit 0)"""
import itertools, sys
import numpy as np
rng = np.random.default_rng(1)
VALUES = dict(Ra=13.7e3, Rb=15.8e3, Rx=330e3, Rf=249. + 49.9, Rg=249.)
NAMES = ('Ra', 'Rb', 'Rx', 'Rf', 'Rg')
VMID = 1.65


def stage(tol, v=None, n=200000, vmid_err=0.0, corner=False):
    """tol: one fraction for all five, or a dict per name."""
    v = dict(VALUES, **(v or {}))
    t = np.array([tol.get(k, 0.0) if isinstance(tol, dict) else tol for k in NAMES])
    if corner:   # all +-tol corners, 2^5
        f = np.array(list(itertools.product((-1, 1), repeat=5))) * t
    else:
        f = rng.uniform(-1, 1, (n, 5)) * t
    a, b, x, ff, g = (v[k] * (1 + f[:, i]) for i, k in enumerate(NAMES))
    S = 1/a + 1/b + 1/x
    G = 1 + ff/g
    gain = G / (a * S)
    vm = VMID + vmid_err
    # offset: output with the DAC at its centre value 1.65 V (nominal Vmid)
    vplus = (VMID/a + vm/x)/S
    out0 = vplus*G - (ff/g)*vm
    return gain, out0


def ok(g, o):
    return (g.min() >= 1.10) and (g.max() <= 1.20) and (np.abs(o).max() <= 0.060)


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        k, val = arg.split('='); VALUES[k] = float(val)
    print('values:', ', '.join(f'{k} {VALUES[k]:g}' for k in NAMES))
    g, o = stage(0.0, corner=True)
    print(f"nominal: gain {g[0]:.4f}, offset {o[0]*1e3:+.2f} mV")
    for tol in (0.001, 0.002, 0.005, 0.01, 0.02):
        g, o = stage(tol, corner=True)
        print(f"tol {tol*100:4.1f} %: corner gain {g.min():.4f}-{g.max():.4f}  offset {o.min()*1e3:+6.1f}..{o.max()*1e3:+6.1f} mV  {'within' if ok(g, o) else 'OUTSIDE'} AW-7")
    # 0.2 % = 0.1 % parts plus 25 ppm/K over an assumed +-40 K (check: the temperature range is not stated in AW-7)
    g, o = stage(0.002, corner=True)
    print(f"0.1 % + 25 ppm/K x 40 K (assumed, check) as 0.2 % corners: gain {g.min():.4f}-{g.max():.4f}, offset {np.abs(o).max()*1e3:.1f} mV")
    # Rx alone at 1 %, the rest 0.1 %: Rx only sets the small Rb/Rx term
    g, o = stage(dict(Ra=0.001, Rb=0.001, Rx=0.01, Rf=0.001, Rg=0.001), corner=True)
    print(f"Rx 1 %, others 0.1 %: gain {g.min():.4f}-{g.max():.4f}, offset {np.abs(o).max()*1e3:.1f} mV")
    g, o = stage(0.01, corner=True)
    ok1 = ok(g, o)
    g, o = stage(0.05, corner=True)   # guard: 5 % parts must break the check
    ok5 = ok(g, o)
    assert not ok5, "guard: 5 % parts must fail AW-7 as-built"
    print("guard ok: 5 % parts fail; 1 % corners within AW-7 as-built (before DAC centre error):", ok1)
