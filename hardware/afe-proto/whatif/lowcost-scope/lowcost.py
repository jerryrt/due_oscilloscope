#!/usr/bin/env python3
"""Low-cost scope what-if (2026-11-11), on a snapshot of sim/scope (variant 'hz', the 1 Mohm design).

  D  : both scope amplifiers in one OPA2354 (vendor model per channel, one shared supply pin and decoupler, and the
       dual's channel-to-channel crosstalk from SBOS233H Fig. 6-28 as an input-referred source in each + input)
  M  : both scope Vmid buffers in one MCP6002 (open behavioural model, models-open/mcp6002), loop redesigned
  T  : both scope Vmid buffers in one TLV9062 (TI model), loop redesigned (the cheaper fast dual)
  DM, DT: the combinations.  H: the design as simulated, with the per-channel supply branch added for comparison.

Run:  python3 -I lowcost.py [section ...]   sections: base xt kick step ac noise flat dc pw7 guards
Results in results/*.json; netlists in netlists/, data in work/ (all under this directory)."""
import os, sys, re, json, time, math
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import numpy as np
import netlib as NL
NL.use_variant("hz")
import run as R
R.set_res(os.path.join(HERE, "results"))
import lowz as L

NL.OPAMPS["OPA2354"] = dict(lib="../../../models/opa354/OPA2354_PSPICE.LIB", sub="OPA2354", vos_max=8e-3, en=6.5e-9, gbw=100e6)
MCP_LIB = "../../../models-open/mcp6002/mcp6002_open.lib"
TLV_LIB = "../../../models/tlv9062/tlv9062.lib"
os.makedirs(NL.NETD, exist_ok=True)
with open(os.path.join(NL.NETD, ".spiceinit"), "w") as f:     # the TI TLV9062 (GWL) model needs PSpice compatibility
    f.write("set ngbehavior=ps\n")

LSB32 = 3.2 / 4096
# OPA2354 channel-to-channel crosstalk, input-referred, SBOS233H Fig. 6-28 (red trace), read from a 200 dpi render
# (about +/-2 dB *(check)*); table: -100 dB typ at 5 MHz.  Below 100 kHz the figure has no data: held at its 100 kHz value.
XT_FIG = [(1e5, -103), (2e5, -104), (3e5, -105.5), (1e6, -105.5), (2e6, -105), (3e6, -106.5), (5e6, -104), (7e6, -101),
          (1e7, -95), (2e7, -91), (3e7, -86), (5e7, -76), (1e8, -63), (2e8, -50), (3e8, -47), (5e8, -47), (1e9, -32)]
# SPICE envelope used inside the netlists (so transients carry it too): k0 flat + kd x d/dt.  k0 = -100 dB (the table's
# typical, 5 dB above the figure's floor), kd = 2.5 ps puts the derivative term on or above the figure from 1 MHz to
# 500 MHz (-96 dB at 1 MHz, -76 at 10 MHz, -56 at 100 MHz, -47 at 300 MHz).  xt_scale multiplies both (corner: x3, +10 dB).
XT_K0, XT_KD = 1e-5, 2.5e-12
def xt_env_db(f, scale=1.0):
    return 20 * np.log10(scale * np.abs(XT_K0 + 1j * 2 * np.pi * f * XT_KD))
def xt_fig_db(f):
    return np.interp(np.log10(f), np.log10([x[0] for x in XT_FIG]), [x[1] for x in XT_FIG])

# Vmid loops (vmid/robust.py chose them; see vmid/*.json)
VLOOP = {
    "mcp": dict(riso=3.0, rfb=4.7e3, cfb=1e-6, n10=8),     # 3 x 1R in series, 4.7k, 1 uF (C15849), 8 x 10 uF + 100 nF
    "mcpB": dict(riso=4.0, rfb=4.7e3, cfb=1e-6, n10=4),    # the leaner one: 4 x 1R in series, 4 x 10 uF
    "tlv": dict(riso=0.25, rfb=4.7e3, cfb=1e-6, n10=6),    # 4 x 1R in parallel, 4.7k, 1 uF, 6 x 10 uF + 100 nF
}
MCP_PAR = dict(ro=1000, fp2=3e6, gbw=0.7e6, a0db=112)     # the stress corner of the unknowns (vmid/robust.py)
# TLV9062 stand-in: gbw/ro/fp2 fitted (vmid/fit_tlv.json); PSRR 7 uV/V typ = 103 dB (SBOS839N table), its corner 1 kHz
# *(assumption: Fig. 6-11 not digitised)*; IQ 538 uA typ
TLV_PAR = dict(gbw=15e6, ro=150, fp2=40e6, a0db=120, psrrdb=103, fps=1e3, iq=538e-6)

