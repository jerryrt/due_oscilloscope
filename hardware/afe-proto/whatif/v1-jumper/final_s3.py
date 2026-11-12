#!/usr/bin/env python3
"""The final version 1 sense design under structure S3: positions (both ADS pins), PR-3/PR-4, AWG load, precision and ablation, SC-7 stack, guards."""
import json, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import net
from net import *
import ranges, s3, stack
from s3 import s3design

N = int(os.environ.get("N", 20000))
FINAL = s3design(22e3, 15e3, 3.9e3, 13e3, "TAP3")      # R7 22k, R8 15k, Rd 1k, Rs 3.9k, Rm 13k = Rt||Rb + Rs = 8.9k + 3.9k = 12.8k
KVM = s3design(15e3, 10e3, 3.9e3, 10e3, "TAP3")         # kvm_02's v2 values on the v1 ladder and window
R = {}

def p99(r): return dict(gain_pct=float(np.percentile(abs(r["gain"]), 99.9) * 100), off_mV=float(np.percentile(abs(r["off"]), 99.9) * 1e3),
                        err_mV=float(np.percentile(abs(r["err"]).max(0), 99.9) * 1e3), k_err_pct=float(np.percentile(abs(r["k"] / r["ktrue"] - 1), 99.9) * 100))

def positions_s3(d):
    rows = []
    for name, wire, Vx, where in ranges.states(d):
        sp = ranges.span(d, wire, Vx)
        t0 = np.concatenate([sp[a][0]["T0"] for a in sp]); tmin, tmax = float(t0.min()), float(t0.max())
        bb = np.concatenate([sp[a][0]["B"] for a in sp]); bmin, bmax = float(bb.min()), float(bb.max())
        iT = iB = 0.0; pT = []; pB = []; iref = 0.0
        for A, (nd, P) in sp.items():
            n = len(nd["T0"])
            nd2 = solve_net(A, P["ref"], P["rl3"], P["rl5"], P["Rt"], P["Rb"], P["Rd"], P["Rs"], np.full(n, 1e15), 0.0, wire, Vx)
            vT, iu, idn = ranges.pin_with_clamp(nd2["T0"], ranges.thevenin_R(d, P, wire), VDD_MIN); pT.append(vT); iT = max(iT, float(np.max(iu + idn)))
            rb = P["Rm2"] + (0.0 if (wire == "fixed") else (250.0 if wire in NODE else 1e3))
            vB, iu, idn = ranges.pin_with_clamp(nd2["B"], rb, VDD_MIN); pB.append(vB); iB = max(iB, float(np.max(iu + idn)))
            i = (nd["ref"] - nd["TAP5"]) / P["rl5"][:, 4] + (nd["ref"] - nd["B"]) / P["Rd"]; iref = max(iref, float(np.abs(i).max()))
        rows.append(dict(state=name, where=where, t0=(tmin, tmax), B=(bmin, bmax), in_range=bool(tmin >= 0 and tmax <= VDD_MIN and bmin >= 0 and bmax <= VDD_MIN),
                         pinT=(float(np.concatenate(pT).min()), float(np.concatenate(pT).max())), pinB=(float(np.concatenate(pB).min()), float(np.concatenate(pB).max())),
                         iT_uA=iT * 1e6, iB_uA=iB * 1e6, iref_mA=iref * 1e3))
    return rows

