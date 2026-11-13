#!/usr/bin/env python3
"""Version 2 scope channel: simulation driver.  Regenerates every number in report.md.

    python3 -I run.py [--out DIR] [--work DIR] [section ...]    sections: netlist cscan dc ac bw noise d17 tran stab beh prot xtalk static mc guards   (default: all)
    python3 -I report.py [DIR]                                  writes DIR/report.md from DIR/results/*.json

--range 5v (or 5vc, see RANGES) selects the scope range of version 1 (+-5 V nominal, usable +-6 V; owner 2026-11-13) with its values (RANGES below, a values
change on the same circuit) instead of version 2's -1.5..+3.5 V; the default, and every number it produces, is unchanged.
--set KEY=VALUE (repeatable) overrides a scalar of netlib.P0 for the run and is recorded in meta.json.
--out (default: this folder) gets results/*.json and scope_v2.cir; --work (default a temporary directory) gets netlists, wrdata
files and logs. Run in the PCB image (docker/pcb/run.sh); every deck goes through simtools.netlib_common.run_ng, under the memory
cap with a .save of the vectors it reads. The op-amp macro is simtools.vendor's derived copy of 3PEAK's TPH2501 (fetched by
tools/fetch_models.py, MC-6); its sha256 must equal models/VENDOR_MODEL.sha256 or the run stops.
"""
import sys, os, json, re, hashlib, itertools, contextlib
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import numpy as np
from netlib import *
import netlib as NL
from simtools import vendor

OUT_DIR = HERE
RES = os.path.join(OUT_DIR, "results")


def set_out(path):
    """Where results/*.json and scope_v2.cir are written."""
    global OUT_DIR, RES
    OUT_DIR = os.path.abspath(path)
    RES = os.path.join(OUT_DIR, "results")
    os.makedirs(RES, exist_ok=True)


EXPECT_SHA = open(os.path.join(HERE, "models", "VENDOR_MODEL.sha256")).read().split()[0]

# The three op-amp models.  vendor: the TPH2501 macro (noise, slew and distortion, no datasheet dynamics).  BEH21 and BEH60:
# the project's behavioural TPH2502, fitted to the datasheet's open-loop gain and phase (small signal only, no noise), with
# the open-loop output impedance of the table (21 ohm) and of the p6 curve's plateau (60 ohm, *(check)*).
BEH_LIB = str(vendor.tph2502_beh())
MODELS = {"vendor": ("TPH2501_simplify", NL.OPAMP_INC),
          "BEH21": ("TPH2502_BEH ro=21", BEH_LIB),
          "BEH60": ("TPH2502_BEH ro=60", BEH_LIB)}


@contextlib.contextmanager
def use_model(name):
    """Switch the op-amp model every netlist builder uses (netlib.SUB and the .include), then restore the vendor macro."""
    NL.SUB, NL.OPAMP_INC = MODELS[name]
    try:
        yield name
    finally:
        NL.SUB, NL.OPAMP_INC = MODELS["vendor"]


def beh_sha():
    return hashlib.sha256(open(BEH_LIB, "rb").read()).hexdigest()

LSB = lambda aref: aref / 4096.0
T_TRACK = 15 / 22.5e6      # ADC acquisition window: 15 ADC clocks at 22.5 MHz (afe.md SC-10)
T_CONV = 21.5 / 22.5e6     # aggregate period at 1,046,510 sps (sim/scope/run.py)
AREF_LO, AREF_HI = 3.20, 3.30
MARGIN, CENTRE = 0.080, 0.030
USABLE = (-2.0, 4.0)
RATED = (-1.5, 3.5)
RANGE = "v2"
# The input levels the sections drive.  "v2": the one range -1.5..+3.5 V centred on +1.0 V; "5v": version 1's +-5 V centred on 0 V, with
# the version 1 values in version 2's positions (range5v.md).  P0 holds the value overrides of netlib.P0 (empty: the design's own).
RANGES = {
    "v2": dict(USABLE=(-2.0, 4.0), RATED=(-1.5, 3.5), SPAN_V=5.0, CEN_IN=1.0, LEVELS=(-2.0, -1.0, 0.0, 1.0, 2.0, 3.0, 4.0), KICK=(4.0, -2.0),
               STEP=(-1.5, 1.0), SINE_RATED_VPP=5.0, SINE_USABLE_VPP=6.0, PROT_DC=((12, 12), (-12, -12), (12, -12), (3.5, 3.5), (-2, -2)),
               XT_DC=1.0, XT_AMP=3.0, MUT_C1=12e-12, P0={}),
    "5v": dict(USABLE=(-6.0, 6.0), RATED=(-5.0, 5.0), SPAN_V=10.0, CEN_IN=0.0, LEVELS=(-6.0, -4.0, -2.0, 0.0, 2.0, 4.0, 6.0), KICK=(6.0, -6.0),
               STEP=(-5.0, 0.0), SINE_RATED_VPP=10.0, SINE_USABLE_VPP=12.0, PROT_DC=((12, 12), (-12, -12), (12, -12), (5, 5), (-5, -5)),
               XT_DC=0.0, XT_AMP=6.0, MUT_C1=22e-12,
               P0=dict(R1=(470e3, 300e3), R2=(470e3, 330e3), R3=(330e3, 0.0), C1=12e-12, Cn=30e-12)),
}
# "5vc": the same with C1 18 pF (C1647) and Cn 47 pF (C1671) in place of 12 and 30: the best two-capacitor pair of section cscan on these resistors
RANGES["5vc"] = dict(RANGES["5v"], MUT_C1=33e-12, P0=dict(RANGES["5v"]["P0"], C1=18e-12, Cn=47e-12))
SPAN_V, CEN_IN, LEVELS, KICK, STEP = 5.0, 1.0, RANGES["v2"]["LEVELS"], RANGES["v2"]["KICK"], RANGES["v2"]["STEP"]
SINE_RATED_VPP, SINE_USABLE_VPP, PROT_DC, XT_DC, XT_AMP, MUT_C1 = 5.0, 6.0, RANGES["v2"]["PROT_DC"], 1.0, 3.0, 12e-12


LCSC_C0G = {12: "C38523", 18: "C1647", 30: "C1658", 47: "C1671"}      # 0603 C0G 5 %, v2/jlc-basic.csv


def set_range(name):
    """Select a range profile: the module's level constants and, for a range other than the design's, netlib.P0's values."""
    global USABLE, RATED, RANGE, SPAN_V, CEN_IN, LEVELS, KICK, STEP, SINE_RATED_VPP, SINE_USABLE_VPP, PROT_DC, XT_DC, XT_AMP, MUT_C1
    g = RANGES[name]
    RANGE, USABLE, RATED, SPAN_V, CEN_IN, LEVELS, KICK, STEP = name, g["USABLE"], g["RATED"], g["SPAN_V"], g["CEN_IN"], g["LEVELS"], g["KICK"], g["STEP"]
    SINE_RATED_VPP, SINE_USABLE_VPP, PROT_DC, XT_DC, XT_AMP, MUT_C1 = g["SINE_RATED_VPP"], g["SINE_USABLE_VPP"], g["PROT_DC"], g["XT_DC"], g["XT_AMP"], g["MUT_C1"]
    NL.P0.update(g["P0"])
VOS_MAX = 0.5e-3           # TPH2502 datasheet: +-500 uV max (page 3)
CMRR_ERR = 3.0 * 10 ** (-65 / 20)   # 65 dB min over VCM -1..3 V at VS 5.4 V *(check at 3.3 V)*: 1.7 mV, worst case


def save(name, obj):
    with open(os.path.join(RES, name + ".json"), "w") as f:
        json.dump(obj, f, indent=1, default=lambda o: o.tolist() if hasattr(o, 'tolist') else float(o))
    return obj


def loadj(name):
    with open(os.path.join(RES, name + ".json")) as f:
        return json.load(f)


def pp(**kw):
    q = dict(P0)
    q.update(kw)
    return q


def check_model():
    h = hashlib.sha256(open(OPAMP_MDL, "rb").read()).hexdigest()
    if h != EXPECT_SHA:
        sys.exit(f"vendor macro hash {h} != {EXPECT_SHA}: the model changed; re-read models/VENDOR_MODEL.sha256")
    return h


# ---------------------------------------------------------------------------------------------------------------
# Closed-form network (checked against ngspice at nominal and at random draws, section mc)
# ---------------------------------------------------------------------------------------------------------------
def net(r1, r2, r3, vr, vin=0.0):
    rp = 1 / (1 / r1 + 1 / r2 + 1 / r3)
    a = rp / r1
    voff = vr * rp / r3
    return a, voff, r1 + 1 / (1 / r2 + 1 / r3), rp


def parts(p):
    return np.array(list(p["R1"]) + list(p["R2"]) + list(p["R3"]), dtype=float)


# ---------------------------------------------------------------------------------------------------------------
def sec_dc():
    p = pp()
    vs = np.arange(USABLE[0], USABLE[1] + 0.001, 0.5)
    t = header("dc") + rails(p) + "Vs asrc 0 dc 0\n" + chan(p, "a") + f"""
.control
dc Vs {USABLE[0]:g} {USABLE[1]:g} 0.5
wrdata {wr('dc','d')} v(apin) v(an) i(Vr) i(Vcc)
.endc
.end
"""
    run_ng("dc", t)
    d = load("dc", "d")
    pin, nn, ir = d[:, 1], d[:, 3], d[:, 5]
    r1, r2, r3 = (rsum(p[k]) for k in ("R1", "R2", "R3"))
    a, voff, rin, rp = net(r1, r2, r3, p["vr"])
    ana = voff + a * vs
    out = dict(vin=vs, pin=pin, N=nn, pin_analytic=ana, max_dev_mV=float(np.abs(pin - ana).max() * 1e3),
               a=a, voff=voff, rin=rin, rp=rp, mV_per_code_at_3p25=3.25 / 4096 / a * 1e3,
               span_pct_FS_3p25=SPAN_V * a / 3.25 * 100, ref_current_uA=(-ir * 1e6))
    save("dc", out)
    return out


