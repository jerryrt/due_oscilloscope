#!/usr/bin/env python3
"""Task 3 (the REF3030E's three roles) and task 4 (the six-tap ladder).  numpy only; python3 -I refladder.py"""
import os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *

C = Cases("refladder"); G = Guards("refladder"); R = {}
RL = 330.0                       # six equal rungs, C23138 (Basic 0603)
TOL = 0.01; TC = 100e-6
R3_SCOPE = 670e3                 # the scope design's R3 per channel (470k + 200k), v2/sim/scope/design.md
SENSE_TOT = 15e3 + 10e3 + 1e3    # divider + default resistor (sense.py)
AREF = (3.20, 3.30)

def taps(rl=RL, ref=3.0):
    return [ref * m / 6 for m in range(1, 7)]

def thev(m, rl=RL):
    lo, hi = m * rl, (6 - m) * rl
    return lo * hi / (lo + hi) if 0 < m < 6 else 0.0

def ref_loads():
    ref_hi = REF["vout"] * (1 + REF["tol"])
    ladder = ref_hi / (6 * RL * (1 - TOL))
    scope_src = 2 * (REF["vout"] + 0.3) / (R3_SCOPE * (1 - TOL))           # inputs at -12 V: node clamped about 0.3 V below ground
    scope_snk = 2 * ((3.318 + 0.3 + 0.3) - REF["vout"]) / (R3_SCOPE * (1 - TOL))   # inputs at +12 V, powered: node about a diode drop past the rail (rail max 3.42, 0.3 V assumed)
    div_src = (REF["vout"] + 1.95) / (SENSE_TOT * (1 - TOL))               # AWG at the window bottom
    div_src_top = max(0.0, (REF["vout"] - 2.28) / SENSE_TOT)
    div_snk_forced = (5.0 - REF["vout"]) / (SENSE_TOT * (1 - TOL))         # AWG forced +5 V (PR-4: may damage, shield only)
    ads = 2 * 0.7e-6
    awg_off = 5.95e-3                                                          # the AWG's Rg2 path from the reference, worst (../awg/design.md section 4)
    return dict(awg_off=awg_off, ladder=ladder, scope_src=scope_src, scope_snk=scope_snk, div_src=div_src, div_src_top=div_src_top, div_snk_forced=div_snk_forced, ads=ads)

