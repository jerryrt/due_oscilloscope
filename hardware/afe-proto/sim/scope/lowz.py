"""2b scope channel, redesign of 2026-11-11: the uncompensated low-impedance divider (SC-3 about 20-30 kohm).
Driven by run.py (python3 -I run.py [--par] [section ...]); every number in report.md comes from here.

Two injection wirings are carried side by side, because the owner's decision (the PA-3 TMUX1119 with node N
on a source pin, 'N') loads the divider node with the switch, and this redesign makes that node a 4 kohm one:
  design 'N'  : the circuit as decided, the injection switch's S1 on N (CSOFF 6 pF, 10 pF IBIS; DAC0 on D)
  design 'R3' : a proposal, the same switch moved into the R3 leg (D on the R3 end, S1 on the channel's
                sense node, S2 on DAC0): N carries no switch, the switch's capacitance sits on a 10 uF node
Everything else is identical.  Results: results/<section>_<design>.json."""
import os, sys, json, re, time, subprocess
import numpy as np
import netlib as NL
import run as R
from netlib import header, rails, core, run_ng, wr, load, freq_metrics, phase_margin, noise_total, OPAMPS

HERE = os.path.dirname(os.path.abspath(__file__))
if NL.VARIANT == "hz":      # 2026-11-11 pivot: 1 Mohm compensated divider, T-switch injection onto N
    DESIGNS = {"H": dict()}
elif NL.VARIANT == "lowz2":   # round 2: one design, buffered sense, R3-leg injection, Kelvin range switch
    DESIGNS = {"K": dict()}
else:
    DESIGNS = {"N": dict(), "R3": dict(inj="R3")}
LSB32 = 3.2 / 4096
DAC_AMP = (2.771 - 0.578) / 2          # DAC0 full swing, half amplitude, V (docs/afe.md: 0.578-2.771 V measured)
OP = "OPA354"

def P(design, **kw):
    q = dict(NL.P0); q.update(DESIGNS.get(design, {})); q.update(op=OP); q.update(kw); return q

def save(name, obj):
    return R.save(name, obj)

def loadj(name):
    return R.loadj(name)

def divider(p):
    """Analytic DC divider figures (R3 leg includes the sense resistor and, for 'R3', the injection switch)."""
    r3 = p["R3"] + p.get("Rs3", 0.0) + (p.get("Ron_inj", 0.0) if p.get("inj") == "R3" else 0.0)
    g1, g2, g3 = 1 / p["R1"], 1 / p["R2"], 1 / r3
    gt = g1 + g2 + g3
    return dict(alpha=g1 / gt, rth=1 / gt, rin=p["R1"] + 1 / (g2 + g3), r3leg=r3,
                centre_err_at_N=1.65 * (g2 + 2 * g3) / gt - 1.65)

# ------------------------------------------------------------------ DC (SC-2, SC-4, SC-11, SC-8)
def sec_dc():
    out = {}
    for d in DESIGNS:
        r = R.dc_section(OP, over=dict(DESIGNS[d]), tag=f"dc_{d}")
        out[d] = r
    return out

# ------------------------------------------------------------------ AC: SM-3, AN-1, flatness, edges, Zin
def corners(design):
    if NL.VARIANT == "hz":
        cs = []
        for cx in (-2e-12, 0.0, 3e-12):
            for ron in (3.7, R.RON_MAX):
                for c1s, c2s in ((1.05, 0.95), (0.95, 1.05)):
                    for csw in (6e-12, 10e-12):
                        q = P(design)
                        cs.append(dict(Cpar_extra=cx, Ron_sw=ron, C1=q["C1"] * c1s, C2=q["C2"] * c2s, Csoff=csw))
        return cs
    cs = []
    for cx in (-2e-12, 0.0, 3e-12):
        for ron in (3.7, R.RON_MAX):
            for cn, cr1 in ((1e-12, 0.5e-12), (3e-12, 0.1e-12)):
                for csw in ((6e-12, 10e-12) if design == "N" else (None,)):
                    kw = dict(Cpar_extra=cx, Ron_sw=ron, Cn=cn, Cr1=cr1)
                    if csw:
                        kw["Csoff"] = csw
                    cs.append(kw)
    return cs

def sec_ac():
    out = {}
    for d in DESIGNS:
        for rng in ("5", "1.25"):
            key = f"{d}_{rng}"
            o = {"nominal": R.ac_summary(P(d, rng=rng), "ac_n")}
            wb, wp, wk, cl = 1e99, 1e9, -1e9, []
            for kw in corners(d):
                r = R.ac_summary(P(d, rng=rng, **kw), "ac_c")
                cl.append(dict(kw, bw=r["bw"], pm=r["pm"], peak_db=r["peak_db"]))
                wb = min(wb, r["bw"]); wk = max(wk, r["peak_db"])
                if r["pm"] is not None:
                    wp = min(wp, r["pm"])
            o["worst"] = dict(bw=wb, pm=wp, peak_db=wk, corners=cl)
            sens = []
            for cx in (-2e-12, -1e-12, 0.0, 1e-12, 2e-12, 3e-12):
                for riso in (10.0, 22.0, 50.0):
                    r = R.ac_summary(P(d, rng=rng, Cpar_extra=cx, Riso=riso), "ac_s")
                    sens.append(dict(cpar_extra_pf=cx * 1e12, riso=riso, pm=r["pm"], bw=r["bw"], peak_db=r["peak_db"]))
            o["sens"] = sens
            r = R.ac_summary(P(d, rng=rng, Riso=0.01, Cpin=10e-12), "ac_s")
            o["no_riso_10pF"] = dict(pm=r["pm"], bw=r["bw"], peak_db=r["peak_db"])
            # gain step from 10 Hz (the per-channel sense filter's shelf) and flatness 1-8 MHz
            f, h, T = NL.ac_response(P(d, rng=rng), "ac_lf", fmin=1.0, fmax=2e9, ppd=20)
            a = np.abs(h); g = lambda x: float(np.interp(np.log10(x), np.log10(f), a))
            o["lf"] = dict(step_1Hz_to_100kHz_pct=(g(1e5) / g(1.0) - 1) * 100, step_1Hz_to_1kHz_pct=(g(1e3) / g(1.0) - 1) * 100,
                           flat_1_8MHz_db=max(abs(20 * np.log10(g(x) / g(1e5))) for x in (1e6, 2e6, 4e6, 6e6, 8e6)))
            out[key] = o
        # no injection switch at all, for reference
    for rng in ("5", "1.25"):
        out[f"noswitch_{rng}"] = {"nominal": R.ac_summary(P("N", rng=rng, inj=None), "ac_n")}
    save("ac", out)
    # edges
    ed = {}
    for d in DESIGNS:
        for rng, vs in (("5", 2.0), ("1.25", 0.5)):
            for tr in (42e-9, 5e-9):
                ed[f"{d}_{rng}_{tr*1e9:.0f}ns"] = R.step_response(P(d, rng=rng), "edge", vs, tr)
    save("edge", ed)
    # input impedance
    zi = {}
    for d in DESIGNS:
        p = P(d)
        txt = header(p, "zin") + rails(p) + "Vs in 0 dc 0 ac 1\n" + core(p) + f"""
.control
ac dec 20 10 100meg
wrdata {wr('zin','i')} i(Vs)
.endc
.end
"""
        run_ng("zin", txt)
        dd = load("zin", "i"); f = dd[:, 0]; Y = -(dd[:, 1] + 1j * dd[:, 2])
        z = dict(R_dc_ohm=float(1 / Y[0].real), analytic=divider(p))
        for fx in (1e5, 1e6, 5e6):
            z[f"C_{fx:.0e}_pF"] = float(np.interp(fx, f, Y.imag) / (2 * np.pi * fx) * 1e12)
        z["C_worst_1MHz_pF"] = z["C_1e+06_pF"] + 1.0 + 0.2   # +1 pF wiring, +0.2 pF across R1 (Cr1 0.5 corner)
        zi[d] = z
    save("zin", zi)
    return out

