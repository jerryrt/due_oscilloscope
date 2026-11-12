"""Netlist builder and ngspice plumbing for the differential-mode simulation (2d).
The channel netlist, the op-amp model include and the range-switch model are the
2b ones (../scope/netlib.py, ../scope/models/rangesw.lib), reused by path; nothing
is copied and nothing is written outside sim/diff/."""
import os, sys, re, subprocess, hashlib
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SCOPE = os.path.join(HERE, "..", "scope")
sys.path.insert(0, SCOPE)
import netlib as nl                      # noqa: E402  (2b's builder)
VARIANT = os.environ.get("D2_VARIANT", "hz")  # 'lowz2' = round 2 (default), 'lowz' = round 1, 'legacy' = the 1 Mohm one
nl.use_variant(VARIANT)
nl.NETD = os.path.join(HERE, "netlists")  # never write into sim/scope
nl.WORK = os.path.join(HERE, "work")

OPA354_LIB = "../../../models/opa354/OPA354_PSPICE.lib"   # relative to netlists/ or work/
RANGESW = "../../scope/models/rangesw.lib"
OPTS = ".options abstol=1e-13 itl1=4000 itl4=500 reltol=1e-4 method=gear"

# ---- the settled 2b channel, as nominal values -------------------------------------------
BASE = dict(nl.P0)
BASE.update(sw="rf", op="OPA354")
UNC = BASE.get("div") == "unc"
C1_NOM = nl.c1_of(BASE)                  # legacy: 12.27 pF, the ideal compensation; lowz: none
C2_EXT = BASE["C2"]                      # legacy: 38 pF external; the model carries the op-amp's own input C

def c1_ideal(leg_nom):
    """Ideal compensating C1 (R1*C1 = (R2leg||R3)*C2tot) for a nominal R2 leg value; the sim's convention, as 2b."""
    r3, r1 = BASE["R3"], BASE["R1"]
    return (C2_EXT + BASE["C2tot_extra"]) * (leg_nom * r3 / (leg_nom + r3)) / r1

def chan(d, rng_):
    """Parameter dict for one channel from a draw's per-channel dict.  The R2 leg is the fixed R2 plus the trimmer Rt."""
    p = dict(BASE)
    if UNC:   # uncompensated low-impedance divider: no C1/C2; the stray at N carries the draw's 'stray'
        p.update(R1=d["R1"], R2=d["R2"] + d.get("Rt", 0.0), R3=d["R3"], Rs3=d["Rs3"], RF=d["RF"], RG=d["RG"],
                 Cn=BASE["Cn"] + d["stray"], Ron_sw=d["Ron"], vos=d["vos"], rng=rng_)
        if BASE.get("inj") == "R3":
            p["Ron_inj"] = d.get("Roninj", BASE["Ron_inj"])
        return p
    c2 = C2_EXT * (1 + d["eC2"]) + d["stray"]
    leg = d["R2"] + d.get("Rt", 0.0)
    if d.get("trim"):   # C1 adjusted on the bench to flatten this channel's own response; eC1 is the residual
        c1 = (c2 + BASE["C2tot_extra"]) * (leg * d["R3"] / (leg + d["R3"])) / d["R1"] * (1 + d["eC1"])
    else:
        if VARIANT == "hz":   # the fixed 12 pF C1 part at its tolerance
            c1 = BASE["C1"] * (1 + d["eC1"])
        else:
            c1 = c1_ideal(d.get("leg_nom", BASE["R2"])) * (1 + d["eC1"]) * (1 + d.get("csys", 0.0))   # csys: the E24 12 pF against the ideal, both channels alike
    p.update(R1=d["R1"], R2=leg, R3=d["R3"], RF=d["RF"], RG=d["RG"], C1=c1, C2=c2,
             Ron_sw=d["Ron"], vos=d["vos"], rng=rng_)
    return p

def rails_p(sh):
    p = dict(BASE)
    p.update(aref=sh["aref"], vmid=sh["aref"] / 2 + sh["cent"], v3=sh["aref"] + 2 * sh["cent"], vcc=sh["vcc"])
    return p

def netlist(title, draw, rng_, body_ctl, sources, ac_rail=None):
    pa, pb = chan(draw["A"], rng_), chan(draw["B"], rng_)
    sh = draw["sh"]
    rp = rails_p(sh)
    t = f"* {title}\n.include {OPA354_LIB}\n.include {RANGESW}\n{OPTS}\n"
    if BASE.get("sense") == "buf":
        t += ".include ../../../models/opa365/OPA365_PSPICE.lib\n"
    if BASE.get("pinclamp"):
        t += ".include ../../../models-open/bat54s-c7420333/bat54s_c7420333.lib\n"
    t += nl.rails(rp, ac_vm=(ac_rail == 'vm'), ac_v3=(ac_rail == 'v3'))
    t += sources
    t += f"Rsa sa ain {max(draw['Rsa'], 1e-3):.6g}\nRsb sb bin {max(draw['Rsb'], 1e-3):.6g}\n"
    t += nl.core(pa, "a") + "\n" + nl.core(pb, "b") + "\n"
    t += ".control\n" + body_ctl + ".endc\n.end\n"
    return t

def run(name, text, subdir="work", keep=False):
    d = os.path.join(HERE, subdir)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, name + ".cir")
    with open(path, "w") as f:
        f.write(text)
    r = subprocess.run(["ngspice", "-b", name + ".cir"], cwd=d, capture_output=True, text=True, timeout=600)
    out = r.stdout + r.stderr
    return out