_core0 = NL.core
def core2(p, pre="", loopbreak=False):
    s = _core0(p, pre, loopbreak)
    lines = s.split("\n")
    # ---- Vmid buffer: replace the P8-k stand-in by a model of a real part
    vb = p.get("vbuf")
    if vb and p.get("vmid_perch"):
        i = next(j for j, l in enumerate(lines) if l.startswith("* per-channel Vmid buffer"))
        lines = lines[:i]
        lp = dict(VLOOP[p.get("vloop", "mcp" if vb == "mcp" else "tlv")]); lp.update(p.get("vloop_over", {}))
        vmc = f"{pre}vmc"
        vsup = p.get("vb_sup", "dual")
        vbs = f"{pre}vbs" if vsup == "sep" else "vbs"
        if vb == "mcp":
            mp = dict(MCP_PAR); mp.update(p.get("mcp_par", {}))
            amp = f"XVB{pre} {pre}vbi {pre}vfb {vbs} 0 {pre}vbo MCP6002_OPEN params: " + " ".join(f"{k}={v:.6g}" for k, v in mp.items())
        else:   # TLV9062: the behavioural subcircuit fitted to the TI model's loop impedance (vmid/fit_tlv.py: within 0.6 %,
                # 1 Hz-1 MHz, for this loop); the TI model itself does not reach an operating point beside the OPA354 model
            amp = f"XVB{pre} {pre}vbi {pre}vfb {vbs} 0 {pre}vbo MCP6002_OPEN params: " + " ".join(f"{k}={v:.6g}" for k, v in TLV_PAR.items())
        n = lp["n10"]; cf = p.get("c10_factor", 1.0)
        lines += [f"* per-channel Vmid buffer {pre or 'A'}: {vb} half, loop {lp}",
                  f"Vvbos{pre} vm {pre}vbi dc {p.get('vos_vb' + pre, 0.0):.6g} {'ac 1' if p.get('ac_vbos') == pre else ''}",
                  amp, f"Rvmi{pre} {pre}vbo {vmc} {lp['riso']:.6g}", f"Rvfb{pre} {vmc} {pre}vfb {lp['rfb']:.6g}",
                  f"Cvfb{pre} {pre}vbo {pre}vfb {lp['cfb']:.6g}",
                  f"Cvd1{pre} {vmc} {pre}vc1 {n * 10e-6 * cf:.6g}", f"Rve1{pre} {pre}vc1 0 {p.get('esr10', 0.005) / n:.6g}",
                  f"Cvd2{pre} {vmc} {pre}vc2 100n", f"Rve2{pre} {pre}vc2 0 30m"]
        if vsup == "sep" or pre in ("", "a"):
            q = pre if vsup == "sep" else ""
            lines += [f"* Vmid buffer package supply {q or '(shared)'}: 50 mohm + 5 nH from the rail, 100 nF at the pin *(layout assumption)*",
                      f"Rvbt{q} vccl {q}vbt 0.05", f"Lvb{q} {q}vbt {vbs} 5n", f"Cvbs{q} {vbs} {q}vbse 100n", f"Rvbse{q} {q}vbse 0 20m"]
    # ---- scope op-amp supply: 'sep' one 1R + 10 uF branch and a 100 nF at each package's pin (the BOM), 'dual' one of each
    sup = p.get("scope_sup")
    if sup:
        pin = f"{pre}sp" if sup == "sep" else "spd"
        lines = [re.sub(r"^(XU\S* \S+ \S+) vccl 0 ", rf"\1 {pin} 0 ", l) for l in lines]
        if sup == "sep" or pre in ("", "a"):
            q = pre if sup == "sep" else "d"
            lines += [f"* scope op-amp supply branch {q}: 1R + 10 uF, 2 nH to the pin's 100 nF *(layout assumption)*",
                      f"Rsb{q} vccl {q}sbr 1", f"Csb{q} {q}sbr {q}sbe 10u", f"Rsbe{q} {q}sbe 0 2.5m",
                      f"Lsp{q} {q}sbr {pin} 2n", f"Csp{q} {pin} {q}spe 100n", f"Rspe{q} {q}spe 0 20m"]
    # ---- the dual's internal crosstalk: victim + input gets k0 x V(aggressor out) + kd x dV/dt
    if p.get("dual_xt") and pre in ("a", "b"):
        agg = "b" if pre == "a" else "a"
        k = p.get("xt_scale", 1.0)
        lines = [re.sub(rf"^(XU{pre} ){pre}np ", rf"\g<1>{pre}npx ", l) for l in lines]
        lines += [f"* OPA2354 internal crosstalk from channel {agg} (SBOS233H Fig. 6-28 envelope x {k})",
                  f"Ext{pre} {pre}npx {pre}npy {agg}out 0 {XT_K0 * k:.6g}",
                  f"Exc{pre} {pre}xc 0 {agg}out 0 1", f"Cxd{pre} {pre}xc {pre}xd {XT_KD * k:.6g}", f"Vxd{pre} {pre}xd 0 0",
                  f"Hxt{pre} {pre}npy {pre}np Vxd{pre} 1"]
    return "\n".join(lines)

_header0 = NL.header
def header2(p, title):
    t = _header0(p, title)
    if p.get("vbuf") in ("mcp", "tlv"):
        t += f".include {MCP_LIB}\n"
    return t