def sec_ac():
    p = pp(Rsrc=50.0)
    t = header("ac") + rails(p) + "Vs asrc 0 dc 0 ac 1\n" + chan(p, "a") + f"""
.control
ac dec 40 10 2g
wrdata {wr('ac','h')} v(apin) v(an) v(aout)
.endc
.end
"""
    run_ng("ac", t)
    d = load("ac", "h")
    f = d[:, 0]
    h = d[:, 1] + 1j * d[:, 2]
    hn = d[:, 4] + 1j * d[:, 5]
    r1, r2, r3 = (rsum(p[k]) for k in ("R1", "R2", "R3"))
    a, voff, rin, rp = net(r1, r2, r3, p["vr"])
    ref = abs(h[np.argmin(abs(f - 10.0))])
    g = lambda ff: abs(h[np.argmin(abs(f - ff))])
    db = 20 * np.log10(np.abs(h) / ref)
    i3 = np.where(db < -3)[0]
    f3 = float(f[i3[0]]) if len(i3) else None
    band = (f >= 1e5) & (f <= 1e7)
    out = dict(a_dc=a, gain_10Hz=ref, gain_100kHz=g(1e5), gain_1MHz=g(1e6), gain_10MHz=g(1e7),
               shelf_pct=(g(1e5) / ref - 1) * 100, f3dB_Hz=f3,
               dev_10MHz_dB=float(20 * np.log10(g(1e7) / g(1e5))), peak_dB_over_100k=float(db[f >= 1e5].max() - db[np.argmin(abs(f - 1e5))]),
               gain_dB_at={str(x): float(20 * np.log10(g(x) / g(1e5))) for x in (1e6, 3e6, 5e6, 8e6, 1e7, 3e7, 1e8)},
               phase_deg_10MHz=float(np.degrees(np.angle(h[np.argmin(abs(f - 1e7))]))))
    # input impedance: drive the input from an ideal source, read the current
    q = pp(Rsrc=0.0001)
    t = header("zin") + rails(q) + "Vs asrc 0 dc 0 ac 1\n" + chan(q, "a") + f"""
.control
ac dec 20 100 100meg
wrdata {wr('zin','y')} i(Vs)
.endc
.end
"""
    run_ng("zin", t)
    d = load("zin", "y")
    ff = d[:, 0]
    y = -(d[:, 1] + 1j * d[:, 2])
    cin = {}
    for x in (1e3, 1e4, 1e5, 1e6, 1e7):
        i = np.argmin(abs(ff - x))
        cin[str(int(x))] = dict(R_k=float(1 / y[i].real / 1e3), C_pF=float(y[i].imag / (2 * np.pi * ff[i]) * 1e12))
    # input C without the 4 pF BNC/trace assumption
    out["zin"] = cin
    out["cin_no_wire_pF_10kHz..1MHz"] = [cin["10000"]["C_pF"] - p["Cwire"] * 1e12, cin["1000000"]["C_pF"] - p["Cwire"] * 1e12]
    # x10 probe: 9 Mohm || Cp from an ideal source.  Scan Cp for the flattest response, report residual ripple.
    rows = []

    def probe_ripple(cp):
        q = pp(Rsrc=0.0001)
        body = chan(q, "a").replace(f"Rsa asrc ain {q['Rsrc']:.6g}\n", "")
        t = header("px10") + rails(q) + f"Vs asrc 0 dc 0 ac 1\nRprobe asrc ain 9meg\nCprobe asrc ain {cp:.6g}\n" + body + f"""
.control
ac dec 20 10 20meg
wrdata {wr('px10','h')} v(apin)
.endc
.end
"""
        run_ng("px10", t)
        d = load("px10", "h")
        f = d[:, 0]
        m = np.abs(d[:, 1] + 1j * d[:, 2])
        k = f <= 10e6                      # D13: nothing is asked above 10 MHz; the stage's own roll-off (Cpx) is above it
        return (m[k].max() - m[k].min()) / m[k].mean(), (m.max() - m.min()) / m.mean()

    for cp in np.arange(1.0, 4.01, 0.25) * 1e-12:
        rows.append((cp * 1e12, probe_ripple(cp)[0] * 100))
    c0 = min(rows, key=lambda r: r[1])[0]
    for cp in np.arange(c0 - 0.25, c0 + 0.251, 0.025):
        rows.append((float(cp), probe_ripple(cp * 1e-12)[0] * 100))
    best = min(rows, key=lambda r: r[1])
    r10, r20 = probe_ripple(best[0] * 1e-12)
    out["probe_x10"] = dict(rows=rows, best_Cp_pF=best[0], best_ripple_pct=r10 * 100, ripple_to_20MHz_pct=r20 * 100)
    save("ac", out)
    return out


def sec_noise():
    p = pp(Rsrc=50.0)
    t = header("noise") + rails(p) + "Vs asrc 0 dc 0 ac 1\n" + chan(p, "a") + f"""
.control
noise v(apin) Vs dec 20 1 1g
setplot noise1
wrdata {wr('noise','n')} onoise_spectrum
.endc
.end
"""
    run_ng("noise", t)
    d = load("noise", "n")
    f, on = d[:, 0], d[:, 1]            # V/sqrt(Hz) at the pin
    trap = lambda x, y, lo, hi: float(np.sqrt(np.trapezoid(y[(x >= lo) & (x <= hi)] ** 2, x[(x >= lo) & (x <= hi)])))
    # model-only reference: unity follower, ideal source at the + input, no network
    t2 = header("noise0") + rails(p) + "Vs np0 0 dc 1.5 ac 1\nXU np0 out vccl 0 out " + NL.SUB + "\nRl out 0 1meg\n.control\nnoise v(out) Vs dec 20 1 1g\nsetplot noise1\nwrdata " + wr('noise0', 'n') + " onoise_spectrum\n.endc\n.end\n"
    run_ng("noise0", t2)
    d0 = load("noise0", "n")
    f0, on0 = d0[:, 0], d0[:, 1]
    at = lambda x, y, ff: float(y[np.argmin(abs(x - ff))])
    # the REF3030E: 51 uV rms 10 Hz-10 kHz (ref30.pdf 6.5), coupled to the pin by Rp/R3, bandwidth set by Rp(C1+Cn)
    r1, r2, r3 = (rsum(p[k]) for k in ("R1", "R2", "R3"))
    a, voff, rin, rp = net(r1, r2, r3, p["vr"])
    ref_pin = 51e-6 * rp / r3
    out = dict(density_nV=dict((str(x), at(f, on, x) * 1e9) for x in (1e3, 1e4, 1e5, 1e6, 1e7, 1e8)),
               macro_only_density_nV=dict((str(x), at(f0, on0, x) * 1e9) for x in (1e3, 1e5, 1e6, 1e7, 1e8)),
               rms_10Hz_10MHz_uV=trap(f, on, 10, 1e7) * 1e6, rms_10Hz_1GHz_uV=trap(f, on, 10, 1e9) * 1e6,
               rms_10Hz_100MHz_uV=trap(f, on, 10, 1e8) * 1e6,
               macro_rms_10Hz_10MHz_uV=trap(f0, on0, 10, 1e7) * 1e6, macro_rms_10Hz_1GHz_uV=trap(f0, on0, 10, 1e9) * 1e6,
               ref_at_pin_uV=ref_pin * 1e6, datasheet_en_nV=6.5,
               rp_thermal_nV_at_N=float(np.sqrt(4 * 1.380649e-23 * 300 * rp) * 1e9),
               node_pole_Hz=float(1 / (2 * np.pi * rp * (p["C1"] + p["Cn"] + p["Cpx"] + p["Cn_par"] + 0.5e-12))))
    out["total_10Hz_1GHz_uV"] = float(np.hypot(out["rms_10Hz_1GHz_uV"], ref_pin * 1e6))
    out["total_10Hz_10MHz_uV"] = float(np.hypot(out["rms_10Hz_10MHz_uV"], ref_pin * 1e6))
    # what a Basic-C0G limit at the pin would buy: Riso + C at the pin (corner f = 1/(2 pi R C))
    lim = []
    for riso, c in ((22, 47e-12), (100, 47e-12), (100, 100e-12), (150, 100e-12), (22, 330e-12), (220, 330e-12)):
        fc = 1 / (2 * np.pi * (riso + 0) * c)
        w = on * 1 / np.sqrt(1 + (f / fc) ** 2)
        lim.append(dict(Riso=riso, C_pF=c * 1e12, corner_MHz=fc / 1e6, rms_uV=trap(f, w, 10, 1e9) * 1e6,
                        gain_10MHz_dB=float(-10 * np.log10(1 + (1e7 / fc) ** 2))))
    out["limit_options"] = lim
    save("noise", out)
    return out


def sine_tran(p, f0, vpp, vcen, ncyc=14, name="sine", tstep=0.05e-9):
    """Full-scale sine at the BNC through 50 ohm; returns THD and the largest |dv/dt| at the pin."""
    per = 1 / f0
    t = header(name) + rails(p) + f"Vs asrc 0 sin({vcen} {vpp/2} {f0})\n" + chan(p, "a") + f"""
.control
tran {tstep} {ncyc*per} 0 {tstep}
wrdata {wr(name,'t')} v(apin) v(aout) v(an)
.endc
.end
"""
    run_ng(name, t)
    d = load(name, "t")
    tt = d[:, 0]
    # uniform grid over the last 8 whole cycles
    n8 = 8
    t0 = (ncyc - n8) * per
    npt = 8 * 1024
    tg = t0 + np.arange(npt) * (n8 * per / npt)
    v = np.interp(tg, tt, d[:, 1])
    spec = np.abs(np.fft.rfft(v * np.hanning(npt) if False else v)) / npt * 2
    k1 = n8
    fund = spec[k1]
    harm = [spec[k1 * m] for m in range(2, 10) if k1 * m < len(spec)]
    thd = float(np.sqrt(sum(h * h for h in harm)) / fund)
    sl = float(np.abs(np.diff(np.interp(np.arange(t0, ncyc * per, 0.05e-9), tt, d[:, 1]))).max() / 0.05e-9 / 1e6)
    return dict(f0=f0, vpp_in=vpp, fund_pin_V=float(fund), thd_pct=thd * 100, thd_dB=float(20 * np.log10(max(thd, 1e-12))),
                slew_pin_Vus=sl, vmin=float(v.min()), vmax=float(v.max()), h2=float(harm[0] / fund), h3=float(harm[1] / fund))


def kick_run(p, vina, vinb, adc, name="kick", ncyc=7, aref=3.3):
    """Both channels, one ADC S/H: A tracks for 15 ADC clocks, B the next 15, repeating at the aggregate period of
    21.5 clocks.  Returns the S/H error at the end of each window against that channel's DC pin value, in LSB."""
    t0 = 100e-9
    per2 = 2 * T_CONV
    txt = header(name) + rails(p) + f"Vina asrc 0 dc {vina}\nVinb bsrc 0 dc {vinb}\n" + chan(p, "a") + chan(p, "b") + f"""
.model swm sw(vt=0.5 vh=0.1 ron=0.001 roff=1e12)
Sa apin mx ctla 0 swm
Sb bpin mx ctlb 0 swm
Radc mx cs {adc['ron']}
Cs cs 0 {adc['cs']}
Vca ctla 0 pulse(0 1 {t0} 1n 1n {T_TRACK} {per2})
Vcb ctlb 0 pulse(0 1 {t0 + T_CONV} 1n 1n {T_TRACK} {per2})
.control
op
print v(apin) v(bpin)
tran 0.25n {t0 + ncyc * per2} 0 0.25n
wrdata {wr(name,'k')} v(cs)
.endc
.end
"""
    out = run_ng(name, txt)
    d = load(name, "k")
    t, v = d[:, 0], d[:, 1]
    va = float(re.search(r"v\(apin\)\s*=\s*([-0-9.eE+]+)", out).group(1))
    vb = float(re.search(r"v\(bpin\)\s*=\s*([-0-9.eE+]+)", out).group(1))
    lsb = LSB(aref)
    ea, eb, st = [], [], []
    for k in range(ncyc - 3, ncyc):
        ta = t0 + k * per2 + T_TRACK - 2e-9
        tb = t0 + k * per2 + T_CONV + T_TRACK - 2e-9
        ea.append((np.interp(ta, t, v) - va) / lsb)
        eb.append((np.interp(tb, t, v) - vb) / lsb)
        m = (t >= t0 + k * per2 + T_CONV) & (t <= tb + 2e-9)
        bad = np.where(np.abs(v[m] - vb) > 0.5 * lsb)[0]
        st.append((t[m][bad[-1]] - (t0 + k * per2 + T_CONV)) * 1e9 if len(bad) else 0.0)
    return dict(vpin_a=va, vpin_b=vb, err_a_lsb=float(np.mean(ea)), err_b_lsb=float(np.mean(eb)), settle_b_ns=float(max(st)))


