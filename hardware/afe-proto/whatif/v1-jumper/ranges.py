#!/usr/bin/env python3
"""Range, wrong positions, host detection, the BAV99 clamp, the forced BNC voltage (PR-4) and the AWG loading (AW-4, AW-6), for any design in net.DESIGNS.
numpy only.  Every check is also run on a deliberately broken input in guards.py and must FAIL there."""
import json, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import net
from net import *

# BAV99 (Nexperia BAV99,215, LCSC C2500) forward curve, from memory of the datasheet, NOT read here (no datasheet in the repo): VF 715 mV max at 1 mA,
# 855 mV max at 10 mA *(check)*.  Shockley fit through those two points.
NVT = (0.855 - 0.715) / np.log(10.0)
IS = 1e-3 / np.exp(0.715 / NVT)
def idiode(v):
    return IS * (np.exp(np.minimum(v, 3.0) / NVT) - 1.0)

def pin_with_clamp(Vth, Rth, vdd):
    """pin voltage and clamp currents: Thevenin (Vth, Rth) into the pin, BAV99 to GND and to +3V3A; the ADS1115's own diodes are in parallel, not modelled *(check)*."""
    Vth = np.atleast_1d(np.asarray(Vth, float)); Rth = np.broadcast_to(np.asarray(Rth, float), Vth.shape)
    vdd = np.broadcast_to(np.asarray(vdd, float), Vth.shape)
    lo = np.full(Vth.shape, -3.0); hi = np.full(Vth.shape, 12.0)
    for _ in range(80):
        v = 0.5 * (lo + hi)
        f = (Vth - v) / Rth - (idiode(v - vdd) - idiode(-v))
        pos = f > 0
        lo = np.where(pos, v, lo); hi = np.where(pos, hi, v)
    v = 0.5 * (lo + hi)
    return v, np.maximum(idiode(v - vdd), 0), np.maximum(idiode(-v), 0)

def header(d):
    """the three header pads: (left neighbour, B, right = the wire node).  Left is the next tap up for a wire at TAP5, next tap down otherwise"""
    w = d["wire"]; n = int(w[-1])
    return ("TAP%d" % (n - 1 if n >= 4 else n + 1), "B", w)

def states(d):
    L, _, Rn = header(d)
    ln, rn = int(L[-1]), int(Rn[-1])
    st = [("wire OFF (default tie, normal use)", None, None, "header"),
          ("wire B-%s (the right position)" % Rn, Rn, None, "header"),
          ("wire B-%s (header neighbour)" % L, L, None, "header"),
          ("wire %s-%s (across one rung, B on its default)" % (L, Rn), "ladder%d%d" % (min(ln, rn), max(ln, rn)), None, "header")]
    for t in range(1, 6):
        if "TAP%d" % t not in (L, Rn): st.append(("wire B-TAP%d (%.4g V, via a Due ADC pin)" % (t, 0.1875 + 0.5625 * (t - 1) if t != 1 else 0.1875), "TAP%d" % t, None, "Due pin"))
    st += [("wire B-VREF (3.0 V)", "fixed", 3.0, "Due pin"), ("wire B-GND", "fixed", 0.0, "Due pin"), ("wire B-+3V3A (3.3 V)", "fixed", 3.3, "Due pin"),
           ("wire B-Due 5V (5.25 V max, stress)", "fixed", 5.25, "Due pin"), ("wire B-Due VIN (12 V, stress)", "fixed", 12.0, "Due pin"),
           ("wire TAP5-GND (ladder shorted at the top)", "tap5fixed", 0.0, "Due pin"), ("wire TAP5-VREF (one rung shorted)", "tap5fixed", 3.0, "Due pin")]
    return st

def span(d, wire, Vx, n=6000, seed=7):
    out = {}
    for A in (-AWG_LIM, AWG_LIM):
        P = draw(n, seed, d, 0.01, 0.0)
        nd = solve_net(A, P["ref"], P["rl3"], P["rl5"], P["Rt"], P["Rb"], P["Rd"], P["Rs"], P["Z"][:, 0], 0.0, wire, Vx)
        out[A] = (nd, P)
    return out

def thevenin_R(d, P, wire):
    fixed = wire is not None and (wire in NODE or wire == "fixed")
    return np.where(fixed, P["Rt"] * P["Rb"] / (P["Rt"] + P["Rb"]), P["Rt"] * (P["Rb"] + P["Rd"]) / (P["Rt"] + P["Rb"] + P["Rd"])) + P["Rs"]

def positions(d, verbose=True):
    rows = []
    for name, wire, Vx, where in states(d):
        sp = span(d, wire, Vx)
        t0 = np.concatenate([sp[a][0]["T0"] for a in sp]); tmin, tmax = float(t0.min()), float(t0.max())
        pins, iclamp, iref = [], 0.0, 0.0
        for A, (nd, P) in sp.items():
            n = len(nd["T0"])
            nd2 = solve_net(A, P["ref"], P["rl3"], P["rl5"], P["Rt"], P["Rb"], P["Rd"], P["Rs"], np.full(n, 1e15), 0.0, wire, Vx)
            v, iu, idn = pin_with_clamp(nd2["T0"], thevenin_R(d, P, wire), VDD_MIN)
            pins.append(v); iclamp = max(iclamp, float(np.max(iu + idn)))
            i = (nd["ref"] - nd["TAP5"]) / P["rl5"][:, 4] + (nd["ref"] - nd["B"]) / P["Rd"]
            iref = max(iref, float(np.abs(i).max()))
        pv = np.concatenate(pins)
        rows.append(dict(state=name, where=where, t0_min=tmin, t0_max=tmax, in_range=bool(tmin >= 0 and tmax <= VDD_MIN), pin_min=float(pv.min()), pin_max=float(pv.max()),
                         i_clamp_uA=iclamp * 1e6, i_ref_mA=iref * 1e3))
    if verbose:
        for r in rows:
            print(f"{r['state']:62s} T0 {r['t0_min']:+.3f}..{r['t0_max']:.3f} in-range={r['in_range']!s:5s} pin {r['pin_min']:+.3f}..{r['pin_max']:.3f} Iclamp {r['i_clamp_uA']:6.1f} uA  Iref {r['i_ref_mA']:.2f} mA")
    return rows

