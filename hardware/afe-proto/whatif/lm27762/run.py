"""TI's LM27762 transient model (LM27762_TRANS.LIB, SNVMAV1, WEBENCH 02FEB2017) in ngspice 47.  TI's file is read in place
(hash-checked); the one translation is written by patch_lib.py into the session scratch area, never into the repository.

What it takes to run (trials/convergence-trials.txt has the ~45 exploratory runs; later trials are in this file's history):
  * `set ngbehavior=ps` (.spiceinit): PSpice mode turns `&`/`|` into `&&`/`||` and VSWITCH into the `pswitch` code
    model.  Without it the file stops at the first `&` (line 55), which is what models/SOURCES.md recorded.  With it,
    TI's unmodified file runs 1 ms unloaded with ideal capacitors (trial p2).
  * `.options method=gear abstol=1e-3`: the pump path (M1/M2, KP = 1e6) has ~1000 S at rest, so the default 1 pA current
    tolerance cannot be met and the step collapses at the first pump edge (402 us) or pulse skip (~500 us).
  * patch "ddrs" (Rs = 10 mohm on TI's ideal diode d_d): without it every LOADED run stalls on the PFM timer diode U25.
  * ideal capacitors (Samsung's derated values, no ESR/ESL): with C15850's ESR or ESL on CIN / outputs every run stalls
    near 420 us (oscillator clamp diodes, clamp U23 on OUT-).  The model's LDO outputs are a 1 mohm source, so the output
    capacitor's ESR/ESL would not shape its output ripple anyway.
Even so convergence is a lottery: of 23 cases 13 ran, the others stalled at U25 with no pattern in the physics
(5.25 V ran, 5.0 V did not; 1 uF ran at a 0.5 us maximum step, not at 1 or 2 us).  The abstol=1e-4 check never ran.
Usage: python3 -I run.py [case ...]   (at most 3 ngspice at a time, LM_JOBS)."""
import hashlib, json, os, subprocess, sys, tempfile, time
from concurrent.futures import ThreadPoolExecutor
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import samsung

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
TI_LIB = "../../models/lm27762/LM27762_TRANS.LIB"          # relative to this folder; never copied (MC-6)
TI_SHA = "16c322a7ad5f3ff2b5a7bb1355f4474ec12fe7335487aed5ec1b1dff293af42a"   # models/SOURCES.md
JOBS = min(3, int(os.environ.get("LM_JOBS", "3")))
SAM = samsung.load()
TOL = 0.9                                   # -10 % (K) on top of Samsung's DC-bias curve, as sim/powercal
ESR, ESL = SAM["esr"](2e6), SAM["esl"]      # 4.04 mohm at 2 MHz, 0.373 nH

def kc(v):
    return SAM["k"](v) * TOL

# design (docs/architecture.md, Power): 174k/100k on FB+, R3 = 330k||100k, R4 = 330k/3 on FB-
R1P, R2P = 174e3, 100e3
R3N, R4N = 1/(1/330e3 + 1/100e3), 330e3/3

RLP = 0.1
NOESL = set()      # capacitor names modelled without ESL (see the convergence note at the cases that use it)
def c15850(name, a, b, n, vbias):
    """n x C15850 in parallel at vbias: capacitance from Samsung's DC-bias curve x 0.9, ESR at 2 MHz, ESL fitted."""
    c = 10e-6 * kc(vbias) * n
    if name in NOESL or "all" in NOESL:
        return [f"C{name} {a} {name}_1 {c:.4e}", f"R{name} {name}_1 {b} {ESR/n:.4e}"]
    # RLP across the ESL: TI's LDO outputs are an ideal source behind 1 mohm with 1 nF inside (R6/C5), so the part's
    # 0.37 nH and that 1 nF make a 360 MHz tank with Q > 100 that the model was never meant to resolve; ngspice rings it and
    # the step collapses on the clamp diode U23.  0.1 ohm per part damps it; at 2 MHz it changes |Z| of the ESL by
    # (wL/R)^2 = 0.05 %, at 10 MHz by 5 % (the ESL then reads about 3 % lower).
    return [f"C{name} {a} {name}_1 {c:.4e}", f"R{name} {name}_1 {name}_2 {ESR/n:.4e}", f"L{name} {name}_2 {b} {ESL/n:.4e}",
            f"RLP{name} {name}_2 {b} {RLP/n:.4e}"]

