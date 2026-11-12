#!/usr/bin/env python3
"""Task 1 (rails, PW-1, PW-2 arithmetic, PW-6, V2-2 supply rating) and task 2 (PR-3, the unpowered +3.3 V_A rail).

    python3 -I power.py          writes results/power.json, results/cases_power.json, results/guards_power.json

Everything is arithmetic on datasheet figures (common.py) and on the AWG's design values, which are READ from ../awg/design.py at run
time (the AWG is being redone by another agent: the file's sha256 is recorded in the results).  numpy only.
"""
import itertools, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *

C = Cases("power"); G = Guards("power"); R = {}

# ------------------------------------------------------------------------------------------------------------- design values
# LM27762 feedback (SNVSAF7C eq 1 and 3): VOUT+ = 1.2 (R1 + R2) / R2, VOUT- = -1.22 (R3 + R4) / R4; R2 and R4 (to ground) >= 50 kohm.
FB = dict(R1=(120e3,), R2=(68e3,), R3=(56e3, 8.2e3), R4=(100e3,))      # R3 two parts in series, the others one part
FB_LCSC = {120e3: "C25808", 68e3: "C23231", 56e3: "C23206", 8.2e3: "C25981", 100e3: "C25803"}
TOL_R = 0.01                      # V2-3: Basic 1 %
TC_R = 100e-6                     # jlc-basic.csv: +-100 ppm/K for the 0603 values used
DT = 10.0                         # EN-1: 15..35 C is +-10 K about the 25 C at which the 1 % holds
REG_ALLOW = 2.5e-3                # line + load regulation allowance on top of VFB's over-temperature limits (1.9 mV/V x 0.75 V (4.5 to 5.25 V at the 5V pin, PW-6) + 11 uV/mA x 100 mA) *(check: whether VFB's limits already include line and load)*

def rails(vfbp, vfbn, r1, r2, r3, r4, tol=TOL_R, dt=DT, tc=TC_R, sign=(1, 1, 1, 1)):
    """One corner: resistor tolerance sign +-1 per R1, R2, R3, R4 and the opposed-tempco drift of dt kelvin applied in the sign's direction."""
    f = lambda x, s: x * (1 + s * (tol + tc * dt))
    r1, r2, r3, r4 = f(r1, sign[0]), f(r2, sign[1]), f(r3, sign[2]), f(r4, sign[3])
    return vfbp * (1 + r1 / r2), vfbn * (1 + r3 / r4)

def rail_corners(r1=120e3, r2=68e3, r3=64.2e3, r4=100e3):
    lo_p = hi_p = lo_n = hi_n = None
    pv, nv = [], []
    for vp, vn in itertools.product((LM["vfbp"][0], LM["vfbp"][2]), (LM["vfbn"][0], LM["vfbn"][2])):
        for s in itertools.product((-1, 1), repeat=4):
            p, n = rails(vp, vn, r1, r2, r3, r4, sign=s)
            pv.append(p); nv.append(n)
    # the nominal pair (typical VFB, no tolerance) and the corners with the allowance for regulation
    nom_p = LM["vfbp"][1] * (1 + r1 / r2); nom_n = LM["vfbn"][1] * (1 + r3 / r4)
    return dict(nom_p=nom_p, nom_n=nom_n, min_p=min(pv) - REG_ALLOW, max_p=max(pv) + REG_ALLOW,
                min_n=min(nv) - REG_ALLOW, max_n=max(nv) + REG_ALLOW)

# ------------------------------------------------------------------------------------------------------------- AWG currents
def awg_values():
    sys.path.insert(0, os.path.join(V2, "sim", "awg"))
    import importlib
    d = importlib.import_module("design")
    v = dict(d.VALUES)
    return v, d

def awg_state(v, vout, rl, vrail, rout=49.5):
    """DC currents of the AWG stage for an op-amp output voltage vout into the back-termination rout and a load rl (inf, 50, 0 = short).
    Topology (design.py): Vout = Gs*Vp - K*Vo, Vo the filtered +3.3 V rail through Rvr; inverting node: Rg1 to ground (if any), Rg2 to Vo, Rf to the output.
    Returns dict: i_load, i_g2 (from the +rail through Rg2), i_o (op-amp output current, + sourcing), ip_awg, in_awg."""
    Rf, Rg2 = v["Rf"], v["Rg2"] + v.get("Rvr", 0.0)
    Rg1 = v.get("Rg1", float("inf"))
    Gs0 = 1 + Rf * (1 / Rg2 + (0.0 if not np.isfinite(Rg1) else 1 / Rg1)); K = Rf / Rg2
    vinv = (vout + K * vrail) / Gs0
    i_g2 = (vrail - vinv) / Rg2
    i_g1 = 0.0 if not np.isfinite(Rg1) else vinv / Rg1
    i_f = i_g2 - i_g1                                   # into the output node through Rf
    i_load = 0.0 if rl == float("inf") else vout / (rout + rl)
    i_o = i_load - i_f                                  # the op-amp output current, + = sourcing from the +rail
    return dict(vinv=vinv, i_load=i_load, i_g2=i_g2, i_o=i_o)

