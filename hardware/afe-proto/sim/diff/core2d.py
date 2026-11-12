"""Draws, evaluation and analysis for 2d (differential mode).  Imported by run.py."""
import numpy as np
import dlib

# ---- limits quoted from docs/afe.md (section numbers in the report) ----------------------------
AREF_LO, AREF_HI = 3.20, 3.30
CENT = 0.030                 # Vmid centring error, SC-2
VCC_LO, VCC_HI = 3.23, 3.37  # op-amp rail, as 2b
VOS_MAX = 8e-3               # OPA354 datasheet max, 25 C, 5 V supply (models/datasheet-facts.md p7)
VOS_TC = 4e-6                # V/K, OPA354 drift +-4 uV/C (datasheet-facts.md p7) *(check typ or max)*
CMRR_OP_DB = 68.0            # OPA354 CMRR above (V+)-2 V, datasheet-facts.md p7 *(check: typ or min)*
DT = 10.0                    # K, EN-1 15-35 C about a 25 C reference
if dlib.VARIANT == "hz":   # the 1 Mohm design of the 2026-11-11 pivot: 760k / 330k / 760k
    NOM = dict(R1=dlib.BASE["R1"], R2=dlib.BASE["R2"], R3=dlib.BASE["R3"], RF=953.0, RG=249.0, Rt=0.0)
    RKEYS = ("R1", "R2", "R3", "RF", "RG")
elif dlib.UNC:   # the 2026-11-11 low-impedance divider: R3's leg is the network plus the per-channel 249R sense resistor
    NOM = dict(R1=dlib.BASE["R1"], R2=dlib.BASE["R2"], R3=dlib.BASE["R3"], Rs3=dlib.BASE["Rs3"], RF=953.0, RG=249.0, Rt=0.0)
    RKEYS = ("R1", "R2", "R3", "Rs3", "RF", "RG")
else:
    NOM = dict(R1=768e3, R2=330e3, R3=768e3, RF=953.0, RG=249.0, Rt=0.0)   # R2 is the FIXED 330k; Rt is the trimmer in series with it
    RKEYS = ("R1", "R2", "R3", "RF", "RG")
# PA-3 calibration residuals (2026-11-11): the MCP3564 reading DAC0 with 1e5 samples per point, 55 ppm (+/-5 V) and
# 62 ppm (+/-1.25 V) of stage gain (whatif/results-2026-11-11.md D), per channel, signs opposite (worst case), both signs taken
CAL_RES = {"5": 55e-6, "1.25": 62e-6}
MATCHED_SOURCES = dlib.VARIANT in ("lowz2", "hz")
RS_CORNER = (0.0, 10.0) if MATCHED_SOURCES else (0.0, 100.0)   # the signed corner's sources (A gain-high gets the lower)
RON_INJ = (3.7, 8.8)          # the injection switch's Ron (TMUX1119 typ / max at 3.3 V); the host corrects with the mid value
RT_NOM, RT_MAX = 5e3, 10e3   # 10 kohm SMD cermet trimmer, 5 kohm mid-setting, wiper 0..10k
RT_TC = 100e-6               # 1/K, trimmer tempco *(check: datasheet of the actual part not read)*
RON_TC = 1e-3                # 1/K: Ron drifts 1 % over 10 K *(check: TMUX1119 Ron-vs-temperature curve not read)*
TRIM_RES = 5e-4              # assumed residual of the one-time trim, in relative divider ratio *(check)*
RT_PROBE = 2e3               # ohm, step for the trim's numerical sensitivity

def nom_of(sc):
    n = dict(NOM)
    n["Rt"] = RT_NOM if sc.get("trimmer") else 0.0
    return n
RANGE_V = {"5": 6.0, "1.25": 1.25}      # input extreme used for the grids
NGRID = 9
F_PTS = None

SPEC = dict(name="spec", tolR=0.001, tolC=0.05, stray=0.5e-12, ron_lo=3.7, ron_hi=8.8, dron=None, tcr=25.0, trim=None)

def grid(rng_):
    v = RANGE_V[rng_]
    return list(np.linspace(-v, v, NGRID))

