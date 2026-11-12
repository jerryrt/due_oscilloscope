#!/usr/bin/env python3
"""Writes report.md from results/*.json (run.py writes those).  python3 -I report.py"""
import json, os, math
HERE = os.path.dirname(os.path.abspath(__file__))
J = lambda n: json.load(open(os.path.join(HERE, "results", n + ".json")))
(meta, dc, ac, bw, noise, d17, tran, stab, beh, prot, xt, st, mc, gd, cs) = (
    J(n) for n in ("meta", "dc", "ac", "bw", "noise", "d17", "tran", "stab", "beh", "prot", "xtalk", "static", "mc", "guards", "cscan"))
MODELS = ("vendor", "BEH21", "BEH60")

rows = []
fails = []


def R(rid, req, result, margin, ok, note=""):
    rows.append(f"| {rid} | {req} | {result} | {margin} | {'PASS' if ok is True else ('FAIL' if ok is False else ok)} | {note} |")
    if ok is False:
        fails.append(rid)


f0 = lambda x: f"{x:.0f}"
f1 = lambda x: f"{x:.1f}"
f2 = lambda x: f"{x:.2f}"
f3 = lambda x: f"{x:.3f}"
cn = mc["corners"]

# ---- numbers used more than once
lo_nom, hi_nom = dc["pin"][0], dc["pin"][-1]
f3db = ac["f3dB_Hz"]
x10 = ac["probe_x10"]
t5, t5u, t10 = tran["sine5_fs"], tran["sine5_usable"], tran["sine10_usable"]
unp = {(r["v1"], r["v2"], r["bleed"], r["pinclamp"]): r for r in prot["unpowered"]}
unpd = {(r["v1"], r["v2"], r["pinclamp"]): r for r in prot["unpowered_diff"]}
pw = {(r["v1"], r["v2"]): r for r in prot["powered"]}
ed = prot["edge"]
cxn = {(r["C_pF"], r["f_MHz"]): r["lsb_at_6Vpp"] for r in xt["Cx_N_to_N"]}
cxi = {(r["C_pF"], r["f_MHz"]): r["lsb_at_6Vpp"] for r in xt["Cx_in_to_in"]}
cxp = {(r["C_pF"], r["f_MHz"]): r["lsb_at_6Vpp"] for r in xt["Cx_pad_to_pad"]}
comb = {(r["Cx_N_pF"], r["Cx_pad_pF"], r["f_MHz"]): r["lsb_at_6Vpp"] for r in xt["combined"]}
BUD_N, BUD_P = 0.02, 0.02            # the layout budget in pF (design.md); the pair is run in section xtalk
bud_lsb = comb[(BUD_N, BUD_P, 10.0)]
st_spread = max(st[m]["spread_pp_100kHz"] for m in MODELS)


# AN-1: worst over the three models of the Riso 22 ohm row of the grid (0 to 100 pF at the pin) and the nominal
def an1(model):
    g = [x for x in stab[model]["grid"] if x["Riso"] == 22 and x["pm_deg"] is not None]
    pm = min([x["pm_deg"] for x in g] + [stab[model]["nominal"]["pm_deg"]])
    gm = min([x["gm_dB"] for x in g if x["gm_dB"] is not None] + [stab[model]["nominal"]["gm_dB"]])
    g0 = [x for x in stab[model]["grid"] if x["Riso"] == 0.001 and x["pm_deg"] is not None]
    return dict(pm=pm, gm=gm, pm0=min(x["pm_deg"] for x in g0))


A = {m: an1(m) for m in MODELS}
worst_m = min(MODELS, key=lambda m: A[m]["pm"])
pm_w = A[worst_m]["pm"]
gm_w = min(A[m]["gm"] for m in MODELS)

# SM-3: the pin with the ADC network on it (three models, both switch cases), and the sampling capacitor
CASES = ("derived", "lowR")
pin_f3 = {(m, c): bw[m][c]["pin"]["f3dB_MHz"] for m in MODELS for c in CASES}
pin_8 = {(m, c): bw[m][c]["pin"]["dB_8MHz"] for m in MODELS for c in CASES}
pin_10 = {(m, c): bw[m][c]["pin"]["dB_10MHz"] for m in MODELS for c in CASES}
sw_f3 = {(m, c): bw[m][c]["sw"]["f3dB_MHz"] for m in MODELS for c in CASES}
sw_8 = {(m, c): bw[m][c]["sw"]["dB_8MHz"] for m in MODELS for c in CASES}
adc_pole = {c: 1 / (2 * math.pi * v["ron"] * v["cs"]) / 1e6 for c, v in d17["adc_cases"].items()}
pin_f3_min = min(pin_f3.values())
pin_8_worst = min(pin_8.values())
pin_10_worst = min(pin_10.values())
sw_f3_der = min(sw_f3[(m, "derived")] for m in MODELS)
sw_f3_low = min(sw_f3[(m, "lowR")] for m in MODELS)
sw_8_der = min(sw_8[(m, "derived")] for m in MODELS)

# D17
dr = d17["rows"]
D = lambda m, c: dr[f"{m}|{c}"]["total_uV"]
d17_vendor = {c: D("vendor", c) for c in CASES}
d17_ds = {c: max(D("BEH21+6.5", c), D("BEH60+6.5", c)) for c in CASES}
d17_93 = {c: max(D("BEH21+9.3", c), D("BEH60+9.3", c)) for c in CASES}
d17_worst = max(max(d17_vendor.values()), max(d17_ds.values()))
pin1g = d17["pin_1GHz_no_network"]
e12 = max(ed["470"]["+12V_2ns"]["peak_mA"], ed["470"]["-12V_2ns"]["peak_mA"])
cp = cs["chosen"]; c22 = cs["cn22_with_cpx"]; b2 = cs["best_by_parts"]["2"]; b4 = cs["best_by_parts"]["4"]; alt = cs["alt_20_10"]

# ---- requirement table
R("§3.1 / SC-2", "range -1.5..+3.5 V rated, -2.0..+4.0 V usable; pin >= 80 mV from each end of 0..AREF at AREF 3.20 V, 1 % parts, centring +-30 mV",
  f"pin {lo_nom:.3f} V at -2 V, {hi_nom:.3f} V at +4 V (ngspice, nominal); Monte Carlo 200,000 draws: low slack {f1(mc['lo_slack_mV_with_30mV'])} mV, high slack {f1(mc['hi_slack_mV_with_30mV'])} mV with the budget's extra +-30 mV; {f1(mc['lo_slack_mV'])} / {f1(mc['hi_slack_mV'])} mV without. 128-corner worst case {f1(cn['lo_slack_mV'])} / {f1(cn['hi_slack_mV'])} mV (no extra 30 mV)",
  f"{f1(mc['lo_slack_mV_with_30mV'])} / {f1(mc['hi_slack_mV_with_30mV'])} mV over the 80 mV", mc["lo_slack_mV_with_30mV"] > 0 and mc["hi_slack_mV_with_30mV"] > 0,
  "VOS +-0.5 mV and a CMRR term of +-1.7 mV (65 dB min at VS 5.4 V, *(check at 3.3 V)*) are inside")
R("SC-4", "at most 1.8 mV per code at the input (afe-v2.md); 5 V span 70 to 75 % of FS at 3.25 V",
  f"{f3(mc['mV_per_code_worst'])} mV/code worst (AREF 3.30 V, smallest a); span {f2(cn['span_pct_FS_3p25'][0])} to {f2(cn['span_pct_FS_3p25'][1])} % over the 128 corners",
  f"{f3(1.8 - mc['mV_per_code_worst'])} mV ({f1((1.8 - mc['mV_per_code_worst']) / 1.8 * 100)} %); span low end {f2(cn['span_pct_FS_3p25'][0] - 70)} % FS over the 70 % minimum", cn["span_pct_FS_3p25"][0] >= 70 and mc["mV_per_code_worst"] <= 1.8,
  "the worst corner of the 1 % parts sits 0.34 % FS above the 70 % floor; the spec lead accepted it")
R("SC-3 / D-V2-9", "1 MOhm nominal within 1 %, spread of 1 % parts allowed on top",
  f"R_in {dc['rin']/1e3:.2f} k nominal ({(dc['rin']/1e6-1)*100:+.2f} %); corners {cn['rin_k'][0]:.1f} to {cn['rin_k'][1]:.1f} k ({(cn['rin_k'][0]/1e3-1)*100:+.2f} to {(cn['rin_k'][1]/1e3-1)*100:+.2f} %)",
  f"{1 - abs(dc['rin']/1e6 - 1) / 0.01:.0%} of the 1 % nominal band left", abs(dc["rin"] / 1e6 - 1) <= 0.01,
  "R_in = R1 + R2||R3, the REF3030E taken as an AC ground")
R("SC-3", "input capacitance at most 30 pF including wiring",
  f"{ac['zin']['100000']['C_pF']:.1f} pF nominal with a 4 pF BNC+trace assumption ({ac['zin']['100000']['C_pF']-4:.1f} pF of network); {mc['cin_pF'][0]:.1f} to {mc['cin_pF'][2]:.1f} pF over C0G 5 % and 2..6 pF of stray at N; flat 1 kHz to 10 MHz",
  f"{30 - mc['cin_pF'][2]:.1f} pF", mc["cin_pF"][2] <= 30, "the 4 pF is *(assumption)*; the margin covers 13 pF more")