def budget(vp, v, awg_rl, awg_vout, iq_per_amp, pu=True, bleed=10e3, ladder_r=330.0, vref=3.009, rail_ok=True, pump_overhead=0.10,
            rd_node=None):
    """mA of every load on OUT+ and OUT- and the 5 V pin, for one state.  vp = the +rail's value, vref the reference's value."""
    s = awg_state(v, awg_vout, awg_rl, vref)     # the AWG's offset source is the REF3030E (../awg/design.py), not the +rail
    iq_awg = 2 * iq_per_amp
    ip_awg = iq_awg + s["i_g2"] + max(s["i_o"], 0.0)
    in_awg = iq_awg + max(-s["i_o"], 0.0)
    ip = dict(scope_dual=2 * iq_per_amp, awg_dual_iq=iq_awg, awg_offset_path=s["i_g2"], awg_output_src=max(s["i_o"], 0.0),
              ads=ADS["iq"][2], ref_iq=REF["iq"][1],
              ladder=vref / (6 * ladder_r * (1 - TOL_R)),
              sense_divider=sense_default_current(awg_vout / 2.0 if awg_rl == 50 else awg_vout, vref),
              scope_centre=2 * 5.4e-6, i2c_pullups=(2 * vp / 4.7e3 if pu else 0.0), bleed=vp / bleed)
    i_neg = dict(awg_dual_iq=iq_awg, awg_output_snk=max(-s["i_o"], 0.0))
    Ip, In = sum(ip.values()), sum(i_neg.values())
    iin = Ip + In * (1 + pump_overhead) + LM["iq"]
    return dict(ip=ip, i_neg=i_neg, Ip=Ip, In=In, Iin=iin, state=s)

def sense_default_current(vnode, vref, rt=20e3):
    """current the default-tied sense divider draws from the reference (A): the node voltage over the total divider + default resistor (design.md)."""
    return abs(vref - vnode) / rt

# ------------------------------------------------------------------------------------------------------------- PW-1
def run_pw1(awg_top=2.2275, awg_bot=-1.9, iq=TPH["iq_max"], bleed=10e3, limit100=REQ["pw1_ma"], limit450=REQ["pw1_total_ma"]):
    v, d = awg_values()
    rc = rail_corners()
    states = []
    rails_ = (rc["max_p"], rc["min_p"])
    cases = [("normal, AWG hi-Z at the window top", float("inf"), awg_top),
             ("normal, AWG into 50 ohm at the window top", 50.0, awg_top),
             ("normal, AWG into 50 ohm at the window bottom", 50.0, awg_bot),
             ("normal, AWG hi-Z at the window bottom", float("inf"), awg_bot),
             ("fault: BNC shorted, DAC at the window top", 0.0, awg_top),
             ("fault: BNC shorted, DAC at the window bottom", 0.0, awg_bot),
             ("fault: BNC shorted, DAC at the 3.3 V reset level (output clips about 0.1 V under the rail)", 0.0, rc["max_p"] - 0.1)]
    worst_norm = worst_fault = 0.0
    out = []
    for name, rl, vo in cases:
        for vp in rails_:
            b = budget(vp, v, rl, vo, iq, bleed=bleed)
            out.append(dict(state=name, rail=vp, Ip_mA=b["Ip"] * 1e3, In_mA=b["In"] * 1e3, Iin_mA=b["Iin"] * 1e3, i_o_mA=b["state"]["i_o"] * 1e3))
            if name.startswith("normal"):
                worst_norm = max(worst_norm, b["Iin"] * 1e3)
            else:
                worst_fault = max(worst_fault, b["Iin"] * 1e3)
    return dict(rows=out, worst_norm=worst_norm, worst_fault=worst_fault, awg_values=v, limit100=limit100, limit450=limit450)