SCRATCH = os.environ.get("LM_SCRATCH", os.path.join(tempfile.gettempdir(), "afe-lm27762"))  # outside the repository
def libfor(patches):
    """TI's file in place when no patch is asked; otherwise a translated copy written by patch_lib.py OUTSIDE the
    repository (the session scratch area), never into a tracked path (MC-6)."""
    if not patches:
        return os.path.join(HERE, TI_LIB)
    os.makedirs(SCRATCH, exist_ok=True)
    out = os.path.join(SCRATCH, "p_" + "_".join(patches) + ".lib")
    subprocess.run([sys.executable, "-I", os.path.join(HERE, "patch_lib.py"), ",".join(patches), out], check=True,
                   capture_output=True)
    return out

def deck(tag, tout=5e-9, opts="method=gear", patches=("ddrs",), noesl=(), capmodel="ideal", vin=5.0, ramp=1e-6, rsrc=1.2, cin=("c15850", 2), c1=("ideal", 1e-6), ccp=("c15850", 2),
         cop=("c15850", 2), con=("c15850", 2), ip=50e-3, ineg=20e-3, steps=(), tstop=1.6e-3, tmax=1e-6,
         abstol=1e-3, fb=(R1P, R2P, R3N, R4N), save_from=0.0):
    """rsrc: Due 5V source 0.2 ohm + the 1 ohm sense resistor (architecture.md).  ip / ineg: DC loads (current sinks).
    steps: (rail, t0, amp) current steps, 100 ns rise, held.  Capacitor tuples: ("c15850", n) or ("ideal", F)."""
    r1, r2, r3, r4 = fb
    NOESL.clear(); NOESL.update(noesl)
    vop = 1.216*(1 + r1/r2); von = -1.216*(1 + r3/r4)        # the model's own references (vref1 = 1.216, vref = -1.216)
    L = [f"* {tag} patches={','.join(patches) or 'none'}", f".include {libfor(patches)}",
         f"Vsrc vsrc 0 PWL(0 0 {ramp:g} {vin})", f"Rsrc vsrc vin {rsrc}"]
    def cap(name, node, spec, vb):
        if spec[0] == "c15850" and capmodel == "ideal":
            return [f"C{name} {node} 0 {10e-6*kc(vb)*spec[1]:.4e}"]
        if spec[0] == "c15850":
            return c15850(name, node, 0, spec[1], vb)
        return [f"C{name} {node} 0 {spec[1]:g}"] if node != "c1" else []
    L += cap("in", "vin", cin, vin)
    if c1[0] == "c15850" and capmodel == "ideal":
        L += [f"Cfly cp cn {10e-6*kc(vin)*c1[1]:.4e}"]
    elif c1[0] == "c15850":
        L += c15850("fly", "cp", "cn", c1[1], vin)
    else:
        L += [f"Cfly cp cn {c1[1]:g}"]
    L += cap("cpo", "cpout", ccp, vin - 0.15)
    L += cap("op", "outp", cop, vop)
    L += cap("on", "outn", con, abs(von))
    L += ["* pins: Cn Cp CPOUT PGOOD EN_N EN_P VIN FB_N FB_P PAD OUT_N OUT_P GND",
          "X1 cn cp cpout pg vin vin vin fbn fbp 0 outn outp 0 LM27762_TRANS",
          f"Rfp1 outp fbp {r1:g}", f"Rfp2 fbp 0 {r2:g}", f"Rfn3 outn fbn {r3:g}", f"Rfn4 fbn 0 {r4:g}",
          "Rpg pg vin 10k",
          # DC loads as resistors at the model's settled rail (a B-source sink with a min/max kink at the operating point
          # stalled ngspice on every ripple cycle)
          ] + ([f"Rldp outp 0 {vop/ip:.4g}"] if ip else []) + ([f"Rldn outn 0 {-von/ineg:.4g}"] if ineg else [])
    for i, (rail, t0, amp) in enumerate(steps):
        if rail == "p":
            L.append(f"Istp{i} outp 0 PWL(0 0 {t0:g} 0 {t0+100e-9:g} {amp:g})")
        else:
            L.append(f"Istn{i} 0 outn PWL(0 0 {t0:g} 0 {t0+100e-9:g} {amp:g})")
    vecs = "v(outp) v(outn) v(cpout) v(vin) v(pg) v(x1.phi2) i(Vsrc)"
    L += [f".options {opts} abstol={abstol:g}", f".tran {tout:g} {tstop:g} {save_from:g} {tmax:g} uic",
          ".control", "run", f"linearize {vecs}", f"wrdata {tag}.dat {vecs}", ".endc", ".end"]
    return "\n".join(L) + "\n", dict(vop=vop, von=von)