# ------------------------------------------------------------------------------------------------
def chan_nominal(sc):
    d = dict(nom_of(sc))
    d.update(eC1=0.0, eC2=0.0, stray=0.0, Ron=sc["ron_lo"], vos=0.0, tc=dict(R1=0, R2=0, R3=0, RF=0, RG=0), tcv=0.0)
    return d

def mc_draw(rng, sc):
    u = lambda t: rng.uniform(-t, t)
    nom = nom_of(sc)
    def ch(ron):
        d = {k: nom[k] * (1 + u(sc["tolR"])) for k in RKEYS}
        d["Rt"] = nom["Rt"]                       # the trimmer carries no tolerance: it is set, not specified
        tc = {k: u(sc["tcr"]) * 1e-6 for k in RKEYS}
        tc["Rt"] = u(RT_TC)
        d.update(eC1=u(sc["trim"] if sc.get("trim") else sc["tolC"]), eC2=u(sc["tolC"]), stray=u(sc["stray"]), Ron=ron, vos=u(VOS_MAX),
                 trim=bool(sc.get("trim")), leg_nom=nom["R2"] + nom["Rt"],
                 tc=tc, tcv=u(VOS_TC), tcron=u(RON_TC))
        if dlib.UNC:   # drawn last, so that the legacy variant's random stream is unchanged
            d["Roninj"] = rng.uniform(*RON_INJ)
        return d
    ra = rng.uniform(sc["ron_lo"], sc["ron_hi"])
    rb = rng.uniform(sc["ron_lo"], sc["ron_hi"])
    if sc["dron"] is not None:
        rb = float(np.clip(ra + u(sc["dron"]), sc["ron_lo"], sc["ron_hi"]))
    rsa, rsb = rng.uniform(0, 100), rng.uniform(0, 100)
    if MATCHED_SOURCES:   # owner 2026-11-11: DF-3 holds for sources both <= 100 ohm and within 10 ohm of each other
        rsb = float(np.clip(rsa + (rsb / 100 * 2 - 1) * 10.0, 0.0, 100.0))
    return dict(A=ch(ra), B=ch(rb),
                sh=dict(aref=rng.uniform(AREF_LO, AREF_HI), cent=u(CENT), vcc=rng.uniform(VCC_LO, VCC_HI)),
                Rsa=rsa, Rsb=rsb, dT=u(DT),
                eop=(u(1 / 10 ** (CMRR_OP_DB / 20)), u(1 / 10 ** (CMRR_OP_DB / 20))), kind="mc")

def corner_draw(sc, s=+1, cs=+1, rs=None, vs=+1, cent=+1, aref=AREF_LO, dT=DT, vcc=VCC_LO, sops=+1, name="wc", rt=None):
    """Signed worst case: channel A is gain-high (s=+1), B gain-low.  Every resistor at its tolerance plus the
    tempco over dT, capacitors at their tolerance (cs=-1 flips the cap direction relative to the resistors),
    Ron at the ends of its range (or dron apart), Vos at the datasheet maximum."""
    rs = RS_CORNER if rs is None else rs
    tR = sc["tolR"] + sc["tcr"] * 1e-6 * dT
    nom = nom_of(sc)
    rtv = rt if rt is not None else (nom["Rt"], nom["Rt"])
    def ch(sg, ron):
        rti = rtv[0] if sg == s else rtv[1]
        extra = dict(Rs3=nom["Rs3"] * (1 + sg * tR)) if "Rs3" in nom else {}
        return dict(R1=nom["R1"] * (1 - sg * tR), R2=nom["R2"] * (1 + sg * tR), R3=nom["R3"] * (1 + sg * tR), **extra,
                    Roninj=RON_INJ[1] if sg > 0 else RON_INJ[0],
                    RF=nom["RF"] * (1 + sg * tR), RG=nom["RG"] * (1 - sg * tR),
                    Rt=rti * (1 + sg * RT_TC * dT), leg_nom=nom["R2"] + nom["Rt"], tcron=sg * RON_TC, csys=sc.get("csys", 0.0),
                    eC1=sg * cs * (sc["trim"] if sc.get("trim") else sc["tolC"]), eC2=-sg * cs * sc["tolC"],
                    stray=-sg * cs * sc["stray"], trim=bool(sc.get("trim")),
                    Ron=ron, vos=sg * vs * VOS_MAX + sg * vs * VOS_TC * dT, tc=None, tcv=0.0)
    if sc["dron"] is None:
        ra, rb = sc["ron_hi"], sc["ron_lo"]
    else:
        ra, rb = sc["ron_hi"], sc["ron_hi"] - sc["dron"]
    e = 1 / 10 ** (CMRR_OP_DB / 20)
    return dict(A=ch(s, ra if s > 0 else rb), B=ch(-s, rb if s > 0 else ra),
                sh=dict(aref=aref, cent=cent * CENT, vcc=vcc), Rsa=rs[0], Rsb=rs[1], dT=dT,
                eop=(sops * e, -sops * e), kind=name)

