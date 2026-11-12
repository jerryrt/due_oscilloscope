"""LM27762 transient cases for the version 2 rails, on TI's own model (LM27762_TRANS.LIB), by way of version 1's
whatif/lm27762 harness (its deck(), analyse() and capacitor data are imported read-only; nothing is written there).

What this adds over version 1: the version 2 feedback values and loads (OUT- carries the AWG dual only, the scope sits on
+3.3 V), the rails at their tolerance corners (power.py), and the AWG's full-scale step between its two ends into 50 ohm.
Model facts that carry over (whatif/lm27762/run.py header): `set ngbehavior=ps`, method=gear, abstol=1e-3, ideal capacitors
(derated from Samsung's DC-bias curve for C15850), the model has NO LDO loop and its ripple under-reads the datasheet, and
it converges by lottery (about half the cases of version 1 stalled at the PFM timer diode).  The model's own references are
1.216 V, the datasheet says 1.2 V (+-1.5 %), so the feedback ratios are set to put the MODEL's output on the value asked for.

The TI library is read in place from the main checkout's untracked models/ directory (not in this worktree); the one translation
(patch_lib.py) is applied to a copy written to the scratch directory, never into the repository.
Usage: python3 -I lm_tran.py [case ...]   (at most 3 ngspice at once; results in lm_results.json, raw in raw_lm/ (not committed))."""
import hashlib, importlib.util, json, os, subprocess, sys, tempfile, time
from concurrent.futures import ThreadPoolExecutor
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import power
from common import LM, TPH

V1 = os.path.normpath(os.path.join(HERE, "../../../whatif/lm27762"))
sys.path.insert(0, V1)
TI = "/home/jerry/EE.Projects/due_oscilloscope/hardware/afe-proto/models/lm27762/LM27762_TRANS.LIB"
OUT = os.path.join(HERE, "raw_lm")
SCR = os.environ.get("LM_SCRATCH") or os.path.join(tempfile.gettempdir(), "afe-lm27762-v2")
import samsung as _sam                      # imported from V1; its data file is in the main checkout's untracked models/ directory
_sam.SAM_FILE = "/home/jerry/EE.Projects/due_oscilloscope/hardware/afe-proto/models/cl21a106kaynnne/CL21A106KAYNNN_product_page.html"
spec = importlib.util.spec_from_file_location("lm1", os.path.join(V1, "run.py"))
sys.path.insert(0, V1)
lm1 = importlib.util.module_from_spec(spec); spec.loader.exec_module(lm1)
assert hashlib.sha256(open(TI, "rb").read()).hexdigest() == lm1.TI_SHA, "TI file does not match SOURCES.md"
lm1.SCRATCH = SCR

def libfor(patches):
    """lm1's translated copy of TI's file, with the source path made absolute (patch_lib.py reads it relative to its own folder)."""
    if not patches:
        return TI
    os.makedirs(SCR, exist_ok=True)
    out = os.path.join(SCR, "p_" + "_".join(patches) + ".lib")
    if os.path.exists(out) and os.path.getsize(out) > 20000:
        return out          # written once (three ngspice threads share it; concurrent writes truncated it)
    src = open(os.path.join(V1, "patch_lib.py")).read()
    old = 'SRC = os.path.join(HERE, "../../models/lm27762/LM27762_TRANS.LIB")'
    assert old in src
    code = src.replace(old, f"SRC = {TI!r}")
    scr = os.path.join(SCR, "patch_lib_abs.py"); open(scr, "w").write(code)
    subprocess.run([sys.executable, "-I", scr, ",".join(patches), out], check=True, capture_output=True)
    return out
lm1.libfor = libfor

VREF = 1.216                      # the model's own reference (both rails)
def fb_for(vp, vn):
    """Feedback resistors that put TI's model on +vp / -vn (R2 = R4 = 100k)."""
    return (100e3 * (vp / VREF - 1), 100e3, 100e3 * (vn / VREF - 1), 100e3)

rc = power.rail_corners()
NOM, MAX, MIN = (rc["nom_p"], rc["nom_n"]), (rc["max_p"], rc["max_n"]), (rc["min_p"], rc["min_n"])
v_awg, _ = power.awg_values()
def loads(rl, vo, vp=rc["nom_p"]):
    b = power.budget(vp, v_awg, rl, vo, TPH["iq_max"])
    return b["Ip"], b["In"]