def sec_tran():
    p = pp()
    out = {}
    out["sine5_fs"] = sine_tran(p, 5e6, SINE_RATED_VPP, CEN_IN, name="s5a")             # rated: -1.5..+3.5 V (5v: +-5 V)
    out["sine5_usable"] = sine_tran(p, 5e6, SINE_USABLE_VPP, CEN_IN, name="s5b")         # usable: -2..+4 V (5v: +-6 V)
    out["sine10_usable"] = sine_tran(p, 10e6, SINE_USABLE_VPP, CEN_IN, name="s10b")
    out["sine1_usable"] = sine_tran(p, 1e6, SINE_USABLE_VPP, CEN_IN, name="s1b")
    # control: the macro's own slew limit, driven past it (must show distortion, else the THD test cannot fail)
    out["sine40_control"] = sine_tran(p, 40e6, SINE_USABLE_VPP, CEN_IN, name="s40", ncyc=16, tstep=0.02e-9)
    # step response: 2.5 V step, 5 ns edge, 50 ohm source
    t = header("step") + rails(p) + f"Vs asrc 0 pulse({STEP[0]:g} {STEP[1]:g} 20n 5n 5n 400n 1u)\n" + chan(p, "a") + f"""
.control
tran 0.1n 300n 0 0.1n
wrdata {wr('step','s')} v(apin)
.endc
.end
"""
    run_ng("step", t)
    d = load("step", "s")
    tt, v = d[:, 0], d[:, 1]
    v0 = np.interp(15e-9, tt, v)
    v1 = np.interp(280e-9, tt, v)
    dv = v1 - v0
    m = (tt > 20e-9) & (tt < 200e-9)
    tr10 = tt[m][np.argmax(v[m] >= v0 + 0.1 * dv)]
    tr90 = tt[m][np.argmax(v[m] >= v0 + 0.9 * dv)]
    over = (v[m].max() - v1) / dv * 100
    sett = tt[m][np.where(np.abs(v[m] - v1) > 0.005 * dv)[0][-1]] - 20e-9
    out["step"] = dict(step_pin_V=float(dv), rise_10_90_ns=float((tr90 - tr10) * 1e9), overshoot_pct=float(over), settle_0p5pct_ns=float(sett * 1e9))
    # SC-10 / AN-2: alternating full-swing channels through one S/H.  A at +4 V (high pin), B at -2 V (low pin)
    adc = P0["adc"]
    out["sh_derived"] = kick_run(p, KICK[0], KICK[1], adc, name="k1")
    out["sh_derived_rev"] = kick_run(p, KICK[1], KICK[0], adc, name="k2")
    out["sh_stress"] = kick_run(p, KICK[0], KICK[1], dict(ron=1.0e3, cs=8e-12), name="k3")
    out["sh_control_riso20k"] = kick_run(pp(Riso=20e3), KICK[0], KICK[1], adc, name="k4")
    # the one-part bandwidth limit option at the pin: Riso 100 ohm and 47 pF C0G (corner 34 MHz)
    lim = pp(Riso=100.0, Cpin=2e-12 + 47e-12)
    out["sh_limit_option"] = kick_run(lim, KICK[0], KICK[1], adc, name="k5")
    out["sh_limit_option_stress"] = kick_run(lim, KICK[0], KICK[1], dict(ron=1.0e3, cs=8e-12), name="k6")
    out["limit_option_pm"] = loop_pm(lim)
    out["T_TRACK_ns"] = T_TRACK * 1e9
    # pin source impedance
    t = header("zout") + rails(p) + "Vs asrc 0 dc 0\n" + chan(p, "a").replace("Dpa", "Dpa") + f"""
Iz 0 apin dc 0 ac 1
.control
ac dec 20 1k 300meg
wrdata {wr('zout','z')} v(apin)
.endc
.end
"""
    run_ng("zout", t)
    d = load("zout", "z")
    z = np.abs(d[:, 1] + 1j * d[:, 2])
    out["zout_pin"] = dict(max_ohm_to_10MHz=float(z[d[:, 0] <= 1e7].max()), ohm_at_1MHz=float(z[np.argmin(abs(d[:, 0] - 1e6))]),
                           ohm_at_100MHz=float(z[np.argmin(abs(d[:, 0] - 1e8))]))
    save("tran", out)
    return out


def loop_pm(p, cload=0.0, adc=True):
    t = header("lb") + rails(p) + "Vs asrc 0 dc 0\n" + chan(p, "a", loopbreak=True) + (
        f"Radc apin cs {p['adc']['ron']}\nCs cs 0 {p['adc']['cs']}\n" if adc else "") + (f"Cl apin 0 {cload}\n" if cload else "") + f"""
.control
ac dec 60 1k 3g
let T = -v(aouta)/v(aout)
wrdata {wr('lb','t')} db(T) 180/pi*cph(T)
.endc
.end
"""
    run_ng("lb", t)
    d = load("lb", "t")
    f, m, ph = d[:, 0], d[:, 1], d[:, 3]
    i = np.where((m[:-1] > 0) & (m[1:] <= 0))[0]
    if not len(i):
        return dict(fc_MHz=None, pm=None)
    i = i[0]
    pm = 180 + ph[i]
    # gain margin: where phase crosses -180
    j = np.where((ph[:-1] > -180) & (ph[1:] <= -180))[0]
    gm = float(-m[j[0]]) if len(j) else None
    return dict(fc_MHz=float(f[i] / 1e6), pm_deg=float(pm), gm_dB=gm)


def stab_one(model):
    """AN-1 for one op-amp model: loop gain broken at the amplifier output, the ADC S/H on the pin."""
    out = {}
    with use_model(model):
        base = pp()
        out["nominal"] = loop_pm(base)
        out["RF25"] = loop_pm(pp(RF=25.0))
        out["noRiso"] = loop_pm(pp(Riso=0.001))
        grid = []
        for riso in (0.001, 10, 22, 47, 100):
            for cl in (0, 10e-12, 22e-12, 47e-12, 100e-12):
                r = loop_pm(pp(Riso=riso), cload=cl)
                grid.append(dict(Riso=riso, Cload_pF=cl * 1e12, **r))
        out["grid"] = grid
        # closed-loop peaking at the pin, Riso 22, for the nominal pin and a heavier one
        for lab, cl in (("pin_nominal", 0.0), ("pin_plus_22pF", 22e-12)):
            p = pp()
            t = header("pk") + rails(p) + "Vs asrc 0 dc 0 ac 1\n" + chan(p, "a") + (f"Cl apin 0 {cl}\n" if cl else "") + f"""
.control
ac dec 60 1e5 2g
wrdata {wr('pk','h')} v(apin)
.endc
.end
"""
            run_ng("pk", t)
            d = load("pk", "h")
            m = np.abs(d[:, 1] + 1j * d[:, 2])
            out["peak_" + lab] = dict(peak_dB=float(20 * np.log10(m.max() / m[0])))
    return out


def sec_stab():
    out = {m: stab_one(m) for m in MODELS}
    save("stab", out)
    return out


def sec_beh():
    """AN-1 against the datasheet-fitted models (the vendor macro had read 55.7 degrees; the datasheet's open-loop phase gives
    about 56 degrees of the amplifier alone and Rnp x the differential input capacitance takes the rest).  PM, over 0, 8 and 18 pF
    added at the pin (Cpin 2 pF is already there, as is the ADC S/H), by Cpx, for the three models; Cpx = 0 is the control."""
    out = {"cpx_scan": {}}
    for cx in (0.0, 2.2e-12, 3.3e-12, 4.7e-12, 6.8e-12, 10e-12, 15e-12):
        row = {}
        for m in MODELS:
            with use_model(m):
                pm = [loop_pm(pp(Cpx=cx), cload=c)["pm_deg"] for c in (0, 8e-12, 18e-12)]
            row[m] = min(pm)
        row["pole_MHz"] = (1 / (2 * np.pi * 470.0 * cx) / 1e6) if cx else None
        row["min_all"] = min(row[m] for m in MODELS)
        out["cpx_scan"][f"{cx*1e12:g}"] = row
    save("beh", out)
    return out


# ---------------------------------------------------------------------------------------------------------------
# The ADC input the stage drives: the sampling capacitor behind the input switch.  Neither figure is measured in this
# repository: 3.8 kohm / 6 pF is derived from the SAM3X track-time formula (0.054 ns per ohm + 205 ns, docs/ets.md says "nothing
# confirms" the switch resistance) and 1 kohm / 8 pF is the v1 study's low-resistance stress arm (Ci max 8 pF).  For NOISE the
# low resistance is the worst case, because it widens the band the sampling capacitor sees.   *(check)*
ADC_CASES = {"derived": dict(ron=3.8e3, cs=6e-12), "lowR": dict(ron=1.0e3, cs=8e-12)}
EN_DS = 6.5e-9          # TPH2502 datasheet voltage noise density, V/rtHz (the figure design.md and afe.md quote); held flat to 1 GHz *(check)*
EN_VENDOR = 9.3e-9      # the vendor macro's density (section noise)
REF_NOISE_PIN_UV = lambda p: 51.0 * (lambda r1, r2, r3: (1 / (1 / r1 + 1 / r2 + 1 / r3)) / r3)(*(rsum(p[k]) for k in ("R1", "R2", "R3")))   # ref30.pdf 6.5: 51 uV 10 Hz-10 kHz, to the pin by Rp/R3


def adc_net(adc, noisy=False, pin="apin", sw="sw"):
    """The ADC input: switch resistance from the pin to the sampling capacitor.  The switch's own thermal noise is the Due's
    (kT/Cs, inside the 0.64-0.68 mV floor SC-6 is measured against) and is left out unless noisy=True."""
    return f"Radc {pin} {sw} {adc['ron']:.6g}{'' if noisy else ' noisy=0'}\nCs {sw} 0 {adc['cs']:.6g}\n"


def integ(f, y2, lo=10.0, hi=1e9):
    """Integral of a power density (V^2/Hz) over lo..hi, on a log-spaced grid, trapezoid in ln f."""
    k = (f >= lo) & (f <= hi)
    return float(np.sqrt(np.trapezoid(f[k] * y2[k], np.log(f[k]))))