def run(tag, **kw):
    os.makedirs(OUT, exist_ok=True)
    net, meta = deck(tag, **kw)
    with open(os.path.join(OUT, f"{tag}.cir"), "w") as f:
        f.write(net)
    t0 = time.time()
    open(os.path.join(OUT, ".spiceinit"), "w").write(open(os.path.join(HERE, ".spiceinit")).read())
    p = subprocess.run(["ngspice", "-b", f"{tag}.cir"], cwd=OUT, capture_output=True, text=True, timeout=3000)
    log = p.stdout + p.stderr
    open(os.path.join(OUT, f"{tag}.log"), "w").write(log)
    fail = [l for l in log.splitlines() if "Timestep too small" in l or "rror" in l]
    if "Compatibility modes selected: ps" not in log:
        fail.append("PSpice compatibility mode not active")
    dat = os.path.join(OUT, f"{tag}.dat")
    if fail or not os.path.exists(dat):
        return dict(tag=tag, ok=False, why=fail[:3], secs=time.time()-t0)
    a = np.loadtxt(dat)
    os.remove(dat)
    names = ["outp", "outn", "cpout", "vin", "pg", "phi2", "isrc"]
    d = {n: a[:, 2*i+1] for i, n in enumerate(names)}
    d["t"] = a[:, 0]
    np.savez_compressed(os.path.join(OUT, f"{tag}.npz"), **d)
    return dict(tag=tag, ok=True, secs=time.time()-t0, **meta)

def load(tag):
    z = np.load(os.path.join(OUT, f"{tag}.npz"))
    return {k: z[k] for k in z.files}

def pump_freq(t, phi2, t1, t2):
    m = (t >= t1) & (t < t2); x = phi2[m] > 0.5
    rises = np.flatnonzero(~x[:-1] & x[1:])
    if len(rises) < 2:
        return 0.0, len(rises)
    return (len(rises)-1) / (t[m][rises[-1]] - t[m][rises[0]]), len(rises)

def spectrum_peak(t, x, t1, t2, fmin=1.0e6, fmax=3.0e6):
    """Largest line between fmin and fmax (Hann window, peak amplitude) and its frequency."""
    m = (t >= t1) & (t < t2); xx = x[m] - x[m].mean(); n = len(xx); dt = t[1]-t[0]
    w = np.hanning(n); X = np.fft.rfft(xx*w) * 2 / w.sum(); f = np.fft.rfftfreq(n, dt)
    s = (f >= fmin) & (f <= fmax); i = np.argmax(np.abs(X[s]))
    return float(np.abs(X[s])[i]), float(f[s][i])

def edges(t, x, final, start_t=0.0):
    """10 % / 90 % crossing times of a ramp from 0 toward final (either sign), and the overshoot past final."""
    s = np.sign(final); y = s*x; F = abs(final); m = t >= start_t
    def cross(level):
        i = np.flatnonzero((y >= level) & m)
        return float(t[i[0]]) if len(i) else float("nan")
    return cross(0.1*F), cross(0.9*F), float(y.max() - F)