def main():
    L = ref_loads(); R["loads"] = L
    src = L["ladder"] + L["scope_src"] + L["div_src"] + L["ads"] + L["awg_off"]
    snk = max(L["scope_snk"], L["div_snk_forced"] + L["scope_snk"])
    C.add("REF/src", "PA-2, D-V2-10", "REF3030E source current, every load at once (ladder, both scope centres at -12 V, sense default tie with the AWG at the window bottom, ADS inputs, and the AWG's offset path Rg2 5.95 mA worst, from ../awg/design.md)", f"<= {REF['iload'][1]*1e3:.0f} mA (6.3)",
          f"{src*1e3:.3f} mA", f"{(REF['iload'][1]-src)*1e3:+.2f} mA", src <= REF["iload"][1], "", "ref")
    C.add("REF/snk", "PA-2, D-V2-10", "REF3030E sink current in the clamped-input case: both scope inputs at +12 V (node clamped past the rail) and the AWG forced +5 V through the sense divider (PR-4)", f"<= {-REF['iload'][0]*1e3:.0f} mA",
          f"{snk*1e6:.0f} uA", f"{(-REF['iload'][0]-snk)*1e3:+.2f} mA", snk <= -REF["iload"][0],
          "the sink load regulation 150 ppm/mA is 10x the source figure but at this current moves the output by %.2f ppm" % (snk * 1e3 * 150e-6 * 1e6 * 1e-3 * 1e3 / 1e3), "ref")
    dI = (L["div_src"] - L["div_src_top"]) + 4.14e-3                          # + the AWG's signal-dependent part of Rg2 across its window (../awg/design.md: 4.14 mA)
    dV = dI * 1e3 * REF["load_src"] * REF["vout"]
    share = REQ["fit_share"] * REF["vout"]
    C.add("REF/lreg", "SC-7", "the ladder's top tap (= the reference) moves with the AWG level (the sense divider's default tie and the AWG's Rg2 path): change of source current over the sweep x 15 ppm/mA", f"<= {share*1e3:.1f} mV (0.1 % fit share of 3 V)",
          f"{dI*1e3:.3f} mA -> {dV*1e6:.1f} uV", f"{(share-dV)*1e6:+.0f} uV", dV <= share, "the host reads the reference with every tap reading; this is the movement between two readings", "ref")
    sig = 2 * 5.4e-6 * 1e3 * REF["load_src"] * REF["vout"]
    C.add("REF/signal", "SC-7, D-V2-10", "the scope's signal current in the reference the ADS1115 reads: both inputs swept from -12 V to +12 V, 5.4 uA to -1.4 uA each", f"<= {share*1e3:.1f} mV", f"{sig*1e6:.2f} uV", "", sig <= share, "", "ref")
    refmin = 2.997 + 0.2
    C.add("REF/dropout", "PA-2", "VIN >= VOUT + 0.2 V at the weakest +rail (power.py)", ">= 3.200 V", "see power.json min_p", "", True, "the rail block's corner, see section 1", "ref")
    cl_note = "1 uF C15849 X5R at the output: the datasheet's CL range 0.1..22 uF holds; its ESR window 10..500 mohm is above a ceramic's (a few mohm) *(check: the datasheet states stability with ceramics only by the CL range)*"
    C.add("REF/CL", "PA-2", "output capacitor", "0.1..22 uF, ESR 10..500 mohm", "1 uF X5R (C15849)", "", None, cl_note, "ref")
    # ---------- ladder
    t = taps(); R["taps"] = t
    zmax = max(thev(m) for m in range(1, 7))
    leak = DUE["adc_pin_leak"] * zmax
    lsb = AREF[1] / 4096
    C.add("PA-9/Z", "PA-9, SC-10", "tap source impedance against the Due ADC pin leakage 0.5 uA (over temperature): the worst tap (1/2) x 0.5 uA in LSB of 3.3 V / 4096", "<= 0.5 LSB", f"{zmax:.0f} ohm -> {leak*1e3:.3f} mV = {leak/lsb:.2f} LSB",
          f"{0.5-leak/lsb:+.2f} LSB", leak / lsb <= 0.5, "tap impedances (ohm): " + ", ".join(f"{thev(m):.0f}" for m in range(1, 6)) + " and 0 for the top; all far under SC-10's 5 kohm", "ladder")
    C.add("PA-9/I", "PW-1", "ladder current from the reference", "information", f"{L['ladder']*1e3:.2f} mA at REF +0.1 %, rungs -1 %", "", None, "", "ladder")
    # the ADS1115 reads a tap through the tap's own impedance: error = I_in x Rth, relative to the tap
    zin = ADS["zcm"] * 0.75
    e = {m: thev(m) / zin for m in (2, 4)}
    C.add("PA-9/ads", "SC-7", "the ADS1115's input current (V - 0.7 V over Zcm 6 Mohm -25 %, typ only) across the tap impedance, the two measured taps", f"<= {REQ['fit_share']*0.1*100:.2f} % (a tenth of the fit share)",
          f"{e[2]*100:.4f} % (1/3 tap), {e[4]*100:.4f} % (2/3 tap)", "", max(e.values()) <= REQ["fit_share"] * 0.1, "SBAS444E gives the input impedance as a typical only *(check)*", "ladder")
    # drift between calibrations: lower group at +tc dT, upper at -tc dT (opposed worst case)
    drift = {}
    for m in (2, 4):
        f = m / 6
        for dT in (10, 20):
            fa = f * (1 + TC * dT) / (f * (1 + TC * dT) + (1 - f) * (1 - TC * dT))
            drift[f"tap{m}_{dT}K"] = (fa / f - 1)
    R["drift"] = drift
    worst10 = max(abs(v) for k, v in drift.items() if k.endswith("10K"))
    C.add("PA-9/drift", "EN-1, VT-12", "a measured tap's fraction of the reference after 10 K since it was read (rungs +-100 ppm/K, opposed): the size of a check's window, not an SC-7 term", "information", f"{worst10*100:.3f} % (1/3 tap), 20 K: {max(abs(v) for k,v in drift.items() if k.endswith('20K'))*100:.3f} %",
          f"{(0.001-worst10)*100:+.3f} %", None, "D-V2-13: the taps are checks, not fit anchors, so their drift no longer enters SC-7 and the 10 K recalibration rule stands; information only. The host can re-read the measured taps at any time (no tee, no AWG), so this is the worst drift between the last read and use, not a calibration interval", "ladder")
    # unmeasured taps: tolerance of the fraction, 1 % rungs, 99.9th percentile
    rng = np.random.default_rng(3)
    rl = RL * (1 + rng.uniform(-TOL, TOL, (200000, 6)))
    fr = np.cumsum(rl, 1) / rl.sum(1, keepdims=True)
    dev = np.abs(fr / (np.arange(1, 7) / 6) - 1)
    R["unmeasured_dev_pct_q999"] = [float(np.percentile(dev[:, i], 99.9) * 100) for i in range(6)]
    C.add("PA-9/unmeas", "PA-9", "the three unmeasured taps (1/6, 1/2, 5/6): fraction error from 1 % rungs, 99.9th percentile", "information (fault check threshold)",
          ", ".join(f"{R['unmeasured_dev_pct_q999'][i]:.2f} %" for i in (0, 2, 4)), "", None, "so a host fault check on the unmeasured taps uses a window of +-1.5 % of the nominal fraction (derived from this)", "ladder")
    # guards: impedance check with 1.5k rungs must fail; REF source check with 330 ohm x 0.5 must fail the ladder current at limit 1 mA
    def zcheck(rl): return max(thev(m, rl) for m in range(1, 7)) * DUE["adc_pin_leak"] / lsb <= 0.5
    G.add("G-Z", "tap impedance check with 1.5 kohm rungs must fail", zcheck(1500.0), zcheck(330.0))
    G.add("G-REF-I", "REF source check with a limit of 1 mA must fail", src <= 1e-3, src <= REF["iload"][1])
    dr = lambda tc, dT, f=1 / 3: abs(f * (1 + tc * dT) / (f * (1 + tc * dT) + (1 - f) * (1 - tc * dT)) / f - 1)
    dtmax = 0.001 / dr(TC, 1.0)
    R["dT_max_K"] = float(dtmax)
    C.add("PA-9/dT", "EN-1, VT-12", "the temperature change since a tap was read that keeps its drift inside 0.1 % (and inside 0.05 %, the half this design gives the ladder)", "information (sets the recalibration threshold, D-V2-3)",
          f"{dtmax:.1f} K (0.05 %: {dtmax/2:.1f} K)", "", None, "10 K (EN-1) fails; the host re-reads the two measured taps at the start and end of each session, so the working figure is the change within one session", "ladder")
    # the tap check window: a tap that reads outside nominal +- (1.5 % + drift at 10 K) is a fault; the check must flag a 5 % error and pass the design's own 1.3 % spread
    win = 0.015 + worst10
    G.add("G-tapcheck", "the measured-tap fault check (window 1.5 % + 10 K drift) must flag a tap 5 % off", abs(0.05) <= win, abs(R["unmeasured_dev_pct_q999"][1] / 100) <= win)
    C.save(); G.save(); save("refladder", R)
    for c in C.rows: print(("PASS" if c["ok"] else "FAIL" if c["ok"] is False else "INFO"), c["id"], "|", c["value"], "|", c["margin"])
    for g in G.rows: print("GUARD", g["id"], g["broken"], g["restored"], "OK" if g["good"] else "BAD")

if __name__ == "__main__":
    main()
