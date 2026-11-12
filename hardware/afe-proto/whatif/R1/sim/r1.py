#!/usr/bin/env python3
"""WHATIF R1 (not approved): drop the scope's +/-1.25 V analog gain stage, use the SAM3X PGA (ADC_CGR gain 4,
ADC_COR offset) for +/-1.25 V, keep per channel only the +/-5 V divider and an OPA365 unity buffer (R4).

Run:  python3 -I r1.py [c2 ac noise dc kick prot loop guards]   (default: all), results in results/r1.json.
Reads sim/scope (copied netlib, buffer topology added) and sim/loop/run.py (read in place, redirected to
whatif/R1/sim/loop for every file it writes).  Up to 4 ngspice processes at once."""
import sys, os, json, time, re, importlib.util
sys.dont_write_bytecode = True      # never leave a cache next to sim/loop/run.py (read in place)
from concurrent.futures import ProcessPoolExecutor
HERE = os.path.dirname(os.path.abspath(__file__))
SC = os.path.join(HERE, "scope")
sys.path.insert(0, SC)
import numpy as np
import netlib as N                      # whatif/R1 copy: sw="buf", R1 = R3 = 760k, R2 330k
import run as S                         # whatif/R1 copy of whatif/C2 scope_p3 run.py (uses the netlib above)
LOOPSRC = os.path.abspath(os.path.join(HERE, "..", "..", "..", "sim", "loop", "run.py"))
spec = importlib.util.spec_from_file_location("looprun", LOOPSRC)
L = importlib.util.module_from_spec(spec); spec.loader.exec_module(L)
L.NETD = os.path.join(HERE, "loop", "netlists"); L.WORK = os.path.join(HERE, "loop", "work"); L.RES = os.path.join(HERE, "loop", "results")
assert L.SN is N, "loop must build the scope from the R1 netlib"
RES = os.path.join(HERE, "results"); os.makedirs(RES, exist_ok=True)
OUT = os.path.join(RES, "r1.json")
W = 4

# ------------------------------------------------------------------ datasheet facts (SAM3X, 11057B = Atmel-SAM3X-SAM3A-Series-Datasheet.pdf)
G4 = 4.0                                  # Table 44-6: GAIN=11, DIFF=0 -> 4 (DIFF=1 -> 2)
WIN = (3 / 8, 5 / 8)                      # Figure 44-6: gain 4, offset=1 -> VIN+ 3/8..5/8 vrefin; offset (G-1)Vrefin/2 (Table 44-7)
GE = (-1.56e-2, +0.29e-2)                 # Table 46-31: gain error, single ended, GAIN=xx, VDDIN 3.0-3.6 V
OE = (-30, +56)                           # Table 46-31: offset error, LSB of the gain-4 scale (46.7.0.1: LSB = Vref/4/4096 at gain 4)
SNR = dict(g2_typ=71, g2_min=66, other_typ=62, other_min=57)   # Table 46-33, fADC 20 MHz, fs 1 MHz, fin 127 kHz
# ------------------------------------------------------------------ project facts
CENT = 0.030; TOL = 0.001
AREFS = (3.20, 3.25, 3.30)
DUE_FLOOR_CODES = (0.8, 0.85)            # afe.md 4.1, held code DAC0->A0, gain 1
ADC_ALONE = (0.68, 0.77)                  # afe.md 4.1 (docs/awg.md): rail-tied divider into A2, gain 1
DAC_FLOOR_MV = 0.64                       # owner's convention in sim/loop: DAC0 white, scales with loop gain
AWG_G = 1.1533                            # sim/loop ideal-AWG gain
SC6, AW6 = 0.2e-3, 0.1e-3
CSW = 6e-12                               # PA-3 injection switch at N: TMUX1119 CSOFF 6 pF (whatif/C2 case Csw6) *(check)*
BASE = dict(N.P0, op="OPA365", sw="buf", R1=760e3, R2=330e3, R3=760e3, C1=12e-12, Csw=CSW)

def alpha(p):
    rp = p["R2"] * p["R3"] / (p["R2"] + p["R3"]); return rp / (p["R1"] + rp)

def pp(**kw):
    q = dict(BASE); q.update(kw); return q