R("SC-3", "compensated for x1 and x10 probes",
  f"HF/DC gain step ('shelf') nominal {ac['shelf_pct']:+.2f} %; with C0G 5 % (C1, Cn and Cpx), 1 % resistors, 2..6 pF of stray: mean {mc['shelf_pct']['mean']:+.2f} %, 95 % of boards within +-{mc['shelf_pct']['p95_abs']:.1f} %, worst of 200,000 {mc['shelf_pct']['min']:+.1f}/{mc['shelf_pct']['max']:+.1f} %. x10 probe (9 M || Cp): ripple {x10['best_ripple_pct']:.2f} % pk-pk 10 Hz to 10 MHz at Cp = {x10['best_Cp_pF']:.2f} pF ({x10['ripple_to_20MHz_pct']:.1f} % to 20 MHz, where Cpx rolls the stage off)",
  f"**static**: the step moves {st_spread:.3f} percentage points over -2..+4 V of input and {abs(st['temperature_40K']['per_K_pp']):.3f} pp/K with temperature (the resistors); section 'Is the step static?'", "PASS*" if (st_spread < 0.1 and mc["shelf_pct"]["p95_abs"] <= 6.5) else False,
  "*as a probe-compensated input; as a flat x1 response it needs the host calibration (SC-5), which the spec lead accepted as a design call because the step is static")
R("SC-5", "no filter; host frequency calibration", f"no filter part in the path; f-3dB {f3db/1e6:.0f} MHz at the pin, relative to DC, with Cpx (datasheet 250 MHz typ at RF 25 ohm); {abs(ac['dev_10MHz_dB']):.2f} dB down at 10 MHz against the 100 kHz gain, no peaking",
  "n/a", True, "the droop is Rnp x Cpx's pole (34 MHz) and the amplifier's: smooth, removed by the host's frequency calibration; the macro's 0.79 dB peak at 100 MHz and 7 % step overshoot are gone")
R("SM-3", "bandwidth at least 8 MHz (a floor), with the ADC input network attached",
  f"at the ADC pin with the switch closed and the sampling capacitor on it (3 models x 2 switch cases): -3 dB at {pin_f3_min:.0f} MHz at worst, {pin_8_worst:+.2f} dB at 8 MHz and {pin_10_worst:+.2f} dB at 10 MHz against the 100 kHz gain. At the sampling capacitor the switch's own pole is added: -3 dB at {sw_f3_der:.1f} MHz ({sw_8_der:+.1f} dB at 8 MHz) at 3.8 kohm / 6 pF, {sw_f3_low:.1f} MHz at 1 kohm / 8 pF; the switch pole alone is {adc_pole['derived']:.2f} and {adc_pole['lowR']:.1f} MHz",
  f"{pin_f3_min/8:.1f}x the floor at the pin", "PASS*" if (pin_f3_min >= 8.0 and pin_8_worst > -3.0) else False,
  "*SM-3 read at the pin, where VT-16 measures it. With the derived switch the Due's own sampling pole (6.98 MHz) is under 8 MHz before the AFE adds anything (the AFE costs 0.16 MHz); the switch is *(check)* (docs/ets.md: nothing confirms it). Spec question 1")
R("SC-6 (D17)", "noise that reaches the Due's sampling capacitor <= 0.2 mV rms: through the stage, Riso, the pin, the input switch at its worst-case resistance and the sampling capacitor, no 10 MHz cut-off",
  f"vendor macro (9.3 nV/rtHz): {f0(d17_vendor['derived'])} uV at 3.8 kohm / 6 pF, **{f0(d17_vendor['lowR'])} uV at 1 kohm / 8 pF**; datasheet density (6.5 nV/rtHz, on the datasheet-fitted BEH21 and BEH60): {f0(d17_ds['derived'])} uV and **{f0(d17_ds['lowR'])} uV**; 9.3 nV flat on the datasheet dynamics: {f0(d17_93['derived'])} / {f0(d17_93['lowR'])} uV. 10 Hz to 1 GHz, REF3030E {noise['ref_at_pin_uV']:.0f} uV included, the switch's own kT/C (26 uV at 6 pF) not (it is the Due's)",
  f"{f0(200 - d17_worst)} uV under 0.2 mV on the worst of the four; the vendor macro reaches 200 uV only below a switch resistance of {d17['Rsw_for_200uV_vendor_ohm']:.0f} ohm (6 pF)", "PASS*" if d17_worst < 200 else False,
  f"*the switch resistance is not measured (*(check)*; 3.8 k derived, 1 k the v1 study's low arm). The datasheet density reads {d17['sweep_Rsw_Cs6pF'][0]['BEH60_ds']:.0f} uV even at 100 ohm. The same circuit read the old way (pin, 10 Hz to 1 GHz, no network) is {pin1g['vendor']['total_uV']:.0f} uV on the macro: that reading is not D17's")
R("SC-7", "DC accuracy +-0.5 % +-5 mV after calibration", f"drift terms for 10 K since calibration, referred to the input: gain {mc['drift_10K_input_mV']['gain_pct']:.3f} % (R1 against R2||R3 opposed at 100 ppm/K; C0G 0), REF3030E {mc['drift_10K_input_mV']['ref']:.2f} mV (15 ppm/K max), VOS {mc['drift_10K_input_mV']['vos']:.2f} mV (2 uV/K max); op-amp bias 3 pA max x {prot['bav99_at_N']['rp_k']:.0f} k = {prot['amp_leak']['err_node_uV']:.2f} uV; REF3030E modulation by the two channels' signal current < 0.01 uV",
  f"{0.5 - mc['drift_10K_input_mV']['gain_pct']:.2f} % of 0.5 % and {5 - mc['drift_10K_input_mV']['ref'] - mc['drift_10K_input_mV']['vos']:.1f} mV of 5 mV left before the converter and the Due's ADC", True,
  "rail-to-rail input crossover of the TPH2502 is not in the macro: *(check)* by VT-1; it would show as a nonlinearity the linear calibration does not remove")
R("SC-8", "channel gain within 3 %; offset inside SC-2's centring margin", f"gain mismatch of two boards' channels, independent 1 % parts: {mc['gain_match_pct_max']:.2f} % worst of 200,000; offset mismatch {mc['offset_match_mV_max_at_pin']:.0f} mV at the pin (calibrated, SC-7)",
  f"{3 - mc['gain_match_pct_max']:.2f} %", mc["gain_match_pct_max"] <= 3, "")
R("SC-9", "crosstalk <= 2 LSB, full-scale input one channel, other shorted, to 10 MHz (the two channels share the dual)",
  f"through the shared rail and shared REF3030E: {xt['shared_rail_ref_only_10MHz']['lsb_at_6Vpp']:.0e} LSB at 10 MHz (6 Vpp); datasheet -100 dB at 5 MHz is {xt['datasheet_xtalk'][0]['lsb_at_6Vpp']:.3f} LSB. **Strays dominate**: between the two N nodes {cxn[(0.02,10.0)]:.2f} LSB at 0.02 pF, {cxn[(0.05,10.0)]:.2f} at 0.05 pF (1 LSB at {xt['Cx_N_for_1LSB_10MHz_pF']:.3f} pF); **between the two +IN pads (dual pins 3 and 5) {cxp[(0.05,10.0)]:.2f} LSB at 0.05 pF, 1 LSB at {xt['Cx_pad_for_1LSB_10MHz_pF']:.3f} pF**; between the two input nets {cxi[(0.5,10.0)]:.2f} LSB at 0.5 pF",
  f"{bud_lsb:.2f} LSB at {BUD_N:g} pF (N to N) plus {BUD_P:g} pF (pad to pad), against 2", "PASS*" if bud_lsb <= 2.0 else False,
  "*the circuit passes; the layout must hold both strays at the budget below, about 0.02 pF each, tighter than the 0.05 pF first stated because the +IN pads are as sensitive as N. A layout rule (LR-3) checked by VT-19")
R("SC-10", "source impedance at the ADC pin <= 5 kOhm; settle to 0.5 LSB inside the 667 ns window",
  f"pin source impedance {tran['zout_pin']['max_ohm_to_10MHz']:.1f} ohm to 10 MHz; alternating full swing (+4 V / -2 V) through the derived ADC input (3.8 k, 6 pF): error {abs(tran['sh_derived']['err_b_lsb']):.0e} LSB at the end of the window, inside 0.5 LSB after {tran['sh_derived']['settle_b_ns']:.0f} ns; stress ADC (1 k, 8 pF) {tran['sh_stress']['settle_b_ns']:.0f} ns",
  f"{tran['T_TRACK_ns'] - tran['sh_derived']['settle_b_ns']:.0f} ns; Z margin {5000/tran['zout_pin']['max_ohm_to_10MHz']:.0f}x", abs(tran["sh_derived"]["err_b_lsb"]) < 0.5 and tran["sh_derived"]["settle_b_ns"] < tran["T_TRACK_ns"],
  f"control: Riso 20 kohm gives {tran['sh_control_riso20k']['err_b_lsb']:.0f} LSB, so the test can fail")
