#!/usr/bin/env python3
"""PR-4: a voltage forced on the AWG BNC (+-1.8 V survive, +-5 V stress), powered and unpowered, wire off / on; the clamp, the
rail it charges unpowered (R65 4.7k bleed, design.py), and the AWG node loading (AW-4, AW-6).  numpy only."""
import json, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import net
from net import *
from ranges import pin_with_clamp, idiode, DD

R_BLEED = 4.7e3      # design.py R65, +3V3A bleed (PR-3)
def forced(Vbnc, powered, wire, n=2000, seed=11):
    P = draw(n, seed, net.DES, 0.01, 0.0)
    ref = P["ref"] if powered else np.zeros(n)
    nd = solve_net(Vbnc, ref, P["rl3"], P["rl5"], P["Rt"], P["Rb"], P["Rd"], P["Rs"], np.full(n, 1e15), 0.0, wire)
    Rth = P["Rt"] * (P["Rb"] + P["Rd"]) / (P["Rt"] + P["Rb"] + P["Rd"]) if wire is None else P["Rt"] * P["Rb"] / (P["Rt"] + P["Rb"])
    if powered:
        v, iu, idn = pin_with_clamp(nd["T0"], Rth + P["Rs"], VDD_MIN)
        vdd = np.full(n, VDD_MIN)
    else:
        vdd = np.zeros(n)
        for _ in range(60):      # the upper diode charges the rail, which the bleed holds down
            v, iu, idn = pin_with_clamp(nd["T0"], Rth + P["Rs"], vdd)
            vdd = np.maximum(iu, 0) * R_BLEED
    iu = np.maximum(iu, 0); idn = np.maximum(idn, 0)
    ichain = np.abs(Vbnc - ref) / (P["Rt"] + P["Rb"] + P["Rd"])
    return dict(V=Vbnc, powered=powered, wire=wire or "off", t0=(float(nd["T0"].min()), float(nd["T0"].max())), pin=(float(v.min()), float(v.max())),
                i_clamp_uA=float(np.max(iu + idn) * 1e6), rail_V=float(vdd.max()), i_chain_uA=float(ichain.max() * 1e6))

def awg_load():
    """DC load of the sense chain on the AWG node, wire off and on: current from the node, the drop in the 49.9 ohm, thermal noise"""
    n = 4000; P = draw(n, 5, net.DES, 0.01, 0.0)
    out = {}
    for wire in (None, "TAP5"):
        cur = []
        for A in (-AWG_LIM, 0.0, AWG_LIM):
            nd = solve_net(A, P["ref"], P["rl3"], P["rl5"], P["Rt"], P["Rb"], P["Rd"], P["Rs"], P["Z"][:, 0], 0.0, wire)
            cur.append((A - nd["T0"]) / P["Rt"])      # current leaving the AWG node into the divider (positive = out of the node)
        out[wire or "off"] = [float(np.max(c)) * 1e6 for c in cur], [float(np.min(c)) * 1e6 for c in cur]
    kT4 = 4 * 1.380649e-23 * 300.0
    # thermal current noise of the chain (Rt + Rb + Rd in series, seen from the node) through the 49.9 ohm back-termination, 10 MHz bandwidth (an upper bound on any AWG stage bandwidth) 
    rchain = 201e3
    vn = np.sqrt(kT4 / rchain) * 49.9 * np.sqrt(10e6)
    # reference noise (SBVS032K 10 Hz-10 kHz, 51 uVrms per v2's common.py REF['noise_uvrms']) reaches the node through the divider: 49.9 / chain
    vref_n = 51e-6 * 49.9 / 201e3
    return out, vn, vref_n

def main():
    rows = []
    for V in (1.8, -1.8, 5.0, -5.0, 12.0, -12.0):
        for powered in (True, False):
            for wire in (None, "TAP5"):
                rows.append(forced(V, powered, wire))
    json.dump(rows, open(os.path.join(RES, "forced.json"), "w"), indent=1)
    for r in rows:
        print(f"{r['V']:+5.1f} V  {'powered  ' if r['powered'] else 'unpowered'} wire {r['wire']:5s} T0 {r['t0'][0]:+.2f}..{r['t0'][1]:+.2f}  pin {r['pin'][0]:+.3f}..{r['pin'][1]:+.3f}  I_clamp {r['i_clamp_uA']:6.1f} uA  rail {r['rail_V']:.3f} V  I_chain {r['i_chain_uA']:.0f} uA")
    out, vn, vrn = awg_load()
    json.dump(dict(load=out, thermal_noise_V=vn, ref_noise_V=vrn), open(os.path.join(RES, "awg_load.json"), "w"), indent=1)
    print(out, vn, vrn)

if __name__ == "__main__":
    main()
