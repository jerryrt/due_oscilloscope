"""PW-2 on TI's LM27762 transient model, in a form the shared ngspice runner accepts, with per-capacitor loop inductance.

The deck comes from version 1's whatif/lm27762 harness (read-only, imported), which builds the converter on
TI's LM27762_TRANS.LIB with the derated capacitors. This module changes three things about how it is run, and
nothing about the circuit:

  * the .control block that wrote every vector with wrdata is dropped; ngspice writes a raw file with a
    .save of five nodes (outp, outn, vin, cpout, cp) - the 4.95 GB run saved every internal node of TI's model;
  * one corner per process, a wall timeout and the memory cap, through simtools.ngspice_run;
  * the lumped output, pump and input capacitors can be split into their physical parts, each with its own
    series inductance (a pad-to-pin distance), via `inject_l`.

The inductance model L(d) = L0 + K*d is an inference from one agent's extraction (kvm_02), NOT validated *(check)*.
A non-converged run is reported as NO_CONVERGE, never as a pass: the model converges by lottery.
"""
import importlib.util
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

AFE = Path(__file__).resolve().parents[1]
WHATIF = AFE / "whatif" / "lm27762"

ESR = 4.04e-3            # ohm, Samsung CL21A106KAYNNN at 2 MHz *(check)*
L0_NH, K_NH_PER_MM = 2.2, 0.87        # L(d) = L0 + K*d, nH *(check)*
DAMP = 1e3               # ohm across each inductance: ngspice rings an undamped L-C tank at the model's 1 nF
SAVE = ["v(outp)", "v(outn)", "v(vin)", "v(cpout)", "v(cp)"]

# as-built pad-to-pin distances, mm (kvm_02, integrated board, power3_final)
DIST_MM = {"C409": 1.77, "C405": 2.33, "C406": 7.64, "C407": 5.59, "C408": 8.42,
           "C403": 4.24, "C404": 7.59, "C401": 8.55, "C402": 5.95}
# which lumped line of the harness deck each physical capacitor belongs to
GROUPS = {"Cin": ("vin", ("C401", "C402")), "Ccpo": ("cpout", ("C403", "C404")),
          "Cop": ("outp", ("C405", "C406")), "Con": ("outn", ("C407", "C408"))}
FLY = ("Cfly", "cp", "cn", "C409")


def l_nh(d_mm, scale=1.0):
    return scale * (L0_NH + K_NH_PER_MM * d_mm)


def _branch(name, a, b, c, l_nh_value, damp=DAMP, short_until=0.0):
    """One capacitor: a -- C -- ESR -- L(with damping) -- b, or without L when l_nh_value is 0."""
    out = [f"C{name} {a} {name}_1 {c:.4e}", f"R{name}_esr {name}_1 {name}_2 {ESR:.4e}"]
    if l_nh_value > 0:
        out += [f"L{name} {name}_2 {b} {l_nh_value * 1e-9:.4e}", f"R{name}_dmp {name}_2 {b} {damp:g}"]
        if short_until > 0:
            # TI's model stalls at its own start-up (about 0.4 ms) with any series L on its capacitors, at every
            # damping and step tried. The L is shorted until short_until, then released: the ripple is read long
            # after, when the inductor currents have settled (their time constant is L/ESR, nanoseconds).
            out += [f"S{name}_sh {name}_2 {b} swctl 0 SWSH"]
    else:
        out += [f"R{name}_0 {name}_2 {b} 1u"]
    return out


def inject_l(deck, *, scale=1.0, extra_nh=None, dist=None, damp=DAMP, short_until=0.0):
    """The harness deck with each lumped capacitor replaced by its physical parts in series with L(d).

    scale multiplies every L (0 gives the ideal ESR-only parts); extra_nh = {"C405": 100.0} adds a series
    inductance to one capacitor (the control: ripple must visibly worsen). A lumped line that is not found is an
    error: a silently unchanged deck would read as a pass."""
    dist = dist or DIST_MM
    extra_nh = extra_nh or {}
    lines = deck.split("\n")
    done = set()
    out = []
    for ln in lines:
        m = re.match(r"^(Cin|Ccpo|Cop|Con) (\S+) 0 (\S+)$", ln)
        if m and m.group(1) in GROUPS:
            name, node, val = m.groups()
            _, parts = GROUPS[name]
            for p in parts:
                out += _branch(p, node, "0", float(val) / len(parts),
                               l_nh(dist[p], scale) + extra_nh.get(p, 0.0), damp, short_until)
            done.add(name)
            continue
        m = re.match(r"^Cfly (\S+) (\S+) (\S+)$", ln)
        if m:
            a, b, val = m.groups()
            out += _branch(FLY[3], a, b, float(val), l_nh(dist[FLY[3]], scale) + extra_nh.get(FLY[3], 0.0), damp, short_until)
            done.add("Cfly")
            continue
        out.append(ln)
    if short_until > 0:
        i = next(k for k, ln in enumerate(out) if ln.strip() == ".end")
        out[i:i] = [f"Vswctl swctl 0 PWL(0 1 {short_until:g} 1 {short_until + 1e-6:g} 0)", ".model SWSH SW(Vt=0.5 Vh=0.1 Ron=1u Roff=1G)"]
    missing = set(GROUPS) | {"Cfly"}
    missing -= done
    if missing:
        raise ValueError(f"lumped capacitor line(s) not found in the harness deck: {sorted(missing)}")
    return "\n".join(out)


def strip_control(deck):
    """Drop the harness's .control block (linearize + wrdata of seven vectors); the runner wants the analysis alone."""
    return re.sub(r"^\.control\b.*?^\.endc\s*\n", "", deck, flags=re.M | re.S)


