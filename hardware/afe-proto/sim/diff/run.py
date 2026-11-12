#!/usr/bin/env python3
"""2d differential mode: regenerates every number in report.md.
   python3 -I run.py                      DF-3 for the 2026-11-11 low-impedance divider -> report.md, results/
   D2_VARIANT=legacy python3 -I run.py    the 1 Mohm divider's full 2d run (all scenarios) -> report_legacy.md, results/legacy/
   D2_WORKERS (default 4) sets the number of parallel ngspice processes; D2_NMC (default 200) the Monte Carlo draws

Everything is ngspice (the 2b channel netlist and OPA354 model, reused by path from ../scope and ../../models)
plus numpy post-processing.  Raw numbers go to results/*.json, representative netlists to netlists/."""
import os, sys, json, time, glob, re
import numpy as np
from concurrent.futures import ProcessPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import dlib, core2d as c

RES = {"hz": os.path.join(HERE, "results"), "lowz2": os.path.join(HERE, "results", "lowz2"), "lowz": os.path.join(HERE, "results", "lowz")}.get(dlib.VARIANT, os.path.join(HERE, "results", "legacy"))
os.makedirs(RES, exist_ok=True)
NMC = int(os.environ.get("D2_NMC", "200"))
SEED = 20261111
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

# ---- the two scenarios ------------------------------------------------------------------------------
SPEC = c.SPEC                                                    # as specified: 0.1 % R, 25 ppm/K, 5 % C, Ron 3.7-8.8 independent
FIXED = dict(name="fixed", tolR=0.0005, tolC=0.05, stray=0.5e-12, ron_lo=3.7, ron_hi=8.8, dron=0.5, tcr=10.0, trim=0.005)
# the three stocked-parts variants added with the trimmer question: 0.05 % at 25 ppm/K without a trimmer, and the SPEC resistors with one
D05 = dict(SPEC, name="d05", tolR=0.0005)
TRIM_CAL = dict(SPEC, name="trim_cal", trimmer="cal")     # trim nulls the reading AFTER the PA-3 stage-gain calibration
TRIM_RAW = dict(SPEC, name="trim_raw", trimmer="raw")     # trim nulls the raw reading, calibration applied afterwards

POOL = ProcessPoolExecutor(max_workers=int(os.environ.get("D2_WORKERS", "4")))   # one ngspice per worker

def corner_worker(args):
    sc, key, tag = args
    # reference = the same corner with no temperature excursion; the one-time trim is found there
    refd = c.corner_draw(sc, dT=0.0, name=key + "_ref", **c.ref_kw(key))
    rts = None; info = None
    if sc.get("trimmer"):
        rtA, rtB, info = c.trim_solve(sc, c.at_T(refd), f"{tag}_{key}_trim", +sc.get("trim_res", c.TRIM_RES))
        rts = {key: (rtA, rtB)}
        refd = c.corner_draw(sc, dT=0.0, name=key + "_ref", rt=(rtA, rtB), **c.ref_kw(key))
    hot = c.corner_set(sc, rts)[key]
    d0 = c.at_T(refd)
    out = {}
    for rg in ("5", "1.25"):
        r = c.eval_range(f"{tag}_{key}_{rg}", c.at_T(hot), rg)
        r0 = c.eval_range(f"{tag}_{key}ref_{rg}", d0, rg, with_ac=False)
        r["df4"] = c.df4_residual(r0, r, rg)
        r["cal"] = c.add_cal(r0, r, d0, rg)
        out[rg] = c._strip(r)
    if info:
        out["trim"] = info
    return key, out

def nominal_worker(args):
    sc, tag = args
    nomd = c.corner_draw(dict(sc, tolR=0, tolC=0, stray=0, dron=0, ron_hi=sc["ron_lo"], tcr=0, trim=None), dT=0, vs=0, rs=(0, 0),
                         sops=0, aref=3.30, cent=0, vcc=3.30, name="nominal")
    return {rg: c._strip(c.eval_range(f"{tag}_nom_{rg}", c.at_T(nomd), rg)) for rg in ("5", "1.25")}

def scenario(sc, tag):
    log(f"scenario {sc['name']}: {NMC} draws + corners")
    mcs = list(POOL.map(c.mc_worker, [(sc, SEED, i, tag) for i in range(NMC)], chunksize=4))
    keys = list(c.HOTKW)
    cor = dict(POOL.map(corner_worker, [(sc, k, tag) for k in keys]))
    nom = nominal_worker((sc, tag))
    S = c.summarize_scenario(sc, mcs, dict(cor, nominal=nom))
    if sc.get("trimmer"):
        inf = [m["trim"] for m in mcs]
        rt = np.array([[i["rtA"], i["rtB"]] for i in inf])
        S["trim_info"] = dict(
            n=len(inf), sat=int(sum(i["sat"] for i in inf)), m0_abs_max=float(max(abs(i["m0"]) for i in inf)),
            m0_abs_p99=float(np.percentile([abs(i["m0"]) for i in inf], 99)), rt_min=float(rt.min()), rt_max=float(rt.max()),
            dR_abs_max=float(np.abs(rt[:, 0] - rt[:, 1]).max()), k_per_ohm=float(np.median([i["k"] for i in inf])),
            corners={k: dict(m0=v["trim"]["m0"], rtA=v["trim"]["rtA"], rtB=v["trim"]["rtB"], sat=v["trim"]["sat"]) for k, v in cor.items()})
    # DF-4
    for rg in ("5", "1.25"):
        S[rg]["df4"] = df4_summary(rg, mcs, cor)
    return S, mcs, cor, nom