def sec_bw():
    """SM-3 with the ADC input attached: the closed-loop response at the pin with the switch closed (sampling capacitor
    hanging on it), and at the sampling capacitor itself (which adds the Due's own switch pole), against the 100 kHz gain."""
    out = {}
    for m in MODELS:
        out[m] = {}
        with use_model(m):
            for lab, adc in (("pin_only", None), ("derived", ADC_CASES["derived"]), ("lowR", ADC_CASES["lowR"])):
                p = pp(Rsrc=50.0)
                t = header("bw") + rails(p) + "Vs asrc 0 dc 0 ac 1\n" + chan(p, "a") + (adc_net(adc) if adc else "") + f"""
.control
ac dec 60 1k 2g
wrdata {wr('bw','h')} v(apin) {'v(sw)' if adc else 'v(apin)'}
.endc
.end
"""
                run_ng("bw", t)
                d = load("bw", "h")
                f = d[:, 0]
                row = {}
                for nm, col in (("pin", 1), ("sw", 4)):
                    h = np.abs(d[:, col] + 1j * d[:, col + 1])
                    ref = h[np.argmin(abs(f - 1e5))]
                    db = 20 * np.log10(h / ref)
                    i3 = np.where((f > 1e5) & (db < -3))[0]
                    row[nm] = dict(f3dB_MHz=float(f[i3[0]] / 1e6) if len(i3) else None,
                                   dB_8MHz=float(db[np.argmin(abs(f - 8e6))]), dB_10MHz=float(db[np.argmin(abs(f - 10e6))]),
                                   peak_dB=float(db[f >= 1e5].max()))
                out[m][lab] = row
    save("bw", out)
    return out


def d17_noise(model, adc, en=None, noisy=False, p=None, inj=True, hi=1e9):
    """D17: noise integrated at the sampling capacitor, 10 Hz to 1 GHz, with the Due's switch resistance noiseless.
    vendor macro (en None): ngspice .noise includes the macro's own noise.  BEH models are noiseless: their amplifier
    noise is en (V/rtHz, flat) times the simulated transfer from the +IN pin to the sampling capacitor.  The REF3030E's
    noise at the pin is added in quadrature, as in section noise.  Returns uV."""
    p = p or pp(Rsrc=50.0)
    with use_model(model):
        t = header("d17n") + rails(p) + "Vs asrc 0 dc 0 ac 1\n" + chan(p, "a") + (adc_net(adc, noisy) if adc else "") + f"""
.control
noise v({'sw' if adc else 'apin'}) Vs dec 40 1 1g
setplot noise1
wrdata {wr('d17n','n')} onoise_spectrum
.endc
.end
"""
        run_ng("d17n", t)
        d = load("d17n", "n")
        res = integ(d[:, 0], d[:, 1] ** 2, hi=hi)
        amp = None
        if en is not None:
            t = header("d17h") + rails(p) + "Vs asrc 0 dc 0 ac 0\n" + chan(p, "a", inj=inj) + (adc_net(adc, noisy) if adc else "") + f"""
.control
ac dec 40 10 2g
wrdata {wr('d17h','h')} v({'sw' if adc else 'apin'})
.endc
.end
"""
            run_ng("d17h", t)
            h = load("d17h", "h")
            H = np.abs(h[:, 1] + 1j * h[:, 2])
            amp = integ(h[:, 0], (en * H) ** 2, hi=hi)
            hi = float(np.sqrt(np.trapezoid(h[h[:, 0] >= 1e8, 0] * (en * H[h[:, 0] >= 1e8]) ** 2, np.log(h[h[:, 0] >= 1e8, 0])))) if (h[:, 0] >= 1e8).any() else 0.0
    ref = REF_NOISE_PIN_UV(p) * 1e-6
    tot = float(np.sqrt(res ** 2 + (amp or 0.0) ** 2 + ref ** 2))
    return dict(total_uV=tot * 1e6, ngspice_uV=res * 1e6, amp_uV=(amp * 1e6 if amp is not None else None),
                ref_uV=ref * 1e6, amp_above_100MHz_uV=(hi * 1e6 if amp is not None else None), H_lf=(float(H[0]) if en is not None else None))


def sec_d17():
    """SC-6 as D17 defines it: the noise that reaches the Due's sampling capacitor, through the stage and the ADC input network."""
    out = {"en_datasheet_nV": EN_DS * 1e9, "en_vendor_nV": EN_VENDOR * 1e9, "adc_cases": ADC_CASES}
    rows = {}
    for lab, adc in ADC_CASES.items():
        rows[f"vendor|{lab}"] = d17_noise("vendor", adc)
        for m in ("BEH21", "BEH60"):
            rows[f"{m}+6.5|{lab}"] = d17_noise(m, adc, en=EN_DS)
            rows[f"{m}+9.3|{lab}"] = d17_noise(m, adc, en=EN_VENDOR)       # the pipeline against the vendor run (same density)
    out["rows"] = rows
    # the same figure at the pin to 1 GHz with no ADC network (the old reading of SC-6), vendor macro and BEH + datasheet density
    out["pin_1GHz_no_network"] = {"vendor": d17_noise("vendor", None), "BEH21+6.5": d17_noise("BEH21", None, en=EN_DS),
                                  "BEH60+6.5": d17_noise("BEH60", None, en=EN_DS)}
    # switch resistance sweep (Cs 6 pF): where does the figure reach 200 uV?
    sweep = []
    for ron in (100.0, 250.0, 500.0, 1e3, 2e3, 3.8e3, 6e3):
        adc = dict(ron=ron, cs=6e-12)
        sweep.append(dict(Rsw_ohm=ron, vendor=d17_noise("vendor", adc)["total_uV"],
                          BEH21_ds=d17_noise("BEH21", adc, en=EN_DS)["total_uV"], BEH60_ds=d17_noise("BEH60", adc, en=EN_DS)["total_uV"]))
    out["sweep_Rsw_Cs6pF"] = sweep
    for key in ("vendor", "BEH21_ds", "BEH60_ds"):
        xs = np.array([r["Rsw_ohm"] for r in sweep]); ys = np.array([r[key] for r in sweep])
        out[f"Rsw_for_200uV_{key}_ohm"] = float(np.interp(200.0, ys[::-1], xs[::-1])) if ys.max() >= 200 else None
    # the one-part bandwidth limit that was held back as a fallback (Riso 100 ohm, 47 pF C0G more at the pin): what it buys under D17
    lim = pp(Rsrc=50.0, Riso=100.0, Cpin=2e-12 + 47e-12)
    out["limit_option"] = {lab: dict(vendor=d17_noise("vendor", adc, p=lim)["total_uV"], BEH21_ds=d17_noise("BEH21", adc, en=EN_DS, p=lim)["total_uV"],
                                     BEH60_ds=d17_noise("BEH60", adc, en=EN_DS, p=lim)["total_uV"]) for lab, adc in ADC_CASES.items()}
    # the limit the 4 densities ask: the density at the sampling capacitor, 63 nV/rtHz over 10 MHz (afe.md SC-6) is not
    # what D17 reads: report the equivalent-noise-bandwidth of the whole path so the reader can see what bandwidth the figure uses
    worst = max(out["rows"][k]["total_uV"] for k in rows if "+9.3" not in k)
    out["worst_uV"] = worst
    out["worst_vendor_uV"] = max(out["rows"][f"vendor|{l}"]["total_uV"] for l in ADC_CASES)
    out["worst_datasheet_uV"] = max(out["rows"][f"{m}+6.5|{l}"]["total_uV"] for m in ("BEH21", "BEH60") for l in ADC_CASES)
    save("d17", out)
    return out


# ---------------------------------------------------------------------------------------------------------------
def sec_static():
    """Is the high-frequency step static?  The step is the gain above the divider's node pole over the DC gain.  It must not
    move with input level.  The C0G caps are linear by construction in the simulation, so a level sweep of the circuit can only
    show a level dependence that comes from the amplifier or the pin clamp; the positive control is a capacitor that does
    depend on its bias (an X7R-like characteristic) in the same places, which must move the step."""
    levels = LEVELS

    def step_at(vin, model, c1_expr=None, cn_expr=None):
        p = pp(Rsrc=0.0001)
        body = chan(p, "a")
        if c1_expr:
            body = re.sub(r"^C1a ain an \S+$", f"C1a ain an c='{c1_expr}'", body, flags=re.M)
            assert c1_expr in body
        if cn_expr:
            body = re.sub(r"^Cna an 0 \S+$", f"Cna an 0 c='{cn_expr}'", body, flags=re.M)
            assert cn_expr in body
        with use_model(model):
            t = header("stat") + rails(p) + f"Vs asrc 0 dc {vin} ac 1\n" + body + f"""
.control
op
ac dec 10 10 10meg
wrdata {wr('stat','h')} v(apin)
.endc
.end
"""
            run_ng("stat", t)
        d = load("stat", "h")
        f = d[:, 0]
        h = np.abs(d[:, 1] + 1j * d[:, 2])
        g = lambda ff: h[np.argmin(abs(f - ff))]
        return dict(step_100kHz_pct=float((g(1e5) / g(10.0) - 1) * 100), step_1MHz_pct=float((g(1e6) / g(10.0) - 1) * 100),
                    gain_10Hz=float(g(10.0)))

    out = {"levels_V": levels}
    for m in MODELS:
        rows = [step_at(v, m) for v in levels]
        out[m] = dict(rows=rows, spread_pp_100kHz=float(max(r["step_100kHz_pct"] for r in rows) - min(r["step_100kHz_pct"] for r in rows)),
                      spread_pp_1MHz=float(max(r["step_1MHz_pct"] for r in rows) - min(r["step_1MHz_pct"] for r in rows)))
    # control: C1 and Cn lose 20 % of their value at 3 V of bias, quadratically (X7R class), *(assumption: the shape; the size is a large one)*
    k = 0.2 / 9.0
    c1x = f"{P0['C1'] * 1e12:g}p*(1-{k}*v(ain,an)*v(ain,an))"        # 22p and 12p on version 2's values
    cnx = f"{P0['Cn'] * 1e12:g}p*(1-{k}*v(an)*v(an))"
    rows = [step_at(v, "vendor", c1x, cnx) for v in levels]
    out["control_voltage_dependent_caps"] = dict(rows=rows, spread_pp_100kHz=float(max(r["step_100kHz_pct"] for r in rows) - min(r["step_100kHz_pct"] for r in rows)),
                                                 spread_pp_1MHz=float(max(r["step_1MHz_pct"] for r in rows) - min(r["step_1MHz_pct"] for r in rows)))
    # temperature: C0G +-30 ppm/K (EIA class I, *(check: the Samsung datasheet is not in the repository)*) over a 40 K change since
    # calibration (EN-1's rule uses 10 K; 40 K is the whole 20 to 60 C span), C1 against Cn and Cpx; the resistors' share is the gain drift
    p = pp()
    r1, r2, r3 = (rsum(p[k_]) for k_ in ("R1", "R2", "R3"))
    a0 = net(r1, r2, r3, 3.0)[0]
    Ct = p["Cn"] + p["Cn_par"] + 0.5e-12 + p["Cpx"]
    s0 = (p["C1"] + p["Cr1"]) / (p["C1"] + p["Cr1"] + Ct) / a0 - 1
    dT, tc = 40.0, 30e-6
    s1 = (p["C1"] * (1 + tc * dT) + p["Cr1"]) / (p["C1"] * (1 + tc * dT) + p["Cr1"] + Ct * (1 - tc * dT)) / a0 - 1
    d = 100e-6 * dT
    a1 = net(r1 * (1 - d), r2 * (1 + d), r3 * (1 + d), 3.0)[0]
    s2 = (p["C1"] + p["Cr1"]) / (p["C1"] + p["Cr1"] + Ct) / a1 - 1
    out["temperature_40K"] = dict(caps_opposed_pp=float((s1 - s0) * 100), resistors_opposed_pp=float((s2 - s0) * 100), per_K_pp=float((s2 - s0) * 100 / dT))
    save("static", out)
    return out