_run0 = NL.run_ng
def run_ng2(name, text, timeout=600):
    """As netlib.run_ng, but every data file of this netlist is removed first, so a failed run cannot be read as the
    previous one's result."""
    pre = NL.PFX + name + "_"
    for fn in os.listdir(NL.WORK) if os.path.isdir(NL.WORK) else []:
        if fn.startswith(pre) and fn.endswith(".dat"):
            os.remove(os.path.join(NL.WORK, fn))
    return _run0(name, text, timeout)
for m in (NL, R, L):
    m.run_ng = run_ng2

for m in (NL, R, L):
    m.core = core2
    m.header = header2

# ------------------------------------------------------------------------------------------------ variants
BASE = dict(L.P("H"))
VAR = {
    "H": dict(scope_sup="sep"),
    "D": dict(op="OPA2354", scope_sup="dual", dual_xt=True),
    "M": dict(scope_sup="sep", vbuf="mcp", vb_sup="dual"),
    "T": dict(scope_sup="sep", vbuf="tlv", vb_sup="dual"),
    "DM": dict(op="OPA2354", scope_sup="dual", dual_xt=True, vbuf="mcp", vb_sup="dual"),
    "DT": dict(op="OPA2354", scope_sup="dual", dual_xt=True, vbuf="tlv", vb_sup="dual"),
}
def P(v, **kw):
    q = dict(BASE); q.update(VAR[v]); q.update(kw); return q

def save(name, obj):
    return R.save(name, obj)
def loadj(name):
    return R.loadj(name)

# ------------------------------------------------------------------------------------------------ SC-9, AC
def adc_track(f, adc):
    """What the S/H keeps of a sine at the pin: the tracking RC (run.py's derived 3.8 kohm / 6 pF, stress 1 kohm / 8 pF)."""
    return 1 / np.abs(1 + 2j * np.pi * f * adc["ron"] * adc["cs"])

def ac_xt(pa, pb, drive="a", name="xt", fmin=1.0, fmax=200e6, ppd=20):
    """|V(victim pin)| per volt at the aggressor's input; the victim's input is shorted (0 V)."""
    va, vb = ("ac 1", "") if drive == "a" else ("", "ac 1")
    txt = NL.header(pa, name) + NL.rails(pa) + f"Vina ain 0 dc 0 {va}\nVinb bin 0 dc 0 {vb}\n" + core2(pa, "a") + "\n" + core2(pb, "b") + f"""
.control
ac dec {ppd} {fmin} {fmax}
wrdata {NL.wr(name,'x')} v(apin) v(bpin) v(aout) v(bout) v(avmc) v(bvmc)
.endc
.end
"""
    NL.run_ng(name, txt)
    d = NL.load(name, "x"); f = d[:, 0]
    c = lambda i: d[:, 1 + 3 * i] + 1j * d[:, 2 + 3 * i]
    vic = c(1) if drive == "a" else c(0)
    return f, dict(victim_pin=np.abs(vic), agg_pin=np.abs(c(0) if drive == "a" else c(1)), agg_out=np.abs(c(2) if drive == "a" else c(3)),
                   victim_vmc=np.abs(c(5) if drive == "a" else c(4)), agg_vmc=np.abs(c(4) if drive == "a" else c(5)))

def ng_victim(p, name="ngv"):
    """Victim's pin per volt in series with its + input (the noise gain), single channel: for the figure cross-check."""
    q = dict(p, dual_xt=False)
    txt = NL.header(q, name) + NL.rails(q) + "Vs in 0 dc 0\n" + core2(q).replace(f"Vos n nv dc {q['vos']:.6g}", f"Vos n nv dc {q['vos']:.6g} ac 1") + f"""
.control
ac dec 20 1 200meg
wrdata {NL.wr(name,'g')} v(pin)
.endc
.end
"""
    NL.run_ng(name, txt)
    d = NL.load(name, "g")
    return d[:, 0], np.abs(d[:, 1] + 1j * d[:, 2])

