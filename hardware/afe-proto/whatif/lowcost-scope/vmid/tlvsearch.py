import os, sys, itertools, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import robust as RB
from concurrent.futures import ProcessPoolExecutor
if __name__ == "__main__":
    C = {}
    for riso, n10, cfb in itertools.product((0.2, 0.25, 1 / 3), (4, 6, 8), (100e-9, 1e-6)):
        C[f"tlv r{riso:.3f}_n{n10}_c{cfb}"] = ("tlv", dict(riso=riso, rfb=4.7e3, cfb=cfb, n10=n10))
    jobs = [(nm, C[nm], f"t{j}_{i}", cc) for j, nm in enumerate(C) for i, cc in enumerate(RB.corners("tlv"))]
    with ProcessPoolExecutor(4) as ex:
        res = list(ex.map(RB.one, jobs))
    S = []
    for nm in C:
        rr = [x for x in res if x["name"] == nm]
        S.append(dict(name=nm, z=max(x["zmax"] for x in rr), z1k1M=max(x["zmax_1k_1M"] for x in rr), pm=min(x["pm"] or -1 for x in rr), nx=any(x["nx"] != 1 for x in rr)))
    for s in sorted(S, key=lambda s: s["z"]):
        print(s)
    json.dump(S, open("tlvsearch.json", "w"), indent=1)
