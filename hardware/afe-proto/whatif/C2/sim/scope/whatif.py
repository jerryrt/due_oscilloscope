"""WHATIF C2: R2 330k fixed (no trimmer), C1 12 pF / C2 39 pF (BOM), OPA365 in both channels."""
import sys; sys.path.insert(0, '.')
from run import *

def bw_rel(f, h, fref):
    a = np.abs(h); g = np.interp(fref, f, a); db = 20*np.log10(a/g)
    i = np.where((db < -3) & (f > fref))[0][0]
    return float(10**(np.log10(f[i-1]) + (np.log10(f[i])-np.log10(f[i-1]))*(-3-db[i-1])/(db[i]-db[i-1])))

def sm3(op="OPA365", base_over=None, tag="sm3"):
    """2b corners (Cpar -2/0/+3 pF, Ron 3.7/8.8, C1 +/-5 %) plus C2 +/-5 % (extended).  BW relative to 10 kHz as 2b; also to 1 kHz and 100 kHz."""
    R = {}; base_over = base_over or {}
    for rng in ("5", "1.25"):
        rows = []
        for cx in (-2e-12, 0.0, 3e-12):
            for ron in (3.7, RON_MAX):
                for c1s in (0.95, 1.0, 1.05):
                    for c2s in (0.95, 1.0, 1.05):
                        p = pp(op=op, rng=rng, Cpar_extra=cx, Ron_sw=ron, **base_over)
                        p["C1"] = c1_of(p) * c1s; p["C2"] = p["C2"] * c2s
                        f, h, T = ac_response(p, "sm3", fmin=1e3, fmax=2e9, ppd=40)
                        m = freq_metrics(f[f >= 1e4], h[f >= 1e4]); pm = phase_margin(f, T)
                        rows.append(dict(cx=cx, ron=ron, c1s=c1s, c2s=c2s, bw10k=m["bw"], bw100k=bw_rel(f, h, 1e5),
                                         bw1k=bw_rel(f, h, 1e3), pk=m["peak_db"], pm=pm["pm"]))
        std = [r for r in rows if r["c2s"] == 1.0 and r["c1s"] != 1.0]
        R[rng] = dict(rows=rows, nominal=[r for r in rows if r["cx"] == 0 and r["ron"] == 3.7 and r["c1s"] == 1 and r["c2s"] == 1][0],
                      worst_2b=min(std, key=lambda r: r["bw10k"]), worst_ext=min(rows, key=lambda r: r["bw10k"]),
                      worst_ext_100k=min(rows, key=lambda r: r["bw100k"]), worst_ext_1k=min(rows, key=lambda r: r["bw1k"]),
                      pm_min=min(r["pm"] for r in rows))
    return save(tag, R)

def g_bw2(p):
    lim = 7e6 if p["rng"] == "1.25" else 8e6
    worst = 1e99
    for cx in (-2e-12, 3e-12):
        for ron in (3.7, RON_MAX):
            for c1s in (0.95, 1.05):
                q = dict(p, Cpar_extra=cx, Ron_sw=ron); q["C1"] = c1_of(p) * c1s
                worst = min(worst, ac_summary(q, "g_bw")["bw"])
    return worst >= lim, f"worst-corner BW {worst/1e6:.2f} MHz (>={lim/1e6:.0f})"

def guards_c2():
    G = []
    def run(name, guard, good, broken, what):
        ok1, d1 = guard(good); ok2, d2 = guard(broken); ok3, d3 = guard(good)
        G.append(dict(guard=name, mutation=what, good=dict(ok=bool(ok1), detail=d1), broken=dict(ok=bool(ok2), detail=d2),
                      restored=dict(ok=bool(ok3), detail=d3), effective=bool(ok1 and not ok2 and ok3)))
    for rng in ("1.25", "5"):
        run(f"SM-3 {rng} OPA354 swap (control)", g_bw2, pp(rng=rng), pp(rng=rng, op="OPA354"), "OPA365 -> OPA354")
        for c1 in (0.90, 0.80):
            run(f"SM-3 {rng} C1 {int(round((c1-1)*100))} %", g_bw2, pp(rng=rng), dict(pp(rng=rng), C1=12e-12 * c1), f"C1 12 -> {12*c1:.1f} pF")
        run(f"SM-3 {rng} Cpar +10 pF", g_bw2, pp(rng=rng), pp(rng=rng, Cpar=13e-12), "inverting-node C 3 -> 13 pF")
    run("DC transfer", g_dc, pp(rng="5"), pp(rng="5", R2=450e3), "R2 330k -> 450k")
    run("Flatness", g_flat, pp(rng="5"), dict(pp(rng="5"), C1=1e-15), "C1 removed")
    run("PM", g_pm, pp(rng="5"), pp(rng="5", **SPEC), "as first specified")
    run("Edge current", g_edge, pp(rng="5"), pp(rng="5", Rnp=0.0), "Rnp removed")
    run("Noise", g_noise, pp(rng="1.25"), pp(rng="1.25", RG=60.4), "RG 249 -> 60.4")
    run("Settling", g_settle, pp(rng="5"), pp(rng="5", Riso=20e3), "Riso 22 -> 20k")
    return save("guards_c2", G)

if __name__ == "__main__":
    want = sys.argv[1:]; t0 = time.time()
    if "sm3" in want:
        sm3("OPA365"); sm3("OPA365", dict(C1=None, C2=38e-12), "sm3_idealC1"); sm3("OPA354", None, "sm3_opa354"); print("sm3", time.time()-t0, flush=True)
    if "dc" in want:
        dc_section("OPA365"); dc_section("OPA354", quick=True); print("dc", time.time()-t0, flush=True)
    if "ac" in want:
        ac_section(); zin_section(); edge_section(); comp_section(); print("ac", time.time()-t0, flush=True)
    if "noise" in want:
        noise_section(); print("noise", time.time()-t0, flush=True)
    if "kick" in want:
        kick_section(); print("kick", time.time()-t0, flush=True)
    if "prot" in want:
        prot_section(); print("prot", time.time()-t0, flush=True)
    if "guards" in want:
        guards_c2(); print("guards", time.time()-t0, flush=True)