# ------------------------------------------------------------------ SM-3 against Rth and the switch capacitance
def sec_sweep():
    """-3 dB bandwidth (worst of: inverting-node +3 pF, Ron 8.8, Cn 3 pF) as the divider is scaled, with the injection
    switch at N (CSOFF 0 / 6 / 10 pF): what Rth the switch would allow."""
    out = []
    for k in (1.0, 0.75, 0.5, 0.35, 0.25):
        for csw in (0.0, 6e-12, 10e-12):
            row = dict(scale=k, csoff_pF=csw * 1e12)
            for rng in ("5", "1.25"):
                p = P("N", rng=rng, Cpar_extra=3e-12, Ron_sw=R.RON_MAX, Cn=3e-12, Cr1=0.1e-12, Csoff=csw, Cft=0.0 if csw == 0 else 1.8e-12)
                for x in ("R1", "R2", "R3", "Rs3"):
                    p[x] = p[x] * k
                if csw == 0:
                    p["inj"] = None
                r = R.ac_summary(p, "sw")
                row[f"bw_{rng}"] = r["bw"]
            dv = divider(p); row.update(rth=dv["rth"], rin=dv["rin"])
            out.append(row)
    return save("sweep", out)

# ------------------------------------------------------------------ noise (SC-6)
def sec_noise():
    ac = loadj("ac")
    out = {}
    for d in DESIGNS:
        for rng in ("5", "1.25"):
            key = f"{d}_{rng}"
            p = P(d, rng=rng)
            fbw = ac[key]["nominal"]["bw"]
            row = {"bw_3dB": fbw}
            for lab, fm in (("at_bw", fbw), ("at_1p5bw", 1.5 * fbw), ("at_10MHz", 10e6)):
                a = noise_total(p, "nz", fm, "all"); r = noise_total(p, "nz", fm, "res"); m = noise_total(p, "nz", fm, "amp")
                vm = R.transfer_rms(p, "nzx", "vm", R.EN_VMID, fm); v3 = R.transfer_rms(p, "nzx", "v3", R.EN_V3, fm)
                cur = max(a * a - r * r - m * m, 0.0) ** 0.5
                row[lab] = dict(fmax=fm, total_V=float(np.sqrt(a * a + vm * vm + v3 * v3)), all_V=a, resistors_V=r, opamp_voltage_V=m,
                                opamp_current_resid_V=cur, vmid_V=vm, v3sense_V=v3)
            noise_total(p, "nzd", 1.5 * fbw, "all")
            dd = load("nzd", "n"); f = dd[:, 0]; S = dd[:, 1]
            row["density_nV"] = {f"{fx:.0e}": float(np.interp(fx, f, S) * 1e9) for fx in (1e5, 1e6, 3e6, 1e7)}
            noise_total(p, "nza", 1e9, "all", ppd=15)
            dd = load("nza", "n"); f = dd[:, 0]; S = dd[:, 1]
            fp = 1 / (2 * np.pi * R.ADC_DERIVED["ron"] * R.ADC_DERIVED["cs"])
            row["through_adc_pole_V"] = float(np.sqrt(np.trapezoid(S ** 2 / (1 + (f / fp) ** 2), f)))
            out[key] = row
    return save("noise", out)

# ------------------------------------------------------------------ SC-9, SC-10: kick, DC and AC crosstalk, AWG coupling
def ac_xtalk(p, name="xt"):
    """|V(B pin)| per volt at A's input, both channels built, B's input shorted (0 V)."""
    txt = header(p, name) + rails(p) + "Vina ain 0 dc 0 ac 1\nVinb bin 0 dc 0\n" + core(p, "a") + "\n" + core(p, "b") + f"""
.control
ac dec 20 1 200meg
wrdata {wr(name,'x')} v(bpin) v(apin)
.endc
.end
"""
    run_ng(name, txt)
    dd = load(name, "x"); f = dd[:, 0]
    return f, np.abs(dd[:, 1] + 1j * dd[:, 2]), np.abs(dd[:, 4] + 1j * dd[:, 5])

def awg_coupling(p, name="awg"):
    """|V(pin)| per volt of DAC0 (AC on the DAC0 node), both channels built, inputs shorted."""
    txt = header(p, name) + rails(p, ac_dac=True) + "Vina ain 0 dc 0\nVinb bin 0 dc 0\n" + core(p, "a") + "\n" + core(p, "b") + f"""
.control
ac dec 20 10 20meg
wrdata {wr(name,'x')} v(apin)
.endc
.end
"""
    run_ng(name, txt)
    dd = load(name, "x"); f = dd[:, 0]
    return f, np.abs(dd[:, 1] + 1j * dd[:, 2])

def sec_kick():
    out = {}
    for d in DESIGNS:
        for rng, vfs in (("5", 6.0), ("1.25", 1.25)):
            for lab, adc in (("derived", R.ADC_DERIVED), ("stress", R.ADC_STRESS)):
                for riso in ((22.0,) if NL.VARIANT == "lowz2" else (10.0, 22.0, 50.0)):   # lowz2: each transient takes ~1 min
                    p = P(d, rng=rng, Riso=riso)
                    full = R.kick_run(p, +vfs, -vfs, adc, aref=3.2)
                    hi = R.kick_run(p, +vfs, 0.0, adc, aref=3.2)
                    lo = R.kick_run(p, -vfs, 0.0, adc, aref=3.2)
                    dyn = abs(hi["errB_lsb"] - lo["errB_lsb"])
                    tot = abs((hi["vpin_b"] + hi["errB_lsb"] * LSB32) - (lo["vpin_b"] + lo["errB_lsb"] * LSB32)) / LSB32
                    out[f"{d}_{rng}_{lab}_Riso{riso:.0f}"] = dict(full_swing=full, xtalk_hi=hi, xtalk_lo=lo, crosstalk_dyn_lsb=dyn,
                                                               crosstalk_dc_lsb=abs(hi["vpin_b"] - lo["vpin_b"]) / LSB32,
                                                               crosstalk_lsb=tot, zout=R.zout_pin(p))
            # sine at any frequency: A full scale (amplitude vfs) -> B
            f, hb, ha = ac_xtalk(P(d, rng=rng))
            xt = hb * vfs / LSB32
            out[f"{d}_{rng}_ac"] = dict(max_lsb=float(xt.max()), f_at_max=float(f[np.argmax(xt)]),
                                        at={f"{x:.0e}": float(np.interp(np.log10(x), np.log10(f), xt)) for x in (10, 1e3, 1e5, 1e6, 1e7)})
            # AWG coupling while DAC0 plays (DAC0 at full swing, any frequency to 20 MHz)
            if not P(d).get("inj"):
                continue     # no injection switch: no AWG path into N in the model (board-level coupling is G3's)
            f, ha = awg_coupling(P(d, rng=rng))
            aw = ha * DAC_AMP / LSB32
            out[f"{d}_{rng}_awg"] = dict(max_lsb=float(aw.max()), f_at_max=float(f[np.argmax(aw)]),
                                         at={f"{x:.0e}": float(np.interp(np.log10(x), np.log10(f), aw)) for x in (1e3, 1e4, 1e5, 1e6, 1e7)},
                                         f_2lsb=float(f[np.argmax(aw > 2.0)]) if (aw > 2.0).any() else None)
    out["charge_injection"] = {}
    for d in DESIGNS:
        NL_P0 = NL.P0
        NL.P0 = P(d)
        try:
            out["charge_injection"][d] = R.qinj_run()
        finally:
            NL.P0 = NL_P0
    return save("kick", out)