def at_T(draw):
    """Fold a draw's tempcos at its own dT into the part values (corners already carry them)."""
    d = dict(draw, A=dict(draw["A"]), B=dict(draw["B"]))
    for k in ("A", "B"):
        c = d[k]
        if c.get("tc"):
            for r in c["tc"]:
                c[r] = c[r] * (1 + c["tc"][r] * draw["dT"])
            c["vos"] = c["vos"] + c["tcv"] * draw["dT"]
        if c.get("tcron"):
            c["Ron"] = c["Ron"] * (1 + c["tcron"] * draw["dT"])
    return d

def at_ref(draw):
    """The same draw at the calibration reference (dT = 0)."""
    d = dict(draw, A=dict(draw["A"]), B=dict(draw["B"]), dT=0.0)
    return d

# ------------------------------------------------------------------------------------------------
def eval_range(name, draw, rng_, with_ac=True, sub="work"):
    """All ngspice work for one draw and one range.  `draw` must already be folded to its temperature."""
    g = grid(rng_)
    pa, pb, oa, ob = dlib.dc_grid(name + "_dc", draw, rng_, g, sub)
    n = len(g); V = g[-1]
    d = pa - pb
    i0 = n // 2
    adm = (d[-1, 0] - d[0, -1]) / (4 * V)
    acm_sim = (d[-1, -1] - d[0, 0]) / (2 * V)
    ea, eb = draw["eop"]
    acm = acm_sim + adm * (ea - eb)
    gA = (pa[-1, i0] - pa[0, i0]) / (2 * V)
    gB = (pb[i0, -1] - pb[i0, 0]) / (2 * V)
    r = dict(adm=adm, acm_sim=acm_sim, acm=acm, cmrr_dc=20 * np.log10(abs(adm) / max(abs(acm), 1e-12)),
             gA=gA, gB=gB, dos=d[i0, i0], pa0=pa[i0, i0], pb0=pb[i0, i0],
             pin_min=float(min(pa.min(), pb.min())), pin_max=float(max(pa.max(), pb.max())),
             out_max=float(max(oa.max(), ob.max())),
             aref=draw["sh"]["aref"])
    r["margin"] = float(min(r["pin_min"], draw["sh"]["aref"] - r["pin_max"]))
    r["_pa"], r["_pb"] = pa, pb
    if with_ac:
        f, a1, b1 = dlib.ac_pair(name + "_cm", draw, rng_, "cm")
        f, a2, b2 = dlib.ac_pair(name + "_dm", draw, rng_, "dm")
        Acm, Adm = a1 - b1, a2 - b2
        Acm_t = Acm + Adm * (ea - eb)
        r["f"] = f
        r["cmrr_f"] = 20 * np.log10(np.abs(Adm) / np.maximum(np.abs(Acm_t), 1e-15))
        # the opposite sign of the op-amp term, for corners that must take the worse of both
        Acm_u = Acm - Adm * (ea - eb)
        r["cmrr_f_alt"] = 20 * np.log10(np.abs(Adm) / np.maximum(np.abs(Acm_u), 1e-15))
        r["adm_f"] = np.abs(Adm)
    return r

def at_f(f, y, f0):
    return float(np.interp(np.log10(f0), np.log10(f), y))

