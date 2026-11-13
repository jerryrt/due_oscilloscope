#!/usr/bin/env python3
"""SC-7's tee-fit extrapolation row on version 2's scope at +-5 V (range5v.md section 5, item 1).

Reuses ../powercal/sc7.py's Monte Carlo unchanged (its INL models, Due ADC gain/offset spread, channel offset, noise, 1024-point staircase,
sweep bottom -1.923 V) and changes only the scope's map (a = 0.2328, centre 1.6295 V, AREF 3.27 as there) and the points the fit is
extrapolated to: +-5 V (the rated ends, where SC-7's 0.5 % + 5 mV is judged) and +-6 V (usable, information).  The AWG's sweep is
-1.923 V to its window top: 1.6 V (the commanded top), 1.785 V (the lowest window top over tolerances, the design's worst case) or
2.133 V (hard-corner DC).  The fit is a straight line of Due code against AWG volts; ladder anchors are NOT used (D-V2-13).

    python3 -I range5v_sc7.py [--json FILE] [--n 800]        numpy only (no ngspice)
"""
import json, math, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
PC = os.path.normpath(os.path.join(HERE, "..", "powercal"))
sys.path.insert(0, PC)
import sc7 as S                                     # the powercal study's module: its run() reads these module globals
S.A_SC, S.C0_SC = 0.2328, 1.6295
VEND = (-6.0, -5.0, 5.0, 6.0)
MODELS = (("cubic", 0.5), ("cubic", 1.2), ("parab", 1.2), ("knots", 1.2))
SHARE = 0.001                                       # the fit's share of SC-7: 0.1 % of the reading (afe.md PA-3)


def study(n):
    out = {}
    for top in (1.6, 1.785, 2.133):
        for model, A in MODELS:
            r = S.run(model=model, A=A, top=top, n=n, anchors=False, vend_list=VEND)
            out[f"{top}/{model}/{A}"] = {str(v): r[v]["A_q999_mV"] for v in VEND}
    return out


def main(argv):
    n = int(argv[argv.index("--n") + 1]) if "--n" in argv else 800
    res = study(n)
    print(f"tee fit alone, 99.9th percentile error in mV at the input, {n} draws, 1024 points; one Due LSB = {S.AREF/4096/S.A_SC*1e3:.2f} mV at the input")
    print(f"{'top V / INL model / LSB':26s} " + " ".join(f"{v:+.0f} V".rjust(8) for v in VEND) + "   share 0.1 % at 5 V = 5.0 mV, at 6 V = 6.0 mV")
    for k, r in res.items():
        print(f"{k:26s} " + " ".join(f"{r[str(v)]:8.2f}" for v in VEND))
    worst = max(res["1.785/knots/1.2"][str(v)] for v in (-5.0, 5.0))
    worst_all = max(max(res[k][str(v)] for v in (-5.0, 5.0)) for k in res)
    print(f"design worst case (1.785 V top, random knots 1.2 LSB, either end at 5 V): {worst:.2f} mV = {worst/5000*100:.3f} % of 5 V; worst of every row {worst_all:.2f} mV")
    # a guard: an INL of 12 LSB must break the 5 mV share
    big = S.run(model="cubic", A=12.0, top=1.785, n=200, anchors=False, vend_list=(5.0,))[5.0]["A_q999_mV"]
    print(f"guard: INL 12 LSB reads {big:.1f} mV at +5 V: {'breaks the share, as it must' if big > 5.0 else 'DOES NOT BREAK THE SHARE: guard is blind'}")
    if "--json" in argv:
        with open(argv[argv.index("--json") + 1], "w") as f:
            json.dump(dict(n=n, results=res, worst_design_mV=worst, worst_all_mV=worst_all, guard_12lsb_mV_at_5V=big), f, indent=1)
    return 0 if big > 5.0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