# ------------------------------------------------------------------ protection: PR-1, PR-2 (powered, vendor model)
def sec_prot():
    out = {"dc": {}, "edge": {}, "above30": {}, "unpowered": {}}
    for d in DESIGNS:
        for rng in ("5", "1.25"):
            for vin in (30.0, -30.0):
                p = P(d, rng=rng, esd_n=True)
                q = dict(p, v3=3.3)
                rl = rails(q, vcc=3.37, vmid=1.65)
                prn = "print i(Vs) v(pin) v(vccl) v(n) v(out) i(V3s) i(Vos)" + (" i(Vesa) i(Vesb)" if P(d).get("inj") in ("N", "T") else "")
                txt = header(q, "prot") + rl + f"Vs in 0 dc {vin}\n" + core(q) + f"""
.control
op
{prn}
.endc
.end
"""
                o = run_ng("prot", txt)
                g = lambda k: R._grab(o, k)
                r = dict(i_in_mA=abs(g("i(vs)")) * 1e3, v_pin=g("v(pin)"), v_rail=g("v(vccl)"), v_n=g("v(n)"), v_out=g("v(out)"),
                         i_opamp_in_mA=abs(g("i(vos)")) * 1e3, i_due33_uA=g("i(v3s)") * 1e6)
                if P(d).get("inj") in ("N", "T"):
                    r["i_tmux_esd_mA"] = max(abs(g("i(vesa)")), abs(g("i(vesb)"))) * 1e3
                # R1 composite: six 100k in parallel, then 249: each 100k part sees (Vin - Vn - I*249)
                vr = abs(vin - r["v_n"]) - r["i_in_mA"] * 1e-3 * 249.0
                r["P_100k_part_mW"] = vr ** 2 / 100e3 * 1e3
                r["V_100k_part"] = vr
                out["dc"][f"{d}|{rng}|{vin:+.0f}"] = r
            for vin in (30.0, -30.0):
                for tr in (5e-9, 42e-9):
                    q = P(d, rng=rng, esd_n=True)
                    txt = header(q, "pedge") + rails(q, vcc=3.37) + f"Vs src 0 dc 0 pulse(0 {vin} 50n {tr} {tr} 3u 10u)\nRs src in 50\n" + core(q) + f"""
.control
tran 0.05n 1.5u 0 0.05n
wrdata {wr('pedge','p')} v(pin)
wrdata {wr('pedge','i')} i(Vos)
wrdata {wr('pedge','n')} v(n)
.endc
.end
"""
                    run_ng("pedge", txt)
                    gg = lambda k: load("pedge", k)[:, 1]
                    out["edge"][f"{d}|{rng}|{vin:+.0f}|{tr*1e9:.0f}ns"] = dict(pin_min=float(gg("p").min()), pin_max=float(gg("p").max()),
                                                                             i_opamp_peak_mA=float(np.abs(gg("i")).max() * 1e3),
                                                                             n_min=float(gg("n").min()), n_max=float(gg("n").max()))
        # above 30 V, powered, +/-5 V range
        for vin in (60.0, 100.0, 200.0, 250.0, -200.0):
            p = P(d, esd_n=True); q = dict(p, v3=3.3)
            txt = header(q, "p30") + rails(q, vcc=3.37, vmid=1.65) + f"Vs in 0 dc {vin}\n" + core(q) + """
.control
op
print i(Vs) v(n) i(Vos)
.endc
.end
"""
            o = run_ng("p30", txt)
            iin = abs(R._grab(o, "i(vs)")); vn = R._grab(o, "v(n)")
            vr = abs(vin - vn) - iin * 249.0
            out["above30"][f"{d}|{vin:+.0f}"] = dict(i_in_mA=iin * 1e3, i_opamp_in_mA=abs(R._grab(o, "i(vos)")) * 1e3,
                                                     V_100k_part=vr, P_100k_part_mW=vr ** 2 / 100e3 * 1e3)
    out["unpowered"] = unpowered_section()
    return save("prot", out)

# ------------------------------------------------------------------ PR-3 / PR-2 unpowered: diode-level network
# BAT54S (existing type, the AWG's): datasheet C7420333 (models/bat54s-c7420333/), MAXIMUM forward voltage 240 mV at 0.1 mA,
# 320 mV at 1 mA, 400 mV at 10 mA -> IS 1e-7, N 1.34 (the fit in sim/awg/models/awg_behavioural.lib); CT 10 pF max at 1 V;
# IR 2 uA max at 25 V.  Fitted to the maximum VF, so a clamp built from it is shown at its weakest.
DBAT54_MODEL = ".model DBAT54 D(IS=1e-7 N=1.34 RS=2.5 CJO=10p M=0.4 VJ=0.4 BV=30 IBV=1u)"

PCM = {"max": "DBAT54S_MAX", "typ": "DBAT54S_TYP"}
BAT_LIB = os.path.join(HERE, "..", "..", "models-open", "bat54s-c7420333", "bat54s_c7420333.lib")

def unpowered_net(p, vins, bleed, r3sw="on", name="unp", pinclamp=False, pinclamp_model=None):
    """Everything unpowered.  The vendor op-amp model is not usable at zero supply (2b report: it draws ~3.5 mA and
    drives the rail negative), so every IC is replaced by its pin clamps: DESD from each signal pin to its V+ (the AFE
    3.3 V rail, which floats with a bleed to ground) and from ground.  The Due's 3.3 V net is a 0 V source whose
    current is the PR-3 figure; each path into it has its own 0 V ammeter.  ICs whose state with no supply is unknown
    (the TMUX1119s) are taken open, and for the 'R3' proposal both open and on (r3sw)."""
    t = [f"* {name}: unpowered, bleed {bleed} ohm, inputs {vins}", NL.DESD_MODEL.strip(), DBAT54_MODEL,
         ".include ../../../models-open/bat54s-c7420333/bat54s_c7420333.lib",
         "Vdue due 0 dc 0", f"Rbleed rail 0 {bleed}",
         "* powercal's Vmid divider from the shared sense filter (249R) and its tap clamps",
         "Rsh due s0 249", "Rva s0 tap 330k", "Rvb tap 0 330k", "Dt1 tap rail DESD", "Dt2 0 tap DESD",
         "* DAC0: the Due pin's clamps (to the Due's 3.3 V net) and the injection switch's D-pin clamp to the AFE rail",
         "Dd1 dac dacd DESD", "Vadac dacd due 0", "Dd2 0 dac DESD", "Dd3 dac rail DESD"]
    if p.get("sense") == "buf":
        t += ["* the shared sense buffer (OPA365) unpowered: pin clamps; its + input on the Vmid tap",
              "Dbo1 sbo rail DESD", "Dbo2 0 sbo DESD", f"Rsbf sbo sbfb {p['Rbf']:.6g}", f"Rsbg sbfb 0 {p['Rbg']:.6g}",
              "Dbf1 sbfb rail DESD", "Dbf2 0 sbfb DESD"]
    for c, vin in zip("ab", vins):
        r3far = f"{c}r3e" if p.get("inj") == "R3" else f"{c}v3s"
        t += [f"* channel {c}",
              f"Vs{c} s{c} 0 dc {vin}", f"Rsrc{c} s{c} {c}in 50",
              f"R1{c} {c}in {c}n {p['R1']:.6g}", f"R2{c} {c}n {c}vm {p['R2']:.6g}", f"R3{c} {c}n {r3far} {p['R3']:.6g}",
              (f"Rs3{c} {c}v3s sbo {p['Rs3']:.6g}\nVas{c} {c}dues due 0\nRdum{c} {c}dues 0 1e12" if p.get("sense") == "buf"
               else f"Rs3{c} {c}v3s {c}dues {p['Rs3']:.6g}\nVas{c} {c}dues due 0"),
              f"Rnp{c} {c}n {c}np {max(p['Rnp'], 1e-3):.6g}",
              f"Dn1{c} {c}np rail DESD", f"Dn2{c} 0 {c}np DESD",
              f"Df1{c} {c}fb rail DESD", f"Df2{c} 0 {c}fb DESD",
              f"Do1{c} {c}out rail DESD", f"Do2{c} 0 {c}out DESD",
              (f"RF{c} {c}out {c}tp {p['RF']:.6g}\nRG{c} {c}tp {c}vm {p['RG']:.6g}" if p.get("sw") == "kelvin"
               else f"RF{c} {c}out {c}fb {p['RF']:.6g}\nRG{c} {c}fb {c}vm {p['RG']:.6g}"),
              f"Riso{c} {c}out {c}pin {p['Riso']:.6g}",
              f"Dp1{c} {c}pin {c}duep DESD", f"Vap{c} {c}duep due 0", f"Dp2{c} 0 {c}pin DESD",
              *( [f"* BAT54S at the ADC pin: pin 1 to ground, pin 3 on the ADC pin, pin 2 on the upper rail",
                  f"Dk1{c} 0 {c}pin {PCM.get(pinclamp_model, 'DBAT54')}",
                  f"Dk2{c} {c}pin {'due' if pinclamp == 'due' else 'rail'} {PCM.get(pinclamp_model, 'DBAT54')}"] if pinclamp else [] ),
              f"* per-channel Vmid buffer (OPA365) unpowered: output clamps, 1 ohm isolation",
              f"Rvi{c} {c}vm {c}vmo 1", f"Dv1{c} {c}vmo rail DESD", f"Dv2{c} 0 {c}vmo DESD"]
        if p.get("inj") in ("N", "T"):
            t += [f"Ds1{c} {c}n rail DESD", f"Ds2{c} 0 {c}n DESD"]
        elif p.get("inj") == "R3":
            t += [f"Ds1{c} {c}r3e rail DESD", f"Ds2{c} 0 {c}r3e DESD", f"Ds3{c} {c}v3s rail DESD", f"Ds4{c} 0 {c}v3s DESD"]
            if r3sw == "on":
                t += [f"Rsw{c} {c}r3e {c}v3s {p['Ron_inj']:.6g}"]
            else:
                t += [f"Rsw{c} {c}r3e {c}v3s 1e12"]
    t += [".control", "op",
          "print i(Vdue) v(rail) v(an) v(bn) v(apin) v(bpin) v(avm) v(bvm) i(Vsa) i(Vsb) i(Vasa) i(Vasb) i(Vapa) i(Vapb) i(Vadac)",
          ".endc", ".end"]
    o = run_ng(name, "\n".join(t) + "\n")
    g = lambda k: R._grab(o, k)
    return dict(i_due_uA=g("i(vdue)") * 1e6, v_rail=g("v(rail)"), v_an=g("v(an)"), v_bn=g("v(bn)"), v_apin=g("v(apin)"),
                v_bpin=g("v(bpin)"), v_avm=g("v(avm)"), i_in_a_mA=abs(g("i(vsa)")) * 1e3, i_in_b_mA=abs(g("i(vsb)")) * 1e3,
                i_sense_a_uA=g("i(vasa)") * 1e6, i_sense_b_uA=g("i(vasb)") * 1e6, i_pin_a_uA=g("i(vapa)") * 1e6,
                i_pin_b_uA=g("i(vapb)") * 1e6, i_dac_uA=g("i(vadac)") * 1e6, i_bleed_mA=g("v(rail)") / bleed * 1e3)

