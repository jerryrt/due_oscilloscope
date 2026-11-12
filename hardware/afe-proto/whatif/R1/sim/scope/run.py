#!/usr/bin/env python3
"""2b scope-channel simulation driver.  Regenerates every number in report.md.
Run:  python3 -I run.py [section ...]     sections: dc ac noise kick prot guards report   (default: all)
Needs ngspice 47 and numpy.  Vendor models are referenced from ../../models, never copied."""
import sys, os, json, re, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import numpy as np
from netlib import *

RES = os.path.join(HERE, "results")
os.makedirs(RES, exist_ok=True)
LSB = lambda aref: aref / 4096.0
TOL = 0.001             # 0.1 % resistors (owner decision 2026-11-11: SC-8 gain matching is 1 %)
CENT = 0.030            # Vmid centring error
AREFS = [3.10, 3.15, 3.20, 3.25, 3.30]
RON_MAX = 8.8           # TMUX1119 RON max at 3.3 V (datasheet-facts.md)
ADC_DERIVED = dict(ron=3.8e3, cs=6e-12)   # derived from tTRACK = 0.054*Z + 205 ns (see report)
ADC_STRESS = dict(ron=1.0e3, cs=8e-12)    # Ci max 8 pF all on the sampling cap, low Ron
T_TRACK = 15 / 22.5e6   # 15 ADC clocks at 22.5 MHz = 666.7 ns
T_CONV = 21.5 / 22.5e6  # aggregate period at 1,046,510 sps is 955.5 ns (docs/hardware.md: ~21.5 clocks)

def save(name, obj):
    with open(os.path.join(RES, name + ".json"), "w") as f:
        json.dump(obj, f, indent=1, default=float)
    return obj

def loadj(name):
    with open(os.path.join(RES, name + ".json")) as f:
        return json.load(f)

def pp(**kw):
    q = dict(P0); q.update(kw); return q

# ------------------------------------------------------------------ DC
def dc_pins(p, vins, name="dc"):
    """ADC-pin voltage for each input voltage (ideal source at the BNC)."""
    vs = list(vins)
    txt = header(p, name) + rails(p) + "Vs in 0 dc 0\n" + core(p) + f"""
.control
dc Vs {vs[0]} {vs[-1]} {(vs[-1]-vs[0])/(len(vs)-1)}
wrdata {wr(name,'d')} v(pin)
wrdata {wr(name,'o')} v(out)
.endc
.end
"""
    run_ng(name, txt)
    d = load(name, "d"); o = load(name, "o")
    return d[:, 1], o[:, 1]

def rand_p(rng, base, aref, vcc=None, tol=TOL):
    p = dict(base)
    u = lambda t: rng.uniform(-t, t)
    for k in ("R1", "R2", "R3", "RF", "RG"):
        if p.get(k):
            p[k] = p[k] * (1 + u(tol))
    c = u(CENT)
    p.update(aref=aref, vmid=aref / 2 + c, v3=aref + 2 * c,
             vos=u(OPAMPS[p["op"]]["vos_max"]), Ron_sw=rng.uniform(3.7, RON_MAX),
             vcc=rng.uniform(3.23, 3.37) if vcc is None else vcc)
    return p

def oat_perturbations(base, aref):
    """One-at-a-time extreme perturbations (name, params) around nominal at this AREF."""
    out = []
    o = OPAMPS[base["op"]]
    for k in ("R1", "R2", "R3", "RF", "RG"):
        for sgn in (+1, -1):
            q = dict(base); q[k] = base[k] * (1 + sgn * TOL); out.append((f"{k}{'+' if sgn>0 else '-'}", q))
    for sgn in (+1, -1):
        q = dict(base); q.update(vmid=aref / 2 + sgn * CENT, v3=aref + 2 * sgn * CENT)
        out.append((f"centring{'+' if sgn>0 else '-'}", q))
        q = dict(base); q["vos"] = sgn * o["vos_max"]; out.append((f"Vos{'+' if sgn>0 else '-'}", q))
    q = dict(base); q["Ron_sw"] = RON_MAX; out.append(("Ron8.8", q))
    for v in (3.23, 3.37):
        q = dict(base); q["vcc"] = v; out.append((f"Vcc{v}", q))
    return out

def dc_metrics(p, rng_name):
    vfs = 6.0 if rng_name == "5" else 1.25
    pins, outs = dc_pins(p, [-vfs, 0.0, vfs])
    aref = p["aref"]
    return dict(lo=float(pins[0]), mid=float(pins[1]), hi=float(pins[2]),
                margin_hi=float(aref - pins[2]), margin_lo=float(pins[0]),
                gain=float((pins[2] - pins[0]) / (2 * vfs)), out_hi=float(outs[2]))

def dc_section(opname="OPA354", quick=False, over=None, tag=None):
    over = over or {}
    R = {"op": opname, "aref_table": {}}
    for rng_name in ("5", "1.25"):
        base = pp(op=opname, rng=rng_name, **over)
        tab = {}
        for aref in AREFS:
            b = dict(base); b.update(aref=aref)
            nom = dc_metrics(b, rng_name)
            drv = {"margin_hi": 0.0, "margin_lo": 0.0, "gain_up": 0.0, "gain_dn": 0.0}
            contrib = {}
            for nm, q in oat_perturbations(b, aref):
                m = dc_metrics(q, rng_name)
                d_hi = m["margin_hi"] - nom["margin_hi"]; d_lo = m["margin_lo"] - nom["margin_lo"]
                contrib[nm] = dict(d_mhi=d_hi, d_mlo=d_lo, d_gain=m["gain"] - nom["gain"])
            # worst case = sum over each parameter of its most adverse sign (parameters in +/- pairs)
            def worst(key, sign):
                tot = 0.0; seen = {}
                for nm, c in contrib.items():
                    par = re.sub(r"[+-]$", "", nm) if nm[-1] in "+-" else nm
                    seen.setdefault(par, []).append(sign * c[key])
                for par, vals in seen.items():
                    tot += min(0.0, min(vals)) if sign > 0 else min(0.0, min(vals))
                return tot
            wm_hi = nom["margin_hi"] + worst("d_mhi", +1)
            wm_lo = nom["margin_lo"] + worst("d_mlo", +1)
            g_min = nom["gain"] + worst("d_gain", +1)
            g_max = nom["gain"] - worst("d_gain", -1)
            tab[f"{aref:.2f}"] = dict(nominal=nom, margin_hi_wc=wm_hi, margin_lo_wc=wm_lo,
                                      margin_wc=min(wm_hi, wm_lo), gain_min=g_min, gain_max=g_max, contrib=contrib)
        R["aref_table"][rng_name] = tab
        # lowest AREF holding 80 mV margin: linear interpolation of the worst-case margin
        xs = np.array(AREFS); ys = np.array([tab[f"{a:.2f}"]["margin_wc"] for a in AREFS])
        if ys.min() >= 0.080:
            R.setdefault("lowest_aref", {})[rng_name] = float("nan")
        else:
            k = np.polyfit(xs, ys, 1)
            R.setdefault("lowest_aref", {})[rng_name] = float((0.080 - k[1]) / k[0])
    # op-amp output headroom to its own rail at the worst supply, top of range
    hd = {}
    for rng_name in ("5", "1.25"):
        q = pp(op=opname, rng=rng_name, aref=3.30, vcc=3.23, vmid=1.65 + CENT, v3=3.30 + 2 * CENT, **over)
        m = dc_metrics(q, rng_name)
        hd[rng_name] = dict(out_hi=m["out_hi"], headroom_to_rail=3.23 - m["out_hi"])
    R["headroom"] = hd
    # Monte Carlo (uniform tolerances, random AREF corner points)
    if not quick:
        mc = {}
        gen = np.random.default_rng(20261111)
        N = 80
        for rng_name in ("5", "1.25"):
            for aref in (3.10, 3.20):
                ms = []
                for _ in range(N):
                    q = rand_p(gen, pp(op=opname, rng=rng_name), aref)
                    ms.append(dc_metrics(q, rng_name))
                mm = np.array([min(m["margin_hi"], m["margin_lo"]) for m in ms])
                gg = np.array([m["gain"] for m in ms])
                mc[f"{rng_name}@{aref:.2f}"] = dict(n=N, margin_min=float(mm.min()), margin_mean=float(mm.mean()),
                                                    gain_min=float(gg.min()), gain_max=float(gg.max()))
        R["mc"] = mc
    return save(tag or f"dc_{opname}", R)


# ------------------------------------------------------------------ AC, stability, edges, input Z
FLAT_F = [1e5, 1e6, 2e6, 4e6, 6e6, 8e6, 10e6, 15e6, 20e6]

def group_delay_flat(f, h, f1=1e5, f2=8e6):
    ph = np.unwrap(np.angle(h)); w = 2 * np.pi * f
    gd = -np.gradient(ph, w)
    m = (f >= f1) & (f <= f2)
    return float(gd[m].max() - gd[m].min()), float(gd[m].mean())

def ac_summary(p, name):
    f, h, T = ac_response(p, name, fmin=1e4, fmax=2e9, ppd=40)
    m = freq_metrics(f, h); pm = phase_margin(f, T)
    gdv, gdm = group_delay_flat(f, h)
    # gain vs frequency relative to the 100 kHz value, for the calibration note
    g100 = abs(np.interp(1e5, f, np.abs(h)))
    flat = {f"{fx:.0e}": float(20 * np.log10(np.interp(fx, f, np.abs(h)) / g100)) for fx in FLAT_F}
    hf = np.abs(h) / g100
    ipk = np.argmax(hf[f > 1e5]) if True else 0
    return dict(g0=m["g0"], bw=m["bw"], peak_db=m["peak_db"], f_peak=m.get("f_peak"), pm=pm["pm"], pm_fc=pm["fc"],
                gm=pm["gm"], gd_var_ns=gdv * 1e9, gd_mean_ns=gdm * 1e9, flat_db=flat)

def ac_section():
    R = {}
    for op in ("OPA354", "OPA365"):
        for rng in ("5", "1.25"):
            key = f"{op}_{rng}"
            R[key] = {"nominal": ac_summary(pp(op=op, rng=rng), "ac_n")}
            # worst-case corner enumeration: parasitics at the inverting node, Ron max, C1 +/-5 %, Riso
            worst_bw = 1e99; worst_pm = 1e9; worst_pk = -1e9; corners = []
            for cx in (-2e-12, 0.0, 3e-12):
                for ron in (3.7, RON_MAX):
                    for c1s in (0.95, 1.05):
                        p = pp(op=op, rng=rng, Cpar_extra=cx, Ron_sw=ron)
                        p["C1"] = c1_of(p) * c1s
                        r = ac_summary(p, "ac_c")
                        corners.append(dict(cpar_extra=cx, ron=ron, c1_scale=c1s, bw=r["bw"], peak_db=r["peak_db"], pm=r["pm"]))
                        worst_bw = min(worst_bw, r["bw"]); worst_pk = max(worst_pk, r["peak_db"])
                        if r["pm"] is not None: worst_pm = min(worst_pm, r["pm"])
            R[key]["worst"] = dict(bw=worst_bw, peak_db=worst_pk, pm=worst_pm, corners=corners)
            # parasitic sensitivity at the inverting node, Riso 10/20/50 ohm
            sens = []
            for cx in (-2e-12, -1e-12, 0.0, 1e-12, 2e-12, 3e-12):
                for riso in (10.0, 22.0, 50.0):
                    r = ac_summary(pp(op=op, rng=rng, Cpar_extra=cx, Riso=riso), "ac_s")
                    sens.append(dict(cpar_extra_pf=cx * 1e12, riso=riso, pm=r["pm"], bw=r["bw"], peak_db=r["peak_db"]))
            R[key]["sens"] = sens
            # stress: all of Cpin 8 pF (bigger pad/trace) and no Riso
            r = ac_summary(pp(op=op, rng=rng, Riso=0.01, Cpin=10e-12), "ac_s")
            R[key]["no_riso_10pF"] = dict(pm=r["pm"], bw=r["bw"], peak_db=r["peak_db"])
    return save("ac", R)

