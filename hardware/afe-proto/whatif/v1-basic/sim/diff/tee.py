#!/usr/bin/env python3
"""2d for the default variant 'hz' (1 Mohm compensated divider, BNC-tee calibration, 2026-11-11).
    python3 -I tee.py        (D2_WORKERS ngspice processes, default 4)  -> results/*.json, report.md

Folded in from whatif/tee (its run.py and sc2.py, which were built on this directory's code):
 * the calibration is the BNC tee: both inputs driven together from the AWG over +-1 V at the reference temperature; each
   channel's whole input->pin slope (divider and stage) is fitted, and at dT = +-10 K each pin is divided by its own slope;
   the slope's error from the Due's INL is an opposite-sign residual per channel, taken from whatif/tee/results/inl.json
   (model 'pt', 1.2 LSB, 64 points: 0.200 % of ratio on +-5 V, 0.042 % on +-1.25 V, sha256 827a106800af9146...);
 * SC-2 / SC-11 by an explicit corner SEARCH (every sign of R1/R2/R3, centring, Vos, both Ron ends), because the DF-3
   corner set ties the Vos sign to the centring sign and so misses the margin's worst case; its guard restricts the
   search to the tied set on a 1 % divider and must find it at least 10 mV optimistic.
Hardware differential mode (SM-6) is held to the before-calibration figures."""
import os, sys, json, time, itertools
import numpy as np
from concurrent.futures import ProcessPoolExecutor
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import dlib, core2d as c

TAG = os.environ.get("V1B_TAG", "")             # v1-basic: results_<TAG>/ and report_<TAG>.md
RES = os.path.join(HERE, "results" + ("_" + TAG if TAG else "")); os.makedirs(RES, exist_ok=True)
NMC = int(os.environ.get("D2_NMC", "200")); WORKERS = int(os.environ.get("D2_WORKERS", "4")); SEED = 20261111
VT = 1.0                                       # the AWG at the tee, +-1.0 V (AW-1)
RCAB = (0.10, 0.12)                            # tee arm + cable + contacts, ohm, A / B *(check)*
RR = {"5": 0.20049528652034473e-2, "1.25": 0.04181755456737798e-2}   # INL ratio residual, whatif/tee/results/inl.json
SC = dict(c.SPEC, name="hz")
T0 = time.time()
NBAD = []

def log(*a):
    print(f"[{time.time()-T0:6.0f}s]", *a, flush=True)

def jdump(name, obj):
    conv = lambda o: o.item() if isinstance(o, (np.floating, np.integer)) else (o.tolist() if isinstance(o, np.ndarray) else str(o))
    json.dump(obj, open(os.path.join(RES, name + ".json"), "w"), indent=1, default=conv)

def tee_slopes(name, d_ref, rg):
    st = 2 * VT / 10
    d = dict(d_ref); d["Rsa"], d["Rsb"] = RCAB
    for k in range(3):   # the vendor model's sweep occasionally fails to converge (once in ~800 here); retry with a shifted start
        try:
            v, pa, pb, _, _ = dlib.cm_sweep(f"{name}_{k}", d, rg, -VT - st * (1 + 0.1 * k), VT + st / 2, st)
            break
        except (FileNotFoundError, OSError, ValueError):
            if k == 2:
                raise
    v, pa, pb = v[1:], pa[1:], pb[1:]          # first point of a sweep dropped (whatif/tee: one wrong first operating point in 1000)
    out = []
    for p in (pa, pb):
        k = np.polyfit(v, p, 1)
        if np.max(np.abs(np.polyval(k, v) - p)) > 2e-3:
            raise RuntimeError(f"{name}: tee sweep not linear")
        out.append(float(k[0]))
    return out

def cal_tee(pa, pb, rg, sA, sB, eop, e=(0.0, 0.0)):
    V = c.grid(rg)[-1]
    d = np.asarray(pa) / (sA * (1 + e[0])) - np.asarray(pb) / (sB * (1 + e[1]))
    adm = (d[-1, 0] - d[0, -1]) / (4 * V); acm = (d[-1, -1] - d[0, 0]) / (2 * V)
    ea, eb = eop
    return min(20 * np.log10(abs(adm) / max(abs(acm + sg * adm * (ea - eb)), 1e-12)) for sg in (1, -1))