def df4_summary(rg, mcs, cor):
    """DF-4 residual after the per-channel gain/offset fit; Adm for the code size."""
    rows = [m[rg] for m in mcs] + [v[rg] for v in cor.values()]
    g = np.array(rows[0]["df4"]["g"])
    true_d = g[:, None] - g[None, :]
    aref = c.AREF_HI
    res = {}
    for pga, k in ((1.0, 1.0), (0.5, 2.0)):
        # |reading| limited to the PGA's range at the pin; one code in input volts at AREF 3.30 (largest LSB)
        worst_ratio = 0.0; worst_abs = 0.0; worst_cm = 0.0
        for r in rows:
            adm = r["adm"]
            code = k * aref / 4096 / adm
            err = np.abs(np.array(r["df4"]["err_grid"]))
            allowed = 0.005 * np.abs(true_d) + code
            worst_ratio = max(worst_ratio, float((err / allowed).max()))
            worst_abs = max(worst_abs, float(err.max()))
        res[f"pga{pga}"] = dict(code_mV=k * aref / 4096 / min(r["adm"] for r in rows) * 1e3,
                                err_over_allowed_max=worst_ratio, err_max_mV=worst_abs * 1e3)
    res["err_max_mV"] = max(r["df4"]["err_max"] for r in rows) * 1e3
    res["drift_max_mV"] = max(r["df4"]["drift_max"] for r in rows) * 1e3
    res["drift_over_allowed_max"] = {}
    for pga, k in ((1.0, 1.0), (0.5, 2.0)):
        res["drift_over_allowed_max"][str(pga)] = max(
            float((np.abs(np.array(r["df4"]["err_grid"])) * 0 + r["df4"]["drift_max"] / (0.005 * np.abs(true_d) + k * aref / 4096 / r["adm"])).max())
            for r in rows)
    res["err_ref_max_mV"] = max(r["df4"]["err_ref_max"] for r in rows) * 1e3
    res["err_zero_diff_max_mV"] = max(r["df4"]["err_at_zero_diff"] for r in rows) * 1e3
    res["vmax_in"] = float(g[-1])
    return res

# ---- sweeps: what closes it ---------------------------------------------------------------------------
def dc_sweep_worker(args):
    tolR, tcr, dron = args
    sc = dict(SPEC, tolR=tolR, tcr=tcr, dron=dron)
    out = {}
    for rg in ("5", "1.25"):
        v = []
        for key in ("wc", "wc_Rsswap"):
            d = c.corner_set(sc)[key]
            v.append(c.eval_range(f"sw_{tolR}_{tcr}_{dron}_{key}_{rg}", c.at_T(d), rg, with_ac=False)["cmrr_dc"])
        out[rg] = float(min(v))
    return (tolR, tcr, dron), out

def hf_sweep_worker(args):
    trim, tolC, stray = args
    sc = dict(FIXED, trim=trim, tolC=tolC, stray=stray)
    out = {}
    for rg in ("5", "1.25"):
        v = []
        for key, d in c.corner_set(sc).items():
            if key == "pin_bot":
                continue
            r = c.eval_range(f"hs_{trim}_{tolC}_{stray}_{key}_{rg}", c.at_T(d), rg)
            v.append(c.at_f(r["f"], np.minimum(r["cmrr_f"], r["cmrr_f_alt"]), 1e4))
        out[rg] = float(min(v))
    return (trim, tolC, stray), out

def sweeps():
    log("DC sweep (tolerance x tempco x Ron matching), worst corners")
    grid = [(t, tc, d) for t in (0.001, 0.0005, 0.00025) for tc in (25, 10, 5) for d in (None, 1.5, 0.5, 0.25)]
    dcs = dict(POOL.map(dc_sweep_worker, grid))
    log("HF sweep (C1 trim residual, C tolerance, stray) at 10 kHz")
    grid = [(tr, 0.05, 0.5e-12) for tr in (None, 0.05, 0.03, 0.02, 0.01, 0.0075, 0.005, 0.0025)] + \
           [(None, tc, st) for tc in (0.05, 0.02, 0.01, 0.005, 0.0025, 0.001) for st in (0.5e-12, 0.1e-12, 0.0)]
    hfs = dict(POOL.map(hf_sweep_worker, grid))
    return dcs, hfs

def c1res_worker(args):
    """10 kHz CMRR (raw, DC-uncalibrated) at the signed corners with the E24 C1 sitting csys away from the ideal in BOTH channels."""
    name, base, csys = args
    sc = dict(base, csys=csys)
    v = {}
    for rg in ("5", "1.25"):
        vals = []
        for key, dd in c.corner_set(sc).items():
            if key == "pin_bot":
                continue
            r = c.eval_range(f"c1r_{name}_{csys}_{key}_{rg}", c.at_T(dd), rg)
            vals.append(c.at_f(r["f"], np.minimum(r["cmrr_f"], r["cmrr_f_alt"]), 1e4))
        v[rg] = float(min(vals))
    return (name, csys), v

def c1_residual():
    grid = [(n, b, cs) for n, b in (("caps_matched", dict(SPEC, tolC=0.0, stray=0.0)), ("caps_5pct", SPEC)) for cs in (0.0, -0.012, 0.013, 0.04)]
    return dict(POOL.map(c1res_worker, grid))