def summarize_scenario(sc, mc, corners, ranges=("5", "1.25")):
    """mc: list of per-draw dicts {rng: result}; corners: {name: {rng: result}}."""
    out = {}
    for rg in ranges:
        rows = [m[rg] for m in mc]
        cr = {k: v[rg] for k, v in corners.items() if k != "nominal"}
        f = rows[0]["f"]
        mcmrr = np.array([r["cmrr_f"] for r in rows])
        ccm = {k: np.minimum(v["cmrr_f"], v["cmrr_f_alt"]) for k, v in cr.items()}
        wc_f = np.min(np.array(list(ccm.values())), axis=0)
        out[rg] = dict(
            f=f.tolist(),
            mc_cmrr_min=mcmrr.min(axis=0).tolist(), mc_cmrr_p1=np.percentile(mcmrr, 1, axis=0).tolist(),
            mc_cmrr_med=np.median(mcmrr, axis=0).tolist(),
            wc_cmrr=wc_f.tolist(),
            corner_cmrr={k: v.tolist() for k, v in ccm.items()},
            dc_mc_min=float(min(r["cmrr_dc"] for r in rows)), dc_mc_med=float(np.median([r["cmrr_dc"] for r in rows])),
            dc_corner={k: float(v["cmrr_dc"]) for k, v in cr.items()},
            dc_corner_min=float(min(v["cmrr_dc"] for v in cr.values())),
            f10k_mc_min=at_f(f, mcmrr.min(axis=0), 1e4), f10k_mc_p1=at_f(f, np.percentile(mcmrr, 1, axis=0), 1e4),
            f10k_wc=at_f(f, wc_f, 1e4),
            f10k_corner={k: at_f(f, v, 1e4) for k, v in ccm.items()},
            n=len(rows),
            margin_min=float(min([r["margin"] for r in rows] + [v["margin"] for v in cr.values()])),
            adm_min=float(min([r["adm"] for r in rows] + [v["adm"] for v in cr.values()])),
            adm_max=float(max([r["adm"] for r in rows] + [v["adm"] for v in cr.values()])),
            dos_max=float(max(abs(r["dos"]) for r in rows)),
            out_max=float(max(r["out_max"] for r in rows)),
            mc_exceeds_corner_dc=int(sum(1 for r in rows if r["cmrr_dc"] < min(v["cmrr_dc"] for v in cr.values()) - 1e-9)),
            mc_exceeds_corner_10k=int(sum(1 for r in rows if at_f(f, r["cmrr_f"], 1e4) < out_min10(ccm, f) - 1e-9)),
            pass_dc=bool(min(r["cmrr_dc"] for r in rows) >= 46 and min(v["cmrr_dc"] for v in cr.values()) >= 46),
            cal_mc_min=float(min(r["cal"]["dc"] for r in rows)), cal_mc_p1=float(np.percentile([r["cal"]["dc"] for r in rows], 1)),
            cal_mc_med=float(np.median([r["cal"]["dc"] for r in rows])),
            cal_ref_mc_min=float(min(r["cal"]["ref"] for r in rows)), cal_ref_mc_med=float(np.median([r["cal"]["ref"] for r in rows])),
            cal_corner={k: float(calw(v["cal"], "dc", sc)) for k, v in cr.items()},
            cal_corner_min=float(min(calw(v["cal"], "dc", sc) for v in cr.values())),
            cal_ref_corner_min=float(min(calw(v["cal"], "ref", sc) for v in cr.values())),
        )
    return out

def calw(cal, key, sc):
    """The calibrated figure of a corner.  Untrimmed, the op-amp's CM error has no known sign, so the worse of the two is
    taken.  Trimmed, the build trim nulls whatever the unit's total common-mode response was at 25 C INCLUDING that term
    (the stimulus cannot tell them apart), so the sign is the unit's and the other sign is a different unit."""
    if sc.get("trimmer"):
        return cal[key]
    return min(cal[key], cal[key + "_alt"])

def out_min10(ccm, f):
    return min(at_f(f, v, 1e4) for v in ccm.values())

