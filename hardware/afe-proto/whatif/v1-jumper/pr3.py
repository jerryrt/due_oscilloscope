#!/usr/bin/env python3
"""PR-3 / PR-4 on kvm_02's worst case: the REF3030E output 0 V, open (ladder only) or clamping into the rail, the ADS1115 ESD onset 0.3 V (a hard onset, 5 ohm),
resistors +-1 %, the +3V3A rail charged by the upper diodes of every input into the bleed R65.  Also the other PR-3 case: both scope inputs at +12 V.  numpy only.
What the earlier ranges.py / s3.py model assumed is listed in design.md section 8 (REF at 0 V, BAV99 Shockley curve, no ESD onset, rail load = R65 4.7k only)."""
import json, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import net
from net import *
from s3 import s3design

RON = 5.0
def hard_clamp(Vth, Rth, vdd, vd):
    """a pin behind Rth with ideal-onset diodes to +3V3A (onset vdd + vd) and to GND (onset -vd), series 5 ohm.  Returns pin voltage, current into the rail, into GND."""
    up = Vth > vdd + vd; dn = Vth < -vd
    v = np.where(up, (Vth * RON + (vdd + vd) * Rth) / (Rth + RON), np.where(dn, (Vth * RON + (-vd) * Rth) / (Rth + RON), Vth))
    iu = np.where(up, (Vth - v) / Rth, 0.0); idn = np.where(dn, (v - Vth) / Rth, 0.0)
    return v, iu, idn

def forced(d, Vbnc, wire, ref_state, vd=0.3, bleed=4.7e3, n=1500, seed=11, iters=30, extra_uA=0.0):
    """ref_state: 'zero' (REF output at 0 V), 'open' (floating, only the ladder to GND), 'clamp' (floating, clamping into the rail through a diode).  Returns the worst over the draws."""
    P = draw(n, seed, d, 0.01, 0.0)
    if ref_state.endswith("_nl"):       # kvm_02's network has no ladder on the reference node: the top rung is taken out
        P["rl5"] = P["rl5"].copy(); P["rl5"][:, 4] = 1e12
    ref = np.zeros(n) if ref_state == "zero" else None
    vdd = np.zeros(n); inj = {1: np.zeros(n), 8: np.zeros(n), 9: np.zeros(n)}
    def sol(i):
        return solve_net(Vbnc, ref, P["rl3"], P["rl5"], P["Rt"], P["Rb"], P["Rd"], P["Rs"], np.full(n, 1e15), 0.0, wire, None, Rm2=P["Rm2"], Z2=np.full(n, 1e15), chan="B", inj=i)
    nodes = [(1, "PIN"), (8, "P2")] + ([(9, "REF")] if ref_state.startswith("clamp") else [])
    u = {}
    for it in range(iters):
        for pin, nm in nodes:
            i0 = dict(inj); i0[pin] = np.zeros(n); V0 = sol(i0)[nm]
            i1 = dict(inj); i1[pin] = np.full(n, 1e-6); V1 = sol(i1)[nm]
            Rth = np.maximum((V0 - V1) / 1e-6, 1.0)
            if pin == 9:    # the reference output pin: an upper diode to the rail only
                v, iu, idn = hard_clamp(V0, Rth, vdd, vd); idn = np.zeros(n)
            else:
                v, iu, idn = hard_clamp(V0, Rth, vdd, vd)
            inj[pin] = iu - idn; u[pin] = (v, iu, idn)
        vdd = (sum(u[p][1] for p in u) + extra_uA * 1e-6) * bleed
    nd = sol(inj)
    irail = sum(u[p][1] for p in u) + extra_uA * 1e-6
    return dict(rail_V=float(vdd.max()), i_rail_uA=float(irail.max() * 1e6), pinT=(float(nd["PIN"].min()), float(nd["PIN"].max())), pinB=(float(nd["P2"].min()), float(nd["P2"].max())),
                i_gnd_uA=float(sum(u[p][2] for p in u if p != 9).max() * 1e6))

def worst(d, V, bleed, extra_uA=0.0, vd=0.3):
    out = {}
    for w in (None, d["wire"]):
        for rs in ("zero", "open", "clamp", "open_nl", "clamp_nl"):
            out[(w or "off", rs)] = forced(d, V, w, rs, vd=vd, bleed=bleed, extra_uA=extra_uA)
    key = max(out, key=lambda k: out[k]["rail_V"])
    return out, key, out[key]

def scope12(bleed, ref_state="clamp", vd=0.3, n=2000, seed=5, v=12.0):
    """both scope inputs at +v, AFE unpowered: IN -R1 770k- N, N -R2 800k- GND, N -R3 330k- REF node, N -Rnp 680- the TPH2502 input, whose ESD diode (onset vd) goes to its V+ pin = the
    +3V3A rail through R71 1R.  REF node: ladder 1.44k to GND, and in 'clamp' a diode to the rail.  The rail voltage solves vdd = I(vdd) x bleed by bisection (I falls as vdd rises)."""
    rng = np.random.default_rng(seed); U = lambda w, s=None: rng.uniform(-w, w, s)
    R1 = 770e3 * (1 + U(0.01, (n, 2))); R2 = 800e3 * (1 + U(0.01, (n, 2))); R3 = 330e3 * (1 + U(0.01, (n, 2))); Rnp = 680.0
    ladder = 1440.0 * (1 + U(0.01, n))
    def irail(vdd):
        vref = np.zeros(n); itot = 0
        for _p in range(8):
            tot = 0; itot = 0
            for c in range(2):
                gth = 1 / R1[:, c] + 1 / R2[:, c] + 1 / R3[:, c]
                Vth = (v / R1[:, c] + vref / R3[:, c]) / gth; Rth = 1 / gth + Rnp
                vp, iu, idn = hard_clamp(Vth, Rth, vdd, vd)
                vn = Vth - iu / gth
                tot = tot + (vn - vref) / R3[:, c]; itot = itot + iu
            vref = tot * ladder
            if ref_state == "clamp":
                vc, iuc, _ = hard_clamp(vref, ladder, vdd, vd); vref = vc
        return itot + (iuc if ref_state == "clamp" else 0)
    lo = np.zeros(n); hi = np.full(n, 3.0)
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        up = irail(mid) * bleed > mid
        lo = np.where(up, mid, lo); hi = np.where(up, hi, mid)
    vdd = 0.5 * (lo + hi)
    return dict(rail_V=float(vdd.max()), i_rail_uA=float(irail(vdd).max() * 1e6))
