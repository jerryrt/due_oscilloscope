#!/usr/bin/env python3
"""whatif/sw3157: the range-switch rows of sim/scope (variant hz, the default) re-run with a 3157-class switch.
Run:  python3 -I sw.py <section> [candidate ...]      sections: dc inl ac noise kick prot report
Candidates are keyed below.  Results: results/<section>_<cand>.json.  Netlists in netlists/, data in work/.
The switch model is models-open/sw3157/sw3157.lib (our own, CC BY-SA 4.0): Ron(V) from digitised datasheet curves.
DC, INL, transients and protection use the Ron(V) model; AC and noise use a linear Ron at the corner values (the
small-signal resistance of the Ron(V) model at the bias point is exactly that, and a B-source has no thermal noise)."""
import sys, os, json, re, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import numpy as np
import netlib as NL
NL.use_variant("hz")
import run as R
R.set_res(os.path.join(HERE, "results"))
import lowz as L
from netlib import header, rails, core, run_ng, wr, load, noise_total

CURVES = json.load(open(os.path.join(HERE, "..", "..", "..", "..", "models-open", "sw3157", "curves.json")))
SV = np.array(CURVES["V"])

def ron_at(sw, vc):
    s = np.interp(vc, SV, CURVES["sNX"] if sw["shape"] == "NX" else CURVES["sTM"])
    return sw["rpk"] - sw["flat"] + sw["flat"] * s

def ron_range(sw, lo=0.2, hi=3.1):
    v = np.linspace(lo, hi, 300); r = ron_at(sw, v)
    return float(r.min()), float(r.max())

# ---------------------------------------------------------------------------------------------- candidates
# con / coff: datasheet on and off capacitance; il: on-state leakage max over -40..85 C (a pessimistic bound, both pins)
CANDS = {
    "tmux1119": dict(label="TMUX1119 (incumbent)", con=20e-12, coff=6e-12,
                     typ=dict(shape="TM", rpk=3.7, flat=1.9), mx=dict(shape="TM", rpk=8.8, flat=2.2), il=0.35e-9),
    "nx3157":   dict(label="74LVC1G3157 Nexperia", con=18e-12, coff=6e-12,
                     typ=dict(shape="NX", rpk=7.698, flat=1.941), mx=dict(shape="NX", rpk=20.0, flat=1.941 * 20 / 7.698), il=1e-6),
    "ts5a3157": dict(label="TS5A3157 TI", con=17.5e-12, coff=5.5e-12,
                     typ=dict(shape="NX", rpk=12.0, flat=8.0), mx=dict(shape="NX", rpk=20.0, flat=13.0), il=0.2e-6),
}
# the datasheet bound taken literally: Ron at its 20 ohm maximum everywhere (flat), against the typical curve
CANDS["nx3157_r20"] = dict(CANDS["nx3157"], label="74LVC1G3157, max corner = 20 ohm flat", mx=dict(shape="NX", rpk=20.0, flat=0.0))
CANDS["ts5a3157_r20"] = dict(CANDS["ts5a3157"], label="TS5A3157, max corner = 20 ohm flat", mx=dict(shape="NX", rpk=20.0, flat=0.0))
# Kelvin arrangement (the switch selects what (-) senses; netlib sw='kelvin') with the Nexperia part, as an option
KELVIN = {"nx3157k": "nx3157", "tmux1119k": "tmux1119"}

def base_of(c):
    """Key '<cand>[_x<k>]': RF and RG both scaled by k (series strings of the existing 953 and 249 types)."""
    scale = 1
    m = re.match(r"(.*)_x(\d+(?:p\d+)?)$", c)
    if m:
        c, scale = m.group(1), float(m.group(2).replace("p", "."))
    k = KELVIN.get(c, c); d = CANDS[k]
    sw = lambda corner: dict(d[corner], con=d["con"], coff=d["coff"], il=0.0)
    p = L.P("H", Cs_on=d["con"], Cs_off=d["coff"], swv=sw("typ"), swv_max=sw("mx"))
    if c in KELVIN:
        p["sw"] = "kelvin"
    p["RF"] *= scale; p["RG"] *= scale
    return p, d

def lin_corners(d):
    """Linear Ron for AC/noise: the lowest Ron the typical curve reaches over the signal span, and the maximum corner's peak."""
    lo = ron_range(d["typ"], 0.4, 2.8)[0]; hi = ron_range(d["mx"], 0.4, 2.8)[1]
    return lo, hi

def save(name, obj):
    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    with open(os.path.join(HERE, "results", name + ".json"), "w") as f:
        json.dump(obj, f, indent=1, default=float)
    return obj

def loadj(name):
    with open(os.path.join(HERE, "results", name + ".json")) as f:
        return json.load(f)

