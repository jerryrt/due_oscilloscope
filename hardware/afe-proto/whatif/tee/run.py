#!/usr/bin/env python3
"""whatif/tee: replace the PA-3 injection (T-switch per channel, 249 ohm branch) with a manual calibration, a BNC tee
from the AWG output into both scope inputs, the MCP3564 reading the AWG at its BNC (CH1, through its sense divider).

    python3 -I run.py          # ngspice (4 processes, TEE_WORKERS), about 10-15 minutes; writes results/*.json
    python3 -I report.py       # the tables in report.md from results/

The circuit is sim/scope's 'hz' channel pair (760k / 330k / 760k, C1 12 pF, OPA354, range switch across RF), built by
sim/diff's dlib/core2d, both COPIED here (netlib.py, dlib.py, core2d.py; models/rangesw.lib) and patched only to
(1) drop the T-switch from N and give its 6 pF back to C2 (variant 'tee'), (2) let the divider carry its own tolerance
and tempco band.  The OPA354 vendor model is used by relative path and never copied.

Calibration modelled ('tee'): at the reference temperature both inputs are driven together from one node over
+-VT (the AWG at the tee, 11 levels in the sim) and each channel's whole input->pin slope is fitted; at the use
temperature (dT = +-10 K) each pin is divided by its own slope and the common-mode response of the difference is read
on the full DC grid (+-6 V on +-5 V, +-1.25 V on +-1.25 V), as sim/diff does.  The slope's own error from the Due INL
(inl.py) is added as an opposite-sign residual per channel; the op-amp CMRR term (+-0.04 % per channel) is kept, as
sim/diff keeps it.  'stage' is sim/diff's PA-3 injection (the stage only, divider trusted) on the same runs.
"""
import os, sys, json, time
import numpy as np
from concurrent.futures import ProcessPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import dlib, core2d as c, inl

RES = os.path.join(HERE, "results")
os.makedirs(RES, exist_ok=True)
NMC = int(os.environ.get("TEE_NMC", "200"))
WORKERS = int(os.environ.get("TEE_WORKERS", "4"))
SEED = 20261111
VTS = (1.0, 1.15)                  # the AWG's amplitude at the tee: +-1.0 V (AW-1) to +-1.15 V
RCAB = (0.10, 0.12)                # tee arm + cable centre conductor + contacts, ohm, A / B *(check: no cable chosen)*
T0 = time.time()

def log(*a):
    print(f"[{time.time()-T0:6.0f}s]", *a, flush=True)

def jdump(name, obj):
    def conv(o):
        if isinstance(o, (np.floating, np.integer)):
            return o.item()
        if isinstance(o, np.ndarray):
            return o.tolist()
        raise TypeError(type(o))
    with open(os.path.join(RES, name + ".json"), "w") as f:
        json.dump(obj, f, indent=1, default=conv)

# ---- scenarios ---------------------------------------------------------------------------------------------
BASE = dict(c.SPEC, name="design")                    # 0.1 %, every part 25 ppm/K (tau 50), caps 5 %, Ron 3.7-8.8
def one_pct(tau, name):
    return dict(BASE, name=name, tolR_div=0.01, tcr_div=tau / 2.0)   # 330k / 100k Basic 1 %; RF/RG stay 0.1 % 25 ppm/K
SCEN = {
    "design": (BASE, True),
    "1pct_tau25": (one_pct(25, "1pct_tau25"), False),
    "1pct_tau50": (one_pct(50, "1pct_tau50"), False),
    "1pct_tau100": (one_pct(100, "1pct_tau100"), True),
    "1pct_tau200": (one_pct(200, "1pct_tau200"), True),    # datasheet only: +-100 ppm/K each, no tracking stated
}

# ---- the tee calibration -------------------------------------------------------------------------------------
def with_rs(d, ra, rb):
    d = dict(d); d["Rsa"], d["Rsb"] = ra, rb
    return d

def tee_slopes(name, d_ref, rg, vt):
    """Each channel's input->pin slope with both inputs driven from one node over +-vt (the tee), at the reference."""
    st = 2 * vt / 10
    # the sweep starts one step early and that point is dropped: the vendor model's first operating point of a sweep
    # occasionally lands on a wrong solution (seen once in 1000 sweeps, a 0.5 V error at the first point); the fit's
    # residual is then checked, and a failed sweep raises rather than returning a wrong slope
    v, pa, pb, _, _ = dlib.cm_sweep(name, with_rs(d_ref, *RCAB), rg, -vt - st, vt + st / 2, st)
    v, pa, pb = v[1:], pa[1:], pb[1:]
    out = []
    for p in (pa, pb):
        k = np.polyfit(v, p, 1)
        if np.max(np.abs(np.polyval(k, v) - p)) > 2e-3:
            raise RuntimeError(f"{name}: tee sweep not linear (max residual {np.max(np.abs(np.polyval(k, v) - p)):.3g} V)")
        out.append(float(k[0]))
    return tuple(out)

