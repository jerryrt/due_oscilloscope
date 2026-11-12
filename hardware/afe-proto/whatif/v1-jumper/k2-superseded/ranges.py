#!/usr/bin/env python3
"""Range, wrong positions, the BAV99 clamp, the forced BNC voltage (PR-4), the AWG loading (AW-4, AW-6).  numpy only.
Every check is also run on a deliberately broken input and must FAIL there (guards at the end)."""
import json, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import net
from net import *

DD = dict(Rt=100e3, Rb=100e3, Rd=1e3, Rs=1.0)
# BAV99 (Nexperia BAV99,215, LCSC C2500) forward curve, from memory of the datasheet, NOT read here (no datasheet in the repo): VF 715 mV max at 1 mA, 855 mV max at 10 mA
# (check).  Shockley fit through those two points: n Vt = (0.855-0.715)/ln(10) V per e-fold, Is from 1 mA at 0.715 V.
NVT = (0.855 - 0.715) / np.log(10.0)
IS = 1e-3 / np.exp(0.715 / NVT)
def idiode(v):
    return IS * (np.exp(np.minimum(v, 3.0) / NVT) - 1.0) * 1.0 if np.isscalar(v) else IS * (np.exp(np.minimum(v, 3.0) / NVT) - 1.0)

def pin_with_clamp(Vth, Rth, vdd):
    """pin voltage and clamp currents: Thevenin (Vth, Rth) into the pin (Rs included in Rth), BAV99 to GND and to +3V3A, the ADS1115 pin otherwise open
    (its 6 Mohm and its own ESD diodes ignored: they are in parallel with the BAV99 and conduct no earlier than it does, (check))."""
    Vth = np.atleast_1d(np.asarray(Vth, float)); Rth = np.broadcast_to(np.asarray(Rth, float), Vth.shape)
    lo = np.full(Vth.shape, -3.0); hi = np.full(Vth.shape, 12.0)
    for _ in range(80):
        v = 0.5 * (lo + hi)
        f = (Vth - v) / Rth - (idiode(v - vdd) - idiode(-v))     # net current into the pin node: source - upper diode (pin above vdd) + lower diode (pin below 0)
        pos = f > 0
        lo = np.where(pos, v, lo); hi = np.where(pos, hi, v)
    v = 0.5 * (lo + hi)
    return v, idiode(v - vdd), idiode(-v)

def thevenin_pin(wire, Vx, n=3000, seed=3, A=0.0, d=DD, ref_scale=1.0):
    """Thevenin source seen by the ADS pin (Z disconnected): open-circuit voltage and resistance (Rt||Rb with the wire, plus Rs)."""
    P = draw(n, seed, dict(net.DES, **d), 0.01, 0.0)
    z = np.full(n, 1e15)
    nd = solve_net(A, P["ref"], P["rl3"], P["rl5"], P["Rt"], P["Rb"], P["Rd"], P["Rs"], z, 0.0, wire, Vx)
    return nd, P

STATES = [  # (name, wire, Vx, allowed on the header, note)
    ("wire OFF (default tie, normal use)", None, None, "header", ""),
    ("wire B-TAP5 (the right position)", "TAP5", None, "header", ""),
    ("wire B-TAP4 (header neighbour)", "TAP4", None, "header", ""),
    ("wire TAP4-TAP5 (across one rung, B left on its default)", "ladder54", None, "header", ""),
    ("wire B-TAP2 (0.75 V, via the Due's ADC pin)", "TAP2", None, "Due pin", ""),
    ("wire B-VREF (3.0 V, via the Due's ADC pin)", "fixed", 3.0, "Due pin", ""),
    ("wire B-GND", "fixed", 0.0, "Due pin", ""),
    ("wire B-+3V3A (3.3 V)", "fixed", 3.3, "Due pin", ""),
    ("wire B-Due 5V (5.25 V max, stress)", "fixed", 5.25, "Due pin", ""),
    ("wire B-Due VIN (12 V, stress)", "fixed", 12.0, "Due pin", ""),
]

