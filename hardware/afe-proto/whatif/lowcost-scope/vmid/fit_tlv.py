"""Fit the behavioural op-amp (models-open/mcp6002 subcircuit, reparameterised) to the TI TLV9062 model's loop
impedance for the chosen TLV loop, so the scope netlists can carry a TLV9062 stand-in (the TI model's operating point
does not converge beside the OPA354 model in ngspice 47)."""
import os, sys, itertools, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import vloop as V
def zc(kind, d, tag, **kw):
    f, z = V.loop(kind, d, "z", tag, **kw); return f, np.abs(z)
if __name__ == "__main__":
    out = {}
    for lab, d in (("chosen 0.25R/4.7k/1uF/6x10uF", dict(riso=0.25, rfb=4.7e3, cfb=1e-6, cnode=60e-6, esr=0.005 / 6)),
                   ("stiffened OPA365 loop 0.2R/4.7k/3nF/2x10uF", dict(riso=0.2, rfb=4.7e3, cfb=3e-9, cnode=20e-6, esr=2.5e-3))):
        f, zt = zc("tlv", d, "ft_ref")
        m = (f >= 1) & (f <= 1e6)
        best = None
        for gbw, ro, fp2 in itertools.product((6e6, 8e6, 10e6, 12e6, 15e6), (30, 50, 70, 100, 150, 200), (20e6, 40e6)):
            _, zm = zc("mcp", d, "ft_try", gbw=gbw, ro=ro, fp2=fp2, a0db=120)
            err = float(np.max(np.abs(zm[m] / zt[m] - 1)))
            if best is None or err < best[0]:
                best = (err, gbw, ro, fp2)
        out[lab] = dict(err_max=best[0], gbw=best[1], ro=best[2], fp2=best[3], zmax_ti=float(zt[m].max()))
        print(lab, out[lab], flush=True)
    json.dump(out, open("fit_tlv.json", "w"), indent=1)
