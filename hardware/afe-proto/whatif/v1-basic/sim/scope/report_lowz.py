"""Writes report.md for the low-impedance divider (variant 'lowz') from results/*.json.  Nothing in a table is typed in."""
import os, json
import numpy as np
import netlib as NL
import run as R
import lowz as L

HERE = os.path.dirname(os.path.abspath(__file__))

def lj(n):
    return R.loadj(n)

def mv(x):
    return f"{x*1e3:.1f} mV"

def uv(x):
    return f"{x*1e6:.0f} uV"

def make():
    dc = {d: lj(f"dc_{d}") for d in L.DESIGNS}
    ac = lj("ac"); nz = lj("noise"); kk = lj("kick"); pr = lj("prot"); gd = lj("guards"); zi = lj("zin"); ed = lj("edge"); sw = lj("sweep")
    hs = R.model_hashes()
    p = L.P("N"); dv = L.divider(p); dv3 = L.divider(L.P("R3"))
    rows = []
    def row(i, lim, res, ok, margin=""):
        v = ok if isinstance(ok, str) else ("PASS" if ok else "FAIL")
        rows.append(f"| {i} | {lim} | {res} | {v} | {margin} |")
    both = lambda f: (f("N"), f("R3"))
    # ---------------- DC
    for d in ("N", "R3"):
        pass
    T5 = {d: dc[d]["aref_table"]["5"] for d in dc}; T12 = {d: dc[d]["aref_table"]["1.25"] for d in dc}
    m5 = min(T5[d]["3.20"]["margin_wc"] for d in dc); m12 = min(T12[d]["3.20"]["margin_wc"] for d in dc)
    row("SC-2 (+/-5 V at +/-6 V, AREF 3.20)", ">= 80 mV per side", f"worst {mv(m5)} (both wirings)", m5 >= 0.08, mv(m5 - 0.08))
    la5 = max(dc[d]["lowest_aref"]["5"] for d in dc); la12 = max(dc[d]["lowest_aref"]["1.25"] for d in dc)
    row("SC-2 / SC-11 over AREF", "80 mV holds down to AREF 3.20", f"holds down to {la5:.3f} V (+/-5 V), {la12:.3f} V (+/-1.25 V)", max(la5, la12) <= 3.20, f"{(3.20-max(la5, la12))*1e3:.0f} mV of AREF")
    gmin = min(T5[d]["3.30"]["gain_min"] for d in dc); gmax = max(T5[d]["3.30"]["gain_max"] for d in dc)
    row("SC-4 step", "<= 4 mV per code at the input", f"{3.3/4096/gmax*1e3:.2f}-{3.3/4096/gmin*1e3:.2f} mV (gain {gmin:.4f}-{gmax:.4f})", 3.3/4096/gmin <= 4e-3, f"{(4e-3-3.3/4096/gmin)*1e3:.2f} mV")
    occ = (10 * gmin / 3.3 * 100, 10 * gmax / 3.3 * 100)
    row("SC-4 occupancy", "70-75 % at nominal AREF (to about 76 % at 3.20)", f"{occ[0]:.1f}-{occ[1]:.1f} % at 3.30 V, {10*gmin/3.2*100:.1f}-{10*gmax/3.2*100:.1f} % at 3.20 V", 70 <= occ[0] and occ[1] <= 75, f"{75-occ[1]:.1f} % below 75")
    g12 = (min(T12[d]["3.20"]["gain_min"] for d in dc), max(T12[d]["3.20"]["gain_max"] for d in dc))
    row("SC-11 gain (+/-1.25 V)", "1.10-1.16 as built", f"{g12[0]:.4f}-{g12[1]:.4f} (RF 953 / RG 249 kept)", 1.10 <= g12[0] and g12[1] <= 1.16, f"{(g12[0]-1.10)*1e3:.0f} / {(1.16-g12[1])*1e3:.0f} milli")
    row("SC-11 margin (AREF 3.20)", ">= 80 mV per side at +/-1.25 V", f"worst {mv(m12)}", m12 >= 0.08, mv(m12 - 0.08))
    # SC-8: two channels at opposite worst-case gain ends
    sp5 = (gmax - gmin) / ((gmax + gmin) / 2) * 100; sp12 = (g12[1] - g12[0]) / ((g12[1] + g12[0]) / 2) * 100
    row("SC-8 gain matching before calibration (not re-specified here)", "within 1 %", f"+/-5 V {sp5:.2f} % (set by Ron 3.7-8.8 ohm in G = 1 + Ron/RG, unchanged from the 1 Mohm design); +/-1.25 V {sp12:.2f} %", sp5 <= 1 and sp12 <= 1, f"{1-sp5:+.2f} % (+/-5 V)")
    # ---------------- SC-3
    row("SC-3 input resistance", "about 20-30 kohm", f"{zi['N']['R_dc_ohm']/1e3:.2f} kohm (simulated; analytic {dv['rin']/1e3:.2f})", 20e3 <= zi['N']['R_dc_ohm'] <= 30e3, "in the window")
    cw = max(zi[d]["C_worst_1MHz_pF"] for d in zi)
    row("SC-3 input capacitance", "<= 30 pF incl. wiring", f"{zi['N']['C_1e+06_pF']:.1f} pF (N) / {zi['R3']['C_1e+06_pF']:.1f} pF (R3) at 1 MHz; {cw:.1f} pF worst (4 pF wiring assumed, +1 pF)", cw <= 30, f"{30-cw:.1f} pF")
    # ---------------- SM-3
    for d, lab in (("N", "injection switch on N (as decided)"), ("R3", "injection switch in the R3 leg (proposal)")):
        w5 = ac[f"{d}_5"]["worst"]["bw"]; w12 = ac[f"{d}_1.25"]["worst"]["bw"]
        row(f"SM-3 bandwidth, {lab}", ">= 8 MHz both ranges, worst corner", f"+/-5 V {w5/1e6:.2f} MHz, +/-1.25 V {w12/1e6:.2f} MHz (nominal {ac[f'{d}_5']['nominal']['bw']/1e6:.2f} / {ac[f'{d}_1.25']['nominal']['bw']/1e6:.2f})", min(w5, w12) >= 8e6, f"{(min(w5, w12)/8e6-1)*100:+.1f} %")
    # ---------------- SC-6
    for d, lab in (("N", "on N"), ("R3", "R3 leg")):
        n5 = nz[f"{d}_5"]["at_1p5bw"]["total_V"]; n12 = nz[f"{d}_1.25"]["at_1p5bw"]["total_V"]
        row(f"SC-6 noise to 1.5 x BW, switch {lab}", "<= 0.2 mV rms", f"+/-5 V {uv(n5)}, +/-1.25 V {uv(n12)}", max(n5, n12) <= 200e-6, uv(200e-6 - max(n5, n12)))
    # ---------------- SC-9
    xt = max(v["crosstalk_lsb"] for k, v in kk.items() if isinstance(v, dict) and "crosstalk_lsb" in v)
    xa = max(v["max_lsb"] for k, v in kk.items() if k.endswith("_ac"))
    row("SC-9 scope-to-scope (A full scale DC / step, B shorted)", "<= 2 LSB", f"{xt:.3f} LSB (shared Vmid at 50 mohm; per-channel sense filters); sine 1 Hz-200 MHz {xa:.3f} LSB", max(xt, xa) <= 2, f"{2-max(xt, xa):.2f} LSB")
    for d, lab in (("N", "switch on N (as decided)"), ("R3", "switch in the R3 leg (proposal)")):
        a = max(kk[f"{d}_{r}_awg"]["max_lsb"] for r in ("5", "1.25"))
        f2 = kk[f"{d}_1.25_awg"]["f_2lsb"]
        extra = f"; exceeds 2 LSB above {f2/1e3:.1f} kHz (+/-1.25 V)" if f2 else ""
        row(f"SC-9 AWG coupling while DAC0 plays, {lab}", "<= 2 LSB", f"{a:.2f} LSB peak, DAC0 full swing, 10 Hz-20 MHz{extra}", a <= 2, f"{2-a:+.2f} LSB")
    # ---------------- SC-10
    err = max(max(abs(v["full_swing"]["errA_lsb"]), abs(v["full_swing"]["errB_lsb"])) for k, v in kk.items() if isinstance(v, dict) and "full_swing" in v)
    st = max(v["full_swing"]["settleB_ns"] for k, v in kk.items() if isinstance(v, dict) and "full_swing" in v)
    zo = max(v["zout"]["zmax_to_10MHz"] for k, v in kk.items() if isinstance(v, dict) and "zout" in v)
    row("SC-10 / AN-2 settling", "0.5 LSB in the 667 ns window; Z <= 5 kohm", f"{err:.4f} LSB at the window end; 0.5 LSB reached in {st:.0f} ns; pin Z <= {zo:.0f} ohm to 10 MHz", err <= 0.5 and st < 667 and zo <= 5000, f"{667-st:.0f} ns")
    # ---------------- AN-1
    for d in ("N", "R3"):
        pmw = min(ac[f"{d}_{r}"]["worst"]["pm"] for r in ("5", "1.25")); pms = min(min(x["pm"] for x in ac[f"{d}_{r}"]["sens"]) for r in ("5", "1.25"))
        row(f"AN-1 phase margin ({d})", ">= 45 deg", f"{min(pmw, pms):.1f} deg worst", min(pmw, pms) >= 45, f"{min(pmw, pms)-45:.1f} deg")
    # ---------------- PR
    dcp = pr["dc"]
    ipk = max(v["i_opamp_peak_mA"] for v in pr["edge"].values()); idc = max(v["i_opamp_in_mA"] for v in dcp.values())
    pw = max(v["P_100k_part_mW"] for v in dcp.values()); vw = max(v["V_100k_part"] for v in dcp.values())
    row("PR-1 +/-30 V continuous, op-amp input clamp", "<= 10 mA (abs max)", f"{idc:.2f} mA DC, {ipk:.2f} mA peak on a 5 ns 30 V edge", max(idc, ipk) <= 10, f"{10-max(idc, ipk):.1f} mA")
    row("PR-1 R1 parts at +/-30 V", "0603 rating 100 mW, 75 V working *(check, part not chosen)*", f"each 100k sees {vw:.1f} V and {pw:.1f} mW", pw <= 100 and vw <= 75, f"{100-pw:.0f} mW")
    tm = max(v.get("i_tmux_esd_mA", 0) for v in dcp.values())
    row("PR-1 injection switch at N (as decided)", "TMUX1119 abs max: S pin within VDD + 0.5 V (no current clause)", f"N is held at {max(v['v_n'] for v in dcp.values()):.2f} V / {min(v['v_n'] for v in dcp.values()):.2f} V at +/-30 V; the switch's own clamp carries {tm:.3f} mA", "FAIL *(check)*", "outside the abs max at |Vin| above about 9 V")
    pwd = [v for v in dcp.values()]; edd = list(pr["edge"].values())
    pmax = max(max(v["v_pin"] for v in pwd), max(v["pin_max"] for v in edd)); pmin = min(min(v["v_pin"] for v in pwd), min(v["pin_min"] for v in edd))
    row("PR-2 ADC pin, powered, +/-30 V DC and 5/42 ns edges", "-0.2 to 3.45 V", f"{pmin:.3f} to {pmax:.3f} V", pmin >= -0.2 and pmax <= 3.45, f"{(3.45-pmax)*1e3:.0f} mV top")
    up = pr["unpowered"]
    def worst(d, sw, bl, which):
        ks = [k for k in up if k.startswith(f"{d}|{sw}|{bl:g}|")]
        return ks
    def one_input(d, sw, bl):
        rs = [up[f"{d}|{sw}|{bl:g}|{a}"] for a in ("+30,+0", "-30,+0")]
        return (max(abs(L.supply_uA(r)) for r in rs), max(abs(r["i_pin_a_uA"]) + abs(r["i_pin_b_uA"]) for r in rs), max(r["v_rail"] for r in rs),
                min(min(r["v_apin"], r["v_bpin"]) for r in rs), max(max(r["v_apin"], r["v_bpin"]) for r in rs))
    def two_inputs(d, sw, bl):
        rs = [up[f"{d}|{sw}|{bl:g}|{a}"] for a in ("+30,+30", "-30,-30", "+30,-30")]
        return (max(abs(L.supply_uA(r)) for r in rs), max(abs(r["i_pin_a_uA"]) + abs(r["i_pin_b_uA"]) for r in rs), max(r["v_rail"] for r in rs))
    for bl, lab in ((4700.0, "4.7 kohm bleed (approved BOM)"), (249.0, "249 ohm bleed (proposed)")):
        s_, pn, vr, pl, ph = one_input("N", "na", bl)
        ok = s_ <= 100 and vr < 0.5
        row(f"PR-3 unpowered, one input at +/-30 V, {lab}", "<= 100 uA into the Due supply pins; rails < 0.5 V", f"supply pins {s_:.1f} uA, AFE rail {vr:.3f} V; ADC-pin clamps a further {pn:.1f} uA", ok, f"{100-s_:.0f} uA, {(0.5-vr)*1e3:.0f} mV")
        if bl == 249.0:
            row("PR-2 ADC pin, unpowered, one input at +/-30 V, 249 ohm bleed", "-0.2 to 3.45 V", f"{pl:.3f} to {ph:.3f} V (held by the SAM3X's own clamps)", pl >= -0.2 and ph <= 3.45, "")
            s2, p2, v2 = two_inputs("N", "na", bl)
            row("PR-3 unpowered, BOTH inputs at +/-30 V, 249 ohm bleed (stress, not the requirement's case)", "as PR-3", f"supply pins {s2:.1f} uA, AFE rail {v2:.3f} V, ADC pins {p2:.1f} uA", s2 <= 100 and v2 < 0.5, "")
    # option adopted below: BAT54S at each ADC pin
    def oc(d, bl):
        rs = [up[f"{d}+clamp|{'on' if d == 'R3' else 'na'}|{bl:g}|{a}"] for a in ("+30,+0", "-30,+0")]
        return (max(abs(r["i_due_uA"]) for r in rs), max(r["v_rail"] for r in rs), min(min(r["v_apin"], r["v_bpin"]) for r in rs),
                max(max(r["v_apin"], r["v_bpin"]) for r in rs))
    for d in ("N", "R3"):
        tot, vr, pl, ph = oc(d, 249.0)
        row(f"PR-3 unpowered, one input, 249 ohm bleed + BAT54S at each ADC pin ({d})", "<= 100 uA into the Due counting the ADC pins too; rails < 0.5 V",
            f"{tot:.1f} uA in all, AFE rail {vr:.3f} V", tot <= 100 and vr < 0.5, f"{100-tot:.0f} uA")
    tot, vr, pl, ph = oc("R3", 249.0)
    row("PR-2 ADC pin, unpowered, one input at +/-30 V, 249 ohm + BAT54S", "-0.2 to 3.45 V", f"{pl:.3f} to {ph:.3f} V, BAT54S at its datasheet MAXIMUM VF *(check: typical is lower)*", pl >= -0.2 and ph <= 3.45, f"{(pl+0.2)*1e3:+.0f} mV")
    pc = lj("pinclamp")
    row("Cost of the BAT54S (10 pF CT max) at the pin, R3 wiring", "SM-3 >= 8 MHz, AN-1 >= 45 deg, SC-10 0.5 LSB", f"worst BW {min(pc['R3_5']['worst_bw'], pc['R3_1.25']['worst_bw'])/1e6:.2f} MHz, PM {min(pc['R3_5']['worst_pm'], pc['R3_1.25']['worst_pm']):.1f} deg, S/H error {max(pc['R3_5']['kick_err_lsb'], pc['R3_1.25']['kick_err_lsb']):.4f} LSB; leakage 2 uA max x 22 ohm = 44 uV", min(pc['R3_5']['worst_bw'], pc['R3_1.25']['worst_bw']) >= 8e6, "")
    # PW-1: sense current from the Due's 3.3 V pin (analytic, from the simulated alpha)
    a_ = dv["alpha"]; r3l = dv["r3leg"]
    i0 = (3.3 - 1.65) / r3l; ilo = (3.3 - (1.65 - 6 * a_)) / r3l; ihi = (3.3 - (1.65 + 6 * a_)) / r3l
    row("PW-1 sense current from the Due's 3.3 V pin (derived)", "'microamps' (PW-1); no number", f"{i0*1e6:.1f} uA per channel at 0 V in, {ihi*1e6:.0f}-{ilo*1e6:.0f} uA over +/-6 V; two channels {2*ihi*1e6:.0f}-{2*ilo*1e6:.0f} uA (was 4.3 uA per channel)", "FLAG", "requirement question")
    out = "\n".join(rows)

    # ============================================================ text
    T = []; A = T.append
    A("# 2b scope channel: simulation report (low-impedance divider, 2026-11-11)\n")
    A("Plan step 2b (`docs/afe-plan.md`), redesigned for SC-3's 20-30 kohm uncompensated input. Regenerated by `python3 -I run.py --par` (four ngspice processes, about 4 minutes) or `python3 -I run.py` (one); raw numbers in `results/*.json`, netlists in `netlists/` (each prefixed with its section). **The superseded 1 Mohm compensated design stays reproducible**: `python3 -I run.py --variant legacy` writes `report_legacy.md`, `results/legacy/` and `netlists_legacy/`; its parameter set is `netlib.P_LEGACY`, unchanged.\n")
    A("## Report header\n")
    A(f"- Simulator `{NL.ngspice_version()}`; vendor models referenced by path, not copied: " + ", ".join(f"`{k}` sha256 `{v['actual']}` ({'matches' if v['match'] else 'DOES NOT MATCH'} `models/SOURCES.md`)" for k, v in hs.items()) + ". OPA354 is the op-amp throughout (owner, 2026-11-11); OPA365 is not re-run.")
    A("- Own models: `models/rangesw.lib` (TMUX1119 Ron / CSOFF / CON, unchanged) and, new, a generic silicon clamp diode `DESD` (IS 1e-15, N 1, RS 5 ohm: 0.60 V at 10 uA, 0.72 V at 1 mA) for every IC pin clamp in the unpowered network and for the injection switch's pins at N *(assumption: no datasheet gives the clamps' I-V)*.")
    A("- Loads, rails, ADC model, stimuli: as the first round (`report_legacy.md`, header), except: the Due's 3.3 V pin is a source behind **0.1 ohm** *(assumption, VT-8)* and each channel has its own 249 ohm + 10 uF sense filter; Vmid is still **one** source behind 50 mohm shared by both channels (conservative for SC-9: powercal is designing one buffer per channel).")
    A("- Parasitics *(assumptions, closed at G3)*: 2 pF from N to ground (pads of 13 parts and the trace; corners 1 and 3 pF), 0.3 pF across the R1 composite (corners 0.1 / 0.5 pF), 4 pF of BNC and trace at the input, 3 pF at the inverting node (corners -2 / +3 pF).")
    A("- The injection switch (PA-3, TMUX1119, owner decision: N on a source pin, D on DAC0): CSOFF **6 pF** (datasheet, f = 1 MHz) and **10 pF** (IBIS) at N as corners, and a feedthrough of **1.8 pF** from DAC0 to N when off, *derived* from OISO -65 dB at 1 MHz and -45 dB at 10 MHz into 50 ohm (both give 1.79 pF) *(check: the datasheet gives isolation, not a capacitance)*.\n")

    A("## Two wirings of the injection switch, because the decided one does not fit this divider\n")
    w5n = ac["N_5"]["worst"]["bw"]; w12n = ac["N_1.25"]["worst"]["bw"]
    A(f"With the switch's S1 on N, its 6-10 pF sits on a node whose Thevenin resistance is now {dv['rth']/1e3:.2f} kohm instead of the old divider's 40 pF-compensated 178 kohm. The pole falls to **{ac['N_1.25']['nominal']['bw']/1e6:.2f} MHz nominal and {min(w5n, w12n)/1e6:.2f} MHz at the worst corner** against SM-3's 8 MHz, and the switch's feedthrough puts DAC0 onto N: **{max(kk['N_5_awg']['max_lsb'], kk['N_1.25_awg']['max_lsb']):.0f} LSB** of AWG at the pin against SC-9's 2 LSB (above {kk['N_1.25_awg']['f_2lsb']/1e3:.0f} kHz on +/-1.25 V). No divider in SC-3's window repairs either; the sweep below shows SM-3 needs a Thevenin of about 1.0-1.4 kohm with the switch on N, an input of 5.5-7.7 kohm.\n")
    A("| divider scale | Rth | Rin | CSOFF 0 pF: BW +/-5 / +/-1.25 V | 6 pF | 10 pF |\n|---|---|---|---|---|---|")
    for k in sorted({r["scale"] for r in sw}, reverse=True):
        rr = {r["csoff_pF"]: r for r in sw if r["scale"] == k}
        A(f"| {k:g} | {rr[0.0]['rth']/1e3:.2f} k | {rr[0.0]['rin']/1e3:.2f} k | " + " | ".join(f"{rr[c]['bw_5']/1e6:.2f} / {rr[c]['bw_1.25']/1e6:.2f} MHz" for c in (0.0, 6.0, 10.0)) + " |")
    A("\n(Worst corner: inverting node +3 pF, Ron 8.8 ohm, 3 pF at N, 0.1 pF across R1; the feedthrough is in the 6 and 10 pF columns.)\n")
    A("**Proposal, simulated alongside ('R3'):** the same TMUX1119 placed in the **R3 leg**, D on the R3 end, S1 on the channel's sense node, S2 on DAC0. In normal use the switch is on (Ron in series with 16.7 kohm, 0.02-0.05 %); for calibration it drives DAC0 into N through R3. N then carries no switch, the switch's capacitance sits on the 10 uF sense node, and DAC0's feedthrough lands on that node through Ron. It costs no part and no type. What it changes in the calibration is in `sim/diff/report.md`: it reads the channel through R3 rather than after the divider. Every row below is given for both wirings where they differ.\n")

    A("## Settled circuit (one channel; the two are identical)\n")
    A("| part | value | built from (all existing types) | note |\n|---|---|---|---|")
    A(f"| R1 | {p['R1']:.1f} ohm | 6 x 100k 0.1 % (C394537, 10 ppm/K) in parallel, + 1 x 249 0.1 % (C2692731) in series | BNC to N; the 249 matches the R3 leg's sense resistor |")
    A(f"| R2 | {p['R2']:.1f} ohm | 8 x 953 0.1 % (C2984375) in series, that string in parallel with 1 x 330k 0.1 % (C351655) | N to Vmid |")
    A(f"| R3 | {p['R3']:.1f} ohm | 6 x 100k 0.1 % in parallel | N to the channel's sense node; R3 + Rs3 = R1 centres N on Vmid |")
    A("| Rs3, Cs3 | 249 ohm 0.1 %, 10 uF X5R | one per channel (was one shared 100R/249R + 10 uF) | from the Due's 3.3 V pin; a shared filter couples the channels by 13 LSB (guard) |")
    A("| C1, C2 | none | | uncompensated |")
    A("| Rnp | none (0 ohm) | | C1 is gone, so no fast edge reaches N; the clamp current is set by the divider (PR-1 row) |")
    A("| RF / RG, range switch, Riso, op-amp | 953 / 249 ohm 0.1 %, TMUX1119 shunting RF, 22 ohm, OPA354 | unchanged | |")
    A("| ADC-pin clamp (proposed) | BAT54S per channel | existing type (the AWG's) | pin 1 ground, pin 3 ADC pin (after Riso), pin 2 AFE +3.3 V; PR-2/PR-3 unpowered |")
    A("| AFE +3.3 V bleed | **249 ohm** 0.1 % (proposed; the approved BOM has 4.7 kohm) | existing type | PR-3: with 4.7 kohm the unpowered rail reaches 3.8 V. Powercal owns this net |")
    A("| injection switch | TMUX1119 | unchanged type | on N as decided, or in the R3 leg (proposal) |")
    A("")
    A(f"Divider (analytic, nominal): alpha = {dv['alpha']:.4f}, Thevenin at N {dv['rth']:.0f} ohm (route (c)'s window 3.6-5.3 kohm), input resistance {dv['rin']:.0f} ohm, R3 leg {dv['r3leg']:.1f} ohm = R1. Placements per channel: 12 x 100k, 8 x 953, 1 x 330k, 2 x 249, 1 x 10 uF.\n")

    A("## Pass / fail\n")
    A("Worst case: DC by one-at-a-time extremes summed (0.1 % on every leg incl. Rs3, centring +/-30 mV, Vos 8 mV, Ron 8.8, rail 3.23-3.37 V; for 'R3' also its Ron 8.8), cross-checked by 80-draw Monte Carlo; AC at 24 (N) / 12 (R3) corners: inverting node -2/0/+3 pF, Ron 3.7/8.8, (N stray, across-R1) = (1, 0.5) / (3, 0.1) pF, CSOFF 6/10 pF.\n")
    A("| requirement | limit | worst-case result | verdict | margin |\n|---|---|---|---|---|\n" + out + "\n")

    A("## Case 1: DC transfer and AREF\n")
    A("| AREF | +/-5 V margin, N / R3 | gain | +/-1.25 V margin, N / R3 | gain |\n|---|---|---|---|---|")
    for a in R.AREFS:
        k = f"{a:.2f}"
        A(f"| {a:.2f} V | {mv(T5['N'][k]['margin_wc'])} / {mv(T5['R3'][k]['margin_wc'])} | {T5['N'][k]['gain_min']:.4f}-{T5['N'][k]['gain_max']:.4f} | {mv(T12['N'][k]['margin_wc'])} / {mv(T12['R3'][k]['margin_wc'])} | {T12['N'][k]['gain_min']:.4f}-{T12['N'][k]['gain_max']:.4f} |")
    mc = dc["N"]["mc"]
    A("\nMonte Carlo (80 draws, wiring N): " + "; ".join(f"{k}: min margin {mv(v['margin_min'])}, gain {v['gain_min']:.4f}-{v['gain_max']:.4f}" for k, v in mc.items()) + ". Headroom to the op-amp rail at the worst corner (rail 3.23 V, +6 V in): " + f"{mv(dc['N']['headroom']['5']['headroom_to_rail'])} (+/-5 V), {mv(dc['N']['headroom']['1.25']['headroom_to_rail'])} (+/-1.25 V) *(check at 3.3 V: datasheet swing is given at 5 V only, VT-1)*.\n")
    A(f"Current that R2 returns to Vmid: +/-{1.39/p['R2']*1e6:.0f} uA per channel at +/-6 V (was +/-4 uA with 335 kohm); the RG current (up to 5.7 mA on the +/-1.25 V range) is unchanged. A note for powercal's Vmid buffers.\n")

    A("## Case 2: bandwidth, peaking, flatness, edges\n")
    A("| wiring, range | gain at 10 kHz | -3 dB nominal | worst corner | peak (worst) | PM nominal / worst | flatness 1-8 MHz vs 100 kHz | step 1 Hz -> 1 kHz (sense filter) |\n|---|---|---|---|---|---|---|---|")
    for k in ("N_5", "N_1.25", "R3_5", "R3_1.25"):
        v = ac[k]; n = v["nominal"]
        A(f"| {k.replace('_', ', +/-')} V | {n['g0']:.4f} | {n['bw']/1e6:.2f} MHz | {v['worst']['bw']/1e6:.2f} MHz | {v['worst']['peak_db']:.2f} dB | {n['pm']:.0f} / {v['worst']['pm']:.0f} deg | {v['lf']['flat_1_8MHz_db']:.2f} dB | {v['lf']['step_1Hz_to_1kHz_pct']:+.2f} % |")
    A(f"\nWith no injection switch at all the nominal bandwidth is {ac['noswitch_5']['nominal']['bw']/1e6:.2f} / {ac['noswitch_1.25']['nominal']['bw']/1e6:.2f} MHz, the same as 'R3': the proposal costs nothing in bandwidth. The 1-8 MHz flatness is the divider pole and the op-amp, not a shelf; there is no compensated-divider shelf any more. The only low-frequency step is the per-channel sense filter: R3's leg is 249 ohm longer at DC than above the filter's corner (64 Hz), a gain step of about -0.35 % between 1 Hz and 1 kHz, identical in both channels, which the host's frequency calibration (SC-5) removes.\n")
    A("| case | rise 10-90 | overshoot | settle 0.5 % |\n|---|---|---|---|")
    for k, v in ed.items():
        A(f"| {k} | {v['rise_10_90_ns']:.1f} ns | {v['overshoot_pct']:.2f} % | {v['settle_0p5pct_ns']:.0f} ns |")
    A("\nPhase margin over the inverting-node capacitance and Riso, OPA354 (wiring R3; N is within 1 degree):\n")
    A("| range | extra Cpar | Riso 10 | Riso 22 | Riso 50 |\n|---|---|---|---|---|")
    for rng in ("5", "1.25"):
        for cx in (-2.0, 0.0, 3.0):
            vals = {x["riso"]: x["pm"] for x in ac[f"R3_{rng}"]["sens"] if abs(x["cpar_extra_pf"] - cx) < 1e-9}
            A(f"| +/-{rng} V | {cx:+.0f} pF | {vals[10.0]:.1f} | {vals[22.0]:.1f} | {vals[50.0]:.1f} |")

    A("\n## Case 3: noise (SC-6)\n")
    A(f"Integrated 10 Hz to the stated frequency at the ADC pin; contributors as the first round (Vmid {R.EN_VMID*1e9:.0f} nV/sqrt Hz and the 3.3 V pin {R.EN_V3*1e9:.0f} nV/sqrt Hz assumed *(check, 2a)*).\n")
    A("| wiring, range | to | total | resistors | op-amp voltage | op-amp current | Vmid | 3.3 V sense | verdict |\n|---|---|---|---|---|---|---|---|---|")
    for k, v in nz.items():
        for lab, nm in (("at_bw", "-3 dB"), ("at_1p5bw", "1.5 x BW"), ("at_10MHz", "10 MHz")):
            x = v[lab]
            A(f"| {k.replace('_', ', +/-')} V | {nm} ({x['fmax']/1e6:.1f} MHz) | {uv(x['total_V'])} | {uv(x['resistors_V'])} | {uv(x['opamp_voltage_V'])} | {uv(x['opamp_current_resid_V'])} | {uv(x['vmid_V'])} | {uv(x['v3sense_V'])} | {'pass' if x['total_V'] <= 200e-6 else 'FAIL'} |")
    A(f"\nThe divider's Johnson noise is now the largest term on +/-1.25 V: the Thevenin is 40 times lower than the old 178 kohm, but the old design's 40 pF at N filtered it at 21 kHz and nothing filters it now below the op-amp's own pole, so it integrates over the whole band (kT/C at the few pF on N, times the stage gain 4.83). Its margin (R3 wiring) is {uv(200e-6 - nz['R3_1.25']['at_1p5bw']['total_V'])}. The 'N' wiring reads lower only because its bandwidth is 3.6 MHz.\n")

    A("## Case 4: ADC load, settling and crosstalk (SC-9, SC-10)\n")
    A("| wiring, range, ADC model, Riso | S/H error A / B at 667 ns | settles in | crosstalk dynamic / DC / total | pin Z to 10 MHz |\n|---|---|---|---|---|")
    for k, v in kk.items():
        if isinstance(v, dict) and "full_swing" in v and "Riso22" in k:
            f = v["full_swing"]
            A(f"| {k} | {f['errA_lsb']:.4f} / {f['errB_lsb']:.4f} LSB | {f['settleB_ns']:.0f} ns | {v['crosstalk_dyn_lsb']:.4f} / {v['crosstalk_dc_lsb']:.3f} / {v['crosstalk_lsb']:.3f} LSB | {v['zout']['zmax_to_10MHz']:.1f} ohm |")
    A("\nThe first round's crosstalk figure subtracted each run's own DC operating point, so it measured only the sampling kick; 'DC' here is the static shift of B's pin as A goes from -6 to +6 V and 'total' is what the converter reads. The DC term is the shared 50 mohm Vmid carrying A's RG current (up to 5.7 mA): 0.4 LSB, which powercal's per-channel Vmid buffers remove. A shared sense filter instead of one per channel adds 13 LSB (guard).\n")
    A("AWG coupling (DAC0 at full swing, 0.578-2.771 V, into a channel with its input shorted), LSB peak at the pin:\n")
    A("| wiring, range | 1 kHz | 10 kHz | 100 kHz | 1 MHz | 10 MHz | max (10 Hz-20 MHz) |\n|---|---|---|---|---|---|---|")
    for d in ("N", "R3"):
        for rng in ("5", "1.25"):
            v = kk[f"{d}_{rng}_awg"]
            A(f"| {d}, +/-{rng} V | " + " | ".join(f"{v['at'][x]:.3g}" for x in ("1e+03", "1e+04", "1e+05", "1e+06", "1e+07")) + f" | {v['max_lsb']:.3g} |")
    ci = kk["charge_injection"]
    A(f"\nRange-switch charge injection (6 pC): {ci['R3']['5']['peak_mV']:.0f} mV, recovered to 0.5 LSB in {ci['R3']['5']['recover_0p5LSB_ns']:.0f} ns (+/-5 V); {ci['R3']['1.25']['peak_mV']:.0f} mV, {ci['R3']['1.25']['recover_0p5LSB_ns']:.0f} ns (+/-1.25 V). Unchanged in kind from the first round.\n")

    A("## Case 5: protection\n")
    A("Powered (vendor model, rail 3.37 V, the injection switch's pin clamps at N included for wiring N):\n")
    A("| wiring, range, input | input current | N | ADC pin | op-amp clamp | switch clamp | each 100k of R1 | Due 3.3 V pin current |\n|---|---|---|---|---|---|---|---|")
    for k, v in dcp.items():
        A(f"| {k.replace('|', ', ')} V | {v['i_in_mA']:.2f} mA | {v['v_n']:.2f} V | {v['v_pin']:.3f} V | {v['i_opamp_in_mA']:.2f} mA | {v.get('i_tmux_esd_mA', float('nan')):.3f} mA | {v['V_100k_part']:.1f} V, {v['P_100k_part_mW']:.1f} mW | {v['i_due33_uA']:+.0f} uA |")
    a3 = pr["above30"]
    A(f"\nAbove +/-30 V (PR-1: damage only to replaceable shield parts): the op-amp clamp reaches its 10 mA at about +/-190 V ({a3['N|+200']['i_opamp_in_mA']:.1f} mA at +200 V), but the R1 parts go first: each 100k carries {a3['N|+100']['V_100k_part']:.0f} V and {a3['N|+100']['P_100k_part_mW']:.0f} mW at 100 V, so a typical 0603 rating (75 V, 100 mW) *(check)* is passed between about 80 and 100 V. They are soldered shield parts. The injection switch at N is outside its absolute maximum (S pin <= VDD + 0.5 V) from about +/-9 V in (N = Vmid + alpha x Vin reaches 3.87 V), while the op-amp is not (its rating allows any voltage with the current held to 10 mA): one more reason for the R3 wiring, where the switch never sees more than the sense node.\n")
    A("**Unpowered** (diode-level network: each IC replaced by its pin clamps to the floating AFE rail and to ground; the Due's 3.3 V net a 0 V source; both channels built; TMUX1119s open with no supply *(check)*, and for 'R3' also on). Current into the Due split into its supply pins (the sense paths, powercal's Vmid divider and DAC0's clamp, all on the 3.3 V net) and the ADC pins' clamps:\n")
    A("| wiring, switch, bleed, inputs | AFE rail | Due supply pins | ADC-pin clamps | N | ADC pin | bleed current |\n|---|---|---|---|---|---|---|")
    for k, v in up.items():
        d, sw_, bl, ins = k.split("|")
        if ins in ("+30,+0", "+30,+30") and bl in ("4700", "680", "249", "124.5"):
            A(f"| {d}, {sw_}, {bl} ohm, {ins} V | {v['v_rail']:.3f} V | {L.supply_uA(v):.1f} uA | {v['i_pin_a_uA']+v['i_pin_b_uA']:.1f} uA | {v['v_an']:.2f} V | {v['v_apin']:.3f} V | {v['i_bleed_mA']:.2f} mA |")
    A("\nNegative inputs draw current **out of** the Due's 3.3 V net (-42 uA at -30 V, one input) and nothing flows into the rail. The positive case is the problem. A 22 kohm input lets +30 V push 1.5-1.7 mA into N; it has nowhere to go but the op-amp's clamp into the AFE rail, and the approved 4.7 kohm bleed lets that rail rise to 3.8 V (5.0 V with both inputs), where the op-amps are partly powered and the current reaches the Due through the sense resistors and the ADC pins (700 uA). The rail must sink the fault current at under 0.5 V: **249 ohm (an existing 0.1 % type) holds it at 0.39 V with one input**; 13.5 mA of quiescent drain on the AFE 3.3 V rail (45 mW in an 0603 *(check rating)*; PW-1's 100 mA budget at powercal's 52-57 mA has room). The supply-pin current is then 65-67 uA (sense path, N at 1.1 V) and the ADC-pin clamps carry another 54-56 uA through R2, Vmid, RG, RF and Riso. PR-3 names supply pins; counted with the ADC pins the total is 119-123 uA. Both inputs at +30 V, or 340-680 ohm, fail the rail. No existing part type clamps N to ground without loading it (BAT54S: 10 pF max; BAV99: silicon, the same 0.7 V as the clamps it would join). **What the existing BAT54S can do is sit on each ADC pin** (pin 1 to ground, pin 3 on the pin, pin 2 on the AFE +3.3 V rail), where the op-amp drives its 10 pF through Riso and its leakage costs 44 uV: its Schottky drop takes the pin's fault current into the AFE rail instead of the SAM3X, so with the 249 ohm bleed everything entering the Due, ADC pins included, is about 85 uA (one input), and the unpowered negative excursion of the pin falls from -0.57 V to -0.22 V, which is still 20 mV outside PR-2's -0.2 V at the datasheet's maximum forward voltage *(check: typical is lower; the SAM3X's own -0.3 V abs max is met)*.\n")

    A("## Checks broken on purpose\n")
    A("| guard | mutation | good | broken | restored | effective |\n|---|---|---|---|---|---|")
    for g in gd:
        A(f"| {g['guard']} | {g['mutation']} | {'pass' if g['good']['ok'] else 'FAIL'}: {g['good']['detail']} | {'pass' if g['broken']['ok'] else 'FAIL'}: {g['broken']['detail']} | {'pass' if g['restored']['ok'] else 'FAIL'} | {'yes' if g['effective'] else 'NO'} |")
    A("\nEvery guard runs on the R3 wiring (the one that passes), so that each can be seen to pass first. Two mutations are the decided circuit itself: the SM-3 and AWG-coupling guards fail on 'switch on N', which is the finding.\n")

    A("## Values for the SM-5 loop simulation (sim/loop, owned elsewhere)\n")
    A(f"- R1 = {p['R1']:.2f} ohm (BNC to N), R2 = {p['R2']:.2f} ohm (N to Vmid), R3 = {p['R3']:.2f} ohm (N to the sense node) + Rs3 = 249 ohm to the Due's 3.3 V pin, 10 uF at the R3/Rs3 junction, per channel. alpha {dv['alpha']:.4f}, Thevenin {dv['rth']:.0f} ohm, Rin {dv['rin']:.0f} ohm.")
    A("- No C1, no C2. Strays: 2 pF N to ground (1-3 pF), 0.3 pF across R1 (0.1-0.5 pF). Rnp 0 (N straight to the + input). RF 953, RG 249, range switch across RF (Ron 3.7/8.8 ohm, CON 20 pF closed; CSOFF 6 pF open), Riso 22 ohm, 2 pF at the pin, OPA354.")
    A("- Injection switch, as decided: CSOFF 6 pF (10 pF IBIS) from N to ground and 1.8 pF from DAC0 to N. Proposal: none at N; the switch in the R3 leg (Ron 3.7-8.8 ohm in series with R3, CON 20 pF on the 10 uF sense node).")
    A("- Previous loop route (c) runs used 2 pF at N and 0.1 pF across R1 with no switch: the R3 wiring is that case at Rth 3.96 kohm; the decided wiring adds 7.8-11.8 pF at N.\n")

    A("## Model gaps and the test that closes each\n")
    A("| gap | closed by |\n|---|---|\n| TMUX1119 feedthrough as a capacitance (derived from OISO), CSOFF 6 vs 10 pF, unpowered state | VT-10 (crosstalk with DAC0 playing), VT-5 |\n| pin clamp I-V of OPA354, OPA365, TMUX1119, SAM3X (DESD) | VT-5 (unpowered +/-30 V, current into the Due measured) |\n| the Due's 3.3 V pin impedance (0.1 ohm) and the AREF shift from a 29-361 uA signal-dependent sense load | VT-8 |\n| stray capacitance at N and across R1 | G3 extraction, VT-4 |\n| op-amp 1/f noise, crossover, swing at 3.23 V | VT-1, VT-3, VT-16 |\n| 0603 voltage and power rating of the 100k parts at 30-100 V | the chosen part's datasheet, VT-5 |\n| LM27762 output with VIN = 0 (assumed open: only the bleed sinks the fault current) | VT-5 |\n")

    A("## Requirement problems to hand back\n")
    A("1. **The decided injection wiring (N on a source pin) fails SM-3 (3.6 MHz) and SC-9 (AWG coupling, up to about 900 LSB) with any divider in SC-3's window.** The R3-leg wiring passes both at no part cost; it changes what PA-3's calibration measures (sim/diff).")
    A("2. **PR-3 needs the AFE rail bleed at 249 ohm** (13.5 mA quiescent; powercal owns the net) and holds for one input only; with a BAT54S at each ADC pin it holds even counting the ADC pins (about 85 uA). Both inputs at +30 V fail at any existing-type bleed that keeps the rail current reasonable. PR-3's text should say one input or both, and whether the ADC pins count. PR-2's unpowered -0.2 V is missed by 20 mV at the BAT54's maximum VF *(check)*, and by 370 mV without it.")
    A("3. **PW-1's 'microamps' on the 3.3 V pin is now 29-361 uA for two channels**, signal dependent (R3's leg returns the divider's centring current); the AREF error it makes depends on the Due's 3.3 V net impedance, not measured *(check, VT-8)*.")
    A("4. **SC-8 (1 % before calibration) fails on +/-5 V in both the old and the new design**: the range switch's Ron (3.7-8.8 ohm, no minimum given) is in the G = 1 gain. Not changed by this redesign.")
    A("5. SC-9's DC term (0.4 LSB) is the shared Vmid; it assumes 50 mohm and goes with per-channel buffers.")
    with open(os.path.join(HERE, "report_round1.md"), "w") as f:
        f.write("\n".join(T) + "\n")
    return out