IP_B, IN_B = loads(50.0, -1.9)    # the AWG into 50 ohm at the window bottom
IP_T, IN_T = loads(50.0, 2.0)     # ... and near its top
IP_I, IN_I = loads(float("inf"), 0.0)
C1 = ("ideal", 1e-6 * 0.63)       # 1 uF X5R 0603 (C15849) at -10 % and an assumed -30 % bias loss *(check)*
STEP = (("p", 1.3e-3, IP_T - IP_B), ("n", 1.3e-3, IN_T - IN_B))   # bottom -> top: +rail loaded more, -rail unloaded

CASES = {
    "su_5.0":      dict(vin=5.0,  fb=fb_for(*NOM), ip=IP_I, ineg=IN_I, c1=C1, tstop=1.6e-3, tmax=0.5e-6),
    "su_5.25_max": dict(vin=5.25, fb=fb_for(*MAX), ip=IP_B, ineg=IN_B, c1=C1, tstop=1.6e-3, tmax=0.5e-6),
    "su_4.5_min":  dict(vin=4.5,  fb=fb_for(*MIN), ip=IP_B, ineg=IN_B, c1=C1, tstop=1.6e-3, tmax=0.5e-6),
    "step_5.0":    dict(vin=5.0,  fb=fb_for(*NOM), ip=IP_B, ineg=IN_B, c1=C1, steps=STEP, tstop=1.7e-3, tmax=0.5e-6),
    "rip_bot":     dict(vin=5.0,  fb=fb_for(*NOM), ip=IP_B, ineg=IN_B, c1=C1, tstop=1.6e-3, tmax=0.5e-6),
    "rip_idle":    dict(vin=5.0,  fb=fb_for(*NOM), ip=IP_I, ineg=IN_I, c1=C1, tstop=1.6e-3, tmax=0.5e-6),
    "step_t1":     dict(vin=5.0,  fb=fb_for(*NOM), ip=IP_B, ineg=IN_B, c1=C1, steps=STEP, tstop=1.7e-3, tmax=1.0e-6),
    "su_5.0_t1":   dict(vin=5.0,  fb=fb_for(*NOM), ip=IP_I, ineg=IN_I, c1=C1, tstop=1.6e-3, tmax=1.0e-6),
}
lm1.CASES.update(CASES)

def run(tag, **kw):
    os.makedirs(OUT, exist_ok=True)
    net, meta = lm1.deck(tag, **kw)
    open(os.path.join(OUT, f"{tag}.cir"), "w").write(net)
    open(os.path.join(OUT, ".spiceinit"), "w").write("set ngbehavior=ps\n")
    t0 = time.time()
    p = subprocess.run(["ngspice", "-b", f"{tag}.cir"], cwd=OUT, capture_output=True, text=True, timeout=6000)
    log = p.stdout + p.stderr
    open(os.path.join(OUT, f"{tag}.log"), "w").write(log)
    fail = [l for l in log.splitlines() if "Timestep too small" in l or "rror" in l]
    if "Compatibility modes selected: ps" not in log:
        fail.append("PSpice compatibility mode not active")
    dat = os.path.join(OUT, f"{tag}.dat")
    if fail or not os.path.exists(dat):
        return dict(tag=tag, ok=False, why=fail[:3], secs=time.time() - t0)
    a = np.loadtxt(dat); os.remove(dat)
    names = ["outp", "outn", "cpout", "vin", "pg", "phi2", "isrc"]
    d = {n: a[:, 2 * i + 1] for i, n in enumerate(names)}; d["t"] = a[:, 0]
    np.savez_compressed(os.path.join(OUT, f"{tag}.npz"), **d)
    return dict(tag=tag, ok=True, secs=time.time() - t0, **meta)

if __name__ == "__main__":
    lm1.OUT = OUT
    names = sys.argv[1:] or list(CASES)
    print("loads (mA): bottom", IP_B * 1e3, IN_B * 1e3, "top", IP_T * 1e3, IN_T * 1e3, "idle", IP_I * 1e3, IN_I * 1e3, flush=True)
    with ThreadPoolExecutor(3) as ex:
        res = dict(zip(names, ex.map(lambda n: run(n, **CASES[n]), names)))
    for n, r in res.items():
        print(n, "OK" if r["ok"] else "FAIL", f"{r['secs']:.0f}s", "" if r["ok"] else r["why"], flush=True)
    A = lm1.analyse(res)
    A = {k: dict(v, loads_mA=dict(ip=CASES[k]["ip"] * 1e3, ineg=CASES[k]["ineg"] * 1e3), vin=CASES[k]["vin"]) for k, v in A.items()}
    p = os.path.join(HERE, "lm_results.json")
    old = json.load(open(p)) if os.path.exists(p) else {}
    old.update(A)
    json.dump(dict(sorted(old.items())), open(p, "w"), indent=1, default=float)
    print(json.dumps(A, indent=1, default=lambda x: round(float(x), 6)))
