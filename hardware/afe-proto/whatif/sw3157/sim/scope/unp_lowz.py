"""PR-1/PR-2 at the range switch's pins, unpowered, on the ~22 kohm round-1 divider (variant lowz, design N), for comparison
with the default hz variant: the switch pins see the op-amp output and inverting node."""
import sys, os, json
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import netlib as NL
import sw as S          # sw selects variant hz on import; switch to lowz after it
import run as R
import lowz as L
NL.use_variant("lowz")
R.set_res(os.path.join(HERE, "results"))
out = {}
NL.PFX = "unplowz_"
for bleed in (4700.0, 249.0):
    for k, v in {"+12 V both": (12.0, 12.0), "-12 V both": (-12.0, -12.0), "+12 / -12 V": (12.0, -12.0)}.items():
        p = L.P("N", inj="N", swv=dict(shape="NX", rpk=7.698, flat=1.941, con=18e-12, coff=6e-12))
        out[f"{bleed:g}|{k}"] = S.unpowered_sw(p, v, bleed=bleed)
json.dump(out, open(os.path.join(HERE, "results", "unp_lowz.json"), "w"), indent=1)
for k, v in out.items(): print(k, {a: round(b, 3) for a, b in v.items()})