CASES = {}
def case(name, **kw):
    CASES[name] = kw

# --- (a) start-up, EN+ = EN- = VIN, 5 V (asked), and the powercal corners 5.25 / 4.4 V; 1 us and 100 us edges
for v in (5.0, 5.25, 4.4):
    for r in (1e-6, 100e-6):
        case(f"su_{v}_{int(r*1e6)}us", vin=v, ramp=r, tstop=1.6e-3)
case("su_5.0_1us_noload", vin=5.0, ramp=1e-6, ip=0.0, ineg=0.0, tstop=1.6e-3)
# --- (b) load steps on a settled rail: +23 mA (the AWG short, PW-2 / P2-a) on OUT+ at 1.2 ms, on OUT- at 1.45 ms
case("step_5.0", vin=5.0, steps=(("p", 1.2e-3, 23e-3), ("n", 1.45e-3, 23e-3)), tstop=1.7e-3)
# --- the abstol check: the same step case at 1e-4 (if it converges)
case("step_5.0_abstol1e-4", vin=5.0, steps=(("p", 1.2e-3, 23e-3), ("n", 1.45e-3, 23e-3)), tstop=1.7e-3, abstol=1e-4)
# --- (c) ripple: steady state at the design loads, light negative load (PFM region), and the datasheet's 2.2 uF outputs
case("rip_5.0", vin=5.0, tstop=1.6e-3, save_from=0.0)
case("rip_5.0_ineg5mA", vin=5.0, ineg=5e-3, tstop=1.6e-3)
case("rip_5.0_samsung", vin=5.0, capmodel="samsung", tstop=1.6e-3)     # C15850 with ESR/ESL: expected not to converge
case("rip_5.0_cout2u2", vin=5.0, cop=("ideal", 2.2e-6), con=("ideal", 2.2e-6), tstop=1.6e-3)
# --- datasheet comparison, Fig 5-1 conditions: VIN 3.7 V, +-3 V, CIN = COUT = 2.2 uF, C1 = 1 uF, CCP = 4.7 uF
FB3 = (150e3, 100e3, 3.0/1.22*110e3 - 110e3, 110e3)
for i_ in (25e-3, 100e-3):
    case(f"ds_fig51_{int(i_*1e3)}mA", vin=3.7, rsrc=0.0, cin=("ideal", 2.2e-6), c1=("ideal", 1e-6), ccp=("ideal", 4.7e-6),
         cop=("ideal", 2.2e-6), con=("ideal", 2.2e-6), ip=i_, ineg=i_, fb=FB3, tstop=1.6e-3)
# --- F-5: the flying capacitor from existing types: 100 nF (C14663, X7R, bias derating not in the repo: nominal),
#     one C15850 (10 uF at 5 V bias), against the datasheet's 1 uF; design loads, then a 23 mA step on OUT-
for lab, c1 in (("1u", ("ideal", 1e-6)), ("100n", ("ideal", 100e-9)), ("c15850", ("c15850", 1))):
    case(f"fly_{lab}", vin=5.0, c1=c1, steps=(("n", 1.3e-3, 23e-3),), tstop=1.6e-3)
    case(f"fly_{lab}_4.4", vin=4.4, c1=c1, steps=(("n", 1.3e-3, 23e-3),), tstop=1.6e-3)

# retries of the C1 = 1 uF design case, which stalled at the PFM timer with the default 1 us maximum step
case("fly_1u_tmax0.5u", vin=5.0, c1=("ideal", 1e-6), steps=(("n", 1.3e-3, 23e-3),), tstop=1.6e-3, tmax=0.5e-6)
case("fly_1u_tmax2u", vin=5.0, c1=("ideal", 1e-6), steps=(("n", 1.3e-3, 23e-3),), tstop=1.6e-3, tmax=2e-6)
case("fly_1u_ineg21mA", vin=5.0, c1=("ideal", 1e-6), ineg=21e-3, steps=(("n", 1.3e-3, 23e-3),), tstop=1.6e-3)

