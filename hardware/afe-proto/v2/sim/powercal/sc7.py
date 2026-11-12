#!/usr/bin/env python3
"""Task 6: the ADS1115 share of SC-7, and the extrapolation of the Due ADC's calibration over the top 1.3 to 1.5 V of the scope's range.

The AWG (window bottom -1.9 V, top 2.05 V nominal .. 2.23 V window end) covers 71 to 75 % of the scope's -1.5..+3.5 V.  The tee fit
(a straight line of Due code against AWG volts) is EXTRAPOLATED above the window.  Two estimators are compared:
  A  the tee fit alone, extrapolated;
  B  the Due ADC's own transfer curve first fitted (a quadratic) against ladder anchors: ground, the two measured taps (1/3 and 2/3
     of the reference) and the reference itself (the ladder's top tap), each as the ADS1115 reads it with its channel match and offset;
     the tee codes are then mapped to pin volts through that curve before the straight-line fit.
Truth: the Due ADC code is 4095 v / AREF plus an INL function (smooth cubic bow, parabolic bow, or random knots every 8 codes seen
through the converter's own 0.8-code noise), a channel offset between the scope pin and the ladder pin, the ladder pins' leakage;
the scope's pin voltage is linear in the input (the divider is resistive; its own nonlinearity is VT-23's).  numpy only."""
import os, sys, math
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *

C = Cases("sc7"); G = Guards("sc7"); R = {}
AREF = 3.27
A_SC, C0_SC = 0.4622, 1.1175            # scope: pin = C0 + A x Vin (v2/sim/scope/design.md)
FS = 4095.0
LO = -1.9
VEND = 3.5