# ---------------------------------------------------------------------------------------------- DC: SC-2, SC-4, SC-11, SC-8
def sec_dc(c):
    p, d = base_of(c)
    over = {k: p[k] for k in ("Cs_on", "Cs_off", "swv", "swv_max", "sw", "RF", "RG")}
    r = R.dc_section("OPA354", quick=True, over=over, tag=f"dc_{c}")
    return r

# ---------------------------------------------------------------------------------------------- SC-7: INL from Ron(V)
def sweep(p, v0, v1, n, name):
    txt = header(p, name) + rails(p) + "Vs in 0 dc 0\n" + core(p) + f"""
.control
dc Vs {v0} {v1} {(v1 - v0) / (n - 1)}
wrdata {wr(name,'d')} v(pin)
wrdata {wr(name,'f')} v(fb)
.endc
.end
"""
    run_ng(name, txt)
    a = load(name, "d"); b = load(name, "f")
    return a[:, 0], a[:, 1], b[:, 1]

def sec_inl(c):
    p, d = base_of(c)
    out = {}
    for rng, vfs in (("5", 5.0), ("1.25", 1.25)):
        for corner in ("typ", "mx", "const"):
            # const: the same switch with its Ron(V) flattened to its value at Vmid: what the rest of the channel contributes
            sw = dict(p["swv"] if corner != "mx" else p["swv_max"])
            if corner == "const":
                sw.update(rpk=float(ron_at(p["swv"], 1.6)), flat=0.0)
            q = dict(p, rng=rng, aref=3.3, swv=sw)
            vin, pin, fb = sweep(q, -1.2 * vfs, 1.2 * vfs, 241, "inl")
            cal = np.abs(vin) <= 0.93 * vfs                  # PA-3: DAC0's window covers about 93 % of the +/-5 V range
            k = np.polyfit(vin[cal], pin[cal], 1)
            res = pin - np.polyval(k, vin)
            inr = np.abs(vin) <= vfs + 1e-9
            lsb = 3.3 / 4096
            # input-referred error against SC-7 (+/-0.5 % of reading +/-5 mV)
            ein = res / k[0]
            lim = 0.005 * np.abs(vin) + 5e-3
            out[f"{rng}_{corner}"] = dict(gain=float(k[0]), inl_codes_pp=float((res[inr].max() - res[inr].min()) / lsb),
                                          inl_codes_max=float(np.abs(res[inr]).max() / lsb),
                                          inl_codes_max_6V=float(np.abs(res).max() / lsb) if rng == "5" else None,
                                          ein_mV_max=float(np.abs(ein[inr]).max() * 1e3),
                                          sc7_fraction_max=float((np.abs(ein[inr]) / lim[inr]).max()),
                                          at_worst_vin=float(vin[inr][np.argmax(np.abs(ein[inr]) / lim[inr])]),
                                          fb_span=[float(fb[inr].min()), float(fb[inr].max())],
                                          ron_span_typ=ron_range(q["swv"], float(fb[inr].min()), float(fb[inr].max())),
                                          vin=vin.tolist(), pin=pin.tolist())
    # the switch's own share: the difference from the flattened-Ron run, fitted and judged the same way
    for rng, vfs in (("5", 5.0),):
        vin = np.array(out[f"{rng}_const"]["vin"]); base = np.array(out[f"{rng}_const"]["pin"])
        for corner in ("typ", "mx"):
            dlt = np.array(out[f"{rng}_{corner}"]["pin"]) - base
            g = out[f"{rng}_{corner}"]["gain"]
            cal = np.abs(vin) <= 0.93 * vfs; inr = np.abs(vin) <= vfs + 1e-9
            k = np.polyfit(vin[cal], dlt[cal], 1); res = dlt - np.polyval(k, vin)
            lim = 0.005 * np.abs(vin) + 5e-3
            out[f"{rng}_{corner}_switch_only"] = dict(inl_codes_max=float(np.abs(res[inr]).max() / (3.3 / 4096)),
                                                      inl_codes_pp=float(np.ptp(res[inr]) / (3.3 / 4096)),
                                                      ein_mV_max=float(np.abs(res[inr]).max() / g * 1e3),
                                                      sc7_fraction_max=float((np.abs(res[inr]) / g / lim[inr]).max()),
                                                      at_worst_vin=float(vin[inr][np.argmax(np.abs(res[inr]) / g / lim[inr])]),
                                                      pct_of_reading_max_above_1V=float((np.abs(res) / g / np.maximum(np.abs(vin), 1e-9))[(np.abs(vin) >= 1.0) & inr].max() * 100))
    # leakage: the on-state leakage bound into the switch pins, as an offset (+/-1.25 V: open, into the RF||RG node)
    for rng in ("5", "1.25"):
        q0 = dict(p, rng=rng, aref=3.3)
        q1 = dict(q0, swv=dict(q0["swv"], il=d["il"]))
        a = sweep(q0, -0.1, 0.1, 3, "lk0")[1][1]; b = sweep(q1, -0.1, 0.1, 3, "lk1")[1][1]
        out[f"leak_{rng}"] = dict(il_A=d["il"], dpin_mV=float((b - a) * 1e3), dpin_codes=float((b - a) / (3.3 / 4096)))
    # temperature: Ron at the Vmid bias on the Nexperia curves (the only part with published curves against temperature)
    if d["typ"]["shape"] == "NX":
        out["tempco_nx"] = {t: float(np.interp(1.6, SV, CURVES["NX"][t])) for t in CURVES["NX"]}
    return save(f"inl_{c}", out)