def detect(d, limit_mult=20.0, A=-1.3, verbose=False):
    """the host reads the tap (AIN0) and the bottom end (AIN2) in both states at one level: right wire = a box in (dT, dB); every other state must sit outside it by 20 x 3.1 mV"""
    res = 125e-6 + 0.001 * 3.0
    boxes = {}
    for name, wire, Vx, where in states(d):
        if wire is None: continue
        P = draw(6000, 21, d, 0.01, 0.0)
        f = lambda w, v: solve_net(A, P["ref"], P["rl3"], P["rl5"], P["Rt"], P["Rb"], P["Rd"], P["Rs"], P["Z"][:, 0], 0.0, w, v)
        off = f(None, None); on = f(wire, Vx)
        dT, dB, dA3 = on["T0"] - off["T0"], on["B"] - off["B"], on["TAP3"] - off["TAP3"]
        boxes[name] = (float(dT.min()), float(dT.max()), float(dB.min()), float(dB.max()), float(dA3.min()), float(dA3.max()))
    key = [k for k in boxes if "(the right position)" in k][0]; right = boxes[key]
    rows = []
    for k, b in boxes.items():
        if k == key: continue
        gaps = [max(b[2 * i] - right[2 * i + 1], right[2 * i] - b[2 * i + 1], 0.0) for i in range(3)]
        rows.append(dict(state=k, gap=max(gaps), ok=max(gaps) >= limit_mult * res, box=b))
    if verbose:
        print("right box: dT %.3f..%.3f  dB %.4f..%.4f" % right[:4])
        for r in rows: print(f"  {r['state']:62s} gap {r['gap']*1e3:7.1f} mV {'ok' if r['ok'] else 'NOT DISTINGUISHED'}")
    return dict(right=right, rows=rows, res=res)

R_BLEED = 4.7e3      # design.py R65, +3V3A bleed (PR-3)
def forced(d, Vbnc, powered, wire, n=2000, seed=11):
    P = draw(n, seed, d, 0.01, 0.0)
    ref = P["ref"] if powered else np.zeros(n)
    nd = solve_net(Vbnc, ref, P["rl3"], P["rl5"], P["Rt"], P["Rb"], P["Rd"], P["Rs"], np.full(n, 1e15), 0.0, wire)
    Rth = thevenin_R(d, P, wire)
    if powered:
        v, iu, idn = pin_with_clamp(nd["T0"], Rth, VDD_MIN); vdd = np.full(n, VDD_MIN)
    else:
        vdd = np.zeros(n)
        for _ in range(60):
            v, iu, idn = pin_with_clamp(nd["T0"], Rth, vdd); vdd = iu * R_BLEED
    return dict(V=Vbnc, powered=powered, wire=wire or "off", pin=(float(v.min()), float(v.max())), i_clamp_uA=float(np.max(iu + idn) * 1e6), rail_V=float(vdd.max()),
                i_chain_uA=float(np.max(np.abs(Vbnc - ref) / (P["Rt"] + P["Rb"] + P["Rd"])) * 1e6))

def awg_load(d):
    n = 4000; P = draw(n, 5, d, 0.01, 0.0); out = {}
    for wire in (None, d["wire"]):
        cur = []
        for A in (-AWG_LIM, 0.0, AWG_LIM):
            nd = solve_net(A, P["ref"], P["rl3"], P["rl5"], P["Rt"], P["Rb"], P["Rd"], P["Rs"], P["Z"][:, 0], 0.0, wire)
            cur.append((A - nd["T0"]) / P["Rt"])
        out[wire or "off"] = (float(min(c.min() for c in cur) * 1e6), float(max(c.max() for c in cur) * 1e6))
    rchain = d["Rt"] + d["Rb"] + d["Rd"]
    return dict(load_uA=out, drop_mV=(abs(out["off"][0]) * 49.9e-3, abs(out["off"][1]) * 49.9e-3),
                thermal_nV=float(np.sqrt(4 * 1.380649e-23 * 300.0 / rchain) * 49.9 * np.sqrt(10e6) * 1e9), ref_nV=51e-6 * 49.9 / rchain * 1e9)

def main():
    allr = {}
    for nm, d in net.DESIGNS.items():
        if 'matched' in nm: continue
        print("==", nm, "k = %.3f, Rth = %.1fk, header %s" % (kof(d), rth(d) / 1e3, header(d)))
        pos = positions(d)
        dt = detect(d, verbose=True)
        fr = [forced(d, V, p, w) for V in (1.8, -1.8, 5.0, -5.0, 12.0, -12.0) for p in (True, False) for w in (None, d["wire"])]
        al = awg_load(d)
        print("awg load", al)
        allr[nm] = dict(positions=pos, detect=dict(right=dt["right"], rows=dt["rows"]), forced=fr, awg=al)
    json.dump(allr, open(os.path.join(RES, "ranges_all.json"), "w"), indent=1, default=float)
if __name__ == "__main__":
    main()
