"""Writes report.md for the default variant 'hz' (1 Mohm compensated divider, 2026-11-11 pivot) from results/*.json."""
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
    dc = lj("dc_H"); ac = lj("ac"); nz = lj("noise"); kk = lj("kick"); pr = lj("prot"); gd = lj("guards"); zi = lj("zin")
    ed = lj("edge"); cp = lj("comp")
    p = L.P("H"); hs = R.model_hashes()
    g1, g2, g3 = 1 / p["R1"], 1 / p["R2"], 1 / p["R3"]; alpha = g1 / (g1 + g2 + g3); rth = 1 / (g1 + g2 + g3)
    rows = []
    def row(i, lim, res, ok, margin=""):
        v = ok if isinstance(ok, str) else ("PASS" if ok else "FAIL")
        rows.append(f"| {i} | {lim} | {res} | {v} | {margin} |")
    T5 = dc["aref_table"]["5"]; T12 = dc["aref_table"]["1.25"]
    m5 = T5["3.20"]["margin_wc"]; m12 = T12["3.20"]["margin_wc"]
    row("SC-2 (+/-6 V, AREF 3.20)", ">= 80 mV per side", mv(m5), m5 >= 0.08, mv(m5 - 0.08))
    gmin, gmax = T5["3.30"]["gain_min"], T5["3.30"]["gain_max"]
    row("SC-4 step / occupancy (AREF 3.30)", "<= 4 mV; 70-75 %", f"{3.3/4096/gmin*1e3:.2f} mV; {10*gmin/3.3*100:.1f}-{10*gmax/3.3*100:.1f} % (DC gain)", 3.3/4096/gmin <= 4e-3 and 10*gmin/3.3 >= 0.70 and 10*gmax/3.3 <= 0.75, f"{75-10*gmax/3.3*100:.1f} % under 75")
    g12 = (T12["3.20"]["gain_min"], T12["3.20"]["gain_max"])
    row("SC-11 gain / margin (AREF 3.20)", "1.10-1.16; >= 80 mV", f"{g12[0]:.4f}-{g12[1]:.4f}; {mv(m12)}", 1.10 <= g12[0] and g12[1] <= 1.16 and m12 >= 0.08, f"{(g12[0]-1.10)*1e3:.0f} / {(1.16-g12[1])*1e3:.0f} milli; {mv(m12-0.08)}")
    sp5 = (gmax - gmin) / ((gmax + gmin) / 2) * 100; sp12 = (g12[1] - g12[0]) / ((g12[1] + g12[0]) / 2) * 100
    row("SC-8 gain match before calibration", "<= 3 %", f"+/-5 V {sp5:.2f} %, +/-1.25 V {sp12:.2f} %", max(sp5, sp12) <= 3, f"{3-max(sp5, sp12):.2f} %")
    z = zi["H"]
    row("SC-3", "1 Mohm; <= 30 pF", f"{z['R_dc_ohm']/1e6:.4f} Mohm; {z['C_1e+06_pF']:.1f} pF at 1 MHz", z["C_1e+06_pF"] + 1.2 <= 30, f"{30-z['C_1e+06_pF']-1.2:.1f} pF")
    w5 = ac["H_5"]["worst"]["bw"]; w12 = ac["H_1.25"]["worst"]["bw"]
    row("SM-3", ">= 8 MHz both ranges, worst corner", f"+/-5 V {w5/1e6:.1f} MHz, +/-1.25 V {w12/1e6:.2f} MHz", min(w5, w12) >= 8e6, f"{(min(w5, w12)/8e6-1)*100:+.0f} %")
    n5 = nz["H_5"]["at_1p5bw"]["total_V"]; n12 = nz["H_1.25"]["at_1p5bw"]["total_V"]
    row("SC-6 to 1.5 x BW", "<= 200 uV", f"+/-5 V {uv(n5)} ({nz['H_5']['at_1p5bw']['fmax']/1e6:.0f} MHz), +/-1.25 V {uv(n12)}", max(n5, n12) <= 200e-6, uv(200e-6 - max(n5, n12)))
    xt = max(v["crosstalk_lsb"] for v in kk.values() if isinstance(v, dict) and "crosstalk_lsb" in v)
    xa = max(v["max_lsb"] for k, v in kk.items() if k.endswith("_ac"))
    row("SC-9 scope to scope (per-channel Vmid, P8-k)", "<= 2 LSB", f"{xt:.4f} LSB DC/step, {xa:.4f} LSB sine 1 Hz-200 MHz", max(xt, xa) <= 2, f"{2-max(xt, xa):.2f} LSB")
    row("SC-9 AWG coupling", "<= 2 LSB", "no injection switch on N (BNC-tee calibration): no AWG path into the channel in the model; board-level coupling is G3's", "N/A", "")
    err = max(max(abs(v["full_swing"]["errA_lsb"]), abs(v["full_swing"]["errB_lsb"])) for v in kk.values() if isinstance(v, dict) and "full_swing" in v)
    st = max(v["full_swing"]["settleB_ns"] for v in kk.values() if isinstance(v, dict) and "full_swing" in v)
    zo = max(v["zout"]["zmax_to_10MHz"] for v in kk.values() if isinstance(v, dict) and "zout" in v)
    row("SC-10", "0.5 LSB in 667 ns; Z <= 5 kohm", f"{err:.4f} LSB; {st:.0f} ns; {zo:.0f} ohm", err <= 0.5 and st < 667 and zo <= 5000, f"{667-st:.0f} ns")
    pm = min(min(ac[f"H_{r}"]["worst"]["pm"], min(x["pm"] for x in ac[f"H_{r}"]["sens"])) for r in ("5", "1.25"))
    row("AN-1", ">= 45 deg", f"{pm:.1f} deg", pm >= 45, f"{pm-45:.1f} deg")
    dcp = pr["dc"]; edg = pr["edge"]; up = pr["unpowered"]
    up0 = lj("prot_noclamp") if os.path.exists(os.path.join(R.RES, "prot_noclamp.json")) else up["-12 V both"]
    ipk = max(v["i_opamp_peak_mA"] for v in edg.values()); idc = max(v["i_opamp_in_mA"] for v in dcp.values())
    row("PR-1 (+/-30 V single input shown; +/-12 V on both is inside it)", "<= 10 mA clamp", f"{idc*1e3:.0f} uA DC, {ipk:.2f} mA peak on a 5 ns 30 V edge", max(idc, ipk) <= 10, f"{10-ipk:.1f} mA")
    pmax = max(max(v["v_pin"] for v in dcp.values()), max(v["pin_max"] for v in edg.values())); pmin = min(min(v["v_pin"] for v in dcp.values()), min(v["pin_min"] for v in edg.values()))
    row("PR-2 powered", "-0.2..3.45 V", f"{pmin:.3f}..{pmax:.3f} V", pmin >= -0.2 and pmax <= 3.45, f"{(3.45-pmax)*1e3:.0f} mV")
    for k in ("+12 V both", "-12 V both", "+12 / -12 V"):
        v = up[k]
        row(f"PR-3 unpowered, {k}, 4.7 kohm bleed", "<= 100 uA into the Due; rails < 0.5 V", f"{v['i_due_uA']:.2f} uA (ADC pins included), rail {v['v_rail']:.3f} V", abs(v["i_due_uA"]) <= 100 and v["v_rail"] < 0.5, f"{100-abs(v['i_due_uA']):.0f} uA")
    vmin = min(min(up[k]["v_apin"], up[k]["v_bpin"]) for k in ("+12 V both", "-12 V both", "+12 / -12 V"))
    vmax = max(max(up[k]["v_apin"], up[k]["v_bpin"]) for k in ("+12 V both", "-12 V both", "+12 / -12 V"))
    row("PR-2 unpowered, +/-12 V both (BAT54S at the pin, maximum-VF fit)", "-0.2..3.45 V", f"{vmin:.3f}..{vmax:.3f} V", vmin >= -0.2 and vmax <= 3.45, f"{(vmin+0.2)*1e3:.0f} mV")
    i3 = 2 * (3.3 - 1.65) / (p["R3"] + p["Rs3"])
    row("PW-1 Due 3.3 V pin", "microamps", f"{i3*1e6:.1f} uA (two R3 legs at 0 V in) + 5 uA (powercal's Vmid divider)", True, "")
    out = "\n".join(rows)

    T = []; A = T.append
    A("# 2b scope channel: simulation report (1 Mohm compensated divider, 2026-11-11)\n")
    A("Owner, 2026-11-11: SM-5 is dropped and the input returns to 1 Mohm, compensated. This is the first round's design (`report_legacy.md`, `--variant legacy`) with every change approved since. Regenerated by `python3 -I run.py --par` (variant `hz`, the default); results in `results/`, netlists in `netlists/`. The route (c) work stays reproducible as `--variant lowz` (`report_round1.md`) and `--variant lowz2` (`report_lowz2.md`).\n")
    A("- Simulator `" + NL.ngspice_version() + "`; OPA354 model " + ", ".join(f"`{k}` {v['actual'][:12]}... ({'matches' if v['match'] else 'DOES NOT MATCH'} SOURCES.md)" for k, v in hs.items() if "354" in k) + "; `models/rangesw.lib`; DESD clamp diode *(assumption)* for the switch pins at N and the unpowered network.")
    A("- Vmid: one buffer per channel, both halves of one TLV9062 (owner): powercal's P8-k stand-in (A0 120 dB, GBW 15 MHz, double pole at 40 MHz, Rout 150 ohm) in the design loop (4 x 1R in parallel, 4.7k, 1 uF, 6 x 10 uF + 100 nF); its |Z| peaks at 0.25 ohm near 2.5 kHz here, as powercal reads. Its 2 mV maximum offset is inside SC-2's +/-30 mV centring allowance, which the DC corners apply. Sense: the Due's 3.3 V pin behind 0.1 ohm *(assumption)*, the shared 249 ohm + 10 uF filter.")
    A("- Calibration is the BNC tee (owner, 2026-11-11): no injection switch and no MCP pin on N; N carries the divider, C1, C2, the op-amp and 2 pF of strays only (the op-amp's own input capacitance is in its model).\n")
    A("## Circuit (one channel)\n")
    A("| part | value |\n|---|---|")
    A(f"| R1, R3 | 760 kohm each = 330k + 330k + 100k, 0.1 % |\n| R2 | 330 kohm 0.1 %, fixed |\n| C1 | 12 pF C0G across R1 |")
    A(f"| C2 | **20 pF || 12 pF || (12 pF in series with 20 pF) = {p['C2']*1e12:.2f} pF**, N to Vmid (four parts, Basic types only) |")
    A("| Rnp | 680 ohm |\n| RF / RG | 953 / 249 ohm, range switch across RF |\n| Riso | 22 ohm |\n| AFE +3.3 V bleed | 4.7 kohm |")
    A(f"\nalpha {alpha:.4f}, Thevenin at N {rth/1e3:.1f} kohm.\n")
    A("## Pass / fail\n")
    A("Worst case: DC by summed one-at-a-time extremes (0.1 %, centring +/-30 mV, Vos 8 mV, Ron 8.8, rail 3.23-3.37 V) and an 80-draw Monte Carlo; AC over the corners: inverting node -2/0/+3 pF, Ron 3.7/8.8, (C1, C2) at (+5 %, -5 %) and (-5 %, +5 %).\n")
    A("| row | limit | worst | verdict | margin |\n|---|---|---|---|---|\n" + out + "\n")

    A("## C2 without a switch on N\n")
    s0 = cp["sweep"]["0"]
    A(f"The DC-to-100 kHz gain step on +/-5 V is zero at C2 = **{s0['null_pF']:.2f} pF** and moves {abs(s0['slope_pct_per_pF']):.2f} % per pF (whatif/tee, with an earlier netlib, found 37.2 pF). Combinations of the Basic 12 pF and 20 pF types (the Extended 39 pF avoided; the what-if's choice shown for comparison):\n")
    A("| C2 | value | 100 kHz step +/-5 / +/-1.25 V | -3 dB +/-1.25 V (nominal) |\n|---|---|---|---|")
    for name, v in sorted(cp["combos"].items(), key=lambda t: t[1]["C2_pF"]):
        rr = v["res"]
        A(f"| {name} | {v['C2_pF']:.2f} pF | {rr['0|5']['step_100k_pct']:+.2f} / {rr['0|1.25']['step_100k_pct']:+.2f} % | {rr['0|1.25']['bw']/1e6:.1f} MHz |")
    A("\nChosen: 20 + 12 + (12 s 20) = 39.5 pF, four parts, -1.0 %. 20 + 12 + (20 s 20 s 20) = 38.7 pF is flatter (+0.6 %, five parts); the suggested 36 and 38 pF leave +5.9 % and +1.8 %. The step is information now (SM-5 dropped; SC-5's host frequency calibration removes it).\n")
    cl = lj("clamp_hz")
    A("## BAT54S at the ADC pin (PR-2 unpowered)\n")
    A("One BAT54S C7420333 per channel after Riso: pin 1 to ground, pin 3 on the ADC pin, pin 2 on the **AFE +3.3 V_A** (chosen: with the Due's 3.3 V instead, the upper die sends 5.4 uA of a +12 V fault into the Due rather than 2 uA, for no gain on the negative side). Models: `models-open/bat54s-c7420333` typical and maximum-VF fits, CT 10 pF at 1 V; the SAM3X datasheet (Table 45-1) gives -0.3 V on input pins and no injection-current rating.\n")
    A("| upper die, fit, inputs | into the Due | AFE rail | ADC pin |\n|---|---|---|---|")
    for k, v in cl["unpowered"].items():
        A(f"| {k.replace('|', ', ')} | {v['i_due_uA']:.2f} uA | {v['v_rail']:.3f} V | {min(v['v_apin'], v['v_bpin']):.3f}..{max(v['v_apin'], v['v_bpin']):.3f} V |")
    A(f"\nWithout the clamp the pin goes to {min(up0['v_apin'], up0['v_bpin']):.3f} V at -12 V (the SAM3X's own diodes). With it, powered, the pin spans " + f"{min(v['v_pin'] for v in cl['powered'].values()):.3f}..{max(v['v_pin'] for v in cl['powered'].values()):.3f} V at +/-12 and +/-30 V (unchanged: the diodes do not conduct). Its capacitance: SM-3 worst {cl['ac']['5']['worst']/1e6:.1f} / {cl['ac']['1.25']['worst']/1e6:.2f} MHz, phase margin {min(cl['ac']['5']['pm'], cl['ac']['1.25']['pm']):.1f} deg, S/H error " + f"{max(v['err_lsb'] for v in cl['kick'].values()):.4f} LSB settled in {max(v['settle_ns'] for v in cl['kick'].values()):.0f} ns. Its leakage at the datasheet's 2 uA-at-25 V bound (12.5 Mohm per die) moves the op-amp-driven pin by at most {max(abs(x) for v in cl['leak'].values() for x in v.values()):.1f} uV.\n")
    A("## Edges, flatness\n")
    A("| case | rise 10-90 | overshoot | settle 0.5 % |\n|---|---|---|---|")
    for k, v in ed.items():
        A(f"| {k} | {v['rise_10_90_ns']:.1f} ns | {v['overshoot_pct']:.1f} % | {v['settle_0p5pct_ns']:.0f} ns |")
    for r in ("5", "1.25"):
        n = ac[f"H_{r}"]["nominal"]; lf = ac[f"H_{r}"]["lf"]
        A(f"\n+/-{r} V: gain at 10 kHz {n['g0']:.4f}, -3 dB {n['bw']/1e6:.1f} MHz, peak {n['peak_db']:.2f} dB, flatness 1-8 MHz vs 100 kHz {lf['flat_1_8MHz_db']:.2f} dB, step 1 Hz -> 100 kHz {lf['step_1Hz_to_100kHz_pct']:+.2f} %.")
    A("\n## Noise\n")
    A("| range | to | total | resistors | op-amp | Vmid | sense |\n|---|---|---|---|---|---|---|")
    for k, v in nz.items():
        for lab in ("at_bw", "at_1p5bw", "at_10MHz"):
            x = v[lab]
            A(f"| {k} | {x['fmax']/1e6:.0f} MHz | {uv(x['total_V'])} | {uv(x['resistors_V'])} | {uv(x['opamp_voltage_V'])} | {uv(x['vmid_V'])} | {uv(x['v3sense_V'])} |")
    A("\n## Unpowered (diode-level network, 4.7 kohm bleed)\n")
    A("| inputs | into the Due (incl. ADC pins) | AFE rail | ADC pin | N |\n|---|---|---|---|---|")
    for k, v in up.items():
        A(f"| {k} | {v['i_due_uA']:.2f} uA | {v['v_rail']:.3f} V | {min(v['v_apin'], v['v_bpin']):.3f}..{max(v['v_apin'], v['v_bpin']):.3f} V | {v['v_an']:.2f} V |")
    A("\n## Guards\n")
    A("| guard | mutation | good | broken | restored | effective |\n|---|---|---|---|---|---|")
    for g in gd:
        A(f"| {g['guard']} | {g['mutation']} | {'pass' if g['good']['ok'] else 'FAIL'}: {g['good']['detail']} | {'pass' if g['broken']['ok'] else 'FAIL'}: {g['broken']['detail']} | {'pass' if g['restored']['ok'] else 'FAIL'} | {'yes' if g['effective'] else 'NO'} |")
    with open(os.path.join(HERE, "report.md"), "w") as f:
        f.write("\n".join(T) + "\n")
    return out