def main():
    d = FINAL
    R["design"] = dict(Rt=d["Rt"], Rb=d["Rb"], Rd=d["Rd"], Rs=d["Rs"], Rm=d["Rm2"], k=kof(d), rth=rth(d), wire=d["wire"])
    # 1. positions
    R["positions"] = positions_s3(d)
    for r in R["positions"]:
        print(f"{r['state']:60s} T0 {r['t0'][0]:+.3f}..{r['t0'][1]:.3f} B {r['B'][0]:.2f}..{r['B'][1]:.2f} {'in ' if r['in_range'] else 'OUT'} pinT {r['pinT'][0]:+.3f} pinB {r['pinB'][0]:+.3f}..{r['pinB'][1]:+.3f} iT {r['iT_uA']:.1f} iB {r['iB_uA']:.1f} uA Iref {r['iref_mA']:.2f}")
    dt = ranges.detect(d); R["detect"] = dict(right=dt["right"], gaps=[(r["state"], r["gap"]) for r in dt["rows"]], min_gap=min(r["gap"] for r in dt["rows"]))
    print("detect min gap mV", R["detect"]["min_gap"] * 1e3)
    # 2. PR-3 / PR-4
    R["pr"] = {}
    for V in (5.0, -5.0, 1.8, -1.8, 12.0, -12.0):
        for powered in (True, False):
            for w in (None, d["wire"]):
                x = s3.forced_s3(d, V, powered, w); R["pr"][f"{V:+.1f}/{'pow' if powered else 'unp'}/{w or 'off'}"] = x
                if V in (5.0, -5.0, -1.8): print(f"{V:+5.1f} V {'pow' if powered else 'unp'} {w or 'off':5s} Tpin {x['pinT'][0]:+.3f}..{x['pinT'][1]:+.3f} Bpin {x['pinB'][0]:+.3f}..{x['pinB'][1]:+.3f} rail-current {x['i_rail_uA']:.0f} uA gnd {x['i_gnd_uA']:.0f} rail {x['rail_V']:.3f} V")
    kv = {f"{V:+.1f}": [s3.forced_s3(KVM, V, False, w) for w in (None, KVM["wire"])] for V in (5.0, -5.0)}
    R["pr_kvm_values"] = {k: dict(rail_V=max(x["rail_V"] for x in v), i_rail_uA=max(x["i_rail_uA"] for x in v)) for k, v in kv.items()}
    print("kvm_02 values (15k/10k/3.9k/10k):", R["pr_kvm_values"])
    R["awg"] = ranges.awg_load(d); print("awg", R["awg"])
    # 3. precision, ablation
    z = dict(tol=0.0, eps=0.0, offs=False, zspread=0.0, navg=10**12)
    def run(zc=1.0, **kw): return p99(net.run_s3(n=N, d=d, zcorr=zc, **kw))
    R["track"] = run(1.0); R["indep"] = run(0.0); R["track_typ"] = run(1.0, eps=EPS_TYP); R["indep_typ"] = run(0.0, eps=EPS_TYP)
    R["offset187"] = dict(track=run(1.0, off_lsb=1.5), indep=run(0.0, off_lsb=1.5))
    ab = {}
    for nm, over in (("channel match 0.1 %", dict(eps=EPS_MAX)), ("offsets 3 LSB", dict(offs=True)), ("resistors 1 %", dict(tol=0.01)), ("Zcm spread 25 %", dict(zspread=0.25)), ("noise 64 readings", dict(navg=64)), ("INL + model floor (control)", dict())):
        kw = dict(z); kw.update(over)
        zc = 0.0 if nm == "Zcm spread 25 %" else 1.0
        ab[nm] = p99(net.run_s3(n=N, d=d, zcorr=zc, **kw))
    R["ablation"] = ab
    R["window_ablation"] = {nm: p99(net.run_s3(n=N, d=d, zcorr=1.0, lev=np.linspace(-hi_lo[0], hi_lo[1], 25), ratio_level=rl)) for nm, hi_lo, rl in (("v1 window -1.35..+1.35", (1.35, 1.35), 0.0), ("v2 window -1.95..+2.28", (1.95, 2.28), 2.0))}
    R["kvm_values"] = dict(track=p99(net.run_s3(n=N, d=KVM, zcorr=1.0)), indep=p99(net.run_s3(n=N, d=KVM, zcorr=0.0)))
    for k in ("track", "indep", "track_typ", "indep_typ"): print(k, R[k])
    print("ablation", {k: "%.3f%%/%.2fmV" % (v["gain_pct"], v["off_mV"]) for k, v in ab.items()})
    print("window", R["window_ablation"]); print("kvm values on v1", R["kvm_values"])
    # 4. stack
    P0 = {"designs": {"S3": dict(max_indepZ=R["indep"], typ_indepZ=R["indep_typ"], max_corrZ=R["track"])}}
    out = {}
    for nm, (sg, so) in {"tracking": (R["track"]["gain_pct"], R["track"]["off_mV"]), "independent": (R["indep"]["gain_pct"], R["indep"]["off_mV"])}.items():
        g, o = stack.stack(sg, so, False); gs, gr = stack.total(g); os_, orr = stack.total(o)
        out[nm] = dict(gain_sum=gs, gain_rss=gr, off_sum=os_, off_rss=orr, ok_sum=bool(gs <= 0.5 and os_ <= 5.0), ok_rss=bool(gr <= 0.5 and orr <= 5.0))
        g, o = stack.stack(sg, so, True); out[nm]["gain_sum_ladder"], out[nm]["gain_rss_ladder"] = stack.total(g)
    R["stack"] = out; print(out)
    guards()
    json.dump(R, open(os.path.join(RES, "final_s3.json"), "w"), indent=1, default=float)

