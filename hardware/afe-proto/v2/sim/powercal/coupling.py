#!/usr/bin/env python3
"""SC-9 through the shared supply (VT-20), PW-2 ripple, PW-7 start-up.  Reads lm_results.json (this block's LM27762 runs) where a run
converged, and version 1's whatif/lm27762/results.json otherwise, saying which.   python3 -I coupling.py"""
import json, os, sys, math
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *
import power

C = Cases("coupling"); G = Guards("coupling"); R = {}
AREF = 3.27; A_SC = 0.4622
LSB_IN = AREF / 4096 / A_SC               # V at the scope input per Due code
R_PLANE = 10e-3                           # ohm, the return path the AWG's load current shares with a scope input's reference: ASSUMPTION *(check, LR-1, VT-20)*
R_SENSE_FEED = 1.0 + 0.2                  # the 1 ohm sense resistor in the 5 V feed plus the Due's path (architecture.md), assumed

def psrr_lin(f):
    """TPH2502: 80 dB min at DC (datasheet); NO frequency curve is given.  Assumed: flat to 10 kHz, then -20 dB/decade *(check)*."""
    return 10 ** (-80 / 20) * max(1.0, f / 1e4)

def lm_runs():
    own = os.path.join(HERE, "lm_results.json")
    v1 = os.path.join(AFE, "whatif", "lm27762", "results.json")
    a = json.load(open(own)) if os.path.exists(own) else {}
    b = json.load(open(v1)) if os.path.exists(v1) else {}
    return {k: v for k, v in a.items() if v.get("ok")}, {k: v for k, v in b.items() if v.get("ok")}