# ------------------------------------------------------------------ jobs (each uses unique netlist names)
def j_c2(args):
    """Compensation: divider shelf = |H(1 MHz)| / |H(30 Hz)| - 1 vs the C2 part, with and without the PA-3 switch."""
    csw, c2 = args; nm = f"c2_{csw*1e12:.0f}_{c2*1e12:.2f}"
    p = pp(Csw=csw, C2=c2, sh=L.ADC["derived"]["ron"] and (3.8e3, 6e-12))
    f, h, T = N.ac_response(p, nm, fmin=10, fmax=1e8, ppd=40); a = np.abs(h)
    g = lambda x: float(np.interp(x, f, a))
    return (f"c2|{csw*1e12:.0f}|{c2*1e12:.2f}", dict(shelf_1M=g(1e6) / g(30) - 1, shelf_100k=g(1e5) / g(30) - 1, g30=g(30)))

def bw_ref(f, h, fref):
    a = np.abs(h); g = np.interp(fref, f, a); db = 20 * np.log10(a / g)
    i = np.where((db < -3) & (f > fref))[0]
    if not len(i): return float("inf")
    i = i[0]; return float(10 ** (np.log10(f[i-1]) + (np.log10(f[i]) - np.log10(f[i-1])) * (-3 - db[i-1]) / (db[i] - db[i-1])))

def j_ac(args):
    tag, kw = args; p = pp(**kw); nm = "ac_" + re.sub(r"[^A-Za-z0-9]", "_", tag)
    f, h, T = N.ac_response(p, nm, fmin=10, fmax=2e9, ppd=40)
    m = N.freq_metrics(f[f >= 1e4], h[f >= 1e4])
    k = f <= 5e8      # the vendor model re-crosses |T| = 1 near 1.9 GHz at Riso 50 (outside its validity); PM at the main crossing
    pm = N.phase_margin(f[k], T[k])
    return (tag, dict(bw10k=m["bw"], bw1k=bw_ref(f, h, 1e3), bw100=bw_ref(f, h, 100.0), peak_db=m["peak_db"], pm=pm["pm"], fc=pm["fc"],
                      g_dc=float(np.abs(h[0])), g10k=float(np.interp(1e4, f, np.abs(h)))))

def j_noise(args):
    tag, kw, fmax = args; p = pp(**kw); nm = "nz_" + re.sub(r"[^A-Za-z0-9]", "_", tag)
    a = N.noise_total(p, nm, fmax, "all"); r = N.noise_total(p, nm + "r", fmax, "res"); m = N.noise_total(p, nm + "m", fmax, "amp")
    vm = S.transfer_rms(p, nm + "x", "vm", S.EN_VMID, fmax); v3 = S.transfer_rms(p, nm + "y", "v3", S.EN_V3, fmax)
    # the spectrum, through the ADC's derived tracking pole
    N.noise_total(p, nm + "d", 1e9, "all", ppd=15); d = S.load(nm + "d", "n"); f, Sd = d[:, 0], d[:, 1]
    fp = 1 / (2 * np.pi * 3.8e3 * 6e-12)
    thru = float(np.sqrt(np.trapezoid(Sd ** 2 / (1 + (f / fp) ** 2), f)))
    dens = {f"{x:.0e}": float(np.interp(x, f, Sd) * 1e9) for x in (1e3, 1e5, 1e6, 1e7)}
    return (tag, dict(fmax=fmax, all=a, res=r, amp=m, cur=max(a*a - r*r - m*m, 0) ** .5, vmid=vm, v3=v3,
                      total=float(np.sqrt(a*a + vm*vm + v3*v3)), thru_adc_pole=float(np.sqrt(thru**2 + vm*vm + v3*v3)), density_nV=dens))

def pins(p, vins, nm):
    pin, out = S.dc_pins(p, vins, nm); return pin, out