def guards():
    G = []
    def g(i, w, broken_fail, restored_pass): G.append(dict(id=i, what=w, broken="fails" if broken_fail else "PASSES (guard void)", restored="passes" if restored_pass else "FAILS", good=bool(broken_fail and restored_pass)))
    d = FINAL
    save = (net.INL_LSB, net.REF_TOL); net.INL_LSB = 0.0; net.REF_TOL = 0.0
    z = dict(n=300, eps=0.0, tol=0.0, zspread=0.0, offs=False, navg=10**12)
    ok = p99(net.run_s3(d=d, **z))["gain_pct"]
    bad_rd = p99(net.run_s3(d=d, hd=dict(d, Rd=2e3), **z))["gain_pct"]; bad_rs = p99(net.run_s3(d=d, hd=dict(d, Rs=7.8e3), **z))["gain_pct"]
    bad_z = p99(net.run_s3(d=d, host_Z=1.5e6, **z))["gain_pct"]
    g("G-s3-zero", "all errors off: the model floor (0.02 %, below 0.03 %); a host with Rd twice the truth, Rs twice, or Zcm 1.5 MOhm must each exceed 0.05 %", min(bad_rd, bad_rs, bad_z) > 0.05, ok <= 0.03)
    net.INL_LSB, net.REF_TOL = save
    r_ok = p99(net.run_s3(n=3000, d=d, zcorr=0.0)); r_off = p99(net.run_s3(n=3000, d=d, zcorr=0.0, off_lsb=60.0)); r_dead = p99(net.run_s3(n=3000, d=d, zcorr=0.0, offs=False))
    g("G-s3-offset", "offsets of 60 LSB must raise the offset figure above 5 x the 3-LSB figure (offsets do not cancel in S3); with the offsets switched off it must not (the check can fail)", not (r_dead["off_mV"] > 5 * r_ok["off_mV"]), r_off["off_mV"] > 5 * r_ok["off_mV"])
    r_eps = p99(net.run_s3(n=3000, d=d, zcorr=0.0, eps=0.02)); R["eps2pct"] = r_eps
    d2 = dict(d, Rs=1.0, Rm2=0.0, Rm1=0.0, Rt=22e3, Rb=15e3)       # the previous structure (T and B single-ended on separate channels, VREF scale) at the same k
    s2_ok = p99(net.run(n=3000, d=d2, zcorr=0.0, levels_ratio=(0.0,)))["gain_pct"]; s2_bad = p99(net.run(n=3000, d=d2, zcorr=0.0, levels_ratio=(0.0,), eps=0.02))["gain_pct"]
    R["s2_eps"] = (s2_ok, s2_bad)
    g("G-s3-eps", "channel match 2 % against 0.1 %: the gain must move by less than 0.1 % absolute (the match cancels). The same test on the previous structure (single-ended T and B, VREF scale) must fail it", not (s2_bad - s2_ok < 0.1), r_eps["gain_pct"] - r_ok["gain_pct"] < 0.1)
    # PR-3: kvm values must FAIL the 100 uA / 0.5 V rows, the final values pass
    k = R["pr_kvm_values"]["+5.0"]; f = max((x for kk, x in R["pr"].items() if kk.startswith("+5.0/unp")), key=lambda x: x["i_rail_uA"])
    g("G-pr3", "PR-3 on kvm_02's 15k/10k/3.9k values (105 uA, 0.491 V) must read over the 100 uA row (the check can fail); the final values pass (limits 100 uA and 0.5 V)", k["i_rail_uA"] > 100, f["i_rail_uA"] <= 100 and f["rail_V"] <= 0.5)
    # range: wire at TAP1 must break 0 V
    rg1 = s3.range_s3(s3design(22e3, 15e3, 3.9e3, 13e3, "TAP1"))["TAP1"][0]; rg3 = s3.range_s3(d)["TAP3"][0]
    g("G-s3-range", "wire at TAP1 (0.19 V): the tap must read below 0 V (fails); the designed TAP3 stays at or above 0", rg1 < 0, rg3 >= 0)
    rgk = s3.range_s3(s3design(22e3, 15e3, 3.9e3, 13e3, "TAP3"), n=2000)
    dt = ranges.detect(d); bad = ranges.detect(d, limit_mult=1000.0)
    g("G-s3-detect", "distinguishability limit raised to 1000 x resolution must fail on at least one wrong state; at 20 x all pass", not all(r["ok"] for r in bad["rows"]), all(r["ok"] for r in dt["rows"]))
    json.dump(G, open(os.path.join(RES, "guards_s3.json"), "w"), indent=1)
    for x in G: print("GUARD", x["id"], x["broken"], x["restored"], "OK" if x["good"] else "BAD")
    R["guards"] = G

if __name__ == "__main__":
    main()