CSV_DIR = AFE / "models-open" / "cl21a106kaynnne"
ESL_H = 0.373e-9         # ohm-henry: median over 3-10 MHz with C = 10 uF (PROVENANCE.md)


def samsung_from_csv(csv_dir=CSV_DIR, esl=ESL_H):
    """What whatif/lm27762/samsung.py's load() returns, from the committed numbers instead of Samsung's page
    (which is not in git and whose upstream bytes no longer match its pinned hash). k(V) = 1 + dcbias(|V|)/100."""
    dc = np.genfromtxt(csv_dir / "dcbias.csv", delimiter=",", skip_header=1)
    er = np.genfromtxt(csv_dir / "esr.csv", delimiter=",", skip_header=1)
    xv, yv = dc[np.argsort(dc[:, 0])].T
    fr, rr = er[np.argsort(er[:, 0])].T
    return dict(esr=lambda f: float(np.interp(f, fr, rr)), k=lambda v: 1 + float(np.interp(abs(v), xv, yv)) / 100,
                esl=esl, xv=xv, yv=yv)


def load_harness(csv_dir=CSV_DIR, esl=ESL_H):
    """The frozen whatif/lm27762/run.py as a module, with its `samsung` data read from the committed CSVs. The
    harness imports samsung.py, which parses Samsung's page and asserts the page's sha256; a stand-in module
    with the same interface is put in its place so the frozen files are untouched."""
    import types
    stand_in = types.ModuleType("samsung")
    stand_in.load = lambda: samsung_from_csv(Path(csv_dir), esl)
    sys.modules["samsung"] = stand_in
    sys.path.insert(0, str(WHATIF))
    spec = importlib.util.spec_from_file_location("lm1", WHATIF / "run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@dataclass
class Pw2Result:
    status: str                  # OK | NO_CONVERGE
    tstop_reached: float
    window_s: float
    detail: str = ""
    outp_pp_mv: float | None = None
    outn_pp_mv: float | None = None
    vin_pp_mv: float | None = None
    outp_mean: float | None = None
    outn_mean: float | None = None
    pump_hz: float | None = None


def analyse(t, v, tstop, window=100e-6, min_fraction=0.99, detail=""):
    """Peak-to-peak ripple (mV) and mean of each rail over the last `window` seconds, and the pump frequency from
    cpout's mean crossings. t, v: time vector and {name: samples}. A run that stopped before min_fraction of tstop
    did not converge and is reported as such with no figures."""
    reached = float(t[-1])
    if reached < min_fraction * tstop:
        return Pw2Result("NO_CONVERGE", reached, window, detail)
    m = t >= reached - window
    tt = t[m]
    # ngspice's step is variable: resample onto a uniform grid fine enough for the 0.7 us pump period
    grid = np.linspace(tt[0], tt[-1], max(len(tt), 2000))
    r = {k: np.interp(grid, tt, v[k][m]) for k in ("outp", "outn", "vin", "cp")}
    pp = lambda x: float((x.max() - x.min()) * 1e3)
    c = r["cp"] - r["cp"].mean()           # the flying-capacitor node switches at the pump frequency; cpout is nearly DC
    ups = np.where((c[:-1] < 0) & (c[1:] >= 0))[0]
    f = float((len(ups) - 1) / (grid[ups[-1]] - grid[ups[0]])) if len(ups) > 2 else None
    return Pw2Result("OK", reached, window, "", pp(r["outp"]), pp(r["outn"]), pp(r["vin"]),
                     float(r["outp"].mean()), float(r["outn"].mean()), f)


def case_deck(lm1, tag, *, scale=1.0, extra_nh=None, damp=DAMP, short_until=0.0, **kw):
    """Runner-ready deck text for one case: the harness deck with L injected and its control block removed."""
    net, meta = lm1.deck(tag, **kw)
    return inject_l(strip_control(net), scale=scale, extra_nh=extra_nh, damp=damp, short_until=short_until), meta


def run_case(lm1, tag, workdir, *, mem="2G", timeout=3600, scale=1.0, extra_nh=None, damp=DAMP, short_until=0.0, **kw):
    """Run one case under the shared runner (capped, one corner, required .save) and analyse its last 100 us.
    Returns (Pw2Result, Run). A run that does not converge is NO_CONVERGE, not an exception."""
    from . import ngspice_run as nr
    deck, meta = case_deck(lm1, tag, scale=scale, extra_nh=extra_nh, damp=damp, short_until=short_until, **kw)
    Path(workdir).mkdir(parents=True, exist_ok=True)
    (Path(workdir) / ".spiceinit").write_text("set ngbehavior=ps\n")          # PSpice mode: TI's file does not parse without it
    try:
        run = nr.run(deck, save=SAVE, workdir=workdir, name=tag, mem=mem, timeout=timeout)
    except nr.RunError as e:
        log = (e.result.stdout + "\n" + e.result.stderr) if e.result is not None else ""
        if e.result is None or e.result.cap_killed or e.result.timed_out or "Timestep too small" not in log:
            raise                                       # a cap kill, a timeout or a broken deck is not a convergence failure
        line = next(l for l in log.splitlines() if "Timestep too small" in l)
        reached = 0.0
        if e.raw_path is not None and Path(e.raw_path).exists():
            try:
                reached = float(next(iter(nr.read_raw(e.raw_path).values()))["time"].real[-1])
            except (ValueError, StopIteration):
                pass
        return Pw2Result("NO_CONVERGE", reached, 100e-6, line.strip()), None
    plot = next(iter(run.plots().values()))
    t = plot["time"].real
    v = {k: plot[f"v({k})"] for k in ("outp", "outn", "vin", "cp")}
    return analyse(t, v, kw.get("tstop", 1.6e-3)), run