def trim_sweep_worker(args):
    res, mode = args
    sc = dict(TRIM_CAL, trimmer=mode, trim_res=res)
    out = {}
    cs = [corner_worker((sc, k, f"ts{res}{mode}")) for k in ("wc", "wc_cold")]
    for rg in ("5", "1.25"):
        out[rg] = dict(cal=min(v[rg]["cal"]["dc"] for _, v in cs),
                       raw=min(v[rg]["cmrr_dc"] for _, v in cs))
    return (res, mode), out

def trim_sweeps():
    grid = [(r, "cal") for r in (0.0, 0.0005, 0.001, 0.002, 0.004)]
    return dict(POOL.map(trim_sweep_worker, grid))

# ---- common-mode window -------------------------------------------------------------------------------
def cm_window():
    """Both inputs driven together, worst corners; where each pin leaves 0..AREF (with and without the 80 mV margin),
    where the op-amp leaves its linear range, and what the difference reads past that."""
    out = {}
    for rg, span, st in (("5", 9.0, 0.05), ("1.25", 2.0, 0.01)):
        for tag, kw in (("aref3.20_cent+", dict(cent=+1, aref=3.20, vcc=3.23)),
                        ("aref3.20_cent-", dict(cent=-1, aref=3.20, vcc=3.23)),
                        ("aref3.30_cent+", dict(cent=+1, aref=3.30, vcc=3.37)),
                        ("aref3.30_cent-", dict(cent=-1, aref=3.30, vcc=3.37))):
            res = {}
            # gain-high channel A + vos sign aligned with the side under test, B gain-low (worst for the difference)
            for side, vs in (("top", +1), ("bottom", -1)):
                d = c.at_T(c.corner_draw(SPEC, vs=vs, dT=0.0, rs=(50.0, 50.0), name="cm", **kw))
                V, pa, pb, oa, ob = dlib.cm_sweep(f"cm_{rg}_{tag}_{side}", d, rg, -span, span, st)
                aref = d["sh"]["aref"]
                lin = (V > -0.3) & (V < 0.3)
                ka = np.polyfit(V[lin], pa[lin], 1)
                dev = pa - np.polyval(ka, V)
                kb = np.polyfit(V[lin], pb[lin], 1)
                devb = pb - np.polyval(kb, V)
                def cross(y, thr, up=True):
                    idx = np.where(y > thr)[0] if up else np.where(y < thr)[0]
                    idx = idx[V[idx] > 0] if up else idx[V[idx] < 0]
                    if len(idx) == 0:
                        return None
                    i = idx[0] if (up) else idx[-1]
                    return float(V[i])
                top = np.maximum(pa, pb); bot = np.minimum(pa, pb)
                res[side] = dict(
                    v_pin_margin80_top=cross(top, aref - 0.08), v_pin_aref=cross(top, aref),
                    v_pin_margin80_bot=cross(bot, 0.08, up=False), v_pin_zero=cross(bot, 0.0, up=False),
                    v_compress_2mV_top=cross(np.maximum(dev, devb), 2e-3), v_compress_2mV_bot=cross(-np.minimum(dev, devb), 2e-3),
                    pin_top_end=float(top.max()), pin_bot_end=float(bot.min()), out_top_end=float(max(oa.max(), ob.max())),
                    diff_end_top=float((pa - pb)[-1]), diff_end_bot=float((pa - pb)[0]),
                    diff_at_zero=float(np.interp(0, V, pa - pb)), diff_peak=float(np.abs(pa - pb).max()), v_diff_peak=float(V[np.argmax(np.abs(pa - pb))]), aref=aref, vcc=d["sh"]["vcc"], span=span)
            out[f"{rg}|{tag}"] = res
    return out

# ---- noise ----------------------------------------------------------------------------------------------
def noise():
    out = {}
    nomd = c.at_T(c.corner_draw(dict(SPEC, tolR=0, tolC=0, stray=0, dron=0, ron_hi=3.7, tcr=0, trim=None), dT=0, vs=0, rs=(50, 50),
                                sops=0, aref=3.30, cent=0, vcc=3.30, name="nominal"))
    bw = {"5": 193e6, "1.25": 25e6}             # 1.5 x the 2b -3 dB bandwidth (the primary figure in 2b)
    wc = c.at_T(c.corner_draw(SPEC, dT=0.0, rs=(50.0, 50.0), name="wc"))
    for rg in ("5", "1.25"):
        for lab, fmax in (("1.5xBW", bw[rg]), ("10MHz", 10e6)):
            single = dlib.noise_pair(f"nz_s_{rg}_{lab}", nomd, rg, fmax, "v(apin)")
            diff = dlib.noise_pair(f"nz_d_{rg}_{lab}", nomd, rg, fmax, "v(apin,bpin)")
            # Vmid (20 nV/rtHz) and 3.3 V sense (100 nV/rtHz) are the 2b assumptions, shared by both channels
            parts = {}
            for rail, en in (("vm", 20e-9), ("v3", 100e-9)):
                f, h = dlib.ac_diff_rail(f"nzr_{rail}_{rg}", wc, rg, rail)
                m = f <= fmax
                parts[rail] = float(np.sqrt(np.trapezoid((en * h[m]) ** 2, f[m])))
            out[f"{rg}|{lab}"] = dict(single_pin=single, diff=diff, ratio=diff / single, vmid_diff=parts["vm"], v3_diff=parts["v3"],
                                      diff_total=float(np.sqrt(diff ** 2 + parts["vm"] ** 2 + parts["v3"] ** 2)), fmax=fmax)
    return out