def cal_tee(pa, pb, rg, sA, sB, eop, e=(0.0, 0.0), opamp=True):
    """DC CMRR after the tee calibration on the use-temperature grid (pa, pb [ia, ib]); worse of both op-amp signs."""
    V = c.grid(rg)[-1]
    d = np.asarray(pa) / (sA * (1 + e[0])) - np.asarray(pb) / (sB * (1 + e[1]))
    adm = (d[-1, 0] - d[0, -1]) / (4 * V)
    acm = (d[-1, -1] - d[0, 0]) / (2 * V)
    ea, eb = eop if opamp else (0.0, 0.0)
    return min(20 * np.log10(abs(adm) / max(abs(acm + sg * adm * (ea - eb)), 1e-12)) for sg in (1, -1))

def run_pair(tag, d_use, d_ref, with_ac):
    """All ngspice work for one pair: use grid (+AC), reference grid, tee slopes at both amplitudes."""
    out = {}
    for rg in ("5", "1.25"):
        r1 = c.eval_range(f"{tag}_u_{rg}", d_use, rg, with_ac=with_ac)
        r0 = c.eval_range(f"{tag}_r_{rg}", d_ref, rg, with_ac=False)
        sl = {str(vt): tee_slopes(f"{tag}_t{vt}_{rg}", d_ref, rg, vt) for vt in VTS}
        # sim/diff's PA-3 'stage' calibration on the same runs, exact (residual added in post-processing)
        st = c.cal_cmrr(r0, r1, d_ref, rg)
        o = dict(pa=r1["_pa"].tolist(), pb=r1["_pb"].tolist(), slopes=sl, eop=d_use["eop"],
                 stage_dc=min(st[0], st[1]), cmrr_dc=r1["cmrr_dc"], margin=r1["margin"], dos=r1["dos"],
                 adm=r1["adm"], gA=r1["gA"], gB=r1["gB"], r0_gA=r0["gA"], r0_gB=r0["gB"],
                 r0=dict(pa=r0["_pa"].tolist(), pb=r0["_pb"].tolist()),
                 alphaA=c.alpha_dc(d_ref["A"], d_ref["Rsa"]), alphaB=c.alpha_dc(d_ref["B"], d_ref["Rsb"]))
        if with_ac:
            o["f10k"] = c.at_f(r1["f"], r1["cmrr_f"], 1e4)
            o["f10k_alt"] = c.at_f(r1["f"], r1["cmrr_f_alt"], 1e4)
        out[rg] = o
    return out

def mc_job(args):
    scname, i = args
    sc, ac = SCEN[scname]
    rng = np.random.default_rng([SEED, i])
    d = c.mc_draw(rng, sc)
    return run_pair(f"{scname}_mc{i}", c.at_T(d), c.at_T(c.at_ref(d)), ac)

def corner_job(args):
    scname, key = args
    sc, ac = SCEN[scname]
    du = c.at_T(c.corner_set(sc)[key])
    dr = c.at_T(c.corner_draw(sc, dT=0.0, name=key + "_ref", **c.ref_kw(key)))
    return key, run_pair(f"{scname}_{key}", du, dr, ac)

def main():
    log("ngspice", dlib.ngspice_version(), "variant", dlib.VARIANT, "NOM", c.NOM, "C2", dlib.BASE["C2"], "inj", dlib.BASE.get("inj"))
    hdr = dict(ngspice=dlib.ngspice_version(), nmc=NMC, seed=SEED, nom=c.NOM, C2=dlib.BASE["C2"], vts=VTS, rcab=RCAB,
               opa354_sha=dlib.sha256(os.path.join(HERE, "..", "..", "models", "opa354", "OPA354_PSPICE.lib")),
               rangesw_sha=dlib.sha256(os.path.join(HERE, "models", "rangesw.lib")),
               netlib_src_sha=dlib.sha256(os.path.join(HERE, "..", "..", "sim", "scope", "netlib.py")),
               scen={k: v[0] for k, v in SCEN.items()})
    jdump("header", hdr)
    only = os.environ.get("TEE_ONLY")
    with ProcessPoolExecutor(WORKERS) as ex:
        for scname in SCEN:
            if only and scname not in only.split(","):
                continue
            log("scenario", scname)
            cor = dict(ex.map(corner_job, [(scname, k) for k in c.HOTKW]))
            mc = list(ex.map(mc_job, [(scname, i) for i in range(NMC)], chunksize=4))
            jdump(f"raw_{scname}", dict(corners=cor, mc=mc))
            for fn in os.listdir(os.path.join(HERE, "work")):
                try:
                    os.remove(os.path.join(HERE, "work", fn))
                except OSError:
                    pass
    log("done")

if __name__ == "__main__":
    main()