# ---------------------------------------------------------------------------------------------------------------
def prot_powered(p, v1, v2, rnp=None, name="pp"):
    """Both inputs at DC levels, powered; the amplifier's input ESD diodes to the rails are added at +IN."""
    q = dict(p)
    if rnp is not None:
        q["Rnp"] = rnp
    t = header(name) + rails(q) + f"Vsa asrc 0 dc {v1}\nVsb bsrc 0 dc {v2}\n" + chan(q, "a", esd=True) + chan(q, "b", esd=True) + f"""
.control
op
print v(apin) v(bpin) v(an) v(bn) v(aout) i(Vr) i(Vcc) i(Vsa) i(Vsb) v(anp) v(bnp) i(Vesua) i(Vesda)
.endc
.end
"""
    o = run_ng(name, t)
    g = lambda k: float(re.search(rf"^{re.escape(k)}\s*=\s*([-0-9.eE+]+)", o, re.M | re.I).group(1))
    return dict(v1=v1, v2=v2, pin_a=g("v(apin)"), pin_b=g("v(bpin)"), N_a=g("v(an)"), N_b=g("v(bn)"),
                i_ref_uA=-g("i(vr)") * 1e6, i_vcc_uA=-g("i(vcc)") * 1e6, i_in_a_uA=-g("i(vsa)") * 1e6, i_in_b_uA=-g("i(vsb)") * 1e6,
                i_esd_up_uA=g("i(vesua)") * 1e6, i_esd_dn_uA=g("i(vesda)") * 1e6)


def prot_edge(p, rnp, vstep=12.0, tr=2e-9, name="pe"):
    """A vstep edge at the BNC from 50 ohm: peak current in the amplifier's input ESD diode (powered)."""
    q = dict(p)
    q["Rnp"] = rnp
    lo, hi = (0.0, vstep) if vstep > 0 else (0.0, vstep)
    t = header(name) + rails(q) + f"Vs asrc 0 pulse({lo} {hi} 20n {tr} {tr} 400n 1u)\n" + chan(q, "a", esd=True) + f"""
.control
tran 0.05n 120n 0 0.05n
wrdata {wr(name,'e')} i(Vesua) i(Vesda)
.endc
.end
"""
    run_ng(name, t)
    d = load(name, "e")
    return dict(peak_mA=float(max(np.abs(d[:, 1]).max(), np.abs(d[:, 3]).max()) * 1e3))


def prot_unpowered(p, v1, v2, bleed, diff_clamp=False, pinclamp=True, name="pu"):
    """Unpowered: the AFE +3.3 V_A rail floats with a bleed to ground, REF at 0 V, the Due's 3.3 V net at 0 V.  The
    TPH2502 is reduced to its ESD structure *(assumption: the datasheet gives no I-V and no unpowered behaviour)*: diodes
    from each of +IN, -IN, OUT to the rail and from ground to each.  diff_clamp adds back-to-back diodes between +IN
    and -IN (the vendor macro has such a pair, DIN1/DIN2: whether the real die does is unknown): the adversarial arm."""
    t = f"* {name}\n{DESD}{DBAV99}.options abstol=1e-13 itl1=4000 reltol=1e-4\n"
    t += f"Rbleed rail 0 {bleed}\nCrail rail 0 1.1u\nVref ref 0 dc 0\nVdue due 0 dc 0\n"
    for k, vin in (("a", v1), ("b", v2)):
        t += f"Vs{k} {k}src 0 dc {vin}\n"
        q = dict(p)
        q["Vsrc"] = vin
        r1a, r1b = p["R1"]; r2a, r2b = p["R2"]; r3a, r3b = p["R3"]
        t += (f"Rs{k} {k}src {k}in {p['Rsrc']}\nR1a{k} {k}in {k}m1 {r1a}\nR1b{k} {k}m1 {k}n {r1b}\n"
              f"R2a{k} {k}n {k}m2 {r2a}\nR2b{k} {k}m2 0 {r2b}\nR3a{k} {k}n {k}m3 {r3a}\nR3b{k} {k}m3 ref {r3b}\n"
              f"Rnp{k} {k}n {k}np {p['Rnp']}\nCpx{k} {k}np 0 {p['Cpx']}\n"
              f"Du1{k} {k}np rail DESD\nDd1{k} 0 {k}np DESD\n"             # +IN
              f"Du2{k} {k}fb rail DESD\nDd2{k} 0 {k}fb DESD\n"             # -IN
              f"Du3{k} {k}out rail DESD\nDd3{k} 0 {k}out DESD\n"           # OUT
              f"Vfb{k} {k}out {k}fb dc 0\n"
              f"Riso{k} {k}out {k}pin {p['Riso']}\n"
              f"Dsa{k} 0 {k}pin DESD\nDsb{k} {k}pin due DESD\n")           # the SAM3X pin's own diodes, to its 3.3 V net
        if diff_clamp:
            t += f"Dx1{k} {k}np {k}fb DESD\nDx2{k} {k}fb {k}np DESD\n"
        if pinclamp:
            t += f"Dpa{k} 0 {k}pin DBAV99\nDpb{k} {k}pin rail DBAV99\n"
    t += ".control\nop\nprint v(rail) v(apin) v(bpin) i(Vdue) i(Vref)\n.endc\n.end\n"
    o = run_ng(name, t)
    g = lambda k: float(re.search(rf"^{re.escape(k)}\s*=\s*([-0-9.eE+]+)", o, re.M | re.I).group(1))
    return dict(v1=v1, v2=v2, bleed=bleed, rail=g("v(rail)"), pin_a=g("v(apin)"), pin_b=g("v(bpin)"),
                i_due_uA=-g("i(vdue)") * 1e6, i_ref_uA=-g("i(vref)") * 1e6)


def sec_prot():
    p = pp()
    out = {"powered": [], "edge": {}, "unpowered": [], "unpowered_diff": [], "bleed_needed": {}}
    for v1, v2 in PROT_DC:
        out["powered"].append(prot_powered(p, v1, v2))
    for rnp in (0.0, 470.0, 560.0, 680.0, 1000.0):
        out["edge"][str(int(rnp))] = {"+12V_2ns": prot_edge(p, rnp, 12.0, 2e-9, name="pe1"),
                                       "+12V_1ns": prot_edge(p, rnp, 12.0, 1e-9, name="pe2"),
                                       "-12V_2ns": prot_edge(p, rnp, -12.0, 2e-9, name="pe4"),
                                       "+30V_5ns": prot_edge(p, rnp, 30.0, 5e-9, name="pe3")}
    for bleed in (1e9, 100e3, 30e3, 14e3, 10e3):
        for pc in (True, False):
            for v1, v2 in ((12, 12), (-12, -12), (12, -12)):
                r = prot_unpowered(p, v1, v2, bleed, pinclamp=pc)
                r["pinclamp"] = pc
                out["unpowered"].append(r)
    for v1, v2 in ((12, 12), (-12, -12), (12, -12)):
        for pc in (True, False):
            r = prot_unpowered(p, v1, v2, 14e3, diff_clamp=True, pinclamp=pc)
            r["pinclamp"] = pc
            out["unpowered_diff"].append(r)
    # largest bleed holding the rail at 0.5 V with both inputs at +12 V (PR-3)
    lo, hi = 100.0, 1e7
    for _ in range(30):
        mid = (lo * hi) ** 0.5
        if prot_unpowered(p, 12, 12, mid, pinclamp=True)["rail"] < 0.5:
            lo = mid
        else:
            hi = mid
    out["bleed_needed"] = dict(max_bleed_ohm=lo, rail_V_at_that=prot_unpowered(p, 12, 12, lo)["rail"])
    # leakage of a BAV99 at N, if one were fitted: error at the pin for the datasheet bounds *(check: recalled)*
    r1, r2, r3 = (rsum(p[k]) for k in ("R1", "R2", "R3"))
    a, voff, rin, rp = net(r1, r2, r3, p["vr"])
    out["bav99_at_N"] = dict(rp_k=rp / 1e3,
                             err_abs_bound_30nA_node_mV=30e-9 * rp * 1e3, err_abs_bound_30nA_input_mV=30e-9 * rp / a * 1e3,
                             conductance_bound_25V_30nA_gain_pct=rp / (25 / 30e-9) * 100,
                             cap_pF=1.5, note="two diodes, each reverse-biased by 0.2 to 3.2 V across the range")
    out["amp_leak"] = dict(ib_max_pA=3.0, err_node_uV=3e-12 * rp * 1e6)
    save("prot", out)
    return out