def run_pair(tag, d_use, d_ref):
    out = {}
    for rg in ("5", "1.25"):
        r1 = c.eval_range(f"{tag}_u_{rg}", d_use, rg, with_ac=True)
        sA, sB = tee_slopes(f"{tag}_t_{rg}", d_ref, rg)
        E = RR[rg]
        out[rg] = dict(before_dc=r1["cmrr_dc"], before_10k=min(c.at_f(r1["f"], r1["cmrr_f"], 1e4), c.at_f(r1["f"], r1["cmrr_f_alt"], 1e4)),
                       tee_exact=cal_tee(r1["_pa"], r1["_pb"], rg, sA, sB, d_use["eop"]),
                       tee=min(cal_tee(r1["_pa"], r1["_pb"], rg, sA, sB, d_use["eop"], (s * E / 2, -s * E / 2)) for s in (1, -1)),
                       tee_1pct=min(cal_tee(r1["_pa"], r1["_pb"], rg, sA, sB, d_use["eop"], (s * 0.005, -s * 0.005)) for s in (1, -1)),
                       gA=r1["gA"], gB=r1["gB"], margin=r1["margin"])
    return out

def mc_job(i):
    rng = np.random.default_rng([SEED, i]); d = c.mc_draw(rng, SC)
    try:
        return run_pair(f"mc{i}", c.at_T(d), c.at_T(c.at_ref(d)))
    except RuntimeError as e:   # v1-basic: a tee sweep the vendor model makes non-linear (a few-mV kink) drops the draw, counted
        print("dropped draw", i, e, flush=True)
        return None

def corner_job(key):
    return key, run_pair(key, c.at_T(c.corner_set(SC)[key]), c.at_T(c.corner_draw(SC, dT=0.0, name=key + "_ref", **c.ref_kw(key))))

# ---- SC-2 / SC-11 corner search (whatif/tee/sc2.py) -------------------------------------------------------------------
SC2_CASES = {"0.1 %, 25 ppm/K (design)": (1e-3, 25e-6), "1 %, 100 ppm/K (guard)": (1e-2, 100e-6)}   # both run on the stage values in V1B_RF / V1B_RG

def sc2_job(a):
    lab, s1, s2, s3, sc_, sv, ron, rg = a
    tol, tc = SC2_CASES[lab]; t = tol + tc * c.DT
    base = c.corner_draw(SC, name="sc2"); ch = dict(base["A"])
    ch.update(R1=c.NOM["R1"] * (1 + s1 * t), R2=c.NOM["R2"] * (1 + s2 * t), R3=c.NOM["R3"] * (1 + s3 * t),
              RF=c.NOM["RF"] * (1 + t), RG=c.NOM["RG"] * (1 - t),   # v1-basic: the stage at the case's own tolerance (was 0.1 % + 25 ppm/K x dT in both cases)
              Ron=ron, vos=sv * (c.VOS_MAX + c.VOS_TC * c.DT), eC1=0.0, eC2=0.0, stray=0.0)
    d = dict(base, A=ch, B=dict(ch), Rsa=0.0, Rsb=0.0, sh=dict(aref=3.20, cent=sc_ * c.CENT, vcc=3.23))
    r = c.eval_range(f"sc2_{abs(hash(a))}", d, rg, with_ac=False)
    return a, r["margin"]

