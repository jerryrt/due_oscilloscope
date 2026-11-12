import itertools, json, sys
from concurrent.futures import ProcessPoolExecutor
sys.path.insert(0, __import__('os').path.dirname(__import__('os').path.abspath(__file__)))
import vloop as V
def one(args):
    i, (riso, rfb, cfb, cn) = args
    d = dict(riso=riso, rfb=rfb, cfb=cfb, cnode=cn, esr=2.5e-3 * 20e-6 / cn)
    out = dict(d)
    for ro in (50, 300, 1000):
        r = V.evaluate("mcp", d, f"s{i}_{ro}", ro=ro)
        out[f"zmax_{ro}"] = r["zmax"]; out[f"fz_{ro}"] = r["fz"]; out[f"pm_{ro}"] = r["pm_min"]; out[f"nx_{ro}"] = len(r["crossings"])
    return out
if __name__ == "__main__":
    grid = list(itertools.product((0.2, 0.333, 0.5, 1.0, 2.0, 3.0), (4.7e3, 100e3), (3e-9, 100e-9, 1e-6), (20e-6, 40e-6, 80e-6)))
    with ProcessPoolExecutor(4) as ex:
        res = list(ex.map(one, enumerate(grid)))
    json.dump(res, open("sweep.json", "w"), indent=1)
    ok = [r for r in res if all((r[f"pm_{ro}"] or 0) >= 45 for ro in (50, 300, 1000))]
    ok.sort(key=lambda r: max(r[f"zmax_{ro}"] for ro in (50, 300, 1000)))
    for r in ok[:25]:
        print({k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()})
