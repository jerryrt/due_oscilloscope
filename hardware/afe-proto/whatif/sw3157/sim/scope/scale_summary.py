"""Summary of the RF/RG scaling runs (sw.py keys <cand>_x<k>).  python3 -I scale_summary.py"""
import json, os
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
j = lambda n: json.load(open(os.path.join(HERE, "results", n + ".json")))
C = json.load(open(os.path.join(HERE, "..", "..", "..", "..", "models-open", "sw3157", "curves.json")))
# Nexperia Fig. 10: Ron at Vmid (1.6 V) against temperature, linear between the tabulated curves
T = np.array([-40, 25, 85, 125]); RV = np.array([np.interp(1.6, C["V"], C["NX"][str(t)]) for t in T])
def ron_T(t, scale=1.0): return float(np.interp(t, T, RV)) * scale
def dc(lab):
    d = j("dc_" + lab); T5 = d["aref_table"]["5"]; T12 = d["aref_table"]["1.25"]
    g5 = (T5["3.30"]["gain_min"], T5["3.30"]["gain_max"]); g12 = (T12["3.20"]["gain_min"], T12["3.20"]["gain_max"])
    return dict(sc2=T5["3.20"]["margin_wc"] * 1e3, occ=(10 * g5[0] / 3.3 * 100, 10 * g5[1] / 3.3 * 100),
                sc8=(g5[1] - g5[0]) / np.mean(g5) * 100, sc11=g12, sc11m=T12["3.20"]["margin_wc"] * 1e3)
rows = []
for k in (1, 1.5, 2, 3, 4):
    RG, RF = 249.0 * k, 953.0 * k
    for c in ("tmux1119", "nx3157"):
        lab = f"{c}_x{str(k).replace('.', 'p')}"
        a = j("ac_" + lab); n = j("noise_" + lab); x = j("xt_" + lab); i = j("inl_" + lab); d = dc(lab)
        r = dict(part=c, k=k, RF=RF, RG=RG, sm3_5=a["5"]["worst"]["bw"] / 1e6, sm3_12=a["1.25"]["worst"]["bw"] / 1e6,
                 pm=min(a["5"]["worst"]["pm"], a["1.25"]["worst"]["pm"]), sc6=(n["5"]["total_V"] * 1e6, n["1.25"]["total_V"] * 1e6),
                 sc9=max(x["5"]["dc_step_lsb"], x["5"]["sine_max_lsb"], x["1.25"]["dc_step_lsb"], x["1.25"]["sine_max_lsb"]),
                 sc7_typ=i["5_typ_switch_only"]["sc7_fraction_max"] * 100, sc7_max=i["5_mx_switch_only"]["sc7_fraction_max"] * 100,
                 inl_max_codes=i["5_mx_switch_only"]["inl_codes_max"], sc7_tot_max=i["5_mx"]["sc7_fraction_max"] * 100, sc7_tot_typ=i["5_typ"]["sc7_fraction_max"] * 100, **d)
        # op-amp output current at +6 V in (+/-5 V range: the RG leg through the closed switch) and +1.25 V (RF + RG leg)
        r["iout_mA"] = (1.4 / RG * 1e3, 1.4 / (RF + RG) * 1e3)
        if c == "nx3157":
            r["dc_r20"] = dc(f"nx3157_r20_x{str(k).replace('.', 'p')}")
            # EN-1: gain drift from Ron's tempco at the max corner (curve scaled x 20/7.698), and typical
            for nm, s in (("typ", 1.0), ("max", 20 / 7.698)):
                r[f"en1_{nm}"] = abs(ron_T(35, s) - ron_T(15, s)) / RG * 100
                r[f"hot_{nm}"] = abs(ron_T(85, s) - ron_T(25, s)) / RG * 100
        rows.append(r)
json.dump(rows, open(os.path.join(HERE, "results", "scale_summary.json"), "w"), indent=1)
for r in rows:
    print(f"{r['part']:9s} x{r['k']} RF/RG {r['RF']:.1f}/{r['RG']:.0f} | SM-3 {r['sm3_5']:.1f}/{r['sm3_12']:.2f} MHz PM {r['pm']:.1f} | SC-6 {r['sc6'][0]:.0f}/{r['sc6'][1]:.0f} uV | "
          f"SC-9 {r['sc9']:.3f} LSB | SC-7 share typ {r['sc7_typ']:.0f}% max {r['sc7_max']:.0f}% ({r['inl_max_codes']:.2f} codes); with the rest of the channel typ {r['sc7_tot_typ']:.0f}% max {r['sc7_tot_max']:.0f}% | "
          f"SC-2 {r['sc2']:.0f} mV occ {r['occ'][0]:.1f}-{r['occ'][1]:.1f}% SC-8 {r['sc8']:.2f}% SC-11 {r['sc11'][0]:.4f}-{r['sc11'][1]:.4f} m{r['sc11m']:.0f} | Iout {r['iout_mA'][0]:.2f}/{r['iout_mA'][1]:.2f} mA"
          + (f" | r20: SC-2 {r['dc_r20']['sc2']:.0f} occ {r['dc_r20']['occ'][1]:.1f}% SC-8 {r['dc_r20']['sc8']:.2f}% | EN-1(15-35) typ {r['en1_typ']:.3f}% max {r['en1_max']:.3f}%; 25-85 typ {r['hot_typ']:.2f}% max {r['hot_max']:.2f}%" if 'dc_r20' in r else ""))