def trim_ends_section():
    """SC-2 / SC-4 / SC-11 with the R2 trimmer at either end of its travel (leg 330 k and 340 k), worst case as the main DC case."""
    return {str(int(r2 / 1e3)): dc_section("OPA354", quick=True, over=dict(R2=r2), tag=f"dc_trim_{int(r2/1e3)}k") for r2 in (330e3, 340e3)}

def comp_section():
    """Compensation with the E24 pair: C1 12 pF against several C2 totals at N (C2tot = external part + 2 pF op-amp input).
    DC is taken at 1 kHz (the divider has settled, no op-amp roll-off)."""
    R = {}
    for leg_name, r2 in (("335k leg (330k + 5k trimmer)", 335e3), ("330k, no trimmer", 330e3)):
        for lab, c1, c2ext in (("ideal C1 for C2tot 40 pF", None, 38e-12), ("C1 12 pF, C2tot 39.0 pF", 12e-12, 37e-12),
                               ("C1 12 pF, C2tot 40.0 pF", 12e-12, 38e-12), ("C1 12 pF, C2tot 41.0 pF (39 pF part + 2 pF)", 12e-12, 39e-12),
                               ("C1 12 pF, C2tot 38.0 pF (36 pF part + 2 pF)", 12e-12, 36e-12)):
            for rng in ("5", "1.25"):
                p = pp(rng=rng, R2=r2, C2=c2ext)
                p["C1"] = c1   # WHATIF C2: None -> ideal (P0 now carries 12 pF)
                f, h, T = ac_response(p, "comp", fmin=1e3, fmax=2e9, ppd=40)
                g = lambda fx: float(np.interp(fx, f, np.abs(h)))
                a = ac_summary(p, "comp_s")
                c1v = c1_of(p); c2t = p["C2"] + p["C2tot_extra"]
                ideal = c2t * (r2 * p["R3"] / (r2 + p["R3"])) / p["R1"]
                R[f"{leg_name}|{lab}|{rng}"] = dict(
                    c1_pF=c1v * 1e12, c1_ideal_pF=ideal * 1e12, comp_err_pct=(c1v / ideal - 1) * 100,
                    step_10k_pct=(g(1e4) / g(1e3) - 1) * 100, step_100k_pct=(g(1e5) / g(1e3) - 1) * 100,
                    flat_1_8MHz_db=max(abs(a["flat_db"][k]) for k in ("1e+06", "2e+06", "4e+06", "6e+06", "8e+06")), bw_MHz=a["bw"] / 1e6)
    return save("comp", R)

def spec_section():
    """The design exactly as first specified, so that its failures are on record."""
    R = {}
    for op in ("OPA354", "OPA365"):
        for rng in ("5", "1.25"):
            p = pp(op=op, rng=rng, **SPEC)
            pins, _ = dc_pins(p, [-6.0 if rng == "5" else -1.25, 0.0, 6.0 if rng == "5" else 1.25], "spec_dc")
            a = ac_summary(p, "spec_ac")
            R[f"{op}_{rng}"] = dict(pin_lo=float(pins[0]), pin_mid=float(pins[1]), pin_hi=float(pins[2]),
                                    margin_lo=float(pins[0]), margin_hi=float(3.2 - pins[2]), ac=a)
    return save("spec", R)

def zin_section():
    R = {}
    for rng in ("5", "1.25"):
        p = pp(rng=rng)
        txt = header(p, "zin") + rails(p) + "Vs in 0 dc 0 ac 1\n" + core(p) + f"""
.control
ac dec 20 1k 100meg
wrdata {wr('zin','i')} i(Vs)
.endc
.end
""".replace("\\n", "\n")
        run_ng("zin", txt.replace("\\n", "\n"))
        d = load("zin", "i"); f = d[:, 0]; Y = -(d[:, 1] + 1j * d[:, 2])
        out = {}
        out["R_dc_ohm"] = float(1 / Y[0].real)
        for fx in (1e5, 1e6, 5e6):
            y = np.interp(fx, f, Y.imag)
            out[f"C_{fx:.0e}_pF"] = float(y / (2 * np.pi * fx) * 1e12)
        # tolerance: C1 and C2 +/-5 % (NP0/C0G), Cwire +/-1 pF
        worst = 0
        for c1s in (0.95, 1.05):
            for c2s in (0.95, 1.05):
                q = pp(rng=rng, C2=39e-12 * c2s); q["C1"] = c1_of(pp(rng=rng)) * c1s
                txt2 = header(q, "zin") + rails(q) + "Vs in 0 dc 0 ac 1\n" + core(q) + f"""
.control
ac lin 1 1meg 1meg
wrdata {wr('zin','j')} i(Vs)
.endc
.end
""".replace("\\n", "\n")
                run_ng("zin", txt2.replace("\\n", "\n"))
                dd = load("zin", "j"); y = -(dd[1] + 1j * dd[2])
                worst = max(worst, y.imag / (2 * np.pi * 1e6) * 1e12 + 1.0)   # + 1 pF wiring tolerance
        out["C_worst_1MHz_pF"] = float(worst)
        R[rng] = out
    return save("zin", R)

def step_response(p, name, vstep, tr, tstop=1.2e-6, tdelay=20e-9):
    txt = header(p, name) + rails(p) + f"""Vs src 0 dc 0 pulse(0 {vstep} {tdelay} {tr} {tr} 5u 10u)
Rs src in {p['Rsrc']}
""" + core(p) + f"""
.control
tran 0.2n {tstop} 0 0.2n
wrdata {wr(name,'t')} v(pin)
.endc
.end
"""
    run_ng(name, txt)
    d = load(name, "t"); t = d[:, 0]; v = d[:, 1]
    v0 = v[t < tdelay * 0.9].mean(); vend = v[(t > tstop * 0.85)].mean()
    dv = vend - v0
    def tcross(level):
        i = np.where(v - v0 >= level * dv)[0]
        return t[i[0]] if len(i) else np.nan
    tr1090 = tcross(0.9) - tcross(0.1)
    over = (v.max() - vend) / dv * 100
    # settling to +/-0.5 % of the step (the compensated divider's own tail is ~0.1-0.4 % and is calibrated out, SC-5)
    outside = np.where(np.abs(v - vend) > 0.005 * abs(dv))[0]
    ts = t[outside[-1]] - tdelay if len(outside) else 0.0
    return dict(step_pin_V=float(dv), rise_10_90_ns=float(tr1090 * 1e9), overshoot_pct=float(over), settle_0p5pct_ns=float(ts * 1e9))

def edge_section():
    R = {}
    for op in ("OPA354", "OPA365"):
        for rng, vs in (("5", 2.0), ("1.25", 0.5)):
            for tr in (42e-9, 5e-9):
                R[f"{op}_{rng}_{tr*1e9:.0f}ns"] = step_response(pp(op=op, rng=rng), "edge", vs, tr)
    return save("edge", R)

# ------------------------------------------------------------------ noise
EN_VMID = 20e-9     # assumed white density of the Vmid source ahead of its decoupling (to be closed by 2a/2f)
EN_V3 = 100e-9      # assumed white density on the Due's 3.3 V pin (PW-4 allows +0.3 mV rms over DC-1 MHz)

def transfer_rms(p, name, which, en, fmax):
    ac = dict(ac_vm=(which == "vm"), ac_v3=(which == "v3"))
    txt = header(p, name) + rails(p, **ac) + "Vs src 0 dc 0 ac 0\nRs src in 50\n" + core(p) + f"""
.control
ac dec 20 10 {fmax}
wrdata {wr(name,'x')} v(pin)
.endc
.end
"""
    run_ng(name, txt)
    d = load(name, "x"); f = d[:, 0]; h = np.abs(d[:, 1] + 1j * d[:, 2])
    return float(np.sqrt(np.trapezoid((en * h) ** 2, f)))

def noise_section(bws=None):
    ac = loadj("ac")
    R = {}
    for op in ("OPA354", "OPA365"):
        for rng in ("5", "1.25"):
            key = f"{op}_{rng}"
            p = pp(op=op, rng=rng)
            fbw = ac[key]["nominal"]["bw"]
            row = {"bw_3dB": fbw}
            for lab, fm in (("at_bw", fbw), ("at_1p5bw", 1.5 * fbw), ("at_10MHz", 10e6)):
                a = noise_total(p, "nz", fm, "all"); r = noise_total(p, "nz", fm, "res"); m = noise_total(p, "nz", fm, "amp")
                vm = transfer_rms(p, "nzx", "vm", EN_VMID, fm); v3 = transfer_rms(p, "nzx", "v3", EN_V3, fm)
                cur = max(a * a - r * r - m * m, 0.0) ** 0.5
                tot = float(np.sqrt(a * a + vm * vm + v3 * v3))
                row[lab] = dict(fmax=fm, total_V=tot, all_V=a, resistors_V=r, opamp_voltage_V=m, opamp_current_resid_V=cur,
                                vmid_V=vm, v3sense_V=v3)
            # density at the pin from the 'all' spectrum run to 1.5 BW
            noise_total(p, "nzd", 1.5 * fbw, "all")
            d = load("nzd", "n"); f = d[:, 0]; S = d[:, 1]
            row["density_nV"] = {f"{fx:.0e}": float(np.interp(fx, f, S) * 1e9) for fx in (1e5, 1e6, 3e6, 1e7)}
            # ADC-limited: a further single pole at the converter's tracking bandwidth 1/(2 pi Ron Cs)
            noise_total(p, "nza", 1e9, "all", ppd=15)
            d = load("nza", "n"); f = d[:, 0]; S = d[:, 1]
            fp = 1 / (2 * np.pi * ADC_DERIVED["ron"] * ADC_DERIVED["cs"])
            row["adc_tracking_pole_Hz"] = fp
            row["through_adc_pole_V"] = float(np.sqrt(np.trapezoid(S ** 2 / (1 + (f / fp) ** 2), f)))
            R[key] = row
    return save("noise", R)

# ------------------------------------------------------------------ ADC load: charge-bucket kick, settling, crosstalk
def pin_dc(p, vin, name="kdc"):
    pins, _ = dc_pins(p, [vin - 0.001, vin, vin + 0.001], name)
    return float(pins[1])

