#!/usr/bin/env python3
"""Post-processing of results/raw_*.json, inl.json and sense.json -> results/summary.json and report.md tables.
python3 -I report.py.  Guards at the end break each DF-3 / SC-2 check on purpose and abort if one does not fire."""
import os, sys, json
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run as R

INL = json.load(open(os.path.join(HERE, "results", "inl.json")))
SEN = json.load(open(os.path.join(HERE, "results", "sense.json")))
HDR = json.load(open(os.path.join(HERE, "results", "header.json")))
GSTAGE = {"5": 1.025, "1.25": 1 + 953 / 249}
ALPHA = 0.2324

def resid(rg, tolkey, key):
    """INL ratio residual (fraction) from inl.json; 'max_code' = the worst of the shared-ADC code models."""
    r = INL["ratio"]
    if key == "max_code64":
        return max(r[f"{rg}|{tolkey}|codeL{L}|64"] for L in (1, 4, 16, 64, 256)) / 100
    if key == "max_code256":
        return max(r[f"{rg}|{tolkey}|codeL{L}|256"] for L in (1, 4, 16, 64, 256)) / 100
    return r[f"{rg}|{tolkey}|{key}"] / 100

def tee_db(o, rg, vt, rr, opamp=True):
    sA, sB = o["slopes"][str(vt)]
    return min(R.cal_tee(o["pa"], o["pb"], rg, sA, sB, o["eop"], (s * rr / 2, -s * rr / 2), opamp) for s in (1, -1))

def stage_db(o, rg, rr):
    sA, sB = o["r0_gA"] / o["alphaA"], o["r0_gB"] / o["alphaB"]
    return min(R.cal_tee(o["pa"], o["pb"], rg, sA, sB, o["eop"], (s * rr / 2, -s * rr / 2), True) for s in (1, -1))

def summarize(name):
    raw = json.load(open(os.path.join(HERE, "results", f"raw_{name}.json")))
    cor, mc = raw["corners"], raw["mc"]
    tolkey = "0.001" if name == "design" else "0.01"
    out = {}
    for rg in ("5", "1.25"):
        allp = list(cor.values()) + mc
        row = {}
        cd = [v[rg]["cmrr_dc"] for v in cor.values()]; md = [m[rg]["cmrr_dc"] for m in mc]
        row["before_dc"] = (min(cd), min(md))
        if "f10k" in mc[0][rg]:
            cf = [min(v[rg]["f10k"], v[rg]["f10k_alt"]) for v in cor.values()]; mf = [min(m[rg]["f10k"], m[rg]["f10k_alt"]) for m in mc]
            row["before_10k"] = (min(cf), min(mf))
        row["margin_mV"] = min(p[rg]["margin"] for p in allp) * 1e3
        row["sc8_offset_mV"] = max(abs(p[rg]["dos"]) for p in allp) / (ALPHA * GSTAGE[rg]) * 1e3
        row["sc8_gain_pct"] = max(abs(p[rg]["gA"] / p[rg]["gB"] - 1) for p in allp) * 100
        res = {"exact": 0.0, "pt64": resid(rg, tolkey, "pt1.2|64"), "pt256": resid(rg, tolkey, "pt1.2|256"),
               "code64": resid(rg, tolkey, "max_code64"), "code256": resid(rg, tolkey, "max_code256")}
        tee = {}
        for vt in R.VTS:
            for k, rr in res.items():
                c_ = [tee_db(v[rg], rg, vt, rr) for v in cor.values()]
                m_ = [tee_db(m[rg], rg, vt, rr) for m in mc]
                tee[f"{vt}|{k}"] = dict(corner=min(c_), mc=min(m_), mc_p1=float(np.percentile(m_, 1)), resid_pct=rr * 100,
                                        below=int(sum(x < min(c_) - 1e-9 for x in m_)))
            c_ = [tee_db(v[rg], rg, vt, res["pt64"], opamp=False) for v in cor.values()]
            tee[f"{vt}|pt64|no_opamp"] = dict(corner=min(c_), mc=min(tee_db(m[rg], rg, vt, res["pt64"], False) for m in mc))
        row["tee"] = tee
        if name == "design":
            inj = INL["ratio"][f"inj|{rg}|pt1.2|64"] / 100
            cres = 2 * {"5": 55e-6, "1.25": 62e-6}[rg]
            row["stage"] = {k: dict(corner=min(stage_db(v[rg], rg, rr) for v in cor.values()), mc=min(stage_db(m[rg], rg, rr) for m in mc), resid_pct=rr * 100)
                            for k, rr in (("exact", 0.0), ("sim/diff 55/62 ppm", cres), ("+ INL (pt, 64 points, DAC0 window)", cres + inj))}
        out[rg] = row
    return out