BLEEDS = (4700.0, 680.0, 340.0, 249.0, 124.5)
INPUTS = ((30.0, 0.0), (-30.0, 0.0), (30.0, 30.0), (-30.0, -30.0), (30.0, -30.0))

def bleed_for(p, vins, target=0.5, pinclamp=False):
    """Largest bleed that keeps the unpowered AFE rail at `target` (bisection on log R), and its quiescent cost at 3.37 V."""
    lo, hi = 10.0, 1e5
    for _ in range(22):
        mid = (lo * hi) ** 0.5
        if unpowered_net(p, vins, mid, name="bl", pinclamp=pinclamp)["v_rail"] < target:
            lo = mid
        else:
            hi = mid
    return dict(bleed_ohm=lo, iq_mA=3.37 / lo * 1e3)

INPUTS2 = {"(a) one input +30 V": (30.0, 0.0), "(b) both inputs +30 V": (30.0, 30.0), "(c) one input +12 V": (12.0, 0.0),
           "(c) both inputs +12 V": (12.0, 12.0), "one input -30 V": (-30.0, 0.0), "(c) one input -12 V": (-12.0, 0.0)}

def sec_unp2():
    """Round 2, PR-3 / PR-2 unpowered with the buffered sense: rail and Due currents at 4.7k and 249 ohm, the bleed for
    a 0.5 V rail, with and without a BAT54S (C7420333) at each ADC pin."""
    out = {}
    p = P("K")
    for lab, vins in INPUTS2.items():
        for pc in (False, True):
            row = {}
            for bl in (4700.0, 249.0):
                row[f"{bl:g}"] = unpowered_net(p, vins, bl, name="u2", pinclamp=pc)
            row["need"] = bleed_for(p, vins, pinclamp=pc) if vins[0] > 0 else None
            if row["need"]:
                row["at_need"] = unpowered_net(p, vins, row["need"]["bleed_ohm"], name="u2", pinclamp=pc)
            out[f"{lab}|{'BAT54S' if pc else 'no clamp'}"] = row
    return save("unp2", out)

def sec_extras():
    """Round 2 comparisons: SC-8 options, one sense buffer or two (SC-9), the MCP3564 input on N, buffer headroom."""
    out = {}
    base = P("K")
    # SC-8: Ron in the +/-5 V gain, three arrangements; SM-3 at the worst corners
    RF7 = 3 * 953.0 + 3 * 249.0 + 49.9
    opts = {"RF shunted by the switch, 953 / 249 (round 1)": dict(sw="rf"), "RF shunted, RG 953 / RF 3x953+3x249+49.9": dict(sw="rf", RG=953.0, RF=RF7),
            "Kelvin: the switch selects what (-) senses, 953 / 249 (adopted)": dict(sw="kelvin")}
    sc8 = {}
    for name, o in opts.items():
        row = {}
        for rng in ("5", "1.25"):
            g = [R.ac_summary(dict(base, **o, rng=rng, Ron_sw=ron), "x8")["g0"] for ron in (3.7, R.RON_MAX)]
            w, pm = 1e99, 1e9
            for kw in corners("K"):
                a = R.ac_summary(dict(base, **o, rng=rng, **kw), "x8c"); w = min(w, a["bw"]); pm = min(pm, a["pm"])
            row[rng] = dict(g_ron37=g[0], g_ron88=g[1], ron_spread_pct=(g[1] / g[0] - 1) * 100, worst_bw=w, worst_pm=pm)
        sc8[name] = row
    out["sc8"] = sc8
    # one sense buffer or one per channel: SC-9 (DC kick incl. static, and the AC sweep)
    sb = {}
    for name, o in (("shared", dict(sbuf="shared")), ("per channel", dict(sbuf="perch"))):
        r = {}
        for rng, vfs in (("5", 6.0), ("1.25", 1.25)):
            q = dict(base, rng=rng, **o)
            hi = R.kick_run(q, +vfs, 0.0, R.ADC_DERIVED, name="xs", aref=3.2); lo = R.kick_run(q, -vfs, 0.0, R.ADC_DERIVED, name="xs", aref=3.2)
            tot = abs((hi["vpin_b"] + hi["errB_lsb"] * LSB32) - (lo["vpin_b"] + lo["errB_lsb"] * LSB32)) / LSB32
            f, hb, ha = ac_xtalk(q, "xsa")
            r[rng] = dict(dc_total_lsb=tot, ac_max_lsb=float((hb * vfs / LSB32).max()))
        sb[name] = r
    out["sense_buffer"] = sb
    # MCP3564 input on N: pin capacitance (not in DS20006181C) and coupling from the AWG nodes (CTALK -130 dB is given at
    # 50 Hz only), with an optional series resistor; SM-3 worst corner on +/-1.25 V and AWG coupling peak
    mc = []
    for R_ in (0.0, 680.0, 4700.0, 22e3, 100e3):
        for cp in (2e-12, 5e-12, 10e-12):
            for cx in (0.0, 0.05e-12, 0.3e-12):
                q = dict(base, mcp=dict(R=R_, Cp=cp, Cx=cx))
                w = min(R.ac_summary(dict(q, rng="1.25", **kw), "xm")["bw"] for kw in (dict(Cpar_extra=3e-12, Ron_sw=R.RON_MAX, Cn=3e-12, Cr1=0.1e-12),))
                f, ha = awg_coupling(dict(q, rng="1.25"), "xma")
                mc.append(dict(R=R_, Cp_pF=cp * 1e12, Cx_pF=cx * 1e12, worst_bw_125=w, awg_max_lsb=float((ha * DAC_AMP / LSB32).max()),
                               dc_read_err_pct=0.30 * R_ / 2.08e6 * 100))
    out["mcp"] = mc
    # sense-buffer headroom: its output at AREF 3.30 against the lowest rail, and the Due pin's current
    k = 1 + base["Rbf"] / base["Rbg"]
    out["buffer"] = dict(k=k, v_out_at_aref330=k * 1.65, headroom_to_323=3.23 - k * 1.65,
                         due_pin_uA=3.30 / 660e3 * 1e6)
    return save("extras", out)

# ------------------------------------------------------------------ round 2b: how powercal reads N (coordinator options a/b/c)
CP_MCP = (2e-12, 5e-12, 10e-12)   # MCP3564 pin capacitance: NOT in DS20006181C; bounded *(check)*

def beta_err(p, state):
    """Option (b): the host computes N = beta x V(D), beta = G3/(G1'+G2+G3) with R3 alone (the MCP reads R3's own end).
    Worst-case and RSS (uniform 0.1 %) error of beta from the three resistors, for the BNC open / shorted / 50 ohm."""
    rs = {"open": None, "short": 0.0, "50 ohm": 50.0}[state]
    g1 = 0.0 if rs is None else 1 / (p["R1"] + rs); g2 = 1 / p["R2"]; g3 = 1 / p["R3"]; gt = g1 + g2 + g3
    s = dict(R3=1 - g3 / gt, R2=g2 / gt, R1=g1 / gt)          # |d ln beta / d ln R|
    return dict(beta=g3 / gt, worst_pct=sum(s.values()) * 0.1, rss_pct=float(np.sqrt(sum(v * v for v in s.values()) / 3)) * 0.1, sens=s)