def loadrm(name, subdir="work", keep=False):
    fn = os.path.join(HERE, subdir, name + ".dat")
    a = np.loadtxt(fn)
    if not keep:
        os.remove(fn)
    return a

def dc_grid(name, draw, rng_, vgrid, subdir="work"):
    """Pin voltages for every (in1,in2) pair on vgrid (nested sweep, 1 run).  Returns arrays [ia, ib]."""
    lo, hi, st = vgrid[0], vgrid[-1], vgrid[1] - vgrid[0]
    src = "Vsa sa 0 dc 0\nVsb sb 0 dc 0\n"
    ctl = f"dc Vsa {lo} {hi} {st} Vsb {lo} {hi} {st}\nwrdata {name}.dat v(apin) v(bpin) v(aout) v(bout)\n"
    txt = netlist(name, draw, rng_, ctl, src)
    n = len(vgrid)
    d = None
    # the vendor op-amp's operating point occasionally fails to converge at one point of a nested sweep for a given draw
    # (seen on 1 draw in ~600); retry with looser convergence options rather than lose the run
    for opts in (OPTS, ".options abstol=1e-12 itl1=10000 itl4=1000 gmin=1e-10 reltol=1e-3 method=gear",
                 ".options abstol=1e-12 itl1=10000 itl4=1000 gmin=1e-9 reltol=1e-3 method=trap"):
        out = run(name, txt.replace(OPTS, opts), subdir)
        fn = os.path.join(HERE, subdir, name + ".dat")
        if os.path.exists(fn):
            d = loadrm(name, subdir)
            if d.shape[0] == n * n:
                break
        d = None
    if d is None:
        raise RuntimeError(f"{name}: dc grid failed " + out[-400:])
    sa = d[:, 0].reshape(n, n)            # inner sweep (Vsa) is the fast index
    assert np.allclose(sa[0], vgrid, atol=1e-6)
    pa = d[:, 1].reshape(n, n).T          # -> [ia, ib]
    pb = d[:, 3].reshape(n, n).T
    return pa, pb, d[:, 5].reshape(n, n).T, d[:, 7].reshape(n, n).T

def ac_pair(name, draw, rng_, mode, f0=10.0, f1=20e6, ppd=12, subdir="work"):
    """AC response of both pins; mode 'cm' (1 V on both inputs) or 'dm' (+0.5 / -0.5 V)."""
    ma, mb = (1.0, 1.0) if mode == "cm" else (0.5, -0.5)
    ph = lambda m: ("ac 1" if m > 0 else "ac 1 180") if abs(m) == 1 else ("ac 0.5" if m > 0 else "ac 0.5 180")
    src = f"Vsa sa 0 dc 0 {ph(ma)}\nVsb sb 0 dc 0 {ph(mb)}\n"
    ctl = f"ac dec {ppd} {f0} {f1}\nwrdata {name}.dat v(apin) v(bpin)\n"
    run(name, netlist(name, draw, rng_, ctl, src), subdir)
    d = loadrm(name, subdir)
    f = d[:, 0]
    return f, d[:, 1] + 1j * d[:, 2], d[:, 4] + 1j * d[:, 5]

def ngspice_version():
    return nl.ngspice_version()

def sha256(p):
    return nl.sha256(p)

def ac_diff_rail(name, draw, rng_, rail, f0=10.0, f1=2e8, ppd=12, subdir="work"):
    """|transfer| from the shared Vmid ('vm') or the 3.3 V sense node ('v3') to V(apin)-V(bpin)."""
    src = "Vsa sa 0 dc 0\nVsb sb 0 dc 0\n"
    ctl = f"ac dec {ppd} {f0} {f1}\nwrdata {name}.dat v(apin) v(bpin)\n"
    run(name, netlist(name, draw, rng_, ctl, src, ac_rail=rail), subdir)
    d = loadrm(name, subdir)
    return d[:, 0], np.abs((d[:, 1] + 1j * d[:, 2]) - (d[:, 4] + 1j * d[:, 5]))

def noise_pair(name, draw, rng_, fmax, node, subdir="work", fmin=10.0, ppd=20):
    """onoise_total (V rms, fmin..fmax) of `node` (e.g. 'v(apin,bpin)' or 'v(apin)'), everything the netlist has."""
    src = "Vsa sa 0 dc 0 ac 1\nVsb sb 0 dc 0\n"
    ctl = f"noise {node} Vsa dec {ppd} {fmin} {fmax}\nsetplot noise2\nprint onoise_total\n"
    out = run(name, netlist(name, draw, rng_, ctl, src), subdir)
    m = re.search(r"onoise_total\s*=\s*([0-9.eE+-]+)", out)
    if not m:
        raise RuntimeError("noise run failed: " + out[-600:])
    return float(m.group(1))

def cm_sweep(name, draw, rng_, v0, v1, st, subdir="work"):
    """Both inputs driven by the same voltage (Esb copies Vsa); returns V, pins, outputs."""
    src = "Vsa sa 0 dc 0\nEsb sb 0 sa 0 1\n"
    ctl = f"dc Vsa {v0} {v1} {st}\nwrdata {name}.dat v(apin) v(bpin) v(aout) v(bout)\n"
    out = run(name, netlist(name, draw, rng_, ctl, src), subdir)
    d = loadrm(name, subdir)
    return d[:, 0], d[:, 1], d[:, 3], d[:, 5], d[:, 7]