R("SC-12", "full-scale sine undistorted (not slew-limited) to 5 MHz", f"5 MHz at 5 Vpp: THD {t5['thd_dB']:.0f} dB, pin slew {t5['slew_pin_Vus']:.0f} V/us; at the usable 6 Vpp: THD {t5u['thd_dB']:.0f} dB, {t5u['slew_pin_Vus']:.0f} V/us; at 10 MHz, 6 Vpp: {t10['thd_dB']:.0f} dB, {t10['slew_pin_Vus']:.0f} V/us",
  f"datasheet slew 160 V/us (VS 3 V, 2 V step): {160/t5u['slew_pin_Vus']:.1f}x at 5 MHz, {160/t10['slew_pin_Vus']:.1f}x at 10 MHz", True,
  f"THD is the macro's behavioural nonlinearity *(check: no vendor distortion model)*; control: the macro at 40 MHz reads {tran['sine40_control']['thd_pct']:.1f} % and so the test can fail")
R("AN-1", "phase margin >= 45 degrees into Riso + clamp + pin + trace, on all three models",
  f"loop gain broken at the amplifier output, ADC S/H load included, 0 to 100 pF added at the pin, Riso 22 ohm, Cpx 10 pF: vendor macro PM >= {A['vendor']['pm']:.1f} deg, BEH21 >= {A['BEH21']['pm']:.1f}, BEH60 >= {A['BEH60']['pm']:.1f}; GM >= {gm_w:.1f} dB. Without Riso: PM >= {min(A[m]['pm0'] for m in MODELS):.1f} deg at 100 pF",
  f"{pm_w - 45:.1f} deg ({worst_m})", pm_w >= 45,
  f"worst of the three. Controls: no Cpx reads {gd['pm_check_noCpx_BEH60']['pm_deg']:.1f} deg on BEH60 ({beh['cpx_scan']['0']['min_all']:.1f} at worst over the pin loads), no Riso with 1 nF reads {gd['pm_check_noRiso_1nF_BEH60']['pm_deg']:.1f} deg")
R("PR-1 powered", "+-12 V on both inputs", f"pin {pw[(12,12)]['pin_a']:.3f} V at +12 V, {pw[(-12,-12)]['pin_a']:.3f} V at -12 V; N held at {pw[(12,12)]['N_a']:.2f} / {pw[(-12,-12)]['N_a']:.2f} V by the amplifier's own input diodes; current in them {pw[(12,12)]['i_esd_up_uA']:.1f} uA / {pw[(-12,-12)]['i_esd_dn_uA']:.1f} uA against the datasheet's 10 mA (note 3)",
  f"{10000/pw[(-12,-12)]['i_esd_dn_uA']:.0f}x on current", True, "diode I-V is *(assumption)* (0.6 V at 10 uA); datasheet gives none")
R("PR-1 edge", "a 12 V step reaching the node", f"peak input-diode current {ed['0']['+12V_2ns']['peak_mA']:.0f} mA with no Rnp, **{ed['470']['+12V_2ns']['peak_mA']:.1f} mA (+12 V) and {ed['470']['-12V_2ns']['peak_mA']:.1f} mA (-12 V) with Rnp 470 ohm and Cpx 10 pF** (2 ns edge from 50 ohm); 30 V / 5 ns (information): {ed['470']['+30V_5ns']['peak_mA']:.0f} mA",
  f"{10 - e12:.1f} mA under the 10 mA note", "PASS*" if e12 <= 10 else False,
  f"*thin: Cpx holds +IN at ground while the edge steps N, so Rnp alone limits the diode current. Rnp 560 gives {ed['560']['-12V_2ns']['peak_mA']:.1f} mA, 680 gives {ed['680']['-12V_2ns']['peak_mA']:.1f} mA (bandwidth and phase margin for those are not re-run). Diode I-V *(assumption)*")
R("PR-1 unpowered", "+-12 V on both inputs, Due unpowered", f"rail rises to {unp[(12,12,1e9,True)]['rail']:.1f} V with no bleed; with a 14 kohm bleed {unp[(12,12,14e3,True)]['rail']:.2f} V; current into the Due's 3.3 V net {abs(unp[(12,12,14e3,True)]['i_due_uA']):.3f} uA",
  f"largest bleed for 0.5 V: {prot['bleed_needed']['max_bleed_ohm']/1e3:.1f} kohm", "OPEN",
  "the unpowered +3.3 V_A rail must sink about 36 uA at 0.5 V (PR-3); that is a rail-block requirement and stays open (the powercal stream owns it)")
R("PR-2", "A0/A1 stay between -0.2 V and 3.45 V in every state", f"powered: {pw[(-12,-12)]['pin_a']:.3f} to {pw[(12,12)]['pin_a']:.3f} V (the amplifier output saturates at its rail; 3.45 V is {3.45-3.3*1.03:.2f} V above a rail at 3.3 V +3 %); unpowered, diodes-only amplifier: {unp[(-12,-12,14e3,True)]['pin_a']:.3f} to {unp[(12,12,14e3,True)]['pin_a']:.3f} V; **unpowered with a differential input clamp (adversarial): {unpd[(-12,-12,True)]['pin_a']:.3f} V at -12 V with the BAV99 at the pin, {unpd[(-12,-12,False)]['pin_a']:.3f} V without it**",
  f"{unpd[(-12,-12,True)]['pin_a'] + 0.2:.2f} V with the pin BAV99, {unpd[(-12,-12,False)]['pin_a'] + 0.2:.2f} V without (adversarial arm)", "PASS*" if unpd[(-12, -12, True)]["pin_a"] >= -0.2 else False,
  "*unpowered behaviour of the TPH2502 is *(check)*: the datasheet says nothing. The pin BAV99 is what passes the adversarial arm; kept per the spec lead, VT-5 may drop it")
R("REF3030E", "loading by both channels; sink when an input is clamped high", f"sources up to {mc['ref_source_uA_max_per_channel']:.2f} uA per channel at -2 V in ({pw[(-12,-12)]['i_ref_uA']/2:.1f} uA per channel at -12 V); sinks {abs(pw[(12,12)]['i_ref_uA'])/2:.2f} uA per channel with an input at +12 V (powered; {mc['ref_sink_uA_clamped_per_channel']:.1f} uA bound at 3.37 V and 0.7 V diode drop); REF30E specification: +-10 mA, load regulation 15 ppm/mA source, 150 ppm/mA sink (ref30.pdf, 6.5)",
  f"worst change in V_REF {(2*5.4e-3)*3*15:.2f} uV source side, {(2*1.6e-3)*3*150:.2f} uV sink side: below 0.002 % of the SC-7 5 mV", True,
  "uA against 10 mA: 2,000x on the rated current")

# ---- assemble
out = []
A_ = out.append
A_(f"""# AFE version 2: the scope channel, simulated

Both scope channels on one TPH2502 dual as unity followers on +3.3 V only, with the input network of
`budget/v2_scope.py` and the REF3030E as the centre. **Generated by `report.py` from `results/*.json`;
`run.py` regenerates the JSON** (`python3 -I run.py && python3 -I report.py`, ngspice 47 and numpy, about a minute). Design values,
reasons and LCSC codes are in `design.md`; the circuit is `scope_v2.cir`.

**Simulator** `{meta['ngspice']}`. **Op-amp models**, three:
the vendor macro `TPH2501_simplify` (`{meta['model']}`, sha256 `{meta['model_sha256']}`, checked by `run.py`), and the project's two
datasheet-fitted behavioural models `BEH21` (open-loop output impedance 21 ohm) and `BEH60` (60 ohm), from `{meta['beh_lib']}`
(sha256 `{meta['beh_lib_sha256']}`, small signal only, no noise). The macro is the *single-amplifier*
TPH2501, which shares one datasheet with the TPH2502 (`tph2502.pdf` covers TPH2501/2/3/4), and nothing in it couples two channels. It was
**not** written for this study and its figures are therefore marked *(check: no vendor TPH2502 model)* wherever a
result depends on them: noise density (9.3 nV/rtHz against the datasheet's 6.5), distortion, the unpowered input
structure, the rail-to-rail input crossover (the macro has one PMOS pair) and every crosstalk figure. Stability, bandwidth and noise are
read on all three models; the large-signal figures (slew, THD, settling) are the macro's alone.

## Verdict

{sum(1 for r in rows if '| PASS |' in r)} lines PASS, {sum(1 for r in rows if '| PASS* |' in r)} PASS with a starred condition (the circuit meets the requirement and the note says what still has to be true), {sum(1 for r in rows if '| OPEN |' in r)} OPEN (a requirement of the rail block that this design sets), and {len(fails)} FAIL{(': ' + ', '.join(fails)) if fails else ''}.
Read the starred and OPEN lines and the section "Open items and spec questions" first.

## Requirement by requirement

| ID | Requirement | Result | Margin | Verdict | Note |
|---|---|---|---|---|---|
""" + "\n".join(rows))