def sec_options():
    out = {"a": [], "b": {}, "c": []}
    base = P("K")
    W = (dict(Cpar_extra=3e-12, Ron_sw=R.RON_MAX, Cn=3e-12, Cr1=0.1e-12), dict(Cpar_extra=-2e-12, Ron_sw=3.7, Cn=3e-12, Cr1=0.1e-12))
    def sm3(q):
        return {r: min(R.ac_summary(dict(q, rng=r, **kw), "op")["bw"] for kw in W) for r in ("5", "1.25")}
    def awg(q):
        f, ha = awg_coupling(dict(q, rng="1.25"), "opa"); return float((ha * DAC_AMP / LSB32).max())
    rth = divider(base)["rth"]
    out["reference_no_mcp"] = dict(sm3=sm3(base), awg_lsb=awg(base), rth=rth)
    # (a) MCP pin on N through a series resistor
    for R_ in (0.0, 100e3, 330e3, 1e6, 3.3e6, 10e6):
        for cp in CP_MCP:
            q = dict(base, mcp=dict(R=R_, Cp=cp, Cx=0.3e-12))
            ratio = 2.08e6 / (R_ + 2.08e6)
            out["a"].append(dict(R=R_, Cp_pF=cp * 1e12, sm3=sm3(q), awg_lsb=awg(q),
                                 hf_load_pct=(100 * rth / R_ if R_ > 0 else float("inf")),
                                 read_ratio=ratio, read_err_pct=100 * (2.08e6 * 1.3 / (R_ + 2.08e6 * 1.3) - 2.08e6 * 0.7 / (R_ + 2.08e6 * 0.7)) / 2 / ratio))
    # (b) MCP on the switch's D node (R3's end): N carries nothing new; beta from the resistors
    q = dict(base, mcpD=True)
    out["b"]["sm3"] = sm3(base); out["b"]["awg_lsb"] = awg(base)
    out["b"]["beta"] = {st: beta_err(base, st) for st in ("open", "short", "50 ohm")}
    b0 = beta_err(base, "short")["beta"]
    out["b"]["state_mismatch_pct"] = {f"model {m} / actual {a}": 100 * (beta_err(base, a)["beta"] / beta_err(base, m)["beta"] - 1)
                                      for m in ("open", "short", "50 ohm") for a in ("open", "short", "50 ohm") if m != a}
    # (c) a lower Thevenin: scale R1, R2 and the R3 network (the 249 sense resistor and Ron stay), MCP pin straight on N
    for s in (1.0, 0.8, 0.65, 0.5, 0.4):
        for cp in (0.0,) + CP_MCP:
            q = dict(base, R1=base["R1"] * s, R2=base["R2"] * s, R3=(base["R3"] + 255.25) * s - 255.25)
            if cp:
                q["mcp"] = dict(R=0.0, Cp=cp, Cx=0.3e-12)
            d = divider(q)
            out["c"].append(dict(scale=s, Cp_pF=cp * 1e12, rth=d["rth"], rin=d["rin"], alpha=d["alpha"], sm3=sm3(q), awg_lsb=awg(q),
                                 tau_ns=d["rth"] * (base["Cn"] + 2e-12 + cp) * 1e9))
    return save("options", out)

def export_loop():
    """Single-channel netlist bodies for sim/loop (SM-5), one per case; the loop agent supplies rails, source and ADC."""
    base = P("K", rng="1.25")
    cases = {"opt0_noMCP": base, "optA_R1M_Cp5": dict(base, mcp=dict(R=1e6, Cp=5e-12, Cx=0.0)),
             "optA_R10M_Cp5": dict(base, mcp=dict(R=10e6, Cp=5e-12, Cx=0.0)), "optB_mcpD": base,
             "optC_direct_Cp2": dict(base, mcp=dict(R=0.0, Cp=2e-12, Cx=0.0)), "optC_direct_Cp5": dict(base, mcp=dict(R=0.0, Cp=5e-12, Cx=0.0)),
             "optC_s0.5_Cp5": dict(base, R1=base["R1"] * 0.5, R2=base["R2"] * 0.5, R3=(base["R3"] + 255.25) * 0.5 - 255.25, mcp=dict(R=0.0, Cp=5e-12, Cx=0.0))}
    d = os.path.join(HERE, "netlists_lowz2", "for_loop"); os.makedirs(d, exist_ok=True)
    for n, q in cases.items():
        with open(os.path.join(d, n + ".cir"), "w") as f:
            f.write(f"* {n}: one scope channel (+/-1.25 V range), sim/scope variant lowz2.  Nodes: in (BNC), vm (Vmid), vccl (rail),\n"
                    "* v3 (Due 3.3 V pin), dac (injection source), pin (ADC pin).  Needs the OPA354 and OPA365 models, models/rangesw.lib.\n"
                    + (header(q, n) + rails(q) + core(q) + "\n").replace("../../../models/", "../../../../models/").replace("../models/rangesw.lib", "../../models/rangesw.lib"))
    return list(cases)

C2_COMBOS_BASIC = {   # Basic types only (12 pF, 20 pF): no 39 pF (Extended)
    "20 + 12 (32)": 32e-12, "12 x 3 (36)": 36e-12, "20 + 12 + 12s12s12 (36)": 36e-12, "20 + 12 + 12s12s20 (36.6)": 32e-12 + 1 / (2 / 12e-12 + 1 / 20e-12),
    "20 + 12 + 12s20s20 (37.5)": 32e-12 + 1 / (1 / 12e-12 + 2 / 20e-12), "20 + 12 + 12s20 (39.5)": 39.5e-12, "20 + 12 + 12s12 (38)": 38e-12,
    "20 + 20 (40)": 40e-12, "12 x 3 + 12s12s12 (40)": 40e-12, "20 + 12 + 20s20s20 (38.7)": 32e-12 + 20e-12 / 3,
    "tee what-if: 20 + 12 + 12s12s39 (37.2, Extended 39)": 32e-12 + 1 / (2 / 12e-12 + 1 / 39e-12)}
C2_COMBOS = {"39": 39e-12, "20 + 12": 32e-12, "12 + 12": 24e-12, "20 + 12s20 (27.5)": 20e-12 + 7.5e-12, "20 + 12s39 (29.2)": 20e-12 + 12e-12 * 39e-12 / 51e-12,
             "20 + 12s12 (26)": 26e-12, "12 + 20s39 (25.2)": 12e-12 + 20e-12 * 39e-12 / 59e-12, "20 + 20s39 (33.2)": 20e-12 + 20e-12 * 39e-12 / 59e-12,
             "12 x 3 (36)": 36e-12, "20 + 20 (40)": 40e-12, "20 + 12s12s... 12+12+12s20 (31.5)": 24e-12 + 7.5e-12, "39s(20+12+12) (20.9)": 39e-12 * 44e-12 / 83e-12,
             "20 + 39s39 (39.5)": 39.5e-12, "12 + 12s39 + 12 (33.2)": 24e-12 + 12e-12 * 39e-12 / 51e-12}

