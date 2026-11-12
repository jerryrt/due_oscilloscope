import os, sys, itertools, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vloop as V
from concurrent.futures import ProcessPoolExecutor
def one(a):
    i, (riso, rfb, cfb, cn) = a
    d = dict(riso=riso, rfb=rfb, cfb=cfb, cnode=cn, esr=2.5e-3 * 20e-6 / cn)
    r = V.evaluate("tlv", d, f"tl{i}")
    return dict(d, zmax=r["zmax"], fz=r["fz"], pm=r["pm_min"], nx=len(r["crossings"]))
if __name__ == "__main__":
    r = V.evaluate("tlv", dict(riso=0.2, rfb=4.7e3, cfb=3e-9, cnode=20e-6, esr=2.5e-3), "tlv0")
    print("TLV9062, the stiffened OPA365 loop:", {k: v for k, v in r.items() if k not in ('f', 'z')})
    grid = list(itertools.product((0.1, 0.2, 0.333, 0.5, 1.0), (4.7e3, 100e3), (3e-9, 100e-9, 1e-6), (20e-6, 40e-6, 80e-6)))
    with ProcessPoolExecutor(4) as ex:
        res = list(ex.map(one, enumerate(grid)))
    json.dump(res, open("sweep_tlv.json", "w"), indent=1)
    ok = sorted([x for x in res if (x["pm"] or 0) >= 45 and x["nx"] == 1], key=lambda x: x["zmax"])
    for x in ok[:12]:
        print({k: (float(f"{v:.4g}") if isinstance(v, float) else v) for k, v in x.items()})
