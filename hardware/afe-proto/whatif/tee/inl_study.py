#!/usr/bin/env python3
"""Tables of the Due-INL terms of the tee calibration -> results/inl.json.  python3 -I inl_study.py (about 3 min).
Every check here is also broken on purpose (the 'guards' block) and the run aborts if a guard does not fire."""
import os, sys, json, math
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import inl

OUT = {}
NP = (64, 128, 256, 512, 1024)

# 0. the model must reproduce powercal C3-e (+-5 V, 64 points, DAC0 at N over 0.58-2.77 V): 0.036 %
OUT["c3e_reproduced"] = inl.c3e_reference()

# 1. absolute per-channel gain error (SC-7 share 0.05 %), 99.9 %
absr = {}
for rg in ("5", "1.25"):
    for vt in (1.0, 1.15):
        for model, A in (("pt", 1.2), ("pt", 0.5)):
            for n in NP:
                absr[f"{rg}|{vt}|{model}{A}|{n}"] = inl.fit(n, vt, rg, model, A=A, N=10000, seed=n)["abs"]
# the PA-3 injection it replaces, same model: N over DAC0's window = an input span of +-4.71 V (+-5 V) / +-1.29 V
absr["inj|5|pt1.2|64"] = inl.fit(64, 4.71, "5", "pt", N=10000)["abs"]
absr["inj|1.25|pt1.2|64"] = inl.fit(64, 1.29, "1.25", "pt", N=10000)["abs"]
OUT["abs"] = absr

# 1b. smooth bows: the reading error at the range end after the fit (extrapolated slope) and with an exact slope
ends = {}
for rg in ("5", "1.25"):
    for model in ("cubic", "parab"):
        for A in (0.5, 1.2):
            ends[f"{rg}|{model}{A}"] = inl.end_error(1.15, rg, model, A)
OUT["end"] = ends

# 2. ratio residual (DF-3): one ADC, both channels at slightly different codes
rat = {}
for rg in ("5", "1.25"):
    for tol in (1e-3, 1e-2):
        for n in (64, 256):
            rat[f"{rg}|{tol}|pt1.2|{n}"] = inl.fit(n, 1.15, rg, "pt", A=1.2, tol_div=tol, N=10000, seed=7)["ratio"]
            for L in (1, 4, 16, 64, 256):
                rat[f"{rg}|{tol}|codeL{L}|{n}"] = inl.fit(n, 1.15, rg, "code", A=1.2, L=L, tol_div=tol, N=3000, seed=8)["ratio"]
            for model in ("cubic", "parab"):
                rat[f"{rg}|{tol}|{model}1.2|{n}"] = inl.fit(n, 1.15, rg, model, A=1.2, tol_div=tol, N=3000, seed=9)["ratio"]
    rat[f"inj|{rg}|pt1.2|64"] = inl.fit(64, 4.71 if rg == "5" else 1.29, rg, "pt", A=1.2, N=10000, seed=7)["ratio"]
OUT["ratio"] = rat

# 3. guards: each check broken on purpose
G = []
def guard(name, mutation, good, broken, ok):
    G.append(dict(check=name, mutation=mutation, good=good, broken=broken, fired=bool(ok)))
c3 = OUT["c3e_reproduced"]
c3m = inl.c3e_reference(A=0.6)
guard("model reproduces C3-e 0.036 % (within 10 %)", "INL 1.2 -> 0.6 LSB in the reference fit",
      c3, c3m, abs(c3 - 0.036) / 0.036 < 0.10 and abs(c3m - 0.036) / 0.036 > 0.10)
# the absolute check (<= 0.05 %) must pass at DAC0's 93 % coverage and fail at the tee's 23 %
a_inj, a_tee = absr["inj|5|pt1.2|64"], absr["5|1.15|pt1.2|64"]
guard("+-5 V gain <= 0.05 % (64 points)", "coverage 23 % (tee) instead of 93 % (DAC0 injection)", a_inj, a_tee, a_inj <= 0.05 < a_tee)
# the ratio estimator: identical codes must cancel the shared INL exactly; independent ADCs must not cancel at all
s = inl.fit(64, 1.15, "5", "code", A=1.2, L=1, N=2000, same_codes=True, seed=11)
i_ = inl.fit(64, 1.15, "5", "code", A=1.2, L=1, N=2000, indep_adc=True, seed=11)
guard("ratio sees the shared INL cancel", "both channels forced to the same codes (gain and offset)", s["ratio"], None, s["ratio"] < 0.02 * s["abs"])
guard("ratio sees no cancellation without a shared ADC", "each channel given its own INL function",
      i_["ratio_sd"], math.sqrt(2) * i_["abs_sd"], abs(i_["ratio_sd"] / (math.sqrt(2) * i_["abs_sd"]) - 1) < 0.1)
OUT["guards"] = G
json.dump(OUT, open(os.path.join(HERE, "results", "inl.json"), "w"), indent=1)
for g in G:
    print(g)
bad = [g for g in G if not g["fired"]]
if bad:
    raise SystemExit(f"guard did not fire: {bad}")
print("C3-e", c3)
for k, v in absr.items():
    print("abs", k, round(v, 4))
for k, v in ends.items():
    print("end", k, [round(x, 4) for x in v])
for k, v in rat.items():
    print("ratio", k, round(v, 4))