def sc2(ex):
    jobs = [(lab, s1, s2, s3, sc_, sv, ron, rg) for lab in SC2_CASES for s1, s2, s3 in itertools.product((1, -1), repeat=3)
            for sc_ in (1, -1) for sv in (1, -1) for ron in (3.7, 8.8) for rg in ("5", "1.25")]
    res = list(ex.map(sc2_job, jobs, chunksize=8))
    out = {}
    for lab in SC2_CASES:
        for rg in ("5", "1.25"):
            rows = [x for x in res if x[0][0] == lab and x[0][7] == rg]
            w = min(rows, key=lambda x: x[1])
            tied = min(x[1] for x in rows if x[0][4] == x[0][5] and (x[0][1], x[0][2], x[0][3]) in ((-1, 1, 1), (1, -1, -1)))
            out[f"{lab}|{rg}"] = dict(margin_mV=w[1] * 1e3, at=dict(zip(("R1", "R2", "R3", "cent", "vos", "Ron"), w[0][1:7])), tied_set_mV=tied * 1e3)
    g = out["1 %, 100 ppm/K (guard)|1.25"]
    out["guard"] = dict(check="the search finds SC-11's margin corner", mutation="restrict to the DF-3 corner set (Vos tied to centring)",
                        good=g["margin_mV"], broken=g["tied_set_mV"], fired=bool(g["tied_set_mV"] - g["margin_mV"] > 10))
    return out

def main():
    log("variant", dlib.VARIANT, "NOM", c.NOM, "C2", dlib.BASE["C2"], "inj", dlib.BASE.get("inj"))
    with ProcessPoolExecutor(WORKERS) as ex:
        s2 = sc2(ex); jdump("sc2", s2); log("sc2", s2["guard"])
        cor = dict(ex.map(corner_job, list(c.HOTKW)))
        mc = list(ex.map(mc_job, range(NMC), chunksize=4))
    ndrop = sum(m is None for m in mc); mc = [m for m in mc if m is not None]; log("MC draws dropped (tee sweep not linear):", ndrop)
    # v1-basic: a draw whose gain grid the vendor model broke (a non-converged sweep: one channel's slope off by more than 15 %
    # of the nominal pair's, which no 1 % tolerance can do) is dropped and counted, so SC-8 is not read off a solver failure
    g0 = {rg: 0.5 * (cor["wc"][rg]["gA"] + cor["wc"][rg]["gB"]) for rg in ("5", "1.25")}
    bad = [i for i, m in enumerate(mc) if any(abs(m[rg][k] / g0[rg] - 1) > 0.15 for rg in ("5", "1.25") for k in ("gA", "gB"))]
    mc = [m for i, m in enumerate(mc) if i not in bad]; log("MC draws dropped (gain grid broken):", len(bad)); NBAD.append(len(bad) + ndrop)
    jdump("raw_tee", dict(corners=cor, mc=mc))
    S = {}
    for rg in ("5", "1.25"):
        row = {}
        for k in ("before_dc", "before_10k", "tee_exact", "tee", "tee_1pct"):
            cv = [v[rg][k] for v in cor.values()]; mv = [m[rg][k] for m in mc]
            row[k] = dict(corner=min(cv), mc=min(mv), p1=float(np.percentile(mv, 1)), med=float(np.median(mv)), below=int(sum(x < min(cv) - 1e-9 for x in mv)))
        row["sc8_gain_pct"] = max(abs(p[rg]["gA"] / p[rg]["gB"] - 1) for p in list(cor.values()) + mc) * 100
        S[rg] = row
    # guard: the residual enters the check (0.5 % per channel opposite must fail 44 dB)
    S["guard"] = dict(check="DF-3 after the tee calibration >= 44 dB sees the residual", mutation="INL residual -> 0.5 % per channel, opposite",
                      good=min(S[r]["tee"]["corner"] for r in ("5", "1.25")), broken=min(S[r]["tee_1pct"]["corner"] for r in ("5", "1.25")))
    S["guard"]["fired"] = bool(S["guard"]["good"] >= 44 > S["guard"]["broken"])
    S["nmc"] = len(mc)
    jdump("tee_summary", S)
    write_report(S, s2)
    for fn in os.listdir(os.path.join(HERE, dlib.WORKSUB)):
        try:
            os.remove(os.path.join(HERE, dlib.WORKSUB, fn))
        except OSError:
            pass
    log("done")