def sec_xt(variants=("H", "D", "M", "DM", "T", "DT")):
    out = {}
    for v in variants:
        for rng, vfs in (("5", 6.0), ("1.25", 1.25)):
            for asym in ((0.0, 0.0), (3e-12, 0.0), (0.0, 3e-12)):
                for scale in ((1.0, 3.0) if VAR[v].get("dual_xt") else (1.0,)):
                    pa = P(v, rng=rng, Cpar_extra=asym[0], xt_scale=scale); pb = P(v, rng=rng, Cpar_extra=asym[1], xt_scale=scale)
                    for drive in ("a", "b"):
                        f, r = ac_xt(pa, pb, drive, "xt")
                        x = r["victim_pin"] * vfs / LSB32
                        key = f"{v}|{rng}|asym{asym[0]*1e12:.0f}/{asym[1]*1e12:.0f}pF|xt{scale:g}|{drive}->{'b' if drive == 'a' else 'a'}"
                        xd = x * adc_track(f, R.ADC_DERIVED); xs = x * adc_track(f, R.ADC_STRESS)
                        out[key] = dict(max_lsb=float(x.max()), f_at_max=float(f[np.argmax(x)]), dc_lsb=float(x[0]),
                                        adc_derived_max_lsb=float(xd.max()), adc_derived_f=float(f[np.argmax(xd)]),
                                        adc_stress_max_lsb=float(xs.max()), adc_stress_f=float(f[np.argmax(xs)]),
                                        at={f"{fx:.0e}": float(np.interp(np.log10(fx), np.log10(f), x)) for fx in (1, 1e2, 1e3, 1e4, 1e5, 1e6, 1e7, 3e7, 1e8)},
                                        victim_vmc_max_uV=float(r["victim_vmc"].max() * vfs * 1e6), agg_vmc_max_mV=float(r["agg_vmc"].max() * vfs * 1e3))
        print("xt", v, flush=True)
    # cross-check of the dual's internal term against the figure itself (post-processed, not the SPICE envelope)
    cc = {}
    for rng, vfs in (("5", 6.0), ("1.25", 1.25)):
        p = P("D", rng=rng)
        f, r = ac_xt(dict(p, dual_xt=False), dict(p, dual_xt=False), "a", "xtc")
        fg, ng = ng_victim(P("D", rng=rng))
        ngi = np.interp(f, fg, ng)
        fig = 10 ** (xt_fig_db(f) / 20) * r["agg_out"] * ngi * vfs / LSB32
        env = 10 ** (xt_env_db(f) / 20) * r["agg_out"] * ngi * vfs / LSB32
        oth = r["victim_pin"] * vfs / LSB32
        tot = fig + oth
        cc[rng] = dict(fig_plus_other_max_lsb=float(tot.max()), fig_plus_other_f=float(f[np.argmax(tot)]),
                       fig_plus_other_adc_derived=float((tot * adc_track(f, R.ADC_DERIVED)).max()),
                       fig_plus_other_adc_stress=float((tot * adc_track(f, R.ADC_STRESS)).max()),
                       other_f=float(f[np.argmax(oth)]), f_2lsb_fig=float(f[np.argmax(tot > 2)]) if (tot > 2).any() else None,
                       f_2lsb_fig_hi=float(f[len(tot) - 1 - np.argmax(tot[::-1] > 2)]) if (tot > 2).any() else None,
                       fig_max_lsb=float(fig.max()), fig_f=float(f[np.argmax(fig)]), env_max_lsb=float(env.max()), env_f=float(f[np.argmax(env)]),
                       other_paths_max_lsb=float((r["victim_pin"] * vfs / LSB32).max()), ng_max=float(ng.max()), agg_out_1MHz=float(np.interp(1e6, f, r["agg_out"])))
    out["figure_crosscheck"] = cc
    return save("xt", out)

# ------------------------------------------------------------------------------------------------ SC-9, DC/S&H (kick) and steps
def sec_kick(variants=("H", "D", "M", "DM")):
    out = {}
    for v in variants:
        for rng, vfs in (("5", 6.0), ("1.25", 1.25)):
            p = P(v, rng=rng)
            hi = R.kick_run(p, +vfs, 0.0, R.ADC_DERIVED, aref=3.2); lo = R.kick_run(p, -vfs, 0.0, R.ADC_DERIVED, aref=3.2)
            hib = R.kick_run(p, 0.0, +vfs, R.ADC_DERIVED, aref=3.2); lob = R.kick_run(p, 0.0, -vfs, R.ADC_DERIVED, aref=3.2)
            ab = abs((hi["vpin_b"] + hi["errB_lsb"] * LSB32) - (lo["vpin_b"] + lo["errB_lsb"] * LSB32)) / LSB32
            ba = abs((hib["vpin_a"] + hib["errA_lsb"] * LSB32) - (lob["vpin_a"] + lob["errA_lsb"] * LSB32)) / LSB32
            out[f"{v}|{rng}"] = dict(a_to_b_lsb=ab, b_to_a_lsb=ba)
        print("kick", v, out[f"{v}|5"], out[f"{v}|1.25"], flush=True)
    return save("kick", out)

def step_xt(p, vfs, tr, tstop, tstep, name="stx", tmax=None):
    """A steps -vfs -> +vfs (edge tr) at 1 us, B's input shorted: B's pin against its value before the step."""
    t0 = 1e-6
    txt = NL.header(p, name) + NL.rails(p) + f"Vina ain 0 dc {-vfs} pulse({-vfs} {vfs} {t0} {tr} {tr} 1 2)\nVinb bin 0 dc 0\n" + \
        core2(p, "a") + "\n" + core2(p, "b") + f"""
.control
tran {tstep} {tstop} 0 {tmax or tstep}
wrdata {NL.wr(name,'s')} v(bpin) v(apin)
.endc
.end
"""
    NL.run_ng(name, txt, timeout=3000)
    d = NL.load(name, "s"); t = d[:, 0]; vb = d[:, 1]
    b0 = float(np.mean(vb[(t > 0.5e-6) & (t < 0.95e-6)]))
    dv = (vb - b0) / LSB32
    after = t > t0
    i = int(np.argmax(np.abs(dv[after])))
    end = float(np.mean(dv[t > 0.9 * tstop]))
    return dict(peak_lsb=float(dv[after][i]), t_peak_us=float((t[after][i] - t0) * 1e6), final_lsb=end)