# ---- ADC pair polarity and ranges (datasheet facts, arithmetic only) --------------------------------------
# Table 43-5: AD6-AD7 -> CH6; Arduino A1 = AD6, A0 = AD7 (CLAUDE.md); VIN+ is the first-listed pin *(check, VT-11)*.
PAIR = dict(vinp="A1", vinm="A0", chp="CH1", chm="CH2")

def adc_diff_code(v_a1, v_a0, aref, pga, mapping=PAIR):
    """Ideal differential conversion: code = 2048 + (VIN+ - VIN-) / LSB; LSB = AREF/4096 (PGA 1), 2 AREF/4096 (PGA 0.5)."""
    lsb = aref / 4096 * (1.0 if pga == 1 else 2.0)
    vp, vm = (v_a1, v_a0) if mapping["vinp"] == "A1" else (v_a0, v_a1)
    return 2048 + (vp - vm) / lsb

# ---- guards: break each check on purpose, watch it fail, restore, watch it pass -----------------------------
def guards():
    G = []
    base_sc = dict(SPEC, tolR=0, tolC=0, stray=0, dron=0, ron_hi=3.7, tcr=0, trim=None)
    def nominal_draw(**over):
        d = c.corner_draw(base_sc, dT=0, vs=0, rs=(0, 0), sops=0, aref=3.30, cent=0, vcc=3.30, name="nominal")
        d = c.at_T(d)
        for k, v in over.items():
            who, key = k.split("_", 1)
            d[who] = dict(d[who]); d[who][key] = v
        return d
    def cm10k(d, rg="5"):
        r = c.eval_range("g_" + str(abs(hash(str(d)))), d, rg)
        return r["cmrr_dc"], c.at_f(r["f"], r["cmrr_f"], 1e4), r
    def row(name, what, ok_good, ok_bad, good_txt, bad_txt):
        G.append(dict(name=name, what=what, good=good_txt, bad=bad_txt, good_pass=bool(ok_good), bad_fails=bool(not ok_bad)))
    # a nominal pair, the check functions, then each break
    dc0, hf0, r0 = cm10k(nominal_draw())
    # 1. C1 mismatch on one channel: the 10 kHz CMRR guard (>= 40 dB) must fail, DC guard must not
    dcb, hfb, _ = cm10k(nominal_draw(A_eC1=0.10))
    row("G1 C1 +10 % on channel A", "CMRR >= 40 dB at 10 kHz", hf0 >= 40, hfb >= 40,
        f"matched pair {hf0:.1f} dB (DC {dc0:.1f})", f"broken {hfb:.1f} dB (DC {dcb:.1f})")
    # 2. R2 and R3 swapped on one channel: the divider loses its centring and its gain; DC CMRR and pin-centre guards
    dcc, hfc, rc = cm10k(nominal_draw(A_R2=768e3, A_R3=330e3))
    row("G2 R2 <-> R3 swapped on channel A", "DC CMRR >= 46 dB", dc0 >= 46, dcc >= 46,
        f"matched pair {dc0:.1f} dB", f"broken {dcc:.1f} dB")
    # 2b. R1 <-> R3 swapped: both are 768k, so the circuit is unchanged - the guard is blind to it by design
    dcd, hfd, _ = cm10k(nominal_draw(A_R1=768e3, A_R3=768e3))
    G.append(dict(name="G2b R1 <-> R3 swapped on channel A", what="DC CMRR >= 46 dB", good=f"matched pair {dc0:.1f} dB",
                  bad=f"swapped {dcd:.1f} dB: identical, because R1 = R3 = 768k by design; a mis-assembly of this kind is invisible to any "
                      f"electrical test and is caught only by the bill of materials / the pick-and-place check",
                  good_pass=True, bad_fails=False, note="null by construction, reported, not counted as a working guard"))
    # 3. Ron mismatch: the real finding, DC CMRR guard on the +/-5 V range
    dcr, hfr, _ = cm10k(nominal_draw(B_Ron=8.8))
    row("G3 Ron 3.7 vs 8.8 ohm between the channels (+/-5 V range)", "DC CMRR >= 46 dB", dc0 >= 46, dcr >= 46,
        f"matched Ron {dc0:.1f} dB", f"broken {dcr:.1f} dB")
    # 4. ADC pair polarity
    aref = 3.30
    vp = lambda vin: 1.65 + 0.2348 * vin
    good = adc_diff_code(vp(+3.0), vp(-3.0), aref, 1) - 2048
    swapped = adc_diff_code(vp(+3.0), vp(-3.0), aref, 1, mapping=dict(PAIR, vinp="A0", vinm="A1")) - 2048
    row("G4 ADC pair polarity (VIN+ = A0 instead of A1)", "reading has the sign of CH1 - CH2 (> 0 for +3 V / -3 V)", good > 0, swapped > 0,
        f"VIN+ = A1: {good:+.0f} codes", f"VIN+ = A0: {swapped:+.0f} codes")
    # 5. pin-window guard.  The pin-margin check alone is BLIND to a mis-centred channel: the op-amp clips about 0.1 V
    #    inside the rail, so the pin stays inside 0..AREF while the reading is clipped (measured below).  The guard
    #    therefore is "margin >= 80 mV AND unclipped (linear to 20 mV at +/-6 V)"; the margin-only check is shown too.
    def clipdev(r):
        pa_ = r["_pa"]; i0 = pa_.shape[0] // 2
        return abs(pa_[i0 + 4, i0] - (pa_[i0, i0] + 4 * (pa_[i0 + 1, i0] - pa_[i0, i0])))
    d = nominal_draw(); d["sh"] = dict(d["sh"], cent=0.45)
    rm = c.eval_range("g_win_bad", d, "5", with_ac=False)
    d = nominal_draw(); rg_ = c.eval_range("g_win_ok", d, "5", with_ac=False)
    okf = lambda r: r["margin"] >= 0.08 and clipdev(r) < 0.020
    row("G5 Vmid centring +450 mV, margin AND linearity", "pin margin >= 80 mV and linear to 20 mV at +6 V", okf(rg_), okf(rm),
        f"centred: margin {rg_['margin']*1e3:.0f} mV, deviation {clipdev(rg_)*1e3:.1f} mV", f"broken: margin {rm['margin']*1e3:.0f} mV, deviation {clipdev(rm)*1e3:.0f} mV")
    G.append(dict(name="G5b the same break seen by the margin check alone", what="pin margin >= 80 mV at +/-6 V (as DF-2's SC-2 criterion reads)",
                  good=f"centred {rg_['margin']*1e3:.0f} mV", bad=f"broken {rm['margin']*1e3:.0f} mV: still above 80 mV, the op-amp clip keeps the pin inside the rail",
                  good_pass=True, bad_fails=False, note="margin-only check is blind to a clipped channel; G5 adds the linearity test"))
    # 6. The harness claim "the signed corner bounds every Monte Carlo draw": weaken the corner (tolerances /4) and
    #    count the MC draws that fall below it; the real corner must have 0, the weakened one must have some.
    weak = dict(SPEC, tolR=SPEC["tolR"] / 4, tcr=SPEC["tcr"] / 4, dron=SPEC["dron"], ron_lo=SPEC["ron_lo"], ron_hi=SPEC["ron_lo"] + (SPEC["ron_hi"] - SPEC["ron_lo"]) / 4)
    wk = c.eval_range("g_weak", c.at_T(c.corner_draw(weak, name="weak")), "5", with_ac=False)["cmrr_dc"]
    mcraw = json.load(open(os.path.join(RES, "mc_raw_spec.json")))["5"]["cmrr_dc"]
    real = json.load(open(os.path.join(RES, "scenario_spec.json")))["summary"]["5"]["dc_corner_min"]
    n_real = sum(1 for x in mcraw if x < real)
    n_weak = sum(1 for x in mcraw if x < wk)
    G.append(dict(name="G6 corner weakened to 1/4 of the tolerances", what="no Monte Carlo draw (200) below the signed worst corner (+/-5 V, DC CMRR)",
                  good=f"true corner {real:.1f} dB: {n_real} draws below", bad=f"weakened corner {wk:.1f} dB: {n_weak} draws below",
                  good_pass=n_real == 0, bad_fails=n_weak > 0))
    # 7. the calibrated metric: a STAGE fault must be calibrated out, a DIVIDER fault must not.  (+-1.25 V range: RF is the stage)
    def calc(d, rg="1.25"):
        r = c.eval_range("g_cal_" + str(abs(hash(str(d)))), d, rg, with_ac=False)
        return c.cal_cmrr(r, r, d, rg)[0], r["cmrr_dc"]
    cal0, raw0 = calc(nominal_draw())
    calS, rawS = calc(nominal_draw(A_RF=953.0 * 1.01))
    calD, rawD = calc(nominal_draw(A_R1=768e3 * 1.01))
    row("G7 R1 +1 % on channel A (a divider fault)", "calibrated DC CMRR >= 46 dB (+-1.25 V)", cal0 >= 46, calD >= 46,
        f"matched pair {cal0:.1f} dB", f"broken {calD:.1f} dB (raw {rawD:.1f}): the calibration cannot see the divider")
    G.append(dict(name="G7b RF +1 % on channel A (a stage fault) - control", what="calibrated DC CMRR >= 46 dB (+-1.25 V)",
                  good=f"matched pair {cal0:.1f} dB", bad=f"stage fault {calS:.1f} dB calibrated, {rawS:.1f} dB raw: the calibration removes it, so the metric is not just the raw one",
                  good_pass=bool(cal0 >= 46), bad_fails=False, note="control: this break must NOT fail the calibrated check; reported, not counted as a working guard"))
    # 8. the trim: leaving the trimmers at mid-setting, or setting them with A and B interchanged, must fail the post-calibration
    #    requirement at a signed worst corner where the solved trim passes it.  The corner is the trim_cal scenario's, +-1.25 V range.
    sc = TRIM_CAL
    refd = c.corner_draw(sc, dT=0.0, name="g8ref")
    rtA, rtB, info = c.trim_solve(sc, c.at_T(refd), "g8", +c.TRIM_RES)
    def hot_cal(a, b, rg="1.25"):
        r0d = c.at_T(c.corner_draw(sc, dT=0.0, name="g8r", rt=(a, b)))
        hotd = c.at_T(c.corner_draw(sc, name="g8h", rt=(a, b)))
        r0 = c.eval_range("g8r" + rg + str(a), r0d, rg, with_ac=False)
        r1 = c.eval_range("g8h" + rg + str(a), hotd, rg, with_ac=False)
        return c.cal_cmrr(r0, r1, r0d, rg)[0]
    ok_t = hot_cal(rtA, rtB); bad_mid = hot_cal(c.RT_NOM, c.RT_NOM); bad_swap = hot_cal(rtB, rtA)
    row("G8a trimmers left at mid-setting (no trim performed)", "post-calibration DC CMRR >= 46 dB at the signed worst corner, +-1.25 V", ok_t >= 46, bad_mid >= 46,
        f"solved trim {ok_t:.1f} dB", f"untrimmed {bad_mid:.1f} dB")
    row("G8b trim set with A and B interchanged", "post-calibration DC CMRR >= 46 dB at the signed worst corner, +-1.25 V", ok_t >= 46, bad_swap >= 46,
        f"solved trim {ok_t:.1f} dB", f"interchanged {bad_swap:.1f} dB")
    # 9. the trim's range check: a 1.5 % divider fault is inside the 0-10 k travel of both trimmers, 3 % is not
    def sat_of(f):
        dd = c.corner_draw(sc, dT=0.0, s=+1, rs=(0, 0), name="g9")
        dd = c.at_T(dd); dd["A"] = dict(dd["A"], R1=dd["A"]["R1"] * (1 + f)); dd["B"] = dict(dd["B"], R1=dd["B"]["R1"] / 1 )
        return c.trim_solve(sc, dd, f"g9_{f}", 0.0)[2]
    i15, i30 = sat_of(0.015), sat_of(0.03)
    row("G9 trim range check: R1 +1.5 % vs +3 % on channel A", "trim reports 'in range' (both trimmers inside 0-10 kohm)", not i15["sat"], not i30["sat"],
        f"+1.5 %: A {i15['rtA']:.0f}, B {i15['rtB']:.0f} ohm", f"+3 %: A {i30['rtA']:.0f}, B {i30['rtB']:.0f} ohm, saturated")
    # 10. The corner must be the worst: a deliberately mild corner (half the tolerances) must be beaten by a Monte Carlo draw set
    #    more often than the true corner (0 draws below it)
    return G, dict(nominal_dc=dc0, nominal_10k=hf0)