HOTKW = dict(wc=dict(), wc_capflip=dict(cs=-1), wc_Rsswap=dict(rs=RS_CORNER[::-1]), wc_cold=dict(dT=-DT), pin_bot=dict(vs=-1, cent=-1))
if MATCHED_SOURCES:
    HOTKW["wc_hiZ"] = dict(rs=(90.0, 100.0))

def corner_set(sc, rts=None):
    """The signed corners at their temperature.  rts: {corner: (RtA, RtB)} the trimmer settings found at the reference."""
    return {k: corner_draw(sc, name=k, rt=(rts or {}).get(k), **kw) for k, kw in HOTKW.items()}

def ref_kw(key):
    kw = dict(HOTKW[key]); kw.pop("dT", None)
    return kw

# ---- calibrated CMRR (PA-3): the host fits each channel's STAGE gain from a source at node N, after the divider --------------
def alpha_dc(ch, rs):
    """DC divider ratio N/Vin of one channel (R1 + source resistance in series), resistors as in the draw."""
    r2 = ch["R2"] + ch.get("Rt", 0.0)
    r3 = ch["R3"] + ch.get("Rs3", 0.0) + (ch.get("Roninj", 6.25) if dlib.BASE.get("inj") == "R3" else 0.0)
    r23 = r2 * r3 / (r2 + r3)
    return r23 / (ch["R1"] + rs + r23)

def beta_r3(ch, rs):
    """Proposal 'R3' injection: DC ratio N/V(DAC0) with DAC0 driving the R3 leg through the switch (the sense
    resistor is out of the path during the calibration), the BNC source at 0 V."""
    # option (b): the MCP reads the switch's D node, i.e. R3's own end: neither Ron nor the source resistance is in beta
    g1 = 1 / (ch["R1"] + rs); g2 = 1 / (ch["R2"] + ch.get("Rt", 0.0)); g3 = 1 / ch["R3"]
    return g3 / (g1 + g2 + g3)

def rth_of(ch, rs):
    g1 = 1 / (ch["R1"] + rs); g2 = 1 / (ch["R2"] + ch.get("Rt", 0.0))
    g3 = 1 / (ch["R3"] + ch.get("Rs3", 0.0) + (ch.get("Roninj", 6.25) if dlib.BASE.get("inj") == "R3" else 0.0))
    return 1 / (g1 + g2 + g3)

def cal_cmrr(r0, r1, d0, rng_, e=(0.0, 0.0), mode="N"):
    """DC CMRR after the PA-3 gain calibration.  r0 = grid at the calibration state (dT = 0, draw d0), r1 = grid at use.
    Stage gain of each channel s = (input->pin gain at calibration) / (divider ratio): what an injection at N measures.
    Each reading is divided by its s, so the stage drops out at the calibration temperature and the divider ratio does not.
    Returns (cmrr_dB with the op-amp CM term as drawn, with the opposite sign, the common-mode mismatch as a fraction)."""
    g = grid(rng_); V = g[-1]
    if mode == "R3":   # what an injection through the R3 leg measures: the whole channel scaled by beta/alpha
        sA = r0["gA"] / alpha_dc(d0["A"], d0["Rsa"]) * beta_r3(d0["A"], d0["Rsa"]) * (1 + e[0])
        sB = r0["gB"] / alpha_dc(d0["B"], d0["Rsb"]) * beta_r3(d0["B"], d0["Rsb"]) * (1 + e[1])
    else:
        sA = r0["gA"] / alpha_dc(d0["A"], d0["Rsa"]) * (1 + e[0])
        sB = r0["gB"] / alpha_dc(d0["B"], d0["Rsb"]) * (1 + e[1])
    d = r1["_pa"] / sA - r1["_pb"] / sB
    adm = (d[-1, 0] - d[0, -1]) / (4 * V)
    acm = (d[-1, -1] - d[0, 0]) / (2 * V)
    ea, eb = d0["eop"]
    out = []
    for sg in (+1, -1):
        a = acm + sg * adm * (ea - eb)
        out.append(20 * np.log10(abs(adm) / max(abs(a), 1e-12)))
    return out[0], out[1], acm / adm

