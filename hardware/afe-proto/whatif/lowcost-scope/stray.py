"""Board stray from channel A's output to channel B's N node (the + input side): the reading change against SC-9's
2 LSB, through the S/H's derived and stress tracking RC.  Used for the dual package's layout note."""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, lowcost as LC
LC.NL.PFX = "stray_"
c0 = LC.core2
def core_s(p, pre="", loopbreak=False):
    s = c0(p, pre, loopbreak)
    if p.get("_cs") and pre == "b":
        s += f"\nCstray aout bn {p['_cs']:.6g}\nCstray2 bout an {p['_cs']:.6g}"
    return s
for m in (LC.NL, LC.R, LC.L):
    m.core = core_s
LC.core2 = core_s
out = {}
for rng, vfs in (("5", 6.0), ("1.25", 1.25)):
    for cs in (0.01e-12, 0.03e-12, 0.1e-12, 0.3e-12):
        p = LC.P("D", rng=rng, _cs=cs)
        f, r = LC.ac_xt(p, p, "a", "st")
        x = r["victim_pin"] * vfs / LC.LSB32
        row = dict(pin=float(x.max()), f=float(f[np.argmax(x)]), derived=float((x * LC.adc_track(f, LC.R.ADC_DERIVED)).max()),
                   stress=float((x * LC.adc_track(f, LC.R.ADC_STRESS)).max()))
        out[f"{rng}|{cs*1e12:.2f}pF"] = row
        print(rng, cs * 1e12, row, flush=True)
json.dump(out, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "stray.json"), "w"), indent=1)