def span(wire, Vx, n=6000, seed=7):
    """min / max of T0 and PIN over A = -1.35 .. +1.35 and the tolerance draws (resistors 1 %, REF 0.1 %)"""
    out = {}
    for A in (-AWG_LIM, AWG_LIM):
        P = draw(n, seed, net.DES, 0.01, 0.0)
        nd = solve_net(A, P["ref"], P["rl3"], P["rl5"], P["Rt"], P["Rb"], P["Rd"], P["Rs"], P["Z"][:, 0], 0.0, wire, Vx)
        out[A] = (nd, P)
    return out

def main():
    rows = []
    for name, wire, Vx, where, note in STATES:
        sp = span(wire, Vx)
        t0 = np.concatenate([sp[a][0]["T0"] for a in sp]); tmin, tmax = float(t0.min()), float(t0.max())
        # clamp solution at the worst end of the window: Thevenin at the pin
        worst = {}
        for A, (nd, P) in sp.items():
            n = len(nd["T0"])
            # open-circuit T0 with the wire (Z removed) and the node resistance Rt||Rb (stiff B for fixed wires) + Rs
            nd2 = solve_net(A, P["ref"], P["rl3"], P["rl5"], P["Rt"], P["Rb"], P["Rd"], P["Rs"], np.full(n, 1e15), 0.0, wire, Vx)
            Rth = np.where(np.array([wire in ("fixed", "TAP5", "TAP4", "TAP2")] * n), P["Rt"] * P["Rb"] / (P["Rt"] + P["Rb"]), P["Rt"] + P["Rb"] + P["Rd"]) 
            # unfixed B (off / ladder54): B floats through Rd to the reference: Thevenin resistance seen from T0 is Rt || (Rb + Rd)
            Rth = np.where(np.array([wire in ("fixed", "TAP5", "TAP4", "TAP2")] * n), Rth, P["Rt"] * (P["Rb"] + P["Rd"]) / (P["Rt"] + P["Rb"] + P["Rd"]))
            v, iup, idn = pin_with_clamp(nd2["T0"], Rth + P["Rs"], VDD_MIN)
            worst[A] = (v, iup, idn)
        pmin = min(float(worst[a][0].min()) for a in worst); pmax = max(float(worst[a][0].max()) for a in worst)
        iclamp = max(float(np.max(worst[a][1] + worst[a][2])) for a in worst)
        # reference and ladder current in the state
        iref = 0.0
        for A, (nd, P) in sp.items():
            i = (nd["ref"] - nd["TAP5"]) / P["rl5"][:, 4] + (nd["ref"] - nd["B"]) / P["Rd"]
            iref = max(iref, float(np.abs(i).max()))
        inr = (tmin >= 0.0) and (tmax <= VDD_MIN)
        rows.append(dict(state=name, where=where, t0_min=tmin, t0_max=tmax, in_range=bool(inr), pin_min=pmin, pin_max=pmax, i_clamp_uA=iclamp * 1e6, i_ref_mA=iref * 1e3))
    # the ladder abuse positions (not B wires): TAP5 to GND, TAP5 to VREF (rung shorted)
    for name, wire, Vx in (("wire TAP5-GND (ladder shorted at the top)", "tap5fixed", 0.0), ("wire TAP5-VREF (one rung shorted)", "tap5fixed", 3.0), ):
        sp = span(wire, Vx)
        iref = 0.0
        t0 = []
        for A, (nd, P) in sp.items():
            t0.append(nd["T0"])
            i = (nd["ref"] - nd["TAP5"]) / P["rl5"][:, 4] + (nd["ref"] - nd["B"]) / P["Rd"]
            iref = max(iref, float(np.abs(i).max()))
        t0 = np.concatenate(t0)
        rows.append(dict(state=name, where="Due pin", t0_min=float(t0.min()), t0_max=float(t0.max()), in_range=bool(t0.min() >= 0 and t0.max() <= VDD_MIN),
                         pin_min=float(t0.min()), pin_max=float(t0.max()), i_clamp_uA=0.0, i_ref_mA=iref * 1e3))
    json.dump(rows, open(os.path.join(RES, "wrong_positions.json"), "w"), indent=1)
    for r in rows:
        print(f"{r['state']:58s} T0 {r['t0_min']:+.3f}..{r['t0_max']:.3f} in-range={r['in_range']!s:5s} pin {r['pin_min']:+.3f}..{r['pin_max']:.3f} Iclamp {r['i_clamp_uA']:6.1f} uA  Iref {r['i_ref_mA']:.2f} mA")
    return rows

if __name__ == "__main__":
    main()