def j_dc(args):
    """One-at-a-time worst case (as sim/scope): R1, R2, R3 +/-0.1 %, centring +/-30 mV (Vmid and the 3.3 V sense
    move together), Vos +/-0.2 mV (OPA365 max), rail 3.23/3.37 V.  +/-6 V on the divider (SC-2) and +/-1.25 V
    against the gain-4 window 3/8..5/8 AREF (R1)."""
    aref, r2 = args; nm = f"dc_{aref:.2f}_{r2/1e3:.0f}"
    base = pp(aref=aref, R2=r2, vmid=None, v3=None)
    def met(q):
        p6, o6 = pins(q, [-6.0, 0.0, 6.0], nm); p1, o1 = pins(q, [-1.25, 0.0, 1.25], nm)   # dc_pins needs equal steps
        pn = [p6[0], p1[0], p6[1], p1[2], p6[2]]; out = [o6[0], o1[0], o6[1], o1[2], o6[2]]
        a = q["aref"]
        return dict(m5_hi=a - pn[4], m5_lo=pn[0], w_hi=WIN[1] * a - pn[3], w_lo=pn[1] - WIN[0] * a,
                    g=(pn[3] - pn[1]) / 2.5, mid=pn[2] - a / 2, out_hi=out[4], pin=list(map(float, pn)))
    nom = met(base); worst = {k: 0.0 for k in ("m5_hi", "m5_lo", "w_hi", "w_lo")}; gmin = gmax = nom["g"]; mids = [nom["mid"]]
    for k in ("R1", "R2", "R3"):
        for sg in (+1, -1):
            q = dict(base); q[k] = base[k] * (1 + sg * TOL); m = met(q)
            for kk in worst: worst[kk] += 0
            gmin = min(gmin, m["g"]); gmax = max(gmax, m["g"])
    deltas = {}
    pert = []
    for k in ("R1", "R2", "R3"):
        pert.append((k, [dict(base, **{k: base[k] * (1 + s * TOL)}) for s in (+1, -1)]))
    pert.append(("cent", [dict(base, vmid=aref / 2 + s * CENT, v3=aref + 2 * s * CENT) for s in (+1, -1)]))
    pert.append(("vos", [dict(base, vos=s * 0.2e-3) for s in (+1, -1)]))
    pert.append(("vcc", [dict(base, vcc=v) for v in (3.23, 3.37)]))
    wc = {k: nom[k] for k in worst}; gl, gh = nom["g"], nom["g"]
    for name, qs in pert:
        ms = [met(q) for q in qs]
        for k in wc:
            wc[k] += min(0.0, min(m[k] - nom[k] for m in ms))
        gl += min(0.0, min(m["g"] - nom["g"] for m in ms)); gh += max(0.0, max(m["g"] - nom["g"] for m in ms))
        deltas[name] = {k: [m[k] - nom[k] for m in ms] for k in ("m5_hi", "m5_lo", "w_hi", "w_lo")}
    return (f"dc|{aref:.2f}|{r2/1e3:.0f}", dict(nominal=nom, worst=wc, gain_min=gl, gain_max=gh, deltas=deltas))

def j_kick(args):
    tag, kw, adc_name, va, vb = args; p = pp(**kw); nm = "k_" + re.sub(r"[^A-Za-z0-9]", "_", tag)
    adc = S.ADC_DERIVED if adc_name == "derived" else S.ADC_STRESS
    r = S.kick_run(p, va, vb, adc, name=nm, aref=3.2)
    return (tag, r)

def j_zout(args):
    tag, kw = args; p = pp(**kw); return (tag, S.zout_pin(p, name="z_" + re.sub(r"[^A-Za-z0-9]", "_", tag)))

def j_zin(args):
    tag, kw = args; p = pp(**kw); nm = "zi_" + re.sub(r"[^A-Za-z0-9]", "_", tag)
    txt = N.header(p, nm) + N.rails(p) + "Vs in 0 dc 0 ac 1\n" + N.core(p) + f"\n.control\nac dec 20 1k 10meg\nwrdata {N.wr(nm,'i')} i(Vs)\n.endc\n.end\n"
    N.run_ng(nm, txt); d = S.load(nm, "i"); f = d[:, 0]; Y = -(d[:, 1] + 1j * d[:, 2])
    return (tag, dict(R_dc=float(1 / Y[0].real), C_1MHz_pF=float(np.interp(1e6, f, Y.imag) / (2 * np.pi * 1e6) * 1e12)))

def j_prot(args):
    state, vin = args; p = pp(); nm = f"pr_{state}_{vin:+.0f}".replace("+", "p").replace("-", "m").replace(".", "_")
    return (f"prot|{state}|{vin:+.0f}", S.prot_dc(p, vin, state, name=nm))

def j_pedge(args):
    vin, tr = args; q = pp(); nm = f"pe_{'p' if vin > 0 else 'm'}{abs(vin):.0f}_{tr*1e9:.0f}"
    txt = N.header(q, nm) + N.rails(q, vcc=3.37) + f"Vs src 0 dc 0 pulse(0 {vin} 50n {tr} {tr} 3u 10u)\nRs src in 50\n" + N.core(q) + f"""
.control
tran 0.05n 1.5u 0 0.05n
wrdata {N.wr(nm,'p')} v(pin)
wrdata {N.wr(nm,'i')} i(Vos)
wrdata {N.wr(nm,'r')} v(vccl)
.endc
.end
"""
    N.run_ng(nm, txt); g = lambda k: S.load(nm, k)[:, 1]
    pn, ii, rr = g("p"), g("i"), g("r")
    return (f"pedge|{vin:+.0f}|{tr*1e9:.0f}", dict(pin_min=float(pn.min()), pin_max=float(pn.max()), i_clamp_peak_mA=float(np.abs(ii).max() * 1e3),
                                                     rail_max=float(rr.max())))

