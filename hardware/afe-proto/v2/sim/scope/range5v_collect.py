#!/usr/bin/env python3
"""Collect the range-5v study's ngspice results into one table and the A/B stray-capacitance sensitivity file.

    python3 -I range5v_collect.py            writes range5v/sensitivity_n_stray_5v.json and range5v/summary_5v.json

Reads range5v/{results,caseA,caseB}/ (values of version 1, C1 12 p / Cn 30 p) and range5v/c18-47/{results,caseA,caseB}/ (C1 18 p /
Cn 47 p), written by `run.py --range 5v|5vc` (range5v.md has the commands), and the version 2 range's own results/ for the
comparison.  The metrics and their definitions are those of ../sensitivity_n_stray.json, so the files compare row by row.
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SETS = {"v2 -1.5..+3.5 V (C1 22 / Cn 12)": ("", None), "5 V, C1 12 / Cn 30": ("range5v", "5v"), "5 V, C1 18 / Cn 47": ("range5v/c18-47", "5vc")}


def L(d, name):
    with open(os.path.join(HERE, d, "results", f"{name}.json")) as f:
        return json.load(f)


def metrics(d):
    ac, bw, x, st, stab = L(d, "ac"), L(d, "bw"), L(d, "xtalk"), L(d, "static"), L(d, "stab")
    comb = [c for c in x["combined"] if c["Cx_N_pF"] == 0.02 and c["Cx_pad_pF"] == 0.02 and c["f_MHz"] == 10.0][0]
    return {
        "f3dB_MHz": ac["f3dB_Hz"] / 1e6,
        "droop_10MHz_dB": ac["dev_10MHz_dB"],
        "nominal_shelf_pct": ac["shelf_pct"],
        "pin_f3dB_MHz_worst": min(v["pin"]["f3dB_MHz"] for m in bw for v in bw[m].values()),
        "sc9_shared_rail_10MHz_lsb": x["shared_rail_ref_only_10MHz"]["lsb_at_6Vpp"],
        "sc9_budget_0p02_0p02_10MHz_lsb": comb["lsb_at_6Vpp"],
        "N_to_N_fF_per_lsb": x["Cx_N_for_1LSB_10MHz_pF"] * 1e3,
        "pad_to_pad_fF_per_lsb": x["Cx_pad_for_1LSB_10MHz_pF"] * 1e3,
        "in_to_in_fF_per_lsb": x["Cx_in_for_1LSB_10MHz_pF"] * 1e3,
        "step_spread_pp": st["vendor"]["spread_pp_100kHz"],
        "nominal_pm_deg": {m: stab[m]["nominal"]["pm_deg"] for m in stab},
    }


def main():
    out = {"what": "the range-5v study's sensitivity to the extracted stray at N, as ../sensitivity_n_stray.json defines it (A: 4.31 pF at N, extraction added; "
                   "B: 0.81 pF, extraction replacing the assumption; Cx N-to-N 0.05 fF in both)", "results": {}}
    for label, (d, rng) in SETS.items():
        if rng is None:
            continue
        out["results"][label] = {"baseline": metrics(d), "A_N_stray_plus_0p81pF": metrics(os.path.join(d, "caseA")),
                                 "B_N_stray_replaced_by_0p81pF": metrics(os.path.join(d, "caseB"))}
    with open(os.path.join(HERE, "range5v", "sensitivity_n_stray_5v.json"), "w") as f:
        json.dump(out, f, indent=1)
    summ = {}
    for label, (d, rng) in SETS.items():
        mc, dc, tr, nz, d17, stab, beh, pr = (L(d, n) for n in ("mc", "dc", "tran", "noise", "d17", "stab", "beh", "prot"))
        row = dict(
            a_nominal=dc["a"], centre_V=dc["voff"], rin_nominal_k=mc["rin_nominal_k"], rin_k_1pct=mc["rin_k"], cin_net_pF=mc["cin_pF"],
            span_pct_FS_3p25=mc["span_pct_FS_3p25"], mV_per_code_worst=mc["mV_per_code_worst"],
            lo_margin_mV_with_30mV=mc["lo_margin_mV_min_with_30mV"], hi_margin_mV_with_30mV=mc["hi_margin_mV_min_with_30mV"],
            lo_slack_mV=mc["lo_slack_mV_with_30mV"], hi_slack_mV=mc["hi_slack_mV_with_30mV"], corners=mc["corners"],
            shelf_pct=mc["shelf_pct"], gain_match_pct_max=mc["gain_match_pct_max"], offset_match_mV_max=mc["offset_match_mV_max_at_pin"],
            gain_drift_20K_pct=mc["gain_drift_20K_pct"], drift_10K_input_mV=mc["drift_10K_input_mV"],
            ref_source_uA=mc["ref_source_uA_max_per_channel"], ref_sink_uA=mc["ref_sink_uA_clamped_per_channel"],
            dc_max_dev_mV=dc["max_dev_mV"], settle_b_ns=tr["sh_derived"]["settle_b_ns"], sh_err_lsb=max(abs(tr["sh_derived"]["err_a_lsb"]), abs(tr["sh_derived"]["err_b_lsb"])),
            sine_thd_pct_5MHz_usable=tr["sine5_usable"]["thd_pct"], sine_slew_Vus_10MHz_usable=tr["sine10_usable"]["slew_pin_Vus"],
            noise_d17_total_uV={k: v["total_uV"] for k, v in d17["rows"].items()}, ref_noise_at_pin_uV=nz["ref_at_pin_uV"],
            pm_nominal={m: stab[m]["nominal"]["pm_deg"] for m in stab}, pm_grid_min={m: min(r["pm_deg"] for r in stab[m]["grid"] if r.get("pm_deg")) for m in stab},
            beh_cpx10_min_pm=beh["cpx_scan"]["10"]["min_all"],
            edge_470_mA={k: v["peak_mA"] for k, v in pr["edge"]["470"].items()}, edge_0_mA={k: v["peak_mA"] for k, v in pr["edge"]["0"].items()},
            bleed_max_ohm=pr["bleed_needed"]["max_bleed_ohm"])
        summ[label] = row
    with open(os.path.join(HERE, "range5v", "summary_5v.json"), "w") as f:
        json.dump(summ, f, indent=1, default=float)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
