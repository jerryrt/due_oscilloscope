#!/usr/bin/env python3
"""v1-basic: SM-3 bandwidth, AN-1 phase margin and SC-6 noise of the scope channel with RF/RG changed, by the copied
sim/scope ac_section and noise_section (variant 'hz', models unchanged; the OPA354 rows are the design's).

    python3 -I scope_ac.py TAG RF RG        -> results/scope_ac_<TAG>/ac.json, noise.json; prints the rows
"""
import os, sys, json
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "sim", "scope"))
import netlib as NL
import run as S

tag, RF, RG = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
NL.P_HZ.update(RF=RF, RG=RG)
NL.use_variant("hz"); NL.PFX = "ac" + tag + "_"
S.set_res(os.path.join(HERE, "results", "scope_ac_" + tag))
ac = S.ac_section(); nz = S.noise_section()
for op in ("OPA354",):
    for rng in ("5", "1.25"):
        k = f"{op}_{rng}"; a = ac[k]
        pm = min([a["worst"]["pm"]] + [x["pm"] for x in a["sens"] if x["pm"] is not None])
        print(f"{k}: BW nominal {a['nominal']['bw']/1e6:.1f} MHz, worst {a['worst']['bw']/1e6:.1f} MHz; peak {a['worst']['peak_db']:.2f} dB; "
              f"PM worst {pm:.1f} deg; noise to 1.5 x BW {nz[k]['at_1p5bw']['total_V']*1e6:.1f} uV, to 10 MHz {nz[k]['at_10MHz']['total_V']*1e6:.1f} uV")