A_(f"""
## What was assumed (all *(assumption)* or *(check)* unless it has a source)

| Item | Value | Source |
|---|---|---|
| Resistors | 1 % uniform, six independent parts per channel (series pairs) | afe-v2.md V2-3; `v2/jlc-basic.csv` |
| C0G capacitors | 5 % uniform; no bias or temperature dependence beyond class I (+-30 ppm/K) | `v2/jlc-basic.csv` (CL10C220JB8NNNC: +-5 %); the ppm and the bias figure are the EIA class's, not read from a Samsung datasheet *(check: not in the repository)* |
| REF3030E | 3.000 V +-0.2 % (E grade is +-0.1 %; `budget/v2_scope.py` uses 0.2 %), Zout 0.05 ohm, 1 uF + 100 nF | `models/ref3030/ref30.pdf` 6.5 (15 ppm/mA = 0.045 ohm); the TI model is encrypted |
| REF3030E noise at the pin | 51 uV rms (10 Hz to 10 kHz) x Rp/R3 = {noise['ref_at_pin_uV']:.0f} uV, added in quadrature; its broadband density above 10 kHz is not known | `ref30.pdf` 6.5 *(check)* |
| Stray at N | 2 to 6 pF total (pads of five parts, the trace, the amplifier's 0.5-1 pF) | *(assumption)* |
| Stray across R1 | 0.1 pF | *(assumption)* |
| BNC + trace at the input | 4 pF | *(assumption)* |
| ADC input | the sampling capacitor behind the input switch: 3.8 kohm / 6 pF (derived from the SAM3X track-time formula, 0.054 ns per ohm + 205 ns) and a low-resistance arm 1 kohm / 8 pF (v1's stress arm, Ci max 8 pF); Cpin 2 pF. Neither is measured: `docs/ets.md` says "nothing confirms" the switch resistance | `sim/scope/run.py` ADC_DERIVED / ADC_STRESS, SAM3X datasheet *(check)* |
| Amplifier noise, datasheet | 6.5 nV/rtHz, flat 10 Hz to 1 GHz (the datasheet curve ends near 100 MHz and rises at low frequency) | `tph2502.pdf` p6 *(check above 100 MHz)* |
| Supply | 3.3 V behind 0.1 ohm and 10 nH, 100 nF + 1 uF at the dual | as version 1's netlib |
| Input ESD diodes | 0.6 V at 10 uA, 5 ohm, to each rail at +IN | the datasheet gives none *(assumption)* |
| BAV99 | VF 0.715 V at 1 mA, CJ 1.5 pF, IR 2.5 uA at BV | recalled, not read: Nexperia's download was blocked (`models/SOURCES.md`) *(check)* |
| VOS, CMRR | 0.5 mV, 65 dB x 3 V swing = 1.7 mV | `tph2502.pdf` page 3 (VOS max; CMRR min at VS 5.4 V) |
| Resistor tempco | 100 ppm/K, opposed | `jlc-basic.csv` (-> `budget/v2_scope.py` TC) |
""")

A_(f"""## DC, range and the network

Nominal (ngspice): attenuation a = {dc['a']:.4f}, R_in = {dc['rin']/1e3:.2f} k, {dc['mV_per_code_at_3p25']:.3f} mV per code at AREF 3.25 V, 5 V
span = {dc['span_pct_FS_3p25']:.1f} % of full scale. The closed form in `run.py` reproduces ngspice to
{dc['max_dev_mV']:.2f} mV (the macro's own offset and gain) and, at 12 random 1 % / 5 % draws, to
{mc['crosscheck_max_gain_err_pct']:.3f} % in gain and {mc['crosscheck_max_shelf_err_pct']:.3f} percentage points in the HF/DC step, so the 200,000-draw
Monte Carlo is the same circuit.

| Input | Pin, nominal (ngspice) |
|---|---|
""" + "\n".join(f"| {v:+.1f} V | {p:.4f} V |" for v, p in zip(dc["vin"], dc["pin"])))

A_(f"""
Monte Carlo (n = {mc['n']}, seed {mc['seed']}): pin at -2.0 V in {mc['pin_at_usable']['lo_V_min']*1e3:.0f} to {mc['pin_at_usable']['lo_V_max']*1e3:.0f} mV; at +4.0 V in
{mc['pin_at_usable']['hi_V_min']:.3f} to {mc['pin_at_usable']['hi_V_max']:.3f} V; the rated -1.5..+3.5 V reaches {mc['rated_pin_V'][0]:.3f} to {mc['rated_pin_V'][1]:.3f} V. The 1 V
input (the centre) sits {mc['centre_offset_mV_at_pin_for_1V_in'][0]:.0f} to {mc['centre_offset_mV_at_pin_for_1V_in'][1]:.0f} mV from mid-scale at AREF 3.25 V,
which is the network's own centring and is removed by calibration. Gain drift (R1 against R2||R3, 100 ppm/K
opposed, 20 K): {mc['gain_drift_20K_pct']:.3f} %, which is `budget/v2_scope.py`'s 0.215 % (EN-1, D-V2-3).""")

