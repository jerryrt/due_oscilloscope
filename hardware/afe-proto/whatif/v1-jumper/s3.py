#!/usr/bin/env python3
"""Structure S3 for version 1: PR-3 / PR-4 with a BAV99 at BOTH ADS1115 inputs (T0 on AIN2 through Rs, B on AIN3 through Rm), range, wrong positions,
precision and the design scan.  numpy only.  The clamp model is ranges.py's (BAV99 from memory, (check))."""
import json, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import net
from net import *
from ranges import idiode, pin_with_clamp

R_BLEED = 4.7e3
def s3design(rt, rb, rs, rm, wire, rd=1e3):
    return dict(Rt=rt, Rb=rb, Rd=rd, Rs=rs, Rm1=0.0, Rm2=rm, Il=0.0, chan="B", wire=wire)

def forced_s3(d, Vbnc, powered, wire, n=1500, seed=11, iters=25):
    """Both pins clamped by BAV99 (diodes to GND and +3V3A); powered: rail 3.21 V; unpowered: REF = 0 and the rail charged by the upper diodes into R65."""
    P = draw(n, seed, d, 0.01, 0.0)
    ref = P["ref"] if powered else np.zeros(n)
    vdd = np.full(n, VDD_MIN if powered else 0.0)
    inj = {1: np.zeros(n), 8: np.zeros(n)}
    def sol(inj_):
        return solve_net(Vbnc, ref, P["rl3"], P["rl5"], P["Rt"], P["Rb"], P["Rd"], P["Rs"], np.full(n, 1e15), 0.0, wire, None, Rm2=P["Rm2"], Z2=np.full(n, 1e15), chan="B", inj=inj_)
    for it in range(iters):
        for pin, nm in ((1, "PIN"), (8, "P2")):
            i0 = dict(inj); i0[pin] = np.zeros(n); V0 = sol(i0)[nm]
            i1 = dict(inj); i1[pin] = np.full(n, 1e-6); V1 = sol(i1)[nm]
            Rth = np.maximum((V0 - V1) / 1e-6, 1.0)
            v, iu, idn = pin_with_clamp(V0, Rth, vdd)
            inj[pin] = iu - idn
            if pin == 1: iu1, idn1, v1 = iu, idn, v
            else: iu8, idn8, v8 = iu, idn, v
        if not powered: vdd = (iu1 + iu8) * R_BLEED
    nd = sol(inj)
    return dict(V=Vbnc, powered=powered, wire=wire or "off", pinT=(float(nd["PIN"].min()), float(nd["PIN"].max())), pinB=(float(nd["P2"].min()), float(nd["P2"].max())),
                i_rail_uA=float(np.max(iu1 + iu8) * 1e6), i_gnd_uA=float(np.max(idn1 + idn8) * 1e6), rail_V=float(vdd.max()), iT_uA=float(np.max(iu1 + idn1) * 1e6), iB_uA=float(np.max(iu8 + idn8) * 1e6))

def pr3(d):
    out = {}
    for V in (5.0, -5.0, 1.8, -1.8):
        for powered in (False, True):
            for w in (None, d["wire"]):
                out[(V, powered, w)] = forced_s3(d, V, powered, w)
    return out

def range_s3(d, n=6000):
    res = {}
    for w in (None, d["wire"]):
        lo, hi = 9.0, -9.0
        for A in (-AWG_LIM, AWG_LIM):
            P = draw(n, 7, d, 0.01, 0.0)
            nd = solve_net(A, P["ref"], P["rl3"], P["rl5"], P["Rt"], P["Rb"], P["Rd"], P["Rs"], P["Z"][:, 0], 0.0, w)
            lo = min(lo, nd["T0"].min(), nd["B"].min()); hi = max(hi, nd["T0"].max(), nd["B"].max())
        res[w or "off"] = (float(lo), float(hi))
    return res

if __name__ == "__main__":
    d = s3design(15e3, 10e3, 3.9e3, 10e3, "TAP3")
    for k, v in pr3(d).items():
        if k[0] in (5.0, -5.0) and not k[1]: print(k, "T pin %+.3f..%+.3f B pin %+.3f..%+.3f rail current %.0f uA gnd %.0f uA rail %.3f V" % (*v["pinT"], *v["pinB"], v["i_rail_uA"], v["i_gnd_uA"], v["rail_V"]))
