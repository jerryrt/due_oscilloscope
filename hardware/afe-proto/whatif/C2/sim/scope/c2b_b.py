import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from c2b_common import *
from whatif import sm3
R = {}
for k, (csw, c2, d) in CASES.items():
    p = pp(Csw=csw, C2=c2)
    s = sm3("OPA365", dict(Csw=csw, C2=c2), "sm3_" + k)
    R[k] = dict(desc=d, comp=comp_row(p),
                sm3={rg: dict(nom=s[rg]["nominal"]["bw10k"], w2b=s[rg]["worst_2b"]["bw10k"], wext=s[rg]["worst_ext"]["bw10k"],
                              wext_DC=s[rg]["worst_ext_1k"]["bw1k"], pk=max(r["pk"] for r in s[rg]["rows"]), pm=s[rg]["pm_min"]) for rg in s},
                edge={f"{rng}_{tr*1e9:.0f}ns": step_response(dict(p, rng=rng), "e2b", vs, tr, tstop=2.5e-6) for rng, vs in (("5", 2.0), ("1.25", 0.5)) for tr in (42e-9, 5e-9)})
    print(k, json.dumps(R[k], default=float), flush=True)
save("c2b_cases", R)