A_(f"""
## Compensation (C1 across R1, Cn at the node, Cpx at +IN) and the x10 probe

Condition for a flat response: R1 C1 = (R2||R3)(C at N), equivalently C1/(C1 + C at N) = a, where **C at N is Cn plus the stray plus Cpx**:
Rnp (470 ohm) is small against the node's impedance above the 13 kHz pole, so Cpx (10 pF, +IN to ground behind Rnp) is
capacitance at N up to its own 34 MHz pole. Cpx therefore takes 10 pF out of what Cn must supply. Section `cscan` tries every one- and
two-part C1 and Cn (Cn may be absent) from the Basic C0G values 10 to 47 pF, with Cpx 10 pF at N, the network capacitance held to 22 pF
(the BNC's 4 pF and 4 pF of margin under SC-3's 30 pF), against the Monte Carlo (5 % C0G, 2..6 pF of stray at N, 1 % resistors), and reports the 95th percentile of the HF/DC step:

| C1 | Cn | parts | 95th percentile | mean | network C |
|---|---|---|---|---|---|
| **22 pF (C1653)** | **12 pF (C38523), the design** | 2 | **{cp['p95_abs_pct']:.1f} %** | {cp['mean_pct']:+.1f} % | {cp['cin_network_pF']:.1f} pF |
| 22 pF | 22 pF (Cn as it was before Cpx) | 2 | {c22['p95_abs_pct']:.1f} % | {c22['mean_pct']:+.1f} % | {c22['cin_network_pF']:.1f} pF |
| 20 pF (C1648) | 10 pF (C1634, the part Cpx is) | 2 | {alt['p95_abs_pct']:.1f} % | {alt['mean_pct']:+.1f} % | {alt['cin_network_pF']:.1f} pF |
| {b2['C1']} pF | {b2['Cn']} pF (best of the two-part pairs) | 2 | {b2['p95_abs_pct']:.1f} % | {b2['mean_pct']:+.1f} % | {b2['cin_network_pF']:.1f} pF |
| {b4['C1']} pF | {b4['Cn']} pF (best of the four-part sets) | 4 | {b4['p95_abs_pct']:.1f} % | {b4['mean_pct']:+.1f} % | {b4['cin_network_pF']:.1f} pF |

The caps' 5 % and the stray's uncertainty set the spread, not the choice of value; two more parts per channel buy 2 points. With Cpx fitted
and Cn left at 22 pF the step is {c22['mean_pct']:+.1f} % on average, which no budget absorbs, so Cn is 12 pF. The step is a one-time gain step of the divider above its
{noise['node_pole_Hz']/1e3:.0f} kHz node pole.

Nominal HF/DC step (ngspice, with Cpx and Cn 12 pF): {ac['shelf_pct']:+.2f} %. Over the Monte Carlo: mean {mc['shelf_pct']['mean']:+.2f} %,
95 % within +-{mc['shelf_pct']['p95_abs']:.1f} %, 99 % within +-{mc['shelf_pct']['p99_abs']:.1f} %, worst {mc['shelf_pct']['min']:+.1f} / {mc['shelf_pct']['max']:+.1f} %.
Input capacitance {ac['zin']['100000']['C_pF']:.1f} pF nominal (flat to 10 MHz in the sim: {ac['zin']['1000']['C_pF']:.2f}, {ac['zin']['1000000']['C_pF']:.2f} pF at 1 kHz, 1 MHz).

With a x10 probe (9 MOhm || Cp from an ideal source) the response is flat to {x10['best_ripple_pct']:.2f} % pk-pk, 10 Hz to 10 MHz, when the
probe's trimmer is set to {x10['best_Cp_pF']:.2f} pF (the sweep is in `results/ac.json`): the input looks like a single R || C to the probe, which
is what compensating a probe needs. Out to 20 MHz the figure is {x10['ripple_to_20MHz_pct']:.1f} %: that is Cpx's roll-off, above the 10 MHz ceiling (D13). A probe's trimmer is adjusted per channel (D-V2-9), so it absorbs the divider's step on that channel; the trimmer's range
against a +-6 % step is *(check)* against the probe's own datasheet.

### Is the step static?

The spec lead accepted the +-6 % step from 5 % C0G as a design call provided it does not move: a static step is a gain ratio the host's
frequency calibration (SC-5) removes once, and a moving one is not. Four ways it could move (`static`):

| Cause | Evidence | Result |
|---|---|---|
| Input level | the step at 100 kHz and 1 MHz against 10 Hz, small-signal at DC inputs of -2 to +4 V, three models | spread {st['vendor']['spread_pp_100kHz']:.3f} (vendor), {st['BEH21']['spread_pp_100kHz']:.3f} (BEH21), {st['BEH60']['spread_pp_100kHz']:.3f} (BEH60) percentage points at 100 kHz; the vendor's is the macro's reading at -2 V in, where the pin sits 0.19 V from ground (its cause is not isolated); the linear datasheet-fitted models read none. Limit used: 0.1 pp (a study choice) |
| Capacitor bias | C0G has no bias dependence (EIA class I) *(check: the Samsung datasheet is not in the repository)*. Control: C1 and Cn made X7R-like (20 % down at 3 V) move the step by {st['control_voltage_dependent_caps']['spread_pp_100kHz']:.1f} pp over the same sweep, so the sweep can see a bias-dependent capacitor | the real parts are not that |
| Temperature | C0G +-30 ppm/K, C1 against Cn and Cpx, over 40 K: {st['temperature_40K']['caps_opposed_pp']:+.2f} pp. The resistors' 100 ppm/K opposed (the gain drift of SC-7, the same quantity): {st['temperature_40K']['resistors_opposed_pp']:+.2f} pp over 40 K, {st['temperature_40K']['per_K_pp']:+.4f} pp/K | the step follows the DC gain's drift, which the 10 K recalibration rule (EN-1) already bounds |
| Ageing | C0G does not age *(check: class I, no datasheet read)* | none |

The step is a fixed per-board gain ratio, set at assembly by the 5 % caps, the 1 % resistors and the stray, and not by the signal.

## Bandwidth, noise, and whether a band limit is needed (D13, SC-5, SC-6)

The follower's -3 dB is {f3db/1e6:.0f} MHz at the pin with the 470 ohm Rnp and Cpx 10 pF in front, {abs(ac['dev_10MHz_dB']):.2f} dB down at 10 MHz against the 100 kHz gain.

### SM-3 with the ADC input attached

Closed-loop response from the BNC (50 ohm source) to the pin with the switch closed, and to the sampling capacitor, against the 100 kHz gain
(`results/bw.json`): -3 dB in MHz / dB at 8 MHz.

| model | pin, no ADC | pin, 3.8 k / 6 pF | pin, 1 k / 8 pF | sampling capacitor, 3.8 k / 6 pF | sampling capacitor, 1 k / 8 pF |
|---|---|---|---|---|---|
""" + "\n".join(f"| {m} | {bw[m]['pin_only']['pin']['f3dB_MHz']:.1f} / {bw[m]['pin_only']['pin']['dB_8MHz']:+.2f} | {pin_f3[(m,'derived')]:.1f} / {pin_8[(m,'derived')]:+.2f} | {pin_f3[(m,'lowR')]:.1f} / {pin_8[(m,'lowR')]:+.2f} | {sw_f3[(m,'derived')]:.1f} / {sw_8[(m,'derived')]:+.1f} | {sw_f3[(m,'lowR')]:.1f} / {sw_8[(m,'lowR')]:+.2f} |" for m in MODELS) + f"""

The sampling capacitor's -3 dB is the Due's own switch pole ({adc_pole['derived']:.2f} MHz at 3.8 kohm / 6 pF, {adc_pole['lowR']:.1f} MHz at 1 kohm / 8 pF) with the stage's
0.2 to 0.3 dB in front of it. At the derived switch resistance the sampling pole is under 8 MHz whatever drives the pin, so SM-3's 8 MHz can only be
met at the pin (which is where VT-16 measures it), and the figure at the capacitor depends on a switch resistance nobody has measured.

### Noise at the sampling capacitor (D17)

SC-6 reads the noise that reaches the Due's sampling capacitor (afe.md SC-6, D17): the stage, Riso, the pin (Cpin 2 pF, the BAV99's 1.5 pF), the
switch resistance and the capacitor, integrated 10 Hz to 1 GHz with no cut-off at 10 MHz, because noise above 10 MHz folds into every sample. The
switch's own thermal noise is not counted (kT/C is 26 uV at 6 pF and 23 uV at 8 pF; it belongs to the Due and is inside the 0.64-0.68 mV floor SC-6 is measured
against). The vendor macro's reading is ngspice's `.noise` at the capacitor. The datasheet-density reading puts the datasheet's 6.5 nV/rtHz in series with the
amplifier's + input, multiplies by the simulated transfer to the capacitor on the datasheet-fitted BEH21 and BEH60 dynamics (which carry no noise of their own), and adds the
resistors' ngspice noise and the REF3030E's {noise['ref_at_pin_uV']:.0f} uV in quadrature (`results/d17.json`).

| Reading, uV rms | 3.8 kohm / 6 pF | 1 kohm / 8 pF |
|---|---|---|
| vendor macro (its own density: 9.3 nV flat to 10 MHz, rising near 100 MHz) | {d17_vendor['derived']:.0f} | **{d17_vendor['lowR']:.0f}** |
| datasheet 6.5 nV/rtHz, BEH21 dynamics | {D('BEH21+6.5','derived'):.0f} | {D('BEH21+6.5','lowR'):.0f} |
| datasheet 6.5 nV/rtHz, BEH60 dynamics | {D('BEH60+6.5','derived'):.0f} | **{D('BEH60+6.5','lowR'):.0f}** |
| 9.3 nV/rtHz flat, BEH21 / BEH60 dynamics | {D('BEH21+9.3','derived'):.0f} / {D('BEH60+9.3','derived'):.0f} | {D('BEH21+9.3','lowR'):.0f} / {D('BEH60+9.3','lowR'):.0f} |
| SC-6 | 200 | 200 |

Switch resistance sweep (Cs 6 pF, uV rms): the figure rises as the switch gets faster and the band the capacitor sees widens.

| Rsw (ohm) | """ + " | ".join(f"{r['Rsw_ohm']:g}" for r in d17["sweep_Rsw_Cs6pF"]) + """ |
|---|""" + "---|" * len(d17["sweep_Rsw_Cs6pF"]) + """
| vendor macro | """ + " | ".join(f"{r['vendor']:.0f}" for r in d17["sweep_Rsw_Cs6pF"]) + """ |
| datasheet, BEH21 | """ + " | ".join(f"{r['BEH21_ds']:.0f}" for r in d17["sweep_Rsw_Cs6pF"]) + """ |
| datasheet, BEH60 | """ + " | ".join(f"{r['BEH60_ds']:.0f}" for r in d17["sweep_Rsw_Cs6pF"]) + f""" |

**The worst of the four readings is {d17_worst:.0f} uV against 200**, and the macro reaches 200 uV only for a switch resistance under {d17['Rsw_for_200uV_vendor_ohm']:.0f} ohm; the
datasheet density does not reach it down to 100 ohm. The figure a pin-level reading would give (10 Hz to 1 GHz at the pin, no network) is {pin1g['vendor']['total_uV']:.0f} uV on the macro and
{pin1g['BEH60+6.5']['total_uV']:.0f} uV on the datasheet density: the capacitor's own pole removes most of it, which is what D17 says. For comparison, at the pin to 10 MHz the macro reads {noise['total_10Hz_10MHz_uV']:.0f} uV and to 100 MHz {noise['rms_10Hz_100MHz_uV']:.0f} uV.
Of the datasheet-density amplifier term at the low-resistance arm, {dr['BEH60+6.5|lowR']['amp_above_100MHz_uV']:.0f} uV of {dr['BEH60+6.5|lowR']['amp_uV']:.0f} uV lies above 100 MHz, where the density is held flat *(check)*.

Output noise density at the pin (the vendor macro, no network):

| f | model, pin (nV/rtHz) | macro alone |
|---|---|---|
""" + "\n".join(f"| {float(k):.0e} Hz | {v:.1f} | {(f"{noise['macro_only_density_nV'][k]:.1f}" if k in noise['macro_only_density_nV'] else '-')} |" for k, v in noise["density_nV"].items()) + f"""

R thermal at N: {noise['rp_thermal_nV_at_N']:.0f} nV/rtHz from Rp = 250 k, but the node's own {noise['node_pole_Hz']/1e3:.0f} kHz pole limits it
to about 9 uV. REF3030E: 51 uV rms 10 Hz-10 kHz x Rp/R3 = {noise['ref_at_pin_uV']:.0f} uV at the pin (`ref30.pdf` 6.5).

**A bandwidth limit is not needed under D17.** The one-part limit held back as a fallback (Riso 100 ohm and 47 pF C0G more at each pin, corner 34 MHz) reads
{d17['limit_option']['lowR']['vendor']:.0f} uV (macro) and {d17['limit_option']['lowR']['BEH60_ds']:.0f} uV (datasheet) at the low-resistance arm, against {d17_vendor['lowR']:.0f} and {d17_ds['lowR']:.0f}: it buys little where the
capacitor's own pole and Cpx already bound the band. It would leave the S/H settled
({tran['sh_limit_option']['settle_b_ns']:.0f} ns, {abs(tran['sh_limit_option']['err_b_lsb']):.0e} LSB, stress arm {tran['sh_limit_option_stress']['settle_b_ns']:.0f} ns) and PM {tran['limit_option_pm']['pm_deg']:.0f} deg. It is
**not adopted**: SC-5 says no filter and V2-9 says no margin the requirement does not ask for.""")