# ---------------------------------------------------------------------------------------------------------------
def sec_xtalk():
    out = {}
    base = pp()
    lsb = LSB(AREF_LO)

    def run(p, f0, name="xt"):
        """Linear: aggressor 1 V ac at A's BNC, B's BNC at DC through 50 ohm.  Returns (pin_b / pin_a, pin_a)."""
        t = header(name) + rails(p) + f"Vsa asrc 0 dc {XT_DC:g} ac 1\nVsb bsrc 0 dc {XT_DC:g}\n" + chan(p, "a") + chan(p, "b") + coupling(p) + f"""
.control
ac lin 1 {f0} {f0}
wrdata {wr(name,'x')} v(apin) v(bpin)
.endc
.end
"""
        run_ng(name, t)
        d = load(name, "x")
        ha = abs(d[0, 1] + 1j * d[0, 2])
        hb = abs(d[0, 4] + 1j * d[0, 5])
        return hb / ha, ha

    def lsb_of(rk):
        """LSB (3.2 V / 4096) at the shorted channel's pin for a 6 Vpp sine at the other channel's BNC."""
        ratio, ha = rk
        return float(ratio * XT_AMP * ha / lsb)

    for f0 in (1e6, 5e6, 10e6):
        rk = run(base, f0)
        out[f"shared_rail_ref_only_{int(f0/1e6)}MHz"] = dict(ratio_b_over_a_pin=float(rk[0]), lsb_at_6Vpp=lsb_of(rk))
    # stray capacitance between the two N nodes, between the two input nets, and between the two +IN pads (pins 3 and 5,
    # after Rnp and Cpx), and the datasheet's -100 dB at 5 MHz
    for key, par, vals in (("Cx_N_to_N", "Cx", (0.0, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2)),
                           ("Cx_in_to_in", "Cxin", (0.0, 0.02, 0.05, 0.1, 0.2, 0.5)),
                           ("Cx_pad_to_pad", "Cxp", (0.0, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0))):
        rows = []
        for cx in vals:
            for f0 in (5e6, 10e6):
                rk = run(pp(**{par: cx * 1e-12}), f0)
                rows.append(dict(C_pF=cx, f_MHz=f0 / 1e6, ratio=float(rk[0]), lsb_at_6Vpp=lsb_of(rk)))
        out[key] = rows
    rows = []
    for xt_db, f0 in ((-100, 5e6), (-94, 10e6), (-80, 10e6)):
        rk = run(pp(xt=10 ** (xt_db / 20)), f0)
        rows.append(dict(xt_dB=xt_db, f_MHz=f0 / 1e6, ratio=float(rk[0]), lsb_at_6Vpp=lsb_of(rk)))
    out["datasheet_xtalk"] = rows
    k0 = out["shared_rail_ref_only_10MHz"]["lsb_at_6Vpp"]
    # the stray for 1 LSB at 10 MHz, from the 0.1 pF row of each sweep (linear in the stray at these sizes)
    for key, ref, name in (("Cx_N_to_N", 0.1, "Cx_N_for_1LSB_10MHz_pF"), ("Cx_in_to_in", 0.1, "Cx_in_for_1LSB_10MHz_pF"), ("Cx_pad_to_pad", 0.1, "Cx_pad_for_1LSB_10MHz_pF")):
        k10 = [r for r in out[key] if r["C_pF"] == ref and r["f_MHz"] == 10.0][0]["lsb_at_6Vpp"]
        out[name] = float(ref * max(1.0 - k0, 0) / max(k10 - k0, 1e-12))
    # the budget: both strays present at once, at the values design.md states
    comb = []
    for cxn, cxp_ in ((0.02, 0.02), (0.01, 0.03), (0.05, 0.0), (0.0, 0.04), (0.03, 0.03)):
        for f0 in (5e6, 10e6):
            comb.append(dict(Cx_N_pF=cxn, Cx_pad_pF=cxp_, f_MHz=f0 / 1e6, lsb_at_6Vpp=lsb_of(run(pp(Cx=cxn * 1e-12, Cxp=cxp_ * 1e-12), f0))))
    out["combined"] = comb
    # what the +IN pad's coupling depends on: Rnp (and the node impedance it makes) at 0.02 pF between the pads, 10 MHz, and Cpx at Rnp 470
    out["pad_0p02pF_by_Rnp"] = {f"{r:g}": lsb_of(run(pp(Rnp=r, Cxp=0.02e-12), 10e6)) for r in (100.0, 220.0, 470.0, 1000.0)}
    out["pad_0p02pF_by_Cpx_pF"] = {f"{c:g}": lsb_of(run(pp(Cpx=c * 1e-12, Cxp=0.02e-12), 10e6)) for c in (4.7, 10.0, 22.0)}
    save("xtalk", out)
    return out


# ---------------------------------------------------------------------------------------------------------------
def draw(rng, p, n, tol_r=0.01, tol_c=0.05, vr_tol=0.002):
    R = parts(p)[:, None] * (1 + rng.uniform(-tol_r, tol_r, (6, n)))
    r1, r2, r3 = R[0] + R[1], R[2] + R[3], R[4] + R[5]
    vr = p["vr"] * (1 + rng.uniform(-vr_tol, vr_tol, n))
    c1 = p["C1"] * (1 + rng.uniform(-tol_c, tol_c, n)) + p["Cr1"]
    # Cn, Cpx (C0G 5 %, fully effective at N below Rnp x Cpx's 34 MHz pole) and 2..6 pF of pads + trace + amplifier *(assumption)*
    cn = (p["Cn"] + p["Cpx"]) * (1 + rng.uniform(-tol_c, tol_c, n)) + rng.uniform(2e-12, 6e-12, n)
    vos = rng.uniform(-VOS_MAX, VOS_MAX, n) + rng.uniform(-CMRR_ERR, CMRR_ERR, n)
    return r1, r2, r3, vr, c1, cn, vos


def sec_mc(n=200_000, seed=20261112):
    p = pp()
    rng = np.random.default_rng(seed)
    r1, r2, r3, vr, c1, cn, vos = draw(rng, p, n)
    a, voff, rin, rp = net(r1, r2, r3, vr)
    out = {"n": n, "seed": seed}
    mv = AREF_HI / 4096 / a * 1e3
    lo_pin = voff + a * USABLE[0] + vos
    hi_pin = voff + a * USABLE[1] + vos
    lo_pin_c = lo_pin - CENTRE
    hi_pin_c = hi_pin + CENTRE
    out["a"] = [float(a.min()), float(a.mean()), float(a.max())]
    out["span_pct_FS_3p25"] = [float((SPAN_V * a / 3.25 * 100).min()), float((SPAN_V * a / 3.25 * 100).max())]
    out["rin_k"] = [float(rin.min() / 1e3), float(rin.mean() / 1e3), float(rin.max() / 1e3)]
    out["rin_nominal_k"] = float(net(rsum(p["R1"]), rsum(p["R2"]), rsum(p["R3"]), p["vr"])[2] / 1e3)
    out["mV_per_code_worst"] = float(mv.max())
    # pin margin to the rails of the converter, and the slack over SC-2's 80 mV, at AREF 3.20 V
    out["lo_margin_mV_min"] = float(lo_pin.min() * 1e3)
    out["hi_margin_mV_min"] = float((AREF_LO - hi_pin.max()) * 1e3)
    out["lo_margin_mV_min_with_30mV"] = float(lo_pin_c.min() * 1e3)
    out["hi_margin_mV_min_with_30mV"] = float((AREF_LO - hi_pin_c.max()) * 1e3)
    out["lo_slack_mV"] = out["lo_margin_mV_min"] - MARGIN * 1e3
    out["hi_slack_mV"] = out["hi_margin_mV_min"] - MARGIN * 1e3
    out["lo_slack_mV_with_30mV"] = out["lo_margin_mV_min_with_30mV"] - MARGIN * 1e3
    out["hi_slack_mV_with_30mV"] = out["hi_margin_mV_min_with_30mV"] - MARGIN * 1e3
    out["rated_pin_V"] = [float((voff + a * RATED[0]).min()), float((voff + a * RATED[1]).max())]
    out["pin_at_usable"] = dict(lo_V_min=float(lo_pin.min()), lo_V_max=float(lo_pin.max()), hi_V_min=float(hi_pin.min()), hi_V_max=float(hi_pin.max()))
    out["centre_offset_mV_at_pin_for_1V_in"] = [float(((voff + a * CEN_IN - 1.625).min()) * 1e3), float(((voff + a * CEN_IN - 1.625).max()) * 1e3)]
    # exact worst case: every combination of the six resistors at +-1 % and the reference at +-0.2 % (128 corners)
    cs = np.array(list(itertools.product((-1, 1), repeat=7)), dtype=float)
    Rc = parts(p)[None, :] * (1 + 0.01 * cs[:, :6])
    r1c, r2c, r3c = Rc[:, 0] + Rc[:, 1], Rc[:, 2] + Rc[:, 3], Rc[:, 4] + Rc[:, 5]
    vrc = p["vr"] * (1 + 0.002 * cs[:, 6])
    ac_, vc_, rc_, _ = net(r1c, r2c, r3c, vrc)
    vos_w = VOS_MAX + CMRR_ERR
    out["corners"] = dict(a=[float(ac_.min()), float(ac_.max())], span_pct_FS_3p25=[float((SPAN_V * ac_.min() / 3.25 * 100)), float((SPAN_V * ac_.max() / 3.25 * 100))],
                          rin_k=[float(rc_.min() / 1e3), float(rc_.max() / 1e3)], mV_per_code_worst=float(AREF_HI / 4096 / ac_.min() * 1e3),
                          lo_pin_min_mV=float(((vc_ + ac_ * USABLE[0]).min() - vos_w) * 1e3),
                          hi_slack_mV=float((AREF_LO - MARGIN - (vc_ + ac_ * USABLE[1]).max() - vos_w) * 1e3),
                          lo_slack_mV=float(((vc_ + ac_ * USABLE[0]).min() - vos_w - MARGIN) * 1e3))
    # HF shelf: gain above the node pole / DC gain - 1
    shelf = (c1 / (c1 + cn)) / a - 1
    out["shelf_pct"] = dict(min=float(shelf.min() * 100), mean=float(shelf.mean() * 100), max=float(shelf.max() * 100),
                            p95_abs=float(np.percentile(np.abs(shelf), 95) * 100), p99_abs=float(np.percentile(np.abs(shelf), 99) * 100))
    cin = c1 * cn / (c1 + cn) + p["Cwire"]
    out["cin_pF"] = [float(cin.min() * 1e12), float(cin.mean() * 1e12), float(cin.max() * 1e12)]
    # channel matching (SC-8): two independent draws
    r1b, r2b, r3b, vrb, c1b, cnb, vosb = draw(rng, p, n)
    ab, voffb, _, _ = net(r1b, r2b, r3b, vr)       # same REF, independent resistors
    out["gain_match_pct_max"] = float(np.abs(a / ab - 1).max() * 100)
    out["offset_match_mV_max_at_pin"] = float(np.abs(voff - voffb).max() * 1e3)
    # REF3030E currents: source at the lowest input, sink with the node clamped at rail + 0.6 V
    n_lo = voff + a * USABLE[0]
    out["ref_source_uA_max_per_channel"] = float(((vr - n_lo) / r3).max() * 1e6)
    out["ref_sink_uA_clamped_per_channel"] = float(((3.3 * 1.01 + 0.7 - vr) / r3).max() * 1e6)
    out["ref_dV_uV_both_channels_worst"] = float(2 * max(out["ref_source_uA_max_per_channel"], out["ref_sink_uA_clamped_per_channel"]) * 1e-6 * 0.45e-3 / 1e-3 * 1e6 * 1e-3)
    # drift: R1 vs R2||R3 opposed at 100 ppm/K over 20 K, C0G 0 ppm/K
    d = 100e-6 * 20
    r1n, r2n, r3n = (rsum(p[k]) for k in ("R1", "R2", "R3"))
    a0 = net(r1n, r2n, r3n, 3.0)[0]
    a1 = net(r1n * (1 - d), r2n * (1 + d), r3n * (1 + d), 3.0)[0]
    out["gain_drift_20K_pct"] = float((a1 / a0 - 1) * 100)
    # EN-1 / SC-7 drift terms at the input for a 10 K change since calibration (SC-7's rule): REF3030E 15 ppm/K max
    # (ref30.pdf 6.5), op-amp VOS 2 uV/K max (page 3), resistors 100 ppm/K opposed (jlc-basic.csv: C23178 etc.)
    a_n, voff_n, _, rp_n = net(rsum(p["R1"]), rsum(p["R2"]), rsum(p["R3"]), p["vr"])
    out["drift_10K_input_mV"] = dict(ref=3.0 * 15e-6 * 10 * (rp_n / rsum(p["R3"])) / a_n * 1e3, vos=2e-6 * 10 / a_n * 1e3,
                                     gain_pct=float((net(r1n * (1 - 100e-6 * 10), r2n * (1 + 100e-6 * 10), r3n * (1 + 100e-6 * 10), 3.0)[0] / a0 - 1) * 100))
    # cross-check against ngspice at 12 random draws: DC gain, offset, and the HF/DC shelf
    chk = []
    for i in range(12):
        q = pp()
        R = parts(p) * (1 + rng.uniform(-0.01, 0.01, 6))
        q["R1"], q["R2"], q["R3"] = tuple(R[:2]), tuple(R[2:4]), tuple(R[4:])
        q["vr"] = 3.0 * (1 + rng.uniform(-0.002, 0.002))
        q["C1"] = p["C1"] * (1 + rng.uniform(-0.05, 0.05))
        q["Cn"] = p["Cn"] * (1 + rng.uniform(-0.05, 0.05))
        q["Cpx"] = p["Cpx"] * (1 + rng.uniform(-0.05, 0.05))
        q["Cn_par"] = rng.uniform(2e-12, 6e-12) - 0.5e-12     # the macro itself adds about 0.5 pF at the + input
        t = header("mcx") + rails(q) + "Vs asrc 0 dc 0 ac 1\n" + chan(q, "a") + f"""
.control
op
print v(apin)
ac dec 10 10 1meg
wrdata {wr('mcx','h')} v(apin)
.endc
.end
"""
        run_ng("mcx", t)
        d = load("mcx", "h")
        f = d[:, 0]
        hh = np.abs(d[:, 1] + 1j * d[:, 2])
        A, V, RI, RP = net(rsum(q["R1"]), rsum(q["R2"]), rsum(q["R3"]), q["vr"])
        sh_sim = hh[np.argmin(abs(f - 1e6))] / hh[0] - 1
        sh_ana = (q["C1"] + q["Cr1"]) / (q["C1"] + q["Cr1"] + q["Cn"] + q["Cpx"] + q["Cn_par"] + 0.5e-12) / A - 1
        chk.append(dict(a_sim=float(hh[0]), a_ana=float(A), shelf_sim_pct=float(sh_sim * 100), shelf_ana_pct=float(sh_ana * 100)))
    out["ngspice_crosscheck"] = chk
    out["crosscheck_max_gain_err_pct"] = float(max(abs(c["a_sim"] / c["a_ana"] - 1) for c in chk) * 100)
    out["crosscheck_max_shelf_err_pct"] = float(max(abs(c["shelf_sim_pct"] - c["shelf_ana_pct"]) for c in chk))
    save("mc", out)
    return out


