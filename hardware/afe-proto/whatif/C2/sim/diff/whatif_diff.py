"""WHATIF C2 DF-3: R2 330k fixed, no trimmer, OPA365, BOM C1 12 pF / C2 39 pF, calibration residual."""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from concurrent.futures import ProcessPoolExecutor
import run as R, core2d as c, dlib

def corner_cal(sc, e, key="wc"):
    hot = c.at_T(c.corner_set(sc)[key]); d0 = c.at_T(c.corner_draw(sc, dT=0.0, name="g_ref", **c.ref_kw(key)))
    v = {}
    for rg in ("5", "1.25"):
        r1 = c.eval_range(f"gw_{key}_{rg}", hot, rg, with_ac=False); r0 = c.eval_range(f"gw0_{key}_{rg}", d0, rg, with_ac=False)
        v[rg] = min(min(c.cal_cmrr(r0, r1, d0, rg, (s * e, -s * e))[:2]) for s in (1, -1))
    return v

def main():
    R.POOL = ProcessPoolExecutor(max_workers=int(os.environ.get("W", "1")))
    csys = 12e-12 / dlib.c1_ideal(330e3) - 1
    print("C1 ideal", dlib.c1_ideal(330e3) * 1e12, "csys", csys, dlib.OPA354_LIB, dlib.BASE["op"], dlib.BASE["R2"], c.VOS_MAX, c.CMRR_OP_DB, flush=True)
    sc = dict(c.SPEC, name="c2_opa365", csys=csys)
    S, mcs, cor, nom = R.scenario(sc, "c2")
    keys = [k for k in mcs[0]["5"]["cal"] if k.startswith("res_")] + ["exact"]
    out = {"summary": {}, "res": {}}
    for rg in ("5", "1.25"):
        s = S[rg]
        out["summary"][rg] = dict(before_dc_corner=s["dc_corner_min"], before_dc_mc_min=s["dc_mc_min"], before_10k_corner=s["f10k_wc"],
                                  before_10k_mc_min=s["f10k_mc_min"], after_corner=s["cal_corner_min"], after_mc_min=s["cal_mc_min"],
                                  after_mc_p1=s["cal_mc_p1"], after_mc_med=s["cal_mc_med"], mc_below_corner_dc=s["mc_exceeds_corner_dc"],
                                  margin_min=s["margin_min"], n=s["n"])
        out["res"][rg] = {}
        for k in keys:
            g = (lambda cal: min(cal["dc"], cal["dc_alt"])) if k == "exact" else (lambda cal, k=k: cal[k])
            mcv = [g(m[rg]["cal"]) for m in mcs]; cv = {kk: g(v[rg]["cal"]) for kk, v in cor.items()}
            out["res"][rg][k] = dict(corner_min=min(cv.values()), corners=cv, mc_min=min(mcv), mc_p1=float(np.percentile(mcv, 1)),
                                     mc_med=float(np.median(mcv)), mc_below_corner=sum(1 for x in mcv if x < min(cv.values()) - 1e-9))
    out["guard"] = dict(good=corner_cal(sc, 62e-6), broken=corner_cal(sc, 2000e-6), restored=corner_cal(sc, 62e-6))
    json.dump(out, open(os.path.join(R.RES, "whatif_c2.json"), "w"), indent=1, default=float)
    print(json.dumps(out["summary"], indent=1, default=float))
    for rg in out["res"]:
        for k, v in out["res"][rg].items():
            print(rg, k, {kk: round(vv, 2) for kk, vv in v.items() if kk != "corners"})
    print(out["guard"])
    R.log("done")

if __name__ == "__main__":
    main()