# ---------------------------------------------------------------------------------------------- AC: SM-3, AN-1
def sec_ac(c):
    p, d = base_of(c)
    lo, hi = lin_corners(d)
    q0 = {k: v for k, v in p.items() if k not in ("swv", "swv_max")}
    out = dict(ron_lin=(lo, hi))
    for rng in ("5", "1.25"):
        ron_nom = float(ron_at(d["typ"], 1.6))
        o = {"nominal": R.ac_summary(dict(q0, rng=rng, Ron_sw=ron_nom), "ac_n")}
        wb, wp, wk = 1e99, 1e9, -1e9
        for cx in (-2e-12, 0.0, 3e-12):
            for ron in (lo, hi):
                for c1s, c2s in ((1.05, 0.95), (0.95, 1.05)):
                    for csw in (6e-12, 10e-12):
                        r = R.ac_summary(dict(q0, rng=rng, Cpar_extra=cx, Ron_sw=ron, C1=q0["C1"] * c1s, C2=q0["C2"] * c2s, Csoff=csw), "ac_c")
                        wb = min(wb, r["bw"]); wk = max(wk, r["peak_db"])
                        if r["pm"] is not None:
                            wp = min(wp, r["pm"])
        o["worst"] = dict(bw=wb, pm=wp, peak_db=wk)
        out[rng] = o
    return save(f"ac_{c}", out)

# ---------------------------------------------------------------------------------------------- SC-6 noise
def sec_noise(c):
    p, d = base_of(c)
    q0 = {k: v for k, v in p.items() if k not in ("swv", "swv_max")}
    ac = loadj(f"ac_{c}")
    out = {}
    for rng in ("5", "1.25"):
        q = dict(q0, rng=rng, Ron_sw=float(ron_at(d["typ"], 1.6)))
        fm = 1.5 * ac[rng]["nominal"]["bw"]
        a = noise_total(q, "nz", fm, "all")
        vm = R.transfer_rms(q, "nzx", "vm", R.EN_VMID, fm); v3 = R.transfer_rms(q, "nzx", "v3", R.EN_V3, fm)
        out[rng] = dict(fmax=fm, total_V=float(np.sqrt(a * a + vm * vm + v3 * v3)), all_V=a, vmid_V=vm, v3_V=v3)
    return save(f"noise_{c}", out)

# ---------------------------------------------------------------------------------------------- SC-10 settling (S/H kick)
def sec_kick(c):
    p, d = base_of(c)
    out = {}
    for rng, vfs in (("5", 6.0), ("1.25", 1.25)):
        for corner in ("typ", "mx"):
            q = dict(p, rng=rng, swv=dict(p["swv"] if corner == "typ" else p["swv_max"]))
            for lab, adc in (("derived", R.ADC_DERIVED), ("stress", R.ADC_STRESS)):
                k = R.kick_run(q, +vfs, -vfs, adc, name="kk", aref=3.2)
                out[f"{rng}_{corner}_{lab}"] = dict(err_lsb=max(abs(k["errA_lsb"]), abs(k["errB_lsb"])), settle_ns=k["settleB_ns"])
    return save(f"kick_{c}", out)

# ---------------------------------------------------------------------------------------------- PR-1 / PR-2 at the switch pins
def prot_powered(p, vin, rng):
    q = dict(p, rng=rng, v3=3.3, esd_n=True)
    txt = header(q, "pp") + rails(q, vcc=3.37, vmid=1.65) + f"Vs in 0 dc {vin}\n" + core(q) + """
.control
op
print v(out) v(fb) v(vccl) v(n) i(Vos)
.endc
.end
"""
    o = run_ng("pp", txt); g = lambda k: R._grab(o, k)
    return dict(v_out=g("v(out)"), v_fb=g("v(fb)"), v_rail=g("v(vccl)"), v_n=g("v(n)"), i_opamp_in_mA=abs(g("i(vos)")) * 1e3)