A_(f"""
## Large signal: SC-12, SC-10, the step

Full-scale sine through 50 ohm (`results/tran.json`):

| f, input | THD | pin slew | Note |
|---|---|---|---|
| 1 MHz, 6 Vpp | {tran['sine1_usable']['thd_dB']:.0f} dB | {tran['sine1_usable']['slew_pin_Vus']:.0f} V/us | |
| 5 MHz, 5 Vpp (rated) | {t5['thd_dB']:.0f} dB | {t5['slew_pin_Vus']:.0f} V/us | pin {t5['vmin']:.2f} to {t5['vmax']:.2f} V |
| 5 MHz, 6 Vpp (usable) | {t5u['thd_dB']:.0f} dB | {t5u['slew_pin_Vus']:.0f} V/us | pin {t5u['vmin']:.2f} to {t5u['vmax']:.2f} V |
| 10 MHz, 6 Vpp | {t10['thd_dB']:.0f} dB | {t10['slew_pin_Vus']:.0f} V/us | |
| 40 MHz, 6 Vpp (control) | {tran['sine40_control']['thd_dB']:.0f} dB | {tran['sine40_control']['slew_pin_Vus']:.0f} V/us | past the macro's limit: the test can fail |

The distortion is the macro's behavioural figure *(check)* and rises when the output nears the rails (0.2 V
and 2.96 V at 6 Vpp); the requirement is *not slew-limited*, and the datasheet slew of 160 V/us at 3 V supply has {160/t10['slew_pin_Vus']:.1f}x of room even at 10 MHz. Step, 2.5 V at the input in
5 ns: 10-90 % rise {tran['step']['rise_10_90_ns']:.1f} ns, **overshoot {max(tran['step']['overshoot_pct'], 0):.1f} %** (none), 0.5 % settling {tran['step']['settle_0p5pct_ns']:.0f} ns. Cpx's pole removes the macro's peaking; the datasheet
suggests 25 ohm in series with the feedback, which is not fitted.

SC-10 (`results/tran.json`, keys `sh_*`): channels alternate through one S/H at the aggregate period (955 ns), one at +4 V in and the other at
-2 V, so the S/H sees the full 2.77 V pin step every conversion; Riso 22 ohm, the pin's Cpin 2 pF and the BAV99's 1.5 pF.
Pin source impedance {tran['zout_pin']['ohm_at_1MHz']:.0f} ohm at 1 MHz, {tran['zout_pin']['ohm_at_100MHz']:.0f} ohm at 100 MHz.""")

A_(f"""
## Stability (AN-1)

Middlebrook loop break at the amplifier's output, the ADC's S/H (3.8 k + 6 pF) on the pin, Cfb 1 pF at the inverting
input, **Cpx 10 pF at +IN**, on the three models (`results/stab.json`). PM / GM in degrees / dB; a dash means the phase never reaches 180 degrees.
The datasheet-fitted models read lower than the vendor macro, and Cpx is what brings them above 45 degrees.

| model, Riso \\\\ extra C at pin | 0 | 10 pF | 22 pF | 47 pF | 100 pF |
|---|---|---|---|---|---|
""" + "\n".join(
    f"| {m}, " + ("no Riso" if r == 0.001 else f"{r:g} ohm") + " | " + " | ".join(
        (lambda g: f"{g['pm_deg']:.0f} / " + (f"{g['gm_dB']:.1f}" if g['gm_dB'] is not None else "-"))(
            next(x for x in stab[m]["grid"] if x["Riso"] == r and x["Cload_pF"] == c)) for c in (0, 10, 22, 47, 100)) + " |"
    for m in MODELS for r in (0.001, 22)) + f"""

With Riso 22 ohm PM is at least {pm_w:.0f} degrees across the grid on the worst model ({worst_m}). With Cpx fitted Riso no longer decides stability (without it PM is at least
{min(A[m]['pm0'] for m in MODELS):.0f} degrees at 100 pF); it sets the pin impedance (22 ohm against SC-10's 5 kohm) and isolates the BAV99 and the pin. Feedback resistor: none (RF = 0).

**Cpx scan.** Minimum PM over the three models and 0, 8 and 18 pF added at the pin, by Cpx (pole = 1/(2 pi Rnp Cpx), Cn 12 pF throughout):

| Cpx | pole | vendor | BEH21 | BEH60 | minimum |
|---|---|---|---|---|---|
""" + "\n".join(f"| {k} pF | {('%.0f MHz' % v['pole_MHz']) if v['pole_MHz'] else '-'} | {v['vendor']:.1f} | {v['BEH21']:.1f} | {v['BEH60']:.1f} | {v['min_all']:.1f} |" for k, v in beh["cpx_scan"].items()) + f"""

4.7 pF would do ({beh['cpx_scan']['4.7']['min_all']:.0f} degrees) but is not a Basic value; 10 pF (C1634) is, and it is the value in the design.""")

A_(f"""
## Protection

**Powered, DC.** The amplifier's input diodes hold N at {pw[(12,12)]['N_a']:.2f} V at +12 V and {pw[(-12,-12)]['N_a']:.2f} V at -12 V, with
{pw[(12,12)]['i_esd_up_uA']:.1f} uA / {pw[(-12,-12)]['i_esd_dn_uA']:.1f} uA in the diodes (the rest runs through R2 and R3 into the REF3030E and ground). **No external clamp is fitted at N.** The datasheet (note 3) allows 10 mA in
these diodes beyond 500 mV past the rail, and R1 limits DC to under 22 uA. An external BAV99 at N would add
about 1.5 pF at N and its leakage times Rp ({prot['bav99_at_N']['rp_k']:.0f} k): at the recalled 30 nA bound that is {prot['bav99_at_N']['err_abs_bound_30nA_node_mV']:.1f} mV at the node, {prot['bav99_at_N']['err_abs_bound_30nA_input_mV']:.0f} mV at the input against SC-7's
5 mV (a DC offset that is calibrated; its voltage dependence, bounded by the conductance of 30 nA / 25 V, is a
{prot['bav99_at_N']['conductance_bound_25V_30nA_gain_pct']:.2f} % gain term). The amplifier's own input leakage is 3 pA max, {prot['amp_leak']['err_node_uV']:.1f} uV. It buys nothing the
diodes already give, so it is not fitted, and the BAT54S question (Extended) does not arise.

**Edge.** Peak input-diode current for a step at the BNC through 50 ohm (the edge couples through C1 straight onto
N, and Cpx holds +IN at ground behind Rnp), by Rnp (the resistor in front of +IN), with Cpx 10 pF and Cn 12 pF:

| Rnp | +12 V, 2 ns | +12 V, 1 ns | -12 V, 2 ns | +30 V, 5 ns (information) |
|---|---|---|---|---|
""" + "\n".join(f"| {(k + ' ohm') if k != '0' else 'none'} | {v['+12V_2ns']['peak_mA']:.1f} mA | {v['+12V_1ns']['peak_mA']:.1f} mA | {v['-12V_2ns']['peak_mA']:.1f} mA | {v['+30V_5ns']['peak_mA']:.1f} mA |" for k, v in ed.items()) + f"""

**Rnp = 470 ohm (C23179) keeps a 12 V edge under 10 mA, by {10 - e12:.1f} mA at -12 V**: thin. Rnp's pole
with Cpx is {1/(2*math.pi*470*10e-12)/1e6:.0f} MHz *(derived)*. A larger Rnp buys current margin and costs bandwidth, noise and phase margin, which are not re-run for
560 or 680 ohm.

**Unpowered** (rail floating with a bleed to ground, REF at 0 V, the Due's 3.3 V net at 0 V, the SAM3X pin as one diode each way; *(assumption)*
throughout: the TPH2502 datasheet gives no unpowered behaviour):

| bleed | +12 V both: rail | pin | current into the Due net | -12 V both: rail | pin |
|---|---|---|---|---|---|
""" + "\n".join(f"| {('none' if b >= 1e9 else f'{b/1e3:g} k')} | {unp[(12,12,b,True)]['rail']:.2f} V | {unp[(12,12,b,True)]['pin_a']:.3f} V | {abs(unp[(12,12,b,True)]['i_due_uA']):.4f} uA | {unp[(-12,-12,b,True)]['rail']:.2f} V | {unp[(-12,-12,b,True)]['pin_a']:.3f} V |" for b in (1e9, 100e3, 30e3, 14e3, 10e3)) + f"""

Both inputs at +12 V push about 18 uA each through R1 into the rail, so **PR-3's 0.5 V rail needs a sink of at least about 36 uA at 0.5 V (a bleed of {prot['bleed_needed']['max_bleed_ohm']/1e3:.1f} kohm or less) on the unpowered +3.3 V_A rail**, and with none the rail
goes to {unp[(12,12,1e9,True)]['rail']:.1f} V. That depends on the other loads on the rail and is for the rail
block, not for this design: it is open item 1. The pin sees at most {unp[(12,12,14e3,True)]['pin_a']:.2f} V.

**Adversarial arm.** The vendor macro carries a back-to-back diode pair between its inputs. If the real die has one, the
unpowered follower connects +IN to its output through it, and at -12 V both inputs the pin falls to
{unpd[(-12,-12,False)]['pin_a']:.3f} V without a pin clamp (PR-2 says -0.2 V: **fails**) and {unpd[(-12,-12,True)]['pin_a']:.3f} V with the BAV99 at the pin ({abs(unpd[(-12,-12,True)]['pin_a'] + 0.2)*1e3:.0f} mV inside). A silicon diode
at 20 uA drops about 0.57 V, so the BAV99 only helps because it shares the current with the two other drops; a
Schottky (BAT54S, Extended) would do better and is not needed in this arm. If the die has no such pair, the pin
stays near 0 V and the BAV99 is not needed. It is fitted as a one-part insurance (Basic, about 1.5 pF on the pin, which the stability grid covers),
*(check)*: one bench read of the unpowered pin at -12 V (VT-5) decides whether to keep it.""")