def write_report(S, s2):
    L = []; A = L.append
    A("# 2d differential mode: DF-3 for the 1 Mohm design with the BNC-tee calibration (2026-11-11)\n")
    A("Regenerated by `python3 -I tee.py` (variant `hz`, the default). The superseded runs: `report_legacy.md` (1 Mohm, first round, `D2_VARIANT=legacy python3 -I run.py`), `report_round1.md` / `results/lowz/` and `results/lowz2/` (route (c), `run.py`).\n")
    A(f"- Pair: sim/scope `hz` channels (R1 = R3 760k, R2 330k, C1 12 pF, C2 {dlib.BASE['C2']*1e12:.1f} pF, Rnp 680, OPA354, RF {c.NOM["RF"]:.1f} / RG {c.NOM["RG"]:.0f} with the range switch across RF, per-channel Vmid P8-k); no injection switch on N. {c.SPEC["tolR"]*100:g} % at {c.SPEC["tcr"]:g} ppm/K for every resistor, capacitors +/-5 %, stray +/-0.5 pF, Ron 3.7-8.8 ohm per channel, dT +/-{c.DT:g} K, {NMC} Monte Carlo draws and {len(c.HOTKW)} signed corners. **Sources matched** (owner): both <= 100 ohm, within 10 ohm.")
    A(f"- Calibration: the BNC tee, +/-{VT:.1f} V from the AWG into both inputs, each channel's whole slope fitted at the reference; INL residual {RR['5']*100:.3f} % (+/-5 V) / {RR['1.25']*100:.3f} % (+/-1.25 V) of ratio, half to each channel, opposite signs (whatif/tee). Tee arm + cable {RCAB[0]} / {RCAB[1]} ohm *(check)*.\n")
    A("| row | range | limit | worst signed corner | Monte Carlo min / 1st pct / median | verdict | margin |\n|---|---|---|---|---|---|---|")
    for rg, nm in (("5", "+/-5 V"), ("1.25", "+/-1.25 V")):
        r = S[rg]
        for k, lab, lim in (("before_dc", "DF-3 before calibration, DC (SM-6's figure)", 30), ("before_10k", "DF-3 before calibration, 10 kHz", 18),
                            ("tee", "DF-3 after the tee calibration (INL residual)", 44), ("tee_exact", "the same, exact (no residual), reference", 44)):
            x = r[k]
            A(f"| {lab} | {nm} | >= {lim} dB | {x['corner']:.1f} dB | {x['mc']:.1f} / {x['p1']:.1f} / {x['med']:.1f} | {'PASS' if min(x['corner'], x['mc']) >= lim else 'FAIL'} | {x['corner']-lim:+.1f} dB |")
    nb = sum(S[rg][k]["below"] for rg in ("5", "1.25") for k in ("before_dc", "tee", "tee_exact"))
    A(f"\nMonte Carlo draws kept: {S['nmc']} of {NMC} (a draw whose tee sweep the vendor model makes non-linear, or whose gain grid it breaks, is dropped, v1-basic). Monte Carlo draws below their signed corner: {nb} (must be 0). SC-8 gain match over all pairs: {S['5']['sc8_gain_pct']:.2f} % (+/-5 V), {S['1.25']['sc8_gain_pct']:.2f} % (+/-1.25 V), limit 3 %.\n")
    A("## SC-2 / SC-11 corner search (folded in from whatif/tee/sc2.py)\n")
    A("| divider | range | worst margin (search) | at (R1, R2, R3, centring, Vos, Ron) | DF-3 corner set alone |\n|---|---|---|---|---|")
    for k, v in s2.items():
        if k == "guard":
            continue
        lab, rg = k.split("|")
        A(f"| {lab} | +/-{rg} V | {v['margin_mV']:.1f} mV | {v['at']} | {v['tied_set_mV']:.1f} mV |")
    A("\n## Guards\n")
    A("| check | mutation | good | broken | fired |\n|---|---|---|---|---|")
    for g in (s2["guard"], S["guard"]):
        A(f"| {g['check']} | {g['mutation']} | {g['good']:.1f} | {g['broken']:.1f} | {'yes' if g['fired'] else 'NO'} |")
    open(os.path.join(HERE, "report" + ("_" + TAG if TAG else "") + ".md"), "w").write("\n".join(L) + "\n")

if __name__ == "__main__":
    main()
