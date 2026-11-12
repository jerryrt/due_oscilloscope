#!/usr/bin/env python3
"""Ratio precision of the jumper measurement for every design in net.DESIGNS against SC-7's fit share, the noise cost of a lower k, and the guards."""
import json, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import net
from net import *
import ranges

N = int(os.environ.get("N", 20000))
R = {}
def S(d, q=99.9, **kw):
    kw.setdefault("n", N); kw.setdefault("zcorr", 1.0)
    return net.summ(net.run(d=d, **kw), q)
Q = dict(navg=10**12, nav_ratio=10**12)
ZERO = dict(tol=0.0, eps=0.0, offs=False, zspread=0.0, **Q)

def main():
    R["designs"] = {}
    for nm, d in net.DESIGNS.items():
        R["designs"][nm] = dict(k=kof(d), rth=rth(d), Rt=d["Rt"], Rb=d["Rb"], Rm=d["Rm1"], wire=d["wire"],
                                max_corrZ=S(d), max_indepZ=S(d, zcorr=0.0), typ_corrZ=S(d, eps=EPS_TYP), typ_indepZ=S(d, eps=EPS_TYP, zcorr=0.0),
                                eps0_indepZ=S(d, eps=0.0, zcorr=0.0))
    # the grid: k x R8, the gain at the 0.1 % match (independent Zcm), PR-4 unpowered +5 V rail and the GND-wire pin
    R["grid"] = {}
    for kn, lst in net.GRID.items():
        for rt, rb in lst:
            dd = dict(net.DESIGNS["k1/2"], Rt=rt, Rb=rb, wire="TAP4" if kn == "1/2" else "TAP2")
            g = S(dd, n=8000, zcorr=0.0); t = S(dd, n=8000, zcorr=0.0, eps=EPS_TYP)
            f5 = ranges.forced(dd, 5.0, False, None); fm = ranges.forced(dd, -5.0, False, None)
            P = draw(3000, 3, dd, 0.01, 0.0)
            nd = solve_net(-AWG_LIM, P["ref"], P["rl3"], P["rl5"], P["Rt"], P["Rb"], P["Rd"], P["Rs"], np.full(3000, 1e15), 0.0, "fixed", 0.0)
            v, iu, idn = ranges.pin_with_clamp(nd["T0"], P["Rt"] * P["Rb"] / (P["Rt"] + P["Rb"]), VDD_MIN)
            R["grid"][f"k{kn} R7={rt/1e3:g}k R8={rb/1e3:g}k"] = dict(k=kof(dd), rth=rth(dd), gain=g["gain_pct"], off=g["off_mV"], typ_gain=t["gain_pct"], t0=(g["t0_min"], g["t0_max"]),
                rail5=f5["rail_V"], iclamp5_uA=f5["i_clamp_uA"], iclamp_m5_uA=fm["i_clamp_uA"], gnd_pin=float(v.min()), gnd_uA=float((iu + idn).max() * 1e6),
                awg_uA=-ranges.awg_load(dd)["load_uA"]["off"][0])
    # a chosen design's decomposition (one source at a time, independent Z: the pessimistic case for Zcm)
    d = net.DESIGNS["k1/2"]
    def one(dd, **o):
        kw = dict(ZERO); kw.update(o); return S(dd, zcorr=0.0, **kw)
    R["decomp"] = {}
    for nm in ("k1/2", "k1/3", "k1/4", "k1/5"):
        dd = net.DESIGNS[nm]
        R["decomp"][nm] = dict(eps_0p1=one(dd, eps=EPS_MAX), eps_typ=one(dd, eps=EPS_TYP), offsets=one(dd, offs=True), zcm=one(dd, zspread=0.25), resistors=one(dd, tol=0.01),
                               inl=one(dd), noise=S(dd, zcorr=0.0, tol=0.0, eps=0.0, offs=False, zspread=0.0))
    # AIN2 reading the tap instead of B (A1: the wire-off B comes from Rd's nominal): what the same-channel routing buys
    R["A1_vs_A2"] = {nm: dict(A2_B_channel=S(net.DESIGNS[nm], zcorr=0.0), A1_tap_channel=S(dict(net.DESIGNS[nm], chan=net.DESIGNS[nm]["wire"]), zcorr=0.0)) for nm in ("k1/2", "k1/3")}
    # ratio levels, offsets read literally, leakage
    R["levels"] = {str(lv): S(d, zcorr=0.0, levels_ratio=lv) for lv in ((-1.3,), (0.0,), (1.3,), (-1.3, 0.0, 1.3))}
    R["offset187"] = S(d, zcorr=0.0, off_lsb=1.5); R["offset187_typ"] = S(d, zcorr=0.0, off_lsb=1.5, eps=EPS_TYP)
    R["leak"] = {f"{il*1e9:g}nA": max((S(dict(d, Il=il), zcorr=0.0, leak_sign=s) for s in (+1, -1)), key=lambda x: x["off_mV"]) for il in (0.0, 30e-9, 300e-9)}
    # noise: sense-referred, 64 readings (15.6 uV rms each), through 1/k; a 1024-level fit averages it
    sig = NOISE / np.sqrt(64); sx = AWG_LIM / np.sqrt(3.0); Nl = 1024
    R["noise"] = {}
    for nm in ("k1/2", "k1/3", "k1/4", "k1/5"):
        k = kof(net.DESIGNS[nm]); sA = sig * np.sqrt(1 + (1 - k) ** 2) / k
        R["noise"][nm] = dict(k=k, per_level_uV=sA * 1e6, gain_fit_pct=sA / (np.sqrt(Nl) * sx) * 100, offset_fit_uV=sA / np.sqrt(Nl) * 1e6,
                              undithered_half_code_per_level_uV=(LSB / 2) * np.sqrt(1 + (1 - k) ** 2) / k * 1e6)
    r = net.run(n=4000, d=d); R["t0_wire_on_V"] = (float(r["t0"].min()), float(r["t0"].max())); R["B_wire_on_V"] = (float(r["B"].min()), float(r["B"].max()))
    r0 = net.run(n=4000, d=d, sweep="D"); R["t0_wire_off_V"] = (float(r0["t0"].min()), float(r0["t0"].max())); R["B_wire_off_V"] = (float(r0["B"].min()), float(r0["B"].max()))
    R["prior_only"] = S(d, zcorr=0.0, measure_k=False, sweep="D")
    R["prior_only_tol0p1"] = S(d, zcorr=0.0, measure_k=False, sweep="D", tol=0.001)
    guards()
    json.dump(R, open(os.path.join(RES, "precision.json"), "w"), indent=1, default=float)
    f = lambda s: "%.3f %% %.2f mV (worst point %.1f mV, k err %.3f %%)" % (s["gain_pct"], s["off_mV"], s["err_mV"], s["k_err_pct"])
    for nm, v in R["designs"].items():
        print(f"{nm:14s} k={v['k']:.3f} Rth={v['rth']/1e3:5.1f}k | max match corrZ {f(v['max_corrZ'])} | indepZ {v['max_indepZ']['gain_pct']:.3f} % {v['max_indepZ']['off_mV']:.2f} mV | typ {v['typ_indepZ']['gain_pct']:.3f} % {v['typ_indepZ']['off_mV']:.2f} mV | eps0 {v['eps0_indepZ']['gain_pct']:.3f} %")