def unpowered_sw(p, vins, bleed=4700.0, sw_state="closed"):
    """lowz.unpowered_net (everything unpowered, ICs as pin clamps, rail floating with a bleed) plus the range switch's own
    pin clamps at out and fb, each through a 0 V ammeter, and the switch itself closed (its Ron) or open."""
    import lowz
    # rebuild the netlist text by calling the original with a capture of run_ng
    cap = {}
    def fake(name, text, timeout=600):
        cap["t"] = text; return ""
    real = lowz.run_ng
    lowz.run_ng = fake
    try:
        try:
            lowz.unpowered_net(p, vins, bleed, name="usw")
        except Exception:
            pass
    finally:
        lowz.run_ng = real
    head = cap["t"].split("\n.control")[0]
    extra = []
    ron = float(ron_at(p["swv"], 0.5))
    for c in "ab":
        extra += [f"* range switch pin clamps, channel {c}",
                  f"Dw1{c} {c}out {c}w1 DESD", f"Vw1{c} {c}w1 rail 0", f"Dw2{c} {c}w2 {c}out DESD", f"Vw2{c} 0 {c}w2 0",
                  f"Dw3{c} {c}fb {c}w3 DESD", f"Vw3{c} {c}w3 rail 0", f"Dw4{c} {c}w4 {c}fb DESD", f"Vw4{c} 0 {c}w4 0",
                  f"Rsw{c} {c}out {c}fb {ron if sw_state == 'closed' else 1e12:.6g}"]
    body = head.rstrip() + "\n" + "\n".join(extra) + "\n.control\nop\nprint v(rail) v(aout) v(afb) v(bout) v(bfb) i(Vw1a) i(Vw2a) i(Vw3a) i(Vw4a) i(Vdue) v(an)\n.endc\n.end\n"
    o = run_ng("usw", body); g = lambda k: R._grab(o, k)
    r = dict(v_rail=g("v(rail)"), v_out=g("v(aout)"), v_fb=g("v(afb)"), v_n=g("v(an)"), i_due_uA=g("i(vdue)") * 1e6,
             i_sw_clamp_uA=max(abs(g("i(vw1a)")), abs(g("i(vw2a)")), abs(g("i(vw3a)")), abs(g("i(vw4a)"))) * 1e6)
    r["above_rail_V"] = max(r["v_out"], r["v_fb"]) - r["v_rail"]; r["below_gnd_V"] = -min(r["v_out"], r["v_fb"])
    return r

def sec_prot(c):
    p, d = base_of(c)
    out = {"powered": {}, "unpowered": {}}
    for rng in ("5", "1.25"):
        for vin in (12.0, -12.0, 30.0, -30.0):
            out["powered"][f"{rng}|{vin:+.0f}"] = prot_powered(p, vin, rng)
    for k, v in L.INPUTS_HZ.items():
        for st in ("closed", "open"):
            out["unpowered"][f"{k}|{st}"] = unpowered_sw(p, v, sw_state=st)
    return save(f"prot_{c}", out)

# ---------------------------------------------------------------------------------------------- SC-9 scope to scope
def sec_xt(c):
    p, d = base_of(c)
    q0 = {k: v for k, v in p.items() if k not in ("swv", "swv_max")}
    out = {}
    for rng, vfs in (("5", 6.0), ("1.25", 1.25)):
        q = dict(q0, rng=rng, Ron_sw=float(ron_at(d["mx"], 1.6)))
        hi = R.kick_run(q, vfs, 0.0, R.ADC_DERIVED, name="xk", aref=3.2)
        lo = R.kick_run(q, -vfs, 0.0, R.ADC_DERIVED, name="xk", aref=3.2)
        tot = abs((hi["vpin_b"] + hi["errB_lsb"] * L.LSB32) - (lo["vpin_b"] + lo["errB_lsb"] * L.LSB32)) / L.LSB32
        f, hb, ha = L.ac_xtalk(q, name="xa")
        xs = hb * vfs / L.LSB32
        out[rng] = dict(dc_step_lsb=tot, sine_max_lsb=float(xs.max()), f_at_max=float(f[np.argmax(xs)]),
                        rg_current_mA_at_fs=float(abs(hi["vpin_a"] - 1.6) / p["RG"] * 1e3))
    return save(f"xt_{c}", out)

FUN = dict(xt=sec_xt, dc=sec_dc, inl=sec_inl, ac=sec_ac, noise=sec_noise, kick=sec_kick, prot=sec_prot)

if __name__ == "__main__":
    sec = sys.argv[1]
    cands = sys.argv[2:] or list(CANDS) + list(KELVIN)
    for c in cands:
        NL.PFX = f"{sec}_{c}_"
        t0 = time.time()
        FUN[sec](c)
        print(sec, c, round(time.time() - t0), flush=True)