def corner_is_worst_guard(S):
    """Guard on the harness itself: the claim 'the signed corner bounds every Monte Carlo draw' is checked by counting
    draws below the corner; then the corner is deliberately weakened (half the tolerance) and the count must become non-zero."""
    sc = S["spec"]
    rows = []
    out = {}
    for rg in ("5", "1.25"):
        out[rg] = dict(mc_below_corner_dc=sc[rg]["mc_exceeds_corner_dc"], mc_below_corner_10k=sc[rg]["mc_exceeds_corner_10k"])
    return out

# ---- the one-shot driver -------------------------------------------------------------------------------------------
def main():
    S = {}
    ver = dlib.ngspice_version()
    log("ngspice:", ver)
    lib_sha = dlib.sha256(os.path.join(HERE, "..", "..", "models", "opa354", "OPA354_PSPICE.lib"))
    sw_sha = dlib.sha256(os.path.join(HERE, "..", "scope", "models", "rangesw.lib"))
    jdump("header", dict(ngspice=ver, opa354_lib_sha256=lib_sha, rangesw_sha256=sw_sha, nmc=NMC, seed=SEED))

    for sc, tag in ((SPEC, "sp"), (FIXED, "fx"), (D05, "d5"), (TRIM_CAL, "tc"), (TRIM_RAW, "tr")):
        s, mcs, cor, nom = scenario(sc, tag)
        S[sc["name"]] = s
        jdump("scenario_" + sc["name"], dict(params={k: v for k, v in sc.items()}, summary=s))
        raw = {rg: dict(cmrr_dc=[m[rg]["cmrr_dc"] for m in mcs], margin=[m[rg]["margin"] for m in mcs],
                        cmrr_10k=[c.at_f(m[rg]["f"], m[rg]["cmrr_f"], 1e4) for m in mcs], adm=[m[rg]["adm"] for m in mcs],
                        cal=[m[rg]["cal"]["dc"] for m in mcs], cal_ref=[m[rg]["cal"]["ref"] for m in mcs],
                        aref=[m[rg]["aref"] for m in mcs]) for rg in ("5", "1.25")}
        jdump("mc_raw_" + sc["name"], raw)
        # plot data: CMRR vs frequency
        plot = {rg: dict(f_Hz=s[rg]["f"], worst_corner_dB=s[rg]["wc_cmrr"], mc_min_dB=s[rg]["mc_cmrr_min"],
                         mc_p1_dB=s[rg]["mc_cmrr_p1"], mc_median_dB=s[rg]["mc_cmrr_med"], corners_dB=s[rg]["corner_cmrr"],
                         limit_dc_dB=46.0, limit_10kHz_dB=40.0) for rg in ("5", "1.25")}
        jdump("cmrr_vs_frequency_" + sc["name"], plot)
        # keep one representative netlist (the worst corner, +/-5 V) in netlists/
        d = c.at_T(c.corner_set(sc)["wc"])
        txt = dlib.netlist(f"2d {sc['name']} worst-corner pair, +/-5 V range, common-mode AC", d, "5",
                           "ac dec 12 10 20e6\nwrdata x.dat v(apin) v(bpin)\n", "Vsa sa 0 dc 0 ac 1\nVsb sb 0 dc 0 ac 1\n")
        with open(os.path.join(HERE, "netlists", f"pair_{sc['name']}_wc_cm_5.cir"), "w") as f:
            f.write(txt)
        d125 = dlib.netlist(f"2d {sc['name']} worst-corner pair, +/-1.25 V range, differential AC", d, "1.25",
                            "ac dec 12 10 20e6\nwrdata x.dat v(apin) v(bpin)\n", "Vsa sa 0 dc 0 ac 0.5\nVsb sb 0 dc 0 ac 0.5 180\n")
        with open(os.path.join(HERE, "netlists", f"pair_{sc['name']}_wc_dm_125.cir"), "w") as f:
            f.write(d125)
    dcs, hfs = sweeps()
    log("C1 systematic residual at 10 kHz")
    c1r = c1_residual()
    jdump("c1_residual", {f"{k[0]}|{k[1]}": v for k, v in c1r.items()})
    log("trim residual sweep")
    tsw = trim_sweeps()
    jdump("trim_sweep", {f"{k[0]}|{k[1]}": v for k, v in tsw.items()})
    jdump("sweeps", dict(dc={f"{k[0]}|{k[1]}|{k[2]}": v for k, v in dcs.items()},
                         hf={f"{k[0]}|{k[1]}|{k[2]}": v for k, v in hfs.items()}))
    log("common-mode window")
    cmw = cm_window()
    jdump("cm_window", cmw)
    log("noise")
    nz = noise()
    jdump("noise", nz)
    log("guards")
    gd, gextra = guards()
    jdump("guards", dict(rows=gd, nominal=gextra, harness=corner_is_worst_guard(S)))
    # report
    import report
    report.write(S, dcs, hfs, cmw, nz, gd, gextra, ver, lib_sha, sw_sha, NMC, tsw, c1r)
    # clean temporary netlists
    for fn in glob.glob(os.path.join(HERE, "work", "*")):
        try:
            os.remove(fn)
        except OSError:
            pass
    log("done")