def sec_comp():
    """C2 for the fixed C1 = 12 pF with the switch's CSOFF at N: the null of the DC-to-100 kHz gain step (+/-5 V range),
    swept, then every 1-3 part combination of the 12 / 20 / 39 pF types, at CSOFF 6 pF (datasheet) and 10 pF (IBIS)."""
    out = {"sweep": {}, "combos": {}}
    noinj = not P("H").get("inj")
    for csw in ((0.0,) if noinj else (6e-12, 10e-12)):
        rows = []
        for c2 in np.arange(18e-12, 46.5e-12, 1e-12):
            f, h, T = NL.ac_response(P("H", rng="5", C2=c2, Csoff=csw), "cmp", fmin=100.0, fmax=1e7, ppd=20)
            a = np.abs(h); g = lambda x: float(np.interp(np.log10(x), np.log10(f), a))
            rows.append(dict(C2=c2, step_100k_pct=(g(1e5) / g(1e3) - 1) * 100, step_10k_pct=(g(1e4) / g(1e3) - 1) * 100))
        x = np.array([r["C2"] for r in rows]); y = np.array([r["step_100k_pct"] for r in rows])
        i = int(np.where(np.diff(np.sign(y)) != 0)[0][0])
        null = float(x[i] - y[i] * (x[i + 1] - x[i]) / (y[i + 1] - y[i]))
        out["sweep"][f"{csw*1e12:.0f}"] = dict(rows=rows, null_pF=null * 1e12, slope_pct_per_pF=float((y[i + 1] - y[i]) / ((x[i + 1] - x[i]) * 1e12)))
    for name, c2 in (C2_COMBOS_BASIC if noinj else C2_COMBOS).items():
        r = {}
        for csw in ((0.0,) if noinj else (6e-12, 10e-12)):
            for rng in ("5", "1.25"):
                f, h, T = NL.ac_response(P("H", rng=rng, C2=c2, Csoff=csw), "cmc", fmin=100.0, fmax=2e9, ppd=30)
                a = np.abs(h); g = lambda x: float(np.interp(np.log10(x), np.log10(f), a))
                m = freq_metrics(f[f >= 1e4], h[f >= 1e4])
                r[f"{csw*1e12:.0f}|{rng}"] = dict(step_10k_pct=(g(1e4) / g(1e3) - 1) * 100, step_100k_pct=(g(1e5) / g(1e3) - 1) * 100,
                                                  flat_1_8MHz_db=max(abs(20 * np.log10(g(xx) / g(1e5))) for xx in (1e6, 2e6, 4e6, 6e6, 8e6)), bw=m["bw"])
        out["combos"][name] = dict(C2_pF=c2 * 1e12, res=r)
    return save("comp", out)

def sec_csw():
    """Information for VT-4: the TMUX1119's CSOFF is given at one point (6 pF, f = 1 MHz) and the IBIS model's at 10 pF; no
    voltage dependence is published.  What a C(V) would do: the 100 kHz gain step at CSOFF 4-12 pF, and the step's change
    over the signal swing at N if CSOFF varied linearly by +/-20 % over 0..3.3 V *(assumption, no data)*."""
    out = []
    for csw in (4e-12, 6e-12, 8e-12, 10e-12, 12e-12):
        f, h, T = NL.ac_response(P("H", rng="5", Csoff=csw), "csw", fmin=100.0, fmax=1e7, ppd=20)
        a = np.abs(h); g = lambda x: float(np.interp(np.log10(x), np.log10(f), a))
        out.append(dict(Csoff_pF=csw * 1e12, step_100k_pct=(g(1e5) / g(1e3) - 1) * 100))
    return save("csw", out)

def sec_clamp_hz():
    """BAT54S C7420333 at each ADC pin (after Riso): unpowered PR-2 / PR-3 for both upper-rail choices and both fits,
    powered PR-2, SM-3 and SC-10 with its capacitance, and its leakage into the op-amp-driven pin."""
    out = {"unpowered": {}, "powered": {}, "ac": {}, "kick": {}, "leak": {}}
    p = P("H")
    for up_ in ("rail", "due"):
        for mdl in ("max", "typ"):
            for k, v in INPUTS_HZ.items():
                out["unpowered"][f"{up_}|{mdl}|{k}"] = unpowered_net(p, v, 4700.0, name="uhc", pinclamp=up_, pinclamp_model=mdl)
    for up_ in ("rail", "due"):
        for rng in ("5", "1.25"):
            for vin in (12.0, -12.0, 30.0, -30.0):
                q = dict(P("H", rng=rng, pinclamp=up_), v3=3.3)
                txt = header(q, "pcp") + rails(q, vcc=3.37, vmid=1.65) + f"Vs in 0 dc {vin}\n" + core(q) + "\n.control\nop\nprint v(pin) i(V3s)\n.endc\n.end\n"
                o = run_ng("pcp", txt)
                out["powered"][f"{up_}|{rng}|{vin:+.0f}"] = dict(v_pin=R._grab(o, "v(pin)"), i_due33_uA=R._grab(o, "i(v3s)") * 1e6)
    for rng in ("5", "1.25"):
        q = P("H", rng=rng, pinclamp="rail")
        out["ac"][rng] = dict(nominal=R.ac_summary(q, "pca")["bw"],
                              worst=min(R.ac_summary(dict(q, **kw), "pcc")["bw"] for kw in corners("H")),
                              pm=min(R.ac_summary(dict(q, **kw), "pcc")["pm"] for kw in corners("H")[:6]))
        vfs = 6.0 if rng == "5" else 1.25
        for lab, adc in (("derived", R.ADC_DERIVED), ("stress", R.ADC_STRESS)):
            k = R.kick_run(q, vfs, -vfs, adc, name="pck", aref=3.2)
            out["kick"][f"{rng}|{lab}"] = dict(err_lsb=max(abs(k["errA_lsb"]), abs(k["errB_lsb"])), settle_ns=k["settleB_ns"])
        # leakage: the pin's DC value with the 12.5 Mohm leakage bound against none, over the swing
        for vin in (-vfs, 0.0, vfs):
            a_ = R.dc_metrics(dict(P("H", rng=rng, pinclamp="rail"), aref=3.3), rng)
            b_ = R.dc_metrics(dict(P("H", rng=rng, pinclamp="rail", pinclamp_leak=True), aref=3.3), rng)
            c_ = R.dc_metrics(dict(P("H", rng=rng), aref=3.3), rng)
        out["leak"][rng] = dict(d_lo_uV=(b_["lo"] - c_["lo"]) * 1e6, d_mid_uV=(b_["mid"] - c_["mid"]) * 1e6, d_hi_uV=(b_["hi"] - c_["hi"]) * 1e6,
                                d_lo_nopar_uV=(a_["lo"] - c_["lo"]) * 1e6, d_hi_nopar_uV=(a_["hi"] - c_["hi"]) * 1e6)
    return save("clamp_hz", out)

INPUTS_HZ = {"+12 V both": (12.0, 12.0), "-12 V both": (-12.0, -12.0), "+12 / -12 V": (12.0, -12.0), "+30 V one (information)": (30.0, 0.0),
             "+30 V both (information)": (30.0, 30.0), "-30 V both (information)": (-30.0, -30.0)}

def unp_hz():
    p = P("H")
    return {k: unpowered_net(p, v, 4700.0, name="uhz", pinclamp=p.get("pinclamp"), pinclamp_model=p.get("pinclamp_model")) for k, v in INPUTS_HZ.items()}

def unpowered_section():
    if NL.VARIANT == "hz":
        return unp_hz()
    out = {}
    for d in DESIGNS:
        sws = ("on", "off") if P(d).get("inj") == "R3" else ("na",)
        for sw in sws:
            for bl in BLEEDS:
                for vins in INPUTS:
                    out[f"{d}|{sw}|{bl:g}|{vins[0]:+.0f},{vins[1]:+.0f}"] = unpowered_net(P(d), vins, bl, r3sw=sw)
    # option: a BAT54S at each ADC pin (to ground and to the AFE rail)
    for d in DESIGNS:
        sw = "on" if P(d).get("inj") == "R3" else "na"
        for bl in (4700.0, 249.0, 124.5):
            for vins in INPUTS:
                out[f"{d}+clamp|{sw}|{bl:g}|{vins[0]:+.0f},{vins[1]:+.0f}"] = unpowered_net(P(d), vins, bl, r3sw=sw, pinclamp=True)
    return out

def sec_pinclamp():
    """What a BAT54S at each ADC pin costs in normal operation: its 10 pF (CT max at 1 V) on the pin behind Riso, for
    SM-3, AN-1 and the S/H kick; its leakage (IR 2 uA max at 25 V) through Riso 22 ohm is 44 uV, by arithmetic."""
    out = {}
    for d in DESIGNS:
        for rng in ("5", "1.25"):
            r = {}
            q = P(d, rng=rng, Cpin=P(d)["Cpin"] + 10e-12)
            r["nominal"] = R.ac_summary(q, "pc_n")
            wb, wp = 1e99, 1e9
            for kw in corners(d):
                a = R.ac_summary(dict(q, **kw), "pc_c"); wb = min(wb, a["bw"]); wp = min(wp, a["pm"])
            r["worst_bw"], r["worst_pm"] = wb, wp
            k = R.kick_run(q, 6.0 if rng == "5" else 1.25, -6.0 if rng == "5" else -1.25, R.ADC_DERIVED, name="pc_k", aref=3.2)
            r["kick_err_lsb"] = max(abs(k["errA_lsb"]), abs(k["errB_lsb"])); r["kick_settle_ns"] = k["settleB_ns"]
            out[f"{d}_{rng}"] = r
    return save("pinclamp", out)