A_(f"""
## Crosstalk (SC-9) and the layout budget it implies

The two channels share the dual, the supply and the REF3030E. The macro is a single amplifier, so the dual's internal
channel-to-channel coupling is not in it; it is injected as an input-referred source at the datasheet's -100 dB at 5 MHz
(rising 6 dB/octave to -94 dB at 10 MHz is assumed *(check)*), and a -80 dB case. Everything below is the pin
reading of the shorted channel for a 6 Vpp (-2..+4 V) sine on the other, in LSB of 3.2 V / 4096:

| Path | 5 MHz | 10 MHz |
|---|---|---|
| shared rail and REF only | {xt['shared_rail_ref_only_5MHz']['lsb_at_6Vpp']:.0e} | {xt['shared_rail_ref_only_10MHz']['lsb_at_6Vpp']:.0e} |
| datasheet -100 dB (-94 at 10 MHz) | {xt['datasheet_xtalk'][0]['lsb_at_6Vpp']:.3f} | {xt['datasheet_xtalk'][1]['lsb_at_6Vpp']:.3f} |
| -80 dB (what the datasheet would need to be wrong by 20 dB) | | {xt['datasheet_xtalk'][2]['lsb_at_6Vpp']:.2f} |
| 0.01 pF between the two N nodes | {cxn[(0.01,5.0)]:.2f} | {cxn[(0.01,10.0)]:.2f} |
| 0.02 pF | {cxn[(0.02,5.0)]:.2f} | {cxn[(0.02,10.0)]:.2f} |
| 0.05 pF | {cxn[(0.05,5.0)]:.2f} | {cxn[(0.05,10.0)]:.2f} |
| 0.1 pF | {cxn[(0.1,5.0)]:.2f} | {cxn[(0.1,10.0)]:.2f} |
| 0.2 pF | {cxn[(0.2,5.0)]:.2f} | {cxn[(0.2,10.0)]:.2f} |
| 0.05 pF between the two +IN pads (pins 3 and 5) | {cxp[(0.05,5.0)]:.2f} | {cxp[(0.05,10.0)]:.2f} |
| 0.1 pF | {cxp[(0.1,5.0)]:.2f} | {cxp[(0.1,10.0)]:.2f} |
| 0.2 pF | {cxp[(0.2,5.0)]:.2f} | {cxp[(0.2,10.0)]:.2f} |
| 0.5 pF | {cxp[(0.5,5.0)]:.2f} | {cxp[(0.5,10.0)]:.2f} |
| 0.2 pF between the two input nets | {cxi[(0.2,5.0)]:.2f} | {cxi[(0.2,10.0)]:.2f} |
| 0.5 pF between the two input nets | {cxi[(0.5,5.0)]:.2f} | {cxi[(0.5,10.0)]:.2f} |

The circuit's own coupling is negligible; **the layout's is not**. The high-impedance node set is N (the R1/R2/R3 junction, C1, Cn, the Rnp pad) **and the +IN pad**:
at 10 MHz each sits at a few hundred ohms (the capacitive divider at N; Rnp plus that, against Cpx, at +IN), and a stray between the two channels' copies of either
injects the other channel's full pin-level signal. N to N costs {xt['Cx_N_for_1LSB_10MHz_pF']*1e3:.0f} fF per LSB, pad to pad {xt['Cx_pad_for_1LSB_10MHz_pF']*1e3:.0f} fF per LSB, input net to input net {xt['Cx_in_for_1LSB_10MHz_pF']*1e3:.0f} fF per LSB, and the strays add (the two together read
{bud_lsb:.2f} LSB at {BUD_N:g} pF each, {comb[(0.03,0.03,10.0)]:.2f} LSB at 0.03 pF each, {comb[(0.05,0.0,10.0)]:.2f} at 0.05 pF N to N alone). The +IN pad figure matters because the
dual's pins 3 and 5 are two pins apart with V- between them: **the budget is {BUD_N:g} pF N to N and {BUD_P:g} pF pad to pad, together {bud_lsb:.1f} LSB at 6 Vpp and 10 MHz against SC-9's 2**, and the two input nets
under about {xt['Cx_in_for_1LSB_10MHz_pF']*2:.2f} pF. A pad coupling of 0.02 pF is {xt['pad_0p02pF_by_Rnp']['470']:.2f} LSB on its own; it falls with a lower Rnp ({xt['pad_0p02pF_by_Rnp']['100']:.2f} at 100 ohm,
{xt['pad_0p02pF_by_Rnp']['1000']:.2f} at 1 kohm) and with a larger Cpx ({xt['pad_0p02pF_by_Cpx_pF']['22']:.2f} at 22 pF, {xt['pad_0p02pF_by_Cpx_pF']['4.7']:.2f} at 4.7 pF), which are circuit levers if the layout cannot reach it. Whether 20 fF between pins 3 and 5 is
reachable is not known: the pin-to-pin capacitance of a SOP-8 with a grounded pad between is not in the repository *(check: field solver, or VT-19's extraction)*.
The AWG-into-scope coupling of SC-9 is not in this block. VT-10 on the first board decides the scope-to-scope figure, as D16 says.""")