def mismatch_ref(draw_ref, rng_, mode, name, sub="work"):
    """Relative CM mismatch (acm/adm) of a draw at the reference state, for the trim: 'cal' = the calibrated reading
    (what the PA-3 fit leaves), 'raw' = the uncalibrated reading."""
    r = eval_range(name, draw_ref, rng_, with_ac=False, sub=sub)
    if mode == "cal":
        return cal_cmrr(r, r, draw_ref, rng_)[2] + (draw_ref["eop"][0] - draw_ref["eop"][1])
    return r["acm"] / r["adm"]

def with_rt(draw, rtA, rtB):
    d = dict(draw, A=dict(draw["A"]), B=dict(draw["B"]))
    d["A"]["Rt"], d["B"]["Rt"] = rtA, rtB
    return d

def trim_solve(sc, d_ref, name, eps, rng_="5", sub="work"):
    """The one-time build trim.  d_ref is the draw folded at the reference (dT = 0).  A common-mode stimulus of +-6 V is
    applied to both inputs on the +-5 V range and the two trimmers are moved until the (calibrated or raw, sc['trimmer'])
    reading is nulled; then the assumed setting residual eps (|eps| <= sc['trim_res'], default TRIM_RES, in relative divider
    ratio: drawn uniform for a Monte Carlo draw, the signed worst case for a corner) is added.  Two runs give the sensitivity; the response is linear to well under the residual.
    Returns (RtA, RtB, info)."""
    mode = sc["trimmer"]
    m0 = mismatch_ref(with_rt(d_ref, RT_NOM, RT_NOM), rng_, mode, name + "_t0", sub)
    m1 = mismatch_ref(with_rt(d_ref, RT_NOM + RT_PROBE, RT_NOM), rng_, mode, name + "_t1", sub)
    k = (m1 - m0) / RT_PROBE                      # mismatch per ohm of RtA (RtB acts with the opposite sign)
    x = (-m0 + eps) / k                           # required RtA - RtB
    dA = float(np.clip(x, -RT_NOM, RT_NOM))
    dB = -(x - dA)
    sat = abs(dB) > RT_NOM + 1e-9
    dB = float(np.clip(dB, -RT_NOM, RT_NOM))
    return RT_NOM + dA, RT_NOM + dB, dict(m0=m0, k=k, x=x, sat=bool(sat), rtA=RT_NOM + dA, rtB=RT_NOM + dB, eps=eps)

def run_scenario(sc, nmc, seed, tag, extra_corners=None):
    rng = np.random.default_rng(seed)
    corners = {}
    for k, d in corner_set(sc).items():
        corners[k] = {rg: eval_range(f"{tag}_{k}_{rg}", at_T(d), rg) for rg in ("5", "1.25")}
    # nominal pair (all nominal, Ron lo/lo)
    nomd = corner_draw(dict(sc, tolR=0, tolC=0, stray=0, dron=0, ron_hi=sc["ron_lo"], tcr=0), dT=0, vs=0, rs=(0, 0), sops=0,
                       aref=3.30, cent=0, vcc=3.30, name="nominal")
    corners["nominal"] = {rg: eval_range(f"{tag}_nom_{rg}", at_T(nomd), rg) for rg in ("5", "1.25")}
    mc = []
    for i in range(nmc):
        d = mc_draw(rng, sc)
        dd = at_T(d)
        mc.append({rg: eval_range(f"{tag}_mc{i}_{rg}", dd, rg) for rg in ("5", "1.25")})
    return mc, corners


def _strip(r):
    return {k: v for k, v in r.items() if not k.startswith("_")}

def mc_worker(args):
    """One Monte Carlo draw: both ranges at the draw's temperature (full: DC grid + AC) and at the
    calibration reference (DC grid only), for the DF-4 residual and the calibrated CMRR.  With a trimmer the one-time
    trim is found first, at the reference temperature, on the +-5 V range."""
    sc, seed, i, tag = args
    rng = np.random.default_rng([seed, i])
    d = mc_draw(rng, sc)
    info = None
    if sc.get("trimmer"):
        eps = rng.uniform(-sc.get("trim_res", TRIM_RES), sc.get("trim_res", TRIM_RES))
        rtA, rtB, info = trim_solve(sc, at_T(at_ref(d)), f"{tag}_trim{i}", eps)
        d = with_rt(d, rtA, rtB)
    dT = at_T(d)
    dR = at_T(at_ref(d))
    res = {}
    for rg in ("5", "1.25"):
        r = eval_range(f"{tag}_mc{i}_{rg}", dT, rg)
        r0 = eval_range(f"{tag}_ref{i}_{rg}", dR, rg, with_ac=False)
        r["df4"] = df4_residual(r0, r, rg)
        r["cal"] = add_cal(r0, r, dR, rg)
        res[rg] = _strip(r)
    if info:
        res["trim"] = info
    return res