# ------------------------------------------------------------------ guards: each check broken on purpose
def g_dc(p):
    m = R.dc_metrics(dict(p, aref=3.2), p["rng"])
    lo, hi = (0.2290, 0.2453) if p["rng"] == "5" else (1.10, 1.16)
    ok = abs(m["mid"] - 1.6) < 0.010 and lo <= m["gain"] <= hi and min(m["margin_hi"], m["margin_lo"]) >= 0.080
    return ok, f"mid {m['mid']:.4f} V (centre 1.6000 +/-10 mV), gain {m['gain']:.4f} (window {lo}-{hi}), margin {min(m['margin_hi'], m['margin_lo'])*1e3:.0f} mV (>=80)"

def g_bw(p):
    worst = 1e99
    for kw in (dict(Cpar_extra=3e-12, Ron_sw=R.RON_MAX, Cn=3e-12, Cr1=0.1e-12), dict(Cpar_extra=-2e-12, Ron_sw=3.7, Cn=3e-12, Cr1=0.1e-12)):
        worst = min(worst, R.ac_summary(dict(p, **kw), "g_bw")["bw"])
    return worst >= 8e6, f"worst-corner BW {worst/1e6:.2f} MHz (>=8)"

def g_pm(p):
    worst = 1e9
    for cx in (-2e-12, 0.0, 3e-12):
        worst = min(worst, R.ac_summary(dict(p, Cpar_extra=cx), "g_pm")["pm"])
    return worst >= 45, f"worst PM {worst:.1f} deg (>=45)"

def g_clamp(p):
    worst = 0.0
    for vin in (30.0, -30.0):
        q = dict(p, v3=3.3, esd_n=True)
        txt = header(q, "gcl") + rails(q, vcc=3.37, vmid=1.65) + f"Vs in 0 dc {vin}\n" + core(q) + "\n.control\nop\nprint i(Vos)\n.endc\n.end\n"
        worst = max(worst, abs(R._grab(run_ng("gcl", txt), "i(vos)")) * 1e3)
    return worst <= 10.0, f"op-amp input clamp current at +/-30 V DC {worst:.2f} mA (<=10)"

def g_noise(p):
    a = R.ac_summary(p, "g_nz"); n = noise_total(p, "g_nz", 1.5 * a["bw"], "all")
    return n <= 200e-6, f"noise to 1.5 x BW ({1.5*a['bw']/1e6:.0f} MHz) {n*1e6:.0f} uV (<=200)"

def g_settle(p):
    r = R.kick_run(p, 6.0, -6.0, R.ADC_DERIVED, name="g_k", aref=3.2)
    e = max(abs(r["errA_lsb"]), abs(r["errB_lsb"]))
    return e <= 0.5, f"S/H error at the end of the 15-clock track {e:.3f} LSB (<=0.5)"

def g_xtalk(p):
    hi = R.kick_run(p, 6.0, 0.0, R.ADC_DERIVED, name="g_x", aref=3.2)
    lo = R.kick_run(p, -6.0, 0.0, R.ADC_DERIVED, name="g_x", aref=3.2)
    tot = abs((hi["vpin_b"] + hi["errB_lsb"] * LSB32) - (lo["vpin_b"] + lo["errB_lsb"] * LSB32)) / LSB32
    return tot <= 2.0, f"B's reading moves {tot:.3f} LSB with A at +6 / -6 V DC (<=2)"

def g_awg(p):
    f, ha = awg_coupling(p, "g_awg")
    m = float((ha * DAC_AMP / LSB32).max())
    return m <= 2.0, f"AWG (DAC0 full swing, 10 Hz-20 MHz) into the pin: {m:.3f} LSB peak (<=2)"

def supply_uA(r):
    """PR-3's figure: current into the Due's SUPPLY pins (the 3.3 V pin through the sense paths and powercal's Vmid
    divider, plus DAC0's clamp, which lands on the same net), excluding what enters through the ADC pins' clamps."""
    return r["i_due_uA"] - r["i_pin_a_uA"] - r["i_pin_b_uA"]

def g_unp(p):
    worst_i, worst_v, worst_p = 0.0, 0.0, 0.0
    for vins in ((30.0, 0.0), (-30.0, 0.0)):
        r = unpowered_net(p, vins, p["_bleed"], name="g_unp")
        worst_i = max(worst_i, abs(supply_uA(r))); worst_v = max(worst_v, abs(r["v_rail"]))
        worst_p = max(worst_p, abs(r["i_pin_a_uA"]) + abs(r["i_pin_b_uA"]))
    return worst_i <= 100 and worst_v < 0.5, (f"one input at +/-30 V, unpowered: into the Due's supply pins {worst_i:.1f} uA (<=100), "
                                              f"AFE rail {worst_v:.3f} V (<0.5); into the ADC pins' clamps {worst_p:.1f} uA (not in this check)")

def g_unp_total(p):
    worst = 0.0
    for vins in ((30.0, 0.0), (-30.0, 0.0)):
        r = unpowered_net(p, vins, 249.0, name="g_unt", pinclamp=p.get("_pinclamp", False))
        worst = max(worst, abs(r["i_due_uA"]))
    return worst <= 100, f"one input at +/-30 V, unpowered, 249 ohm bleed: everything into the Due incl. the ADC pins {worst:.1f} uA (<=100)"

def g_sc8(p):
    g = [R.ac_summary(dict(p, rng="5", Ron_sw=ron), "g8")["g0"] for ron in (3.7, R.RON_MAX)]
    spread = abs(g[1] / g[0] - 1) * 100 + 0.4    # + 4 x 0.1 % of resistor tolerance between two channels' dividers
    return spread <= 3.0, f"+/-5 V gain spread between channels: Ron term {abs(g[1]/g[0]-1)*100:.3f} % + 0.4 % resistors = {spread:.2f} % (<=3)"

def g_unp_hz(p):
    wi, wv = 0.0, 0.0
    for vins in ((12.0, 12.0), (-12.0, -12.0)):
        r = unpowered_net(p, vins, p["_bleed"], name="g_uh", pinclamp=p.get("pinclamp"), pinclamp_model=p.get("pinclamp_model"))
        wi = max(wi, abs(r["i_due_uA"])); wv = max(wv, abs(r["v_rail"]))
    return wi <= 100 and wv < 0.5, f"both inputs at +/-12 V, unpowered: into the Due {wi:.1f} uA (<=100, ADC pins included), AFE rail {wv:.3f} V (<0.5)"

def g_pin_hz(p):
    r = unpowered_net(p, (-12.0, -12.0), 4700.0, name="g_ph", pinclamp=p.get("pinclamp"), pinclamp_model=p.get("pinclamp_model"))
    v = min(r["v_apin"], r["v_bpin"])
    return v >= -0.2, f"ADC pin {v:.3f} V with both inputs at -12 V, unpowered (>= -0.2)"

def guards3():
    G = []
    def run_(name, guard, good, broken, what):
        ok1, d1 = guard(good); ok2, d2 = guard(broken); ok3, d3 = guard(good)
        G.append(dict(guard=name, mutation=what, good=dict(ok=bool(ok1), detail=d1), broken=dict(ok=bool(ok2), detail=d2),
                      restored=dict(ok=bool(ok3), detail=d3), effective=bool(ok1 and not ok2 and ok3)))
    good = P("H", rng="5"); good12 = P("H", rng="1.25")
    run_("DC transfer (SC-2, SC-4, SC-11)", g_dc, good, dict(good, R2=450e3), "R2 330k -> 450k")
    run_("DC centring (SC-2)", g_dc, good, dict(good, R3=None), "R3 removed (R2 to Vmid only, the first specification)")
    run_("Bandwidth >= 8 MHz (SM-3)", g_bw, good12, dict(good12, op="OPA365"), "OPA354 -> OPA365")
    run_("Phase margin >= 45 deg (AN-1)", g_pm, good, dict(good, sw="rg", RF=3.83e3, RG=1.00e3, Rnp=0.0), "range switch in the RG leg, RF 3.83k / RG 1k")
    run_("Edge clamp current <= 10 mA (PR-1)", R.g_edge, good, dict(good, Rnp=0.0), "Rnp removed")
    run_("Noise <= 0.2 mV (SC-6)", g_noise, good12, dict(good12, RG=60.4), "RG 249 -> 60.4 ohm")
    run_("ADC settling <= 0.5 LSB (SC-10)", g_settle, good, dict(good, Riso=20e3), "Riso 22 -> 20 kohm")
    run_("Scope-to-scope crosstalk <= 2 LSB (SC-9)", g_xtalk, good, dict(good, vmid_perch=False, Rvo=1.0), "one shared Vmid at 1 ohm instead of a buffer per channel")
    run_("Gain matching <= 3 % (SC-8)", g_sc8, good, dict(good, RF=383.0, RG=100.0), "RF/RG 383/100 (same ratio, Ron/RG x 2.5)")
    run_("Unpowered ADC pin >= -0.2 V at -12 V (PR-2)", g_pin_hz, good, dict(good, pinclamp=None), "BAT54S at the ADC pin removed")
    run_("Unpowered +/-12 V on both inputs (PR-3)", g_unp_hz, dict(good, _bleed=4700.0), dict(good, _bleed=47e3), "bleed 4.7 kohm -> 47 kohm")
    return save("guards", G)

