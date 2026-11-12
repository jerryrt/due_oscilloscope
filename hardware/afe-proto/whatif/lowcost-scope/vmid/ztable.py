import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, vloop as V
rows = {}
F = (1, 10, 30, 100, 300, 1e3, 3e3, 1e4, 3e4, 1e5, 1e6)
cases = {
 "OPA365 stand-in, design loop (0.2R, 4.7k, 3 nF, 2x10uF)": ("lin365", dict(riso=0.2, rfb=4.7e3, cfb=3e-9, cnode=20e-6, esr=2.5e-3), {}),
 "MCP6002 chosen (3R, 4.7k, 1uF, 8x10uF), Ro 300 typical-guess": ("mcp", dict(riso=3.0, rfb=4.7e3, cfb=1e-6, cnode=80e-6, esr=0.005/8), dict(ro=300)),
 "MCP6002 chosen, worst (Ro 1000, GBW 0.7 MHz, fp2 3 MHz, C x0.82, Cfb x1.235)": ("mcp", dict(riso=3.0, rfb=4.7e3, cfb=1.235e-6, cnode=80e-6*0.8208, esr=0.005/8), dict(ro=1000, gbw=0.7e6, fp2=3e6)),
 "MCP6002 chosen, stress (Ro 2000, same)": ("mcp", dict(riso=3.0, rfb=4.7e3, cfb=1.235e-6, cnode=80e-6*0.8208, esr=0.005/8), dict(ro=2000, gbw=0.7e6, fp2=3e6)),
 "MCP6002 drop-in on the design loop, Ro 300": ("mcp", dict(riso=0.2, rfb=4.7e3, cfb=3e-9, cnode=20e-6, esr=2.5e-3), dict(ro=300)),
 "MCP6002-B lean (4R, 4.7k, 1uF, 4x10uF), Ro 1000 worst": ("mcp", dict(riso=4.0, rfb=4.7e3, cfb=1.235e-6, cnode=40e-6*0.8208, esr=0.005/4), dict(ro=1000, gbw=0.7e6, fp2=3e6)),
 "TLV9062 chosen (0.25R, 4.7k, 1uF, 6x10uF), TI model": ("tlv", dict(riso=0.25, rfb=4.7e3, cfb=1e-6, cnode=60e-6, esr=0.005/6), {}),
 "TLV9062 chosen, C x0.82, Cfb x0.765": ("tlv", dict(riso=0.25, rfb=4.7e3, cfb=0.765e-6, cnode=60e-6*0.8208, esr=0.005/6), {}),
}
for i, (k, (kind, d, kw)) in enumerate(cases.items()):
    r = V.evaluate(kind, d, f"zt{i}", **kw)
    az = np.abs(r["z"]); f = r["f"]
    rows[k] = dict(z={f"{x:g}": float(np.interp(np.log10(x), np.log10(f), az)) for x in F}, zmax=r["zmax"], fz=r["fz"], pm=r["pm_min"], fc=r["crossings"][0][0] if r["crossings"] else None)
    print(k, "| zmax %.3f at %.0f Hz, PM %.1f at %.0f Hz" % (r["zmax"], r["fz"], r["pm_min"], rows[k]["fc"]), "|", " ".join(f"{x}:{v:.3g}" for x, v in rows[k]["z"].items()))
json.dump(rows, open("ztable.json", "w"), indent=1)