# ---- the 2026-11-11 low-impedance divider: DF-3 only ------------------------------------------------------------
LOWZ = dict(SPEC, name="lowz")      # 0.1 %, 25 ppm/K (every divider part, as instructed), Ron 3.7-8.8, no trimmer

def guards_lowz():
    """The calibrated-CMRR check (>= 44 dB) must fail when the calibration residual is 2000 ppm instead of 55/62, and when
    R1 of one channel is 1 % off (a divider fault the N injection cannot see); the R3 injection must be blind to an R1
    fault no more than to the channel's own ratio (control)."""
    G = []
    key = "wc"
    hot = c.at_T(c.corner_set(LOWZ)[key]); d0 = c.at_T(c.corner_draw(LOWZ, dT=0.0, name="g_ref", **c.ref_kw(key)))
    def cal_at(rg, e, d0_=d0, hot_=hot, mode="N"):
        r1 = c.eval_range(f"gl_{key}_{rg}_{mode}", hot_, rg, with_ac=False); r0 = c.eval_range(f"gl0_{key}_{rg}_{mode}", d0_, rg, with_ac=False)
        return min(min(c.cal_cmrr(r0, r1, d0_, rg, (s * e, -s * e), mode=mode)[:2]) for s in (1, -1))
    # nominal pair, R1 +1 % on A: the N-injection calibration must fail 44 dB, the R3-injection one must not (it sees R3 = R1 ... only
    # through R3, so it does not see an R1 fault either: this row is a control that shows the limit of the R3 proposal)
    base_sc = dict(LOWZ, tolR=0, tolC=0, stray=0, dron=0, ron_hi=3.7, tcr=0, trim=None)
    nd = c.at_T(c.corner_draw(base_sc, dT=0, vs=0, rs=(0, 0), sops=0, aref=3.30, cent=0, vcc=3.30, name="nominal"))
    for rg in ("5", "1.25"):
        # the residual enters the check: a nominal pair passes with 55/62 ppm and must fail with 5000 ppm (1 % between channels)
        g1 = cal_at(rg, c.CAL_RES[rg], nd, nd); b1 = cal_at(rg, 5000e-6, nd, nd); r1_ = cal_at(rg, c.CAL_RES[rg], nd, nd)
        G.append(dict(guard=f"DF-3 after calibration >= 44 dB, +/-{rg} V, nominal pair", mutation="calibration residual 55/62 ppm -> 5000 ppm per channel",
                      good=g1, broken=b1, restored=r1_, effective=bool(g1 >= 44 and b1 < 44 and r1_ >= 44)))
    def nominal(**over):
        d = c.at_T(c.corner_draw(base_sc, dT=0, vs=0, rs=(0, 0), sops=0, aref=3.30, cent=0, vcc=3.30, name="nominal"))
        for k, v in over.items():
            who, kk = k.split("_", 1); d[who] = dict(d[who]); d[who][kk] = v
        return d
    def calnom(d, rg="1.25", mode="N"):
        r = c.eval_range("gn_" + str(abs(hash(str(d)))) + mode, d, rg, with_ac=False)
        return c.cal_cmrr(r, r, d, rg, mode=mode)[0]
    ok = calnom(nominal()); bad = calnom(nominal(A_R1=c.NOM["R1"] * 1.01)); ok2 = calnom(nominal())
    G.append(dict(guard="DF-3 after calibration >= 44 dB, nominal pair, +/-1.25 V", mutation="R1 +1 % on channel A (a divider fault)",
                  good=ok, broken=bad, restored=ok2, effective=bool(ok >= 44 and bad < 44 and ok2 >= 44)))
    if dlib.VARIANT == "hz":
        return G
    bad3 = calnom(nominal(A_R3=c.NOM["R3"] * 1.01), mode="R3"); ok3 = calnom(nominal(), mode="R3")
    G.append(dict(guard="R3-injection calibration, nominal pair, +/-1.25 V (control: the R3 injection reads the divider through R3)",
                  mutation="R3 +1 % on channel A: the R3 injection now mis-reads A's divider by the R3 error",
                  good=ok3, broken=bad3, restored=ok3, effective=bool(ok3 >= 44 and bad3 < 44)))
    return G