def j_edge(args):
    tag, kw, vs, tr = args; p = pp(**kw)
    return (tag, S.step_response(p, "ed_" + re.sub(r"[^A-Za-z0-9]", "_", tag), vs, tr, tstop=2.5e-6))

def j_loop(args):
    tag, kw = args
    try:
        return (tag, L.simulate(tag, **kw))
    except Exception as e:
        return (tag, dict(error=str(e)[-1200:]))

def pool(fn, jobs):
    out = {}
    with ProcessPoolExecutor(max_workers=W) as ex:
        for k, v in ex.map(fn, jobs):
            out[k] = v
    return out

# ------------------------------------------------------------------ sections
def sec_c2(R):
    jobs = [(csw, c2 * 1e-12) for csw in (0.0, CSW) for c2 in np.arange(26.0, 40.01, 1.0)]
    r = pool(j_c2, jobs); R["c2_sweep"] = r
    nulls = {}
    for csw in (0.0, CSW):
        xs = np.arange(26.0, 40.01, 1.0); ys = np.array([r[f"c2|{csw*1e12:.0f}|{x:.2f}"]["shelf_1M"] for x in xs])
        k = np.where(np.diff(np.sign(ys)))[0][0]
        x0 = xs[k] - ys[k] * (xs[k+1] - xs[k]) / (ys[k+1] - ys[k])
        nulls[f"{csw*1e12:.0f}"] = dict(c2_null_pF=float(x0), shelf_pct_per_pF=float((ys[k+1] - ys[k]) * 100))
    R["c2_null"] = nulls
    ideal = BASE["C1"] * BASE["R1"] / (BASE["R2"] * BASE["R3"] / (BASE["R2"] + BASE["R3"]))
    R["c2_ideal_total_pF"] = ideal * 1e12

def c2_nom(R):
    return R["c2_null"][f"{CSW*1e12:.0f}"]["c2_null_pF"] * 1e-12

def sec_ac(R):
    c2 = c2_nom(R); sh_d = (3.8e3, 6e-12); sh_s = (1.0e3, 8e-12)
    jobs = []
    for c1s in (0.95, 1.0, 1.05):
        for c2s in (0.95, 1.0, 1.05):
            for cpin in (2e-12, 4.7e-12):
                for riso in (10.0, 22.0, 50.0):
                    for sh in (("d", sh_d), ("s", sh_s)):
                        for cpo in (0.0, 3e-12):
                            tag = f"ac|{c1s}|{c2s}|{cpin*1e12:.1f}|{riso:.0f}|{sh[0]}|{cpo*1e12:.0f}"
                            jobs.append((tag, dict(C1=12e-12 * c1s, C2=c2 * c2s, Cpin=cpin, Riso=riso, sh=sh[1], Cpar_out=cpo)))
    r = pool(j_ac, jobs); R["ac"] = r
    nomk = f"ac|1.0|1.0|2.0|22|d|0"
    R["ac_nominal"] = r[nomk]
    vals = list(r.values())
    R["ac_worst"] = dict(bw10k=min(v["bw10k"] for v in vals), bw1k=min(v["bw1k"] for v in vals), bw100=min(v["bw100"] for v in vals),
                         pm=min(v["pm"] for v in vals if v["pm"] is not None), peak_db=max(v["peak_db"] for v in vals), n=len(vals))
    # Riso 0, 10 pF at the pin (stress), and the PGA's unknown input C bounded by Ci 8 pF all at the S/H
    R["ac_stress"] = dict(pool(j_ac, [("noriso_10p", dict(C2=c2, Riso=0.01, Cpin=10e-12, sh=sh_s)),
                                      ("cpo10", dict(C2=c2, Cpar_out=10e-12, sh=sh_d))]))
    # input impedance (SC-3)
    R["zin"] = pool(j_zin, [("nom", dict(C2=c2)), ("c1hi_c2hi", dict(C2=c2 * 1.05, C1=12.6e-12, Cwire=5e-12))])

def sec_noise(R):
    c2 = c2_nom(R); bw = R["ac_nominal"]["bw10k"]
    jobs = [("bw", dict(C2=c2), bw), ("1p5bw", dict(C2=c2), 1.5 * bw), ("10M", dict(C2=c2), 10e6),
            ("x10_1p5bw", dict(C2=c2, en_extra=45e-9), 1.5 * bw)]      # guard: a buffer 10x noisier than OPA365's 4.5 nV
    R["noise"] = pool(j_noise, jobs)

