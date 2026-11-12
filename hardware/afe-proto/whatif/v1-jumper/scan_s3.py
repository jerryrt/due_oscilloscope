#!/usr/bin/env python3
"""S3 design scan for version 1: k about 0.4, divider total, series Rs on the tap input, Rm = Rt||Rb + Rs on the B input (nearest Basic).  PR-3/PR-4, range, precision."""
import json, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import net
from net import *
import s3

BASIC = [1e3, 1.2e3, 1.5e3, 1.8e3, 2e3, 2.2e3, 2.4e3, 2.7e3, 3e3, 3.3e3, 3.6e3, 3.9e3, 4.7e3, 5.1e3, 5.6e3, 6.2e3, 6.8e3, 7.5e3, 8.2e3, 9.1e3, 10e3, 12e3, 13e3, 15e3, 18e3, 20e3, 22e3, 24e3, 27e3, 30e3, 33e3, 39e3, 47e3, 51e3, 56e3, 68e3, 75e3, 82e3, 100e3]
def nearest(x): return min(BASIC, key=lambda b: abs(np.log(b / x)))
N = int(os.environ.get("N", 8000))
def summ99(r): return float(np.percentile(abs(r["gain"]), 99.9) * 100), float(np.percentile(abs(r["off"]), 99.9) * 1e3)

def evaluate(rt, rb, rs, wire="TAP3", n=N, full=True):
    rth = rt * rb / (rt + rb); rm = nearest(rth + rs)
    d = s3.s3design(rt, rb, rs, rm, wire)
    f = {"Rt": rt, "Rb": rb, "Rs": rs, "Rm": rm, "k": rb / (rt + rb), "total": rt + rb}
    fo = [s3.forced_s3(d, 5.0, False, w) for w in (None, wire)]
    f["rail_V"] = max(x["rail_V"] for x in fo); f["rail_uA"] = max(x["i_rail_uA"] for x in fo)
    fm = [s3.forced_s3(d, -5.0, False, w) for w in (None, wire)]; f["gnd_uA"] = max(x["i_gnd_uA"] for x in fm)
    f["pinT_m5"] = min(x["pinT"][0] for x in fm); f["pinB_m5"] = min(x["pinB"][0] for x in fm)
    rg = s3.range_s3(d); f["range"] = rg
    if full:
        a = net.run_s3(n=n, d=d, zcorr=1.0); b = net.run_s3(n=n, d=d, zcorr=0.0)
        f["track"] = summ99(a); f["indep"] = summ99(b)
    return f

if __name__ == "__main__":
    rows = []
    for rt, rb in ((15e3, 10e3), (18e3, 12e3), (22e3, 15e3), (27e3, 18e3), (30e3, 20e3), (33e3, 22e3), (47e3, 30e3)):
        for rs in (3.9e3, 6.8e3, 10e3):
            f = evaluate(rt, rb, rs)
            rows.append(f)
            print(f"Rt {rt/1e3:g}k Rb {rb/1e3:g}k (k {f['k']:.3f}, total {f['total']/1e3:g}k) Rs {rs/1e3:g}k Rm {f['Rm']/1e3:g}k | +5V unp rail {f['rail_V']:.3f} V {f['rail_uA']:.0f} uA | -5V gnd {f['gnd_uA']:.0f} uA pinT {f['pinT_m5']:+.2f} | track {f['track'][0]:.3f}%/{f['track'][1]:.2f}mV indep {f['indep'][0]:.3f}%/{f['indep'][1]:.2f}mV")
    json.dump(rows, open(os.path.join(RES, "scan_s3.json"), "w"), indent=1, default=float)