# ------------------------------------------------------------------------------------------------------------- run
def main():
    v, d = awg_values()
    R["awg_design_sha"] = sha(d.__file__)
    R["awg_report_table_sha"] = sha(os.path.join(V2, "sim", "awg", "report_table.md"))
    R["awg_values"] = v
    R["awg_top_end_lim"] = float(d.TOP_END_LIM)

    # ---------- rails
    rc = rail_corners()
    R["rails"] = rc
    sum_max = rc["max_p"] + rc["max_n"]
    C.add("PW-V2-2", "V2-2", "supply across the op-amp <= recommended 5.5 V (TPH2502 VDD row) at both rails' worst corners, 1 % Basic feedback, +-10 K, regulation 2.5 mV",
          "V+ + |V-| at the maximum corner <= 5.5 V", f"{rc['max_p']:.4f} + {rc['max_n']:.4f} = {sum_max:.4f} V", f"{5.5-sum_max:+.4f} V", sum_max <= 5.5,
          "the line: TPH2502 datasheet Rev. A, 'Electrical Characteristics' (continued), PDF page 4, row 'VDD Supply Voltage, MIN 2.5, MAX 5.5, V'; its Applications Information (PDF page 7) says 'specified over +2.7 V to +5.5 V ... the supply voltage may range from +2.5 V to +5.5 V'. The datasheet has no Recommended Operating Conditions table: 5.5 V is the top of its specified supply range and is taken as the recommended maximum. Abs max V+ - V- = 7.0 V (Absolute Maximum Ratings, PDF page 2; the text says 7.5 V). Minimum corner sum 5.175 V is inside 2.5 V. See the R3 table", "rails")
    C.add("PW-V2-2b", "V2-2", "the same at the abs-max reading (information)", "7.0 V", f"{rc['max_p']+rc['max_n']:.3f} V", f"{7.0-sum_max:+.2f} V", True, "", "rails")
    C.add("PR-2", "PR-2", "the powered scope op-amp's supply <= 3.45 V (anything that drives A0/A1)", "<= 3.45 V", f"{rc['max_p']:.4f} V", f"{3.45-rc['max_p']:+.4f} V", rc["max_p"] <= 3.45, "", "rails")
    refmin = REF["vout"] * (1 + REF["tol"]) + REF["vin_min_off"]
    C.add("PA-2/rail", "PA-2", "REF3030E VIN >= VOUT + 0.2 V (6.3, REF30xxE) at the weakest +rail",
          f">= {refmin:.3f} V (VOUT at +0.1 %)", f"{rc['min_p']:.4f} V", f"{rc['min_p']-refmin:+.4f} V", rc["min_p"] >= refmin,
          "only 1 % Basic feedback resistors move this: with VFB 1.5 % and the resistors 1.3 % the rail's window is the reference's whole dropout margin", "rails")
    C.add("PW-6", "PW-6", "LDO headroom at 5V pin 4.50 V: +LDO (VIN - V+max) and the pump (|CPOUT| - |V-|max)", ">= 0.05 V / 0.03 V (dropout at 100 mA, 5.5 VLDO+/-)",
          f"{4.5-rc['max_p']:.2f} V / {4.5 - 0.034*3.0 - rc['max_n']:.2f} V", "", (4.5 - rc["max_p"]) >= 0.05 and (4.5 - 0.034 * 3.0 - rc["max_n"]) >= 0.03,
          "RNEG 2.5 ohm at 100 mA / 5.5 V; 3 ohm assumed at 4.5 V (check)", "rails")
    # R3 alternatives
    alt = []
    for r3 in (62.2e3, 64.2e3, 66e3, 68e3):
        rcx = rail_corners(r3=r3)
        alt.append(dict(R3=r3, nom_n=rcx["nom_n"], min_n=rcx["min_n"], max_n=rcx["max_n"], sum_max=rcx["max_p"] + rcx["max_n"],
                        margin_rating=5.5 - rcx["max_p"] - rcx["max_n"]))
    R["r3_options"] = alt

    # ---------- PW-1
    pw = run_pw1()
    R["pw1"] = pw
    C.add("PW-1", "PW-1", "AFE current from the Due's 5V pin, normal operation, IQ at the datasheet maximum, rails at the strong corner",
          "<= 100 mA", f"{pw['worst_norm']:.1f} mA", f"{100-pw['worst_norm']:+.1f} mA", pw["worst_norm"] <= 100.0,
          "charge-pump input current = output current + 10 % + IQ 0.39 mA *(check: IQ is a typical, no maximum is given; the datasheet gives no efficiency table in text)*. The AWG's offset path comes from the REF3030E, which the +rail supplies, so it counts on OUT+ either way", "pw1")
    tot = pw["worst_fault"] + REQ["due_ma"]
    C.add("PW-1 total", "PW-1", "Due (300 mA, D7) + AFE in the worst fault (indefinite short), <= 450 mA", "<= 450 mA",
          f"{tot:.0f} mA ({pw['worst_fault']:.1f} mA AFE)", f"{450-tot:+.0f} mA", tot <= 450.0, "the short is exempt from the 100 mA, not from the 450 mA total", "pw1")

    # ---------- thermal of the LM27762
    p = max((rr["Ip_mA"] * 1e-3 * (5.25 - rc["max_p"]) + rr["In_mA"] * 1e-3 * (5.25 * 1.1 - rc["min_n"]) + 5.25 * LM["iq"]) for rr in pw["rows"] for _ in [0])
    # (the pump-side term uses the pump input current at 5.25 V against the |V-| it delivers: the whole difference is dissipated)
    tj = 85 + LM["rth_ja"] * p
    R["lm_pdiss_w"] = p; R["lm_tj"] = tj
    C.add("PW-1/th", "PW-1", "LM27762 junction at 85 C ambient, worst state, 5.25 V in, RthJA 62.2 C/W (the datasheet's) ", "<= 125 C", f"{tj:.0f} C ({p*1e3:.0f} mW)", f"{125-tj:+.0f} K", tj <= 125.0,
          "RthJA is the datasheet's JEDEC figure; a real board does better or worse: check", "pw1")

    # ---------- PW-2 rule, as the design states it
    R["fsw"] = LM["fsw"]
    C.add("PW-2", "PW-2", "ripple at an amplifier supply pin <= 20 mV", "<= 20 mV", "see lm27762 runs and section 'PW-2'", "", None,
          "the switching frequency is the part's 1.7 to 2.3 MHz (2 MHz typ), not settable; see the rule in design.md", "pw2")

    # ---------- unpowered rail (PR-3)
    run_unpowered()

    # ---------- guards
    run_guards()
    C.save(); G.save(); save("power", R)
    for r in C.rows:
        print(("PASS" if r["ok"] else "FAIL" if r["ok"] is False else "INFO"), r["id"], "|", r["value"], "|", r["margin"])
    for g in G.rows:
        print("GUARD", g["id"], g["broken"], g["restored"], "OK" if g["good"] else "BAD")
    return 0

