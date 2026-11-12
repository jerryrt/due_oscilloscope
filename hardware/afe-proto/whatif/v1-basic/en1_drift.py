#!/usr/bin/env python3
"""v1-basic: EN-1, the scope channel's uncalibrated gain drift over 15-35 C (20 K), by the 2b netlist.

Each resistor carries its datasheet tempco with a free sign; every sign combination is simulated (ngspice, the copied
sim/scope 'hz' channel, OPA354 model unchanged) at -10 K and +10 K about 25 C, and the largest gain change is reported
per range.  The TMUX1119's Ron drift (sim/diff's RON_TC, 1 %/10 K, *(check)*) is added with its own free sign on the
+/-5 V range, where Ron is in the gain.  AREF, Vmid and the op-amp are held: EN-1 excludes the Due's own drift and the
offset terms do not enter a slope.

    python3 -I en1_drift.py            -> results/en1.json, prints the table
Design rows:
  current  0.1 %: R1 = R3 = 330k + 330k + 100k (25, 25, 10 ppm/K), R2 330k 25 ppm/K, RF 953 25 ppm/K, RG 249 10 ppm/K
  basic    1 %:   every resistor 100 ppm/K (UNI-ROYAL datasheet, > 10 ohm), RF 1k || 100k, RG 270
"""
import os, sys, json, itertools
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "sim", "scope"))
import netlib as NL
import run as S

DT = 10.0
RON_TC = 1e-3          # 1/K, sim/diff core2d RON_TC *(check: TMUX1119 Ron-vs-temperature curve not read)*
DESIGNS = {
    "current (0.1 %)": dict(RF=953.0, RG=249.0, tc=dict(R1=(660e3 * 25 + 100e3 * 10) / 760e3, R2=25.0, R3=(660e3 * 25 + 100e3 * 10) / 760e3, RF=25.0, RG=10.0)),
    "basic (1 %)": dict(RF=1 / (1 / 1e3 + 1 / 100e3), RG=270.0, tc=dict(R1=100.0, R2=100.0, R3=100.0, RF=100.0, RG=100.0)),
}

def gain(p, rng):
    v = 6.0 if rng == "5" else 1.25
    pins, _ = S.dc_pins(p, [-v, 0.0, v], name="en1")
    return (pins[2] - pins[0]) / (2 * v)

def drift(des, rng):
    NL.use_variant("hz"); NL.PFX = "en1_"
    base = S.pp(rng=rng, RF=des["RF"], RG=des["RG"], aref=3.25, vmid=1.625, v3=3.25, vcc=3.3, Ron_sw=3.7)
    g0 = gain(base, rng)
    keys = ["R1", "R2", "R3"] + (["RF", "RG"] if rng == "1.25" else ["RG", "Ron"])
    worst = (0.0, None)
    for signs in itertools.product((1, -1), repeat=len(keys)):
        g = {}
        for dT in (-DT, DT):
            q = dict(base)
            for k, s in zip(keys, signs):
                if k == "Ron":
                    q["Ron_sw"] = base["Ron_sw"] * (1 + s * RON_TC * dT)
                else:
                    q[k] = base[k] * (1 + s * des["tc"][k] * 1e-6 * dT)
            g[dT] = gain(q, rng)
        d = abs(g[DT] - g[-DT]) / g0
        if d > worst[0]:
            worst = (d, dict(zip(keys, signs)))
    return dict(g0=g0, drift_pct=worst[0] * 100, signs=worst[1])

if __name__ == "__main__":
    out = {}
    for name, des in DESIGNS.items():
        for rng in ("5", "1.25"):
            r = drift(des, rng)
            out[f"{name} | +/-{rng} V"] = r
            print(f"{name:16s} +/-{rng:4s} V  gain {r['g0']:.4f}  drift over 20 K {r['drift_pct']:.3f} %  at {r['signs']}")
    json.dump(out, open(os.path.join(HERE, "results", "en1.json"), "w"), indent=1)