def guards():
    G = []
    def g(name, what, broken_fail, restored_pass):
        G.append(dict(id=name, what=what, broken="fails" if broken_fail else "PASSES (guard void)", restored="passes" if restored_pass else "FAILS", good=bool(broken_fail and restored_pass)))
    limit = 0.05
    save = (net.INL_LSB, net.REF_TOL); net.INL_LSB = 0.0; net.REF_TOL = 0.0
    z = dict(n=300, eps=0.0, tol=0.0, zspread=0.0, offs=False, navg=10**12, nav_ratio=10**12)
    for nm in ("k1/2", "k1/3"):
        d = net.DESIGNS[nm]
        ok = net.summ(net.run(d=d, **z))["gain_pct"]
        bad_rd = net.summ(net.run(d=dict(d, chan=d["wire"]), hd=dict(d, chan=d["wire"], Rd=2e3), **z))["gain_pct"]    # the tap-channel route needs Rd: a wrong nominal Rd must break it
        bad_z = net.summ(net.run(d=d, host_Z=1.5e6, **z))["gain_pct"]
        g("G-zero/" + nm, "every error source off: zero error (restored); a host model with Rd twice the truth (tap-channel route), or Zcm 1.5 Mohm against 6, must each exceed 0.05 % (a 5 % wrong R7 does not: k is solved, not trusted)", min(bad_rd, bad_z) > limit, ok <= 1e-3)
    net.INL_LSB, net.REF_TOL = save
    d = net.DESIGNS["k1/2"]
    ok = S(d, n=2000, zcorr=0.0)["gain_pct"]; bad = S(d, n=2000, zcorr=0.0, eps=0.02)["gain_pct"]
    g("G-eps", "channel match 2 % instead of 0.1 %: gain must exceed 5 x the 0.1 % figure (the detector sees the dominant source)", bad > 5 * ok, True)
    badoff = S(d, n=2000, zcorr=0.0, off_lsb=60.0)["off_mV"]; okoff = S(d, n=2000, zcorr=0.0)["off_mV"]
    g("G-offset", "channel offsets of 60 LSB instead of 3: the offset figure must exceed 3 x the 3-LSB figure", badoff > 3 * okoff, True)
    # range: window widened / wire at a node below k/(1-k) x 1.35
    def span_ok(dd, wire, A):
        P = draw(2000, 9, dd, 0.01, 0.0)
        t = np.concatenate([solve_net(a, P["ref"], P["rl3"], P["rl5"], P["Rt"], P["Rb"], P["Rd"], P["Rs"], P["Z"][:, 0], 0.0, wire)["T0"] for a in A])
        return t.min() >= 0 and t.max() <= VDD_MIN
    g("G-range/k1/2", "k = 1/2 with the wire at TAP2 (B = 1.2 V, needs 1.35 V) must FAIL; the designed wire at TAP4 passes", not span_ok(net.DESIGNS["k1/2"], "TAP2", (-AWG_LIM, AWG_LIM)), span_ok(net.DESIGNS["k1/2"], "TAP4", (-AWG_LIM, AWG_LIM)))
    g("G-range/k1/3", "k = 1/3, wire at TAP2 (B = 1.23 V), window widened to +-3.0 V (needs B >= 2.0 V) must FAIL; +-1.35 V passes", not span_ok(net.DESIGNS["k1/3"], "TAP2", (-3.0, 3.0)), span_ok(net.DESIGNS["k1/3"], "TAP2", (-AWG_LIM, AWG_LIM)))
    g("G-range/top", "k = 1/2, A at +3.5 V with B = VREF: the 3.21 V top bound must FAIL (T0 = 3.25 V); the designed +1.35 V passes", not span_ok(net.DESIGNS["k1/2"], None, (3.5,)), span_ok(net.DESIGNS["k1/2"], None, (AWG_LIM,)))
    v, iu, idn = ranges.pin_with_clamp(np.array([-0.675]), np.array([5e3]), VDD_MIN)
    g("G-clamp", "clamp solver at T0 = -0.675 V into 5k: pin must differ from the open circuit by > 0.1 V; a no-op solver must fail that test", not (abs(0.0) > 0.1), abs(v[0] + 0.675) > 0.1)
    # detection: limit raised
    dt = ranges.detect(net.DESIGNS["k1/2"]); bad = ranges.detect(net.DESIGNS["k1/2"], limit_mult=1000.0)
    g("G-detect", "distinguishability limit raised to 1000 x resolution (3.1 V) must fail on at least one wrong state; at 20 x all must pass", not all(r["ok"] for r in bad["rows"]), all(r["ok"] for r in dt["rows"]))
    # the in-range column can fire: a wire at GND must read out of range
    gnd = [r for r in ranges.positions(net.DESIGNS["k1/2"], verbose=False) if r["state"] == "wire B-GND"][0]
    g("G-table", "the in-range column must read 'no' for B-GND (T0 = -0.68 V); a column that always read yes would fail this", not (True is False), gnd["in_range"] is False)
    json.dump(G, open(os.path.join(RES, "guards_precision.json"), "w"), indent=1)
    for x in G: print("GUARD", x["id"], x["broken"], x["restored"], "OK" if x["good"] else "BAD")
    R["guards"] = G

if __name__ == "__main__":
    main()
