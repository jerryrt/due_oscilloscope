import json, os
L=lambda n: json.load(open(f"results/{n}.json"))
mv=lambda x: f"{x*1e3:.1f} mV"
d=L("dc_OPA365"); T5=d["aref_table"]["5"]; T12=d["aref_table"]["1.25"]
print("SC-2 +/-5 AREF3.20 wc", mv(T5["3.20"]["margin_wc"]), "hi", mv(T5["3.20"]["margin_hi_wc"]), "lo", mv(T5["3.20"]["margin_lo_wc"]))
print("SC-2 lowest AREF", d["lowest_aref"], "at 3.10:", mv(T5["3.10"]["margin_wc"]), mv(T12["3.10"]["margin_wc"]))
g=T5["3.30"]; print("SC-4 gain@3.30", g["gain_min"], g["gain_max"], "step mV", 3.3/4096/g["gain_max"]*1e3, 3.3/4096/g["gain_min"]*1e3, "occ", 10*g["gain_min"]/3.3*100, 10*g["gain_max"]/3.3*100, "occ@3.20", 10*T5["3.20"]["gain_min"]/3.2*100, 10*T5["3.20"]["gain_max"]/3.2*100)
print("SC-11 gain@3.20", T12["3.20"]["gain_min"], T12["3.20"]["gain_max"], "margin", mv(T12["3.20"]["margin_wc"]))
print("headroom", d["headroom"]); print("MC", d["mc"])
d4=L("dc_OPA354"); print("OPA354 330k SC-2", mv(d4["aref_table"]["5"]["3.20"]["margin_wc"]), mv(d4["aref_table"]["1.25"]["3.20"]["margin_wc"]), "gains", d4["aref_table"]["5"]["3.30"]["gain_min"], d4["aref_table"]["5"]["3.30"]["gain_max"], d4["aref_table"]["1.25"]["3.20"]["gain_min"], d4["aref_table"]["1.25"]["3.20"]["gain_max"])
zi=L("zin"); print("SC-3", zi)
ac=L("ac")
for k,v in ac.items():
    n=v["nominal"]; w=v["worst"]
    pms=min(x["pm"] for x in v["sens"])
    print("AC",k,f"g0 {n['g0']:.4f} bw {n['bw']/1e6:.2f} pk {n['peak_db']:.2f} pm {n['pm']:.1f} | worst bw {w['bw']/1e6:.2f} pm {w['pm']:.1f} pk {w['peak_db']:.2f} | sens pm min {pms:.1f} | noRiso10pF {v['no_riso_10pF']} | gdvar {n['gd_var_ns']:.1f} flat {n['flat_db']}")
nz=L("noise")
for k,v in nz.items():
    print("NOISE",k,{l:(round(v[l]['fmax']/1e6,1), round(v[l]['total_V']*1e6,1)) for l in ("at_bw","at_1p5bw","at_10MHz")}, "dens", v["density_nV"])
kk=L("kick")
xt=max(v["crosstalk_lsb"] for v in kk.values() if isinstance(v,dict) and "crosstalk_lsb" in v)
err=max(max(abs(v["full_swing"]["errA_lsb"]),abs(v["full_swing"]["errB_lsb"])) for v in kk.values() if isinstance(v,dict) and "full_swing" in v)
st=max(v["full_swing"]["settleB_ns"] for v in kk.values() if isinstance(v,dict) and "full_swing" in v)
zo=max(v["zout"]["zmax_to_10MHz"] for v in kk.values() if isinstance(v,dict) and "zout" in v)
print("SC-9 xt", xt, "SC-10 err", err, "settle", st, "Z", zo, "qinj", kk["charge_injection"])
pr=L("prot"); dcp=pr["dc"]
pw=[v for k,v in dcp.items() if "|powered|" in k]; ed=list(pr["edge"].values())
pmax=max(max(v["v_pin"] for v in pw),max(v["pin_max"] for v in ed)); pmin=min(min(v["v_pin"] for v in pw),min(v["pin_min"] for v in ed))
print("PR-2", pmin, pmax); print("PR-1 ipk", max(v["i_clamp_peak_mA"] for v in ed), "dc uA", max(v["i_clamp_uA"] for v in dcp.values()))
idue=max(abs(v["i_due33_uA"]) for v in dcp.values()); iin=max(v["i_in_uA"] for v in dcp.values())
print("PR-3 idue", idue, "iin", iin, "rail", iin*4.7e3*1e-6)
for k,v in dcp.items():
    if "unpowered" in k or "floating_4700" in k: print("  ",k, {a:round(b,3) for a,b in v.items()})
print("above30", pr["above30"])
ed=L("edge")
for k,v in ed.items(): print("EDGE",k,{a:round(b,2) for a,b in v.items()})
cp=L("comp")
for k,v in cp.items(): print("COMP",k,{a:round(b,3) for a,b in v.items()})
for g in L("guards_c2"): print("GUARD",g["guard"],"|",g["mutation"],"|",g["good"]["ok"],g["good"]["detail"],"|",g["broken"]["ok"],g["broken"]["detail"],"|",g["restored"]["ok"],"| eff",g["effective"])