# ---------------------------------------------------------------------------------------------------------------
def sec_guards():
    """Break each check on purpose and confirm it fails (CLAUDE.md: a new check is not trusted until it has failed)."""
    out = {}
    rng = np.random.default_rng(1)
    # 1. DC margin check: the REF3030E disconnected (R3 = 10 Mohm: no centre) must violate the low margin
    p = pp(R3=(10e6, 0.001))
    r1, r2, r3, vr, c1, cn, vos = draw(rng, p, 20000)
    a, voff, rin, rp = net(r1, r2, r3, vr)
    lo = (voff + a * USABLE[0] + vos).min() * 1e3
    hi = (AREF_LO - (voff + a * USABLE[1] + vos).max()) * 1e3
    out["margin_check_with_R3_open"] = dict(lo_mV=float(lo), hi_mV=float(hi), fails=bool(lo < MARGIN * 1e3 or hi < MARGIN * 1e3))
    # 2. compensation step check: C1 = 12 pF instead of 22 pF must show a large step ...
    p = pp(C1=MUT_C1)                  # v2: 12 pF in place of 22 pF; 5v: 22 pF in place of 12 pF (the other range's value)
    r1, r2, r3, vr, c1, cn, vos = draw(rng, p, 20000)
    a, voff, rin, rp = net(r1, r2, r3, vr)
    sh = ((c1 / (c1 + cn)) / a - 1) * 100
    out["shelf_check_with_C1_12pF"] = dict(p95_abs_pct=float(np.percentile(np.abs(sh), 95)), fails=bool(np.percentile(np.abs(sh), 95) > 8))
    # ... and so must Cn left at 22 pF now that Cpx is 10 pF more at N (the circuit as it stood when Cpx was added)
    cs_ = loadj("cscan")
    out["shelf_check_Cn22_with_Cpx"] = dict(p95_abs_pct=cs_["cn22_with_cpx"]["p95_abs_pct"], mean_pct=cs_["cn22_with_cpx"]["mean_pct"],
                                            fails=bool(cs_["cn22_with_cpx"]["p95_abs_pct"] > 8))
    # 3. stability check: no Riso with a heavy pin load, and no Cpx on the datasheet-fitted model, must fail 45 degrees
    with use_model("BEH60"):
        r = loop_pm(pp(Riso=0.001), cload=1000e-12)
    out["pm_check_noRiso_1nF_BEH60"] = dict(**r, fails=bool(r.get("pm_deg") is not None and r["pm_deg"] < 45))
    with use_model("BEH60"):
        r = loop_pm(pp(Cpx=0.0))
    out["pm_check_noCpx_BEH60"] = dict(**r, fails=bool(r.get("pm_deg") is not None and r["pm_deg"] < 45))
    # 4. THD/slew check: a 40 MHz sine must show the slew limit (done in tran), repeat and compare to a 5 MHz one
    t = loadj("tran")
    out["thd_check_40MHz"] = dict(thd_5MHz_pct=t["sine5_usable"]["thd_pct"], thd_40MHz_pct=t["sine40_control"]["thd_pct"],
                                  fails=bool(t["sine40_control"]["thd_pct"] > 10 * t["sine5_usable"]["thd_pct"]))
    # 5. settling check: 20 kohm of series resistance must fail 0.5 LSB (tran)
    out["settling_check_20k"] = dict(err_lsb=t["sh_control_riso20k"]["err_b_lsb"], fails=bool(abs(t["sh_control_riso20k"]["err_b_lsb"]) > 0.5))
    # 6. crosstalk checks: 0.2 pF between the N nodes, 0.2 pF between the +IN pads, and 0.03 pF on both at once, must exceed 2 LSB at 10 MHz
    x = loadj("xtalk")
    r = [q for q in x["Cx_N_to_N"] if q["C_pF"] == 0.2 and q["f_MHz"] == 10.0][0]
    out["xtalk_check_Cx_0p2pF"] = dict(lsb=r["lsb_at_6Vpp"], fails=bool(r["lsb_at_6Vpp"] > 2))
    r = [q for q in x["Cx_pad_to_pad"] if q["C_pF"] == 0.2 and q["f_MHz"] == 10.0][0]
    out["xtalk_check_pad_0p2pF"] = dict(lsb=r["lsb_at_6Vpp"], fails=bool(r["lsb_at_6Vpp"] > 2))
    r = [q for q in x["combined"] if q["Cx_N_pF"] == 0.03 and q["Cx_pad_pF"] == 0.03 and q["f_MHz"] == 10.0][0]
    out["xtalk_check_combined_0p03"] = dict(lsb=r["lsb_at_6Vpp"], fails=bool(r["lsb_at_6Vpp"] > 2))
    # 7. the protection checks: with no bleed the rail must exceed 0.5 V at +12 V on both inputs; with no Rnp the edge must exceed 10 mA
    q = prot_unpowered(pp(), 12, 12, 1e9)
    out["rail_check_no_bleed"] = dict(rail_V=q["rail"], fails=bool(q["rail"] > 0.5))
    e = prot_edge(pp(), 0.0, 12.0, 2e-9, name="ge")
    out["edge_check_no_Rnp"] = dict(peak_mA=e["peak_mA"], fails=bool(e["peak_mA"] > 10))
    if RANGE != "v2":      # on +-5 V values C1 is small and the 12 V edge reads under 10 mA even with no Rnp (range5v.md): the control is the 30 V / 5 ns edge
        e = prot_edge(pp(), 0.0, 30.0, 5e-9, name="ge3")
        out["edge_check_no_Rnp_30V"] = dict(peak_mA=e["peak_mA"], fails=bool(e["peak_mA"] > 10))
        out["edge_check_no_Rnp"]["fails"] = True                    # not a control on this range: replaced by the 30 V one above, said so here
        out["edge_check_no_Rnp"]["replaced_by"] = "edge_check_no_Rnp_30V"
    # 8. SM-3 check: a 4.7 kohm Rnp (pole with Cpx at about 3 MHz) must put the pin's -3 dB under 8 MHz
    p = pp(Rnp=4700.0, Rsrc=50.0)
    t_ = header("gbw") + rails(p) + "Vs asrc 0 dc 0 ac 1\n" + chan(p, "a") + f"""
.control
ac dec 60 1k 2g
wrdata {wr('gbw','h')} v(apin)
.endc
.end
"""
    run_ng("gbw", t_)
    dd = load("gbw", "h")
    hh = np.abs(dd[:, 1] + 1j * dd[:, 2])
    db = 20 * np.log10(hh / hh[np.argmin(abs(dd[:, 0] - 1e5))])
    f3 = float(dd[np.where((dd[:, 0] > 1e5) & (db < -3))[0][0], 0] / 1e6)
    out["bw_check_Rnp4k7"] = dict(f3dB_MHz=f3, fails=bool(f3 < 8.0))
    # 9. D17: detach the ADC network and the reading must rise (the old pin-to-1-GHz reading), so the network is what is being read
    d17 = loadj("d17") if os.path.exists(os.path.join(RES, "d17.json")) else None
    if d17:
        with_net = d17["rows"]["vendor|derived"]["total_uV"]
        detached = d17["pin_1GHz_no_network"]["vendor"]["total_uV"]
        out["d17_check_network_detached"] = dict(with_network_uV=with_net, detached_uV=detached, fails=bool(detached > 1.2 * with_net))
    # 9b. the sampling capacitor's own kT/C, switched on, must appear in quadrature (the pipeline sees what the capacitor sees)
    adc = ADC_CASES["derived"]
    t0 = d17_noise("BEH21", adc, en=EN_DS)["total_uV"]
    t1 = d17_noise("BEH21", adc, en=EN_DS, noisy=True)["total_uV"]
    ktc = float(np.sqrt(1.380649e-23 * 300 / adc["cs"]) * 1e6)
    added = float(np.sqrt(max(t1 ** 2 - t0 ** 2, 0.0)))
    out["d17_check_ktc"] = dict(kTC_uV=ktc, added_uV=added, rel_err=abs(added / ktc - 1), passes_as_positive_control=bool(abs(added / ktc - 1) < 0.1))
    # 9b2. the amplifier-noise pipeline against the vendor macro, in the band where the macro's density is flat (10 Hz-10 MHz): the two
    # must agree, or the transfer-function route (used for the datasheet density) is not the same circuit as the .noise route
    vv = d17_noise("vendor", adc, hi=1e7)["total_uV"]
    bb = d17_noise("BEH21", adc, en=EN_VENDOR, hi=1e7)["total_uV"]
    out["d17_pipeline_vs_vendor_10MHz"] = dict(vendor_uV=vv, beh21_9p3_uV=bb, rel_err=abs(bb / vv - 1), passes_as_positive_control=bool(abs(bb / vv - 1) < 0.15))
    # 9c. broken injection: the amplifier's noise transfer must not be zero (a disconnected source gives zero, so the amplifier part would vanish)
    a_ok = d17_noise("BEH21", adc, en=EN_DS)["amp_uV"]
    a_bad = d17_noise("BEH21", adc, en=EN_DS, inj=False)["amp_uV"]
    out["d17_check_injection_disconnected"] = dict(amp_uV_connected=a_ok, amp_uV_disconnected=a_bad, fails=bool(a_bad < 0.05 * a_ok))
    # 9d. the integrator against an analytic RC: 1 nV/rtHz through a 7 MHz pole is 1 nV x sqrt(pi/2 x 7 MHz).  The mutant is a linear-f trapezoid
    # on a 2-points-per-decade grid (the grid and rule a careless rerun would use), which must miss it by over 2 %
    fcg = 7e6
    ref_ = 1e-9 * np.sqrt(np.pi / 2 * fcg)
    fg = np.logspace(0, 9, 9 * 40 + 1)
    out["d17_integrator_fine"] = dict(rel_err=abs(integ(fg, (1e-9 / np.sqrt(1 + (fg / fcg) ** 2)) ** 2) / ref_ - 1))
    out["d17_integrator_fine"]["passes_as_positive_control"] = bool(out["d17_integrator_fine"]["rel_err"] < 0.02)
    fg = np.logspace(0, 9, 9 * 2 + 1)
    kk = fg >= 10
    bad = np.sqrt(np.trapezoid((1e-9 / np.sqrt(1 + (fg[kk] / fcg) ** 2)) ** 2, fg[kk]))
    out["d17_integrator_mutant"] = dict(rel_err=abs(bad / ref_ - 1), fails=bool(abs(bad / ref_ - 1) > 0.02))
    # 9e. the SC-6 verdict can fail: a 100 nV/rtHz amplifier on the datasheet dynamics at the derived switch must read over 200 uV
    v = d17_noise("BEH21", adc, en=100e-9)["total_uV"]
    out["d17_check_noisy_amp_100nV"] = dict(total_uV=v, fails=bool(v > 200))
    # 10. static-step check: a bias-dependent capacitor must move the step by over 1 percentage point across the level sweep (static, section static)
    st = loadj("static") if os.path.exists(os.path.join(RES, "static.json")) else None
    if st:
        out["static_check_voltage_dependent_caps"] = dict(spread_pp=st["control_voltage_dependent_caps"]["spread_pp_100kHz"],
                                                           fails=bool(st["control_voltage_dependent_caps"]["spread_pp_100kHz"] > 1.0))
    out["all_fail_as_intended"] = bool(all(v.get("fails", True) for v in out.values() if isinstance(v, dict) and "fails" in v)
                                       and all(v.get("passes_as_positive_control", True) for v in out.values() if isinstance(v, dict)))
    save("guards", out)
    return out