def sec_dc(R):
    jobs = [(a, 330e3) for a in AREFS] + [(3.20, 340e3), (3.20, 360e3)]      # 360k: guard (alpha up), must fail the window
    R["dc"] = pool(j_dc, jobs)

def sec_kick(R):
    c2 = c2_nom(R); jobs = []
    for adc in ("derived", "stress"):
        for riso in (10.0, 22.0, 50.0):
            jobs.append((f"full6|{adc}|{riso:.0f}", dict(C2=c2, Riso=riso), adc, 6.0, -6.0))
            jobs.append((f"x6hi|{adc}|{riso:.0f}", dict(C2=c2, Riso=riso), adc, 6.0, 0.0))
            jobs.append((f"x6lo|{adc}|{riso:.0f}", dict(C2=c2, Riso=riso), adc, -6.0, 0.0))
            jobs.append((f"full125|{adc}|{riso:.0f}", dict(C2=c2, Riso=riso), adc, 1.25, -1.25))
    jobs.append(("guard_riso20k|derived|20000", dict(C2=c2, Riso=20e3), "derived", 6.0, -6.0))
    R["kick"] = pool(j_kick, jobs)
    R["zout"] = pool(j_zout, [("nom", dict(C2=c2)), ("riso50", dict(C2=c2, Riso=50.0))])

def sec_prot(R):
    jobs = [(st, v) for st in ("powered", "unpowered", "floating_4700") for v in (30.0, -30.0)]
    R["prot"] = pool(j_prot, jobs)
    R["pedge"] = pool(j_pedge, [(v, tr) for v in (30.0, -30.0) for tr in (5e-9, 42e-9)])
    c2 = c2_nom(R)
    R["edge"] = pool(j_edge, [("5_42", dict(C2=c2), 2.0, 42e-9), ("5_5", dict(C2=c2), 2.0, 5e-9)])

def sec_loop(R):
    """SM-5 shelf.  The scope is the R1 buffer (or, as the harness control, the gain-4.83 stage of sim/loop's routes);
    the AWG is ideal (sim/loop convention) so the scope's share is alone.  ISI normalised = worst/G - base, G the
    spacing ratio; an ideal PGA multiplies the pin by 4 and leaves the normalised figure unchanged."""
    L.dac_for("derived")
    c2n = c2_nom(R) * 1e12
    sc = lambda **k: {**dict(op="OPA365", sw="buf", R1=760e3, R2=330e3, R3=760e3, C1=12e-12, Csw=CSW), **k}
    J = [("base", dict(baseline=True))]
    grid = np.round(np.arange(c2n - 2.0, c2n + 2.01, 0.5), 2)
    for c2 in grid:
        J.append((f"buf_C2_{c2:.2f}", dict(awg=dict(ideal=True), scope=sc(C2=c2 * 1e-12))))
    for c1s, c2s in ((1.05, 0.95), (0.95, 1.05), (1.01, 0.99), (0.99, 1.01), (1.02, 0.98), (0.98, 1.02)):
        J.append((f"buf_C1x{c1s}_C2x{c2s}", dict(awg=dict(ideal=True), scope=sc(C1=12e-12 * c1s, C2=c2n * 1e-12 * c2s))))
    # harness control: sim/loop's own R760 OPA365 gain-4.83 route, C2 33 and 34 pF (its table: 2.2 and 8.3 codes at the pin)
    for c2 in (33.0, 34.0):
        J.append((f"ctl_g483_C2_{c2:.0f}", dict(awg=dict(ideal=True), scope=dict(op="OPA365", sw="rf", rng="1.25", R1=760e3, R3=760e3,
                                                                                  R2=335e3, C1=12e-12, C2=c2 * 1e-12, Csw=0.0))))
    # guard: C1 removed must fail SM-5
    J.append(("guard_noC1", dict(awg=dict(ideal=True), scope=sc(C1=1e-15, C2=c2n * 1e-12))))
    R["loop"] = pool(j_loop, J)

def main(want):
    R = json.load(open(OUT)) if os.path.exists(OUT) else {}
    t0 = time.time()
    for name, fn in (("c2", sec_c2), ("ac", sec_ac), ("noise", sec_noise), ("dc", sec_dc), ("kick", sec_kick),
                     ("prot", sec_prot), ("loop", sec_loop)):
        if "all" in want or name in want:
            fn(R); print(name, f"{time.time()-t0:.0f} s", flush=True)
            json.dump(R, open(OUT, "w"), indent=1, default=float)

if __name__ == "__main__":
    main(sys.argv[1:] or ["all"])