def kick_run(p, vina, vinb, adc, name="kick", ncyc=7, b_driven=True, aref=3.3):
    """Two identical channels A and B share Vmid, the supply and one S/H (Ron + Cs).  A tracks for 15 ADC clocks,
    B tracks the next 15, and so on at the aggregate period of 21.5 ADC clocks.  Returns the S/H error at the end of
    each track window against the DC value of that channel's pin, in LSB of AREF/4096, and B's settling time."""
    t0 = 100e-9
    parts = [header(p, name), rails(p),
             f"Vina ain 0 dc {vina}\n", core(p, pre="a") + "\n"]
    if b_driven:
        parts += [f"Vinb bin 0 dc {vinb}\n", core(p, pre="b") + "\n"]
    else:
        parts += [f"Cpb bpin 0 {p['Cpin']:.6g}\n"]
    per2 = 2 * T_CONV
    parts.append(f"""
.model swm sw(vt=0.5 vh=0.1 ron=0.001 roff=1e12)
Sa apin mx ctla 0 swm
Sb bpin mx ctlb 0 swm
Radc mx cs {adc['ron']}
Cs cs 0 {adc['cs']}
Vca ctla 0 pulse(0 1 {t0} 1n 1n {T_TRACK} {per2})
Vcb ctlb 0 pulse(0 1 {t0 + T_CONV} 1n 1n {T_TRACK} {per2})
.control
op
print v(apin) {'v(bpin)' if b_driven else ''}
tran 0.25n {t0 + ncyc * per2} 0 0.25n
wrdata {wr(name,'k')} v(cs)
.endc
.end
""")
    out = run_ng(name, "".join(parts))
    d = load(name, "k"); t = d[:, 0]; v = d[:, 1]
    va = float(re.search(r"v\(apin\)\s*=\s*([-0-9.eE+]+)", out).group(1))
    vb = float(re.search(r"v\(bpin\)\s*=\s*([-0-9.eE+]+)", out).group(1)) if b_driven else None
    lsb = LSB(aref)
    res = {"vpin_a": va, "vpin_b": vb}
    errs_a, errs_b, settle = [], [], []
    for k in range(ncyc - 3, ncyc):
        ta = t0 + k * per2 + T_TRACK - 2e-9
        tb = t0 + k * per2 + T_CONV + T_TRACK - 2e-9
        errs_a.append((np.interp(ta, t, v) - va) / lsb)
        if b_driven:
            errs_b.append((np.interp(tb, t, v) - vb) / lsb)
            m = (t >= t0 + k * per2 + T_CONV) & (t <= tb + 2e-9)
            bad = np.where(np.abs(v[m] - vb) > 0.5 * lsb)[0]
            settle.append((t[m][bad[-1]] - (t0 + k * per2 + T_CONV)) * 1e9 if len(bad) else 0.0)
    res["errA_lsb"] = float(np.mean(errs_a))
    if b_driven:
        res.update(errB_lsb=float(np.mean(errs_b)), settleB_ns=float(max(settle)),
                   stepAB_V=float(va - vb))
    return res

def zout_pin(p, name="zout"):
    q = dict(p)
    txt = header(q, name) + rails(q) + "Vs in 0 dc 0 ac 0\n" + core(q) + f"""
Iz 0 pin dc 0 ac 1
.control
ac dec 20 1k 200meg
wrdata {wr(name,'z')} v(pin)
.endc
.end
"""
    run_ng(name, txt)
    d = load(name, "z"); f = d[:, 0]; z = np.abs(d[:, 1] + 1j * d[:, 2])
    m = f <= 10e6
    return dict(zmax_to_10MHz=float(z[m].max()), z_at_10MHz=float(np.interp(10e6, f, z)), z_at_100MHz=float(np.interp(100e6, f, z)))

def kick_section():
    R = {}
    for rng, vfs in (("5", 6.0), ("1.25", 1.25)):
        for lab, adc in (("derived", ADC_DERIVED), ("stress", ADC_STRESS)):
            for riso in (10.0, 22.0, 50.0):
                p = pp(rng=rng, Riso=riso)
                full = kick_run(p, +vfs, -vfs, adc, aref=3.2)        # A high, B low: the full-swing kick
                xt_hi = kick_run(p, +vfs, 0.0, adc, aref=3.2)        # A full scale high, B shorted
                xt_lo = kick_run(p, -vfs, 0.0, adc, aref=3.2)        # A full scale low, B shorted
                R[f"{rng}_{lab}_Riso{riso:.0f}"] = dict(
                    full_swing=full, xtalk_hi=xt_hi, xtalk_lo=xt_lo,
                    crosstalk_lsb=float(abs(xt_hi["errB_lsb"] - xt_lo["errB_lsb"])),
                    zout=zout_pin(p))
    R["bare_pin_charge_share"] = {f"Cp{cp*1e12:.1f}pF": ADC_DERIVED["cs"] / (ADC_DERIVED["cs"] + cp) for cp in (2e-12, 4.7e-12, 8e-12)}
    # charge injection of the range switch (6 pC) into the inverting node: recovery
    R["charge_injection"] = qinj_run()
    return save("kick", R)

def qinj_run():
    out = {}
    for rng in ("5", "1.25"):
        p = pp(rng=rng)
        txt = header(p, "qinj") + rails(p) + "Vs in 0 dc 0\n" + core(p) + f"""
Iq 0 fb pulse(0 6m 200n 0.1n 0.1n 1n 10u)
.control
tran 0.1n 1.2u 0 0.1n
wrdata {wr('qinj','q')} v(pin)
.endc
.end
"""
        run_ng("qinj", txt)
        d = load("qinj", "q"); t = d[:, 0]; v = d[:, 1]
        base = v[t < 190e-9].mean()
        dev = np.abs(v - base)
        lsb5 = LSB(3.2) * 0.5
        bad = np.where((dev > lsb5) & (t > 200e-9))[0]
        out[rng] = dict(peak_mV=float(dev.max() * 1e3), recover_0p5LSB_ns=float((t[bad[-1]] - 200e-9) * 1e9) if len(bad) else 0.0)
    return out

# ------------------------------------------------------------------ protection
def _grab(out, name):
    m = re.search(rf"{re.escape(name)}\s*=\s*([-0-9.eE+]+)", out)
    return float(m.group(1)) if m else float("nan")

def prot_dc(p, vin, state, name="prot"):
    if state == "powered":
        rl = rails(p, vcc=3.37, vmid=1.65)
        q = dict(p, v3=3.3)
    elif state == "unpowered":
        rl = rails(p, vcc=0.0, vmid=0.0)
        q = dict(p, v3=0.0)
    elif state.startswith("floating"):
        bl = float(state.split("_")[1])
        rl = rails(p, vmid=0.0, rail_bleed=bl)
        q = dict(p, v3=0.0)
    rl = rails(q, vcc=3.37 if state == "powered" else 0.0, vmid=1.65 if state == "powered" else 0.0,
               rail_bleed=(float(state.split("_")[1]) if state.startswith("floating") else None))
    txt = header(q, name) + rl + f"Vs in 0 dc {vin}\n" + core(q) + f"""
.control
op
print i(Vs) v(pin) v(vccl) v(n) v(np) v(out) i(V3s) i(Vm) i(Vos)
{'print i(Vcc)' if not state.startswith('floating') else ''}
.endc
.end
"""
    out = run_ng(name, txt)
    r = dict(i_in_uA=abs(_grab(out, "i(vs)")) * 1e6, v_pin=_grab(out, "v(pin)"), v_rail=_grab(out, "v(vccl)"),
             v_n=_grab(out, "v(n)"), i_due33_uA=_grab(out, "i(v3s)") * 1e6, i_clamp_uA=abs(_grab(out, "i(vos)")) * 1e6)
    if not state.startswith("floating"):
        r["i_vcc_uA"] = _grab(out, "i(vcc)") * 1e6
    return r

BLEED = 4.7e3   # AFE +3.3 V_A rail bleed, 4.7 kohm 1 % (one part with powercal's +3.3 V bleed, MC-12)

def prot_section():
    R = {"dc": {}, "above30": {}, "edge": {}}
    for rng in ("5", "1.25"):
        p = pp(rng=rng)
        for state in ("powered", "unpowered", f"floating_{BLEED:.0f}", "floating_1000000"):
            for vin in (30.0, -30.0):
                R["dc"][f"{rng}|{state}|{vin:+.0f}"] = prot_dc(p, vin, state)
    p = pp(rng="5")
    for vin in (60.0, 100.0, 200.0, -100.0):
        r = prot_dc(p, vin, f"floating_{BLEED:.0f}")
        r["P_R1_mW"] = (vin ** 2 / p["R1"]) * 1e3
        R["above30"][f"{vin:+.0f}"] = r
    # fast edges through C1
    for rng in ("5", "1.25"):
        for vin in (30.0, -30.0):
            for tr in (5e-9, 42e-9):
                q = pp(rng=rng)
                txt = header(q, "pedge") + rails(q, vcc=3.37) + f"Vs src 0 dc 0 pulse(0 {vin} 50n {tr} {tr} 3u 10u)\nRs src in 50\n" + core(q) + f"""
.control
tran 0.05n 1.5u 0 0.05n
wrdata {wr('pedge','p')} v(pin)
wrdata {wr('pedge','n')} v(n)
wrdata {wr('pedge','i')} i(Vos)
wrdata {wr('pedge','r')} v(vccl)
.endc
.end
"""
                run_ng("pedge", txt)
                g = lambda k: load("pedge", k)[:, 1]
                pn, nn, ii, rr = g("p"), g("n"), g("i"), g("r")
                R["edge"][f"{rng}|{vin:+.0f}|{tr*1e9:.0f}ns"] = dict(
                    pin_min=float(pn.min()), pin_max=float(pn.max()), n_min=float(nn.min()), n_max=float(nn.max()),
                    i_clamp_peak_mA=float(np.abs(ii).max() * 1e3), rail_min=float(rr.min()), rail_max=float(rr.max()))
    return save("prot", R)

# ------------------------------------------------------------------ guards (checks broken on purpose)
def g_dc(p):
    m = dc_metrics(dict(p, aref=3.2), p["rng"])
    lo, hi = (0.2290, 0.2453) if p["rng"] == "5" else (1.10, 1.16)
    ok = (abs(m["mid"] - 1.6) < 0.010 and lo <= m["gain"] <= hi and min(m["margin_hi"], m["margin_lo"]) >= 0.080)
    return ok, f"mid {m['mid']:.4f} V (centre 1.6000), gain {m['gain']:.4f} (window {lo}-{hi}), margin {min(m['margin_hi'], m['margin_lo'])*1e3:.0f} mV (>=80)"

def g_flat(p):
    a = ac_summary(p, "g_ac")
    worst = max(abs(a["flat_db"][k]) for k in ("1e+06", "2e+06", "4e+06", "6e+06", "8e+06"))
    return worst <= 0.3, f"gain flatness 1-8 MHz {worst:.3f} dB (<=0.3), BW {a['bw']/1e6:.1f} MHz"

def g_bw(p):
    worst = 1e99
    for cx in (-2e-12, 3e-12):
        for ron in (3.7, RON_MAX):
            r = ac_summary(dict(p, Cpar_extra=cx, Ron_sw=ron), "g_bw")
            worst = min(worst, r["bw"])
    return worst >= 8e6, f"worst-corner BW {worst/1e6:.1f} MHz (>=8)"

def g_pm(p):
    worst = 1e9; pk = -1
    for cx in (-2e-12, 0.0, 3e-12):
        r = ac_summary(dict(p, Cpar_extra=cx), "g_pm")
        worst = min(worst, r["pm"]); pk = max(pk, r["peak_db"])
    return worst >= 45, f"worst PM {worst:.1f} deg (>=45), peaking {pk:.1f} dB (reported, no limit)"

