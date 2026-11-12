import sys; sys.path.insert(0,'.')
from run import *
from whatif import sm3, g_bw2
R={}
for c2 in (33e-12, 36e-12):
    t=f"sm3_C2_{c2*1e12:.0f}p"; s=sm3("OPA365", dict(C2=c2), t)
    R[t]={rg:dict(nom=s[rg]["nominal"]["bw10k"], w2b=s[rg]["worst_2b"]["bw10k"], wext=s[rg]["worst_ext"]["bw10k"], pk=max(r["pk"] for r in s[rg]["rows"]), pm=s[rg]["pm_min"]) for rg in s}
    R[t]["edge"]={f"{rng}_{tr*1e9:.0f}ns": step_response(pp(rng=rng,C2=c2),"edge2",vs,tr) for rng,vs in (("5",2.0),("1.25",0.5)) for tr in (42e-9,5e-9)}
    R[t]["guard"]={rg: dict(good=g_bw2(pp(rng=rg,C2=c2)), c1m10=g_bw2(dict(pp(rng=rg,C2=c2),C1=10.8e-12)), c1m20=g_bw2(dict(pp(rng=rg,C2=c2),C1=9.6e-12)), opa354=g_bw2(pp(rng=rg,C2=c2,op="OPA354"))) for rg in ("1.25","5")}
    print(t, json.dumps(R[t], default=float), flush=True)
save("recomp", R)