def analyse(res):
    R = {}
    for tag, r in res.items():
        if not r["ok"]:
            R[tag] = dict(ok=False, why=r["why"]); continue
        d = load(tag); t = d["t"]; e = dict(ok=True, secs=round(r["secs"], 1))
        tend = t[-1]
        win = (tend - 200e-6, tend) if not CASES[tag].get("steps") else (CASES[tag]["steps"][0][1] - 200e-6, CASES[tag]["steps"][0][1])
        fp = np.mean(d["outp"][(t >= win[0]) & (t < win[1])]); fn = np.mean(d["outn"][(t >= win[0]) & (t < win[1])])
        e["outp_dc"], e["outn_dc"] = fp, fn
        e["cpout_dc"] = float(np.mean(d["cpout"][(t >= win[0]) & (t < win[1])]))
        p10, p90, pov = edges(t, d["outp"], fp); n10, n90, nov = edges(t, d["outn"], fn)
        e.update(outp_t10=p10, outp_t90=p90, outp_over=pov, outn_t10=n10, outn_t90=n90, outn_over=nov,
                 rail_gap_90=n90 - p90, outp_max=float(d["outp"].max()), outn_min=float(d["outn"].min()),
                 bare_max=float((d["outp"] - d["outn"]).max()))
        pgl = np.flatnonzero(d["pg"] < 0.5*d["vin"]); e["pgood_low_t"] = float(t[pgl[0]]) if len(pgl) else None
        fsw, nsw = pump_freq(t, d["phi2"], *win); e["pump_hz"], e["pump_edges"] = fsw, nsw
        for k in ("outp", "outn", "cpout", "vin"):
            seg = d[k][(t >= win[0]) & (t < win[1])]
            e[f"{k}_pp"] = float(seg.max() - seg.min())
            e[f"{k}_line_pk"], e[f"{k}_line_f"] = spectrum_peak(t, d[k], *win)
        isrc = d["isrc"][(t >= win[0]) & (t < win[1])]
        e["iin_mean"] = float(-isrc.mean())
        for i, (rail, t0, amp) in enumerate(CASES[tag].get("steps", ())):
            k = "outp" if rail == "p" else "outn"
            pre = (t >= t0 - 50e-6) & (t < t0); post = (t >= t0) & (t < t0 + 100e-6)
            v0 = d[k][pre].mean(); seg = d[k][post] - v0; tt = t[post] - t0
            s = 1 if rail == "p" else -1          # droop direction: toward zero
            late = (t >= t0 + 150e-6) & (t < t0 + 250e-6) if t0 + 250e-6 <= tend else (t >= tend - 50e-6)
            v1 = d[k][late].mean()
            dev = s*seg
            e[f"step{i}_{k}"] = dict(droop_mV=float(-dev.min()*1e3), over_mV=float(max(dev.max(), 0)*1e3),
                                     static_mV=float((v1 - v0)*1e3), pp_before_mV=float(np.ptp(d[k][pre])*1e3))
        R[tag] = e
    return R

if __name__ == "__main__":
    assert hashlib.sha256(open(os.path.join(HERE, TI_LIB), "rb").read()).hexdigest() == TI_SHA
    assert open(os.path.join(HERE, ".spiceinit")).read().strip() == "set ngbehavior=ps"
    names = sys.argv[1:] or list(CASES)
    with ThreadPoolExecutor(JOBS) as ex:
        res = dict(zip(names, ex.map(lambda n: run(n, **CASES[n]), names)))
    for n, r in res.items():
        print(n, "OK" if r["ok"] else "FAIL", f"{r['secs']:.0f}s", "" if r["ok"] else r["why"])
    A = analyse(res)
    old = {}
    p = os.path.join(HERE, "results.json")
    if os.path.exists(p):
        old = json.load(open(p))
    old.update(A)
    json.dump(dict(sorted(old.items())), open(p, "w"), indent=1, default=float)
    print(json.dumps(A, indent=1, default=lambda x: round(float(x), 6)))