def inl_fn(model, A, rng, L=8):
    if model == "cubic":
        sg = rng.choice((-1.0, 1.0)); kk = 1 / (2 / (3 * math.sqrt(3)))
        return lambda c: sg * A * kk * (((c - 2048) / 2048) ** 3 - (c - 2048) / 2048)
    if model == "parab":
        sg = rng.choice((-1.0, 1.0)); return lambda c: sg * A * (1 - ((c - 2048) / 2048) ** 2)
    nk = int(FS // L) + 3
    knots = rng.uniform(-A, A, nk); grid = np.arange(-8.0, FS + 8.0, 0.25)
    raw = np.interp(grid / L, np.arange(nk), knots)
    k = np.arange(-4.8, 4.8 + 1e-9, 0.25); w = np.exp(-0.5 * (k / 0.8) ** 2); w /= w.sum()
    sm = np.convolve(raw, w, mode="same")
    return lambda c: np.interp(c, grid, sm)

def run(model="cubic", A=1.2, npts=1024, top=2.2275, n=1500, seed=1, anchors=True, ch_off_lsb=0.5, eps=ADS["gain_ch_match"][1], ads_off_lsb=3.0, leak=True,
        quad=True, vend_list=(2.5, 3.0, 3.5)):
    rng = np.random.default_rng(seed)
    L = np.linspace(LO, top, npts)
    cpv = FS / AREF
    errA = {v: [] for v in vend_list}; errB = {v: [] for v in vend_list}
    for _ in range(n):
        f = inl_fn(model, A, rng)
        a_ = A_SC * (1 + rng.uniform(-0.02, 0.02)); c0 = C0_SC + rng.uniform(-0.03, 0.03)     # the scope's own map: unknown to the host
        g = 1 + rng.uniform(-0.0156, 0.0029); o = rng.uniform(-30, 56)                      # Due ADC gain / offset (codes), the board's: afe.md
        def code(v, extra=0.0):
            c = g * cpv * v + o + extra
            return c + f(c)
        cl = code(C0_SC * 0 + c0 + a_ * L, 0.0) + rng.normal(0, 0.8 / math.sqrt(1e5), npts)
        # ---- estimator A: straight line of code against L, extrapolated
        p = np.polyfit(L, cl, 1)
        vtrue = np.array(vend_list)
        ce = code(c0 + a_ * vtrue)
        for v, e in zip(vend_list, (ce - p[1]) / p[0] - vtrue): errA[v].append(e)
        # ---- estimator B: the ADC's transfer from the anchors
        if anchors:
            va = np.array([0.0, 1.0, 2.0, 3.0]) * (AREF * 0 + 1)
            ea = np.zeros(4)
            if leak: ea[1:] += -DUE["adc_pin_leak"] * np.array([440.0, 440.0, 0.0])[:3] * 0   # leakage appears in the Due code, not in the ADS reading (below)
            # the ADS1115's reading of the taps: channel match eps/2 each way, offset, relative to the reference (taps 1 and 2; the reference IS 3.0 V by definition)
            vm = va.copy()
            vm[1] = 1.0 * (1 + rng.uniform(-eps / 2, eps / 2)) + rng.uniform(-ads_off_lsb, ads_off_lsb) * ADS["lsb"]
            vm[2] = 2.0 * (1 + rng.uniform(-eps / 2, eps / 2)) + rng.uniform(-ads_off_lsb, ads_off_lsb) * ADS["lsb"]
            ca = np.array([code(v, ch_off_lsb * rng.uniform(-1, 1)) for v in va])
            if leak:
                ca[1:3] += DUE["adc_pin_leak"] * 440.0 * cpv          # the Due pin's leakage across the tap impedance (ADS does not see it)
                ca[3] += 0.0
            deg = 2 if quad else 1
            q = np.polyfit(vm, ca, deg)                                # code(v)
            vv = np.linspace(-0.2, 3.4, 4000); cc = np.polyval(q, vv)
            inv = lambda c: np.interp(c, cc, vv)
            vh = inv(cl)
            p2 = np.polyfit(L, vh, 1)
            ceB = ce
            for v, e in zip(vend_list, (inv(ceB) - p2[1]) / p2[0] - vtrue): errB[v].append(e)
    out = {}
    for v in vend_list:
        a_ = np.abs(errA[v]); b_ = np.abs(errB[v]) if anchors else None
        out[v] = dict(A_q999_mV=float(np.percentile(a_, 99.9) * 1e3), A_sd_mV=float(np.std(errA[v]) * 1e3),
                      B_q999_mV=float(np.percentile(b_, 99.9) * 1e3) if anchors else None)
    return out

LSB_IN_MV = AREF / 4096 / A_SC * 1e3

def main():
    share = lambda v: REQ["fit_share"] * v * 1e3        # mV: 0.1 % of the reading
    full = lambda v: REQ["sc7_pct"] / 100 * v * 1e3 + REQ["sc7_mv"]
    res = {}
    for top in (2.05, 2.2275):
        cover = (top - (-1.5)) / 5.0
        for model, A in (("cubic", 0.5), ("cubic", 1.2), ("parab", 1.2), ("knots", 1.2)):
            r = run(model=model, A=A, top=top, n=800)
            res[f"{top}/{model}/{A}"] = r
            rr = r[3.5]
            okA = rr["A_q999_mV"] <= share(3.5); okB = rr["B_q999_mV"] <= share(3.5)
            C.add("SC-7/ext", "SC-7, PA-3, VT-23", f"fit extrapolated to +3.5 V (AWG window {LO} .. {top} V covers {cover*100:.0f} % of the range), INL {model} {A} LSB, 1024 points: A = tee only, B = with ladder anchors, 99.9th pct",
                  f"<= {share(3.5):.1f} mV (0.1 % of 3.5 V)", f"A {rr['A_q999_mV']:.2f} mV ({rr['A_q999_mV']/3500*100:.3f} %), B {rr['B_q999_mV']:.2f} mV ({rr['B_q999_mV']/3500*100:.3f} %)",
                  f"A {share(3.5)-rr['A_q999_mV']:+.1f} / B {share(3.5)-rr['B_q999_mV']:+.1f} mV", okA, f"B {'passes' if okB else 'fails'} the share; against SC-7's whole 0.5 % + 5 mV = {full(3.5):.1f} mV both leave {full(3.5)-max(rr['A_q999_mV'], rr['B_q999_mV']):.1f} mV. One Due LSB is {LSB_IN_MV:.2f} mV at the input", "ext")
    R["ext"] = res
    # what the anchors buy: with ideal anchors (no channel match, no offset) and the quadratic
    ideal = run(model="cubic", A=1.2, top=2.2275, n=800, eps=0.0, ads_off_lsb=0.0, ch_off_lsb=0.0)
    R["ext_ideal_anchors"] = ideal
    C.add("SC-7/ext-ideal", "SC-7", "the same (cubic 1.2 LSB, top 2.2275 V) with perfect anchors (no ADS channel mismatch, no offset, no pin offset)", "information",
          f"A {ideal[3.5]['A_q999_mV']:.2f} mV, B {ideal[3.5]['B_q999_mV']:.2f} mV at +3.5 V", "", None, "what the ladder would buy if the ADS1115 read its taps exactly", "ext")
    # the sense-chain and reference terms (sense.json), in the SC-7 budget of this block
    import json
    sj = load("sense")
    s = sj["base"]
    refp = REF["tol"] * 100 + REF["tc_max"] * 10 * 100 + REF["hyst_ppm"][1] * 1e-4 + REF["lt_ppm"] * 1e-4     # %: initial + 15 ppm/K x 10 K + hysteresis + long term
    rows = [("REF3030E: initial 0.1 %, 15 ppm/K x 10 K, hysteresis 100 ppm, long-term 40 ppm", refp, 0.0),
            ("AWG sense chain (jumper ratio, ADS1115 at the max channel match, Rs, Zcm, 1 % resistors), 99.9th pct", s["gain_pct"], s["off_mV"]),
            ("Due-ADC fit extrapolated to +3.5 V (A, cubic 1.2 LSB, window top 2.2275)", res["2.2275/cubic/1.2"][3.5]["A_q999_mV"] / 3500 * 100, 0.0),
            ("ladder drift of a measured tap, 10 K since read", 0.133, 0.0)]
    tot_g = sum(r[1] for r in rows); rss = math.sqrt(sum(r[1] ** 2 for r in rows)); tot_o = sum(r[2] for r in rows)
    R["sum"] = dict(rows=rows, linear=tot_g, rss=rss, off=tot_o)
    C.add("SC-7/sum", "SC-7", "this block's gain terms alone, linear sum (RSS in the note), and its offset, against ±0.5 % of reading ± 5 mV",
          "<= 0.5 % and <= 5 mV for the WHOLE of SC-7 (the scope's own terms come on top)", f"{tot_g:.2f} % (RSS {rss:.2f} %), {tot_o:.1f} mV", f"{0.5-tot_g:+.2f} %", tot_g <= 0.5 and tot_o <= 5.0,
          "the sense chain's channel match, offsets and 1 % parts are the dominant term, see section 5", "sum")
    # ADS noise and averaging at the AWG node
    nav = 64
    nz = ADS["noise_rms"] / math.sqrt(nav) / 0.4 * 1e6
    C.add("SC-7/noise", "SC-7", "ADS1115 noise averaged over 64 conversions, referred to the AWG node through k = 0.4 (125 uV rms per reading, Table 6-1)", "<= 1 mV", f"{nz:.0f} uV rms", "", nz <= 1000, "the table's figure equals one LSB: the converter is quantisation-limited, so averaging reduces it only if the input noise dithers it; the worst case without dither is 0.5 LSB = %.0f uV at the node" % (0.5 * ADS["lsb"] / 0.4 * 1e6), "sum")
    # guards
    big = run(model="cubic", A=12.0, top=2.2275, n=200)
    G.add("G-ext", "the extrapolation check with an INL of 12 LSB must fail the 0.1 % share", big[3.5]["A_q999_mV"] <= share(3.5), res["2.2275/cubic/0.5"][3.5]["A_q999_mV"] <= share(3.5))
    G.add("G-sum", "the SC-7 sum check against a 1.0 % limit with the sense chain's error multiplied by 10 must fail (the real sum passes the same 1.0 %)", (tot_g + 9 * s["gain_pct"]) <= 1.0, tot_g <= 1.0)
    C.save(); G.save(); save("sc7", R)
    for c in C.rows: print(("PASS" if c["ok"] else "FAIL" if c["ok"] is False else "INFO"), c["id"], "|", c["value"], "|", c["margin"])
    for g in G.rows: print("GUARD", g["id"], g["broken"], g["restored"], "OK" if g["good"] else "BAD")

if __name__ == "__main__":
    main()
