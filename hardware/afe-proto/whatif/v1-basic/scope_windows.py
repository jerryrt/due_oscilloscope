#!/usr/bin/env python3
"""v1-basic: the scope channel's DC windows (SC-2, SC-4, SC-11) with Basic 1 % resistors, by the 2b simulation.

Runs the copied sim/scope (sim/scope/run.py dc_section, variant 'hz', OPA354, unchanged models) with
  V1B_TOL      resistor tolerance (0.001 = the current design's 0.1 %, 0.01 = Basic 1 %)
  V1B_VCC_LO/HI the +3.3 V_A corners (the LM27762 rail with 1 % feedback resistors, see powercal_v1b.py)
and the stage values RF/RG as arguments.  Worst case = one-at-a-time extremes summed (2b's method), plus 2b's
Monte Carlo when --mc is given.

    python3 -I scope_windows.py TAG RF RG [--mc]       -> results/scope_<TAG>.json, prints the window rows
"""
import os, sys, json
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "sim", "scope"))
import netlib as NL
import run as S

def windows(tag, RF, RG, mc=False):
    NL.use_variant("hz")
    NL.PFX = tag + "_"
    S.set_res(os.path.join(HERE, "results"))
    d = S.dc_section("OPA354", quick=not mc, over=dict(RF=RF, RG=RG), tag=f"scope_{tag}")
    T5, T12 = d["aref_table"]["5"], d["aref_table"]["1.25"]
    g5 = (T5["3.30"]["gain_min"], T5["3.30"]["gain_max"])
    g12 = (T12["3.20"]["gain_min"], T12["3.20"]["gain_max"])
    out = dict(tag=tag, RF=RF, RG=RG, tol=S.TOL, vcc=(S.VCC_LO, S.VCC_HI),
               sc2_margin_mV=T5["3.20"]["margin_wc"] * 1e3, sc2_hi_mV=T5["3.20"]["margin_hi_wc"] * 1e3, sc2_lo_mV=T5["3.20"]["margin_lo_wc"] * 1e3,
               sc4_gain=g5, sc4_occ_pct=(10 * g5[0] / 3.3 * 100, 10 * g5[1] / 3.3 * 100), sc4_mV_per_code=3.3 / 4096 / g5[0] * 1e3,
               sc11_gain=g12, sc11_margin_mV=T12["3.20"]["margin_wc"] * 1e3,
               nominal_g5=T5["3.30"]["nominal"]["gain"], nominal_g12=T12["3.20"]["nominal"]["gain"],
               headroom_mV={k: v["headroom_to_rail"] * 1e3 for k, v in d["headroom"].items()},
               lowest_aref=d["lowest_aref"], mc=d.get("mc"))
    out["checks"] = {
        "SC-2 margin >= 80 mV (+/-6 V, AREF 3.20)": out["sc2_margin_mV"] - 80,
        "SC-4 occupancy 70-75 % (AREF 3.30)": min(out["sc4_occ_pct"][0] - 70, 75 - out["sc4_occ_pct"][1]),
        "SC-4 step <= 4 mV/code": 4 - out["sc4_mV_per_code"],
        "SC-11 gain 1.10-1.16": min(g12[0] - 1.10, 1.16 - g12[1]),
        "SC-11 margin >= 80 mV (+/-1.25 V, AREF 3.20)": out["sc11_margin_mV"] - 80,
    }
    json.dump(out, open(os.path.join(HERE, "results", f"scope_{tag}_summary.json"), "w"), indent=1)
    return out

if __name__ == "__main__":
    a = sys.argv[1:]
    mc = "--mc" in a; a = [x for x in a if x != "--mc"]
    tag, RF, RG = a[0], float(a[1]), float(a[2])
    o = windows(tag, RF, RG, mc)
    print(json.dumps({k: o[k] for k in ("tag", "RF", "RG", "tol", "vcc", "nominal_g5", "nominal_g12", "sc4_gain", "sc11_gain",
                                       "sc2_margin_mV", "sc11_margin_mV", "headroom_mV")}, default=str))
    for k, v in o["checks"].items():
        print(f"  [{'PASS' if v >= 0 else 'FAIL'}] {k}: margin {v:+.4g}")