# ------------------------------------------------------------------------------------------------------------- PR-3
def unpowered(bleed, vrail=0.5, vin=12.0, r1=540e3, rn=464e3, vd=0.3, tol=0.01, fb=188e3, ads_leak=0.0, lm_pd=None):
    """Worst-case current the scope inputs push into the unpowered +3.3 V_A rail at vrail (A), and what the sinks take at that voltage.
    Per channel: (vin - vrail - vd) through R1 (-1 %) into the node, less the node's own return V_N/Rn (R2||R3, +1 %), is the clamp current into the rail."""
    v_n = vrail + vd
    src = 2 * ((vin - v_n) / (r1 * (1 - tol)) - v_n / (rn * (1 + tol)))
    snk = dict(bleed=vrail / (bleed * (1 + tol)), fb=vrail / (fb * (1 + tol)))
    if lm_pd:
        snk["lm27762_discharge"] = vrail / lm_pd
    snk["ads_ref_ops"] = ads_leak
    return src, snk

def bleed_options():
    rs = basic_resistors("0603")
    out = []
    for r in sorted(rs):
        if 5e3 <= r <= 30e3:
            src, snk = unpowered(r)
            tot = sum(snk.values())
            vr = 0.5
            # the rail voltage at which sink = source (linear sinks) -> bisection
            lo, hi = 0.0, 6.0
            for _ in range(60):
                mid = (lo + hi) / 2
                s_, k_ = unpowered(r, vrail=mid)
                if sum(k_.values()) >= s_: hi = mid
                else: lo = mid
            out.append(dict(R=r, lcsc=rs[r], sink_ua_at_0p5=tot * 1e6, rail_v=hi, quiescent_ma_3p3=3.3 / r * 1e3, quiescent_ma_3p392=3.392 / r * 1e3))
    return out

