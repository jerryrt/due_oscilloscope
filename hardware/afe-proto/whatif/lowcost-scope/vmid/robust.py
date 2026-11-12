"""Robustness of the candidate per-channel Vmid loops: impedance peak (1 Hz-10 MHz, and 1 kHz-1 MHz for P8-i's
window) and loop phase margin over the buffer's unknowns and the passives' tolerances.  Writes robust.json."""
import os, sys, itertools, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import vloop as V
from concurrent.futures import ProcessPoolExecutor
K165 = 0.8208          # C15850 at 1.65 V of bias (Samsung data) x 0.9 tolerance, as powercal's K10_165
CANDS = {
    "OPA365 (design): 0.2R, 4.7k, 3 nF, 2x10uF": ("lin365", dict(riso=0.2, rfb=4.7e3, cfb=3e-9, n10=2)),
    "MCP6002-a: 2R (1R+1R), 4.7k, 1 uF, 4x10uF": ("mcp", dict(riso=2.0, rfb=4.7e3, cfb=1e-6, n10=4)),
    "MCP6002-b: 2R (1R+1R), 4.7k, 1 uF, 8x10uF": ("mcp", dict(riso=2.0, rfb=4.7e3, cfb=1e-6, n10=8)),
    "TLV9062-a: 0.2R (5x1R), 4.7k, 100 nF, 4x10uF": ("tlv", dict(riso=0.2, rfb=4.7e3, cfb=100e-9, n10=4)),
    "TLV9062-b: 0.333R (3x1R), 4.7k, 1 uF, 4x10uF": ("tlv", dict(riso=1 / 3, rfb=4.7e3, cfb=1e-6, n10=4)),
}
def corners(kind):
    pas = list(itertools.product((K165, 1.0), (0.005, None), (0.765, 1.235)))   # C factor, ESR per cap (None: Samsung at 5 kHz 72 mohm), Cfb factor
    if kind == "mcp":
        buf = [dict(ro=ro, fp2=fp2, gbw=g) for ro in (50, 300, 1000, 2000) for fp2 in (3e6, 6e6) for g in (0.7e6, 1.0e6)]
    else:
        buf = [dict()]
    return [(c, e, k, b) for (c, e, k) in pas for b in buf]
def one(a):
    name, spec, tag, (c, e, k, b) = a
    kind, d = spec
    n = d["n10"]; esr = (e if e is not None else 0.0721) / n
    dd = dict(riso=d["riso"], rfb=d["rfb"], cfb=d["cfb"] * k, cnode=n * 10e-6 * c, esr=esr)
    r = V.evaluate(kind, dd, f"rb_{tag}", **b)
    f, az = r["f"], np.abs(r["z"]); w = (f >= 1e3) & (f <= 1e6)
    return dict(name=name, corner=dict(C=c, esr=e, cfb=k, **b), zmax=r["zmax"], fz=r["fz"], zmax_1k_1M=float(az[w].max()),
                pm=r["pm_min"], nx=len(r["crossings"]))
if __name__ == "__main__":
    jobs = [(nm, CANDS[nm], f"{j}_{i}", cc) for j, nm in enumerate(CANDS) for i, cc in enumerate(corners(CANDS[nm][0]))]
    with ProcessPoolExecutor(4) as ex:
        res = list(ex.map(one, jobs))
    out = {}
    for nm in CANDS:
        rr = [x for x in res if x["name"] == nm]
        nom = rr[0]
        out[nm] = dict(n=len(rr), zmax_worst=max(x["zmax"] for x in rr), zmax_1k_1M_worst=max(x["zmax_1k_1M"] for x in rr),
                       pm_worst=min((x["pm"] if x["pm"] is not None else -1) for x in rr), multi_crossing=any(x["nx"] != 1 for x in rr),
                       worst_z_corner=max(rr, key=lambda x: x["zmax"])["corner"], worst_pm_corner=min(rr, key=lambda x: x["pm"] or -1)["corner"])
        print(nm, {k: v for k, v in out[nm].items()})
    json.dump(dict(summary=out, rows=res), open("robust.json", "w"), indent=1)