def add_cal(r0, r1, d0, rg):
    a, b, m = cal_cmrr(r0, r1, d0, rg)
    a0, b0, m0 = cal_cmrr(r0, r0, d0, rg)
    out = dict(dc=a, dc_alt=b, ref=a0, ref_alt=b0, mism=m)
    if dlib.VARIANT == "hz":   # MCP reads the injection source; at N's 180 kohm Thevenin the T-switch's Ron divides negligibly
        E = CAL_RES[rg]
        out["res"] = min(min(cal_cmrr(r0, r1, d0, rg, (sg * E, -sg * E))[:2]) for sg in (+1, -1))
    elif dlib.UNC:
        E = CAL_RES[rg]
        # (1) the stated residual: MCP noise only, opposite signs per channel, worse of both signs and of the op-amp CM sign
        out["res"] = min(min(cal_cmrr(r0, r1, d0, rg, (sg * E, -sg * E))[:2]) for sg in (+1, -1))
        # (2) N injection through Ron against the divider's ~4 kohm Thevenin: the host knows DAC0 at its pin, N sits
        #     Ron/(Rth+Ron) lower; corrected with the mid Ron (6.25 ohm), the residual is (6.25 - Ron)/Rth per channel
        ka = (6.25 - d0["A"]["Roninj"]) / rth_of(d0["A"], d0["Rsa"]); kb = (6.25 - d0["B"]["Roninj"]) / rth_of(d0["B"], d0["Rsb"])
        out["res_ron"] = min(min(cal_cmrr(r0, r1, d0, rg, (ka + sg * E, kb - sg * E))[:2]) for sg in (+1, -1))
        out["res_ron_swap"] = min(min(cal_cmrr(r0, r1, d0, rg, (kb + sg * E, ka - sg * E))[:2]) for sg in (+1, -1))
        # (3) proposal: injection through the R3 leg (sees the divider through R3 = R1), stated residual
        out["r3"] = min(min(cal_cmrr(r0, r1, d0, rg, (sg * E, -sg * E), mode="R3")[:2]) for sg in (+1, -1))
    return out

def df4_residual(r0, r1, rg):
    """Calibrate each channel's gain and offset at the reference (other input grounded, 9 points, least squares),
    then read the same 81 input pairs at temperature.  Returns the input-referred error of the difference."""
    g = np.array(grid(rg))
    n = len(g); i0 = n // 2
    ga, oa = np.polyfit(g, r0["_pa"][:, i0], 1)
    gb, ob = np.polyfit(g, r0["_pb"][i0, :], 1)
    v1 = (r1["_pa"] - oa) / ga                  # [ia, ib]: estimate of in1
    v2 = (r1["_pb"] - ob) / gb
    true_d = g[:, None] - g[None, :]
    err = (v1 - v2) - true_d
    cm = (g[:, None] + g[None, :]) / 2
    # also the residual at the reference itself (INL of the channel after the fit, the vendor model's crossover)
    v1r = (r0["_pa"] - oa) / ga; v2r = (r0["_pb"] - ob) / gb
    errr = (v1r - v2r) - true_d
    return dict(drift_max=float(np.abs(err - errr).max()), err_max=float(np.abs(err).max()), err_ref_max=float(np.abs(errr).max()),
                err_at_zero_diff=float(np.abs(err[np.isclose(true_d, 0)]).max()),
                err_over_reading=float(np.max(np.abs(err)[np.abs(true_d) > 1e-9] / np.abs(true_d)[np.abs(true_d) > 1e-9])),
                err_grid=err.tolist(), g=g.tolist())
