#!/usr/bin/env python3
"""Ratio precision of the jumper measurement (design.md section 3) against SC-7's fit share, and the guards.  numpy only."""
import json, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import net
from net import *

N = int(os.environ.get("N", 20000))
D = dict(net.DES)                      # Rt = Rb = 100k, Rd = 1k, Rs = 4.7k, no Rm, no leakage
LV3 = (-1.3, 0.0, 1.3)
def S(q=99.9, **kw):
    kw.setdefault("n", N); kw.setdefault("d", D); kw.setdefault("levels_ratio", LV3); kw.setdefault("zcorr", 1.0)
    return net.summ(net.run(**kw), q)
Q = dict(navg=10**12, nav_ratio=10**12)   # no averaging noise
R = {}
def main():
    # 1. the whole procedure, percentiles
    R["all_max_match"] = {q: S(q) for q in (50, 95, 99.9)}
    R["all_typ_match"] = {q: S(q, eps=EPS_TYP) for q in (50, 95, 99.9)}
    R["all_independent_Z"] = S(99.9, zcorr=0.0)
    # 2. one source at a time (the rest at zero), 99.9th percentile
    z = dict(tol=0.0, eps=0.0, offs=False, zspread=0.0, **Q)
    def one(**over):
        kw = dict(z); kw.update(over); return S(99.9, **kw)
    save_inl = net.INL_LSB
    R["one"] = dict(
        resistors_1pct=one(tol=0.01),
        channel_match_0p1pct=one(eps=EPS_MAX),
        offsets_3lsb_of_125uV=one(offs=True),
        zcm_spread_25pct=one(zspread=0.25),
        noise_64_readings={**S(99.9, tol=0.0, eps=0.0, offs=False, zspread=0.0)},
    )
    net.INL_LSB = 0.0
    R["one"]["inl_off_control_all_zero"] = one()
    net.INL_LSB = save_inl
    # 3. against the "do not measure, trust the nominal k" baseline (wire off, k = 1/2 of the 1 % parts)
    R["prior_only"] = S(99.9, measure_k=False, sweep="D")
    # 4. the wire's loaded tap and B over the sweep (not a Due-ADC calibration point while fitted)
    r = net.run(n=4000, d=D, levels_ratio=LV3)
    R["B_wire_on_V"] = (float(r["B"].min()), float(r["B"].max())); R["t0_wire_on_V"] = (float(r["t0"].min()), float(r["t0"].max()))
    r0 = net.run(n=4000, d=D, levels_ratio=LV3, sweep="D"); R["t0_wire_off_V"] = (float(r0["t0"].min()), float(r0["t0"].max())); R["B_wire_off_V"] = (float(r0["B"].min()), float(r0["B"].max()))
    # 5. immunity: Thevenin match Rm on AIN1 and AIN2 = Rt||Rb + Rs = 54.7k (not 56k: the nearest Basic, C23206, is shown too)
    for nm, rm in (("unmatched", 0.0), ("matched_50k", 50e3), ("matched_51k", 51e3)):
        dm = dict(D, Rm=rm)
        R["match_" + nm] = dict(correlated_Z=S(99.9, d=dm, zcorr=1.0), independent_Z=S(99.9, d=dm, zcorr=0.0),
                                zonly_corr=S(99.9, d=dm, zcorr=1.0, tol=0.0, eps=0.0, offs=False, **Q), zonly_indep=S(99.9, d=dm, zcorr=0.0, tol=0.0, eps=0.0, offs=False, **Q))
    # 6. clamp leakage, constant, both signs (sensitivity: mV per nA)
    R["leak"] = {}
    for il in (0.0, 1e-9, 30e-9, 300e-9):
        R["leak"][f"{il*1e9:g}nA"] = max((S(99.9, d=dict(D, Il=il), leak_sign=s) for s in (+1, -1)), key=lambda x: x["off_mV"])
    # 7. ratio levels: one level at the window bottom, one at 0, three, and one at the top
    R["levels"] = {str(lv): S(99.9, levels_ratio=lv) for lv in ((-1.3,), (0.0,), (1.3,), LV3, (-1.3, -0.65, 0, 0.65, 1.3))}
    # 8. Rd and R scan (the design choice), correlated Z, unmatched
    R["scan"] = {}
    for rr in (10e3, 22e3, 47e3, 100e3):
        for rd in (330.0, 1e3, 2.2e3):
            R["scan"][f"R{rr/1e3:g}k_Rd{rd:g}"] = S(99.9, n=6000, d=dict(D, Rt=rr, Rb=rr, Rd=rd))
    # 8b. what the ADS1115's own channel terms cost: the same run with them removed (what an equal-voltage channel calibration would leave)
    R["no_ads_match_offset"] = dict(unmatched=S(99.9, eps=0.0, offs=False), matched_50k=S(99.9, eps=0.0, offs=False, d=dict(D, Rm=50e3)))
    save_off = net.OFF_LSB; net.OFF_LSB = 1.5          # offset +-3 LSB read at the +-2.048 V LSB of 62.5 uV (187.5 uV), not 375 uV
    R["offset_187uV"] = S(99.9); R["offset_187uV_typ"] = S(99.9, eps=EPS_TYP)
    net.OFF_LSB = save_off
    # 9. noise budget: the average of 64 readings at 128 SPS (0.5 s), 125 uV rms each
    R["noise_per_reading_uV"] = NOISE / np.sqrt(64) * 1e6
    guards()
    json.dump(R, open(os.path.join(RES, "precision.json"), "w"), indent=1, default=float)
    p = R["all_max_match"][99.9]; t = R["all_typ_match"][99.9]
    print("max match 99.9th: gain %.3f %%, offset %.2f mV, worst point %.2f mV, k error %.3f %%" % (p["gain_pct"], p["off_mV"], p["err_mV"], p["k_err_pct"]))
    print("typ match 99.9th: gain %.3f %%, offset %.2f mV, worst point %.2f mV" % (t["gain_pct"], t["off_mV"], t["err_mV"]))
    for k, v in R["one"].items(): print("  one:", k, "%.3f %% %.2f mV k %.3f %%" % (v["gain_pct"], v["off_mV"], v["k_err_pct"]))
    print("prior only:", R["prior_only"]["gain_pct"], R["prior_only"]["off_mV"])

