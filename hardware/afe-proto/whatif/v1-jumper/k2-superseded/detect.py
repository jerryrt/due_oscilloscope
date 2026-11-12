#!/usr/bin/env python3
"""The host verifies the wire from the readings: per wire state, the sense tap's shift dT and the TAP5 input's shift dA2 against the wire-off
readings at the same AWG level (A = -1.3 V, the ratio level).  The right position is a box in (dT, dA2); every other state must be outside it
by at least 20 x the reading resolution (125 uV + 0.1 % of 3 V = 3.1 mV, v2's figure).  numpy only."""
import json, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import net
from net import *
from ranges import STATES

def box(wire, Vx, A, n=6000):
    P = draw(n, 21, net.DES, 0.01, 0.0)
    f = lambda w, v: solve_net(A, P["ref"], P["rl3"], P["rl5"], P["Rt"], P["Rb"], P["Rd"], P["Rs"], P["Z"][:, 0], 0.0, w, v)
    off = f(None, None); on = f(wire, Vx)
    return (on["T0"] - off["T0"]), (on["TAP5"] - off["TAP5"])

def main(limit_mult=20.0, A=-1.3, verbose=True):
    res = 125e-6 + 0.001 * 3.0
    boxes = {}
    for name, wire, Vx, where, note in STATES + [("wire TAP5-GND (ladder shorted at the top)", "tap5fixed", 0.0, "Due pin", ""), ("wire TAP5-VREF (one rung shorted)", "tap5fixed", 3.0, "Due pin", "")]:
        if wire is None: continue
        dT, dA = box(wire, Vx, A)
        boxes[name] = (float(dT.min()), float(dT.max()), float(dA.min()), float(dA.max()))
    right = boxes["wire B-TAP5 (the right position)"]
    rows = []
    for k, b in boxes.items():
        if k == "wire B-TAP5 (the right position)": continue
        gt = max(b[0] - right[1], right[0] - b[1], 0.0); ga = max(b[2] - right[3], right[2] - b[3], 0.0)
        rows.append(dict(state=k, dT=(b[0], b[1]), dA2=(b[2], b[3]), gap_dT=gt, gap_dA2=ga, gap=max(gt, ga), ok=max(gt, ga) >= limit_mult * res))
    if verbose:
        print("right box: dT %.3f..%.3f  dA2 %.4f..%.4f  (resolution %.2f mV)" % (right[0], right[1], right[2], right[3], res * 1e3))
        for r in rows: print(f"  {r['state']:58s} dT {r['dT'][0]:+.3f}..{r['dT'][1]:+.3f} dA2 {r['dA2'][0]:+.3f}..{r['dA2'][1]:+.3f}  gap {r['gap']*1e3:7.1f} mV  {'ok' if r['ok'] else 'NOT DISTINGUISHED'}")
    return dict(right=right, rows=rows, res=res)

if __name__ == "__main__":
    out = main()
    # guard: with the limit raised to 1 V the check must fail on at least one state; at 20 x it must pass on all
    bad = main(limit_mult=1000.0, verbose=False); ok = all(r["ok"] for r in out["rows"])
    g = dict(id="G-detect", what="distinguishability limit raised to 1000 x resolution (3.1 V) must fail", broken="fails" if not all(r["ok"] for r in bad["rows"]) else "PASSES (guard void)", restored="passes" if ok else "FAILS")
    print(g)
    json.dump(dict(detect=out, guard=g), open(os.path.join(RES, "detect.json"), "w"), indent=1, default=float)