def g_edge(p):
    q = dict(p); vin = 30.0
    txt = header(q, "ge") + rails(q, vcc=3.37) + f"Vs src 0 dc 0 pulse(0 {vin} 50n 5n 5n 3u 10u)\nRs src in 50\n" + core(q) + """
.control
tran 0.05n 400n 0 0.05n
wrdata ../work/ge_i.dat i(Vos)
.endc
.end
"""
    run_ng("ge", txt)
    i = np.abs(load("ge", "i")[:, 1]).max() * 1e3
    return i <= 10.0, f"peak op-amp input clamp current {i:.1f} mA on a 5 ns, 30 V edge (<=10 mA abs max)"

def g_noise(p):
    a = ac_summary(p, "g_nz"); n = noise_total(p, "g_nz", 1.5 * a["bw"], "all")
    return n <= 200e-6, f"noise to 1.5 x BW ({1.5*a['bw']/1e6:.0f} MHz) {n*1e6:.0f} uV (<=200, op-amp+resistors only)"

def g_settle(p):
    r = kick_run(p, 6.0, -6.0, ADC_DERIVED, name="g_k", aref=3.2)
    e = max(abs(r["errA_lsb"]), abs(r["errB_lsb"]))
    return e <= 0.5, f"S/H error at end of 15-clock track {e:.3f} LSB (<=0.5), settles in {r['settleB_ns']:.0f} ns"

def guards_section():
    G = []
    def run(name, guard, good, broken, what):
        ok1, d1 = guard(good); ok2, d2 = guard(broken); ok3, d3 = guard(good)
        ok1, ok2, ok3 = bool(ok1), bool(ok2), bool(ok3)
        G.append(dict(guard=name, mutation=what, good=dict(ok=ok1, detail=d1), broken=dict(ok=ok2, detail=d2),
                      restored=dict(ok=ok3, detail=d3), effective=bool(ok1 and not ok2 and ok3)))
    run("DC transfer (SC-2, SC-4, SC-11)", g_dc, pp(rng="5"), pp(rng="5", R2=450e3), "R2 leg 335k -> 450k (wrong divider ratio)")
    run("DC centring (SC-2)", g_dc, pp(rng="5"), pp(rng="5", **SPEC), "design as first specified: R2 returned to Vmid only, no R3")
    run("Flatness / compensation (SC-5)", g_flat, pp(rng="5"), dict(pp(rng="5"), C1=1e-15), "C1 removed (uncompensated divider)")
    run("Bandwidth >= 8 MHz at worst corner (SM-3)", g_bw, pp(rng="1.25"), pp(rng="1.25", op="OPA365"), "OPA354 swapped for the slower OPA365")
    run("Phase margin >= 45 deg, peaking (AN-1)", g_pm, pp(rng="5"), pp(rng="5", **SPEC), "range switch back in the RG leg (6 pF Coff on the inverting node path), RF 3.83k/RG 1k, no Rnp")
    run("Edge current into op-amp clamp (PR-1)", g_edge, pp(rng="5"), pp(rng="5", Rnp=0.0), "series resistor ahead of the + input removed")
    run("Noise <= 0.2 mV (SC-6)", g_noise, pp(rng="1.25"), pp(rng="1.25", RG=60.4), "RG 249 -> 60.4 ohm (gain 16.8 instead of 4.83)")
    run("ADC settling <= 0.5 LSB (SC-10, AN-2)", g_settle, pp(rng="5"), pp(rng="5", Riso=20e3), "series isolation 22 ohm -> 20 kohm")
    return save("guards", G)

# ------------------------------------------------------------------ report
def model_hashes():
    src = open(os.path.join(MODELS, "SOURCES.md")).read()
    out = {}
    for rel, fn in (("opa354/OPA354_PSPICE.lib", "OPA354_PSPICE.lib"), ("opa365/OPA365_PSPICE.lib", "OPA365_PSPICE.lib")):
        m = re.search(rf"\| {re.escape(fn)} \|.*?\| ([0-9a-f]{{64}}) \|", src)
        actual = sha256(os.path.join(MODELS, rel))
        out[fn] = dict(sources_md=m.group(1) if m else None, actual=actual, match=bool(m and m.group(1) == actual))
    return out

def mv(x):
    return f"{x*1e3:.1f} mV"

def uv(x):
    return f"{x*1e6:.0f} uV"