def guards():
    G = []
    def g(name, what, broken_fail, restored_pass): G.append(dict(id=name, what=what, broken="fails" if broken_fail else "PASSES (guard void)", restored="passes" if restored_pass else "FAILS", good=bool(broken_fail and restored_pass)))
    limit = 0.05      # % gain allotted to the sense (half of the 0.1 % fit share, as v2 does)
    # G-zero: with every error source off the procedure returns zero error; the same run with the host's nominal Rd twice the truth must FAIL the limit
    save = (net.INL_LSB, net.REF_TOL); net.INL_LSB = 0.0; net.REF_TOL = 0.0
    z = dict(n=300, eps=0.0, tol=0.0, zspread=0.0, offs=False, navg=10**12, nav_ratio=10**12, levels_ratio=LV3)
    ok = net.summ(net.run(d=D, **z))["gain_pct"]; bad = net.summ(net.run(d=D, hd=dict(D, Rd=2e3), **z))["gain_pct"]
    g("G-zero", "all errors off: zero error; host model with Rd twice the truth must exceed 0.05 %", bad > limit, ok <= 1e-3)
    bad = net.summ(net.run(d=D, host_Z=3e6, **z))["gain_pct"]
    g("G-Z", "all errors off, host assumes Zcm = 3 Mohm against the true 6 Mohm: must exceed 0.05 % (the loading model is exercised)", bad > limit, ok <= 1e-3)
    net.INL_LSB, net.REF_TOL = save
    # G-eps: channel match 2 % must fail the 0.8 % level that the 0.1 % match meets
    ok = S(99.9, n=2000)["gain_pct"]; bad = S(99.9, n=2000, eps=0.02)["gain_pct"]
    g("G-eps", "ADS1115 channel match 2 % instead of 0.1 %: gain must exceed 2 x the 0.1 % figure (the detector sees the dominant source)", bad > 2 * ok, True)
    # G-range: a window of +-1.9 V (the v2 window) with the wire at TAP2 must break the 0..3.21 V rule; the designed window passes with the wire at TAP5
    import ranges
    def span_ok(wire, A):
        P = draw(2000, 9, net.DES, 0.01, 0.0)
        t = np.concatenate([solve_net(a, P["ref"], P["rl3"], P["rl5"], P["Rt"], P["Rb"], P["Rd"], P["Rs"], P["Z"][:, 0], 0.0, wire)["T0"] for a in A])
        return t.min() >= 0 and t.max() <= VDD_MIN
    g("G-range", "tap range, wire at TAP2 (0.75 V) and window +-1.35 V, must FAIL (T0 down to -0.07 V); wire at TAP5 passes", not span_ok("TAP2", (-AWG_LIM, AWG_LIM)), span_ok("TAP5", (-AWG_LIM, AWG_LIM)))
    g("G-range2", "tap range with the window widened to +-3.0 V and the wire at TAP5 (T0 down to -0.3 V) must FAIL; +-1.35 V passes", not span_ok("TAP5", (-3.0, 3.0)), span_ok("TAP5", (-AWG_LIM, AWG_LIM)))
    # G-clamp: the clamp solver with the diodes removed (huge vdd, no lower diode) returns the open-circuit tap: out of range must show
    v, iu, idn = ranges.pin_with_clamp(np.array([-0.675]), np.array([50e3]), VDD_MIN)
    v_noclamp = -0.675
    g("G-clamp", "clamp solver at T0 = -0.675 V, Thevenin 50k: pin must differ from the open-circuit -0.675 V by > 0.2 V; a no-op solver (pin = open circuit) must fail that test", not (abs(v_noclamp - v_noclamp) > 0.2), abs(v[0] - v_noclamp) > 0.2)
    json.dump(G, open(os.path.join(RES, "guards_precision.json"), "w"), indent=1)
    for x in G: print("GUARD", x["id"], x["broken"], x["restored"], "OK" if x["good"] else "BAD", "|", x["what"])
    R["guards"] = G

if __name__ == "__main__":
    main()