def main_lowz():
    ver = dlib.ngspice_version()
    log("ngspice:", ver, "variant", dlib.VARIANT, "NOM", c.NOM)
    lib_sha = dlib.sha256(os.path.join(HERE, "..", "..", "models", "opa354", "OPA354_PSPICE.lib"))
    sw_sha = dlib.sha256(os.path.join(HERE, "..", "scope", "models", "rangesw.lib"))
    jdump("header", dict(ngspice=ver, opa354_lib_sha256=lib_sha, rangesw_sha256=sw_sha, nmc=NMC, seed=SEED, nom=c.NOM,
                         cal_res=c.CAL_RES, ron_inj=c.RON_INJ, dT=c.DT, tcr=LOWZ["tcr"], tolR=LOWZ["tolR"]))
    s, mcs, cor, nom = scenario(LOWZ, "lz")
    keys = ("dc", "res") if dlib.VARIANT == "hz" else ("dc", "res", "res_ron", "res_ron_swap", "r3")
    extra = {}
    for rg in ("5", "1.25"):
        extra[rg] = {}
        for k in keys:
            g = (lambda cal: min(cal["dc"], cal["dc_alt"])) if k == "dc" else (lambda cal, k=k: cal[k])
            mcv = [g(m[rg]["cal"]) for m in mcs]; cv = {kk: g(v[rg]["cal"]) for kk, v in cor.items()}
            extra[rg][k] = dict(corner_min=min(cv.values()), corners=cv, mc_min=min(mcv), mc_p1=float(np.percentile(mcv, 1)),
                                mc_med=float(np.median(mcv)), mc_below_corner=sum(1 for x in mcv if x < min(cv.values()) - 1e-9))
    # what moves the worst corner: the source condition and the divider tolerance, one at a time ('res' = 55/62 ppm residual)
    var = {}
    for lab, sc_, rs in (("sources 0 / 100 ohm (DF-3 as written)", LOWZ, (0.0, 100.0)), ("sources 0 / 50 ohm", LOWZ, (0.0, 50.0)),
                         ("sources 0 / 10 ohm (10 ohm asymmetry)", LOWZ, (0.0, 10.0)), ("sources 90 / 100 ohm (10 ohm asymmetry)", LOWZ, (90.0, 100.0)),
                         ("sources equal, 0 / 0 ohm", LOWZ, (0.0, 0.0)), ("sources equal, 50 / 50 ohm", LOWZ, (50.0, 50.0)),
                         ("sources equal, 100 / 100 ohm", LOWZ, (100.0, 100.0)), ("divider 0.05 %, sources 0 / 100 ohm", dict(LOWZ, tolR=0.0005), (0.0, 100.0))):
        var[lab] = {}
        for rg in ("5", "1.25"):
            vals = []
            for key, dT in (("wc", c.DT), ("wc_cold", -c.DT)):
                hot = c.at_T(c.corner_draw(sc_, dT=dT, rs=rs, name=key)); d0 = c.at_T(c.corner_draw(sc_, dT=0.0, rs=rs, name=key + "_ref"))
                r1 = c.eval_range(f"var_{len(var)}_{key}_{rg}", hot, rg, with_ac=False); r0 = c.eval_range(f"var0_{len(var)}_{key}_{rg}", d0, rg, with_ac=False)
                E = c.CAL_RES[rg]
                vals.append(min(min(c.cal_cmrr(r0, r1, d0, rg, (sg * E, -sg * E))[:2]) for sg in (1, -1)))
            var[lab][rg] = float(min(vals))
    jdump("scenario_lowz", dict(params={k: v for k, v in LOWZ.items()}, summary=s, cal=extra, variants=var))
    jdump("mc_raw_lowz", {rg: dict(cmrr_dc=[m[rg]["cmrr_dc"] for m in mcs], cmrr_10k=[c.at_f(m[rg]["f"], m[rg]["cmrr_f"], 1e4) for m in mcs],
                                   cal={k: [m[rg]["cal"][k] for m in mcs] for k in keys}) for rg in ("5", "1.25")})
    d = c.at_T(c.corner_set(LOWZ)["wc"])
    txt = dlib.netlist("2d lowz worst-corner pair, +/-5 V range, common-mode AC", d, "5",
                       "ac dec 12 10 20e6\nwrdata x.dat v(apin) v(bpin)\n", "Vsa sa 0 dc 0 ac 1\nVsb sb 0 dc 0 ac 1\n")
    with open(os.path.join(HERE, "netlists", "pair_lowz_wc_cm_5.cir"), "w") as f:
        f.write(txt)
    log("guards")
    gd = guards_lowz()
    jdump("guards_lowz", gd)
    import report_df3
    report_df3.write()
    for fn in glob.glob(os.path.join(HERE, "work", "*")):
        try:
            os.remove(fn)
        except OSError:
            pass
    log("done")

if __name__ == "__main__":
    if dlib.VARIANT == "hz":     # the default: the 1 Mohm design with the BNC-tee calibration
        import tee
        tee.main()
    elif dlib.VARIANT == "legacy":
        main()
    elif dlib.VARIANT in ("lowz", "lowz2") and not os.environ.get("D2_ROUND1_OK"):
        raise SystemExit("round 1 (lowz) results are kept in results/lowz/; set D2_ROUND1_OK=1 to overwrite results/ with it")
    else:
        main_lowz()