def sec_step(variants=("H", "D", "M", "DM")):
    out = {}
    for v in variants:
        for rng, vfs in (("5", 6.0), ("1.25", 1.25)):
            p = P(v, rng=rng)
            fast = step_xt(p, vfs, 5e-9, 4e-6, 0.1e-9)
            slow = step_xt(p, vfs, 100e-9, 3e-3, 10e-9, tmax=50e-9)   # ms scale (Vmid loops, the sense filter); the edge is the fast run's
            out[f"{v}|{rng}"] = dict(fast=fast, slow=slow)
            print("step", v, rng, out[f"{v}|{rng}"], flush=True)
    return save("step", out)

# ------------------------------------------------------------------------------------------------ SM-3, AN-1 for the dual
def sec_ac(variants=("H", "D")):
    out = {}
    for v in variants:
        for rng in ("5", "1.25"):
            rows = []
            for kw in L.corners("H"):
                r = R.ac_summary(P(v, rng=rng, **kw), "acc"); rows.append(dict(kw, bw=r["bw"], pm=r["pm"], peak_db=r["peak_db"]))
            # the dual's asymmetric strays: extra inverting-node capacitance on one channel, and pin 1-2 / 6-7 capacitance
            asym = []
            for cx in (5e-12, 8e-12):
                for cf in (0.0, 0.3e-12):
                    for ron in (3.7, R.RON_MAX):
                        r = R.ac_summary(P(v, rng=rng, Cpar_extra=cx, Cf=cf, Ron_sw=ron), "aca")
                        asym.append(dict(Cpar_extra=cx, Cf=cf, Ron_sw=ron, bw=r["bw"], pm=r["pm"], peak_db=r["peak_db"]))
            nom = R.ac_summary(P(v, rng=rng), "acn")
            out[f"{v}|{rng}"] = dict(nominal=nom, worst_bw=min(x["bw"] for x in rows), worst_pm=min(x["pm"] for x in rows),
                                     asym_worst_bw=min(x["bw"] for x in asym), asym_worst_pm=min(x["pm"] for x in asym),
                                     asym_worst_peak_db=max(x["peak_db"] for x in asym), asym=asym)
            print("ac", v, rng, {k: out[f"{v}|{rng}"][k] for k in ("worst_bw", "worst_pm", "asym_worst_bw", "asym_worst_pm")}, flush=True)
    return save("ac", out)

# ------------------------------------------------------------------------------------------------ SC-6
def en_mcp(f):
    return 28e-9 * np.sqrt(1 + 130.0 / f)       # Fig. 2-12 fit (lib header)
def en_tlv(f):
    return 10e-9 * np.sqrt(1 + 1560.0 / f)       # SBOS839N table: 16 nV at 1 kHz, 10 nV at 10 kHz -> 1/f corner 1.56 kHz
def vm_transfer(p, name="nvm"):
    q = dict(p, Rvo=p["Rvo"])
    txt = NL.header(q, name) + NL.rails(q, ac_vm=True) + "Vs src 0 dc 0 ac 0\nRs src in 50\n" + core2(q) + f"""
.control
ac dec 20 0.1 100meg
wrdata {NL.wr(name,'x')} v(pin)
.endc
.end
"""
    NL.run_ng(name, txt)
    d = NL.load(name, "x"); return d[:, 0], np.abs(d[:, 1] + 1j * d[:, 2])

def sec_noise(variants=("H", "D")):
    """Scope op-amp noise for the dual (the vendor model's own .noise, as sim/scope does), and the Vmid buffer's
    datasheet density through its simulated transfer to the pin for M / T."""
    out = {}
    base_ac = {}
    for v in variants:
        for rng in ("5", "1.25"):
            p = P(v, rng=rng)
            bw = R.ac_summary(p, "nbw")["bw"]; fm = 1.5 * bw
            a = NL.noise_total(p, "nz", fm, "all")
            vm = R.transfer_rms(p, "nzx", "vm", R.EN_VMID, fm); v3 = R.transfer_rms(p, "nzx", "v3", R.EN_V3, fm)
            out[f"{v}|{rng}"] = dict(bw=bw, fmax=fm, total_V=float(np.sqrt(a * a + vm * vm + v3 * v3)), opamp_and_res_V=a, vmid_V=vm, v3_V=v3)
            base_ac[f"{v}|{rng}"] = bw
            print("noise", v, rng, out[f"{v}|{rng}"], flush=True)
    for vb, enf in (("M", en_mcp), ("T", en_tlv)):
        for rng in ("5", "1.25"):
            f, h = vm_transfer(P(vb, rng=rng))
            fm = 1.5 * base_ac.get(f"H|{rng}", 1e8)
            m = (f <= fm) & (f >= 0.1)
            vmid = float(np.sqrt(np.trapezoid((enf(f[m]) * h[m]) ** 2, f[m])))
            out[f"{vb}|{rng}|vmid_buffer"] = dict(vmid_at_pin_V=vmid, h_max=float(h.max()), f_hmax=float(f[np.argmax(h)]), fmax=fm,
                                                 total_with_H_V=float(np.sqrt(out[f"H|{rng}"]["total_V"] ** 2 - out[f"H|{rng}"]["vmid_V"] ** 2 + vmid ** 2)) if f"H|{rng}" in out else None)
            print("noise", vb, rng, out[f"{vb}|{rng}|vmid_buffer"], flush=True)
    return save("noise", out)