def main():
    v, _ = power.awg_values()
    rc = power.rail_corners()
    bt = power.budget(rc["nom_p"], v, 50.0, 2.0, TPH["iq_max"]); bb = power.budget(rc["nom_p"], v, 50.0, -1.9, TPH["iq_max"])
    dIp = bt["Ip"] - bb["Ip"]; dIn = bt["In"] - bb["In"]; dIin = bt["Iin"] - bb["Iin"]
    R.update(dIp_mA=dIp * 1e3, dIn_mA=dIn * 1e3, dIin_mA=dIin * 1e3)
    terms = []
    dVp = abs(dIp) * 1e3 * LM["load_reg_p"]
    terms.append(("the +3.3 V rail's load regulation (11 uV/mA) x the AWG's current swing %.1f mA = %.0f uV on the rail, through the scope dual's DC PSRR (80 dB min)" % (dIp * 1e3, dVp * 1e6), dVp * 1e-4))
    dVin = abs(dIin) * R_SENSE_FEED
    terms.append(("the 5 V feed: current swing %.1f mA x %.1f ohm = %.1f mV at VIN, x LDO line regulation 1.9 mV/V, x PSRR" % (dIin * 1e3, R_SENSE_FEED, dVin * 1e3), dVin * LM["line_reg_p"] * 1e-4))
    import refladder
    dIref = 0.165e-3 + refladder.ref_loads()["awg_swing"]                                   # the sense tie plus the AWG's Rg2 path (its offset comes from the reference: ../awg/design.md)
    dVref = dIref * 1e3 * REF["load_src"] * REF["vout"]
    terms.append(("the REF3030E: the sense tie and the AWG's own Rg2 path change its load by %.3f mA over the AWG sweep (15 ppm/mA = %.1f uV), to the scope's centre through Rp/R3 = 0.3725 and 1/a" % (dIref * 1e3, dVref * 1e6), dVref * 0.3725 / A_SC))
    iawg = max(abs(bt["state"]["i_load"]), abs(bb["state"]["i_load"]))
    terms.append(("the shared return: AWG load current %.1f mA x an ASSUMED %.0f mohm of plane shared with a scope input's reference (LR-1) *(check)*" % (iawg * 1e3, R_PLANE * 1e3), iawg * R_PLANE))
    rows = []
    tot = 0.0
    for nm, vv in terms:
        lsb = vv / LSB_IN
        rows.append((nm, vv, lsb)); tot += lsb
    R["dc_terms"] = rows; R["dc_total_lsb"] = tot
    C.add("SC-9/DC", "V2-1, SC-9, VT-20", "AWG stepped between its window ends into 50 ohm: change of a scope reading, settled, the four paths by which a scope on +3.3 V alone still hears the AWG (sum, 1 LSB = %.2f mV at the input)" % (LSB_IN * 1e3),
          "<= 2 LSB", f"{tot:.3f} LSB (largest: the assumed plane return, {rows[3][2]:.3f} LSB)", f"{2-tot:+.2f} LSB", tot <= 2.0,
          "the scope is on +3.3 V only (its V- is ground), so the negative rail reaches it only through the shared LM27762: the 5 V feed and the +LDO's line regulation; the paths are the +rail's load regulation, the feed, the shared reference, and the shared return", "sc9")
    lm_own, lm_v1 = lm_runs()
    src = "this block's LM27762 runs" if lm_own else "version 1's LM27762 runs (whatif/lm27762: its own loads, 3.33 V / -2.07 V rails), because none of this block's converged"
    # AC: step droop and ripple, scaled by the PSRR shape
    st = {k: v for k, v in lm_own.items() if k.startswith("step")}
    if st:
        k, e = next(iter(st.items()))
        d0 = e.get("step0_outp", {}); droop = max(abs(d0.get("droop_mV", 0)), abs(d0.get("over_mV", 0))) * 1e-3
        stat = d0.get("static_mV", 0) * 1e-3
        R["step"] = dict(run=k, **d0)
        ac = droop * psrr_lin(2e5)
        C.add("SC-9/AC", "SC-9", "the AWG's %.0f mA step on OUT+ (%s): peak rail movement %.2f mV, static %.2f mV (the model has no LDO loop: its droop is the capacitors' alone), through an assumed PSRR 80 dB flat to 10 kHz then -20 dB/dec at 200 kHz" % (dIp * 1e3, k, droop * 1e3, stat * 1e3),
              "<= 2 LSB", f"{ac/LSB_IN:.4f} LSB", "", ac / LSB_IN <= 2.0, "settled in microseconds, so a mean of 1024 samples sees only the static term", "sc9")
    else:
        # capacitor droop, hand figure: dI x (ESR + dt / C): 2 x 10 uF at -50 % bias, 4 mohm, 1 us LDO response
        c_eff = 2 * 10e-6 * 0.5; dv = abs(dIp) * (4e-3 + 1e-6 / c_eff)
        ac = dv * psrr_lin(2e5)
        R["step"] = dict(run="hand estimate", droop_mV=dv * 1e3)
        C.add("SC-9/AC", "SC-9", "the AWG's %.0f mA step on OUT+: peak rail movement by hand (2 x 10 uF at 50 %% of nominal, 4 mohm ESR, a 1 us LDO response) = %.2f mV, through an assumed PSRR 80 dB flat to 10 kHz then -20 dB/dec at 200 kHz" % (dIp * 1e3, dv * 1e3),
              "<= 2 LSB", f"{ac/LSB_IN:.4f} LSB", "", ac / LSB_IN <= 2.0, "no converged LM27762 step run: hand estimate *(check)*", "sc9")
    # ripple at the + rail
    rips = {k: v for k, v in (lm_own or lm_v1).items() if k.startswith(("rip", "su", "fly", "step")) and "outp_pp" in v}
    pp = max(v["outp_pp"] for v in rips.values()) if rips else None
    if pp is not None:
        rip_pin = pp * psrr_lin(2e6)
        R["ripple_pp_mV"] = pp * 1e3
        sc6 = REQ["sc6_mv"] * 1e-3
        C.add("PW-2/ripple", "PW-2, SC-6", "ripple at the +3.3 V rail from %s (largest peak-to-peak %.2f mV), through the assumed PSRR at 2 MHz (-34 dB), at the scope's pin" % (src, pp * 1e3),
              f"<= {sc6*1e3:.1f} mV rms (SC-6) and the rail <= 20 mV (PW-2)", f"{rip_pin*1e6:.1f} uV pk-pk at the pin, {pp*1e3:.2f} mV at the rail", "", rip_pin <= sc6 and pp <= 0.02,
              "the model has no LDO loop and under-reads the datasheet (version 1's note); PW-2's 20 mV holds by 30x, SC-6 by 15x on the model's figure *(check, VT-8)*", "pw2")
    fs = [v.get("outp_line_f") for v in rips.values() if v.get("outp_line_pk")]
    R["fsw_seen_Hz"] = fs
    C.add("PW-2/fsw", "PW-2", "switching frequency, the rule: not settable (LM27762 fSW 1.7 to 2.3 MHz, 2 MHz typ at VIN 3.6 V; pulse-skipping below that at light load, the loop 'can drop into the sub-2-kHz range when unloaded', 6.3.3)", "stated, with the wide path in mind",
          "line at 2 MHz +-15 %%, inside SM-3's 8 MHz band; residue at the pin %s" % ("%.1f uV" % (rip_pin * 1e6) if pp is not None else "not run"), "", None,
          "the AFE's idle load is never light: the AWG dual alone draws 15 mA on each rail, so the pump runs at constant frequency (a moving sub-2-MHz spur would need a load under a few mA) *(check at the PFM threshold: not given)*", "pw2")
    # PW-2 with and without the AWG's second (1 uF) supply-pin capacitor: the AWG stream's own figure is a factor 0.3 at the pin (its note in parts.csv); this block's ripple is at the rail
    if pp is not None:
        awg_pin_wo = pp  # no filter resistor in the AWG's supply branch (awg/parts.csv): the pin sees the rail
        for lab, f in (("with 100 nF + 1 uF at the pin", 0.3), ("with 100 nF only (1 uF dropped)", 1.0)):
            pk = pp * f; rms = pk / 2 / math.sqrt(2)
            via_psrr = rms * 2.65 * 2e6 / 120e6                   # the AWG stream's op-amp-like PSRR row: ripple x noise gain 2.65 / A(f), A = 120 MHz / f
            C.add("PW-2/AWG", "PW-2, AW-6 (D22: 0.3 mV)", "ripple at the AWG dual's supply pin %s: %.2f mV pk-pk on OUT+ (TI model) x %.1f; at the AWG output through the op-amp-like PSRR" % (lab, pp * 1e3, f), "<= 20 mV at the pin; <= 0.3 mV rms at the output (AW-6, D22)",
                  f"{pk*1e3:.2f} mV pk-pk at the pin, {via_psrr*1e6:.1f} uV rms at the output", f"{(0.3e-3-via_psrr)*1e6:+.0f} uV", pk <= 0.02 and via_psrr <= 0.3e-3, "the model under-reads: a factor 10 more still passes", "pw2")
    # start-up
    su = {k: v for k, v in (lm_own or lm_v1).items() if k.startswith("su") and v.get("outp_t90")}
    t90p = max(v["outp_t90"] for v in su.values()) if su else None
    t90n = max(v["outn_t90"] for v in su.values()) if su else None
    if t90p:
        t_ref = REF["turnon_s"]
        t_all = max(t90p, t90n) + t_ref
        R["startup"] = dict(t90p=t90p, t90n=t90n, t_ref=t_ref, t_all=t_all)
        C.add("PW-7", "PW-7", "rails up (%s: +rail 90 %% at %.2f ms, -rail %.2f ms) then the REF3030E's 2 ms to 0.1 %%, then the scope node's own RC (about 12 us)" % (src, t90p * 1e3, t90n * 1e3), "<= 15 s", f"{t_all*1e3:.1f} ms", "", t_all <= 15.0,
              "PW-7 is met by 3 orders of magnitude by the electrical start-up; what takes seconds is thermal (VT-18), not the rails. The host flags readings not ready until the ADS1115 sees the reference within 0.1 % of its first valid reading", "pw7")
    G.add("G-sc9", "the SC-9 DC sum with the plane return assumed 100 ohm instead of 10 mohm must fail", (tot - rows[3][2] + iawg * 100.0 / LSB_IN) <= 2.0, tot <= 2.0)
    G.add("G-pw7", "PW-7 check against a 1 ms limit must fail", (R.get("startup", {}).get("t_all", 0)) <= 1e-3 if "startup" in R else False, (R.get("startup", {}).get("t_all", 1e9)) <= 15.0 if "startup" in R else True)
    C.save(); G.save(); save("coupling", R)
    for c in C.rows: print(("PASS" if c["ok"] else "FAIL" if c["ok"] is False else "INFO"), c["id"], "|", c["value"], "|", c["margin"])
    for g in G.rows: print("GUARD", g["id"], g["broken"], g["restored"], "OK" if g["good"] else "BAD")

if __name__ == "__main__":
    main()
