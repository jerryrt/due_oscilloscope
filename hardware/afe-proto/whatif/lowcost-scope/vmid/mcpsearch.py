import os, sys, itertools, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import robust as RB
from concurrent.futures import ProcessPoolExecutor
if __name__ == "__main__":
    RB.CANDS.clear()
    for riso, n10, cfb in itertools.product((2.0, 3.0, 4.0), (4, 6, 8), (100e-9, 1e-6)):
        RB.CANDS[f"r{riso}_n{n10}_c{cfb}"] = ("mcp", dict(riso=riso, rfb=4.7e3, cfb=cfb, n10=n10))
    jobs = [(nm, RB.CANDS[nm], f"m{j}_{i}", cc) for j, nm in enumerate(RB.CANDS) for i, cc in enumerate(RB.corners("mcp"))]
    with ProcessPoolExecutor(4) as ex:
        res = list(ex.map(RB.one, jobs))
    S = []
    for nm in RB.CANDS:
        rr = [x for x in res if x["name"] == nm]
        r1k = [x for x in rr if x["corner"]["ro"] <= 1000]
        S.append(dict(name=nm, z_all=max(x["zmax"] for x in rr), pm_all=min(x["pm"] or -1 for x in rr),
                      z_1k=max(x["zmax"] for x in r1k), pm_1k=min(x["pm"] or -1 for x in r1k), nx=any(x["nx"] != 1 for x in rr)))
    for s in sorted(S, key=lambda s: s["z_all"]):
        print(s)
    json.dump(S, open("mcpsearch.json", "w"), indent=1)