# ------------------------------------------------------------------------------------------------ SC-5 / SC-4 / SC-11: own-channel flatness
def gain_curve(p, name="fl"):
    txt = NL.header(p, name) + NL.rails(p) + "Vs src 0 dc 0 ac 1\nRs src in 50\n" + core2(p) + f"""
.control
ac dec 40 0.1 20meg
wrdata {NL.wr(name,'h')} v(pin) v(vmc)
.endc
.end
"""
    NL.run_ng(name, txt)
    d = NL.load(name, "h"); f = d[:, 0]
    return f, np.abs(d[:, 1] + 1j * d[:, 2]), np.abs(d[:, 4] + 1j * d[:, 5])

def sec_flat(variants=("H", "M", "T", "DM")):
    """Own-channel response from 0.1 Hz to 20 MHz.  The Vmid buffer's share is the ratio to the H design's curve (same
    divider, same amplifier), so the divider's compensation step and the range's own roll-off cancel."""
    out = {}
    ref = {}
    for rng in ("5", "1.25"):
        f, h, hv = gain_curve(P("H", rng=rng), "flr"); ref[rng] = (f, h)
    for v in variants:
        cs = [dict()]
        if VAR[v].get("vbuf") == "mcp":
            cs = [dict(mcp_par=dict(ro=ro, fp2=f2, gbw=g)) for ro in (50, 300, 1000, 2000) for f2, g in ((6e6, 1e6), (3e6, 0.7e6))]
        cs = [dict(c, c10_factor=k, esr10=e) for c in cs for k in (0.8208, 1.0) for e in (0.005, 0.0721)]
        for rng in ("5", "1.25"):
            rows = []
            fr, hr = ref[rng]
            for c in cs:
                for loop in ((("mcp", "mcpB") if VAR[v].get("vbuf") == "mcp" else (None,))):
                    q = P(v, rng=rng, **c)
                    if loop:
                        q["vloop"] = loop
                    f, h, hv = gain_curve(q)
                    rel = (h / np.interp(f, fr, hr) - 1) * 100
                    m = f <= 20e6
                    i = int(np.argmax(np.abs(rel[m])))
                    rows.append(dict(c, loop=loop, g_dc=float(h[0]), rel_max_pct=float(rel[m][i]), f_rel=float(f[m][i]),
                                     rel_dc_pct=float(rel[0]), rel_10=float(np.interp(10, f, rel)), rel_100=float(np.interp(100, f, rel)),
                                     rel_1k=float(np.interp(1e3, f, rel)), rel_40k=float(np.interp(4e4, f, rel)), rel_1M=float(np.interp(1e6, f, rel)),
                                     vmc_per_vin_max=float(hv[m].max()), f_vmc=float(f[m][np.argmax(hv[m])])))
            out[f"{v}|{rng}"] = rows
            for loop in sorted(set(str(r["loop"]) for r in rows)):
                rr = [r for r in rows if str(r["loop"]) == loop]
                w = max(rr, key=lambda r: abs(r["rel_max_pct"]))
                print("flat", v, rng, loop, {k: w[k] for k in ("rel_max_pct", "f_rel", "rel_dc_pct", "rel_40k", "vmc_per_vin_max")}, flush=True)
    return save("flat", out)