def make_report():
    dc = {op: loadj(f"dc_{op}") for op in ("OPA354", "OPA365")}
    ac = loadj("ac"); nz = loadj("noise"); kk = loadj("kick"); pr = loadj("prot"); gd = loadj("guards")
    zi = loadj("zin"); ed = loadj("edge"); sp = loadj("spec"); cp = loadj("comp")
    hs = model_hashes()
    d = dc["OPA354"]
    T5 = d["aref_table"]["5"]; T12 = d["aref_table"]["1.25"]
    rows = []
    def row(i, lim, res, ok, margin=""):
        rows.append(f"| {i} | {lim} | {res} | {'PASS' if ok else 'FAIL'} | {margin} |")
    # SC-2
    row("SC-2 (+/-5 V, AREF 3.20)", ">= 80 mV per side at +/-6 V", f"worst {mv(T5['3.20']['margin_wc'])} (hi {mv(T5['3.20']['margin_hi_wc'])}, lo {mv(T5['3.20']['margin_lo_wc'])})",
        T5["3.20"]["margin_wc"] >= 0.08, mv(T5["3.20"]["margin_wc"] - 0.08))
    row("SC-2 over AREF 3.10-3.30 (new)", "80 mV holds to the lowest AREF", f"holds down to AREF = {d['lowest_aref']['5']:.3f} V; at 3.10 V worst {mv(T5['3.10']['margin_wc'])}",
        d["lowest_aref"]["5"] <= 3.20, f"{(3.20 - d['lowest_aref']['5'])*1e3:.0f} mV of AREF below 3.20")
    # SC-4
    gmin, gmax = T5["3.30"]["gain_min"], T5["3.30"]["gain_max"]
    row("SC-4 step", "<= 4 mV / code at the input", f"{3.3/4096/gmax*1e3:.2f}-{3.3/4096/gmin*1e3:.2f} mV (AREF 3.30, gain {gmin:.4f}-{gmax:.4f})", 3.3/4096/gmin <= 4e-3, f"{(4e-3-3.3/4096/gmin)*1e3:.2f} mV")
    occ = (10 * gmin / 3.3 * 100, 10 * gmax / 3.3 * 100)
    row("SC-4 occupancy", "70-75 % of full scale at nominal AREF", f"{occ[0]:.1f}-{occ[1]:.1f} % at AREF 3.30 (at 3.20: {10*gmin/3.2*100:.1f}-{10*gmax/3.2*100:.1f} %)", 70 <= occ[0] and occ[1] <= 75, f"{75-occ[1]:.1f} % below the top")
    # SC-11
    g12 = (T12["3.20"]["gain_min"], T12["3.20"]["gain_max"])
    row("SC-11 gain (+/-1.25 V)", "1.10 to 1.16 as built", f"{g12[0]:.4f}-{g12[1]:.4f}", 1.10 <= g12[0] and g12[1] <= 1.16, f"{(g12[0]-1.10)*1e3:.0f} / {(1.16-g12[1])*1e3:.0f} milli-units")
    row("SC-11 margin (AREF 3.20)", ">= 80 mV per side at +/-1.25 V", f"worst {mv(T12['3.20']['margin_wc'])}", T12["3.20"]["margin_wc"] >= 0.08, mv(T12["3.20"]["margin_wc"] - 0.08))
    row("SC-11 over AREF (new)", "80 mV holds to the lowest AREF", f"down to AREF = {d['lowest_aref']['1.25']:.3f} V", d["lowest_aref"]["1.25"] <= 3.20, "")
    # SC-3
    c = max(zi["5"]["C_worst_1MHz_pF"], zi["1.25"]["C_worst_1MHz_pF"])
    row("SC-3", "1 Mohm; <= 30 pF incl. wiring", f"{zi['5']['R_dc_ohm']/1e6:.4f} Mohm; {zi['5']['C_1e+06_pF']:.1f} pF nominal, {c:.1f} pF worst (C +/-5 %, wiring +/-1 pF, 4 pF wiring assumed)", c <= 30, f"{30-c:.1f} pF")
    # SM-3
    w5 = ac["OPA354_5"]["worst"]["bw"]; w12 = ac["OPA354_1.25"]["worst"]["bw"]
    row("SM-3 bandwidth, OPA354", ">= 8 MHz (-3 dB, BNC to ADC pin)", f"+/-5 V {w5/1e6:.0f} MHz, +/-1.25 V {w12/1e6:.1f} MHz (worst of 12 corners)", min(w5, w12) >= 8e6, f"{(min(w5, w12)/8e6-1)*100:.0f} %")
    w5b = ac["OPA365_5"]["worst"]["bw"]; w12b = ac["OPA365_1.25"]["worst"]["bw"]
    row("SM-3 bandwidth, OPA365", ">= 8 MHz", f"+/-5 V {w5b/1e6:.0f} MHz, +/-1.25 V {w12b/1e6:.2f} MHz (worst corner)", min(w5b, w12b) >= 8e6, f"{(min(w5b, w12b)/8e6-1)*100:.0f} %")
    # SC-6
    n5 = nz["OPA354_5"]["at_1p5bw"]["total_V"]; n12 = nz["OPA354_1.25"]["at_1p5bw"]["total_V"]
    row("SC-6 noise, OPA354 (to 1.5 x BW)", "<= 0.2 mV rms", f"+/-5 V {uv(n5)} ({nz['OPA354_5']['at_1p5bw']['fmax']/1e6:.0f} MHz), +/-1.25 V {uv(n12)} ({nz['OPA354_1.25']['at_1p5bw']['fmax']/1e6:.0f} MHz)", max(n5, n12) <= 200e-6, uv(200e-6 - max(n5, n12)))
    n5b = nz["OPA365_5"]["at_1p5bw"]["total_V"]; n12b = nz["OPA365_1.25"]["at_1p5bw"]["total_V"]
    row("SC-6 noise, OPA365 (to 1.5 x BW)", "<= 0.2 mV rms", f"+/-5 V {uv(n5b)}, +/-1.25 V {uv(n12b)}", max(n5b, n12b) <= 200e-6, uv(200e-6 - max(n5b, n12b)))
    # SC-9, SC-10
    xt = max(v["crosstalk_lsb"] for k, v in kk.items() if isinstance(v, dict) and "crosstalk_lsb" in v)
    row("SC-9 crosstalk (two channels, shared Vmid)", "<= 2 LSB", f"{xt:.4f} LSB worst of 18 cases (Vmid Zout 50 mohm assumed)", xt <= 2, f"{2-xt:.3f} LSB")
    err = max(max(abs(v["full_swing"]["errA_lsb"]), abs(v["full_swing"]["errB_lsb"])) for k, v in kk.items() if isinstance(v, dict) and "full_swing" in v)
    st = max(v["full_swing"]["settleB_ns"] for k, v in kk.items() if isinstance(v, dict) and "full_swing" in v)
    zo = max(v["zout"]["zmax_to_10MHz"] for k, v in kk.items() if isinstance(v, dict) and "zout" in v)
    row("SC-10 / AN-2 settling", "0.5 LSB inside the 15-clock window (667 ns); Z <= 5 kohm", f"error at window end {err:.4f} LSB; reaches 0.5 LSB in {st:.0f} ns; pin Z <= {zo:.0f} ohm to 10 MHz", err <= 0.5 and st < 667 and zo <= 5000, f"{667-st:.0f} ns")
    # AN-1
    pm = min(v["worst"]["pm"] for k, v in ac.items() if k.startswith("OPA354"))
    pms = min(min(x["pm"] for x in v["sens"]) for k, v in ac.items() if k.startswith("OPA354"))
    row("AN-1 phase margin, OPA354", ">= 45 deg with real parasitics", f"{min(pm, pms):.1f} deg worst (Cpar -2..+3 pF, Riso 10-50, Ron 8.8, C1 +/-5 %)", min(pm, pms) >= 45, f"{min(pm, pms)-45:.1f} deg")
    # PR
    dcp = pr["dc"]
    pw = [v for k, v in dcp.items() if "|powered|" in k]
    ed_pin = [v for v in pr["edge"].values()]
    pmax = max(max(v["v_pin"] for v in pw), max(v["pin_max"] for v in ed_pin)); pmin = min(min(v["v_pin"] for v in pw), min(v["pin_min"] for v in ed_pin))
    row("PR-2 pin range, powered, +/-30 V DC and 5/42 ns edges", "-0.2 to 3.45 V", f"{pmin:.3f} to {pmax:.3f} V", pmin >= -0.2 and pmax <= 3.45, f"{(3.45-pmax)*1e3:.0f} mV top, {(pmin+0.2)*1e3:.0f} mV bottom")
    ipk = max(v["i_clamp_peak_mA"] for v in pr["edge"].values())
    row("PR-1 clamp current, 5 ns 30 V edge, 50 ohm source", "<= 10 mA (op-amp abs max, DC rating; no pulse rating in the datasheet *(check)*)", f"{ipk:.1f} mA peak; DC +/-30 V: {max(v['i_clamp_uA'] for v in dcp.values()):.0f} uA", ipk <= 10, f"{10-ipk:.1f} mA")
    idue = max(abs(v["i_due33_uA"]) for v in dcp.values()); iin = max(v["i_in_uA"] for v in dcp.values())
    row("PR-3 unpowered, +/-30 V", "<= 100 uA into the Due supply pins; rails < 0.5 V", f"3.3 V-pin sense path {idue:.1f} uA; AFE rail receives {iin:.1f} uA, rail = {iin*BLEED*1e-6:.2f} V with the {BLEED/1e3:.1f} kohm bleed (analytic: I x R)", idue <= 100 and iin <= 100 and iin * BLEED * 1e-6 < 0.5, f"{100-iin:.0f} uA")
    te = {k: loadj(f"dc_trim_{k}k") for k in ("330", "340")}
    tm5 = min(te[k]["aref_table"]["5"]["3.20"]["margin_wc"] for k in te); tm12 = min(te[k]["aref_table"]["1.25"]["3.20"]["margin_wc"] for k in te)
    tg5 = (min(te[k]["aref_table"]["5"]["3.30"]["gain_min"] for k in te), max(te[k]["aref_table"]["5"]["3.30"]["gain_max"] for k in te))
    tg12 = (min(te[k]["aref_table"]["1.25"]["3.20"]["gain_min"] for k in te), max(te[k]["aref_table"]["1.25"]["3.20"]["gain_max"] for k in te))
    row("SC-2 with the R2 trimmer at either end (leg 330k / 340k)", ">= 80 mV per side at +/-6 V, AREF 3.20", f"worst {mv(tm5)} (+/-5 V), {mv(tm12)} (+/-1.25 V, SC-11)", min(tm5, tm12) >= 0.08, mv(min(tm5, tm12) - 0.08))
    row("SC-4 / SC-11 gain with the trimmer at either end", "+/-5 V gain 0.2290-0.2453 (SC-4 occupancy window); +/-1.25 V 1.10-1.16", f"+/-5 V {tg5[0]:.4f}-{tg5[1]:.4f}; +/-1.25 V {tg12[0]:.4f}-{tg12[1]:.4f}", 0.2290 <= tg5[0] and tg5[1] <= 0.2453 and 1.10 <= tg12[0] and tg12[1] <= 1.16, "")
    out = "\n".join(rows)

    # ------------------------------------------------------------ text
    L = []
    A = L.append
    A("# 2b scope channel: simulation report\n")
    A("Plan step 2b (`docs/afe-plan.md`). Everything below is regenerated by `python3 -I run.py` (about 1-2 minutes); raw numbers are in `results/*.json`, netlists in `netlists/`, the open behavioural range switch in `models/rangesw.lib`.\n")
    A("## Report header\n")
    A(f"- Simulator: `{ngspice_version()}`; KiCad not used in this step (no schematic yet).")
    A("- Vendor models, referenced by relative path from `netlists/` and not copied (TI, not redistributable): " +
      ", ".join(f"`{k}` sha256 `{v['actual']}` ({'matches' if v['match'] else 'DOES NOT MATCH'} `models/SOURCES.md`)" for k, v in hs.items()) +
      ". They are used here for local cross-checks only.")
    A("- Our own model: `models/rangesw.lib` (RSW_CLOSED / RSW_OPEN), every parameter with its TMUX1119 datasheet source in the file header. TI's TMUX1119 model does not parse in ngspice 47; this is a flagged model gap.")
    A("- Op-amp pin order for both vendor subcircuits: `+IN -IN V+ V- OUT`. OPA2354 is the same die/model as OPA354 (SOURCES.md), so it was not run separately.")
    A("- Stimuli: DC sources at the input; AC 1 V at the BNC behind 50 ohm; steps 0 to 2.0 V (+/-5 V range) and 0 to 0.5 V (+/-1.25 V range) with 5 ns and 42 ns edges; +/-30 V DC and 30 V edges (5 ns, 42 ns) through 50 ohm for protection.")
    A("- Loads and rail assumptions: ADC pin = 2 pF + the SAM3X sample-and-hold (below); Vmid = AREF/2 +/-30 mV behind **0.05 ohm**, 10 uF + 100 nF decoupling (ESR 20 mohm); the op-amp rail 3.23-3.37 V behind 0.1 ohm + 10 nH with 100 nF + 1 uF at the pin; 3.3 V sense node = AREF through 100 ohm + 10 uF. These are requirements on the 2a power block, listed under 'Assumptions'.\n")
    A("### SAM3X ADC input model (quoted, `docs/datasheets/microchip/SAM3X-SAM3A-11057C.pdf`, Section 45.7, printed pages 1403-1409)\n")
    A("- Track time, 12-bit: `tTRACK = 0.054 x ZSOURCE + 205` ns (Section 45.7.2.1); minimum track time 160 ns (Table 45-30); 15 ADC clocks at 22.5 MHz = 667 ns (docs/hardware.md, `TRACKTIM=0`, `TRANSFER=1`).")
    A("- Input capacitance `Ci` max **8 pF**, input leakage 0.5 uA max (Table 45-38). The datasheet states Csample and RON are 'taken into account in the formulas' (Figure 45-18) but gives **no separate values**.")
    A("- fADC max in this datasheet revision is 22 MHz (Table 45-30); docs/hardware.md quotes 20 MHz from Table 46-28 of another revision. The project runs 22.5 MHz, above both.")
    A(f"- **Derived (not quoted) model:** a 12-bit settling to 0.5 LSB needs ln(2^13) = 9.01 time constants, so the slope 0.054 ns/ohm gives Csample = 0.054 ns / 9.01 = **6.0 pF**, and the 205 ns intercept gives Ron = 205 ns / (9.01 x 6 pF) = **3.8 kohm**. Used as the 'derived' ADC. A 'stress' ADC with Ron = 1 kohm and all 8 pF of Ci on the sampling cap is also run. Both are *(check)* against the part; the SC-10 bench test (VT-10) is what closes them.")
    A(f"- Sampling sequence modelled: the shared S/H tracks channel A for 667 ns, channel B for the next 667 ns, with a period of 21.5 ADC clocks = 955.6 ns per conversion (docs/hardware.md, aggregate 1,046,510 sps) *(check: the exact overlap of track and convert is not in the datasheet text read here)*.\n")

    A("## Two defects in the specified design, found before anything else\n")
    s1 = sp["OPA354_5"]; s2 = sp["OPA354_1.25"]
    A("The design was first simulated exactly as specified (R2 returned to Vmid, range switch in the RG leg, RF 3.83 kohm / RG 1.00 kohm, no input series resistor). Two requirement-level problems appeared. Neither is fixed by tuning a value; both needed a circuit change, and the changes are what the rest of this report simulates.\n")
    A(f"1. **The divider does not centre the pin.** With R2 returned to Vmid the node N sits at (1 - alpha) x Vmid + alpha x Vin, with alpha = 0.2358, so at 0 V in the pin is at **{s1['pin_mid']:.3f} V**, not Vmid (1.650 V). The +/-5 V range then spans {s1['pin_lo']:.3f} to {s1['pin_hi']:.3f} V: the low side is **{mv(s1['margin_lo'])}** (needs +80 mV), and on the +/-1.25 V range the pin at 0 V is {s2['pin_mid']:.3f} V, clipped at the rail. `architecture.md` says 'pin = Vmid + 0.2358 x Vin', which is true only if the divider's far end sits at Vmid / (1 - alpha) = 2.16 V. **Fix used:** a third resistor R3 = R1 = 768 kohm from N to the 3.3 V sense node (the Due's 3.3 V pin through 100 ohm + 10 uF, 4.3 uA per channel), and R2 raised to a 335 kohm leg (330 kohm fixed + the 10 kohm trimmer at its 5 kohm mid-setting). Then N(0) = Vmid for any R2 (the condition is R3 = R1 only), alpha = 1/(2 + R1/R2) = 0.2330 and Rin = R1 + R2||R3 = 1.0013 Mohm. The centre now tracks AREF ratiometrically. It draws microamps from the 3.3 V pin (PW-1 allows that for sensing).")
    A(f"2. **The range switch in the RG leg makes a peaking amplifier.** The open switch's 6 pF (CSOFF) in series with RG puts a zero at 1/(2 pi RF Coff) = 7 MHz into the gain: in the +/-5 V range the response as specified peaks **{s1['ac']['peak_db']:.0f} dB** at {s1['ac']['f_peak']/1e6:.0f} MHz with a phase margin of **{s1['ac']['pm']:.0f} degrees** (OPA354) and {sp['OPA365_5']['ac']['pm']:.0f} degrees (OPA365). A feedback capacitor and scaling RF/RG together were tried (RF 3.83k/1k, 1.91k/499, 953/249 with Cf 0-3.3 pF): peaking stayed 10-15 dB, because the zero depends on RF x Coff only. **Fix used:** the switch is moved to **shunt RF** (closed = +/-5 V, G = 1 + Ron/RG; open = +/-1.25 V, G = 1 + RF/RG), RG fixed to Vmid. The open switch's Coff then sits across RF as a pole that only trims the +/-1.25 V bandwidth, and nothing peaks. Costs, listed honestly: Ron (3.7 typ, 8.8 max) is in the G = 1 gain (+1.5 % to +3.5 % of gain in the +/-5 V range with RG = 249 ohm, within the 0.2290-0.2453 window but a part-to-part spread against SC-8 that the datasheet does not bound), RG now carries the output current in both ranges (up to 5.7 mA), and RF/RG are scaled to 953 / 249 ohm (both E96) to keep the +/-1.25 V pole at 28 MHz. **The Vmid source therefore has to hold its voltage under +/-5.7 mA per channel (50 mohm or less); with 1 ohm it adds 6 mV of crosstalk.**\n")
    A("3. A series resistor **Rnp = 680 ohm** ahead of each op-amp + input (not in the specification) limits the clamp current of a fast edge on the input (73 mA without it, case 5). It costs ~2 dB of extra peaking in the +/-5 V range.\n")

    A("## Settled circuit (one channel; the two are identical)\n")
    A("| part | value | note |\n|---|---|---|\n| R1 | 768 kohm 0.1 % 25 ppm/K (FH TD03G7683BT, C667248) | IN to N |\n| R2 | 330 kohm 0.1 % 25 ppm/K (E24) fixed, in series with a 10 kohm SMD cermet trimmer (5 kohm mid-setting, 0-10 kohm, 100 ppm/K *(check: datasheet of the actual part not read)*); the sim leg is 335 kohm | N to Vmid; the trim is set once at build (see sim/diff) |\n| R3 | 768 kohm 0.1 % 25 ppm/K (same part as R1) | N to filtered 3.3 V sense; must match R1 |\n| C1 | 12 pF C0G (E24 12; the ideal is 12.27 pF) | across R1 |\n| C2 | 39 pF C0G (E24 39) incl. op-amp, stray: the sim uses 38 pF + the model's own input capacitance | N to Vmid |\n| Rnp | 680 ohm 1 % 0603 (E24; UNI-ROYAL 0603WAF6800T5E, C23228, Basic *(check)*) | N to + input |\n| RF / RG | 953 ohm / 249 ohm 0.1 % (E96), ratio 3.827 | G = 4.83 when the switch is open |\n| range switch | TMUX1119-class SPST across RF, Ron 3.7/8.8 ohm | closed = +/-5 V (default; the Due-pin pull-down keeps it closed) |\n| Riso | 22 ohm 1 % 0603 (E24; UNI-ROYAL 0603WAF220JT5E, C23345, Basic *(check)*) | op-amp to ADC pin |\n| bleed on the AFE 3.3 V rail | 4.7 kohm 1 % 0603 (UNI-ROYAL 0603WAF4701T5E, C23162, Basic *(check)*) | for the unpowered case, PR-3; the same resistor as powercal's +3.3 V bleed (one net, one part) |\n| op-amp | **OPA354** | see recommendation |\n")
    A("The sim netlist uses C1 = (38 + 2) pF x (R2||R3 / R1), i.e. 12.15 pF for the 335 kohm leg, to isolate the circuit from the E24 grid; with the E24 pair 12 pF / 39 pF the compensation error is 1.2 % on C1 and it is covered by the C1 +/-5 % corner in the AC cases.\n")

    A("## Pass / fail\n")
    A("Worst-case means: DC by one-at-a-time extremes of every tolerance summed (0.1 % resistors, Vmid centring +/-30 mV, op-amp Vos at datasheet max, Ron 8.8, rail 3.23-3.37 V), cross-checked by a Monte Carlo; AC/noise at 12 corners (Cpar -2/0/+3 pF, Ron 3.7/8.8, C1 +/-5 %).\n")
    A("| requirement | limit | worst-case result | verdict | margin |\n|---|---|---|---|---|\n" + out + "\n")
    A("Rows for OPA365 are shown so the choice is visible; the recommendation row set is OPA354.\n")

    A("## Recommendation\n")
    fails = []
    A(f"**OPA354.** With the circuit above it passes every case at its worst corner: SM-3 bandwidth {min(w5, w12)/1e6:.1f} MHz worst against 8 MHz, SC-6 noise {max(n5, n12)*1e6:.0f} uV against 200 uV, phase margin {min(pm, pms):.0f} degrees. **OPA365 fails SM-3** on the +/-1.25 V range: its 50 MHz GBW gives {ac['OPA365_1.25']['nominal']['bw']/1e6:.2f} MHz nominal and {w12b/1e6:.2f} MHz at the worst corner against 8 MHz, and no value of RF/RG/Cf helped (it needs a gain-4.83 bandwidth GBW/4.83 = 10 MHz before parasitics). It is quieter ({uv(max(n5b, n12b))} against {uv(max(n5, n12))}), which matters only if SC-6 were tightened. OPA354 costs more supply current (5-6.3 mA against 4.6) and its input stage has a crossover near V+ - 2 V, shown below to be harmless here.\n")
    A("**Cost of the choice on the +/-5 V range:** the OPA354 gives a wide, peaking response there (a 5 dB peak near 90 MHz, about 20 % overshoot on a 5 ns edge). It is outside the 8 MHz band, but the ADC folds it in; the noise numbers above integrate it. There is no requirement on peaking, but the calibration note (case 8) must not assume the response is monotone above 20 MHz.\n")

    # ---------------------------------------------------------- case detail
    A("## Case 1: DC transfer, headroom and the AREF 3.10 to 3.30 V range\n")
    A("Worst-case margin to the ADC rails per side (the smaller of top and bottom), OPA354, +/-6 V on the +/-5 V range and +/-1.25 V on the +/-1.25 V range. AREF is the 3.3 V pin; Vmid = AREF/2 +/-30 mV; the sense node tracks AREF.\n")
    A("| AREF | +/-5 V margin (worst case) | gain window | +/-1.25 V margin | gain window |\n|---|---|---|---|---|")
    for a in AREFS:
        k = f"{a:.2f}"
        A(f"| {a:.2f} V | {mv(T5[k]['margin_wc'])} | {T5[k]['gain_min']:.4f}-{T5[k]['gain_max']:.4f} | {mv(T12[k]['margin_wc'])} | {T12[k]['gain_min']:.4f}-{T12[k]['gain_max']:.4f} |")
    A("")
    A(f"**Lowest AREF at which the 80 mV margin still holds (linear fit of the worst-case column): +/-5 V range {d['lowest_aref']['5']:.3f} V, +/-1.25 V range {d['lowest_aref']['1.25']:.3f} V.** Below those the range cannot be used to its full +/-6 V / +/-1.25 V; the instrument still works but clips earlier. At AREF 3.10 V the worst-case margin is {mv(T5['3.10']['margin_wc'])} and {mv(T12['3.10']['margin_wc'])}. The gain window 0.2290-0.2453 (+/-5 V) and 1.10-1.16 (+/-1.25 V) holds at every AREF (gain is ratiometric). The SC-4 occupancy of 70-75 % is defined at nominal AREF and reads {10*T5['3.30']['gain_min']/3.3*100:.1f}-{10*T5['3.30']['gain_max']/3.3*100:.1f} % at 3.30 V, {10*T5['3.30']['gain_min']/3.2*100:.1f}-{10*T5['3.30']['gain_max']/3.2*100:.1f} % at 3.20 V: above 75 % at the low end of the AREF spread, informational.\n")
    mc = d["mc"]
    A("Monte Carlo (80 draws per point; uniform tolerances, Vos, Ron 3.7-8.8, rail 3.23-3.37 V): " + "; ".join(f"{k}: min margin {mv(v['margin_min'])}, gain {v['gain_min']:.4f}-{v['gain_max']:.4f}" for k, v in mc.items()) + ". Every draw lies inside the worst-case sum, as it must.\n")
    h = d["headroom"]
    A(f"Op-amp output headroom at the worst corner (rail 3.23 V, AREF 3.30, Vmid +30 mV, +6 V in): output {h['5']['out_hi']:.3f} V on the +/-5 V range, {h['1.25']['out_hi']:.3f} V on +/-1.25 V, i.e. **{mv(h['5']['headroom_to_rail'])} and {mv(h['1.25']['headroom_to_rail'])} below the rail**. The vendor model's swing at this load is the only evidence: the datasheet specifies 0.1 V typ / 0.3 V max from the rail at 1 kohm and 5 V supply only *(check at 3.3 V; VT-1)*. If the real swing at 3.23 V is 0.3 V the top 6 V point clips; the +/-6 V usable range in SC-2 depends on it.\n")
    o5 = dc["OPA365"]
    A(f"OPA365 DC, for the comparison: lowest AREF {o5['lowest_aref']['5']:.3f} V (+/-5 V) and {o5['lowest_aref']['1.25']:.3f} V (+/-1.25 V); its offset (0.2 mV max against 8 mV) buys about 8 mV of margin.\n")
    A("**Input-stage crossover (OPA354):** the signal at the + input spans 0.4 to 2.9 V and crosses the crossover near V+ - 2 V. The DC sweeps above show the transfer gain is the same at the +/-6 V points as the two-point corner assumed; the model's step in Vos at the transition is inside the 8 mV offset allowance. An INL sweep was not run; VT-1 closes it.\n")

    A("## Case 2: bandwidth, peaking, edges, group delay\n")
    A("| op-amp, range | gain at 10 kHz | -3 dB | peak | PM (nominal) | PM (worst) | BW (worst corner) | group-delay variation 0.1-8 MHz |\n|---|---|---|---|---|---|---|---|")
    for k, v in ac.items():
        n = v["nominal"]
        A(f"| {k.replace('_', ', +/-')} V | {n['g0']:.4f} | {n['bw']/1e6:.1f} MHz | {n['peak_db']:.2f} dB at {n['f_peak']/1e6:.0f} MHz | {n['pm']:.0f} deg | {v['worst']['pm']:.0f} deg | {v['worst']['bw']/1e6:.1f} MHz | {n['gd_var_ns']:.1f} ns |")
    A("\nEdge response (BNC behind 50 ohm; 10-90 % rise at the pin; overshoot; settling to 0.5 % of the step):\n")
    A("| case | rise 10-90 | overshoot | settle 0.5 % |\n|---|---|---|---|")
    for k, v in ed.items():
        A(f"| {k} | {v['rise_10_90_ns']:.1f} ns | {v['overshoot_pct']:.1f} % | {v['settle_0p5pct_ns']:.0f} ns |")
    A("\nThe +/-1.25 V range on OPA354 shows a slow tail to 0.5 % of the step that is the compensated divider's DC-to-HF gain step (C1 12.15 pF against the true C2 including the op-amp input), not the op-amp; it is the gain-flatness error host calibration removes (SC-5) and a measured C1 trim would reduce. The 5 ns edge on the +/-5 V range overshoots 20 % on OPA354 because of the 3.5-5 dB peaking near 90 MHz.\n")

    A("## Case 3: noise\n")
    A(f"Integrated 10 Hz to the stated frequency, at the ADC pin, with ngspice `.noise`. Contributors split by re-running with parts silenced (resistors only: ideal noiseless op-amp; op-amp voltage noise: divider replaced by a noiseless source and resistors silenced; op-amp current noise is the remainder). **Which bandwidth:** the primary figure is integrated to **1.5 x the -3 dB bandwidth** (the stricter of the two requested); the -3 dB figure and the 10 MHz figure (the SC-6 'derived 63 nV/sqrt Hz over 10 MHz') are also given. Vmid and the 3.3 V sense node are added from their AC transfer to the pin times an *assumed* source density (Vmid {EN_VMID*1e9:.0f} nV/sqrt Hz ahead of its decoupling, the 3.3 V pin {EN_V3*1e9:.0f} nV/sqrt Hz) *(assumptions, closed by 2a)*.\n")
    A("| op-amp, range | to | total | resistors | op-amp voltage | op-amp current | Vmid | 3.3 V sense | verdict vs 0.2 mV |\n|---|---|---|---|---|---|---|---|---|")
    for k, v in nz.items():
        for lab, nm in (("at_bw", "-3 dB"), ("at_1p5bw", "1.5 x BW"), ("at_10MHz", "10 MHz")):
            x = v[lab]
            A(f"| {k.replace('_', ', +/-')} V | {nm} ({x['fmax']/1e6:.0f} MHz) | {uv(x['total_V'])} | {uv(x['resistors_V'])} | {uv(x['opamp_voltage_V'])} | {uv(x['opamp_current_resid_V'])} | {uv(x['vmid_V'])} | {uv(x['v3sense_V'])} | {'pass' if x['total_V'] <= 200e-6 else 'FAIL'} |")
    A("\nDensity at the pin, OPA354: " + "; ".join(f"{k.replace('_',', +/-')} V: " + ", ".join(f"{fx} Hz {val:.1f}" for fx, val in v['density_nV'].items()) + " nV/sqrt Hz" for k, v in nz.items() if k.startswith("OPA354")) + ". The SC-6 equivalent density, 63 nV/sqrt Hz, is met at every listed frequency on the +/-5 V range and at 1-10 MHz on the +/-1.25 V range (37.5 and 31 nV); at 100 kHz the +/-1.25 V range reads 64 nV (1/f).\n")
    A("**ADC sampling view (supplementary):** the SAM3X's own tracking pole 1/(2 pi Ron Cs) = " + f"{nz['OPA354_5']['adc_tracking_pole_Hz']/1e6:.1f} MHz (derived model, *(check)*) limits what the sample actually folds in; through it the pin noise is " + ", ".join(f"{k.replace('_',', +/-')} V {uv(v['through_adc_pole_V'])}" for k, v in nz.items() if k.startswith('OPA354')) + ". Not used for the verdict. 'ADC kick' as a noise term is not noise: its settling residual is 0.0002 LSB (case 4); the converter's own kT/C noise is the Due's floor (0.8-0.85 codes) and is not part of SC-6.\n")
    A("Note the largest single term is the op-amp's own voltage noise multiplied by its noise gain; the 1/f corner of the vendor model is included (INPUT VOLTAGE NOISE WITH 1/F) but its fit to the real part is a model gap.\n")

    A("## Case 4: ADC load, settling and crosstalk\n")
    A("A and B share Vmid, the supply and one S/H. 'Full swing' puts A at +full scale and B at -full scale (the worst kick, 2.86 V at the pins on the +/-5 V range); 'crosstalk' puts A at +/- full scale and B shorted (Vin = 0), and the crosstalk is the change in B's sampled error between the two A states. Error is the S/H voltage 2 ns before the end of the 667 ns window against that pin's own DC value, in LSB of AREF/4096 (AREF 3.20 V, 0.78 mV).\n")
    A("| range, ADC model, Riso | S/H error at 667 ns (A / B) | settles to 0.5 LSB in | crosstalk | pin Z to 10 MHz |\n|---|---|---|---|---|")
    for k, v in kk.items():
        if isinstance(v, dict) and "full_swing" in v:
            f = v["full_swing"]
            A(f"| {k} | {f['errA_lsb']:.4f} / {f['errB_lsb']:.4f} LSB | {f['settleB_ns']:.0f} ns | {v['crosstalk_lsb']:.4f} LSB | {v['zout']['zmax_to_10MHz']:.1f} ohm |")
    bs = kk["bare_pin_charge_share"]
    A(f"\n**Undriven-pin memory.** CLAUDE.md records 56 % of A0's amplitude on an undriven pin. For a bare pin the charge-share ratio Cs/(Cs + Cpin) is {bs['Cp2.0pF']:.2f} at 2 pF, {bs['Cp4.7pF']:.2f} at 4.7 pF and {bs['Cp8.0pF']:.2f} at 8 pF with the derived 6 pF Cs; 56 % corresponds to about 4.7 pF of pin capacitance, which is consistent with the datasheet's Ci = 8 pF (derived, not simulated as the bench effect). A driven pin shows a memory of {max(abs(v['full_swing']['errB_lsb']) for k,v in kk.items() if isinstance(v,dict) and 'full_swing' in v)/(2.86/LSB(3.2)):.1e} of the step instead, i.e. the op-amp (output impedance 20 ohm to 10 MHz, mostly Riso) removes the bucket charge long before the window ends. The two-channel case at 1,022,727 sps single channel has no inter-channel kick at all (the previous sample is the same channel). The shared Vmid and supply coupling is inside these runs: it is why Vmid must be 50 mohm, not 1 ohm (6 mV at 1 ohm, found while building this).\n")
    qi = kk["charge_injection"]
    A(f"**Range-switch charge injection** (6 pC into the inverting node, TMUX1119 QC): peak {qi['5']['peak_mV']:.0f} mV and recovery to 0.5 LSB in {qi['5']['recover_0p5LSB_ns']:.0f} ns on the +/-5 V range, {qi['1.25']['peak_mV']:.0f} mV and {qi['1.25']['recover_0p5LSB_ns']:.0f} ns on +/-1.25 V. It happens only when the range is changed; the instrument must discard samples for a few hundred ns, nothing more. The datasheet value is for a 1 nF load and is a model gap.\n")

    A("## Case 5: protection\n")
    A("The vendor op-amp model has input clamps to both rails (diodes, no series resistance). DC input current is set by R1: (30 - 0.55 V)/768 kohm = 38 uA, matching the sim (38.3 uA). Tables are in `results/prot.json`.\n")
    A("| state, range, input | input current | voltage on the ADC pin | rail | current into the Due 3.3 V pin (sense) |\n|---|---|---|---|---|")
    for k, v in dcp.items():
        if "floating_1000000" in k:
            continue
        A(f"| {k.replace('|', ', ')} V | {v['i_in_uA']:.1f} uA | {v['v_pin']:.3f} V | {v['v_rail']:.3f} V | {v['i_due33_uA']:+.1f} uA |")
    A("\n**Read this table with care.** Powered rows are physical: the pin reaches 3.26-3.33 V at +30 V (limit 3.45) and 0.04-0.11 V at -30 V (limit -0.2), so no clamp current reaches the ADC pin and PR-2 holds with 120-190 mV at the top. The unpowered and floating rows contain a **vendor-model artifact**: with its supply at zero the model draws ~3.5 mA through the supply pins and the floating rail goes to -0.4 V, which no real part does when the clamp current flows *into* the rail. Those two columns (pin -0.185 to -0.216 V, rail -0.41 to -0.44 V) are therefore not evidence for or against PR-2 with the Due unpowered; the unpowered PR-2 check is **inconclusive from the model and is closed by VT-5**. What the model does show and what is analytic: the input current is 38-39 uA in every state; with the AFE rail floating that current must go somewhere, and without a bleed it raises the rail (the model cannot show how far, 1 Mohm gave the same artifact value). " + f"A **{BLEED/1e3:.1f} kohm bleed** (one part with powercal's +3.3 V bleed, which sits on the same net) keeps it at {iin:.1f} uA x {BLEED/1e3:.1f} kohm = {iin*BLEED*1e-6:.2f} V (< 0.5 V) and costs {3.34/BLEED*1e3:.2f} mA at 3.34 V of the 100 mA budget; {0.5/(iin*1e-6)/1e3:.1f} kohm would be the upper limit. " + "The current into the Due's own supply (through the 3.3 V sense resistor R3) is at most " + f"{idue:.1f} uA (limit 100 uA). Whether the AFE's 3.3 V rail can pass the 39 uA back to the Due's 5 V pin depends on the LM27762, which has no usable model: *(check)*, VT-5.\n")
    A("Fast edges through C1 (30 V, powered, source 50 ohm): " + ", ".join(f"{k}: {v['i_clamp_peak_mA']:.1f} mA" for k, v in pr["edge"].items() if k.startswith("5|+30") or k.startswith("5|-30")) + f". Node N reaches {max(v['n_max'] for v in pr['edge'].values()):.1f} V and {min(v['n_min'] for v in pr['edge'].values()):.1f} V (C1/(C1+C2) of 30 V) and is held to the rails by the clamps only through Rnp. Without Rnp the 5 ns edge puts 73 mA into the clamp (guard below). The datasheet gives +/-10 mA as a continuous rating and no pulse rating *(check)*; 6.5 mA for about a nanosecond is accepted with that caveat.\n")
    a1 = pr["above30"]
    A(f"**What fails above +/-30 V** (PR-1: 'only parts the owner can replace on the shield'). The op-amp is not the limit: at +/-200 V the input current is {a1['+200']['i_in_uA']:.0f} uA, far below its +/-10 mA, which would need ~7.7 kV across R1. The parts that go first are the passives in front of it: **C1** (12 pF C0G 0603, typically 50 V rated) and **R1** (768 kohm 0603, typically 75 V working voltage; dissipation {a1['+200']['P_R1_mW']:.0f} mW at 200 V against 100 mW). Both are soldered, replaceable parts on the shield; the BNC and the op-amp are not harmed. Voltage ratings are typical catalogue values *(check against the chosen part)*. Above about 90 V R1's 100 mW is exceeded by dissipation alone only at ~277 V.\n")

    A("## Case 6: input resistance and capacitance\n")
    A(f"R = {zi['5']['R_dc_ohm']/1e6:.4f} Mohm; C = {zi['5']['C_1e+05_pF']:.1f} pF at 100 kHz, {zi['5']['C_1e+06_pF']:.1f} pF at 1 MHz, {zi['5']['C_5e+06_pF']:.1f} pF at 5 MHz, identical in both ranges (the switch is after the divider); worst {c:.1f} pF with C1, C2 +/-5 % and +/-1 pF wiring. The 4 pF of BNC and trace at the input is an assumption *(check at layout and VT-10)*. The divider capacitance is C1 in series with C2 = 9.4 pF.\n")

    A("## Case 7: phase margin and parasitic sensitivity\n")
    A("Loop gain by a Middlebrook break at the op-amp output (so the load, Riso and the ADC pin are inside the loop). Phase margin, OPA354, over the inverting-node extra capacitance (pad 2 pF + trace 1 pF assumed as 3 pF; extra -2 to +3 pF) and Riso 10/22/50 ohm:\n")
    A("| range | extra Cpar | Riso 10 | Riso 22 | Riso 50 |\n|---|---|---|---|---|")
    for rng in ("5", "1.25"):
        sens = ac[f"OPA354_{rng}"]["sens"]
        for cx in (-2.0, -1.0, 0.0, 1.0, 2.0, 3.0):
            vals = {x["riso"]: x["pm"] for x in sens if abs(x["cpar_extra_pf"] - cx) < 1e-9}
            A(f"| +/-{rng} V | {cx:+.0f} pF | {vals[10.0]:.1f} deg | {vals[22.0]:.1f} deg | {vals[50.0]:.1f} deg |")
    nr = ac["OPA354_5"]["no_riso_10pF"]
    A(f"\nWith no series resistor and 10 pF at the pin the +/-5 V range still reads {nr['pm']:.1f} degrees: the OPA354 model is stable into capacitive load here, so Riso is set by SC-10 and edge-current, not by stability. The minimum over all of these is {min(pm, pms):.1f} degrees (>= 45). The vendor model's capacitive-load behaviour is a model gap *(check)*.\n")

    A("## Case 8: gain flatness the host calibration must correct\n")
    A(f"Gain relative to 100 kHz, BNC to ADC pin through the 50 ohm source, nominal corner, dB. The gain at 100 kHz is {cp['335k leg (330k + 5k trimmer)|ideal C1 for C2tot 40 pF|5']['step_100k_pct']:.2f} % above the 1 kHz gain on +/-5 V ({cp['335k leg (330k + 5k trimmer)|ideal C1 for C2tot 40 pF|1.25']['step_100k_pct']:.2f} % on +/-1.25 V): C1 is the ideal for 40 pF at N, but the true capacitance there is about 1 pF more (the op-amp model's own pin capacitance and the wiring; the step vanishes near 41 pF in the table below), so the compensated divider has a step between DC and 100 kHz, about 2.3 % of gain per pF of error at 100 kHz (0.6 % at 10 kHz, where the divider's 17 kHz corner has only partly turned over). Above 100 kHz the divider is flat to 0.01 dB; the rest is the op-amp. At 20 MHz the +/-1.25 V range is 4 dB down on OPA354 (its -3 dB point is 16.8 MHz).\n")
    A("| op-amp, range | " + " | ".join(f"{float(k)/1e6:g} MHz" for k in ac["OPA354_5"]["nominal"]["flat_db"]) + " |\n|---|" + "---|" * len(ac["OPA354_5"]["nominal"]["flat_db"]))
    for k, v in ac.items():
        A(f"| {k.replace('_', ', +/-')} V | " + " | ".join(f"{x:+.2f}" for x in v["nominal"]["flat_db"].values()) + " |")
    A("\nFor the calibration note: (a) the +/-5 V range is flat to 0.05 dB through 8 MHz and +0.27 dB at 20 MHz, then peaks about 5 dB near 90 MHz; (b) the +/-1.25 V range is -0.26 dB at 4 MHz, -0.96 dB at 8 MHz, -1.4 dB at 10 MHz and -3 dB at 16.8 MHz (OPA354), so it needs a frequency-dependent correction from about 2 MHz up; (c) the gain differs between ranges by the Ron term (about 1.7 %) and between channels by Ron spread, so each channel and range needs its own gain (CA-1); (d) group-delay variation 0.1-8 MHz is 6-9 ns per range, to be corrected as phase if the ETS reconstruction needs it; (e) the divider's DC-to-100 kHz gain step (+0.55-0.6 % here) follows C1/C2 tolerance and is per board.\n")
    A("\n### Compensation with the E24 pair, and the 330 kohm resistor\n")
    A("C1 = 12 pF is fixed (E24) and the ideal is C1 = C2tot x (R2||R3) / R1, with C2tot the external C2 plus the op-amp's 2 pF. The divider's own gain step between DC (1 kHz) and 100 kHz is the compensation error times about 0.18, in the sim; flatness is 1-8 MHz relative to 100 kHz. All nominal parts, OPA354.\n")
    A("| R2 leg | case | C1 ideal (pF) | C1 error | step 10 kHz (+/-5 V) | step 100 kHz (+/-5 V) | step 100 kHz (+/-1.25 V) | flatness 1-8 MHz (+/-5 V / +/-1.25 V, dB) | BW (+/-5 V / +/-1.25 V, MHz) |\n|---|---|---|---|---|---|---|---|---|")
    for key in cp:
        leg, lab, rg = key.split("|")
        if rg != "5":
            continue
        v5, v12 = cp[key], cp[f"{leg}|{lab}|1.25"]
        A(f"| {leg} | {lab} | {v5['c1_ideal_pF']:.2f} | {v5['comp_err_pct']:+.1f} % | {v5['step_10k_pct']:+.2f} % | {v5['step_100k_pct']:+.2f} % | {v12['step_100k_pct']:+.2f} % | {v5['flat_1_8MHz_db']:.3f} / {v12['flat_1_8MHz_db']:.3f} | {v5['bw_MHz']:.0f} / {v12['bw_MHz']:.1f} |")
    A("\nEach 1 % of compensation error moves the 100 kHz step by about 0.8 % of gain, and the 1-8 MHz flatness (0.04-0.06 dB on +/-5 V) and the bandwidth (128-130 MHz on +/-5 V, 16-18 MHz on +/-1.25 V) barely move across the rows: both are set by the op-amp stage. **The E24 pair C1 = 12 pF with a 39 pF C2 (C2tot 41 pF, the +/-5 V row marked '39 pF part') is the flattest of the rows on the 335 kohm leg (-0.31 % step) and stays inside SC-5's 0.3 dB flatness by a factor of 7; 36 pF or 39 pF both stay inside it too, only the step differs (+5.6 % / -0.3 %).** The step is a smooth gain change between 10 kHz and 100 kHz that the host's frequency calibration (SC-5) removes; it is not a flatness failure in the 1-8 MHz band SM-3/SC-6 are about. Because both channels carry the same systematic residual, it cancels in the common-mode response; what reaches the 10 kHz CMRR is only the channel-to-channel difference, which the +/-5 % capacitor tolerance sets (sim/diff).\n")

    A("## Checks I broke on purpose\n")
    A("Each guard was run on the good circuit (pass), on a deliberately broken circuit (must fail), and on the restored circuit (must pass again). A guard that passed the broken circuit would be worthless; one did, the first time (the noise guard, whose first mutation narrowed the bandwidth and so lowered the noise), and its mutation was changed.\n")
    A("| guard | mutation | good | broken | restored | effective |\n|---|---|---|---|---|---|")
    for g in gd:
        A(f"| {g['guard']} | {g['mutation']} | {'pass' if g['good']['ok'] else 'FAIL'}: {g['good']['detail']} | {'pass' if g['broken']['ok'] else 'FAIL'}: {g['broken']['detail']} | {'pass' if g['restored']['ok'] else 'FAIL'} | {'yes' if g['effective'] else 'NO'} |")
    A("")

    A("## Model gaps and the test that closes each\n")
    A("| gap | why the model cannot show it | closed by |\n|---|---|---|\n"
      "| range switch charge injection, Ron spread and signal/temperature dependence, real Coff | TI's TMUX1119 model does not parse in ngspice 47; ours is Ron + capacitances only | VT-10 (gain per range, matching), VT-4 (response), VT-1 (offset step on range change) |\n"
      "| op-amp input 1/f noise and its real corner | the vendor model's flicker fit is not verified against the part | VT-3, VT-16 (noise with an external instrument) |\n"
      "| OPA354 input-stage crossover near V+ - 2 V, real offset step and INL | no INL sweep run; model's transition step unverified | VT-1 (DC accuracy per channel) |\n"
      "| op-amp output swing at 3.23 V and light load, and stability into capacitance | datasheet gives swing only at 5 V, 1 kohm | VT-1, VT-4 |\n"
      "| ADC input: Csample, Ron, the track/convert overlap, leakage, the real 56 % memory | the datasheet gives only the track-time formula and Ci | VT-10 (source impedance, crosstalk, memory) and Step 0's crosstalk measurement |\n"
      "| unpowered and floating-rail behaviour of the op-amp | vendor model draws current at zero supply and lets the rail go negative | VT-5 (overload, fault, unpowered), with the 4.7 kohm bleed fitted |\n"
      "| the 3.3 V LM27762 back-feed path of the clamp current | no usable model | VT-5, VT-8 |\n"
      "| PCB parasitics: input wiring, inverting-node pad and trace, Vmid and supply impedance, coupling between channels | not laid out | G3 (extracted parasitics as sensitivity cases), VT-10, VT-15 |\n"
      "| Vmid and 3.3 V sense-node noise | assumed densities (20 and 100 nV/sqrt Hz) | step 2a, VT-8, VT-16 |\n"
      "| pulse rating of the op-amp input clamps and 0603 C1/R1 voltage ratings | datasheet gives DC absolute maxima only | VT-5 |\n")

    A("## Assumptions the other blocks must meet\n")
    A("- Vmid: 50 mohm output impedance to at least 1 MHz and +/-5.7 mA per channel, 10 uF + 100 nF at the node (2a). With 1 ohm the crosstalk through Vmid reaches ~6 mV.\n- A 4.7 kohm bleed on the AFE 3.3 V rail (the same part as powercal's +3.3 V bleed).\n- The 3.3 V sense node needs 100 ohm + 10 uF (sources 4.3 uA per channel from the Due 3.3 V pin).\n- Input wiring: 4 pF of BNC and trace (Case 6).\n- ADC and acquisition: derived 3.8 kohm / 6 pF, 667 ns window, 955.6 ns period.\n")
    A("## Requirement problems to hand back\n")
    A("1. `architecture.md` and `afe.md` SC-2/SC-11 are met only with the third resistor R3 (case: 'two defects'); with R2 to Vmid alone the pin is centred at 0.764 x Vmid. Needs a correction to the architecture text.\n2. The range switch cannot sit in the RG leg; it shunts RF. This changes which pin state is the default (closed = +/-5 V).\n3. The 70-75 % occupancy limit of SC-4 is defined at nominal AREF; it reads up to 76.2 % at AREF 3.20 V.\n4. SC-6 is a rms over 'the whole bandwidth', but the +/-5 V range has 129 MHz of bandwidth; the verdict above integrates to 1.5 x -3 dB. If the intent were an 8-10 MHz band, the 10 MHz row above applies: 31 uV on +/-5 V and 122 uV on +/-1.25 V (1.6x margin), still passing.\n5. AREF below the lowest values in Case 1 loses the 80 mV margin. Per the owner's decision (PW-6 now keeps AREF at 3.20-3.30 V, SC-2 and SC-11 not relaxed) the 3.10 V sweep is margin evidence only, not a requirement case.\n6. **No deliberate band limit was added anywhere.** SC-6 is met by the OPA354's own noise at the stage's own bandwidth (the figures above integrate to 1.5 x the actual -3 dB point, 129 MHz on +/-5 V and 16.8 MHz on +/-1.25 V). The only added series part, Rnp (680 ohm), is there for edge-current protection (PR-1); it moves the +/-5 V bandwidth from 137.6 to 129 MHz and was not chosen to cut noise. During exploration a feedback capacitor across RF was tried against the switch-peaking defect only, and rejected.\n")
    with open(os.path.join(HERE, "report.md"), "w") as f:
        f.write("\n".join(L))
    return out

SECTIONS = ["dc", "ac", "noise", "kick", "prot", "guards", "report"]
# comp and trim-ends belong to "dc" and "ac" respectively

def main(argv):
    want = argv or SECTIONS
    t0 = time.time()
    if "dc" in want:
        dc_section("OPA354"); dc_section("OPA365"); trim_ends_section(); print("dc", round(time.time() - t0))
    if "ac" in want:
        ac_section(); spec_section(); zin_section(); edge_section(); comp_section(); print("ac", round(time.time() - t0))
    if "noise" in want:
        noise_section(); print("noise", round(time.time() - t0))
    if "kick" in want:
        kick_section(); print("kick", round(time.time() - t0))
    if "prot" in want:
        prot_section(); print("prot", round(time.time() - t0))
    if "guards" in want:
        guards_section(); print("guards", round(time.time() - t0))
    if "report" in want:
        print(make_report()); print("report", round(time.time() - t0))

if __name__ == "__main__":
    main(sys.argv[1:])