A_(f"""
## Reference loading and the SC-7 terms

REF3030E (E grade, `ref30.pdf` 6.5): sink and source both specified to +-10 mA; load regulation 15 ppm/mA source (max), 150 ppm/mA sink (max);
short-circuit 35 mA. Here: per channel the reference sources {mc['ref_source_uA_max_per_channel']:.2f} uA at the bottom of the usable range and 5.4 uA at -12 V, and sinks
{abs(pw[(12,12)]['i_ref_uA'])/2:.2f} uA with an input at +12 V (clamped by the amplifier's diodes), so it is never near the rating, and the signal-dependent
change in V_REF is under {2*5.4e-3*3*15:.1f} uV (source) and {2*1.6e-3*3*150:.1f} uV (sink) *(derived from the specified load regulation)*. The reference's Zout does not
couple the channels (shared-REF and rail coupling together is {xt['shared_rail_ref_only_10MHz']['lsb_at_6Vpp']:.0e} LSB). The {noise['ref_at_pin_uV']:.0f} uV of REF noise that reaches the pin is in the noise total.

## Guards: each check broken on purpose

Every check below was run against a deliberately wrong circuit (or a deliberately wrong input to its method) and had to fail (`guards.json`); a line marked *positive control* is
instead a reading that must hold for the method to be trusted. All behaved as intended: **{'yes' if gd['all_fail_as_intended'] else 'NO'}**.

| Check | Mutation | Reading | Failed |
|---|---|---|---|
| DC margins | REF3030E disconnected (R3 = 10 M) | low margin {gd['margin_check_with_R3_open']['lo_mV']:.0f} mV | {'yes' if gd['margin_check_with_R3_open']['fails'] else 'NO'} |
| compensation step | C1 = 12 pF | 95th percentile +-{gd['shelf_check_with_C1_12pF']['p95_abs_pct']:.0f} % | {'yes' if gd['shelf_check_with_C1_12pF']['fails'] else 'NO'} |
| compensation step | Cn left at 22 pF with Cpx 10 pF fitted | 95th percentile +-{gd['shelf_check_Cn22_with_Cpx']['p95_abs_pct']:.0f} %, mean {gd['shelf_check_Cn22_with_Cpx']['mean_pct']:+.0f} % | {'yes' if gd['shelf_check_Cn22_with_Cpx']['fails'] else 'NO'} |
| phase margin | no Riso, 1 nF at the pin (BEH60) | PM {gd['pm_check_noRiso_1nF_BEH60']['pm_deg']:.1f} deg | {'yes' if gd['pm_check_noRiso_1nF_BEH60']['fails'] else 'NO'} |
| phase margin | no Cpx (BEH60) | PM {gd['pm_check_noCpx_BEH60']['pm_deg']:.1f} deg | {'yes' if gd['pm_check_noCpx_BEH60']['fails'] else 'NO'} |
| slew / THD | 40 MHz in place of 5 MHz | THD {gd['thd_check_40MHz']['thd_40MHz_pct']:.1f} % against {gd['thd_check_40MHz']['thd_5MHz_pct']:.2f} % | {'yes' if gd['thd_check_40MHz']['fails'] else 'NO'} |
| S/H settling | 20 kohm in place of 22 ohm | {gd['settling_check_20k']['err_lsb']:.0f} LSB | {'yes' if gd['settling_check_20k']['fails'] else 'NO'} |
| crosstalk | 0.2 pF between the N nodes | {gd['xtalk_check_Cx_0p2pF']['lsb']:.1f} LSB | {'yes' if gd['xtalk_check_Cx_0p2pF']['fails'] else 'NO'} |
| crosstalk | 0.2 pF between the +IN pads | {gd['xtalk_check_pad_0p2pF']['lsb']:.1f} LSB | {'yes' if gd['xtalk_check_pad_0p2pF']['fails'] else 'NO'} |
| crosstalk budget | 0.03 pF on both | {gd['xtalk_check_combined_0p03']['lsb']:.2f} LSB | {'yes' if gd['xtalk_check_combined_0p03']['fails'] else 'NO'} |
| PR-3 rail | no bleed | rail {gd['rail_check_no_bleed']['rail_V']:.1f} V | {'yes' if gd['rail_check_no_bleed']['fails'] else 'NO'} |
| PR-1 edge | no Rnp | {gd['edge_check_no_Rnp']['peak_mA']:.0f} mA | {'yes' if gd['edge_check_no_Rnp']['fails'] else 'NO'} |
| SM-3 | Rnp 4.7 kohm | -3 dB at {gd['bw_check_Rnp4k7']['f3dB_MHz']:.1f} MHz | {'yes' if gd['bw_check_Rnp4k7']['fails'] else 'NO'} |
| D17 reading | ADC network detached | {gd['d17_check_network_detached']['detached_uV']:.0f} uV against {gd['d17_check_network_detached']['with_network_uV']:.0f} uV with it | {'yes' if gd['d17_check_network_detached']['fails'] else 'NO'} |
| D17 reading | amplifier source disconnected | amplifier term {gd['d17_check_injection_disconnected']['amp_uV_disconnected']:.0f} uV against {gd['d17_check_injection_disconnected']['amp_uV_connected']:.0f} uV | {'yes' if gd['d17_check_injection_disconnected']['fails'] else 'NO'} |
| D17 integrator | linear-f trapezoid on 2 points per decade | {gd['d17_integrator_mutant']['rel_err']*100:.0f} % off an analytic RC | {'yes' if gd['d17_integrator_mutant']['fails'] else 'NO'} |
| D17 verdict | a 100 nV/rtHz amplifier | {gd['d17_check_noisy_amp_100nV']['total_uV']:.0f} uV | {'yes' if gd['d17_check_noisy_amp_100nV']['fails'] else 'NO'} |
| static step | bias-dependent (X7R-like) C1 and Cn | step moves {gd['static_check_voltage_dependent_caps']['spread_pp']:.1f} pp | {'yes' if gd['static_check_voltage_dependent_caps']['fails'] else 'NO'} |
| *positive control* | the sampling capacitor's own kT/C switched on | adds {gd['d17_check_ktc']['added_uV']:.1f} uV against {gd['d17_check_ktc']['kTC_uV']:.1f} | {'held' if gd['d17_check_ktc']['passes_as_positive_control'] else 'NO'} |
| *positive control* | transfer route (BEH21, 9.3 nV) against the vendor macro, 10 Hz to 10 MHz | {gd['d17_pipeline_vs_vendor_10MHz']['beh21_9p3_uV']:.1f} uV against {gd['d17_pipeline_vs_vendor_10MHz']['vendor_uV']:.1f} | {'held' if gd['d17_pipeline_vs_vendor_10MHz']['passes_as_positive_control'] else 'NO'} |
| *positive control* | integrator against an analytic RC, 40 points per decade | {gd['d17_integrator_fine']['rel_err']*100:.2f} % | {'held' if gd['d17_integrator_fine']['passes_as_positive_control'] else 'NO'} |

The Monte Carlo itself is anchored by the ngspice cross-check above (12 draws, {mc['crosscheck_max_gain_err_pct']:.3f} % in gain). What none of these checks can show is
a defect of the *macro*: that is the open items below.
""")

A_(f"""
## Open items and spec questions

**Settled by the spec lead (2026-11-12), and what the study holds**

| Question | Answer | Where it stands |
|---|---|---|
| SC-6's band | D17: the noise that reaches the Due's sampling capacitor, through the stage and the ADC input network | read here: {d17_vendor['lowR']:.0f} uV (macro) and {d17_ds['lowR']:.0f} uV (datasheet density) at the low-resistance arm, against 200 |
| SC-3's +-6 % step from 5 % C0G | accepted as a design call if static | shown static: no level dependence, a temperature dependence equal to the DC gain's drift |
| SC-9 and the layout | LR-3 carries the rule, VT-19 the check, with the +IN pads in the budget | the budget is {BUD_N:g} pF N to N and {BUD_P:g} pF pad to pad ({bud_lsb:.1f} LSB), tighter than the 0.05 pF first stated |
| PR-2's pin clamp | BAV99 per pin kept | VT-5 may drop it |
| SC-4 at 70.34 % of full scale | accepted | |

**Open (check)s**

1. **PR-3 rail sink** (the powercal stream owns it). Both inputs at +12 V with the Due unpowered push about 36 uA into the +3.3 V_A rail through the amplifier's input diodes; the rail needs a sink of that size at 0.5 V ({prot['bleed_needed']['max_bleed_ohm']/1e3:.1f} kohm or less) and the quiescent cost of a permanent bleed that small is 0.23 mA at 3.3 V *(derived)*. Whether the LM27762 and the other ICs already provide it is not in this study.
2. **The macro is the TPH2501's, a single amplifier, and no vendor TPH2502 model exists here.** Noise density (9.3 against the datasheet's 6.5 nV, both read), distortion (the SC-12 THD figures), the unpowered input structure, the rail-to-rail crossover and the dual's internal crosstalk are not the part's. VT-1, VT-3, VT-5 and VT-10 on the first board close them.
3. **The Due's ADC input switch and sampling capacitor** (3.8 kohm / 6 pF derived, 1 kohm / 8 pF the low arm) are not measured; they set D17's figure and the response at the sampling capacitor. VT-3 and VT-16 with an external instrument close it.
4. **The datasheet gives no input-diode I-V and no unpowered behaviour**; the protection and the PR-2 adversarial arm rest on a generic diode. One bench read of the unpowered pin at -12 V decides the pin BAV99. The PR-1 edge margin ({10 - e12:.1f} mA under the datasheet's 10 mA) rests on the same diode.
5. **BAV99 figures** (VF, CJ, IR) are recalled and not read from a datasheet *(check)*; the BAV99 is only at the pin, where they do not matter at these currents.
6. **Parasitics** (stray at N 2-6 pF, across R1 0.1 pF, BNC and trace 4 pF) are assumptions; the two channels' mutual strays (SC-9) are layout numbers, and nothing here says what a SOP-8 can reach between pins 3 and 5.
7. **C0G's bias, temperature and ageing figures** are the EIA class's, not read from the Samsung datasheet *(check: not in the repository)*.
8. **CMRR at 3.3 V supply** (65 dB is specified at VS 5.4 V) and VOS across the input range (specified at one VCM): the crossover of the rail-to-rail input could add a step the linear calibration does not remove.
9. **Output swing near the rails at 3.3 V**: the datasheet gives 2/30 mV at 100 kOhm; the pin range needs 0.17 to 2.98 V, so it is not close, but it is not read at 3.3 V.
10. **Supply current**: 2 x 7.5 mA max at 3.3 V for the scope dual *(derived from IQ max, datasheet page 4)*.

**Spec questions still open (for the orchestrator)**

1. **Where SM-3's 8 MHz is read.** At the pin the stage is {pin_f3_min:.0f} MHz or better; at the Due's sampling capacitor the Due's own switch pole is {adc_pole['derived']:.1f} MHz at the derived 3.8 kohm / 6 pF. Confirm SM-3 is a pin figure (VT-16 measures it there).
2. **The pad budget.** The layout must hold {BUD_P * 1e3:.0f} fF between pins 3 and 5 and {BUD_N * 1e3:.0f} fF between the N nodes. If that is not credible, the circuit levers above (a lower Rnp, a larger Cpx) or one dual per channel (D16's fallback) are the choices.
3. **Rnp 470 ohm and the 10 mA note.** The margin is {10 - e12:.1f} mA at -12 V. A larger Rnp (560 ohm: {ed['560']['-12V_2ns']['peak_mA']:.1f} mA) needs its bandwidth, noise and phase margin re-run.
4. **Cn 12 pF** is a second C0G value (C38523) beside C1's 22 pF and Cpx's 10 pF; C1 20 pF with Cn 10 pF (the same part as Cpx) would drop one value at a 95th percentile of {alt['p95_abs_pct']:.1f} % in place of {cp['p95_abs_pct']:.1f} %. Confirm 12 pF.
""")
open(os.path.join(HERE, "report.md"), "w").write("\n".join(out))
print("report.md:", len(rows), "rows,", "fails:", fails)