def guards():
    if NL.VARIANT == "hz":
        return guards3()
    if NL.VARIANT == "lowz2":
        return guards2()
    G = []
    def run_(name, guard, good, broken, what):
        ok1, d1 = guard(good); ok2, d2 = guard(broken); ok3, d3 = guard(good)
        G.append(dict(guard=name, mutation=what, good=dict(ok=bool(ok1), detail=d1), broken=dict(ok=bool(ok2), detail=d2),
                      restored=dict(ok=bool(ok3), detail=d3), effective=bool(ok1 and not ok2 and ok3)))
    good = P("R3", rng="5"); good12 = P("R3", rng="1.25")
    run_("DC transfer (SC-2, SC-4, SC-11)", g_dc, good, dict(good, R2=good["R2"] * 1.35), "R2 x 1.35 (a wrong divider ratio)")
    run_("DC centring (SC-11)", g_dc, good12, dict(good12, R1=good12["R1"] - 249.0), "the 249 in series with R1 left out (R1 no longer matches the R3 leg)")
    run_("Bandwidth >= 8 MHz at the worst corner (SM-3)", g_bw, good12, dict(good12, inj="N"), "injection switch moved back onto N (CSOFF 6 pF + feedthrough)")
    run_("Phase margin >= 45 deg (AN-1)", g_pm, good, dict(good, sw="rg", RF=3.83e3, RG=1.00e3), "range switch back in the RG leg, RF 3.83k / RG 1k")
    run_("Clamp current <= 10 mA (PR-1)", g_clamp, good, dict(good, R1=1000.0, R3=1000.0 - 249.0, R2=440.0), "divider scaled to a 1.3 kohm input (protection resistance gone)")
    run_("Noise <= 0.2 mV (SC-6)", g_noise, good12, dict(good12, RG=60.4), "RG 249 -> 60.4 ohm (gain 16.8)")
    run_("ADC settling <= 0.5 LSB (SC-10)", g_settle, good, dict(good, Riso=20e3), "Riso 22 ohm -> 20 kohm")
    run_("Scope-to-scope crosstalk <= 2 LSB (SC-9)", g_xtalk, good, dict(good, sense="shared"), "one shared 249R + 10 uF sense filter for both channels (the approved BOM's)")
    run_("AWG coupling <= 2 LSB (SC-9)", g_awg, good12, dict(good12, inj="N"), "injection switch back on N (feedthrough 1.8 pF into a 4 kohm node)")
    run_("Unpowered +/-30 V (PR-3)", g_unp, dict(good, _bleed=249.0), dict(good, _bleed=4700.0), "AFE rail bleed 249 ohm -> the 4.7 kohm of the approved BOM")
    run_("Unpowered, total into the Due incl. ADC pins (PR-3, strict reading)", g_unp_total, dict(good, _pinclamp=True), dict(good, _pinclamp=False),
         "BAT54S at each ADC pin removed")
    return save("guards", G)

def guards2():
    G = []
    def run_(name, guard, good, broken, what):
        ok1, d1 = guard(good); ok2, d2 = guard(broken); ok3, d3 = guard(good)
        G.append(dict(guard=name, mutation=what, good=dict(ok=bool(ok1), detail=d1), broken=dict(ok=bool(ok2), detail=d2),
                      restored=dict(ok=bool(ok3), detail=d3), effective=bool(ok1 and not ok2 and ok3)))
    good = P("K", rng="5"); good12 = P("K", rng="1.25")
    run_("DC transfer (SC-2, SC-4, SC-11)", g_dc, good, dict(good, R2=good["R2"] * 1.35), "R2 x 1.35")
    run_("DC centring (SC-11)", g_dc, good12, dict(good12, Rbg=good12["Rbg"] * 1.01), "sense buffer's Rbg +1 % (gain error 0.45 %)")
    run_("Bandwidth >= 8 MHz (SM-3)", g_bw, good12, dict(good12, inj="N"), "injection switch back on N")
    run_("Phase margin >= 45 deg (AN-1)", g_pm, good, dict(good, sw="rg", RF=3.83e3, RG=1.00e3), "range switch in the RG leg, RF 3.83k / RG 1k")
    run_("Clamp current <= 10 mA (PR-1)", g_clamp, good, dict(good, R1=1000.0, R3=1000.0 * 0.8284 - 255.25, R2=480.0), "divider scaled to a 1.3 kohm input")
    run_("Noise <= 0.2 mV (SC-6)", g_noise, good12, dict(good12, RG=60.4), "RG 249 -> 60.4 ohm")
    run_("ADC settling <= 0.5 LSB (SC-10)", g_settle, good, dict(good, Riso=20e3), "Riso 22 -> 20 kohm")
    run_("Scope-to-scope crosstalk <= 2 LSB (SC-9)", g_xtalk, good, dict(good, Rvo=1.0), "shared Vmid at 1 ohm instead of 50 mohm")
    run_("AWG coupling <= 2 LSB (SC-9)", g_awg, good12, dict(good12, inj="N"), "injection switch back on N")
    run_("Gain matching <= 3 % (SC-8)", g_sc8, good, dict(good, RF=383.0, RG=100.0), "RF/RG scaled to 383/100 (same ratio, Ron/RG x 2.5)")
    run_("Unpowered +/-30 V, one input (PR-3)", g_unp, dict(good, _bleed=249.0), dict(good, _bleed=4700.0), "bleed 249 ohm -> 4.7 kohm")
    return save("guards", G)

# ------------------------------------------------------------------ driver
SECS = ["dc", "ac", "kick", "prot", "noise", "guards", "sweep", "pinclamp", "report"]
if NL.VARIANT == "lowz2":
    SECS = ["dc", "ac", "kick", "prot", "noise", "guards", "pinclamp", "extras", "unp2", "report"]
if NL.VARIANT == "hz":
    SECS = ["dc", "ac", "kick", "prot", "noise", "guards", "comp", "clamp", "report"]
FUN = dict(clamp=sec_clamp_hz, comp=sec_comp, csw=sec_csw, options=sec_options, dc=sec_dc, ac=sec_ac, kick=sec_kick, prot=sec_prot, noise=sec_noise, guards=guards, sweep=sec_sweep, pinclamp=sec_pinclamp,
           extras=sec_extras, unp2=sec_unp2)

def main(argv):
    par = "--par" in argv
    want = [a for a in argv if not a.startswith("--")] or SECS
    t0 = time.time()
    if par:
        # wave 1 needs nothing; noise needs ac's bandwidths; the report needs everything
        waves = [[s for s in ("dc", "ac", "kick", "prot") if s in want], [s for s in ("noise", "guards", "sweep", "pinclamp", "comp", "csw", "clamp") if s in want],
                 [s for s in ("extras", "unp2") if s in want]]
        for wv in waves:
            procs = [subprocess.Popen([sys.executable, "-I", os.path.join(HERE, "run.py"), "--variant", NL.VARIANT, s], cwd=HERE) for s in wv]
            for pr in procs:
                if pr.wait() != 0:
                    raise SystemExit(f"section failed: {pr.args}")
            print("wave", wv, round(time.time() - t0), flush=True)
        if "report" in want:
            report()
        return
    for s in want:
        if s == "report":
            report()
        else:
            NL.PFX = s + "_"
            FUN[s]()
        print(s, round(time.time() - t0), flush=True)

def report():
    if NL.VARIANT == "hz":
        import report_hz; report_hz.make()
    elif NL.VARIANT == "lowz2":
        import report_lowz2; report_lowz2.make()
    else:
        import report_lowz; report_lowz.make()
