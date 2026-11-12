#!/usr/bin/env python3
"""The whole SC-7 stack for version 1 (gain terms in %, offset terms in mV), with the sense term from precision.py.  Sources in the strings; nothing measured."""
import json, os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); RES = os.path.join(HERE, "results")
P = json.load(open(os.path.join(RES, "precision.json")))
LIM_G, LIM_O = 0.5, 5.0            # SC-7: +-0.5 % of reading +-5 mV, mean of >= 1024 samples (afe.md)
def stack(sense_g, sense_o, ladder=False):
    g = [("REF3030E E grade: 0.1 % initial + 15 ppm/K x 10 K + 100 ppm hysteresis (check) + 40 ppm long term", 0.13, "afe-v2 powercal design.md section 6; PA-2"),
         ("EN-1 uncalibrated gain drift, +-5 V range, 10 K since calibration (0.336 % over 20 K, halved: linear scaling (check))", 0.168, "whatif/v1-basic/values.md section 3, D19"),
         ("Due ADC INL fit share, 1024 points on +-5 V", 0.042, "afe.md PA-3 (design analysis)"),
         ("sense: ADS1115 channel match, offsets, Zcm, resistors, noise (this design)", sense_g, "precision.py, 99.9th percentile")]
    if ladder: g.append(("ladder drift of a measured tap, 10 K opposed (v2's 330 ohm figure; v1's 8 x 270 ohm at 1 %, same mechanism (check))", 0.133, "afe-v2 powercal design.md section 4"))
    o = [("EN-1 offset drift (15 to 35 C)", 3.0, "afe.md EN-1 requirement figure, not simulated"),
         ("sense: ADS1115 offsets, resistors, noise (this design)", sense_o, "precision.py, 99.9th percentile")]
    return g, o
def total(rows):
    v = np.array([r[1] for r in rows]); return float(v.sum()), float(np.sqrt((v ** 2).sum()))
def main():
    out = {}; D = P["designs"]
    cases = {"k1/2 max match (0.1 %)": (D["k1/2"]["max_indepZ"]["gain_pct"], D["k1/2"]["max_indepZ"]["off_mV"]),
             "k1/2 typical match (0.05 %)": (D["k1/2"]["typ_indepZ"]["gain_pct"], D["k1/2"]["typ_indepZ"]["off_mV"]),
             "k1/3 max match": (D["k1/3"]["max_indepZ"]["gain_pct"], D["k1/3"]["max_indepZ"]["off_mV"]),
             "superseded k1/2 Rd-model design": (1.116, 20.4), "allotment 0.05 % / 3 mV": (0.05, 3.0)}
    for nm, (sg, so) in cases.items():
        for lad in (False, True):
            g, o = stack(sg, so, lad)
            sg_sum, sg_rss = total(g); so_sum, so_rss = total(o)
            out[f"{nm}{' + ladder' if lad else ''}"] = dict(gain=g, offset=o, gain_sum=sg_sum, gain_rss=sg_rss, off_sum=so_sum, off_rss=so_rss,
                                                          pass_sum=bool(sg_sum <= LIM_G and so_sum <= LIM_O), pass_rss=bool(sg_rss <= LIM_G and so_rss <= LIM_O))
    rest = [r[1] for r in stack(0, 0)[0][:3]]; rest_l = rest + [0.133]
    out["room"] = dict(sum_no_ladder=LIM_G - sum(rest), sum_with_ladder=LIM_G - sum(rest_l),
                       rss_no_ladder=float(np.sqrt(LIM_G ** 2 - np.sum(np.square(rest)))), rss_with_ladder=float(np.sqrt(LIM_G ** 2 - np.sum(np.square(rest_l)))), offset_room=LIM_O - 3.0)
    for k, v in out.items():
        if k == "room": print(v); continue
        print(f"{k:46s} gain sum {v['gain_sum']:.3f} % RSS {v['gain_rss']:.3f} % | offset sum {v['off_sum']:.2f} mV RSS {v['off_rss']:.2f} | sum {'PASS' if v['pass_sum'] else 'FAIL'} RSS {'PASS' if v['pass_rss'] else 'FAIL'}")
    g, o = stack(1.12, 20.4); bad = total(g)[0] <= LIM_G and total(o)[0] <= LIM_O
    g2, o2 = stack(0.05, 2.0); ok = total(g2)[0] <= LIM_G and total(o2)[0] <= LIM_O
    print("GUARD G-stack: sense 1.12 %% / 20.4 mV passes? %s (must be False); sense 0.05 %% / 2 mV passes? %s (must be True)" % (bad, ok))
    out["guard"] = dict(broken_passes=bool(bad), restored_passes=bool(ok)); json.dump(out, open(os.path.join(RES, "stack.json"), "w"), indent=1)
if __name__ == "__main__":
    main()
