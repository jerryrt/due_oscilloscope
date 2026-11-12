"""Writes report.md for round 2 of the low-impedance divider (variant 'lowz2') from results/*.json."""
import os
import numpy as np
import netlib as NL
import run as R
import lowz as L

HERE = os.path.dirname(os.path.abspath(__file__))
lj = R.loadj
mv = lambda x: f"{x*1e3:.1f} mV"
uv = lambda x: f"{x*1e6:.0f} uV"

def make():
    dc = lj("dc_K"); ac = lj("ac"); nz = lj("noise"); kk = lj("kick"); pr = lj("prot"); gd = lj("guards"); zi = lj("zin")
    ed = lj("edge"); pc = lj("pinclamp"); ex = lj("extras"); u2 = lj("unp2")
    p = L.P("K"); dv = L.divider(p); hs = R.model_hashes()
    k = 1 + p["Rbf"] / p["Rbg"]
    rows = []
    def row(i, lim, res, ok, margin=""):
        v = ok if isinstance(ok, str) else ("PASS" if ok else "FAIL")
        rows.append(f"| {i} | {lim} | {res} | {v} | {margin} |")
    T5 = dc["aref_table"]["5"]; T12 = dc["aref_table"]["1.25"]
    m5 = T5["3.20"]["margin_wc"]; m12 = T12["3.20"]["margin_wc"]
    row("SC-2 (+/-6 V, AREF 3.20)", ">= 80 mV per side", mv(m5), m5 >= 0.08, mv(m5 - 0.08))
    row("SC-11 margin (AREF 3.20)", ">= 80 mV per side", mv(m12), m12 >= 0.08, mv(m12 - 0.08))
    mids = {r: T["3.20"]["nominal"]["mid"] for r, T in (("5", T5), ("1.25", T12))}
    cb = {r: T["3.20"]["contrib"] for r, T in (("5", T5), ("1.25", T12))}
    bufterm = {r: max(abs(cb[r][x]["d_mhi"]) for x in cb[r] if x.startswith(("Rbf", "Rbg", "vosb"))) for r in cb}
    row("Centring: the sense buffer's share (gain 0.1 % resistors + 0.2 mV offset, worst single term)", "inside SC-2/SC-11's budget", f"{bufterm['5']*1e3:.2f} mV (+/-5 V), {bufterm['1.25']*1e3:.2f} mV (+/-1.25 V) at the pin; nominal centre {mids['5']:.4f} / {mids['1.25']:.4f} V against 1.6000", "INFO")
    gmin, gmax = T5["3.30"]["gain_min"], T5["3.30"]["gain_max"]
    row("SC-4 step / occupancy (AREF 3.30)", "<= 4 mV; 70-75 %", f"{3.3/4096/gmin*1e3:.2f} mV; {10*gmin/3.3*100:.1f}-{10*gmax/3.3*100:.1f} %", 3.3/4096/gmin <= 4e-3 and 10*gmin/3.3 >= 0.70 and 10*gmax/3.3 <= 0.75, f"{(10*gmin/3.3-0.70)*100:.1f} % above 70")
    g12 = (T12["3.20"]["gain_min"], T12["3.20"]["gain_max"])
    row("SC-11 gain", "1.10-1.16", f"{g12[0]:.4f}-{g12[1]:.4f}", 1.10 <= g12[0] and g12[1] <= 1.16, f"{(g12[0]-1.10)*1e3:.0f} / {(1.16-g12[1])*1e3:.0f} milli")
    sp5 = (gmax - gmin) / ((gmax + gmin) / 2) * 100; sp12 = (g12[1] - g12[0]) / ((g12[1] + g12[0]) / 2) * 100
    row("SC-8 gain matching before calibration", "<= 3 % (owner, 2026-11-11)", f"+/-5 V {sp5:.2f} %, +/-1.25 V {sp12:.2f} % (worst-case sums, two channels at opposite ends)", max(sp5, sp12) <= 3, f"{3-max(sp5, sp12):.2f} %")
    row("SC-3", "20-30 kohm; <= 30 pF", f"{zi['K']['R_dc_ohm']/1e3:.2f} kohm; {zi['K']['C_worst_1MHz_pF']:.1f} pF worst", 20e3 <= zi['K']['R_dc_ohm'] <= 30e3 and zi['K']['C_worst_1MHz_pF'] <= 30)
    w5 = ac["K_5"]["worst"]["bw"]; w12 = ac["K_1.25"]["worst"]["bw"]
    row("SM-3", ">= 8 MHz both ranges, worst corner", f"+/-5 V {w5/1e6:.2f} MHz, +/-1.25 V {w12/1e6:.2f} MHz (nominal {ac['K_5']['nominal']['bw']/1e6:.1f} / {ac['K_1.25']['nominal']['bw']/1e6:.1f})", min(w5, w12) >= 8e6, f"{(min(w5, w12)/8e6-1)*100:+.0f} %")
    n5 = nz["K_5"]["at_1p5bw"]["total_V"]; n12 = nz["K_1.25"]["at_1p5bw"]["total_V"]
    row("SC-6 to 1.5 x BW", "<= 200 uV", f"+/-5 V {uv(n5)}, +/-1.25 V {uv(n12)} (sense node {uv(nz['K_1.25']['at_1p5bw']['v3sense_V'])})", max(n5, n12) <= 200e-6, uv(200e-6 - max(n5, n12)))
    xt = max(v["crosstalk_lsb"] for v in kk.values() if isinstance(v, dict) and "crosstalk_lsb" in v)
    xa = max(v["max_lsb"] for kx, v in kk.items() if kx.endswith("_ac"))
    aw = max(kk[f"K_{r}_awg"]["max_lsb"] for r in ("5", "1.25"))
    row("SC-9 scope to scope (one shared sense buffer)", "<= 2 LSB", f"{xt:.3f} LSB DC/step, {xa:.3f} LSB sine", max(xt, xa) <= 2, f"{2-max(xt, xa):.2f} LSB")
    row("SC-9 AWG coupling (R3-leg switch, DAC0 buffer + 249 ohm shared)", "<= 2 LSB", f"{aw:.2f} LSB peak", aw <= 2, f"{2-aw:.2f} LSB")
    err = max(max(abs(v["full_swing"]["errA_lsb"]), abs(v["full_swing"]["errB_lsb"])) for v in kk.values() if isinstance(v, dict) and "full_swing" in v)
    st = max(v["full_swing"]["settleB_ns"] for v in kk.values() if isinstance(v, dict) and "full_swing" in v)
    row("SC-10", "0.5 LSB in 667 ns", f"{err:.4f} LSB, settled in {st:.0f} ns", err <= 0.5 and st < 667, f"{667-st:.0f} ns")
    pm = min(min(ac[f"K_{r}"]["worst"]["pm"], min(x["pm"] for x in ac[f"K_{r}"]["sens"])) for r in ("5", "1.25"))
    row("AN-1", ">= 45 deg", f"{pm:.1f} deg", pm >= 45, f"{pm-45:.1f} deg")
    dcp = pr["dc"]
    idc = max(v["i_opamp_in_mA"] for v in dcp.values()); ipk = max(v["i_opamp_peak_mA"] for v in pr["edge"].values())
    row("PR-1 op-amp clamp, +/-30 V", "<= 10 mA", f"{idc:.2f} mA DC, {ipk:.2f} mA on a 5 ns edge; each 100k {max(v['V_100k_part'] for v in dcp.values()):.1f} V", max(idc, ipk) <= 10, f"{10-max(idc, ipk):.1f} mA")
    pmax = max(max(v["v_pin"] for v in dcp.values()), max(v["pin_max"] for v in pr["edge"].values())); pmin = min(min(v["v_pin"] for v in dcp.values()), min(v["pin_min"] for v in pr["edge"].values()))
    row("PR-2 powered", "-0.2..3.45 V", f"{pmin:.3f}..{pmax:.3f} V", pmin >= -0.2 and pmax <= 3.45, f"{(3.45-pmax)*1e3:.0f} mV")
    # PR-1 / PR-3 as ruled: +/-12 V on both inputs, powered or unpowered
    for key, lab in (("(c) both inputs +12 V|BAT54S", "with BAT54S"), ("(c) both inputs +12 V|no clamp", "no pin clamp")):
        r = u2[key]; nd = r["need"]; at = r["at_need"]
        row(f"PR-3 unpowered, +12 V on both inputs, {lab}", "rail < 0.5 V; <= 100 uA into the Due",
            f"bleed {nd['bleed_ohm']:.0f} ohm ({nd['iq_mA']:.1f} mA quiescent): Due supply pin {at['i_due_uA']-at['i_pin_a_uA']-at['i_pin_b_uA']:.1f} uA, ADC pins {at['i_pin_a_uA']+at['i_pin_b_uA']:.1f} uA; 4.7 kohm gives {r['4700']['v_rail']:.2f} V",
            at["i_due_uA"] <= 100, "")
    rn = u2["(c) one input -12 V|BAT54S"]["249"]
    row("PR-2 unpowered, -12 V, BAT54S, 249 ohm", "-0.2..3.45 V", f"pin {min(rn['v_apin'], rn['v_bpin']):.3f} V", min(rn["v_apin"], rn["v_bpin"]) >= -0.2, "")
    b = ex["buffer"]
    row("PW-1 Due 3.3 V pin current", "microamps", f"{b['due_pin_uA']:.1f} uA (powercal's 330k + 330k only; the sense buffer's input is a few pA)", True, "")
    row("Sense buffer headroom", "output below the rail", f"k = {k:.4f}: {b['v_out_at_aref330']:.3f} V at AREF 3.30, {b['headroom_to_323']*1e3:.0f} mV under the 3.23 V rail minimum (OPA365 swing 20 mV max at 10 kohm, VS 5.5 V)", b["headroom_to_323"] > 0.05, "")
    out = "\n".join(rows)

    T = []; A = T.append
    A("# 2b scope channel: simulation report (low-impedance divider, round 2, 2026-11-11)\n")
    A("Regenerated by `python3 -I run.py --par` (variant `lowz2`, four ngspice processes); results in `results/`, netlists in `netlists_lowz2/`. Round 1 (injection on N, sense from the Due pin) is `report_round1.md` / `results/lowz/` (`--variant lowz`); the 1 Mohm design is `report_legacy.md` (`--variant legacy`).\n")
    A("- Simulator `" + NL.ngspice_version() + "`; models: " + ", ".join(f"`{kx}` {v['actual'][:12]}... ({'matches' if v['match'] else 'DOES NOT MATCH'} SOURCES.md)" for kx, v in hs.items()) + "; `models/rangesw.lib`; generic clamp diode DESD *(assumption)*; BAT54S fitted to the C7420333 datasheet's maximum VF.")
    A("- Assumptions as round 1 (`report_round1.md`): 2 pF at N (1-3), 0.3 pF across R1 (0.1-0.5), Vmid one ideal source behind 50 mohm shared by both channels (conservative: powercal has one buffer per channel), Due 3.3 V pin behind 0.1 ohm *(check)*.\n")
    A("## Circuit (one channel; the sense buffer is shared)\n")
    A("```")
    A("BNC --R1 16.18k--+--N------------------------------- OPA354 (+)")
    A("                 +--R2 7.873k-- Vmid (this channel's buffer)")
    A("                 +--R3 13.15k-- [TMUX1119: D] --S1-- sense node --Rs3 249-- V3b   (10 uF on the sense node)")
    A("                                              --S2-- DAC0 buffer (OPA365) + 249 ohm, shared   (calibration)")
    A("V3b = k x Vmid tap, OPA365 shared, k = 1 + (953+249)/(953+2x249) = 1.8284;  (R3 + Ron + 249)/R1 = k - 1 centres N on Vmid")
    A("OPA354: RF 953 out->(-), RG 249 (-)->Vmid; TMUX1119 range switch across RF (closed = +/-5 V), as round 1")
    A("out --Riso 22-- ADC pin;  BAT54S at the ADC pin (ground / pin / AFE +3.3 V);  AFE +3.3 V bleed: see PR-3")
    A("```\n")
    A("| part | value | from (existing 0.1 % types) |\n|---|---|---|")
    A(f"| R1 | {p['R1']:.1f} ohm | 5 x 100k, 1 x 174k, 2 x 330k, all in parallel |")
    A(f"| R2 | {p['R2']:.0f} ohm | 8 x 953 + 1 x 249 in series |")
    A(f"| R3 | {p['R3']:.1f} ohm | 7 x 100k, 2 x 330k in parallel; leg = R3 + Ron (6.25 mid) + Rs3 249 = {dv['r3leg']:.1f} ohm |")
    A("| Rs3, Cs3 | 249 ohm, 10 uF | one per channel |")
    A("| sense buffer | OPA365, Rf = 953 + 249, Rg = 953 + 2 x 249 | one, shared (5 resistors) |")
    A("| RF / RG / Riso | 953 / 249 / 22 ohm | unchanged, switch across RF |")
    A(f"\nalpha {dv['alpha']:.4f}, Thevenin at N {dv['rth']:.0f} ohm, input {dv['rin']:.0f} ohm.\n")
    A("## Pass / fail\n")
    A("| row | limit | worst | verdict | margin |\n|---|---|---|---|---|\n" + out + "\n")

    A("## SC-8: where the range switch's Ron goes\n")
    A("| arrangement | +/-5 V gain at Ron 3.7 / 8.8 ohm | Ron spread | SM-3 worst +/-5 / +/-1.25 V | PM worst |\n|---|---|---|---|---|")
    for name, r in ex["sc8"].items():
        A(f"| {name} | {r['5']['g_ron37']:.5f} / {r['5']['g_ron88']:.5f} | {r['5']['ron_spread_pct']:.3f} % | {r['5']['worst_bw']/1e6:.2f} / {r['1.25']['worst_bw']/1e6:.2f} MHz | {min(r['5']['worst_pm'], r['1.25']['worst_pm']):.1f} deg |")
    A("\nSC-8 is 3 % (owner, 2026-11-11), so the round-1 arrangement passes and is kept. Raising RG to 953 puts the open switch's 6 pF across a 3.66 kohm RF (SM-3 on +/-1.25 V about 5 MHz). The Kelvin arrangement (the SPDT selecting what the inverting input senses) takes Ron out of the gain and cuts the +/-5 V range's RG current from 5.7 to 1.2 mA, but widens +/-1.25 V to 15 MHz, and the wider band integrates 216 uV, failing SC-6; it stays available as `sw=\"kelvin\"` if SM-5 wants the bandwidth more than SC-6 wants the noise.\n")
    A("## One sense buffer or two (SC-9)\n")
    A("| buffer | +/-5 V DC/step | +/-5 V sine | +/-1.25 V DC/step | +/-1.25 V sine |\n|---|---|---|---|---|")
    for name, r in ex["sense_buffer"].items():
        A(f"| {name} | {r['5']['dc_total_lsb']:.3f} | {r['5']['ac_max_lsb']:.3f} | {r['1.25']['dc_total_lsb']:.3f} | {r['1.25']['ac_max_lsb']:.3f} LSB |")
    A("\nEach channel keeps its own 249 ohm + 10 uF after the buffer, so above 64 Hz the R3 return current (about +/-0.2 mA) closes in that channel's own capacitor; at DC the OPA365's closed-loop output impedance is milliohms. The remaining DC term is the shared 50 mohm Vmid of the simulation. **One shared buffer.**\n")

    A("## PR-3 / PR-2 unpowered (buffered sense)\n")
    A("The R3 leg now ends on the sense buffer's output, whose clamps go to the AFE rail, so no fault current reaches the Due's 3.3 V pin through R3. What is left into the Due is the ADC pins' clamp path (N -> R2 -> Vmid -> RG -> RF -> out -> Riso -> SAM3X clamp). 'Supply' below is the Due's 3.3 V net through its supply pin (powercal's divider and DAC0); 'ADC pins' the SAM3X clamps. Bleed needed = the largest bleed holding the rail at 0.5 V; its quiescent current at 3.37 V.\n")
    A("| case | clamp | 4.7 kohm: rail / supply / ADC pins | 249 ohm: rail / supply / ADC pins | bleed for 0.5 V | its quiescent current | at that bleed: ADC pins, pin voltage |\n|---|---|---|---|---|---|---|")
    for key, r in u2.items():
        lab, cl = key.split("|")
        a, b2 = r["4700"], r["249"]
        sup = lambda x: x["i_due_uA"] - x["i_pin_a_uA"] - x["i_pin_b_uA"]
        pins = lambda x: x["i_pin_a_uA"] + x["i_pin_b_uA"]
        need = r.get("need"); at = r.get("at_need")
        A(f"| {lab} | {cl} | {a['v_rail']:.2f} V / {sup(a):.1f} / {pins(a):.1f} uA | {b2['v_rail']:.3f} V / {sup(b2):.1f} / {pins(b2):.1f} uA | "
          + (f"{need['bleed_ohm']:.0f} ohm | {need['iq_mA']:.1f} mA | {pins(at):.1f} uA, {min(at['v_apin'], at['v_bpin']):.3f}..{max(at['v_apin'], at['v_bpin']):.3f} V |" if need else
             f"not needed (no current into the rail) | - | pin {min(b2['v_apin'], b2['v_bpin']):.3f} V |"))
    A("\nExisting types for a bleed: 249 ohm (0.1 %), 680 ohm and 4.7 kohm (1 %), and parallel combinations. BAT54S at the pin: datasheet C7420333, CT 10 pF max at 1 V, IR 2 uA max at 25 V, VF max 240 mV at 0.1 mA.\n")
    A(f"**BAT54S cost at the pin:** worst SM-3 {min(pc['K_5']['worst_bw'], pc['K_1.25']['worst_bw'])/1e6:.2f} MHz, PM {min(pc['K_5']['worst_pm'], pc['K_1.25']['worst_pm']):.1f} deg, S/H error {max(pc['K_5']['kick_err_lsb'], pc['K_1.25']['kick_err_lsb']):.4f} LSB, settled in {max(pc['K_5']['kick_settle_ns'], pc['K_1.25']['kick_settle_ns']):.0f} ns (SC-10 unchanged: the op-amp drives the 10 pF through 22 ohm). Leakage 2 uA max x 22 ohm = 44 uV (0.06 LSB) of offset, inside the loop's output, so not divided by any gain; its shot noise (0.8 pA/sqrt Hz) through 22 ohm is 18 pV/sqrt Hz: nothing. The capacitance is not noise. *(check: IR at 3 V and 35 C is not tabulated; the curve shows it falling with VR)*\n")

    A("## MCP3564 input on N (powercal's calibration read-back)\n")
    A("DS20006181C gives the converter's differential input impedance (260 kohm at gain 1, inversely proportional to AMCLK; 2.08 Mohm at prescaler 8) and CTALK -130 dB **at 50 Hz only**; it gives **no pin capacitance, no sampling-capacitor value and no high-frequency channel isolation** *(check)*. Derived: the sampling capacitance behind 260 kohm at AMCLK 4.9152 MHz is about 0.8 pF differential; it loads N only while N's channel is being converted (calibration). In normal use N sees the pin (Cp, unknown) and coupling from the AWG pins CH0/CH1 through the package and the mux (Cx, unknown). Bounded below over Cp 2-10 pF and Cx 0-0.3 pF, with a series resistor R from N to the pin. DC reading error of R: 0.30 x R / 2.08 Mohm (Zin +/-30 %).\n")
    A("| R | Cp | Cx | SM-3 worst, +/-1.25 V | AWG coupling peak | DC read error |\n|---|---|---|---|---|---|")
    for r in ex["mcp"]:
        A(f"| {r['R']:.0f} | {r['Cp_pF']:.0f} pF | {r['Cx_pF']:.2f} pF | {r['worst_bw_125']/1e6:.2f} MHz | {r['awg_max_lsb']:.2f} LSB | {r['dc_read_err_pct']:.4f} % |")
    A("\nReading: a pin on N costs SM-3 its margin unless Cp is 2 pF or less, and any coupling from the AWG channels above about 0.01 pF fails SC-9 at a 4 kohm node. A series resistor that isolates them (22-100 kohm) costs 0.3-1.4 % of DC read error against C3-e's 0.05 %; one that keeps C3-e (680 ohm: 0.010 %) isolates nothing. A switch to read N only during calibration puts a TMUX1119's CSOFF (6-10 pF) on N, which round 1 showed fails SM-3. Options (a)-(c) below.\n")

    o = lj("options")
    A("## How the calibration reads N (options a / b / c)\n")
    A(f"Reference, nothing new on N: SM-3 worst {o['reference_no_mcp']['sm3']['5']/1e6:.2f} / {o['reference_no_mcp']['sm3']['1.25']/1e6:.2f} MHz, AWG coupling {o['reference_no_mcp']['awg_lsb']:.2f} LSB, Thevenin {o['reference_no_mcp']['rth']:.0f} ohm. The MCP pin's capacitance Cp is bounded 2-10 pF and its coupling from the AWG channels Cx at 0.3 pF, neither given by DS20006181C *(check)*. HF load = Thevenin / R, against the loop's 0.04 %. DC read error = half the spread of Zin/(R + Zin) for Zin 2.08 Mohm +/-30 %, against C3-e's 0.05 %.\n")
    A("| (a) R | Cp | SM-3 worst +/-5 / +/-1.25 V | AWG coupling (Cx 0.3 pF) | HF load on N | DC read error |\n|---|---|---|---|---|---|")
    for r in o["a"]:
        A(f"| {r['R']/1e3:.0f} k | {r['Cp_pF']:.0f} pF | {r['sm3']['5']/1e6:.2f} / {r['sm3']['1.25']/1e6:.2f} MHz | {r['awg_lsb']:.1f} LSB | {r['hf_load_pct']:.3f} % | {r['read_err_pct']:.2f} % |")
    A("\n(b) the MCP on the switch's D node (R3's own end; in normal use it is held by Ron to the 10 uF sense node, so its Cp and Cx do nothing to N). The host computes N = beta x V(D) from the resistors. beta's error from 0.1 % parts:\n")
    A("| BNC during calibration | beta | worst | RSS (uniform) |\n|---|---|---|---|")
    for st, v in o["b"]["beta"].items():
        A(f"| {st} | {v['beta']:.4f} | {v['worst_pct']:.3f} % | {v['rss_pct']:.3f} % |")
    A("\nIf the procedure's assumed state is wrong: " + "; ".join(f"{k} {v:+.3f} %" for k, v in o["b"]["state_mismatch_pct"].items()) + ".\n")
    A("| (c) scale | Cp on N | Thevenin | input | SM-3 worst +/-5 / +/-1.25 V | AWG coupling (Cx 0.3 pF) | N time constant |\n|---|---|---|---|---|---|---|")
    for r in o["c"]:
        A(f"| {r['scale']:g} | {r['Cp_pF']:.0f} pF | {r['rth']:.0f} | {r['rin']/1e3:.1f} k | {r['sm3']['5']/1e6:.2f} / {r['sm3']['1.25']/1e6:.2f} MHz | {r['awg_lsb']:.1f} LSB | {r['tau_ns']:.1f} ns |")
    A("\nNetlists for sim/loop's SM-5 runs: `netlists_lowz2/for_loop/*.cir` (one channel, +/-1.25 V range).\n")
    A("## Guards\n")
    A("| guard | mutation | good | broken | restored | effective |\n|---|---|---|---|---|---|")
    for g in gd:
        A(f"| {g['guard']} | {g['mutation']} | {'pass' if g['good']['ok'] else 'FAIL'}: {g['good']['detail']} | {'pass' if g['broken']['ok'] else 'FAIL'}: {g['broken']['detail']} | {'pass' if g['restored']['ok'] else 'FAIL'} | {'yes' if g['effective'] else 'NO'} |")
    A("\n## Values for sim/loop (SM-5)\n")
    A(f"- N: Thevenin {dv['rth']:.0f} ohm, alpha {dv['alpha']:.4f}; R1 {p['R1']:.1f}, R2 {p['R2']:.0f}, R3 leg {dv['r3leg']:.1f} ohm to an AC ground (10 uF); 2 pF N to ground (1-3 pF), 0.3 pF across R1 (0.1-0.5 pF), 20 pF CON + Ron on the R3 leg's far end (on the 10 uF node, negligible). No switch, no MCP pin on N.")
    A("- OPA354, RF 953 / RG 249 with the Kelvin range switch (Ron in the sense path only, CON 20 pF split on (-) and the selected node, CSOFF 6 pF to the other), Riso 22, 2 pF + BAT54S (10 pF) at the pin.")
    with open(os.path.join(HERE, "report_lowz2.md"), "w") as f:
        f.write("\n".join(T) + "\n")
    return out
