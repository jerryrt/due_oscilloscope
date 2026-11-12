#!/usr/bin/env python3
"""SC-2 / SC-11 pin margin before calibration, by an explicit corner SEARCH (ngspice, the tee netlist).
python3 -I sc2.py -> results/sc2.json.

Why a separate search: the DF-3 corners (core2d.corner_draw) are built for CMRR and tie the op-amp offset
sign to the Vmid centring sign (wc: both +, pin_bot: both -).  The margin's worst case on +-1.25 V needs them OPPOSITE
(found below: R1 -, R2 +, R3 +, centring -, Vos +), so that set's 'margin' under-states the 1 % divider's loss: it
read 111.5 mV where this search and whatif/R3's analytic model read 64 and 62 (the guard in report.py that expected a
failure did not fire, which is how this was found).  Here every sign of R1, R2, R3 (tolerance + tempco over 10 K, absolute: before calibration the
tempco does not track), both Vmid centring signs (+-30 mV), both op-amp offset signs and both Ron ends are run, at
AREF 3.20 V, rail 3.23 V, both channels set alike (the margin is per channel)."""
import os, sys, json, itertools
import numpy as np
from concurrent.futures import ProcessPoolExecutor
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import dlib, core2d as c

CASES = {"0.1 %, 25 ppm/K (design)": (1e-3, 25e-6), "1 %, 100 ppm/K (Basic, datasheet)": (1e-2, 100e-6)}
DT = 10.0

def job(a):
    lab, s1, s2, s3, sc_, sv, ron, rg = a
    tol, tc = CASES[lab]
    t = tol + tc * DT
    base = c.corner_draw(c.SPEC, name="sc2")
    ch = dict(base["A"])
    ch.update(R1=c.NOM["R1"] * (1 + s1 * t), R2=c.NOM["R2"] * (1 + s2 * t), R3=c.NOM["R3"] * (1 + s3 * t),
              RF=c.NOM["RF"] * (1 + 1e-3 + 25e-6 * DT), RG=c.NOM["RG"] * (1 - 1e-3 - 25e-6 * DT),
              Ron=ron, vos=sv * (c.VOS_MAX + c.VOS_TC * DT), eC1=0.0, eC2=0.0, stray=0.0)
    d = dict(base, A=ch, B=dict(ch), Rsa=0.0, Rsb=0.0, sh=dict(aref=3.20, cent=sc_ * c.CENT, vcc=3.23))
    r = c.eval_range(f"sc2_{abs(hash(a))}", d, rg, with_ac=False)
    return a, r["margin"], r["pin_min"], r["pin_max"]

def main():
    jobs = [(lab, s1, s2, s3, sc_, sv, ron, rg) for lab in CASES for s1, s2, s3 in itertools.product((1, -1), repeat=3)
            for sc_ in (1, -1) for sv in (1, -1) for ron in (3.7, 8.8) for rg in ("5", "1.25")]
    with ProcessPoolExecutor(int(os.environ.get("TEE_WORKERS", "4"))) as ex:
        res = list(ex.map(job, jobs, chunksize=8))
    out = {}
    for lab in CASES:
        for rg in ("5", "1.25"):
            rows = [x for x in res if x[0][0] == lab and x[0][7] == rg]
            w = min(rows, key=lambda x: x[1])
            # what the DF-3 corner set alone would have reported: R1 -, R2 +, R3 + (and the mirror)
            dfc = min(x[1] for x in rows if (x[0][1], x[0][2], x[0][3]) in ((-1, 1, 1), (1, -1, -1)))
            out[f"{lab}|{rg}"] = dict(margin_mV=w[1] * 1e3, at=dict(zip(("R1", "R2", "R3", "cent", "vos", "Ron"), w[0][1:7])),
                                      df3_corner_signs_only_mV=dfc * 1e3, pass_=bool(w[1] >= 0.080))
    # guard: the search must find a worse margin than the DF-3 corner signs on the 1 % divider (that is why it exists),
    # and the 80 mV check must pass on 0.1 % and fail on 1 % for the range that whatif/R3 flagged (+-1.25 V)
    g1 = out["1 %, 100 ppm/K (Basic, datasheet)|1.25"]
    g0 = out["0.1 %, 25 ppm/K (design)|1.25"]
    df3m = json.load(open(os.path.join(HERE, "results", "raw_1pct_tau100.json")))["corners"]
    df3m = min(v["1.25"]["margin"] for v in df3m.values()) * 1e3
    out["guards"] = [dict(check="search finds the SC-11 margin corner", mutation="restrict to the DF-3 corner set (Vos and centring signs tied)",
                          good=g1["margin_mV"], broken=df3m, fired=bool(df3m - g1["margin_mV"] > 10)),
                     dict(check="SC-11 margin >= 80 mV", mutation="divider 0.1 % -> 1 %", good=g0["margin_mV"], broken=g1["margin_mV"],
                          fired=bool(g0["margin_mV"] >= 80 > g1["margin_mV"]))]
    json.dump(out, open(os.path.join(HERE, "results", "sc2.json"), "w"), indent=1)
    print(json.dumps(out, indent=1))

if __name__ == "__main__":
    main()