def run_unpowered():
    src, _ = unpowered(1e9)
    R["pr3_source_ua"] = src * 1e6
    certain = 0.5 / (188e3 * 1.01)
    pd = 0.5 / LM["shutdown_pulldown"]
    R["pr3_certain_sink_ua"] = certain * 1e6
    R["pr3_lm_pd_ua"] = pd * 1e6
    opts = bleed_options()
    R["pr3_options"] = opts
    # what the unpowered ICs sink at 0.5 V that a datasheet supports
    C.add("PR-3/src", "PR-3", "worst current pushed into the +3.3 V_A rail by both inputs at +12 V (0.3 V clamp drop assumed, R1 -1 %)", "information", f"{src*1e6:.1f} uA", "", None,
          "the scope design's 36 uA was a 0.6 V drop; a Schottky-like input structure raises it: *(check)* the TPH2502 gives no unpowered figure", "pr3")
    C.add("PR-3/ic", "PR-3", "sink the unpowered ICs provide at 0.5 V by datasheet: feedback divider only", "information", f"{certain*1e6:.1f} uA", "", None,
          "LM27762 shutdown discharge 50 kohm would add 10 uA at 0.5 V but 6.4.1 does not say it works with VIN = 0 *(check)*; ADS1115, REF3030E and the op-amps give no leakage at 0.5 V: none counted", "pr3")
    C.add("PR-3/ic2", "PR-3", "sink counted if the LM27762's discharge works (information)", "information", f"{(certain+pd)*1e6:.1f} uA", "", None, "not relied on", "pr3")
    choice = 10e3
    s, k = unpowered(choice)
    # bisect the rail voltage with the chosen bleed
    lo, hi = 0.0, 6.0
    for _ in range(60):
        mid = (lo + hi) / 2
        s_, k_ = unpowered(choice, vrail=mid)
        if sum(k_.values()) >= s_: hi = mid
        else: lo = mid
    R["pr3_choice"] = dict(R=choice, rail_v=hi, ua_at_0p5=sum(k.values()) * 1e6, q_ma=3.3 / choice * 1e3, q_ma_max=3.392 / (choice * 0.99) * 1e3)
    C.add("PR-3", "PR-3", "unpowered +3.3 V_A rail with both scope inputs at +12 V, 10k bleed (C25804) at +1 %, with only the resistive sinks", "<= 0.5 V", f"{hi:.3f} V",
          f"{0.5-hi:+.3f} V", hi <= 0.5, f"sinks {sum(k.values())*1e6:.1f} uA against {s*1e6:.1f} uA pushed in at 0.5 V", "pr3")
    qm = 3.392 / (choice * 0.99) * 1e3
    C.add("PR-3/Q", "PW-1", "quiescent cost of the bleed, rail at its maximum, resistor -1 %", "information", f"{qm:.3f} mA = {qm:.2f} % of 100 mA", "", None, "", "pr3")
    # PR-3's other half: current into the Due's supply pins (the 5 V pin is not touched; the 3.3 V pin through the R3s is at most microamps)
    C.add("PR-3/Due", "PR-3", "current into the Due's supply pins <= 100 uA", "<= 100 uA", "1.8 uA (scope design, through R3 and the sense filter; nothing reaches the 5V pin)", "", True,
          "the scope design's figure, not re-derived here; the bleed does not change it", "pr3")

def run_guards():
    # 1  the V2-2 rating check must fail when the nominal negative rail is raised (R3 = 82k gives 2.26 V)
    ok_b = _sum_ok(rail_corners(r3=82e3))
    ok_r = _sum_ok(rail_corners())
    G.add("G-PW-rating", "V2-2 supply check: R3 = 82k (nominal -2.26 V) must exceed 5.5 V at the corners", ok_b, ok_r)
    # 2  PW-1 must fail with a limit of 40 mA
    w = run_pw1()
    G.add("G-PW-1", "PW-1 check with the limit lowered to 40 mA must fail", w["worst_norm"] <= 40.0, w["worst_norm"] <= 100.0)
    # 3  the PR-3 check must fail with no bleed
    def pr3(bl):
        s, k = unpowered(bl)
        lo, hi = 0.0, 6.0
        for _ in range(60):
            mid = (lo + hi) / 2
            s_, k_ = unpowered(bl, vrail=mid)
            if sum(k_.values()) >= s_: hi = mid
            else: lo = mid
        return hi <= 0.5
    G.add("G-PR-3", "PR-3 check with the bleed removed (1 Gohm) must fail", pr3(1e9), pr3(10e3))
    # 4  REF dropout check must fail if the +rail's feedback is lowered (R1 = 150k: 3.0 V nominal)
    def refdrop(r1):
        return rail_corners(r1=r1)["min_p"] >= REF["vout"] * 1.001 + REF["vin_min_off"]
    G.add("G-REF-VIN", "REF3030E dropout check with R1 = 100k (nominal 2.97 V) must fail", refdrop(100e3), refdrop(120e3))

def _sum_ok(rc):
    return rc["max_p"] + rc["max_n"] <= 5.5

if __name__ == "__main__":
    sys.exit(main())