def sec_cscan(n=100_000, seed=1):
    """Every one- or two-part C1 and Cn (Cn may be absent) from the Basic C0G values, with Cpx at +IN fully effective at N, against the
    same Monte Carlo as section mc: the 95th percentile of the HF/DC gain step, among pairs whose network capacitance is at most 22 pF
    (SC-3: 30 pF with the BNC).  Basic C0G values (v2/jlc-basic.csv, 0603): 10 12 15 18 20 22 30 33 47 100 330 pF."""
    p = pp()
    rng = np.random.default_rng(seed)
    vals = [10, 12, 15, 18, 20, 22, 30, 33, 47]
    combos = {f"{v:g}": float(v) for v in vals}
    for a, b in itertools.combinations_with_replacement(vals, 2):
        combos.setdefault(f"{a:g}+{b:g}", float(a + b))
    U = lambda t: 1 + rng.uniform(-t, t, n)
    R = parts(p)[:, None] * np.stack([U(0.01) for _ in range(6)])
    r1, r2, r3 = R[0] + R[1], R[2] + R[3], R[4] + R[5]
    a = net(r1, r2, r3, 3.0)[0]
    par = rng.uniform(2e-12, 6e-12, n)
    cpx = p["Cpx"] * U(0.05)

    def draw_c(label):          # a part made of two caps has each part's tolerance drawn
        if label == "none":
            return 0.0 * par
        return sum(float(c) * 1e-12 * U(0.05) for c in label.split("+"))
    rows = []
    for k1 in combos:
        for k2 in ["none"] + list(combos):
            C1 = draw_c(k1) + p["Cr1"]
            Cn = draw_c(k2) + par + cpx
            eps = C1 / (C1 + Cn) / a - 1
            cin = float((C1 * Cn / (C1 + Cn)).mean() * 1e12)
            if cin > 22.0:       # 4 pF of BNC + trace and 4 pF of margin must still fit under SC-3's 30 pF
                continue
            nparts = len(k1.split("+")) + (0 if k2 == "none" else len(k2.split("+")))
            rows.append(dict(C1=k1, Cn=k2, parts=nparts, p95_abs_pct=float(np.percentile(np.abs(eps), 95) * 100),
                             mean_pct=float(eps.mean() * 100), cin_network_pF=cin))
    rows.sort(key=lambda r: r["p95_abs_pct"])
    best_by_parts = {}
    for r in rows:
        best_by_parts.setdefault(r["parts"], r)
    chosen = [r for r in rows if r["C1"] == f"{p['C1']*1e12:g}" and r["Cn"] == f"{p['Cn']*1e12:g}"][0]
    kept22 = [r for r in rows if r["C1"] == "22" and r["Cn"] == "22"][0]       # Cn left at its value before Cpx existed
    alt = [r for r in rows if r["C1"] == "20" and r["Cn"] == "10"][0]           # Cn the same part as Cpx: one C0G value fewer
    save("cscan", dict(top=rows[:10], best_by_parts=best_by_parts, chosen=chosen, cn22_with_cpx=kept22, alt_20_10=alt, n=n, seed=seed))
    return rows[:3]


def sec_netlist():
    """The circuit as one file: scope_v2.cir (both channels, one dual, nominal values, a bare .op and .ac)."""
    p = pp()
    txt = """* AFE version 2 scope channels: two unity followers on one TPH2502 dual, +3.3 V only (nominal values).
* Generated by run.py (section netlist); every value and its LCSC code is in design.md.  Run from this directory:
*   ngspice -b scope_v2.cir
* Per channel (suffix a = CH1, b = CH2):
*   R1a 510k C23192 + R1b 30k C22984 (IN -> N)       C1 22p C0G C1653 across R1 (Cr1: 0.1 pF stray, not a part)
*   R2a 1M C22935 + R2b 510k C23192 (N -> GND)       Cn 12p C0G C38523, N -> GND (Cnp: 3.5 pF stray, not a part)
*   R3a 470k C23178 + R3b 200k C25811 (N -> REF3030E output)
*   Rnp 470 C23179 (N -> +IN)   Cpx 10p C0G C1634 (+IN -> GND)   Riso 22 C23345 (OUT -> ADC pin)   Dp: BAV99 C2500 (GND / pin / +3.3 V_A)
* TPH2502 C118223 is one dual: XUa is half A, XUb half B.  The vendor macro is the single-amplifier TPH2501 and
* is read from whatif/tph2502/models/ (local, uncommitted, hashed in models/VENDOR_MODEL.sha256).
* Parasitics (Cw BNC+trace 4 pF, Cr1, Cnp, Cfb, Cpin), the source Rs and the ADC input are *(assumption)*: report.md.
""" + header("scope_v2") + rails(p) + """Vsa asrc 0 dc 1.0 ac 1
Vsb bsrc 0 dc 1.0
""" + chan(p, "a") + chan(p, "b") + """
.control
op
print v(apin) v(bpin)
ac dec 20 1k 1g
.endc
.end
"""
    if RANGE != "v2":
        txt = txt.replace("AFE version 2 scope channels", "AFE version 2 scope channels, range 5v (version 1's +-5 V values, range5v.md)")
        txt = txt.replace("R1a 510k C23192 + R1b 30k C22984", "R1a 470k C23178 + R1b 300k C23024").replace("C1 22p C0G C1653", "C1 %gp C0G %s" % (round(P0["C1"] * 1e12), LCSC_C0G[round(P0["C1"] * 1e12)]))
        txt = txt.replace("R2a 1M C22935 + R2b 510k C23192", "R2a 470k C23178 + R2b 330k C23137").replace("Cn 12p C0G C38523", "Cn %gp C0G %s" % (round(P0["Cn"] * 1e12), LCSC_C0G[round(P0["Cn"] * 1e12)]))
        txt = txt.replace("R3a 470k C23178 + R3b 200k C25811", "R3a 330k C23137 + R3b 0R C21189")
        txt = txt.replace("Vsa asrc 0 dc 1.0 ac 1\nVsb bsrc 0 dc 1.0\n", "Vsa asrc 0 dc 0 ac 1\nVsb bsrc 0 dc 0\n")
    with open(os.path.join(OUT_DIR, "scope_v2.cir" if RANGE == "v2" else f"scope_{RANGE}.cir"), "w") as f:
        f.write(txt.replace(OPAMP_INC, os.path.basename(OPAMP_MDL)))          # the committed copy names the macro, not this machine's path
    out = run_ng("scope_v2", txt)                                              # netlists/scope_v2.cir, run under the cap
    return dict(ok=("v(apin)" in out and "Error" not in out), tail=out[-200:])


SECTIONS = dict(netlist=sec_netlist, cscan=sec_cscan, dc=sec_dc, ac=sec_ac, bw=sec_bw, noise=sec_noise, d17=sec_d17, tran=sec_tran, stab=sec_stab, beh=sec_beh,
                prot=sec_prot, xtalk=sec_xtalk, static=sec_static, mc=sec_mc, guards=sec_guards)

def main(argv):
    work, want, it, overrides = None, [], iter(argv), {}
    if "--range" in argv:
        set_range(argv[argv.index("--range") + 1])
    for a in it:
        if a == "--out":
            set_out(next(it))
        elif a == "--work":
            work = next(it)
        elif a == "--range":                               # applied first (below): a --set after it still wins
            next(it)
        elif a == "--set":                                 # a sensitivity case: --set Cn_par=4.31e-12 (any key of netlib.P0, scalar)
            k, v = next(it).split("=", 1)
            if k not in NL.P0 or isinstance(NL.P0[k], (tuple, dict)):
                raise SystemExit(f"--set {k}: not a scalar parameter of netlib.P0")
            NL.P0[k] = type(NL.P0[k])(float(v)) if not isinstance(NL.P0[k], bool) else v == "1"
            overrides[k] = NL.P0[k]
        else:
            want.append(a)
    if work:
        NL.set_workdir(work)
    want = want or list(SECTIONS)
    os.makedirs(RES, exist_ok=True)
    h = check_model()
    meta = dict(ngspice=ngspice_version(), model_sha256=h, model="TPH2501_ngspice.mdl (simtools.vendor)", beh_lib_sha256=beh_sha(),
                beh_lib="models-open/tph2502-beh/tph2502_beh.lib")
    if RANGE != "v2":
        meta["range"] = RANGE                               # a run on another range says so, and names the values it ran
        meta["range_values"] = {k: (list(v) if isinstance(v, tuple) else v) for k, v in RANGES[RANGE]["P0"].items()}
    if overrides:
        meta["overrides"] = overrides                       # a run that is not the baseline says so in its meta.json
    save("meta", meta)
    for s in want:
        print(f"== {s}", flush=True)
        r = SECTIONS[s]()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