# ------------------------------------------------------------------------------------------------ SC-2 centring (P8-c method) and SC-8 offsets
def sec_dc():
    """P8-c's Monte Carlo (sim/powercal an4_mc) re-implemented here, with the Vmid buffer's offset as a parameter;
    and the corner sum.  Also SM: the SC-2 margin through run.py's DC section with the buffer offset as a Vmid shift."""
    rng = np.random.default_rng(20261111)
    R1, R2, R3, RF, RG = 760e3, 330e3, 760e3, 953.0, 249.0
    RSF = 249.0
    out = {}
    for lab, vos in (("OPA365 0.2 mV (design)", 0.2e-3), ("TLV9062 1.6 mV", 1.6e-3), ("MCP6002 4.5 mV", 4.5e-3), ("MCP6002 pre-2004 7 mV", 7e-3)):
        e = []; N = 200000
        u = lambda t: rng.uniform(-t, t, N)
        for v33 in (3.10, 3.20, 3.25, 3.30):
            rt = 330e3 * (1 + u(0.001)); rb = 330e3 * (1 + u(0.001))
            vmid = v33 * rb / (rt + rb) + u(vos) + u(10e-12 * 165e3)
            r1 = R1 * (1 + u(0.001)); r2 = R2 * (1 + u(0.001)); r3 = R3 * (1 + u(0.001)); g = 1 + RF * (1 + u(0.001)) / (RG * (1 + u(0.001)))
            i_s = (v33 - 1.65) / R3 + rng.uniform(0, v33 / R3, N)
            vs = v33 - i_s * RSF
            n0 = (vmid / r2 + vs / r3) / (1 / r1 + 1 / r2 + 1 / r3)
            aref = v33 - 5e-3
            for pin in (n0, g * n0 - (g - 1) * vmid):
                e.append(np.abs(pin - aref / 2))
        cv = (1 / R2) / (1 / R1 + 1 / R2 + 1 / R3); G = 1 + RF / RG
        out[lab] = dict(mc_worst_mV=float(np.max(e) * 1e3), vos_coef_5=cv, vos_coef_125=abs(G * cv - (G - 1)),
                        vos_at_pin_mV_5=cv * vos * 1e3, vos_at_pin_mV_125=abs(G * cv - (G - 1)) * vos * 1e3,
                        # SC-8 offset between channels (two halves at opposite extremes), at the pin and referred to the input
                        match_pin_mV_5=2 * cv * vos * 1e3, match_pin_mV_125=2 * abs(G * cv - (G - 1)) * vos * 1e3)
    alpha = (1 / R1) / (1 / R1 + 1 / R2 + 1 / R3)
    for lab in out:
        o = out[lab]
        o["match_in_mV_5"] = o["match_pin_mV_5"] / alpha
        o["match_in_mV_125"] = o["match_pin_mV_125"] / (alpha * (1 + RF / RG))
    # for scale: the scope op-amp's own offset (OPA354/OPA2354, 8 mV max) between two channels at opposite extremes
    out["scope op-amp 8 mV (OPA354 / OPA2354), for scale"] = dict(match_pin_mV_5=16.0, match_in_mV_5=16.0 / alpha,
                                                                    match_pin_mV_125=16.0 * (1 + RF / RG), match_in_mV_125=16.0 / alpha)
    # SC-2 margin: run.py's DC worst case (one-at-a-time sum) with the Vmid buffer's offset as one more term, a shift of
    # the channel's Vmid alone (the +/-30 mV centring term stays as it is)
    sc2 = {}
    oat0 = R.oat_perturbations
    for lab, vos in (("design (OPA365 offset inside the 30 mV)", 0.0), ("MCP6002 4.5 mV", 4.5e-3), ("TLV9062 1.6 mV", 1.6e-3)):
        def oat(base, aref, vos=vos):
            o = oat0(base, aref)
            if vos:
                for sgn in (+1, -1):
                    q = dict(base); q["vmid"] = aref / 2 + sgn * vos; o.append((f"vbos{'+' if sgn > 0 else '-'}", q))
            return o
        R.oat_perturbations = oat
        try:
            d = R.dc_section("OPA354", quick=True, over=dict(), tag=f"dc_{'mcp' if vos > 4e-3 else ('tlv' if vos else 'design')}")
        finally:
            R.oat_perturbations = oat0
        sc2[lab] = {rg: dict(margin_wc_V=d["aref_table"][rg]["3.20"]["margin_wc"], gain_min=d["aref_table"][rg]["3.20"]["gain_min"],
                             gain_max=d["aref_table"][rg]["3.20"]["gain_max"]) for rg in ("5", "1.25")}
    out["sc2_margin_V"] = sc2
    print(json.dumps(out, indent=1, default=float))
    return save("dc", out)

# ------------------------------------------------------------------------------------------------ PW-7 start-up
def sec_pw7():
    """Power-on: the AFE rail ramps 0 -> 3.3 V in 1 ms, the Due's 3.3 V pin is up; the Vmid divider tap (2 x 330k, 10 uF)
    charges from 0 V.  Two Vmid buffers in one package (MCP6002 open model / TLV9062 / the OPA365 stand-in) drive their
    loops; time for each channel's Vmid node, and the ADC pin at 0 V in, to stay inside 0.5 LSB (AREF 3.3) of final."""
    out = {}
    for v in ("H", "M", "T"):
        p = P(v, rng="1.25")
        q = dict(p)
        txt = NL.header(q, "pw7") + f"""* PW-7 start-up
Vcc vcc0 0 dc 0 pwl(0 0 1m 3.3)
Rvc vcc0 vccl 0.1
Cdc1 vccl 0 1u
V33 v33 0 dc 3.3
Rt v33 tap 330k
Rb tap 0 330k
Ct tap 0 10u ic=0
Etap vm 0 tap 0 1
Rv3 v33 v3p 0.1
Rs3sh v3p v3 249
Cs3sh v3 0 10u
Vina ain 0 dc 0
Vinb bin 0 dc 0
""" + core2(q, "a") + "\n" + core2(q, "b") + f"""
.control
tran 1m 20 0 1m uic
wrdata {NL.wr('pw7','v')} v(avmc) v(bvmc) v(apin) v(tap)
.endc
.end
"""
        NL.run_ng("pw7", txt, timeout=3000)
        d = NL.load("pw7", "v"); t = d[:, 0]
        lsbh = 0.5 * 3.3 / 4096
        row = {}
        for j, nm in ((1, "avmc"), (3, "bvmc"), (5, "apin"), (7, "tap")):
            x = d[:, j]; fin = x[-1]
            bad = np.where(np.abs(x - fin) > lsbh)[0]
            row[nm] = dict(final_V=float(fin), t_settle_s=float(t[bad[-1]]) if len(bad) else 0.0)
        out[v] = row
        print("pw7", v, row, flush=True)
    return save("pw7", out)