S = {}
for name in R.SCEN:
    if os.path.exists(os.path.join(HERE, "results", f"raw_{name}.json")):
        S[name] = summarize(name)

# ---- guards: each DF-3 / SC-2 check broken on purpose (on stored grids, no new simulation) ---------------------------
G = []
def guard(name, mutation, good, broken, fired):
    G.append(dict(check=name, mutation=mutation, good=good, broken=broken, fired=bool(fired)))
if "design" in S:
    raw = json.load(open(os.path.join(HERE, "results", "raw_design.json")))
    o = raw["corners"]["wc"]["5"]
    g = tee_db(o, "5", 1.15, 0.0)
    # 1. the tee must see the divider: calibrate with the STAGE slope only on a 1 % design corner -> must fail 44 dB
    if "1pct_tau100" in S:
        o1 = json.load(open(os.path.join(HERE, "results", "raw_1pct_tau100.json")))["corners"]["wc"]["5"]
        b = stage_db(o1, "5", 0.0); t1 = tee_db(o1, "5", 1.15, 0.0)
        guard("DF-3 after cal >= 44 dB sees the divider", "1 % divider corner calibrated by the stage only (divider not seen)", t1, b, t1 >= 44 > b)
    # 2. the residual enters the check: 0.5 % per-channel opposite residual must fail
    b2 = tee_db(o, "5", 1.15, 0.01)
    guard("DF-3 after cal >= 44 dB sees the calibration residual", "INL residual 0 -> 1 % between channels", g, b2, g >= 44 > b2)
    # 3. the slopes must be the reference-state ones: using the use-state slopes would hide all drift (too good)
    sA_u, sB_u = o["gA"], o["gB"]
    # (the DC grid's single-ended gains at the use temperature: a 'calibration' at the use temperature)
    hid = min(R.cal_tee(o["pa"], o["pb"], "5", sA_u, sB_u, o["eop"], (0, 0), False), 200)
    g_nop = tee_db(o, "5", 1.15, 0.0, opamp=False)
    guard("drift since calibration is in the check", "calibrate at the use temperature instead of the reference", g_nop, hid, hid > g_nop + 6)
if "1pct_tau200" in S and "design" in S:
    m1, m0 = S["1pct_tau200"]["1.25"]["margin_mV"], S["design"]["1.25"]["margin_mV"]
    # this guard DID NOT FIRE on its first run: the DF-3 corner set cannot see the SC-11 margin corner (sc2.py). Kept as
    # a record and inverted: it must keep reporting that the DF-3 corners pass the 1 % divider, so nobody reads them as SC-2
    guard("(record) DF-3 corners are blind to SC-11's margin corner", "divider 0.1 % -> 1 %: the corner set still passes", m0, m1, m1 >= 80)
json.dump(dict(summary=S, guards=G), open(os.path.join(HERE, "results", "summary.json"), "w"), indent=1)
print(json.dumps(dict(summary=S, guards=G), indent=1))
if not all(x["fired"] for x in G):
    raise SystemExit("a guard did not fire")