# ------------------------------------------------------------------------------------------------ guards (break each new check once)
def sec_guards():
    G = []
    def run_(name, fn, good, broken, what):
        ok1, d1 = fn(good); ok2, d2 = fn(broken); ok3, d3 = fn(good)
        G.append(dict(guard=name, mutation=what, good=dict(ok=ok1, d=d1), broken=dict(ok=ok2, d=d2), restored=dict(ok=ok3, d=d3),
                      effective=bool(ok1 and not ok2 and ok3)))
        print(G[-1], flush=True)
    def xt_guard(p):   # the reading: the victim's pin through the S/H's derived tracking RC
        f, r = ac_xt(p, p, "a", "gx"); m = float((r["victim_pin"] * 6.0 / LSB32 * adc_track(f, R.ADC_DERIVED)).max()); return m <= 2.0, f"{m:.3f} LSB"
    # the dual's internal crosstalk term must be able to fail SC-9: scale the envelope x 1e4 (+80 dB)
    run_("SC-9 picks up the dual's internal term", xt_guard, P("D", rng="5"), P("D", rng="5", xt_scale=1e4), "crosstalk envelope x 1e4")
    # the shared supply pin must be able to fail SC-9: put 30 ohm in the shared branch instead of 1 ohm (and no 10 uF)
    def sup_guard(p):
        f, r = ac_xt(p, p, "a", "gs"); m = float((r["victim_pin"] * 6.0 / LSB32 * adc_track(f, R.ADC_DERIVED)).max()); return m <= 2.0, f"{m:.3f} LSB"
    bad = P("D", rng="5", dual_xt=False)
    run_("SC-9 sees the shared supply pin", sup_guard, P("D", rng="5", dual_xt=False), dict(bad, _bigsup=True), "shared supply branch 1R -> 10 ohm, its 10 uF and the pin's 100 nF removed")
    # Vmid: one MCP6002 package: the halves joined must fail SC-9
    run_("SC-9 sees a shared Vmid node", xt_guard, P("M", rng="5"), P("M", rng="5", _joinvm=True), "the two Vmid nodes joined (one buffer)")
    # flatness guard: MCP with the OPA365 loop (unstable) must show a large deviation
    fr, hr, _ = gain_curve(P("H", rng="5"), "gfr")
    def flat_guard(p):   # the Vmid buffer's share: the ratio to the H design's curve (as sec_flat)
        f, h, hv = gain_curve(p, "gf"); dev = float(np.max(np.abs(h[f <= 20e6] / np.interp(f[f <= 20e6], fr, hr) - 1)) * 100); return dev <= 1.0, f"{dev:.2f} %"
    run_("own-channel flatness <= 1 % sees the Vmid loop", flat_guard, P("M", rng="5"), P("M", rng="5", vloop_over=dict(riso=0.2, cfb=3e-9, n10=2)),
         "the OPA365 loop (0.2R, 3 nF, 2 x 10 uF) on the MCP6002")
    return save("guards", G)

# hooks used only by the guards
_core_g = core2
def core3(p, pre="", loopbreak=False):
    s = _core_g(p, pre, loopbreak)
    if p.get("_bigsup"):
        s = s.replace("Rsbd vccl dsbr 1\n", "Rsbd vccl dsbr 10\n").replace("Csbd dsbr dsbe 10u", "Csbd dsbr dsbe 1p").replace("Cspd spd dspe 100n", "Cspd spd dspe 1p")
        assert pre not in ("", "a") or ("Rsbd vccl dsbr 10\n" in s and "Cspd spd dspe 1p" in s)
    if p.get("_joinvm") and pre == "b":
        s += "\nRjoin avmc bvmc 1m"
    return s
for m in (NL, R, L):
    m.core = core3
core2 = core3

SECS = dict(xt=sec_xt, kick=sec_kick, step=sec_step, ac=sec_ac, noise=sec_noise, flat=sec_flat, dc=sec_dc, pw7=sec_pw7, guards=sec_guards)

if __name__ == "__main__":
    want = sys.argv[1:] or list(SECS)
    for s in want:
        t0 = time.time()
        NL.PFX = s + "_"
        SECS[s]()
        print(s, "done", round(time.time() - t0), "s", flush=True)
