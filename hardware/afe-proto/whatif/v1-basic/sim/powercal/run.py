#!/usr/bin/env python3
"""AFE steps 2a (power) and 2e (calibration, Phase 3).  `python3 -I run.py` regenerates
netlists/, raw/, logs/, results.json and report.md.  numpy only; ngspice 47 for circuits.
Every number is either computed here, simulated, or quoted with its datasheet table/page
(see SRC) - nothing else.  Guards are mutation-tested by `python3 -I run.py --mutate`."""
import json, os, re, subprocess, sys, hashlib, math
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
for d in ("netlists", "raw", "logs"):
    os.makedirs(d, exist_ok=True)
R = {}                      # results, dumped to results.json
CASES = []                  # pass/fail rows: (id, req, limit, worst, margin, ok, note)
MUT = os.environ.get("MUTATE", "")      # name of a deliberately broken target (guards)
rng = np.random.default_rng(20261111)

PENDING_PREFIX = ()          # 2026-11-11: SM-5 dropped, the 1 Mohm divider is final again, nothing is pending on it
RENAME = {  # 2026-11-11: per-channel Vmid buffers + an AWG buffer, and the T-switch, are the design; the earlier arrangement keeps its rows
    "P8-a": "P8-a [one shared buffer, previous]", "P8-a [M-4]": "P8-a [M-4, one shared buffer]", "P8-a [M-5]": "P8-a [M-5, one shared buffer]",
    "P8-a [sensitivity]": "P8-a [sensitivity, one shared buffer]", "P8-f": "P8-f [one shared buffer, previous]",
    "P8-a [Vmid x2]": "P8-a", "P8-a [Vmid x2 + M-4]": "P8-a [M-4]", "P8-a [Vmid x2 + M-5]": "P8-a [M-5]",
    "P8-f [Vmid x2, AWG on its own buffer]": "P8-f", "P8-f [Vmid x2, AWG on a channel's buffer]": "P8-f [AWG on a channel's buffer]",
    "P8-f [Vmid x2 + M-4, AWG on its own buffer]": "P8-f [M-4]", "P8-f [Vmid x2 + M-5, AWG on its own buffer]": "P8-f [M-5]",
    "P8-f [Vmid x2 + M-4, AWG on a channel's buffer]": None, "P8-f [Vmid x2 + M-5, AWG on a channel's buffer]": None,
    "C3-f": "C3-f [single switch, previous]", "C3-c": "C3-c [single switch, previous]", "C3-f [T-switch]": "C3-f", "C3-c [T-switch]": "C3-c",
    "SC-9 AWG [Vmid x2, AWG on its own buffer; T-switch]": "SC-9 AWG", "SC-9 AWG [Vmid x2, AWG on a channel's buffer; T-switch]": "SC-9 AWG [AWG on a channel's Vmid buffer]",
    "SC-9 AWG [one shared Vmid buffer; T-switch]": "SC-9 AWG [one shared Vmid buffer, previous]",
    "P8-b": "P8-b [one shared buffer, previous]", "P8-g": "P8-g [one shared buffer, previous]",
}
def case(cid, req, limit, worst, margin, ok, note=""):
    if cid in RENAME:
        cid = RENAME[cid]
        if cid is None: return
    if cid.startswith(PENDING_PREFIX) and "pending" not in note:
        note = (note + "; " if note else "") + DIVIDER_PENDING
    CASES.append(dict(id=cid, req=req, limit=limit, worst=worst, margin=margin, ok=bool(ok), note=note))
    print(f"[{'PASS' if ok else 'FAIL'}] {cid} {req}: limit {limit}; worst {worst}; margin {margin} {note}")

def sh(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True)

def spice(name, text, tail=""):
    """write netlists/<name>.cir, run ngspice -b, return log text"""
    p = f"netlists/{name}.cir"
    open(p, "w").write(text)
    r = sh(f"ngspice -b -o logs/{name}.log {p}")
    log = open(f"logs/{name}.log").read()
    if "Error" in log and "fatal" in log.lower():
        print(log[-1500:]); raise SystemExit(f"ngspice failed: {name}")
    return log

JOBS = max(1, min(3, int(os.environ.get("POWERCAL_JOBS", "3"))))   # parallel ngspice processes; at most 3 (shared machine)
def spice_many(jobs):
    """run [(name, text), ...] as independent ngspice processes, JOBS at a time; logs returned in input order, so the
    results do not depend on the worker count (every case has its own netlist/log file and no shared state)"""
    from concurrent.futures import ThreadPoolExecutor
    if JOBS == 1: return [spice(n, t) for n, t in jobs]
    with ThreadPoolExecutor(max_workers=JOBS) as ex:
        return list(ex.map(lambda nt: spice(*nt), jobs))

def meas(log, key):
    m = re.search(rf"^{re.escape(key)}\s*=\s*([-+0-9.eE]+)", log, re.M)
    return float(m.group(1)) if m else float("nan")

def load(name, ncol=None):
    a = np.loadtxt(f"raw/{name}.txt")
    return a

# ---------------------------------------------------------------- constants (SRC = where from)
SRC = {}
def K(name, val, src):
    SRC[name] = (val, src); return val
OP365 = "../../models/opa365/OPA365_PSPICE.lib"
OP354 = "../../models/opa354/OPA354_PSPICE.lib"
LIM_PW1_AFE = 100e-3        # PW-1 (afe.md): AFE normal operation
LIM_TOTAL   = 400e-3        # coordinator 2026-11-11: Due+AFE target 400 mA (polyfuse hold current), normal operation
LIM_FAULT_MA = 450.0        # afe.md PR-4 (2026-11-11): during a forced-voltage fault the Due + AFE stay within PW-1's 450 mA
BLEED = 4.7e3               # +3.3 V_A bleed, 4.7 kohm 1 % 0603: the one bleed on that net (scope PR-3 and AWG PR-4 back-feed, MC-12)
DUE_MA      = 300e-3        # D7 budget
OPA365_ABS  = 5.5           # OPA365 abs max supply (datasheet-facts, Sec 7.1 p5)
def par(*r): return 1/sum(1/x for x in r)
LSB12 = 3.3/4096                         # 12-bit LSB at AREF 3.3 V (0.806 mV)
# scope channel (sim/scope, architecture.md; trimmer removed 2026-11-11; R1 = R3 = 760k = 330k + 330k + 100k, approved
# 2026-11-11 because the 768k has no stock): IN -R1- N, N -R2- Vmid, N -R3- sense node,
# N -Rnp- op-amp (+), RF out -> (-), RG (-) -> Vmid, the range switch shunts RF (+-5 V: G = 1); out -Riso- ADC pin
SC_R1, SC_R2, SC_R3, SC_RF, SC_RG, SC_RNP, SC_RISO = 760e3, 330e3, 760e3, 1000.0, 270.0, 680.0, 22.0   # v1-basic: RF 1k, RG 270 (were 953 / 249 0.1 %)
SC_C1, SC_C2, SC_RON = 12e-12, 39e-12, 3.7
SC_G = 1 + SC_RF/SC_RG                                  # +-1.25 V range, 4.83
SC_ALPHA = par(SC_R2, SC_R3)/(SC_R1 + par(SC_R2, SC_R3))  # IN -> N, 0.2311
SC_RTH = par(SC_R1, SC_R2, SC_R3)                       # N Thevenin, 177.5 kohm
# AWG stage, variant n1 (whatif/awg-rab/run.py, approved 2026-11-11): Ra = (4.7k||4.7k) + 3 x 4.7k = 16.45k,
# Rb = 4 x 4.7k = 18.8k (1 %), Rx 330k to Vmid, Rf 249 + 49.9, Rg 249 to Vmid; per supply pin 10 uF at the rail,
# 22 || 22 = 11 ohm, 100 nF, then the series Schottky
# 2026-11-11: the AWG is now the buffered-DAC0 design (sim/loop step "buf", being verified in sim/awg; values as given by the
# coordinator and in sim/loop's BUF): DAC0 -> 680 ohm -> OPA365 follower (330k to Vmid at its input, own Schottky + 100 nF on
# +3.3 V_A, ~5 mA) -> Ra 953 -> V+, Rb = 953 + 249||249 + 22 to ground, no Rx; Rg 953 to Vmid, Rf = 953 + 249||249 + 22 with 12 pF
AW_RA, AW_RB, AW_RX, AW_RF, AW_RG, AW_RFLT, AW_RS = 1000.0, 1000.0 + 135.0 + 44.0, None, 1000.0 + 135.0 + 44.0, 1000.0, 11.0, 50.0   # v1-basic
AW_G = 1 + AW_RF/AW_RG
# sense node: Due 3.3 V pin -> RSF -> sense node (10 uF + 100 nF) -> R3 of each channel (sim/scope netlib)
RSF, CSF = 270.0, 10e-6     # v1-basic: 270 ohm Basic 1 % (was 249 0.1 %). M-3 approved 2026-11-11: the sense filter's resistor is a 249 ohm 0.1 % (was 100 ohm)
DIVIDER_PENDING = ""
# 10 uF parts are Samsung CL21A106KAYNNNE (C15850, X5R 0805 25 V, the only Basic 10 uF, jlcpcb-parts.md).  Its DC-bias
# derating is not on the part page *(check)*: the 5 V bulk keeps the earlier assumption (2 parts -> 5 uF, 25 % each);
# parts at <= 3.3 V are modelled at nominal, with a 25 % sensitivity row where the result depends on them.
C10_DERATE = 0.25                       # the earlier assumption, kept for the comparison rows
# Samsung's characterisation of CL21A106KAYNNN (C15850), from the product page's embedded datasheetData JSON, stored and
# hashed in models/cl21a106kaynnne/ (manifest.json); parsed as data with json.loads, never executed.
SAM_FILE = "../../models/cl21a106kaynnne/CL21A106KAYNNN_product_page.html"
SAM_SHA = "4b7cf7d8e24b0af8cb7f0d2118a8077c6b512ade8c0662c6b0ab1a4bb4f27c24"
def samsung_c15850():
    raw = open(SAM_FILE, "rb").read()
    assert hashlib.sha256(raw).hexdigest() == SAM_SHA, "Samsung C15850 file does not match manifest.json"
    t = raw.decode("utf-8", "replace"); i = t.index("var datasheetData = ") + len("var datasheetData = "); dpt = 0
    for j in range(i, len(t)):
        if t[j] == "[": dpt += 1
        elif t[j] == "]":
            dpt -= 1
            if dpt == 0: break
    data = json.loads(t[i:j+1])
    z = [b for b in data if b["graphType"] == "|Z|_R"][0]["selectPartsList"][0]["chartList"]
    arr = lambda ch: (np.array([float(q["x"]) for q in ch["data"]])*1e6, np.array([float(q["y"]) for q in ch["data"]]))
    fz, Z = arr([c for c in z if c["graphSubType"] == "|Z|"][0]); fr, Rr = arr([c for c in z if c["graphSubType"] == "R"][0])
    dc = [b for b in data if b["graphType"] == "DCBias"][0]["selectPartsList"][0]["chartList"][0]["data"]
    xv = np.array([float(q["x"]) for q in dc]); yv = np.array([float(q["y"]) for q in dc]); o = np.argsort(xv)
    m = (fz >= 3e6) & (fz <= 10e6); w = 2*np.pi*fz[m]; X = np.sqrt(np.maximum(Z[m]**2 - np.interp(fz[m], fr, Rr)**2, 0))
    esl = float(np.median((X + 1/(w*10e-6))/w))
    return dict(esr=lambda f_: float(np.interp(f_, fr, Rr)), z=lambda f_: float(np.interp(f_, fz, Z)),
                k=lambda v: 1 + float(np.interp(abs(v), xv[o], yv[o]))/100, esl=esl, srf=float(fz[np.argmin(Z)]))
SAM = samsung_c15850()
C10_TOL = 0.9                                     # -10 % tolerance (K) on top of the DC-bias derating
K10_5V, K10_33, K10_N, K10_165 = (SAM["k"](v)*C10_TOL for v in (5.0, 3.3, 2.07, 1.65))
ESR10_2M, ESR10_HI, ESL10 = SAM["esr"](2e6), max(SAM["esr"](x) for x in np.linspace(3e6, 10.5e6, 40)), SAM["esl"]
C_BULK = 2*10e-6*K10_5V                           # the 5 V bulk, 2 x C15850 at 5 V DC bias (was 2 x 10 uF x 25 % assumed)
N_RAIL10 = 2                                      # 10 uF per LM27762 output (+3.3 V_A and the negative rail): 2, approved 2026-11-11
# tolerance stack of the rails (LM27762 Sec 5.5 VFB+ 1.182..1.218, VFB- -1.238..-1.202; FB resistors 0.1 %)
RT_P, RB_P = 175e3, 100e3   # v1-basic: 75k + 100k, Vout = 1.2*(1+Rt/Rb) = 3.300 (was 174k: 3.288)
# - rail (2026-11-11, AWG AW-1 into 50 ohm; the 768k left the BOM): R3 = 330k || 100k, R4 = 330k / 3, 0.1 % BOM types:
# Vout = -1.22*(1+R3/R4) = -2.0733 V (Sec 7.2.2.3 Eq. 3; R4 >= 50 kohm; range -1.5..-5 V).  It was 330k || 100k / 100k (-2.156 V)
# 2026-11-11: the 768k left the BOM (no stock), so R3 = (330k + 330k + 100k) || 330k, R4 = 330k (BOM review proposal),
# -1.22 x (1 + 230.1/330) = -2.0706 V.  R3 = 330k || 100k with R4 = 330k/3 gives -2.0712 V at 45 k source impedance (also 5 parts).
RT_N, RB_N = 75e3, 330e3/3      # v1-basic: R3 = 75k (one part), -2.052 V (was 330k || 100k, -2.071 V). approved 2026-11-11: R3 = 330k || 100k, R4 = 330k || 330k || 330k (45 k at FB-)
RTOL_FB = 0.01   # v1-basic: Basic 1 % feedback resistors (was 0.1 %)
def rails(vfbp, vfbn, rt=RTOL_FB):
    vp = vfbp*(1+RT_P*(1+rt)/(RB_P*(1-rt))); vn = abs(vfbn)*(1+RT_N*(1+rt)/(RB_N*(1-rt)))
    return vp, vn
VP_NOM, VN_NOM = rails(1.2, 1.22, 0)
VP_MAX, VN_MAX = rails(1.218, 1.238)
VP_MIN, VN_MIN = rails(1.182, 1.202, -RTOL_FB)   # resistor tolerance on the low side too (was +0.001: not the minimum)
R["rails"] = dict(vp_nom=VP_NOM, vn_nom=VN_NOM, vp_max=VP_MAX, vn_max=VN_MAX, vp_min=VP_MIN, vn_min=VN_MIN,
                  sum_max=VP_MAX+VN_MAX)
# BAT54-class Schottky, fitted to Vf 0.24 V @1 mA and 0.32 V @10 mA (ASSUMED typical, *(check)* - no datasheet in repo)
SCH = ".model DSCH D(IS=9.9e-7 N=1.34 RS=1.5 CJO=7p)"

# =============================================================== P1 start-up, ordering, shut-down
def p1_netlist(name, vin, ramp, tss, ov, order, rsrc, vp=None, vn=None, sch=True, tstop=20e-3):
    vp = VP_MAX if vp is None else vp; vn = VN_MAX if vn is None else vn
    d = 3e-3
    enp = {"both": "vs", "neg_first": "enpd", "pos_first": "vs"}[order]
    enn = {"both": "vs", "neg_first": "vs", "pos_first": "enpd"}[order]
    if order == "neg_first":    pwl = f"Vdl enpd 0 PWL(0 0 {d} 0 {d+1e-6} 5)"
    elif order == "pos_first":  pwl = f"Vdl enpd 0 PWL(0 0 {d} 0 {d+1e-6} 5)"
    else:                       pwl = "Vdl enpd 0 0"
    # AWG op-amp pins (sim/awg): 10 uF at the rail, 22 || 22 ohm, 100 nF, then the series Schottky (or nothing)
    awg = (f"Cbp vp cbp 10u\nRcbp cbp 0 0.02\nCbn vn cbn 10u\nRcbn cbn 0 0.02\nCbp2 vp cbp2 10u\nRcbp2 cbp2 0 0.02\nCbn2 vn cbn2 10u\nRcbn2 cbn2 0 0.02\n"
           f"Rfp vp vpf {AW_RFLT}\nCfp vpf 0 100n\nRfn vnf vn {AW_RFLT}\nCfn vnf 0 100n\n")
    awg += "Dp vpf awgp DSCH\nDn awgn vnf DSCH\n" if sch else "Rp vpf awgp 1m\nRn awgn vnf 1m\n"
    t = f"""* P1 start-up / ordering. vin={vin} ramp={ramp} tss={tss} ov={ov} order={order} rsrc={rsrc} sch={sch}
.include models/lm27762_beh.lib
.param vp={vp} vn={vn}
{SCH}
Vdue due 0 PWL(0 0 {ramp} {vin})
Rsrc due v5 {rsrc}
Cdue v5 0 47u
Rs v5 v6 1.0
Rbd v6 vs {RBEAD+1e-3}
Cin vs 0 {C_BULK}
X1 vs vp vn {enp} {enn} LM27762B vp={{vp}} vn={{vn}} tss={tss} ov={ov}
{pwl}
Cp vp 0 22u
Cn vn 0 17u
* loads: two scope op-amps + vmid buffer + ref buffer + converters ~ 25 mA on +3.3 V
Rlp vp 0 {{vp/25m}}
{awg}
Rla awgp awgn 1.1k
Rln vn 0 1e6
Bsa sa 0 V=V(awgp)-V(awgn)
Bsm sm 0 V=V(vp)-V(vn)
.tran 1u {tstop}
.control
run
meas tran sum_awg max v(sa)
meas tran sum_main max v(sm)
meas tran vpmax max v(vp)
meas tran vnmin min v(vn)
meas tran ipk min i(Vdue)
meas tran vpend find v(vp) at={tstop}
meas tran vnend find v(vn) at={tstop}
meas tran t33 when v(vp)=3.0 rise=1
.endc
.end
"""
    return t

def run_p1(vp=None, tag=""):
    """vp: the + rail maximum to start up to (None = VP_MAX); tag != "": a variant, results under R['p1'+tag], no cases"""
    vpx = VP_MAX if vp is None else vp
    rows = []; jobs = []
    for order in ("both", "neg_first", "pos_first"):
        for vin in (4.4, 5.25):
            for ramp in (1e-6, 100e-6, 5e-3):
                for tss in (20e-6, 2e-3):
                    for rsrc in (0.2, 1.0):
                        for sch in (True, False):
                            nm = f"p1{tag}_{order}_{vin}_{ramp:g}_{tss:g}_{rsrc}_{'s' if sch else 'n'}"
                            if not (sch or (ramp == 100e-6 and rsrc == 0.2)):
                                continue    # the no-Schottky comparison needs only the corner cases
                            jobs.append((nm, p1_netlist(nm, vin, ramp, tss, 0, order, rsrc, vp=vpx, sch=sch)))
                            rows.append(dict(order=order, vin=vin, ramp=ramp, tss=tss, rsrc=rsrc, sch=sch))
    for row, log in zip(rows, spice_many(jobs)):
        row.update(dict(sum_awg=meas(log, "sum_awg"), sum_main=meas(log, "sum_main"),
                        vpmax=meas(log, "vpmax"), vnmin=meas(log, "vnmin"), ipk=-meas(log, "ipk"),
                        vpend=meas(log, "vpend"), vnend=meas(log, "vnend")))
    s_on = [r for r in rows if r["sch"]]; s_off = [r for r in rows if not r["sch"]]
    worst_on = max(r["sum_awg"] for r in s_on); worst_off = max(r["sum_main"] for r in s_off)
    # allowed simultaneous overshoot per rail: sweep ov at the worst-case corner
    ovres = {}
    keys = [(sch, ov) for sch in (True, False) for ov in (0.0, 0.1, 0.2, 0.3, 0.4)]
    logs = spice_many([(f"p1{tag}_ov_{ov}_{'s' if sch else 'n'}", p1_netlist("ov", 5.25, 100e-6, 2e-3, ov, "both", 0.2, vp=vpx, sch=sch)) for sch, ov in keys])
    for (sch, ov), log in zip(keys, logs):
        ovres[(sch, ov)] = meas(log, "sum_awg" if sch else "sum_main")
    # largest per-rail overshoot that still keeps the AWG op-amp pins under 5.5 V
    allow = {}
    for sch in (True, False):
        good = [ov for (s, ov), v in ovres.items() if s == sch and v < OPA365_ABS]
        allow[sch] = max(good) if good else -1
    res = dict(rows=rows, worst_pins_sch=worst_on, worst_pins_nosch=worst_off, vp=vpx, sum_max=vpx+VN_MAX,
               overshoot={f"{'sch' if k[0] else 'nosch'}_{k[1]}": v for k, v in ovres.items()}, allowed_overshoot={"sch": allow[True], "nosch": allow[False]})
    if tag:
        R["p1" + tag] = {k: v for k, v in res.items() if k != "rows"}
        return res
    R["p1_rows"] = rows
    R["p1_worst_pins_sch"] = worst_on; R["p1_worst_pins_nosch"] = worst_off
    R["p1_overshoot"] = res["overshoot"]; R["p1_allowed_overshoot"] = res["allowed_overshoot"]
    case("P1-a", "AWG op-amp supply < 5.5 V, all start orderings, Vin 4.4/5.25, ramp 1 us-5 ms, Rsrc 0.2-1 ohm, rails at +tol",
         f"< {OPA365_ABS} V (OPA365 abs max)", f"{worst_on:.3f} V at the op-amp pins ({worst_off:.3f} V on the bare rails)",
         f"{OPA365_ABS-worst_on:.3f} V", worst_on < OPA365_ABS)
    case("P1-b", f"overshoot allowance: if +3.3 V (and -{VN_NOM:.2f} V) overshoot by X together",
         "< 5.5 V", f"X = {allow[True]*1e3:.0f} mV per rail tolerated with the series Schottkys, {allow[False]*1e3:.0f} mV without",
         f"DC stack alone leaves {OPA365_ABS-(VP_MAX+VN_MAX):.3f} V bare", allow[True] >= allow[False] and allow[True] >= 0.2,
         "overshoot is an ASSUMED sweep (model gap G1)")
    iin = max(r["ipk"] for r in rows)
    R["p1_inrush_A"] = iin

# =============================================================== M-6: + rail divider from existing types
def run_m6():
    """WITHDRAWN 2026-11-11 (not called): Rt = 768k + (768k || 768k) needs the 768k, which has left the BOM; no Rt/Rb
    from 330k and 100k in up to 4 + 2 parts lands within 3.27-3.31 V.  Kept for the record."""
    rt, rb = 768e3 + 384e3, 660e3
    f = lambda vfb, s_: vfb*(1 + rt*(1+s_)/(rb*(1-s_)))
    vp_nom, vp_max, vp_min = f(1.2, 0), f(1.218, 0.001), f(1.182, -0.001)
    r = run_p1(vp=vp_max, tag="_m6")
    rth_new, rth_old = par(rt, rb), par(RT_P, RB_P)
    d = dict(vp_nom=vp_nom, vp_max=vp_max, vp_min=vp_min, sum_max=vp_max+VN_MAX, worst_pins_sch=r["worst_pins_sch"], worst_bare=r["worst_pins_nosch"],
             allow_sch=r["allowed_overshoot"]["sch"], allow_nosch=r["allowed_overshoot"]["nosch"], rth_k=rth_new/1e3, rth_old_k=rth_old/1e3,
             mV_per_nA=rt*1e-9*1e3, mV_per_nA_old=RT_P*1e-9*1e3, i_fb_to_abs_nA=(OPA365_ABS-(vp_max+VN_MAX))/rt*1e9)
    R["m6"] = d
    case("P1-a [M-6]", f"as P1-a with the + rail divider Rt = 768k + 768k||768k, Rb = 330k + 330k ({vp_nom:.4f} V nominal, {vp_max:.3f} V max)",
         f"< {OPA365_ABS} V", f"{r['worst_pins_sch']:.3f} V at the op-amp pins, {r['worst_pins_nosch']:.3f} V on the bare rails", f"{OPA365_ABS-r['worst_pins_sch']:.3f} V (bare {OPA365_ABS-r['worst_pins_nosch']:.3f} V)",
         r["worst_pins_sch"] < OPA365_ABS)
    case("P1-b [M-6]", "bare rails at the datasheet maxima, DC, and the overshoot tolerated", "< 5.5 V", f"{vp_max+VN_MAX:.3f} V DC; overshoot {r['allowed_overshoot']['sch']*1e3:.0f} mV per rail with the Schottkys, {r['allowed_overshoot']['nosch']*1e3:.0f} mV without",
         f"{OPA365_ABS-(vp_max+VN_MAX):.3f} V", vp_max+VN_MAX < OPA365_ABS and r["allowed_overshoot"]["sch"] >= 0.2,
         f"FB+ Thevenin {rth_new/1e3:.0f} k (was {rth_old/1e3:.0f} k): each nA of FB+ input current moves +3.3 V by {rt*1e-6:.2f} mV (was {RT_P*1e-6:.2f}); "
         f"the FB+ input current is not in the datasheet *(check)*; {(OPA365_ABS-(vp_max+VN_MAX))/rt*1e9:.0f} nA would take the bare rails to 5.5 V")

# =============================================================== P2 load step, shut-down
def p2_netlist(vin, rsrc, mode):
    vp, vn = VP_NOM, VN_NOM
    if mode == "step":   src = f"Vdue due 0 {vin}"
    else:                src = f"Vdue due 0 PWL(0 {vin} 5m {vin} 5.1m 0 8m 0)"     # Due powered off at 5 ms
    return f"""* P2 {mode} vin={vin} rsrc={rsrc}  (LDO closed-loop Zout ASSUMED 11 mohm DC + 0.8 uH, model gap G2)
.include models/lm27762_beh.lib
{SCH}
{src}
Rsrc due v5 {rsrc}
Cdue v5 0 47u
Rs v5 v6 1.0
Rbd v6 vs {RBEAD+1e-3}
Cin vs 0 {C_BULK}
Vst stp 0 PWL(0 0 {'1m 5' if mode=='step' else '1m 5'})
X1 vs vpi vni vs vs LM27762B vp={vp} vn={vn} tss=100u
Lzp vpi vpo 0.8u
Rzp vpo vp 0.011
Lzn vni vno 0.8u
Rzn vno vn 0.011
Cp vp 0 22u
Cn vn 0 17u
Rlp vp 0 {vp/25e-3}
Cbp vp cbp 10u
Rcbp cbp 0 0.02
Cbn vn cbn 10u
Rcbn cbn 0 0.02
Cbp2 vp cbp2 10u
Rcbp2 cbp2 0 0.02
Cbn2 vn cbn2 10u
Rcbn2 cbn2 0 0.02
Rfp vp vpf {AW_RFLT}
Cfp vpf 0 100n
Rfn vnf vn {AW_RFLT}
Cfn vnf 0 100n
Dp vpf awgp DSCH
Dn awgn vnf DSCH
Rla awgp awgn 1.1k
* AWG shorted-output load: 23 mA out of the + pin node (positive half) ; second source 23 mA into - pin (negative half)
Ish awgp 0 PWL(0 0 3m 0 3.0001m 23m 3.3m 23m 3.3001m 0 3.6m 0 3.6001m 0 )
Bsa sa 0 V=V(awgp)-V(awgn)
Ish2 0 awgn PWL(0 0 4m 0 4.0001m 23m 4.3m 23m 4.3001m 0 )
.tran 0.05u 9m
.control
run
meas tran vp_lo min v(vp) from=3.0m to=3.4m
meas tran vp_ref find v(vp) at=2.9m
meas tran vn_hi max v(vn) from=4.0m to=4.4m
meas tran vn_ref find v(vn) at=3.9m
meas tran ap_lo min v(awgp) from=3.0m to=3.4m
meas tran an_hi max v(awgn) from=4.0m to=4.4m
meas tran ap_ref find v(awgp) at=2.9m
meas tran an_ref find v(awgn) at=3.9m
meas tran sumpk max v(sa) from=0.5m to=9m
meas tran ap_ss find v(awgp) at=3.28m
meas tran an_ss find v(awgn) at=4.28m
meas tran vp5ms find v(vp) at=5.5m
meas tran vp6ms find v(vp) at=7m
meas tran vn6ms find v(vn) at=7m
.endc
.end
"""

def run_p2():
    out = {}
    for vin in (4.4, 5.25):
        for rsrc in (0.2, 1.0):
            lg = spice(f"p2_step_{vin}_{rsrc}", p2_netlist(vin, rsrc, "step"))
            out[f"{vin}_{rsrc}"] = dict(
                dvp=meas(lg, "vp_ref")-meas(lg, "vp_lo"), dvn=meas(lg, "vn_hi")-meas(lg, "vn_ref"),
                dap=meas(lg, "ap_ss")-meas(lg, "ap_lo"), dan=meas(lg, "an_hi")-meas(lg, "an_ss"),
                shift_p=meas(lg, "ap_ref")-meas(lg, "ap_ss"), shift_n=meas(lg, "an_ss")-meas(lg, "an_ref"))
    lg = spice("p2_down", p2_netlist(5.25, 0.2, "down"))
    out["shutdown"] = dict(sumpk=meas(lg, "sumpk"), vp_after2ms=meas(lg, "vp6ms"), vn_after2ms=meas(lg, "vn6ms"))
    R["p2"] = out
    worst_rail = max(max(v["dvp"], v["dvn"]) for k, v in out.items() if k != "shutdown")
    worst_pin = max(max(v["dap"], v["dan"]) for k, v in out.items() if k != "shutdown")
    case("P2-a", "PW-2 load step, AWG output short step 0->23 mA (and back), droop at the rails",
         "<= 20 mV (transient, beyond the static shift)", f"{worst_rail*1e3:.2f} mV on the rails, {worst_pin*1e3:.2f} mV at the AWG op-amp pins; static Schottky shift {max(out[k]['shift_p'] for k in out if k!='shutdown')*1e3:.0f} mV",
         f"{(20e-3-worst_pin)*1e3:.1f} mV", worst_pin <= 20e-3, "LDO loop response assumed (G2)")
    case("P2-b", "shut-down (Due powered off, 5V pin collapsing): op-amp supply never exceeds abs max",
         "< 5.5 V", f"{out['shutdown']['sumpk']:.3f} V", f"{OPA365_ABS-out['shutdown']['sumpk']:.3f} V",
         out['shutdown']['sumpk'] < OPA365_ABS)

# =============================================================== P3 current budget, P6 PW-6 sweep
RSENSE, RBEAD = 1.0, 0.0            # 1 ohm 1 % 0603 sense resistor in the 5 V feed (D7); R2 approved 2026-11-11: no ferrite bead,
                                    # the feed's filter is the sense resistor and the bulk (was a bead, DCR 0.2 ohm *(check)*)
R_FUSE, R_FET, R_CONN = 0.5, 0.1, 0.05   # F1/F2 polyfuse, FDN340P, contacts: ASSUMED *(check)*, no datasheet in repo
# ladder (PA-9 / D11, decided 2026-11-11): eight discrete 249 ohm 0.1 % 10 ppm/K resistors (RESI PTFR0603B249RN9, C2692731,
# a type already in the design); three in parallel at the bottom, five in series above: 83 + 5 x 249 = 1328 ohm, 2.26 mA at
# 3.0 V.  It replaced 2 x 4 x 330 ohm 5 % arrays (C12018, an Extended part), which replaced 4 x 1 kohm (C20197, failed C2-c).
RLAD_ELEM, RLAD_NPAR, RLAD_NSER, RLAD_TOL, RLAD_TC = 270.0, 3, 5, 0.01, 100e-6   # v1-basic: 8 x 270 ohm Basic 1 % 100 ppm/K (C22966)
RLAD_PEL = 0.100                        # v1-basic: 0603WAF 100 mW at 70 C (v2/jlc-basic.md section 2, datasheet section 6/7)
SEG_1K = [1000.0/3] + [1000.0]*5        # the previous owner ladder (C20197), kept for the C2-c guard and the sweep
SEG = [RLAD_ELEM/RLAD_NPAR] + [RLAD_ELEM]*RLAD_NSER
RLAD_TOTAL = sum(SEG)
def budget(scope_ma, ladder_r=RLAD_TOTAL*(1-RLAD_TOL), bleed_r=BLEED, vp=3.0, typical=False):
    """input current of the AFE at the 5V pin, mA.  Quiescent currents counted on BOTH rails where they flow
    through both (an op-amp's supply current is drawn from VIN by the + LDO and again by the charge pump)."""
    q = (lambda mx, ty: ty) if typical else (lambda mx, ty: mx)
    items = {
        "2 scope op-amps (quiescent, both rails)": 2*q(scope_ma, 4.6 if scope_ma < 6 else 5.0)*2 if False else 2*q(scope_ma, 4.9),
        "Vmid buffers: TLV9062 (both scope channels, 2 x 0.8 mA max, 0.538 typ) + the AWG's own OPA365 (sim/awg buf)": 2*q(0.8, 0.538) + q(5.0, 4.6),
        "AWG Vmid divider 330k/330k on +3.3 V_A": 3.34/660e3*1e3,
        "DAC0 buffer (OPA365 follower, AWG)": q(5.0, 4.6),
        "AWG op-amp quiescent (+ rail)": q(5.0, 4.6),
        "AWG op-amp quiescent again via the charge pump (- rail)": q(5.0, 4.6),
        "ADS124S08 IAVDD + IDVDD (conversion, PGA bypassed; AVDD max taken from the PGA-enabled gain-1 row)": q(0.135+0.300, 0.085+0.225),
        "ADS124S08 REFP0 input current from the REF3030 (about 250 kohm unbuffered, 6 uA/V max)": 3.0*6e-6*1e3,
        "REF3030E": q(0.037, 0.027),
        "TMUX1119 ratio switch x1 (IDD 0.8 uA max; the four injection T-switches are retired)": q(0.0008, 0.000003),
        "AWG-sense divider 300k from the 3.0 V ladder top (ratio switch on S2, calibration only)": 3.0/300e3*1e3,
        "ladder 3.0 V / R (every element at -tol)": 3.0/ladder_r*1e3,
        "bleed on +3.3 V": 3.34/bleed_r*1e3,
        "LM27762 Iq": q(0.6, 0.39),
    }
    return items
def run_p3():
    out = {}
    for variant, sc_max in (("OPA365 scope", 5.0), ("OPA354 scope", 6.3)):
        base = sum(budget(sc_max).values())
        base_t = sum(budget(sc_max, typical=True).values())
        # loads: normal = 10 mA peak into 50 ohm; short = 23 mA; external +-5 V = OPA365 ISC 65 mA (typ, Sec 7.6 p7)
        rows = {"normal (AWG +-1 V into 50 ohm, 10 mA peak)": base+10, "AWG shorted (23 mA)": base+23,
                "external +-5 V on AWG output (65 mA op-amp limit)": base+65}
        rows_t = {k: v for k, v in zip(rows, (base_t+10, base_t+23, base_t+65))}
        out[variant] = dict(max=rows, typ=rows_t)
    R["p3"] = out
    R["p3_items"] = budget(5.0)
    for variant, d in out.items():
        n, s, e = (d["max"][k] for k in d["max"])
        case(f"P3-a [{variant}]", "PW-1 AFE current, normal / AWG shorted (PW-3), all datasheet maxima at once",
             "<= 100 mA", f"{n:.1f} mA normal, {s:.1f} mA shorted", f"{100-s:.1f} mA", s <= 100)
        case(f"P3-b [{variant}]", "Due 300 mA + AFE, external +-5 V on AWG (PR-4, exempt from PW-3), all maxima",
             f"<= {LIM_FAULT_MA:.0f} mA total (PW-1; afe.md PR-4: a fault is judged against 450, not the 400 mA target)", f"{300+e:.1f} mA (AFE {e:.1f})", f"{LIM_FAULT_MA-300-e:.1f} mA", 300+e <= LIM_FAULT_MA,
             "typ-sum " + f"{300+d['typ']['external +-5 V on AWG output (65 mA op-amp limit)']:.1f} mA")

def run_p6(rbead=None, tag=""):
    rbead = RBEAD if rbead is None else rbead
    """5V pin sweep with the Due's 3.3 V = min(3.3, V5 - h), h = 1.0..1.2 V (NCP1117 dropout *(check)*)."""
    n_max = sum(budget(5.0).values()) + 23      # AWG shorted, OPA365 scope: the worst continuous case
    i_afe = n_max*1e-3
    rows = []
    for v5 in np.round(np.arange(3.40, 5.30, 0.05), 2):
        vin = v5 - i_afe*(RSENSE+rbead)
        need_pos = VP_MAX + 0.45*(i_afe*0.6)       # + LDO dropout 45 mV @100 mA -> 0.45 ohm (Sec 5.5)
        need_neg = VN_MAX + 2.5*i_afe*0.4 + 0.03*(i_afe*0.4/0.1)   # RNEG 2.5 ohm, LDO- dropout 30 mV @100 mA
        row = dict(v5=float(v5), vin=vin, margin_pos=vin-need_pos, margin_neg=vin-need_neg)
        for h in (1.0, 1.2):
            v33 = min(3.3, v5 - h); row[f"v33_h{h}"] = v33
        rows.append(row)
    if not tag: R["p6_rows"] = rows
    lo = min(r["v5"] for r in rows if r["margin_pos"] >= 0 and r["margin_neg"] >= 0)
    r44 = [r for r in rows if abs(r["v5"]-4.4) < 1e-9][0]
    r525 = [r for r in rows if abs(r["v5"]-5.25) < 1e-9][0]
    if tag:
        R["p6" + tag.strip(" []").lower()] = dict(min_v5=lo, at44=r44, i_afe_mA=n_max)
        case("P6-a" + tag, f"PW-6 rails in regulation at a 4.4 V 5V pin with the bead removed (1 ohm sense resistor only, {n_max:.1f} mA)", "margin >= 0 at 4.4 V",
             f"Vin {r44['vin']:.3f} V; LDO+ headroom {r44['margin_pos']:.3f} V, charge-pump/LDO- headroom {r44['margin_neg']:.3f} V; rails regulate down to V5 = {lo:.2f} V",
             f"{min(r44['margin_pos'], r44['margin_neg']):.2f} V", min(r44['margin_pos'], r44['margin_neg']) >= 0)
        return
    R["p6_min_v5_rails"] = lo
    R["p6_aref_below_3p20"] = {"h1.0": 3.2+1.0, "h1.2": 3.2+1.2}
    case("P6-a", f"PW-6 rails in regulation (3.3 V dropout, -{VN_NOM:.2f} V charge-pump headroom) over 5V pin 4.4..5.25 V, Rsrc 1 ohm path + 1 ohm sense",
         "margin >= 0 at 4.4 V", f"3.3 V rail margin {r44['margin_pos']:.2f} V and -{VN_NOM:.2f} V margin {r44['margin_neg']:.2f} V at 4.4 V (Vin {r44['vin']:.2f} V); rails regulate down to V5 = {lo:.2f} V",
         f"{min(r44['margin_pos'], r44['margin_neg']):.2f} V", min(r44['margin_pos'], r44['margin_neg']) >= 0)
    # USB path drop at the 400 mA budget
    drop = 0.4*(R_FUSE+R_FET+R_CONN)
    R["p6_usb"] = dict(drop=drop, v5_from_4v75=4.75-drop, v5_from_4v40=4.40-drop)
    case("P6-b", "USB path polyfuse + FDN340P + contacts at the 400 mA budget (assumed 0.65 ohm *(check)*)",
         "V5 >= 4.4 V from a 4.75 V host", f"drop {drop*1e3:.0f} mV -> V5 = {4.75-drop:.2f} V", f"{4.75-drop-4.4:.2f} V", 4.75-drop >= 4.4,
         "a 4.4 V bus-powered device after its cable reaches V5 = %.2f V" % (4.40-drop))

# =============================================================== P4/P5 ripple, residue, PW-4 (AC, TI op-amp models)
STAGES = [  # name, model, include, gain-network, kind
    ("s354_g1", "OPA354", OP354, 1.0), ("s354_g4", "OPA354", OP354, SC_G),
    ("s365_g1", "OPA365", OP365, 1.0), ("s365_g4", "OPA365", OP365, SC_G)]
FILT_BEAD = "L={0} 0.5u"   # ferrite bead model: 0.5 uH || 500 ohm, 0.2 ohm DCR (GZ1608D601TF class, ASSUMED *(check)*)
def bead(tag, a, b, rdc=0.2):
    return (f"Rbd{tag} {a} {a}x {rdc}\nLbd{tag} {a}x {b} 0.5u\nRbp{tag} {a}x {b} 500\n")
def ac_netlist(stim, rsrc=1.0, c_bulk=C_BULK, local="100n", br_c="10u", nobead=True, ripple_cal=False,
               esr10=None, esl10=ESL10, k33=K10_33, kneg=K10_N, nrail=N_RAIL10, psrr_zero=10e3, psrr_db=43, psrr_dbn=50, sch=True):
    """stim in a (5V-pin ripple), bp/bn (LDO output ripple), c (charge-pump input current).  The 10 uF parts (C15850) carry
    esr10 + esl10 in series and the DC-bias derating k33 (+3.3 V_A) / kneg (negative rail); nrail of them per LM27762 output."""
    esr10 = ESR10_2M if esr10 is None else esr10
    ka = 10**(-psrr_db/20); kn = 10**(-psrr_dbn/20)
    acs = {s: (1 if s == stim else 0) for s in ("a", "bp", "bn", "c")}
    t = [f"* P4/P5 AC stimulus={stim}  rsrc={rsrc}", f".include {OP354}", f".include {OP365}", SCH,
         (f"Vsrc v5 0 DC 5 AC 1" if stim == "a" else f"Vsrc due 0 DC 5 AC 0"),
         ("" if stim == "a" else f"Rsrc due v5 {rsrc}"), ("" if stim == "a" else "Cdue v5 0 47u"), ("" if stim == "a" else "Resr v5 v5e 0.05"), ("" if stim == "a" else "Cde v5e 0 1u"),
         "Rs v5 v6 1.0", ("Rnbin v6 v7 1m" if nobead else bead("in", "v6", "v7")), f"Rcb v7 v7b 5m", f"Cbulk v7b 0 {c_bulk}",
         f"Ic v7 0 DC 0 AC {acs['c']}"]
    # LDO+ : PSRR network (k at low f, rising to unity), ripple source in series, output cap
    rb = 1e3; ra = rb*(1/ka-1); cz = 1/(2*math.pi*psrr_zero*ra)
    t += [f"Rpa v7 psn {ra}", f"Cpa v7 psn {cz}", f"Rpb psn 0 {rb}", "Ep pa pdc psn 0 1", "Vpdc pdc 0 DC 3.34"]
    if ripple_cal:   # the LDO ripple as a source behind the LDO's assumed 11 mohm + 0.8 uH, calibrated (in run_p4) to the datasheet's 5 mV on 2.2 uF
        t += ["Rop pa outq 0.011", f"Vrp outq outp DC 0 AC {acs['bp']}", "Lzp outp op0 0.8u", "Rco op0 op3 0.02", "Cop op3 0 2.2u", "Rlp op0 0 1e5", "Vop2 op2 op0 DC 0"]
    else:            # the ripple as an ideal source in series after the LDO's 2.2 uF: the datasheet's 5 mV whatever is added downstream
        t += ["Rop pa outp 0.011", "Lzp outp op0 0.8u", "Rco op0 op3 0.02", "Cop op3 0 2.2u", "Rlp op0 0 1e5", f"Vrp op2 op0 DC 0 AC {acs['bp']}"]
    rbn = 1e3; ran = rbn*(1/kn-1); czn = 1/(2*math.pi*psrr_zero*ran)
    t += [f"Rna v7 nsn {ran}", f"Cna v7 nsn {czn}", f"Rnb nsn 0 {rbn}", "En na ndc nsn 0 1", f"Vndc ndc 0 DC {-VN_MAX:.3f}"]
    if ripple_cal:
        t += ["Ron na outr 0.011", f"Vrn outr outn DC 0 AC {acs['bn']}", "Lzn outn on0 0.8u", "Rcn on0 on3 0.02", "Con on3 0 2.2u", "Rln on0 0 1e5", "Von2 on2 on0 DC 0"]
    else:
        t += ["Ron na outn 0.011", "Lzn outn on0 0.8u", "Rcn on0 on3 0.02", "Con on3 0 2.2u", "Rln on0 0 1e5", f"Vrn on2 on0 DC 0 AC {acs['bn']}"]
    # branches: one per stage + awg
    def branch(tag, rail, pin):
        # R2 what-if (nobead): the branch bead becomes a 1 ohm (the sense resistor's type)
        ser = f"Rbr{tag} {rail} br{tag} 1.0\n" if nobead else bead(tag+"r", rail, "br"+tag)
        return (ser + f"Rcx{tag} br{tag} br{tag}b {esr10}\nLcx{tag} br{tag}b br{tag}l {esl10+1e-15}\nCbr{tag} br{tag}l 0 {cval(br_c)*k33}\n")
    for (nm, mdl, inc, g) in STAGES:
        k = nm
        t += [branch(k, "op2", "pv"+k).rstrip(), f"Rpv{k} br{k} pv{k} 0.01", f"Cpv{k} pv{k} 0 {local}",
              f"Vb{k} bias{k} 0 DC 1.65", f"Vm{k} vm{k} 0 DC 1.65",
              f"Rn{k} bias{k} n{k} {SC_RTH:.6g}", f"Cn{k} n{k} 0 {SC_C1+SC_C2:.6g}", f"Rnp{k} n{k} np{k} {SC_RNP}",
              f"X{k} np{k} m{k} pv{k} 0 o{k} {mdl}"]
        # +-5 V range: the switch (Ron) shunts RF; +-1.25 V: RF; RG to Vmid on both (sim/scope "rf" topology)
        t += [f"Rf{k} o{k} m{k} {SC_RON if g == 1.0 else SC_RF}", f"Rg{k} m{k} vm{k} {SC_RG}"]
        t += [f"Rio{k} o{k} adc{k} {SC_RISO}", f"Cadc{k} adc{k} 0 8p"]
    # AWG: + pin via Schottky (optional), - pin via Schottky
    # AWG supply pins as in sim/awg (no bead): 10 uF at the rail, 22 || 22 ohm, 100 nF, series Schottky
    for i in range(nrail):     # the 10 uF on each LM27762 output (+3.3 V_A at op2, the negative rail at on2): C15850 with ESR and ESL
        t += [f"CbA{i} op2 cbA{i} {cval(br_c)*k33}", f"RcbA{i} cbA{i} cbAl{i} {esr10}", f"LcbA{i} cbAl{i} 0 {esl10+1e-15}",
              f"CbAn{i} on2 cbAn{i} {cval(br_c)*kneg}", f"RcbAn{i} cbAn{i} cbAnl{i} {esr10}", f"LcbAn{i} cbAnl{i} 0 {esl10+1e-15}"]
    t += [f"RflA op2 brA {AW_RFLT}", f"CwpA brA cwpA {local}", "RwpA cwpA 0 0.05",
          f"RflAn brAn on2 {AW_RFLT}", f"CwpAn brAn cwpAn {local}", "RwpAn cwpAn 0 0.05"]
    if sch: t += ["Dap brA awp DSCH", "Dan awn brAn DSCH"]
    else:   t += ["Rap brA awp 1m", "Ran awn brAn 1m"]
    t += ["Rawl awp awn 1.1k",
          # the DAC0 buffer: OPA365 follower on +3.3 V_A through its own Schottky + 100 nF (sim/loop BUF), input 680 ohm + 330k to Vmid
          "Vdac dacp 0 DC 1.65", "Rbin dacp dbi 680", "Rbpl dbi 0 330k", "DbsA op2 pvbuf DSCH", f"Cpvb pvbuf cpvb {local}", "Rcpvb cpvb 0 0.05",
          "Xdbuf dbi dac pvbuf 0 dac OPA365",
          f"Ra dac np {AW_RA}", f"Rb np 0 {AW_RB}",
          # the AWG's own Vmid (sim/awg variant buf, 2026-11-11): 330k / 330k 0.1 % off +3.3 V_A, 12 pF at the tap, an OPA365
          # follower with no output capacitor on its own BAT54S die + 100 nF.  +3.3 V_A ripple reaches it through the divider.
          "Rtvw op2 dvw 330k", "Rbvw dvw 0 330k", "Cdvw dvw 0 12p", "DbsW op2 pvvw DSCH", f"Cpvw pvvw cpvw {local}", "Rcpvw cpvw 0 0.05",
          "Xvw dvw vmw pvvw 0 vmw OPA365",
          "Xawg np mw awp awn oa OPA365", f"Rfa oa mw {AW_RF}", "Cfa oa mw 12p", f"Rga mw vmw {AW_RG}", f"Rout oa awgo {AW_RS}", "Rl awgo 0 1e6", "Cl awgo 0 20p"]
    nodes = ["v(v5)", "v(op2)", "v(on2)", "v(pvs354_g1)", "v(pvs365_g1)", "v(awp,awn)", "v(awp)", "v(awn)", "v(awgo)"] + \
            [f"v(adc{n})" for n, *_ in STAGES]
    t += [".ac dec 60 10k 20meg", ".control", "run", f"wrdata raw/ac_{stim}.txt " + " ".join(nodes), ".endc", ".end"]
    return "\n".join(t) + "\n", nodes

def cval(x):
    return x if isinstance(x, (int, float)) else float(x.replace("u", "e-6").replace("n", "e-9").replace("p", "e-12"))
def ac_run(stim, **kw):
    tag = "ac_" + stim + kw.pop("tag", "")
    txt, nodes = ac_netlist(stim, **kw)
    spice(tag, txt)
    if tag != "ac_" + stim: os.replace(f"raw/ac_{stim}.txt", f"raw/{tag}.txt")
    a = np.loadtxt(f"raw/{tag}.txt")
    f = a[:, 0]
    d = {nm: a[:, 1+3*i] + 1j*a[:, 2+3*i] for i, nm in enumerate(nodes)}
    return f, d

def tf_at(f, y, f0):
    """|y| at f0 by log-log interpolation"""
    return float(np.exp(np.interp(np.log(f0), np.log(f), np.log(np.abs(y)+1e-30))))

def spectrum(fund, a1, nmax):
    return [(fund*n, a1/n) for n in range(1, nmax+1) if fund*n <= 10.5e6]

def rms_resid(f, y, spec, band=None):
    return math.sqrt(sum((tf_at(f, y, fr)*a)**2/2 for fr, a in spec))

LDO_A1 = K("LDO ripple fundamental, pk", 5e-3, "LM27762 Fig 5-1: 0.5-5 mV vs load (graph, pk/pp unstated) -> 5 mV taken as PEAK, conservative")
BUCK_A1 = K("LM2734Y ripple fundamental at 5V pin, pk", 10e-3, "ASSUMED 20 mV pp (no measurement exists, afe.md 4.3); LM2734Y 3 MHz *(check)*")
LIM_SC6, LIM_AW6 = 0.2e-3, 0.1e-3
ALLOC = 0.10               # my allocation: supply residue <= 10 % of the SC-6 budget (0.5 % of its power)
LIM_P4B = 20e-6            # AWG output supply residue: 20 uV rms, 20 % of AW-6 (raised from 10 uV, accepted by montreal5 2026-11-11)
def run_p4(esr_split=True, **kw):
    """esr_split: the 10 uF's ESR is Samsung's 2 MHz value for the fundamental lines (below 3 MHz) and its 3-10.5 MHz maximum
    for the harmonics; both AC sets are run and stitched by frequency.  With esr10 given, one ESR for every line."""
    out = {}
    fa, da = ac_run("a", **kw); fb, dbp = ac_run("bp", **kw); _, dbn = ac_run("bn", **kw); fc, dc = ac_run("c", **{**kw, "rsrc": 1.0})
    if esr_split and kw.get("esr10") is None:
        tg = kw.get("tag", "") + "_hi"; kh = {**kw, "esr10": ESR10_HI, "tag": tg}
        _, dbph = ac_run("bp", **kh); _, dbnh = ac_run("bn", **kh); hi = fb >= 3e6
        dbp = {k: np.where(hi, dbph[k], v) for k, v in dbp.items()}; dbn = {k: np.where(hi, dbnh[k], v) for k, v in dbn.items()}
    stages = [s[0] for s in STAGES]
    if kw.get("ripple_cal"):   # source amplitude that puts the datasheet's 5 mV (/n) on 2.2 uF alone behind 11 mohm + 0.8 uH
        kcal = lambda fr: abs(0.011 + 2j*math.pi*fr*0.8e-6 + 0.02 + 1/(2j*math.pi*fr*2.2e-6))/abs(0.02 + 1/(2j*math.pi*fr*2.2e-6))
        dbp = {k: v*np.array([kcal(x) for x in fb]) for k, v in dbp.items()}; dbn = {k: v*np.array([kcal(x) for x in fb]) for k, v in dbn.items()}
    def lines_ldo(): return [(fs*n, LDO_A1/n) for fs in (1.7e6, 2.0e6, 2.3e6) for n in range(1, 6) if fs*n <= 10.5e6]
    res = {}
    for st in stages:
        key = f"v(adc{st})"
        # buck ripple (3 MHz fund), incoherent with LDO ripple (different line frequencies)
        rb = rms_resid(fa, da[key], spectrum(3e6, BUCK_A1, 3))
        # LDO: coherent worst-case sum of + and - rail contributions per line, worst switching frequency
        best = 0
        for fs in (1.7e6, 2.0e6, 2.3e6):
            tot = sum(((tf_at(fb, dbp[key], fs*n) + 0*tf_at(fb, dbn[key], fs*n))*LDO_A1/n)**2/2 for n in range(1, 6) if fs*n <= 10.5e6)
            best = max(best, tot)
        rl = math.sqrt(best)
        res[st] = dict(buck=rb, ldo=rl, total=math.hypot(rb, rl))
    # AWG output: both rails, coherent
    keyo = "v(awgo)"; best = 0
    for fs in (1.7e6, 2.0e6, 2.3e6):
        tot = sum(((tf_at(fb, dbp[keyo], fs*n) + tf_at(fb, dbn[keyo], fs*n))*LDO_A1/n)**2/2 for n in range(1, 6) if fs*n <= 10.5e6)
        best = max(best, tot)
    rb = rms_resid(fa, da[keyo], spectrum(3e6, BUCK_A1, 3))
    res["awg"] = dict(buck=rb, ldo=math.sqrt(best), total=math.hypot(rb, math.sqrt(best)))
    out["residue_rms"] = res
    # discrete spurs: each LDO line (2.0 MHz nominal; worst of 1.7/2.0/2.3 MHz per harmonic) and each assumed buck line, peak
    sp = {}
    for key, lab, both in [("v(awgo)", "awg", True)] + [(f"v(adc{st})", st, False) for st in stages]:
        rows = []
        for n in range(1, 6):
            if 2.0e6*n > 10.5e6: break
            amp = lambda fs: (tf_at(fb, dbp[key], fs*n) + (tf_at(fb, dbn[key], fs*n) if both else 0))*LDO_A1/n
            rows.append(dict(src="LDO", f=2.0e6*n, pk=amp(2.0e6), pk_worst_fs=max(amp(x) for x in (1.7e6, 2.0e6, 2.3e6))))
        for n in (1, 2, 3):
            rows.append(dict(src="buck (assumed)", f=3e6*n, pk=tf_at(fa, da[key], 3e6*n)*BUCK_A1/n, pk_worst_fs=None))
        sp[lab] = rows
    out["spurs"] = sp
    # pin ripple pk (PW-2), worst of every pin, sources added by magnitude
    pk = {}
    for pin in ("v(pvs354_g1)", "v(awp)", "v(awn)"):
        lp = max(sum(tf_at(fb, dbp[pin], fs*n)*LDO_A1/n for n in range(1, 6) if fs*n <= 10.5e6) +
                 sum(tf_at(fb, dbn[pin], fs*n)*LDO_A1/n for n in range(1, 6) if fs*n <= 10.5e6) for fs in (1.7e6, 2.0e6, 2.3e6))
        bk = sum(tf_at(fa, da[pin], 3e6*n)*BUCK_A1/n for n in (1, 2, 3))
        pk[pin] = dict(ldo=lp, buck=bk, total=lp+bk)
    out["pin_ripple_pk"] = pk
    # PW-4: AFE-added ripple at the 5V pin per amp of charge-pump input current, and in band 10 kHz-1 MHz
    z5 = np.abs(dc["v(v5)"])
    out["z5_2MHz"] = tf_at(fc, dc["v(v5)"], 2e6)
    band = (fc >= 10e3) & (fc <= 1e6)
    out["z5_band_max"] = float(z5[band].max()); out["z5_band_max_f"] = float(fc[band][np.argmax(z5[band])]); out["z5_curve_f"] = fc.tolist(); out["z5_curve"] = z5.tolist()
    out["rails_dc_check"] = None
    return out

def p4_cases(out, tag=""):
    res = out["residue_rms"]
    sc = max(res[s]["total"] for s in res if s != "awg"); aw = res["awg"]["total"]
    for s in res:
        pass
    case(f"P4-a{tag}", "SC-6 supply residue at the scope ADC pin (LM27762 2 MHz lines + assumed 3 MHz buck lines), both ranges, OPA354 and OPA365",
         f"<= {ALLOC*LIM_SC6*1e6:.0f} uV rms (my 10 % allocation of 0.2 mV)", f"{sc*1e6:.2f} uV rms", f"{(ALLOC*LIM_SC6-sc)*1e6:.1f} uV", sc <= ALLOC*LIM_SC6,
         f"= {sc/LIM_SC6*100:.2f} % of SC-6")
    case(f"P4-b{tag}", "AW-6 supply residue at the AWG output (both rails coherent + buck lines)",
         f"<= {LIM_P4B*1e6:.0f} uV rms (internal share of AW-6's 0.1 mV, 20 %, accepted 2026-11-11)", f"{aw*1e6:.2f} uV rms", f"{(LIM_P4B-aw)*1e6:.1f} uV", aw <= LIM_P4B,
         f"= {aw/LIM_AW6*100:.2f} % of AW-6")
    pk = max(v["total"] for v in out["pin_ripple_pk"].values())
    case(f"P4-c{tag}", "PW-2 ripple at the amplifier supply pins (all sources added by magnitude)", "<= 20 mV", f"{pk*1e3:.3f} mV pk",
         f"{20-pk*1e3:.2f} mV", pk <= 20e-3)

def p5_cases(out, tag=""):
    i_neg = (5.0 + 23.0)*1e-3             # charge pump carries the AWG op-amp quiescent + short-circuit current
    a = 4/math.pi*i_neg
    fc = out["z5_curve_f"]; zc = out["z5_curve"]
    v2 = a*out["z5_2MHz"]/math.sqrt(2)
    req = [(f, 20*math.log10(max(a*z/math.sqrt(2)/0.3e-3, 1e-9))) for f, z in zip(fc, zc) if 10e3 <= f <= 1e6]
    freq_req, db_req = max(req, key=lambda x: x[1])
    out["pw4"] = dict(i_cp_fund_pk=a, v5_rms_2MHz=v2, req_rej_db=db_req, req_rej_f=freq_req)
    case("P5-a" + tag, "PW-4 AFE-added ripple at the Due 5V pin from the charge pump (2 MHz line), before the Due's own 3.3 V regulator",
         "<= 0.3 mV rms at 3.3 V/AREF (rise <= added)", f"{v2*1e6:.2f} uV rms at the 5V pin at 2 MHz (0 dB regulator rejection assumed)",
         f"{(0.3e-3-v2)*1e6:.0f} uV", v2 <= 0.3e-3, "2 MHz is outside the DC-1 MHz test band; reported because the ADC aliases it" + (f"; P5-b's pulse-skipping case would need {db_req:.0f} dB of regulator rejection at {freq_req/1e3:.0f} kHz" if tag else ""))
    if tag: return
    case("P5-b", "PW-4 in-band (10 kHz-1 MHz) IF the pump pulse-skips at light load (datasheet Sec 6.3.3: can fall below 2 kHz)",
         "<= 0.3 mV rms with NO help from the Due's regulator", f"needs >= {db_req:.0f} dB of NCP1117 rejection at {freq_req/1e3:.0f} kHz; 0 dB gives {10**(db_req/20)*0.3:.1f} mV rms",
         "negative at 0 dB", False, "OPEN: closes only by VT-8 (pump mode at 5 mA is not in the datasheet, gap G3); rejection at 10 kHz-1 MHz not in repo *(check)*")

# =============================================================== P7 unpowered / back-feed (PR-2, PR-3, PR-4)
FEEDS = ("none", "schottky", "pfet_gate_gnd", "ideal_diode")
def feed_lines(kind, a, b):
    """series element in the 5 V feed between the Due's 5V pin node a and the AFE node b"""
    if kind == "none":          return f"Rfeed {a} {b} 1m"
    if kind == "schottky":      return f"Dfeed {a} {b} DSCH"
    if kind == "pfet_gate_gnd": return f"Mfeed {a} 0 {b} {b} PF\n.model PF PMOS(LEVEL=1 VTO=-0.9 KP=0.5 LAMBDA=0.01 IS=1e-10 RS=0.01 RD=0.01)"
    if kind == "ideal_diode":   return f"Sfeed {a} {b} {a} {b} SWI\n.model SWI SW(VT=0 VH=0.01 RON=0.05 ROFF=1e6)"
def p7_netlist(feed, stim, iso, powered=False, bleed=BLEED, vdue5=0.0, r3=SC_R3, r1=SC_R1):
    """stim: ('scope', volts) or ('awg', volts).  Due side = a voltage source (0 V = unpowered, treated as a short for max current)."""
    kind, v = stim
    ext = ("Vin in 0 DC {v}\n".format(v=v) if kind == "scope" else "Vext ext 0 DC {v}\n".format(v=v))
    t = [f"* P7 feed={feed} stim={stim} iso={iso} powered={powered}", f".include models/lm27762_beh.lib", f".include {OP365}", SCH,
         ".model DCL D(IS=1e-12 N=1.0 RS=2)",
         f"Vdue d5 0 DC {5.0 if powered else vdue5}", feed_lines(feed, "d5", "afe"),
         f"Rs afe v6 {RSENSE}", f"Rbd v6 vs {RBEAD+1e-3}", f"Cin vs 0 {C_BULK}",
         f"X1 vs vp vn vs vs LM27762B vp=3.34 vn={VN_MAX:.3f} tss=100u", "Cp vp 0 22u", "Cn vn 0 17u"]
    if not powered:
        t += [f"Rbleed vp 0 {bleed}"]
    else:
        t += [f"Rlp vp 0 {3.34/25e-3}"]
    # both scope channels (as built, PR-1/PR-3 2026-11-11: +-12 V on both inputs at once): R1 760k IN-N, R2 330k N-Vmid_k,
    # R3 760k N-sense node (249 ohm + 10 uF from the Due 3.3 V pin, shared), Rnp 680 to the op-amp (+), RG 249 to Vmid_k,
    # Riso 22 into the Due ADC pin.  Each channel has its own Vmid buffer: unpowered, its node is held only by that buffer's
    # ESD diodes.  Unpowered: the Due's 3.3 V pin held at 0 V (a short, like its 5V pin); powered: 3.3 V and Vmid 1.65 V.
    t += [ext, f"Rsf v3 d33 {RSF}", f"Csf v3 0 {CSF}", f"Vd33 d33 0 DC {3.3 if powered else 0.0}", ".model DESD D(IS=1e-14 N=1.05 RS=5)"]
    for k, sfx in ((1, ""), (2, "_2")):
        vin = "in" if kind == "scope" else f"in{sfx}x"
        if kind != "scope": t += [f"Rinx{sfx} {vin} 0 50"]          # an AWG test leaves the scope inputs terminated
        t += [f"R1{sfx} {vin} n{sfx} {r1}", f"R2{sfx} n{sfx} vmid{sfx} {SC_R2}", f"R3{sfx} n{sfx} v3 {r3}",
              (f"Vvm{sfx} vmid{sfx} 0 DC 1.65" if powered else f"Dvm1{sfx} vmid{sfx} vp DESD\nDvm2{sfx} 0 vmid{sfx} DESD\nRvl{sfx} vmid{sfx} 0 10Meg"),
              f"Rnpx{sfx} n{sfx} np1{sfx} {SC_RNP}", f"Rio{sfx} o{sfx} adc{sfx} {SC_RISO}", f"Dpin1{sfx} 0 adc{sfx} DCL", f"Dpin2{sfx} adc{sfx} 0 DCL", f"Cadc{sfx} adc{sfx} 0 8p"]
        if powered:
            t += [f"Xs{sfx} np1{sfx} m{sfx} vp 0 o{sfx} OPA365", f"Rf{sfx} o{sfx} m{sfx} {SC_RON}", f"Rg{sfx} m{sfx} vmid{sfx} {SC_RG}"]
        else:
            t += [f"Den1{sfx} np1{sfx} vp DESD", f"Den2{sfx} 0 np1{sfx} DESD", f"Deo1{sfx} o{sfx} vp DESD", f"Deo2{sfx} 0 o{sfx} DESD",
                  f"Rgu{sfx} m{sfx} vmid{sfx} {SC_RG}", f"Rfu{sfx} o{sfx} m{sfx} 1e9"]
    # AWG supply pins as in sim/awg: 10 uF at the rail, 22 || 22 ohm, 100 nF, then the series Schottky (iso) or 1 mohm
    t += ["Cbp vp cbp 10u", "Rcbp cbp 0 0.02", "Cbn vn cbn 10u", "Rcbn cbn 0 0.02", "Cbp2 vp cbp2 10u", "Rcbp2 cbp2 0 0.02", "Cbn2 vn cbn2 10u", "Rcbn2 cbn2 0 0.02",
          f"Rfp vp vpf {AW_RFLT}", "Cfp vpf 0 100n", f"Rfn vnf vn {AW_RFLT}", "Cfn vnf 0 100n"]
    if iso: t += ["Dap vpf awp DSCH", "Dan awn vnf DSCH"]
    else:   t += ["Rap vpf awp 1m", "Ran awn vnf 1m"]
    vplus0 = (AW_G-1)/AW_G*1.65                     # V+ that holds the AWG output at 0 V with Rg to Vmid 1.65 V
    if powered:
        t += [f"Vdacd np 0 DC {vplus0:.4f}", "Vmw vmw 0 DC 1.65",
              "Xa np ma awp awn oa OPA365", f"Rfa oa ma {AW_RF}", "Cfa oa ma 12p", f"Rga ma vmw {AW_RG}"]
    else:
        # unpowered: op-amps are only their ESD structures (diodes to the rails; model gap G6), outputs high-Z
        t += ["Dea1 oa awp DESD", "Dea2 awn oa DESD", "Dei1 np awp DESD", "Dei2 awn np DESD", f"Rnp np 0 {par(AW_RA, AW_RB):.6g}",
              "Rdvw vp 0 660k"]                     # the AWG's own Vmid divider on +3.3 V_A
    t += [f"Rout oa awgo {AW_RS}", ("Rext ext awgo 1m" if kind == "awg" else "Rl awgo 0 1e6")]
    t += [".option gmin=1e-12 reltol=1e-3 itl1=500", ".tran 20u 400m uic" if not powered else ".tran 5u 5m",
          ".control", "run",
          "meas tran vp_e find v(vp) at=0.399" if not powered else "meas tran vp_e find v(vp) at=4.9m",
          "meas tran vn_e find v(vn) at=0.399" if not powered else "meas tran vn_e find v(vn) at=4.9m",
          "meas tran vafe_e find v(afe) at=0.399" if not powered else "meas tran vafe_e find v(afe) at=4.9m",
          "meas tran idue_e find i(Vdue) at=0.399" if not powered else "meas tran idue_e find i(Vdue) at=4.9m",
          "meas tran id33_e find i(Vd33) at=0.399" if not powered else "meas tran id33_e find i(Vd33) at=4.9m",
          "meas tran adc_min min v(adc)", "meas tran adc_max max v(adc)", "meas tran adc2_min min v(adc_2)", "meas tran adc2_max max v(adc_2)",
          "meas tran awp_e find v(awp) at=0.399" if not powered else "meas tran awp_e find v(awp) at=4.9m",
          "meas tran awn_e find v(awn) at=0.399" if not powered else "meas tran awn_e find v(awn) at=4.9m",
          ".endc", ".end"]
    return "\n".join(t) + "\n"

def run_p7():
    def row(lg, **kw):
        return dict(**kw, vp=meas(lg, "vp_e"), vn=meas(lg, "vn_e"), vafe=meas(lg, "vafe_e"), i_due=-meas(lg, "idue_e"), i_d33=-meas(lg, "id33_e"),
                    adc_min=min(meas(lg, "adc_min"), meas(lg, "adc2_min")), adc_max=max(meas(lg, "adc_max"), meas(lg, "adc2_max")), awp=meas(lg, "awp_e"), awn=meas(lg, "awn_e"))
    meta = []; jobs = []
    for feed in FEEDS:
        for stim in (("scope", 12), ("scope", -12), ("awg", 5), ("awg", -5)):
            meta.append(dict(feed=feed, stim=f"{stim[0]} {stim[1]:+d} V", iso=True)); jobs.append((f"p7_{feed}_{stim[0]}_{stim[1]}_iso", p7_netlist(feed, stim, True)))
    for feed in FEEDS:
        for stim in (("awg", 5), ("awg", -5)):
            meta.append(dict(feed=feed, stim=f"awg {stim[1]:+d} V", iso=False)); jobs.append((f"p7_{feed}_{stim[0]}_{stim[1]}_noiso", p7_netlist(feed, stim, False)))
    rows = [row(lg, **m) for m, lg in zip(meta, spice_many(jobs))]
    R["p7"] = rows
    st = (("awg", 5), ("awg", -5), ("awg", 0))
    logs = spice_many([(f"p7_powered_{x[1]}", p7_netlist("none", x, True, powered=True)) for x in st])
    R["p7_powered"] = [dict(stim=f"{x[1]:+d} V", i_due=-meas(lg, "idue_e"), vp=meas(lg, "vp_e"), vn=meas(lg, "vn_e"),
                            awp=meas(lg, "awp_e"), awn=meas(lg, "awn_e")) for x, lg in zip(st, logs)]
    return rows

def p7_cases():
    rows = R["p7"]
    def sel(feed, iso, pref):
        return [r for r in rows if r["feed"] == feed and r["iso"] == iso and r["stim"].startswith(pref)]
    rec = "none"      # recommended: no element in the 5 V feed; isolation Schottkys on the AWG op-amp pins; 4.7 k bleed on +3.3 V
    s30 = sel(rec, True, "scope"); a5 = sel(rec, True, "awg")
    wr = max(max(abs(r["vp"]), abs(r["vn"])) for r in s30); wi = max(abs(r["i_due"]) for r in s30); wi33 = max(abs(r["i_d33"]) for r in s30)
    wpin_lo = min(r["adc_min"] for r in s30+a5); wpin_hi = max(r["adc_max"] for r in s30+a5)
    case("P7-a", "PR-3 Due unpowered, +-12 V on both scope inputs at once (16 uA through each R1): AFE rails", "< 0.5 V", f"{wr:.3f} V", f"{0.5-wr:.3f} V", wr < 0.5)
    case("P7-b", "PR-3 same: current into the Due's supply pins (5V pin; 3.3 V pin through R3 and the sense filter)", "<= 100 uA each", f"{wi*1e6:.2f} uA into 5V, {wi33*1e6:.2f} uA into 3.3 V", f"{100-max(wi, wi33)*1e6:.1f} uA", max(wi, wi33) <= 100e-6,
         "the Due's 3.3 V pin is held at 0 V (a short), its worst case")
    case("P7-c", "PR-2 ADC pin and DAC pin voltage, all unpowered cases", "-0.2 .. 3.45 V", f"{wpin_lo:.3f} .. {wpin_hi:.3f} V", f"{0.2+wpin_lo:.3f} V", wpin_lo >= -0.2 and wpin_hi <= 3.45,
         "Due-pin clamps and the unpowered op-amp output are models (gap G6)")
    wr4 = max(max(abs(r["vp"]), abs(r["vn"])) for r in a5); wi4 = max(abs(r["i_due"]) for r in a5)
    pins = max(max(abs(r["awp"]), abs(r["awn"])) for r in a5)
    case("P7-d", "PR-4 unpowered, +-5 V on the AWG output: AFE main rails", "< 0.5 V (PR-3 limits)", f"{wr4:.3f} V (op-amp pins reach {pins:.2f} V, isolated by the series Schottkys)", f"{0.5-wr4:.3f} V", wr4 < 0.5)
    case("P7-e", "PR-4 unpowered, +-5 V on the AWG output: current into the Due's 5V pin", "<= 100 uA", f"{wi4*1e6:.2f} uA", f"{100-wi4*1e6:.1f} uA", wi4 <= 100e-6)
    # the isolation is what does it
    bad = max(abs(r["i_due"]) for r in rows if (not r["iso"]) and r["feed"] == "none")
    badv = max(max(r["vp"], -r["vn"]) for r in rows if (not r["iso"]) and r["feed"] in ("schottky", "ideal_diode"))
    R["p7_no_iso_none_idue"] = bad; R["p7_no_iso_blocking_vp"] = badv
    pw = {r["stim"]: r for r in R["p7_powered"]}
    ext = max(pw["+5 V"]["i_due"], pw["-5 V"]["i_due"]); base0 = pw["+0 V"]["i_due"]
    R["p7_ext_delta_mA"] = (ext-base0)*1e3
    return ext, base0

def p3_ext_case(ext_delta_ma):
    """P3-b redone with the powered-simulation increment (op-amp model delivers >65 mA through 50 ohm)"""
    for variant, sc in (("OPA365 scope", 5.0), ("OPA354 scope", 6.3)):
        base = sum(budget(sc).values())
        tot = base + max(ext_delta_ma, 65.0)
        case(f"P3-c [{variant}]", "Due 300 mA + AFE with +-5 V on the AWG output powered (PR-4; exempt from PW-3; afe.md judges the fault against PW-1's 450 mA), maxima + simulated increment",
             f"<= {LIM_FAULT_MA:.0f} mA", f"{300+tot:.1f} mA (AFE {tot:.1f}: base {base:.1f} + {max(ext_delta_ma, 65.0):.1f})", f"{LIM_FAULT_MA-300-tot:.1f} mA", 300+tot <= LIM_FAULT_MA,
             "set by 5 V / 50 ohm, not by the AFE rails; above the 400 mA normal-operation target, which a fault is not held to")

# =============================================================== P8 Vmid: AN-4 centring, output impedance, noise, crosstalk
# Vmid generator: Rt = Rb = rdiv from the Due 3.3 V pin, cdv at the tap, OPA365 follower, riso to the Vmid node,
# DC feedback from the node through rfb, HF feedback from the buffer output through cfb, cd1 (ESR 5 mohm) + 100 nF at the node
VM_OLD = dict(rfb=1e3, cfb=1.5e-9, riso=1.0, cd1=10e-6, esr1=0.005, rdiv=330e3, tol=0.01, cdv=10e-6)   # v1-basic: Vmid divider Basic 1 % (was tol=0.001). M-7 + M-10 approved 2026-11-11
# 2026-11-11, the owner's condition (SM-5 loop run: the per-channel Vmid added 0.26 codes): the per-channel loop is stiffened
# for a peak under ~0.3 ohm from 1 kHz to 1 MHz, existing types only: isolation 5 x 1R in parallel (0.2 ohm), DC feedback
# 4.7k, HF feedback 2 x 1.5 nF X7R (C1595), 2 x 10 uF (C15850, 2.5 mohm ESR together, assumed *(check)*) + 100 nF at the node.
VM_OPA = dict(VM_OLD, rfb=4.7e3, cfb=3.0e-9, riso=0.2, cd1=20e-6, esr1=0.0025)     # the stiffened OPA365 loop (previous design)
# 2026-11-11 (owner, C): both scope Vmid buffers in one TLV9062 (C398355), with whatif/lowcost-scope/vmid's loop: isolation
# 4 x 1R in parallel (0.25 ohm), DC feedback 4.7k, HF feedback 1 uF, 6 x 10 uF (C15850) + 100 nF at each channel's node.
# The buffer is the behavioural stand-in fitted there to TI's TLV9062 model (fit_tlv.json: GBW 15 MHz, Rout 150 ohm, second
# pole 40 MHz, A0 120 dB; within 0.59 % of TI's loop impedance, 1 Hz-1 MHz), because TI's model needs PSpice compatibility
# mode and does not converge beside the OPA354 model in ngspice 47.  The AWG's own Vmid follower stays an OPA365 (sim/awg).
VM = dict(VM_OLD, rfb=4.7e3, cfb=1e-6, riso=0.25, cd1=60e-6, esr1=0.005/6)
VM_NCAP = 6
VBUF = "tlv"
MCP_OPEN = "../../models-open/mcp6002/mcp6002_open.lib"
TLV_SI = "gbw=15e6 ro=150 fp2=40e6 a0db=120"
def buf_inst(nm, inp, inm, vdd, out, buf):
    if buf == "tlv":
        return f"X{nm} {inp} {inm} {vdd} 0 {out} MCP6002_OPEN params: {TLV_SI}"
    return f"X{nm} {inp} {inm} {vdd} 0 {out} OPA365"
LIM_ZVM = 0.30              # owner's target for the per-channel Vmid impedance peak, 1 kHz-1 MHz
# Cfb: 1.5 nF X7R 50 V 0603, FH 0603B152K500NT, LCSC C1595 (Basic), replacing the 1.6 nF C0G (approved option (a), 2026-11-11).
# It sits between the buffer output and its feedback node, both at Vmid, so its DC bias is ~0 V and the voltage coefficient
# does not enter; its tolerance (+-10 %, page) and X7R's +-15 % over temperature do: 1.15-1.90 nF is swept.
VM_LOOPS = {"design: Rfb 1 k, Cfb 1.6 nF": {},
            "M-4: Rfb 953 ohm (0.1 %), Cfb 1.6 nF": dict(rfb=953.0),
            "M-5: Rfb 10 + 10 ohm, Cfb 100 nF": dict(rfb=20.0, cfb=100e-9),
            "sensitivity: design with the 10 uF at 25 % (DC bias, *(check)*)": dict(cd1=10e-6*C10_DERATE)}
AWGP = {}                   # AWG -> scope through Vmid, per frequency (f, volts at the pin), by Vmid arrangement
LIM_AWG_XT = 2*LSB12        # AWG -> scope coupling while DAC0 plays: SC-9's 2 LSB (afe.md, 2026-11-11), also through the off injection switch
I_STEP = SC_ALPHA*5.0/SC_RG             # full-scale +-5 V input: the RG current one channel pushes into Vmid (4.64 mA)
def vmid_netlist(kind, name, **kw):
    v = {**VM_OLD, **kw}             # the one shared buffer: kept as the previous arrangement, with its own loop
    base = f""".include {OP365}
* Vmid generator: {v}
Vdd vp 0 DC 3.34
V33 v33 0 DC 3.3
Rt v33 dv {v['rdiv']}
Rb dv 0 {v['rdiv']}
Cdv dv 0 {v['cdv']}
Xb dv fb vp 0 bo OPA365
Rfb vmid fb {v['rfb']}
Cfb bo fb {v['cfb']}
Riso bo vmid {v['riso']}
Cd1 vmid c1 {v['cd1']}
Resr1 c1 0 {v['esr1']}
Cd2 vmid c2 100n
Resr2 c2 0 0.03
"""
    if kind == "z":
        return base + f"Iac 0 vmid DC 0 AC 1\n.ac dec 40 1k 10meg\n.control\nrun\nwrdata raw/{name}.txt v(vmid)\n.endc\n.end\n"
    # step: the full-scale RG current of one channel switched into the node in 10 ns
    return base + f"Ist 0 vmid PWL(0 0 200u 0 200.01u {I_STEP})\n.tran 20n 800u\n.control\nrun\nwrdata raw/{name}.txt v(vmid)\n.endc\n.end\n"

def xt_paths(f, z, rsf=RSF):
    """SC-9 crosstalk at the victim's ADC pin, worst over aggressor/victim range, per frequency (volts).
    Vmid path: the aggressor's N moves by alpha*Vfs and drives (1/RG + Y2) into Vmid; the victim sees Vmid through
    Y2/(Y1+Y2+Y3) at N, and on +-1.25 V through its own RG: G*c - (G-1).  Sense path: the aggressor's R3 current moves the
    sense node through RSF || CSF; the victim sees it through Y3/(Y1+Y2+Y3) (x G on +-1.25 V)."""
    w = 2*np.pi*f
    Y1 = 1/SC_R1 + 1j*w*SC_C1; Y2 = 1/SC_R2 + 1j*w*SC_C2; Y3 = 1/SC_R3
    cv = Y2/(Y1+Y2+Y3); cs = Y3/(Y1+Y2+Y3)
    zs = 1/(1/rsf + 1j*w*CSF)
    vm = np.zeros_like(f); se = np.zeros_like(f)
    for vfs in (5.0, 1.25):
        I = SC_ALPHA*vfs*(1/SC_RG + Y2)
        for vc_vm, vc_s in ((np.abs(cv), np.abs(cs)), (np.abs(SC_G*cv-(SC_G-1)), SC_G*np.abs(cs))):
            vm = np.maximum(vm, np.abs(I*z)*vc_vm)
            se = np.maximum(se, np.abs(SC_ALPHA*vfs/SC_R3*zs)*vc_s)
    # the sense path is largest at DC (the 10 uF shorts it above a few Hz) and the AC grid starts at 1 kHz: add DC
    cs0 = (1/SC_R3)/(2/SC_R1 + 1/SC_R2)
    se_dc = SC_ALPHA*5.0/SC_R3*rsf*cs0*SC_G
    se = np.maximum(se, se_dc)
    return vm, se

def run_p8():
    names = list(VM_LOOPS)
    jobs = []
    for i, nm in enumerate(names):
        jobs += [(f"p8_vmid_z{i}", vmid_netlist("z", f"vmid_z{i}", **VM_LOOPS[nm])), (f"p8_vmid_step{i}", vmid_netlist("step", f"vmid_step{i}", **VM_LOOPS[nm]))]
    spice_many(jobs)
    lsb = LSB12; out = {}
    for i, nm in enumerate(names):
        a = np.loadtxt(f"raw/vmid_z{i}.txt"); f = a[:, 0]; z = a[:, 1] + 1j*a[:, 2]
        vm, se = xt_paths(f, z)
        b = np.loadtxt(f"raw/vmid_step{i}.txt"); t = b[:, 0]; v = b[:, 1]
        v0 = float(np.interp(199e-6, t, v)); after = t >= 200e-6; dv = v[after]-v0; ta = t[after]
        ip = int(np.argmax(np.abs(dv))); pk = dv[ip]; vfin = float(dv[-1])
        opp = float(np.max(-np.sign(pk)*dv[ip:])) if ip < len(dv)-1 else 0.0          # excursion past the final value, opposite sign
        bad = np.where(np.abs(dv - vfin) > 0.5*lsb)[0]
        tset = float(ta[bad[-1]] - 200e-6) if len(bad) else 0.0
        az = np.abs(z)
        out[nm] = dict(z1k=float(az[0]), zmax=float(az.max()), fzmax=float(f[np.argmax(az)]), z10M=float(az[-1]),
                       xt_vmid=float(vm.max()), f_xt=float(f[np.argmax(vm)]), xt_sense=float(se.max()), xt=float(vm.max()+se.max()),
                       step_pk_mV=float(pk*1e3), step_final_mV=vfin*1e3, step_opp_mV=opp*1e3, step_opp_pct=abs(opp/pk)*100 if pk else 0.0, settle_us=tset*1e6,
                       zmax_allowed=float(2*lsb/(I_STEP*abs(SC_G*(1/SC_R2)/(2/SC_R1+1/SC_R2)-(SC_G-1)))))
        if i == 0: R["p8_z"] = dict(f=f.tolist(), z=az.tolist())
    R["p8_loops"] = out
    d = out[names[0]]
    case("P8-a", "SC-9 channel crosstalk through the shared Vmid node and the shared 3.3 V sense node, full-scale input (+-5 V or +-1.25 V) on the other channel, 1 kHz-10 MHz, RF 953 / RG 249",
         f"<= 2 LSB = {2*lsb*1e3:.2f} mV at the pin", f"{d['xt']*1e3:.2f} mV = {d['xt']/lsb:.2f} LSB (Vmid path {d['xt_vmid']/lsb:.2f} LSB at {d['f_xt']/1e3:.0f} kHz, sense path {d['xt_sense']/lsb:.2f} LSB at DC)",
         f"{(2*lsb-d['xt'])*1e3:.2f} mV", d["xt"] <= 2*lsb,
         f"one channel's RG pushes up to {I_STEP*1e3:.2f} mA into Vmid (RG 249, was 1 k); the Vmid path passes only if |Z| stays under {d['zmax_allowed']:.2f} ohm at every frequency. "
         "A Vmid buffer per channel (one more OPA365 placement, no new type) removes the shared-node path")
    case("P8-b", "Vmid output impedance 1 kHz-10 MHz (it is the AC ground for R2, RG and the AWG's Rg)", "reported (no numeric requirement)",
         f"{d['z1k']*1e3:.0f} mohm at 1 kHz, max {d['zmax']:.2f} ohm at {d['fzmax']/1e3:.0f} kHz, {d['z10M']:.2f} ohm at 10 MHz", "-", True)
    case("P8-g", f"Vmid step response: {I_STEP*1e3:.2f} mA (one channel's full-scale RG current) switched into the node in 10 ns",
         "reported: peak, opposite-sign excursion (ringing), settling to 0.5 LSB", f"peak {d['step_pk_mV']:.2f} mV, opposite excursion {d['step_opp_pct']:.0f} % of the peak, settles to 0.5 LSB in {d['settle_us']:.1f} us", "-", True)
    for nm in names[1:]:
        x = out[nm]; tag = nm.split(":")[0]
        case(f"P8-a [{tag}]", f"SC-9 crosstalk as P8-a with {nm}", f"<= 2 LSB", f"{x['xt']/lsb:.2f} LSB (Vmid {x['xt_vmid']/lsb:.2f} at {x['f_xt']/1e3:.0f} kHz); |Z| max {x['zmax']:.2f} ohm at {x['fzmax']/1e3:.0f} kHz; "
             f"step peak {x['step_pk_mV']:.2f} mV, opposite {x['step_opp_pct']:.0f} %, settle {x['settle_us']:.1f} us", f"{(2*lsb-x['xt'])/lsb:.2f} LSB", x["xt"] <= 2*lsb,
             f"design reads {d['xt']/lsb:.2f} LSB, |Z| {d['zmax']:.2f} ohm, step opposite {d['step_opp_pct']:.0f} %")
    a = np.loadtxt("raw/vmid_z0.txt"); f = a[:, 0]; z = a[:, 1] + 1j*a[:, 2]
    # AWG -> scope through Vmid: the AWG's Rg 249 carries out/(G*Rg) into Vmid at AW-1's +-1 V
    I_awg = 1.0/(AW_G*AW_RG); w = 2*np.pi*f
    Y1 = 1/SC_R1 + 1j*w*SC_C1; Y2 = 1/SC_R2 + 1j*w*SC_C2; Y3 = 1/SC_R3; cv = Y2/(Y1+Y2+Y3)
    xa = np.abs(I_awg*z)*np.maximum(np.abs(cv), np.abs(SC_G*cv-(SC_G-1)))
    AWGP["one shared Vmid buffer"] = (f, xa)
    R["p8_awg_xt"] = dict(I_mA=I_awg*1e3, xt_mV=float(xa.max()*1e3), f=float(f[np.argmax(xa)]), lsb=float(xa.max()/lsb))
    case("P8-f", "AWG -> scope through the shared Vmid node: the AWG's Rg return carries out/(G*Rg) at +-1 V (AW-1)",
         "<= 2 LSB at the scope pin (SC-9, AWG while DAC0 plays)", f"{I_awg*1e3:.2f} mA -> {xa.max()*1e3:.2f} mV = {xa.max()/lsb:.2f} LSB at {f[np.argmax(xa)]/1e3:.0f} kHz",
         f"{(LIM_AWG_XT-xa.max())/lsb:.2f} LSB", xa.max() <= LIM_AWG_XT, "the same shared-node mechanism as P8-a")
    # noise: ngspice .noise aborts on the TI JFET model, so the bound is analytic from datasheet figures
    en = 10e-9; bw = 10e6                       # TLV9062 10 nV/rtHz at 10 kHz (Sec 6.5), white to 10 MHz assumed *(1/f corner check)*
    kT = 1.380649e-23*300
    coef = abs(SC_G*(1/SC_R2)/(2/SC_R1+1/SC_R2)-(SC_G-1))       # victim pin per volt of Vmid at DC, +-1.25 V range (1.23)
    noise_rows = {}
    for lab, cdv in (("1 uF at the tap (design)", 1e-6), ("10 uF at the tap (M-10)", 10e-6)):
        n_div = math.sqrt(kT/cdv); n_op = en*math.sqrt(bw); tot = math.hypot(n_op, n_div)
        noise_rows[lab] = dict(op_rms=n_op, divider_rms=n_div, total_rms=tot, at_pin=tot*coef)
    R["p8_noise"] = noise_rows
    nd = noise_rows["1 uF at the tap (design)"]
    case("P8-e", f"Vmid reference noise at the ADC pin (upper bound, buffer white to 10 MHz; x{coef:.2f} on +-1.25 V, the victim coefficient at DC)",
         "informational; SC-6 allows 0.2 mV for ALL sources", f"{nd['total_rms']*1e6:.1f} uV at Vmid, {nd['at_pin']*1e6:.1f} uV at the pin = {nd['at_pin']/LIM_SC6*100:.0f} % of SC-6 amplitude; divider kT/C {nd['divider_rms']*1e9:.0f} nV (1 uF), {noise_rows['10 uF at the tap (M-10)']['divider_rms']*1e9:.0f} nV (10 uF)",
         "-", True, "noise analysis not run: ngspice .noise aborts on the TI model; closes by VT-3/VT-16")
    case("P8-l", "SC-9 through the TLV9062 package: one half's output excursion coupled into the other (channel separation 100 dB at DC, TLV9062 datasheet Sec 6.5; no AC figure read)",
         "<= 2 LSB", "an aggressor Vmid excursion of a few mV (P8-a's own-node figure) x 1e-5 = tens of nV", "-", True,
         "separation at the loop's 10-100 kHz peak is not tabulated *(check: the datasheet's crosstalk graph)*; the shared supply pin is held by the +3.3 V_A decoupling")
    # start-up of the divider tap and the sense current, per divider choice
    st = {}
    for lab, rd, cdv in (("2 x 100k, 1 uF (design)", 100e3, 1e-6), ("2 x 100k, 10 uF (M-10)", 100e3, 10e-6), ("2 x 330k, 1 uF (M-7)", 330e3, 1e-6), ("2 x 330k, 10 uF (M-7 + M-10)", 330e3, 10e-6)):
        tau = rd/2*cdv
        st[lab] = dict(tau_s=tau, t_half_lsb_s=tau*math.log(1.65/(0.5*LSB12)), i_div_uA=3.3/(2*rd)*1e6, ib_err_uV=10e-12*rd/2*1e6)
    R["p8_startup"] = st
    return z, f

def an4_mc(rdiv=VM["rdiv"], tol_div=VM["tol"], rsf=RSF, delta=0.5e-3, aref_fixed=None, N=200000, tol_net=0.01, rsf_tol=0.0):
    """worst centring error at the ADC pin over both ranges and V33 3.10-3.30 V (3.10 is margin evidence).
    Vmid = buffered divider of the Due 3.3 V pin (+ OPA365 VOS 200 uV max and IB 10 pA x the divider's Thevenin);
    N at 0 V in = (Vmid/R2 + Vs/R3)/(1/R1+1/R2+1/R3); Vs = the sense node, 3.3 V pin minus RSF x (own R3 current at the
    centre + the other channel's anywhere from 0 to full); R1-R3, RF, RG 0.1 %; the scope op-amp's own offset is not a
    reference term (sim/scope's SC-2 rows carry it)."""
    e = []
    u = lambda tol: rng.uniform(-tol, tol, N)
    for v33 in (3.10, 3.20, 3.25, 3.30):
        rt = rdiv*(1+u(tol_div)); rb = rdiv*(1+u(tol_div))
        vmid = v33*rb/(rt+rb) + u(2e-3) + u(10e-12*rdiv/2)            # TLV9062 VOS 2 mV max (-40..125 C, VS 5 V; no 3.3 V row)
        r1 = SC_R1*(1+u(tol_net)); r2 = SC_R2*(1+u(tol_net)); r3 = SC_R3*(1+u(tol_net)); g = 1 + SC_RF*(1+u(tol_net))/(SC_RG*(1+u(tol_net)))   # v1-basic: tol_net (was 0.001)
        i_s = (v33-1.65)/SC_R3 + rng.uniform(0, v33/SC_R3, N)
        vs = v33 - i_s*rsf*(1+u(rsf_tol)) if rsf_tol else v33 - i_s*rsf
        n0 = (vmid/r2 + vs/r3)/(1/r1 + 1/r2 + 1/r3)
        aref = (v33 - delta) if aref_fixed is None else aref_fixed
        for pin in (n0, g*n0 - (g-1)*vmid):
            e.append(np.abs(pin - aref/2))
    return float(np.max(e))

# ---- fix for P8-a with no new part type: one Vmid buffer per channel (OPA365 and its loop parts, all existing types),
# both fed from the one divider tap.  Channel 1's RG current goes into node vm1; channel 2 reads vm2.
def vmid2_netlist(kind, name, **kw):
    v = {**VM, **kw}; buf = v.pop("buf", VBUF)
    t = [f".include {OP365}", f".include {MCP_OPEN}", f"* two Vmid buffers on one divider tap ({buf}): {v}", "Vdd vp 0 DC 3.34", "V33 v33 0 DC 3.3",
         f"Rt v33 dv {v['rdiv']}", f"Rb dv 0 {v['rdiv']}", f"Cdv dv 0 {v['cdv']}"]
    for i in (1, 2):
        t += [buf_inst(f"b{i}", "dv", f"fb{i}", "vp", f"bo{i}", buf), f"Rfb{i} vm{i} fb{i} {v['rfb']}", f"Cfb{i} bo{i} fb{i} {v['cfb']}", f"Riso{i} bo{i} vm{i} {v['riso']}",
              f"Cd1{i} vm{i} c1{i} {v['cd1']}", f"Resr1{i} c1{i} 0 {v['esr1']}", f"Cd2{i} vm{i} c2{i} 100n", f"Resr2{i} c2{i} 0 0.03"]
    if kind == "z":
        t += ["Iac 0 vm1 DC 0 AC 1", ".ac dec 40 1k 10meg", ".control", "run", f"wrdata raw/{name}.txt v(vm1) v(vm2)", ".endc", ".end"]
    else:
        t += [f"Ist 0 vm1 PWL(0 0 200u 0 200.01u {I_STEP})", ".tran 20n 800u", ".control", "run", f"wrdata raw/{name}.txt v(vm1) v(vm2)", ".endc", ".end"]
    return "\n".join(t) + "\n"

VM2_LOOPS = {"Vmid x2": {},
             "Vmid x2, Cfb X7R low (1 uF -10 % -15 %)": dict(cfb=1e-6*0.9*0.85),
             "Vmid x2, Cfb X7R high (1 uF +10 % +15 %)": dict(cfb=1e-6*1.1*1.15),
             "Vmid x2, the 6 x 10 uF at 1.65 V bias (Samsung data, -10 %)": dict(cd1=60e-6*K10_165),
             "Vmid x2, stiffened OPA365 loop (previous design)": dict(VM_OPA, buf="opa365"),
             "Vmid x2, previous loop (1R, 1k, 1.5 nF, 1 x 10 uF)": dict(riso=1.0, rfb=1e3, cfb=1.5e-9, cd1=10e-6, esr1=0.005, buf="opa365")}

def vmid_pm_netlist(name, **kw):
    """loop gain of one per-channel buffer: voltage injected between the feedback node and the inverting input"""
    v = {**VM, **kw}; buf = v.pop("buf", VBUF)
    t = [f".include {OP365}", f".include {MCP_OPEN}", "Vdd vp 0 DC 3.34", "Vdv dv 0 DC 1.65", buf_inst("b", "dv", "inm", "vp", "bo", buf), f"Riso bo vm {v['riso']}",
         f"Rfb vm fb {v['rfb']}", f"Cfb bo fb {v['cfb']}", f"Cd1 vm c1 {v['cd1']}", f"Resr1 c1 0 {v['esr1']}", f"Cd2 vm c2 {v.get('cd2', '100n')}", "Resr2 c2 0 0.03",
         "Vbr inm fb DC 0 AC 1", ".ac dec 40 100 200meg", ".control", "run", f"wrdata raw/{name}.txt v(fb) v(inm)", ".endc", ".end"]
    return "\n".join(t) + "\n"
def pm_of(name):
    b = np.loadtxt(f"raw/{name}.txt"); f = b[:, 0]; T = -(b[:, 1]+1j*b[:, 2])/(b[:, 4]+1j*b[:, 5])
    m = np.abs(T); ph = np.degrees(np.angle(T)); idx = np.where(np.diff(np.sign(m-1)) != 0)[0]
    return [float((180+ph[i]) % 360) for i in idx], [float(f[i]) for i in idx]

def zlin(f, A0, gbw, rout, riso, rfb, cfb, caps, fp2=None):
    """linear stand-in for the loop agent: the buffer as A0 / (1 + s A0 / (2 pi GBW)) [/ (1 + s / 2 pi fp2)^2] behind an open-loop output resistance"""
    out = []
    for fr in f:
        sx = 2j*np.pi*fr; A = A0/(1 + sx*A0/(2*np.pi*gbw)); A = A/(1 + sx/(2*np.pi*fp2))**2 if fp2 else A; Yc = sum(1/(e + 1/(sx*c)) for c, e in caps)
        M = np.array([[1, 0, A, 0], [-1/rout, 1/rout + 1/riso + sx*cfb, -sx*cfb, -1/riso], [0, -sx*cfb, sx*cfb + 1/rfb, -1/rfb],
                      [0, -1/riso, -1/rfb, 1/riso + 1/rfb + Yc]], complex)
        out.append(np.linalg.solve(M, np.array([0, 0, 0, 1], complex))[3])
    return np.array(out)

# corners of the stiffened loop from Samsung's data: the 10 uF at 1.65 V of bias with -10 % tolerance, or nominal; its ESR at
# 200 kHz, 5 mohm (the design value) and at 22 kHz (the loop's impedance peak), per capacitor; the X7R Cfb at +-23.5 %
VML_GRID = [(ck, dr, es) for ck in (0.765, 1.0, 1.265) for dr in (round(K10_165, 4), 1.0) for es in (round(SAM["esr"](2e5), 5), 0.005, round(SAM["esr"](2.2e4), 5))]
def run_vmid_loop():
    """the stiffened per-channel loop: impedance peak and phase margin over the X7R, the 10 uF's DC bias and its ESR"""
    grid = VML_GRID
    jobs = []
    for i, (ck, dr, es) in enumerate(grid):
        kw = dict(cfb=VM["cfb"]*ck, cd1=VM["cd1"]*dr, esr1=es/VM_NCAP)
        jobs += [(f"p8_vml_z{i}", vmid_netlist_pc_z(f"vml_z{i}", **kw)), (f"p8_vml_t{i}", vmid_pm_netlist(f"vml_t{i}", **kw))]
    # previous loop, and two guards: no isolation (riso 1 mohm) and the HF feedback cut to 12 pF
    extra = {"prev": dict(riso=1.0, rfb=1e3, cfb=1.5e-9, cd1=10e-6, esr1=0.005, buf="opa365"), "opa_stiff": dict(VM_OPA, buf="opa365"),
             "g_noiso": dict(riso=1e-3), "g_cfb12p": dict(cfb=12e-12),
             "awg_follower": dict(riso=1e-3, rfb=1e-3, cfb=1e-15, cd1=1e-15, esr1=1.0, cd2="1f", buf="opa365"),           # sim/awg buf: a plain follower, no output capacitor
             "direct_10u": dict(riso=1e-3, rfb=1e-3, cfb=1e-15, cd1=10e-6, esr1=0.005, buf="opa365")}           # sim/awg's flagged case: follower straight into 10 uF + 100 nF
    for k, kw in extra.items():
        jobs += [(f"p8_vml_z_{k}", vmid_netlist_pc_z(f"vml_z_{k}", **kw)), (f"p8_vml_t_{k}", vmid_pm_netlist(f"vml_t_{k}", **kw))]
    spice_many(jobs)
    rows = []
    for i, (ck, dr, es) in enumerate(grid):
        a = np.loadtxt(f"raw/vml_z{i}.txt"); f = a[:, 0]; z = np.abs(a[:, 1]+1j*a[:, 2]); band = (f >= 1e3) & (f <= 1e6)
        pms, fcs = pm_of(f"vml_t{i}")
        rows.append(dict(cfb=VM["cfb"]*ck, cd1=VM["cd1"]*dr, esr_each=es, zmax=float(z[band].max()), fz=float(f[band][np.argmax(z[band])]),
                         pm=min(pms) if pms else None, fc=fcs, nx=len(pms)))
    ex = {}
    for k in extra:
        a = np.loadtxt(f"raw/vml_z_{k}.txt"); f = a[:, 0]; z = np.abs(a[:, 1]+1j*a[:, 2]); band = (f >= 1e3) & (f <= 1e6)
        pms, fcs = pm_of(f"vml_t_{k}"); ex[k] = dict(zmax=float(z[band].max()), fz=float(f[band][np.argmax(z[band])]), pm=min(pms) if pms else None, fc=fcs)
    nom = [r for r in rows if abs(r["cfb"]-VM["cfb"]) < 1e-15 and r["cd1"] == VM["cd1"] and r["esr_each"] == 0.005][0]
    wz = max(rows, key=lambda r: r["zmax"]); wp = min(rows, key=lambda r: r["pm"])
    a = np.loadtxt(f"raw/vml_z{grid.index((1.0, 1.0, 0.005))}.txt"); f = a[:, 0]; zc = a[:, 1]+1j*a[:, 2]
    R["vmid_loop"] = dict(rows=rows, nominal=nom, worst_z=wz, worst_pm=wp, extra=ex, z_curve=dict(f=f[::4].tolist(), z=np.abs(zc[::4]).tolist()))
    case("P8-j [other buffers]", "Phase margin, same method, of the AWG's own Vmid follower (no output capacitor, sim/awg buf) and of a follower straight into 10 uF + 100 nF (sim/awg's flag)",
         "reported", f"AWG follower {ex['awg_follower']['pm']:.0f} deg at {ex['awg_follower']['fc'][0]/1e6:.1f} MHz; direct into 10 uF {ex['direct_10u']['pm']:.0f} deg", "-", True,
         "the AWG follower's own netlist (its 100 nF across the 100 nF node is absent here: no output capacitor) is sim/awg's; this is a cross-check only")
    case("P8-i", "Per-channel Vmid impedance peak, 1 kHz-1 MHz (owner's target): one TLV9062 half per channel (stand-in fitted to TI's model), 0.25 ohm (4 x 1R), 4.7k / 1 uF X7R, 6 x 10 uF + 100 nF, over Cfb +-23.5 %, the 10 uF at 100 % or at Samsung's 1.65 V derating with -10 % tolerance, and Samsung's ESR at 200 kHz / 22 kHz (or 5 mohm)",
         f"<= {LIM_ZVM} ohm", f"{nom['zmax']:.3f} ohm at {nom['fz']/1e3:.0f} kHz nominal; worst {wz['zmax']:.3f} ohm at {wz['fz']/1e3:.0f} kHz (Cfb {wz['cfb']*1e6:.2f} uF, C {wz['cd1']*1e6:.0f} uF, ESR {wz['esr_each']*1e3:.0f} mohm each); the stiffened OPA365 loop (previous design) {ex['opa_stiff']['zmax']:.3f} ohm; TI's own model in whatif/lowcost-scope/vmid: 0.252 ohm",
         f"{LIM_ZVM-wz['zmax']:.3f} ohm", wz["zmax"] <= LIM_ZVM, "C15850's ESR and DC-bias derating from Samsung's characterisation (models/cl21a106kaynnne); ESR at 0 V bias, 25 C")
    case("P8-j", "Per-channel Vmid loop phase margin (loop broken at the inverting input), same corners", ">= 45 deg",
         f"{nom['pm']:.0f} deg at {nom['fc'][0]/1e3:.0f} kHz nominal; worst {wp['pm']:.0f} deg (Cfb {wp['cfb']*1e6:.2f} uF, C {wp['cd1']*1e6:.0f} uF, ESR {wp['esr_each']*1e3:.0f} mohm each); one crossing in every corner: {all(r['nx'] == 1 for r in rows)}; stiffened OPA365 loop (previous) {ex['opa_stiff']['pm']:.0f} deg",
         f"{wp['pm']-45:.0f} deg", wp["pm"] >= 45,
         f"the loop is broken at the op-amp's inverting input, whose impedance (MOhm, pF) is far above the 4.7k / 3 nF network driving it, so the injection sees the capacitive load inside the loop; the previous loop (1R, 1k, 1.5 nF, 10 uF) reads {ex['prev']['pm']:.0f} deg the same way")
    # linear stand-in: fit A0, GBW, Rout to the macromodel's impedance at the nominal corner, 100 Hz-10 MHz
    caps = ((VM["cd1"], VM["esr1"]), (100e-9, 0.03))
    b2 = (f >= 100) & (f <= 1e7); b1 = (f >= 1e3) & (f <= 1e6); zm = np.abs(zc)
    def err(A0, g, r, band, p2): return float(np.max(np.abs(np.abs(zlin(f[band], A0, g, r, VM["riso"], VM["rfb"], VM["cfb"], caps, p2))/zm[band] - 1)))
    best = None
    for p2 in (None, 20e6, 40e6, 80e6):
        for A0 in (10**(x/20) for x in (90, 100, 110, 120)):
            for g in (10e6, 15e6, 20e6, 30e6, 50e6):
                for r in (50, 100, 150, 200):
                    e = err(A0, g, r, b2, p2)
                    if best is None or e < best[0]: best = (e, A0, g, r, p2)
    for _ in range(5):
        e0, A0, g, r, p2 = best
        for A in (A0*0.8, A0, A0*1.25):
            for gg in (g*0.92, g, g*1.08):
                for rr in (r*0.92, r, r*1.08):
                    for pp in ((p2*0.85, p2, p2*1.15) if p2 else (None,)):
                        e = err(A, gg, rr, b2, pp)
                        if e < best[0]: best = (e, A, gg, rr, pp)
    e2, A0, g, r, p2 = best; e1 = err(A0, g, r, b1, p2)
    zl_ext = {}
    for k, kw in (("nominal", {}), ("Cfb low", dict(cfb=VM["cfb"]*0.765)), ("C at 1.65 V bias", dict(cd1=VM["cd1"]*round(K10_165, 4)))):
        v = {**VM, **kw}; i = grid.index((0.765, 1.0, 0.005) if k == "Cfb low" else ((1.0, round(K10_165, 4), 0.005) if k == "C at 1.65 V bias" else (1.0, 1.0, 0.005)))
        a2 = np.loadtxt(f"raw/vml_z{i}.txt"); zz = np.abs(a2[:, 1]+1j*a2[:, 2])
        zl = np.abs(zlin(f[b1], A0, g, r, v["riso"], v["rfb"], v["cfb"], ((v["cd1"], v["esr1"]), (100e-9, 0.03)), p2))
        zl_ext[k] = float(np.max(np.abs(zl/zz[b1] - 1)))
    R["vmid_standin"] = dict(A0=A0, A0_dB=20*math.log10(A0), GBW_Hz=g, Rout_ohm=r, fp2_Hz=p2, err_1k_1M=e1, err_100_10M=e2, err_other_corners=zl_ext)
    case("P8-k", "Linear stand-in for the loop agent (the TLV9062 half as A0 / (1 + s A0 / 2 pi GBW) behind Rout), fitted to the design loop's impedance (behavioural TLV9062)",
         "within 3 % of the macromodel's |Z|, 1 kHz-1 MHz", f"A0 {20*math.log10(A0):.1f} dB, GBW {g/1e6:.1f} MHz, Rout {r:.1f} ohm, double pole {('%.1f MHz' % (p2/1e6)) if p2 else 'none'}: {e1*100:.2f} % (1 kHz-1 MHz), {e2*100:.2f} % (100 Hz-10 MHz); same parameters at other corners: "
         + ", ".join(f"{k} {v*100:.1f} %" for k, v in zl_ext.items()), f"{3-e1*100:.2f} %", e1 <= 0.03,
         "the design loop's buffer is itself a linear behavioural stand-in (whatif/lowcost-scope/vmid, 0.59 % from TI's TLV9062 model), so this fit is exact by construction and its fidelity to the part is that 0.59 %")

def vmid_netlist_pc_z(name, **kw):
    """impedance of one per-channel buffer (the design loop) with its own node"""
    v = {**VM, **kw}; buf = v.pop("buf", VBUF)
    t = [f".include {OP365}", f".include {MCP_OPEN}", "Vdd vp 0 DC 3.34", "Vdv dv 0 DC 1.65", buf_inst("b", "dv", "fb", "vp", "bo", buf), f"Riso bo vm {v['riso']}",
         f"Rfb vm fb {v['rfb']}", f"Cfb bo fb {v['cfb']}", f"Cd1 vm c1 {v['cd1']}", f"Resr1 c1 0 {v['esr1']}", f"Cd2 vm c2 {v.get('cd2', '100n')}", "Resr2 c2 0 0.03",
         "Iac 0 vm DC 0 AC 1", ".ac dec 40 100 20meg", ".control", "run", f"wrdata raw/{name}.txt v(vm)", ".endc", ".end"]
    return "\n".join(t) + "\n"

def run_vmid2():
    names = list(VM2_LOOPS); jobs = []
    for i, nm in enumerate(names):
        jobs += [(f"p8_vm2_z{i}", vmid2_netlist("z", f"vm2_z{i}", **VM2_LOOPS[nm])), (f"p8_vm2_step{i}", vmid2_netlist("step", f"vm2_step{i}", **VM2_LOOPS[nm]))]
    spice_many(jobs)
    out = {}
    for i, nm in enumerate(names):
        a = np.loadtxt(f"raw/vm2_z{i}.txt"); f = a[:, 0]; z11 = a[:, 1] + 1j*a[:, 2]; z21 = a[:, 4] + 1j*a[:, 5]
        vm, se = xt_paths(f, z21)
        vs, _ = xt_paths(f, z11)                       # the aggressor's own Vmid: its own reading, not crosstalk
        b = np.loadtxt(f"raw/vm2_step{i}.txt"); t = b[:, 0]; v1 = b[:, 1]; v2 = b[:, 3]
        after = t >= 200e-6; d1 = v1[after]-np.interp(199e-6, t, v1); d2 = v2[after]-np.interp(199e-6, t, v2)
        ipk = int(np.argmax(np.abs(d1))); pk1 = d1[ipk]; fin1 = float(d1[-1]); ta = t[after]
        opp1 = float(np.max(-np.sign(pk1)*d1[ipk:])) if ipk < len(d1)-1 else 0.0
        bad = np.where(np.abs(d1 - fin1) > 0.5*LSB12)[0]; tset1 = float(ta[bad[-1]] - 200e-6) if len(bad) else 0.0
        out[nm] = dict(z21max=float(np.abs(z21).max()), z11max=float(np.abs(z11).max()), f11=float(f[np.argmax(np.abs(z11))]),
                       own_opp_pct=abs(opp1/pk1)*100 if pk1 else 0.0, own_settle_us=tset1*1e6,
                       xt_vmid=float(vm.max()), xt_sense=float(se.max()), xt=float(vm.max()+se.max()), self_lsb=float(vs.max()/LSB12),
                       step_victim_uV=float(np.abs(d2).max()*1e6), step_own_mV=float(np.abs(d1).max()*1e3))
        x = out[nm]
        case(f"P8-a [{nm}]", f"SC-9 crosstalk with {nm}: one Vmid buffer per channel (TLV9062 halves; the previous loops OPA365) on the shared divider tap (the sense node stays shared), full scale on the other channel, 1 kHz-10 MHz, and a {I_STEP*1e3:.2f} mA step",
             f"<= 2 LSB = {2*LSB12*1e3:.2f} mV", f"{x['xt']/LSB12:.3f} LSB (Vmid path {x['xt_vmid']/LSB12:.4f}, sense path {x['xt_sense']/LSB12:.2f} at DC); step: {x['step_victim_uV']:.2f} uV at the other channel's Vmid; at its own {x['step_own_mV']:.2f} mV, opposite excursion {x['own_opp_pct']:.0f} %, settles in {x['own_settle_us']:.1f} us; own |Z| peak {x['z11max']:.2f} ohm at {x['f11']/1e3:.0f} kHz",
             f"{(2*LSB12-x['xt'])/LSB12:.2f} LSB", x["xt"] <= 2*LSB12,
             f"transfer impedance max {x['z21max']*1e3:.3f} mohm; the channel's own Vmid still peaks at {x['z11max']:.2f} ohm at {x['f11']/1e3:.0f} kHz, which is a signal-dependent error on that channel itself of up to {x['self_lsb']:.2f} LSB (not SC-9)")
        # AWG Rg return: on one channel's buffer (that channel sees Z11), or on a buffer of its own (the channels see Z21)
        w = 2*np.pi*f; Y1 = 1/SC_R1 + 1j*w*SC_C1; Y2 = 1/SC_R2 + 1j*w*SC_C2; Y3 = 1/SC_R3; cv = Y2/(Y1+Y2+Y3)
        coef = np.maximum(np.abs(cv), np.abs(SC_G*cv-(SC_G-1))); I_awg = 1.0/(AW_G*AW_RG)
        x["awg_shared_lsb"] = float((np.abs(I_awg*z11)*coef).max()/LSB12); x["awg_own_lsb"] = float((np.abs(I_awg*z21)*coef).max()/LSB12)
        AWGP[f"{nm}, AWG on a channel's buffer"] = (f, np.abs(I_awg*z11)*coef); AWGP[f"{nm}, AWG on its own buffer"] = (f, np.abs(I_awg*z21)*coef)
        if nm not in ("Vmid x2", "Vmid x2 + M-4", "Vmid x2 + M-5"): continue
        case(f"P8-f [{nm}, AWG on a channel's buffer]", "AWG -> scope through Vmid with the AWG's Rg on the same buffer as one scope channel", "<= 2 LSB (SC-9)",
             f"{x['awg_shared_lsb']:.2f} LSB on that channel, {x['awg_own_lsb']:.4f} LSB on the other", f"{2-x['awg_shared_lsb']:.2f} LSB", x["awg_shared_lsb"] <= 2)
        case(f"P8-f [{nm}, AWG on its own buffer]", "AWG -> scope through Vmid with a third OPA365 buffer for the AWG's Rg and Rx", "<= 2 LSB (SC-9)",
             f"{x['awg_own_lsb']:.4f} LSB on either channel", f"{2-x['awg_own_lsb']:.2f} LSB", x["awg_own_lsb"] <= 2)
    # a stiff shared source, flat impedance: where the shared node would have to be
    a = np.loadtxt("raw/vmid_z0.txt"); f = a[:, 0]
    flat = {}
    for zf in (0.5, 0.28, 0.1):
        vm, se = xt_paths(f, np.full_like(f, zf) + 0j); flat[zf] = float((vm.max()+se.max())/LSB12)
    out["flat_shared_lsb"] = flat
    case("P8-a [shared, flat 0.5 ohm]", "SC-9 with one shared Vmid source of a flat 0.5 ohm (the alternative fix)", "<= 2 LSB", f"{flat[0.5]:.2f} LSB; 0.28 ohm {flat[0.28]:.2f}, 0.1 ohm {flat[0.1]:.2f}",
         f"{2-flat[0.5]:.2f} LSB", flat[0.5] <= 2, "a flat 0.5 ohm is not enough: the shared node needs about 0.28 ohm")
    R["vmid2"] = out

def run_an4():
    out = {"design (2 x 330k 0.1 %, sense 249 ohm), ADVREF drop 0.5 mV": an4_mc(),
           "design, ADVREF drop 5 mV": an4_mc(delta=5e-3),
           "previous (2 x 100k 0.05 %, sense 100 ohm), 5 mV drop": an4_mc(rdiv=100e3, tol_div=0.0005, rsf=100.0, delta=5e-3),
           "reworked AREF = 3.0 V reference (PA-7 / D6, not done)": an4_mc(aref_fixed=3.0)}
    R["an4"] = out
    k = list(out)
    case("P8-c", "AN-4 / SC-2 centring error at the ADC pin, +-5 V and +-1.25 V ranges, V33 3.10 (margin evidence) -3.30 V, Vmid divider 2 x 330k 0.1 % (M-7), R1-R3/RF/RG 0.1 %, 249 ohm sense filter (M-3) carrying both R3 currents, OPA365 offset + bias, stock Due", "<= 30 mV",
         f"{out[k[0]]*1e3:.2f} mV (ADVREF drop 0.5 mV) / {out[k[1]]*1e3:.2f} mV (5 mV drop); previous parts {out[k[2]]*1e3:.2f} mV", f"{30-out[k[1]]*1e3:.1f} mV", out[k[1]] <= 30e-3)
    case("P8-d", "AN-4 reworked Due, AREF = the 3.0 V reference while Vmid stays V33/2", "<= 30 mV", f"{out[k[3]]*1e3:.0f} mV", f"{30-out[k[3]]*1e3:.0f} mV", out[k[3]] <= 30e-3,
         "a PA-7 rework needs Vmid derived from the reference, not from V33")
    st = R["p8_startup"]["2 x 330k, 10 uF (M-7 + M-10)"]
    case("P8-h", "PW-7 start-up: the Vmid divider tap (2 x 330k, 10 uF at the tap) settles to 0.5 LSB of its final value from 0 V", "about 15 s (PW-7)",
         f"{st['t_half_lsb_s']:.1f} s (tau {st['tau_s']:.2f} s)", f"{15-st['t_half_lsb_s']:.1f} s", st["t_half_lsb_s"] <= 15,
         "the buffer and the Vmid node's 10 uF follow in microseconds; readings before this are flagged not ready (PW-7)")

# =============================================================== 2e calibration
VREF = 3.0
# ladder from bottom: 3 elements in parallel, then 5 in series (SEG); taps after each segment; top tap = buffered reference
CUM = np.cumsum(SEG)
F = CUM/CUM[-1]                          # nominal tap fractions
def ladder_thevenin(res):
    """tap voltages (fractions) and Thevenin resistances for resistor list res (bottom to top), top held by an ideal buffer"""
    cum = np.cumsum(res); tot = cum[-1]
    f = cum/tot
    rbelow = cum; rabove = tot-cum
    rth = np.where(rabove > 0, rbelow*rabove/np.maximum(tot, 1e-9), 0.0)
    return f, rth, tot
F_NOM, ZI_NOM, RTOT = ladder_thevenin(np.array(SEG, float))
S_CS, S_RON = 6e-12, 3.8e3
# derivation: tTRACK = 0.054*Z + 205 ns (12 bit, Table/Sec 45.7.2.1) = ln(2^13)*(Z+Ron)*Cs + t0  ->  Cs = 0.054e-9/ln(8192) ohm^-1 s
CS_DERIVED = 0.054e-9/math.log(2**13)
def run_c1():
    """tap source impedance and settling into the Due ADC sample-and-hold (SC-10, AN-2)"""
    out = []; jobs = []; meta = []
    for k, (f, zi) in enumerate(zip(F_NOM, ZI_NOM)):
        v = f*VREF
        for ctap in ("0", "100n"):
            nm = f"c1_tap{k+1}_{ctap}"
            meta.append((k, v, zi, ctap))
            jobs.append((nm, f"""* C1 settle: tap {k+1}, Thevenin {zi:.1f} ohm, V {v:.4f}, C_tap {ctap}; pin Ci 8 pF, Ron {S_RON} ohm, Csample {S_CS}
Vt t 0 {v}
Rth t pin {zi+1e-3}
Ctap pin 0 {ctap if ctap != '0' else '1f'}
Cpin pin 0 8p
S1 pin sh sw 0 SWM
.model SWM SW(VT=0.5 VH=0.1 RON={S_RON} ROFF=1e12)
Vsw sw 0 PWL(0 0 1n 1 667n 1 667.1n 0)
Csh sh 0 {S_CS} IC=0
.ic v(pin)={v} v(sh)=0
.tran 0.2n 700n uic
.control
run
meas tran vend find v(sh) at=666n
meas tran vpin find v(pin) at=666n
.endc
.end
"""))
    for (k, v, zi, ctap), lg in zip(meta, spice_many(jobs)):
            e = abs(meas(lg, "vend") - v)
            out.append(dict(tap=k+1, v=v, zi=zi, ctap=ctap, err_mV=e*1e3, err_lsb=e/LSB12, vpin_dev_mV=abs(meas(lg, "vpin")-v)*1e3))
    R["c1"] = out
    zmax = max(r["zi"] for r in out)
    worst = max(r["err_lsb"] for r in out)
    worst0 = max(r["err_lsb"] for r in out if r["ctap"] == "0"); worst1 = max(r["err_lsb"] for r in out if r["ctap"] == "100n")
    zw = zmax*(1+RLAD_TOL)
    R["c1_zmax"] = dict(nominal=zmax, all_elements_5pct_high=zw, tap=int(np.argmax(ZI_NOM))+1)
    case("C1-a", f"SC-10 tap source impedance (ladder Thevenin, worst tap; 8 x {RLAD_ELEM:.0f} ohm {RLAD_TOL*100:g} %, 3 in parallel + 5 in series)", "<= 5 kohm",
         f"{zmax:.0f} ohm nominal (tap {int(np.argmax(ZI_NOM))+1}), {zw:.0f} ohm with every element at +tol", f"{(5000-zw):.0f} ohm", zw <= 5000)
    R["c1_decision"] = f"no capacitor at the taps (a 100 nF tap capacitor is worse: it shares charge with the sample capacitor instead of the {zmax:.0f} ohm ladder re-settling it)"
    case("C1-b", "AN-2 settling into the Due S/H within the 15-clock (667 ns) window, worst tap from a 0 V previous sample, to 0.5 LSB (12 bit, 3.3 V)",
         "<= 0.5 LSB", f"{worst0:.4f} LSB with no tap capacitor (design); {worst1:.3f} LSB with 100 nF at each tap", f"{0.5-worst0:.3f} LSB", worst0 <= 0.5,
         f"Csample {CS_DERIVED*1e12:.1f} pF derived from the 0.054 ns/ohm slope (Cs={S_CS*1e12:.0f} pF used), Ron {S_RON/1e3:.1f} kohm from the 205 ns intercept: both inferred, not datasheet figures")
    buffer_case("C1-c", RLAD_TOTAL, RLAD_TOL, RLAD_ELEM, RLAD_NPAR, RLAD_PEL, RLAD_TC, store=True)
    q = S_CS*VREF; c_ref = 2*0.1e-6*0.9
    R["c1_kick"] = dict(q_pC=q*1e12, dv_mV=q/c_ref*1e3, lsb=q/c_ref/(3.3/4096))
    case("C1-d", "B: the Due's sample-and-hold kick on the top tap (= the REF3030E output = REFP0), sampled from 0 V, into the 2 x 100 nF at -10 %",
         "<= 0.5 LSB at the Due (C1-b); no Due tap read while the ADS124S08 converts", f"{q*1e12:.0f} pC -> {q/c_ref*1e3:.3f} mV = {q/c_ref/(3.3/4096):.2f} LSB before the REF3030E recovers it (its output impedance at MHz is not modelled)",
         f"{0.5-q/c_ref/(3.3/4096):.2f} LSB", q/c_ref/(3.3/4096) <= 0.5,
         "sequencing rule (B): the Due does not read the ladder while the ADS124S08 converts; calibration already reads them one after the other (C4-c)")

# B (owner, 2026-11-11): the ladder hangs directly on the REF3030E output (SBVS032K 6.5, REF30xxE): load regulation 15
# ppm/mA max (source, 0-10 mA, at VIN = VOUT + 0.5 V), dropout VIN >= VOUT + 0.2 V (Sec 6.3), RthJA 218.5 K/W (Sec 6.4),
# tempco 15 ppm/K max (0-70 C).  +3.3 V_A is its input (3.235-3.342 V).
I_REF_LIM = 10e-3
def buffer_case(cid, rtot, tol, elem, npar, pel, tc, store=False, label=""):
    rmin = rtot*(1-tol); i_max = VREF/rmin + 18e-6; head = VP_MIN - VREF
    lreg = 15e-6*i_max*1e3*VREF; heat = (VP_MAX - VREF)*i_max*218.5; heat_ppm = heat*15
    p_ser = (VREF/rmin)**2*elem*(1-tol); i_par = VREF/rmin/npar; p_par = i_par**2*elem*(1-tol)
    p_arr = max(npar*p_par + (4-npar)*p_ser, 4*p_ser)
    d = dict(r_min=rmin, i_nom_mA=VREF/rtot*1e3, i_max_mA=i_max*1e3, headroom_V=head, loadreg_uV=lreg*1e6, self_heat_K=heat, self_heat_ppm=heat_ppm,
             p_series_elem_mW=p_ser*1e3, p_par_elem_mW=p_par*1e3, p_array_max_mW=p_arr*1e3, p_elem_rating_mW=(pel*1e3 if pel else None),
             dT_for_0p2pct_K=0.002/tc, theta_for_0p2pct_KperW=(0.002/tc)/p_arr, i_lim_mA=I_REF_LIM*1e3)
    if store: R["c1_buffer"] = d
    ok = head >= 0.2 and i_max <= I_REF_LIM
    case(cid, f"REF3030E sourcing the ladder directly (B, no buffer){label}, plus the ADS124S08's REFP0 (18 uA): output current, headroom, load regulation, self-heating; every element at -tol",
         f"I <= {I_REF_LIM*1e3:.0f} mA (the load-regulation range) and VIN - VOUT >= 0.2 V",
         f"{i_max*1e3:.2f} mA ({VREF/rtot*1e3:.2f} nominal); headroom {head*1e3:.0f} mV at +3.3 V_A = {VP_MIN:.3f} V; load regulation <= {lreg*1e6:.0f} uV (specified at VIN = VOUT + 0.5 V *(check)*); self-heating {heat:.2f} K = {heat_ppm:.1f} ppm",
         f"{(I_REF_LIM-i_max)*1e3:.2f} mA, {head*1e3-200:.0f} mV", ok,
         "ratiometric for the ADS124S08 (REFP0 is the ladder's top node); a static term of PA-6 for the Due's gain fit, which uses the top tap's absolute value; element dissipation "
         + f"{p_ser*1e3:.2f} mW" + (f" of {pel*1e3:.1f} mW rating" if pel else " (rating not read *(check)*)"))
    return d

def draw_ladder(seg, npar, tol):
    """one ladder: the bottom segment is npar equal elements in parallel (each drawn), the others single elements"""
    seg = np.array(seg, float)
    if npar > 1:
        e = seg[0]*npar*(1+rng.uniform(-tol, tol, npar))
        bot = 1/np.sum(1/e)
    else:
        bot = seg[0]*(1+rng.uniform(-tol, tol))
    return np.concatenate([[bot], seg[1:]*(1+rng.uniform(-tol, tol, len(seg)-1))])

VOS_BUF = 0.0       # B (owner, 2026-11-11): the ladder hangs on the REF3030E output, no buffer; the top tap is the REFP0 node itself
# precision ADC (2026-11-11): ADS124S08 (C2870171, TQFP-32; SBAS660C), PGA bypassed, single-ended against AINCOM = AGND,
# REFP0 = the REF3030 node, REFN0 = AGND, low-latency filter at 20 SPS.  Inputs: the six ladder taps (top tap direct),
# the AWG-sense tap and the sense divider's bottom node; the rest spare.  Figures, all PGA bypassed: differential input
# current 1 nA/V typ, absolute 0.5 nA typ (no maxima) -> an input resistance of ~1 Gohm, no loading correction needed;
# INL 10 ppm FSR max (FSR = 2 VREF = 6 V -> 60 uV, 20 ppm of the 3 V span); gain error 120 ppm max, calibrated out against
# the top tap; noise 1.2 uVrms (8.0 uVpp) at 20 SPS, low-latency filter, Table 3 (gain 1, PGA enabled, internal 2.5 V
# reference: the closest the table gives to PGA bypassed at 3.0 V *(check)*); first conversion 56.5 ms (Table 13).
ADS_ZIN, ADS_INL_PPM, ADS_NOISE, ADS_NOISE_PP, ADS_T_CONV = 1e9, 10*6/3.0, 1.2e-6, 8.0e-6, 56.504e-3 + 14*16/4.096e6
def fit_mc(n_taps_used, mcp_cal, N=20000, zin=ADS_ZIN, zin_unc=0.30, lkg=0.5e-6, inl=1.2, adc_noise=0.8, navg=4096,
           mcp_inl_ppm=ADS_INL_PPM, tol=RLAD_TOL, vos_buf=VOS_BUF, abs_scale=False, seg=None, npar=None, zcorr=False, drift=0.0, reread=False,
           refin_top=False):
    """drift: each element moves by up to +-drift (uniform, uncorrelated) between the MCP reading and the Due's reading
    (a calibration not re-read after a temperature change); reread=True: the same drift happens, but the MCP reads the
    taps again in this calibration, so its reading is of the drifted ladder (PA-9's rule); zcorr=False: the MCP's Zin
    loading is not corrected.  refin_top=True (previous): the MCP3564's reference REFIN+ is the REF3030 output itself and
    the top tap is read through the internal REFIN+ channel (ratio exactly 1), while the ladder hangs off the OPA365 buffer,
    whose offset sits between the two: the Due sees every tap at f x Vbuf, the MCP reads the inner taps as f x Vbuf / Vref and
    the top as 1.  refin_top=False (the design, 2026-11-11): CH7 reads the buffered top tap itself, so every tap is read
    against the same buffered node and the buffer's offset is pure scale (reported in PA-6)."""
    if seg is None: seg, npar = SEG, RLAD_NPAR
    npar = npar or 1
    zi_nom = ladder_thevenin(np.array(seg, float))[1]
    ends = np.array([0.2, 3.1])
    gerr = []; oerr = []; ends_err = []
    for _ in range(N):
        res = draw_ladder(seg, npar, tol)
        f_cal, rth_cal, _ = ladder_thevenin(res)
        if drift: res = res*(1+rng.uniform(-drift, drift, len(res)))
        f, rth, tot = ladder_thevenin(res)
        if reread: f_cal, rth_cal = f, rth
        vref = VREF*(1+rng.uniform(-0.001, 0.001)) if abs_scale else VREF
        vbuf = vref + rng.uniform(-vos_buf, vos_buf)                 # top tap = buffered reference
        v_true = f*vbuf
        zin_t = zin*(1+rng.uniform(-zin_unc, zin_unc))
        # what the Due ADC sees: true tap voltage + leakage drop; the ADC gain/offset are the unknowns
        a_true = 4095/3.3*(1+rng.uniform(-0.0156, 0.0029)); b_true = rng.uniform(-30, 56)
        leak = rng.uniform(-lkg, lkg, len(f))
        code = a_true*(v_true + leak*rth) + b_true + rng.uniform(-inl, inl, len(f)) + rng.normal(0, adc_noise/math.sqrt(navg), len(f))
        # what we know about the taps
        if mcp_cal:
            # the MCP reads each tap as a ratio to its own reference, times (1 - rth/zin_t) for its loading
            gain = vbuf/vref if refin_top else 1.0
            r_meas = f_cal*gain*(1-rth_cal/zin_t) + rng.uniform(-mcp_inl_ppm, mcp_inl_ppm, len(f))*1e-6 + rng.normal(0, ADS_NOISE/3.0, len(f))
            if refin_top: r_meas[-1] = 1.0 + rng.normal(0, 1.2e-6/3.0)   # the top tap through the internal REFIN+ channel: Vref / Vref
            # correct the loading with the NOMINAL Zi and NOMINAL Zin (the uncertainty is zin_unc)
            r_corr = r_meas/(1-zi_nom/zin) if zcorr else r_meas
            v_est = r_corr*VREF if refin_top else r_corr/r_corr[-1]*VREF   # in units of the reference (its scale reported separately, PA-6)
        else:
            v_est = ladder_thevenin(np.array(seg, float))[0]*VREF
        idx = np.arange(len(f)) if n_taps_used >= len(f) else np.delete(np.arange(len(f)), rng.integers(1, len(f)-1))[:n_taps_used]
        A = np.vstack([v_est[idx], np.ones(len(idx))]).T
        a_e, b_e = np.linalg.lstsq(A, code[idx], rcond=None)[0]
        # compare the fitted line with the truth at the span ends, in 12-bit LSB; truth scale uses the same Vref normalisation
        scale = (vref if refin_top else vbuf)/VREF                      # true volts per assumed volt: the scale is reported separately (PA-6)
        d = [(a_e*(x) + b_e) - (a_true*(x*scale) + b_true) for x in ends]
        ends_err.append(np.max(np.abs(d)))
    e = np.array(ends_err)
    return dict(p50=float(np.percentile(e, 50)), p99=float(np.percentile(e, 99)), p999=float(np.percentile(e, 99.9)), max=float(e.max()))

# MCP3564 inputs (2026-11-11, SM-5 dropped, the 1 Mohm input back): CH0 the DAC0 buffer output (the injection source),
# CH1 the AWG output, CH2-CH6 the five inner ladder taps, CH7 the buffered top tap (approved 2026-11-11: it takes the
# OPA365's offset out of the fit, which reading the top through REFIN+ left in): six taps
NTAP = 6
K_CAL, K_DROP, K_LKG = "ladder+MCP only: MCP-calibrated, 6 taps (design)", "ladder+MCP only: MCP-calibrated, 5 taps (one of 6 dropped)", "ladder+MCP+leakage 0.5 uA: MCP-calibrated, 6 taps"
STALE = "stale calibration: elements drift +-%.2f %% (%.0f ppm/K x 10 K, uncorrelated) after the MCP read, ladder+MCP only, 6 taps" % (RLAD_TC*10*100, RLAD_TC*1e6)
REREAD = "re-read calibration: the same +-%.2f %% drift, taps re-read by the MCP in this calibration (PA-9), ladder+MCP only, 6 taps" % (RLAD_TC*10*100)
def run_c2():
    out = {}
    base = dict(N=15000)
    for label, cal, n in (("nominal ratios, 6 taps", False, NTAP), ("MCP-calibrated, 6 taps (design)", True, NTAP), ("MCP-calibrated, 5 taps (one of 6 dropped)", True, NTAP-1), ("MCP-calibrated, 4 taps (D11 minimum)", True, 4)):
        out["ladder+MCP only: " + label] = fit_mc(n, cal, inl=0.0, lkg=0.0, **base)
    out[K_LKG] = fit_mc(NTAP, True, inl=0.0, **base)
    out["ladder+MCP+leakage+ADC INL 1.2 LSB: MCP-calibrated, 6 taps"] = fit_mc(6, True, **base)
    out["ladder+MCP+leakage+ADC INL 1.2 LSB: nominal ratios, 6 taps"] = fit_mc(6, False, **base)
    out["absolute (Vref +-0.1 % included), ladder+MCP only, 6 taps"] = fit_mc(6, True, inl=0.0, lkg=0.0, abs_scale=True, **base)
    out["sensitivity: ADC input resistance 1 Mohm (1000 x the typical input current), uncorrected, ladder+ADC only, 6 taps"] = fit_mc(6, True, inl=0.0, lkg=0.0, zin=1e6, **base)
    out["sensitivity: ladder 0.1 % resistors, nominal ratios, ladder only"] = fit_mc(6, False, inl=0.0, lkg=0.0, tol=0.001, **base)
    out["sensitivity: ADC INL at its typical 1 ppm FSR, ladder+ADC only, 6 taps"] = fit_mc(6, True, inl=0.0, lkg=0.0, mcp_inl_ppm=1*6/3.0, **base)
    out["comparison: top tap through REFIN+ (previous), ladder+MCP only, 6 taps"] = fit_mc(NTAP, True, inl=0.0, lkg=0.0, refin_top=True, **base)
    out["comparison: buffer offset 0, ladder+MCP only, 6 taps"] = fit_mc(NTAP, True, inl=0.0, lkg=0.0, vos_buf=0.0, **base)
    out[STALE] = fit_mc(NTAP, True, inl=0.0, lkg=0.0, drift=RLAD_TC*10, **base)
    out[REREAD] = fit_mc(NTAP, True, inl=0.0, lkg=0.0, drift=RLAD_TC*10, reread=True, **base)
    sweep = {}
    for lab, seg, npar, tol, zin, ppm in (("249 ohm 0.1 % (design), gain 1x, prescaler 8", SEG, RLAD_NPAR, RLAD_TOL, 2.08e6, 14.0), ("249 ohm 0.1 % (design), gain 0.33x, prescaler 8", SEG, RLAD_NPAR, RLAD_TOL, 4.08e6, 60.0),
                                          ("330 ohm arrays 5 % (previous), gain 1x, prescaler 8", [110.0]+[330.0]*5, 3, 0.05, 2.08e6, 14.0),
                                          ("1 kohm arrays 5 % (previous), gain 1x, prescaler 8", SEG_1K, 3, RLAD_TOL, 2.08e6, 14.0),
                                          ("604 ohm 0.1 % ladder (previous), gain 1x, prescaler 8", [150]+[604]*5, 1, 0.001, 2.08e6, 14.0), ("604 ohm 0.1 % ladder (previous), gain 0.33x, prescaler 8", [150]+[604]*5, 1, 0.001, 4.08e6, 60.0)):
        for nt in (6, 5):
            sweep[f"{lab}, {nt} taps"] = fit_mc(nt, True, inl=0.0, lkg=0.0, seg=seg, npar=npar, tol=tol, zin=zin, mcp_inl_ppm=ppm, **base)
            sweep[f"{lab}, {nt} taps, +leakage"] = fit_mc(nt, True, inl=0.0, lkg=0.5e-6, seg=seg, npar=npar, tol=tol, zin=zin, mcp_inl_ppm=ppm, **base)
    R["c2_design_sweep"] = sweep
    R["c2"] = out
    lim = 0.5
    cal = out[K_CAL]; nom = out["ladder+MCP only: nominal ratios, 6 taps"]
    case("C2-a", f"PA-9 Due-ADC gain/offset fit from the MCP-read taps, error that the ladder + MCP readback add (6 taps: CH2-CH6 + the buffered top tap on CH7, so the OPA365's offset is pure scale; 8 x {RLAD_ELEM:.0f} ohm {RLAD_TOL*100:g} % (3 parallel + 5 series), buffer offset 200 uV, ADS124S08 read: INL 10 ppm FSR max, 1.2 uVrms, input current 1 nA/V), at the span ends 0.2 V / 3.1 V",
         f"<= {lim} LSB (12 bit) at 99.9 %", f"{cal['p999']:.3f} LSB (99.9th pct), {cal['max']:.3f} max; with nominal ratios instead of MCP readings {nom['p999']:.3f} LSB",
         f"{lim-cal['p999']:.3f} LSB", cal["p999"] <= lim,
         f"top tap through REFIN+ instead (previous): {out['comparison: top tap through REFIN+ (previous), ladder+MCP only, 6 taps']['p999']:.3f} LSB; buffer offset 0: {out['comparison: buffer offset 0, ladder+MCP only, 6 taps']['p999']:.3f} LSB")
    w5 = out[K_DROP]["p999"]
    case("C2-b", "PA-9 fit robustness: one of the 6 taps dropped (5 left), ladder + MCP error", f"<= {lim} LSB", f"{w5:.3f} LSB", f"{lim-w5:.3f} LSB", w5 <= lim)
    lk = out[K_LKG]["p999"]
    case("C2-c", "SC-10 leakage: Due ADC pin leakage 0.5 uA max (Table 45-38) x tap impedance, added to C2-a", f"<= {lim} LSB", f"{lk:.3f} LSB", f"{lim-lk:.3f} LSB", lk <= lim,
         "0.5 uA is a MAX over temperature; typical is not given *(check)*")
    st, rr = out[STALE]["p999"], out[REREAD]["p999"]
    case("C2-d", "PA-9 taps re-read by the MCP at every calibration: elements drift +-%.2f %% (%.0f ppm/K x 10 K, uncorrelated) after an earlier read; the calibration re-reads them" % (RLAD_TC*10*100, RLAD_TC*1e6),
         f"<= {lim} LSB with the re-read", f"{rr:.3f} LSB re-read; {st:.3f} LSB if the earlier reading is reused (stale)", f"{lim-rr:.3f} LSB", rr <= lim,
         "with 10 ppm/K parts even the stale reading passes, so the re-read rule is margin here rather than load-bearing; the guard runs the stale arm at 200 ppm/K")
    inl = out["ladder+MCP+leakage+ADC INL 1.2 LSB: MCP-calibrated, 6 taps"]["p999"]
    R["c2_inl_floor_lsb"] = inl
    return out


# ---- ladder built from discrete parts of an existing type (merge candidates: the C12018 array type goes)
LADDER_VARIANTS = {   # label: element, tolerance, tempco, element rating (None = not read)
    "330R 5 % arrays (previous)": (330.0, 0.05, 200e-6, 1/16),   # C12018 4D03WGJ0331T5E: 5 %, 200 ppm/K, 1/16 W per element (page)
    "680R 1 %": (680.0, 0.01, 100e-6, None),       # UNI-ROYAL 0603WAF6800T5E C23228: 1 %, 100 ppm/K (architecture.md); rating not read *(check)*
}
def settle_spice(name, zi, v):
    return f"""* C1 settle: Thevenin {zi:.1f} ohm, V {v:.4f}; pin Ci 8 pF, Ron {S_RON} ohm, Csample {S_CS}
Vt t 0 {v}
Rth t pin {zi+1e-3}
Ctap pin 0 1f
Cpin pin 0 8p
S1 pin sh sw 0 SWM
.model SWM SW(VT=0.5 VH=0.1 RON={S_RON} ROFF=1e12)
Vsw sw 0 PWL(0 0 1n 1 667n 1 667.1n 0)
Csh sh 0 {S_CS} IC=0
.ic v(pin)={v} v(sh)=0
.tran 0.2n 700n uic
.control
run
meas tran vend find v(sh) at=666n
.endc
.end
"""
def run_ladder_variants():
    out = {}; lim = 0.5; base = dict(N=15000)
    jobs = []
    for lab, (el, tol, tc, pel) in LADDER_VARIANTS.items():
        seg = [el/3] + [el]*5
        f, zi, tot = ladder_thevenin(np.array(seg))
        k = int(np.argmax(zi)); jobs.append((f"lv_{lab.split()[0]}", settle_spice(lab, zi[k]*(1+tol), f[k]*VREF)))
    logs = spice_many(jobs)
    for (lab, (el, tol, tc, pel)), lg in zip(LADDER_VARIANTS.items(), logs):
        seg = [el/3] + [el]*5; tg = f" [{lab}]"
        f, zi, tot = ladder_thevenin(np.array(seg)); k = int(np.argmax(zi))
        zw = zi[k]*(1+tol); settle = abs(meas(lg, "vend") - f[k]*VREF)/LSB12
        case("C1-a" + tg, f"SC-10 tap source impedance, ladder of 8 x {lab} (3 parallel + 5 series, {tot:.0f} ohm)", "<= 5 kohm",
             f"{zi[k]:.0f} ohm nominal (tap {k+1}), {zw:.0f} ohm at +tol", f"{5000-zw:.0f} ohm", zw <= 5000)
        case("C1-b" + tg, "AN-2 settling of the worst tap into the Due S/H in 667 ns", "<= 0.5 LSB", f"{settle:.4f} LSB", f"{0.5-settle:.3f} LSB", settle <= 0.5)
        b = buffer_case("C1-c" + tg, tot, tol, el, 3, pel, tc, label=f" ({lab})")
        kw = dict(seg=seg, npar=3, tol=tol)
        cal = fit_mc(6, True, inl=0.0, lkg=0.0, **kw, **base); nom = fit_mc(6, False, inl=0.0, lkg=0.0, **kw, **base)
        w5 = fit_mc(5, True, inl=0.0, lkg=0.0, **kw, **base); lk = fit_mc(6, True, inl=0.0, **kw, **base)
        st = fit_mc(6, True, inl=0.0, lkg=0.0, drift=tc*10, **kw, **base); rr = fit_mc(6, True, inl=0.0, lkg=0.0, drift=tc*10, reread=True, **kw, **base)
        case("C2-a" + tg, "PA-9 fit from the MCP-read taps, ladder + MCP error", f"<= {lim} LSB at 99.9 %", f"{cal['p999']:.3f} LSB; nominal ratios {nom['p999']:.3f} LSB", f"{lim-cal['p999']:.3f} LSB", cal["p999"] <= lim)
        case("C2-b" + tg, "PA-9 one tap dropped (5 taps)", f"<= {lim} LSB", f"{w5['p999']:.3f} LSB", f"{lim-w5['p999']:.3f} LSB", w5["p999"] <= lim)
        case("C2-c" + tg, "SC-10 pin leakage 0.5 uA x tap impedance, added to C2-a", f"<= {lim} LSB", f"{lk['p999']:.3f} LSB (worst tap {zi[k]:.0f} ohm)", f"{lim-lk['p999']:.3f} LSB", lk["p999"] <= lim)
        case("C2-d" + tg, f"PA-9 re-read: drift +-{tc*10*100:.2f} % ({tc*1e6:.0f} ppm/K x 10 K)", f"<= {lim} LSB with the re-read", f"{rr['p999']:.3f} LSB re-read; {st['p999']:.3f} LSB stale", f"{lim-rr['p999']:.3f} LSB", rr["p999"] <= lim)
        bud = {v: sum(budget(sc, ladder_r=tot*(1-tol)).values()) for v, sc in (("OPA365", 5.0), ("OPA354", 6.3))}
        case("P3-a" + tg, f"PW-1 AFE current with this ladder ({b['i_max_mA']:.2f} mA at -tol), AWG shorted, all maxima", "<= 100 mA",
             f"OPA365 scope {bud['OPA365']+23:.1f} mA, OPA354 scope {bud['OPA354']+23:.1f} mA", f"{100-bud['OPA354']-23:.1f} mA", bud["OPA354"]+23 <= 100)
        out[lab] = dict(total=tot, zmax=zi[k], zmax_tol=zw, settle_lsb=settle, buffer=b, c2a=cal["p999"], c2a_nominal=nom["p999"], c2b=w5["p999"], c2c=lk["p999"],
                        c2d_reread=rr["p999"], c2d_stale=st["p999"], p3_shorted={k_: v+23 for k_, v in bud.items()})
    R["ladder_variants"] = out

# ---- C3: the Due's DAC0 -> TMUX1119 (one per channel) -> scope node N (PA-3, 2026-11-11: no precision DAC; the DAC8551,
# its 22 ohm and the 4.7 nF DX node are removed).  The MCP3564 reads DAC0 at its pin (CH0) while the switch is on.
# DAC0's output impedance is not in the SAM3X datasheet (Sec 46.9 gives no load or output-resistance figure) *(check)*.
LOWZ = False                # the ~20-30 kohm input (SC-3 what-if) is dropped with SM-5 (2026-11-11): its C3-e rows are not run
C_N_PAR = 2e-12 + 1e-12                 # op-amp input 2 pF + layout ~1 pF at N (sim/scope: "about 1 pF more than the part plus the op-amp's 2 pF")
C_SW = 20e-12                           # TMUX1119 CDON 20 pF typ (Sec 5.6), no min/max and no OFF D-pin value (gap G7)
DAC0_LO, DAC0_HI = 0.58, 2.77           # DAC0 window, afe.md PA-3 / section 4.1
def run_c3():
    out = {}
    alpha = SC_ALPHA; rth = SC_RTH; G = SC_G
    # --- OFF: leakage
    ileak = 0.1e-9*2                       # 0.1 nA each of IS(OFF) and ID(OFF), 85 C max (SCDS401C Sec 5.6); ID(OFF) assumed equal *(check)*
    vn = ileak*rth
    lk = {rng_: vn*g/LSB12 for rng_, g in (("+-5 V", 1.0), ("+-1.25 V", G))}
    out["leak_lsb"] = lk
    case("C3-a", f"PA-4 switch OFF: leakage 0.2 nA (85 C max) x R1||R2||R3 {rth/1e3:.0f} kohm at the scope pin", "<= 0.5 LSB (SC-9/SC-10 allocation)",
         f"{lk['+-5 V']:.3f} LSB (+-5 V), {lk['+-1.25 V']:.3f} LSB (+-1.25 V); at 125 C x5: {5*lk['+-1.25 V']:.2f}", f"{0.5-lk['+-1.25 V']:.2f} LSB", max(lk.values()) <= 0.5,
         "EN-1 is 15-35 C, so 85 C is conservative")
    # --- capacitance at N: the switch's CDON lands on N, so the C2 part shrinks to keep C2tot = C1 (R1 / (R2||R3))
    c1 = SC_C1; c2tot = c1*SC_R1/par(SC_R2, SC_R3); c2part = c2tot - C_SW - C_N_PAR
    cin = c1*c2tot/(c1+c2tot)
    step_if_39 = (c1/(c1+SC_C2+C_N_PAR+C_SW))/alpha - 1          # HF/DC gain if C2 stays 39 pF with the switch on N
    out["cap"] = dict(c2tot_pF=c2tot*1e12, c2part_pF=c2part*1e12, cin_pF=cin*1e12, hf_err_per_pF=1e-12/(c1+c2tot), step_if_39_pct=step_if_39*100)
    case("C3-b", "PA-4 switch OFF: its capacitance at the divider node N, with C1 12 pF kept and the C2 part resized so C2tot matches; SC-3 input capacitance", "SC-3 <= 30 pF",
         f"C2tot {c2tot*1e12:.1f} pF -> C2 part {c2part*1e12:.1f} pF (switch {C_SW*1e12:.0f} + {C_N_PAR*1e12:.0f} pF), Cin {cin*1e12:.1f} pF; 1 pF of CDON spread = {1e-12/(c1+c2tot)*100:.1f} % of HF gain; a 39 pF C2 with the switch on N steps the HF gain by {step_if_39*100:.0f} %",
         f"{30-cin*1e12:.1f} pF", cin <= 30e-12,
         "CDON is a typical with no min/max (gap G7); afe.md PA-3 says the switch stays off the high-impedance input node, which this placement on N does not do (requirement conflict, F-9)")
    # --- OFF: crosstalk channel to channel through the shared DAC0 node, and AWG to scope through the open switch
    cft = 10**(-45/20)/(2*math.pi*10e6*25)      # -45 dB at 10 MHz into 50 ohm -> 3.6 pF across the open switch
    cft1 = 10**(-65/20)/(2*math.pi*1e6*25)
    f = np.logspace(3, 7, 300); w = 2*np.pi*f
    # the shared source node: raw DAC0 (single switch, previous) with its unknown Zout || 680 ohm + the buffer's input
    # (330k to Vmid); the T-switch is fed from the DAC0 buffer's output instead (an OPA365 follower)
    za = 680.0 + 1/(1/330e3 + 1j*w*2e-12)
    zn = 1/(1/rth + 1j*w*(c1+c2tot))
    xt_rows = {}
    for zd in (1.0, 10.0, 100.0, 1e3, 1e4, None):
        zdx = za if zd is None else 1/(1/zd + 1/za)
        h = (1j*w*cft*zdx/(1+1j*w*cft*zdx))*(1j*w*cft*zn/(1+1j*w*cft*zn))   # N1 -> DAC0 node -> N2
        xt = np.abs(h)*alpha*5.0*G                                   # aggressor full scale +-5 V, victim on +-1.25 V
        xt_rows["open" if zd is None else f"{zd:g}"] = float(xt.max())
    out["xtalk_dac0_mV"] = {k: v*1e3 for k, v in xt_rows.items()}; out["cft_pF"] = (cft*1e12, cft1*1e12)
    ok_zd = [k for k, v in xt_rows.items() if v <= 2*LSB12]
    worst = xt_rows["open"]
    case("C3-c", "SC-9 channel crosstalk through the shared DAC0 node (both switches OFF), +-5 V full scale on one channel, the other on +-1.25 V, 1 kHz-10 MHz, DAC0's output impedance unknown",
         f"<= 2 LSB = {2*LSB12*1e3:.2f} mV", f"{worst*1e3:.3f} mV with DAC0's output open (the AWG input network alone loads the node); "
         + ", ".join(f"{k} ohm: {v*1e3:.3f} mV" for k, v in xt_rows.items() if k != "open"), f"{(2*LSB12-worst)*1e3:.2f} mV", worst <= 2*LSB12,
         f"feed-through {cft*1e12:.2f} pF from -45 dB @ 10 MHz ({cft1*1e12:.2f} pF from -65 dB @ 1 MHz); board coupling is a layout item (G8)")
    # AWG -> scope: DAC0 carries the AWG signal while the switches are off; it couples into N through the feed-through.
    # Judged against SC-9's 2 LSB (afe.md 2026-11-11: AWG coupling while DAC0 plays, including through the off switch), 1 kHz-10 MHz.
    k = lambda zz: 1j*w*cft*zz/(1+1j*w*cft*zz)            # one open switch feeding a node of impedance zz
    vd = (DAC0_HI-DAC0_LO)/2
    a125 = np.abs(k(zn))*vd*G
    out["awg_feed"] = dict(pin_mV_5=float((a125/G).max()*1e3), pin_mV_125=float(a125.max()*1e3), at10k_mV_125=float(np.interp(1e4, f, a125)*1e3), at1M_mV_125=float(np.interp(1e6, f, a125)*1e3))
    case("C3-f", "AWG -> scope through the open injection switch (single TMUX1119): DAC0 at full window (+-1.1 V) couples into N through the switch's feed-through, 1 kHz-10 MHz, +-1.25 V range",
         "<= 2 LSB at the pin (SC-9, AWG while DAC0 plays, through the off switch)",
         f"{a125.max()*1e3:.0f} mV = {a125.max()/LSB12:.0f} LSB max; {np.interp(1e6, f, a125)*1e3:.0f} mV at 1 MHz, {np.interp(1e4, f, a125)*1e3:.1f} mV at 10 kHz",
         f"{(LIM_AWG_XT-a125.max())/LSB12:.0f} LSB", a125.max() <= LIM_AWG_XT, "rests on the datasheet's off-isolation (a 50 ohm fixture figure) *(check)*")
    # fix 1, T-switch: per channel two TMUX1119 in series; the first one's off throw holds the middle node M at Vmid
    # (M sees Ron <= 8.8 ohm + the Vmid node, taken as 10 ohm flat; the per-channel buffer's own peak is 1.2 ohm)
    zm = 10.0
    aT = np.abs(k(zm)*k(zn))*vd*G
    xT = {}
    for zd in (1.0, 100.0, None):
        zdx = za if zd is None else 1/(1/zd + 1/za)
        xT["open" if zd is None else f"{zd:g}"] = float((np.abs(k(zm)*k(zdx)*k(zm)*k(zn))*alpha*5.0*G).max())
    out["tsw"] = dict(awg_mV=float(aT.max()*1e3), awg_lsb=float(aT.max()/LSB12), xt_mV=xT)
    case("C3-f [T-switch]", "as C3-f with a T-switch: DAC0 -> TMUX1119 A (off: middle node to Vmid) -> TMUX1119 B -> N", "<= 2 LSB (SC-9)",
         f"{aT.max()*1e6:.2f} uV = {aT.max()/LSB12:.4f} LSB max (1 kHz-10 MHz)", f"{(LIM_AWG_XT-aT.max())/LSB12:.3f} LSB", aT.max() <= LIM_AWG_XT,
         "one more TMUX1119 per channel (existing type); ON path Ron doubles to 7.4-17.6 ohm (C3-e covers it); DAC0's load is unchanged (both throws of A are open to DAC0 when off)")
    case("C3-c [T-switch]", "as C3-c with the T-switch on both channels: N1 -> B1 -> M1 (held) -> A1 -> DAC0 -> A2 -> M2 (held) -> B2 -> N2", f"<= 2 LSB",
         f"{xT['open']*1e9:.3f} nV with DAC0's output open; {xT['1']*1e9:.3f} nV at 1 ohm", f"{(2*LSB12-xT['open'])/LSB12:.3f} LSB", xT["open"] <= 2*LSB12,
         "DAC0's unknown output impedance no longer matters")
    # SC-9, AWG while DAC0 plays, both paths together (added per frequency, in phase as a bound): Vmid path + switch path
    tot = {}
    for vk, (fv, av) in AWGP.items():
        for sk, arr in (("single switch", a125), ("T-switch", aT)):
            tot[f"{vk}; {sk}"] = float((av + np.interp(fv, f, arr)).max())
    out["awg_total_mV"] = {k: v*1e3 for k, v in tot.items()}
    for key in ("Vmid x2, AWG on its own buffer; T-switch", "Vmid x2, AWG on a channel's buffer; T-switch", "one shared Vmid buffer; T-switch"):
        if key in tot:
            case(f"SC-9 AWG [{key}]", "AWG -> scope while DAC0 plays, through Vmid and through the off injection switch together, 1 kHz-10 MHz, +-1.25 V victim (worst)",
                 "<= 2 LSB (SC-9)", f"{tot[key]*1e3:.3f} mV = {tot[key]/LSB12:.2f} LSB", f"{(2*LSB12-tot[key])/LSB12:.2f} LSB", tot[key] <= 2*LSB12)
    # fix 2 for comparison, series R + shunt C: 330k from DAC0 to M, 100 nF from M to Vmid, one switch M -> N (no DAC0 DC load)
    rs, csh = 330e3, 100e-9
    hm = 1/(1+1j*w*rs*csh); aR = np.abs(hm*k(zn))*vd*G
    cover = rth/(rs+rth)
    out["rc"] = dict(awg_mV=float(aR.max()*1e3), awg_lsb=float(aR.max()/LSB12), f=float(f[np.argmax(aR)]), cover=cover)
    case("C3-f [R 330k + C 100 nF]", "as C3-f with DAC0 -> 330k -> node M (100 nF to Vmid) -> one TMUX1119 -> N", "<= 2 LSB (SC-9)",
         f"{aR.max()*1e3:.3f} mV = {aR.max()/LSB12:.2f} LSB at {f[np.argmax(aR)]/1e3:.0f} kHz", f"{(LIM_AWG_XT-aR.max())/LSB12:.2f} LSB", aR.max() <= LIM_AWG_XT,
         f"but ON, N sees M through 330k against its own {rth/1e3:.0f}k: the injected swing shrinks to {cover*100:.0f} %, so +-5 V coverage falls to about {93*cover:.0f} % and the MCP must read M (CH2 is free); not pursued")
    # --- OFF: charge injection at the OFF event (ngspice with our TMUXB)
    cn = c1 + c2tot
    lg = spice("c3_qinj", f"""* C3 charge injection at turn-off into node N (C_N={cn*1e12:.1f} pF incl. C1), Rth={rth/1e3:.0f} k
.include models/tmux_beh.lib
Vc ctl 0 PWL(0 1 1u 1 1.01u 0)
Vd s 0 DC 1.65
Xs n s ctl TMUXB ron=3.7 csoff=6p cdoff=0.1p ileak=0 qinj=6p
Rth n vm {rth}
Vm vm 0 DC 1.65
Cn n 0 {cn}
.tran 20n 100u
.control
run
meas tran dv max v(n)
meas tran dvmin min v(n)
.endc
.end
""")
    dv = max(abs(meas(lg, "dv")-1.65), abs(meas(lg, "dvmin")-1.65))
    tau = rth*cn
    out["qinj"] = dict(dV_N=dv, tau_us=tau*1e6)
    res = {nm_: tau*math.log(max(g*dv/(0.5*LSB12), 1.0)) for nm_, g in (("+-5 V", 1.0), ("+-1.25 V", G))}
    out["qinj_settle_us"] = {k: v*1e6 for k, v in res.items()}
    case("C3-d", "PA-4 charge injection when the switch turns OFF (6 pC, SCDS401C Sec 5.6): step at N and time for the scope pin to settle to 0.5 LSB", "static error 0 (event only); settle <= 1 ms (~1000 samples) so calibration can be cleared by waiting",
         f"{dv*1e3:.0f} mV at N, settles to 0.5 LSB in {res['+-5 V']*1e6:.0f} us (+-5 V) / {res['+-1.25 V']*1e6:.0f} us (+-1.25 V); no error while the switch stays off", f"{(1e-3-max(res.values()))*1e6:.0f} us", max(res.values()) <= 1e-3,
         "sim step at N agrees with Q/C_N = %.0f mV" % (6e-12/cn*1e3))
    # --- ON: gain-fit accuracy per channel and range, DAC0 points read back by the MCP at DAC0's pin
    n0 = 1.65                                                      # N's Thevenin voltage with the input shorted (centred: Vmid)
    def gain_fit(npts, g, N=20000, navg=100000, inl=1.2, rcorr=7.4, ron_known=False, read_n=False):
        ge = []; oe = []
        lo, hi = (DAC0_LO, DAC0_HI) if g == 1.0 else (1.65-1.45/g, 1.65+1.45/g)     # keep the pin inside ~0.2-3.1 V
        for _ in range(N):
            vdx = np.linspace(lo, hi, npts)
            v_read = vdx + rng.uniform(-42e-6, 42e-6, npts) + rng.normal(0, 1.2e-6, npts)     # MCP readback of DAC0's pin: INL 7 ppm x 6 V, noise
            ron = rng.uniform(3.7, 8.8) + rng.uniform(3.7, 8.8)          # T-switch: two TMUX1119 in series at 3.3 V, 3.7 typ, 8.8 max each (Sec 5.5)
            vn_true = vdx - (vdx - n0)*ron/(ron + rth)                  # node N: the switch's Ron against the divider's Thevenin
            vn_est = v_read - (v_read - n0)*rcorr/(rcorr + rth)         # corrected with an assumed Ron of both switches
            if ron_known: vn_est = v_read - (v_read - n0)*ron/(ron + rth)          # (a) the host has estimated this switch's Ron exactly
            if read_n: vn_est = vn_true + rng.uniform(-42e-6, 42e-6, npts) + rng.normal(0, 1.2e-6, npts)   # (c) the MCP reads N itself
            a = 4095/3.3*(1+rng.uniform(-0.0156, 0.0029)); b = rng.uniform(-30, 56)
            slope = a*g
            pin_code = slope*(vn_true-1.65) + a*1.65 + b + rng.uniform(-inl, inl, npts) + rng.normal(0, math.hypot(0.8, 0.5)/math.sqrt(navg), npts)
            A = np.vstack([vn_est-1.65, np.ones(npts)]).T
            sl, ic = np.linalg.lstsq(A, pin_code, rcond=None)[0]
            ge.append(abs(sl/slope-1)); oe.append(abs(ic-(a*1.65+b))*1.0)
        return np.percentile(ge, 99.9)*100, np.percentile(oe, 99.9)
    for npts in (8, 32, 64):
        for nm_, g in (("+-5 V", 1.0), ("+-1.25 V", G)):
            out[f"fit_{nm_}_{npts}"] = gain_fit(npts, g, rcorr=12.7)       # the middle of the T-switch's 7.4-17.6 ohm
    for nm_, g in (("+-5 V", 1.0), ("+-1.25 V", G)):
        out[f"fit_{nm_}_32_typcorr"] = gain_fit(32, g, rcorr=7.4)
    opts = {"32 points (previous)": dict(npts=32), "(a) Ron estimated exactly by the host, 32 points": dict(npts=32, ron_known=True),
            "(c) MCP reads N directly, 32 points": dict(npts=32, read_n=True), "128 points": dict(npts=128), "Due INL 0.5 LSB (measured line, afe.md 4.1), 32 points": dict(npts=32, inl=0.5)}
    out["c3e_options"] = {}
    for lab, kw in opts.items():
        ge, oe = gain_fit(g=1.0, rcorr=12.7, **kw)
        out["c3e_options"][lab] = (ge, oe)
        case(f"C3-e [+-5 V, {lab}]", "as C3-e [+-5 V] with " + lab, "gain <= 0.05 %, offset <= 0.5 LSB at 99.9 %", f"{ge:.3f} % / {oe:.2f} LSB", f"{0.05-ge:.3f} %", ge <= 0.05 and oe <= 0.5)
    # ---- the new low-impedance input (SC-3, ~20-30 kohm, being designed in sim/scope): N modelled as RTH to Vmid + 2 pF,
    # RTH 3.6-5.3 kohm (coordinator's placeholder until the scope agent gives values).  The T-switch (2 x 3.7-8.8 ohm) and an
    # isolation resistor at the DAC0 buffer (22-49.9 ohm, being added by the AWG agent) now divide against a few kohm.
    def gain_fit_lo(g, rth_, riso, mode, npts=64, N=20000, navg=100000, inl=1.2, zin=2.08e6, zin_unc=0.30):
        """N = Thevenin rth_ to Vmid, driven during injection by the DAC0 buffer through rser = 2 Ron + Riso.
        mode 'src':   MCP reads the buffer output; the host corrects rser at its nominal (Ron 2 x 6.35, Riso as given).
        mode 'n_sim': MCP reads N with its mux held on N while the Due reads: both see the same loaded node.
        mode 'n_seq': MCP reads N, then releases it while the Due reads; the MCP's Zin (to ground, +-30 %) loads N
                      only while it is connected, and the host corrects it with the nominal Zin."""
        ge = []; oe = []
        lo, hi = (DAC0_LO, DAC0_HI) if g == 1.0 else (1.65-1.45/g, 1.65+1.45/g)
        for _ in range(N):
            vs = np.linspace(lo, hi, npts)
            rser = rng.uniform(3.7, 8.8) + rng.uniform(3.7, 8.8) + riso*(1+rng.uniform(-0.01, 0.01))
            zt = zin*(1+rng.uniform(-zin_unc, zin_unc))
            node = lambda gz: (vs/rser + n0/rth_)/(1/rser + 1/rth_ + gz)           # gz: conductance of the MCP input to ground
            v_free, v_mcp = node(0.0), node(1/zt)
            if mode == "src":
                vr = vs + rng.uniform(-42e-6, 42e-6, npts) + rng.normal(0, 1.2e-6, npts); rn = 12.7 + riso
                est = (vr/rn + n0/rth_)/(1/rn + 1/rth_); v_due = v_free
            elif mode == "n_sim":
                est = v_mcp + rng.uniform(-42e-6, 42e-6, npts) + rng.normal(0, 1.2e-6, npts); v_due = v_mcp
            else:
                m = v_mcp + rng.uniform(-42e-6, 42e-6, npts) + rng.normal(0, 1.2e-6, npts)
                g0 = 1/(12.7 + riso) + 1/rth_
                est = m*(g0 + 1/zin)/g0; v_due = v_free
            a = 4095/3.3*(1+rng.uniform(-0.0156, 0.0029)); b = rng.uniform(-30, 56); slope = a*g
            code = slope*(v_due-1.65) + a*1.65 + b + rng.uniform(-inl, inl, npts) + rng.normal(0, math.hypot(0.8, 0.5)/math.sqrt(navg), npts)
            A = np.vstack([est-1.65, np.ones(npts)]).T
            sl, ic = np.linalg.lstsq(A, code, rcond=None)[0]
            ge.append(abs(sl/slope-1)); oe.append(abs(ic-(a*1.65+b)))
        return float(np.percentile(ge, 99.9)*100), float(np.percentile(oe, 99.9))
    # loading of N by the MCP: undriven (switch off) it is rth/zin; during injection N is held by the ~30-70 ohm source
    out["mcp_load"] = {f"{r_/1e3:.1f}k": dict(undriven_pct=r_/2.08e6*100, driven_pct=par(r_, 12.7+49.9)/2.08e6*100) for r_ in (3.6e3, 4.5e3, 5.3e3)}
    out["n_pole_MHz"] = {f"{r_/1e3:.1f}k": 1/(2*math.pi*r_*(2e-12+6e-12))/1e6 for r_ in (3.6e3, 4.5e3, 5.3e3)}
    lo_rows = {}
    for rth_ in ((3.6e3, 4.5e3, 5.3e3) if LOWZ else ()):
        for riso in (22.0, 49.9):
            for mode in ("src", "n_sim", "n_seq"):
                for nm_, g in (("+-5 V", 1.0), ("+-1.25 V", G)):
                    if rth_ != 4.5e3 and nm_ != "+-5 V": continue
                    lo_rows[f"{rth_/1e3:.1f}k|{riso:g}|{mode}|{nm_}"] = gain_fit_lo(g, rth_, riso, mode)
    out["c3e_lo"] = lo_rows
    lab = {"src": "MCP reads the DAC0 buffer output", "n_sim": "MCP reads N, mux held on N during the Due's read", "n_seq": "MCP reads N, then releases it (Zin corrected, +-30 %)"}
    for mode in (("src", "n_sim", "n_seq") if LOWZ else ()):
        rows = {k: v for k, v in lo_rows.items() if f"|{mode}|" in k}
        w = max(v[0] for v in rows.values()); wo = max(v[1] for v in rows.values()); kw = max(rows, key=lambda k: rows[k][0])
        case(f"C3-e [low-Z input, {lab[mode]}]", f"PA-3 gain/offset fit with N at a 3.6-5.3 kohm Thevenin (SC-3 redesign, placeholder), T-switch + 22-49.9 ohm isolation, 64 points, both ranges",
             "gain <= 0.05 %, offset <= 0.5 LSB at 99.9 %", f"worst {w:.3f} % / {wo:.2f} LSB (at {kw.replace('|', ', ')})", f"{0.05-w:.3f} %", w <= 0.05 and wo <= 0.5,
             "N's values are the coordinator's placeholder until sim/scope gives them; the MCP's Zin loads N by 0.17-0.25 % only while N is undriven, and by under 0.003 % during injection")
    for nm_, g in (("+-5 V", 1.0), ("+-1.25 V", G)):
        ge8, oe8 = out[f"fit_{nm_}_8"]; ge32, oe32 = out[f"fit_{nm_}_64"]
        case(f"C3-e [{nm_}]", f"PA-3 switch ON: per-channel gain/offset fit from DAC0 points read back by the MCP at DAC0's pin, {nm_} range (Due ADC INL 1.2 LSB, held-code noise 0.8 + DAC 0.5 codes over 10^5 samples, T-switch Ron 7.4-17.6 ohm corrected at its middle, 12.7 ohm)",
             "gain <= 0.05 % (1/10 of SC-7), offset <= 0.5 LSB at 99.9 %", f"64 points: {ge32:.3f} % / {oe32:.2f} LSB (8 points {ge8:.3f} %, 32 points {out[f'fit_{nm_}_32'][0]:.3f} %)",
             f"{0.05-ge32:.3f} %", ge32 <= 0.05 and oe32 <= 0.5, f"corrected at the typical 7.4 ohm instead: {out[f'fit_{nm_}_32_typcorr'][0]:.3f} %; reference scale (0.1 %) excluded here, added in PA-6; DAC0's noise in the MCP's 19 Hz band is not in the datasheet *(check)*")
    R["c3"] = out


# ---- C4: PA-1 effective resolution, PA-6 accuracy statement, time cost
# ---- tee calibration (approved 2026-11-11): the AWG into both scope inputs through a BNC tee, the ADC reading the AWG
# through its sense divider (Ra = Rb = 100k 0.1 % 10 ppm/K, C394537; k = 1/2) whose bottom end PA-4's ratio switch (one
# TMUX1119, SEL pulled down: S1 = the AWG's Vmid, S2 = the buffered 3.0 V ladder top) moves so the ratio is measured.  The
# injection T-switches, the 249 ohm injection branch and the C3 rows are retired.  The fit figures are whatif/tee's.
LIM_TEE = 0.1       # % : the tee fit share on both ranges (owner decision 2026-11-11, k = 1/3 kept); was 0.05 % (1/10 of SC-7)
LIM_RSW = LIM_TEE/10   # % : the ratio switch's share, proposed here (1/10 of the tee's share)
TEE_DIR = os.path.join(HERE, "..", "..", "whatif", "tee", "results")
TEE_K = "k = 1/2 (2 x 100k)"               # 2026-11-11: k = 1/2 (Ra = Rb = 100k, C394537) after whatif/tee's re-run with the ADC INL at the AWG; was k = 1/3
TEE_RUNS = {"+-1.25 V, 256 points": "1.25|1.15|pt1.2|256", "+-5 V, 1024 points": "5|1.15|pt1.2|1024"}
# whatif/tee report.md, "Update: precision-ADC INL at the AWG node (re-run, 2026-11-11)": linear sum of fit, ratio measurement
# and 10 K drift, (nominal, at the bound: per-point INL to an S-bow within the AWG span).  Quoted, not recomputed; the
# +-1.25 V k = 1/2 rows give one figure, used for both *(check)*.  ADS1220 at k = 1/2 on +-5 V needs 2048 points (4096 at
# the bound) per the same section, which gives no figure for those counts.
TEE_TAB = {("ADS124S08", "k = 1/2 (2 x 100k)", "+-1.25 V, 256 points"): (0.051, 0.051), ("ADS124S08", "k = 1/2 (2 x 100k)", "+-5 V, 1024 points"): (0.074, 0.091),
           ("ADS124S08", "k = 1/3 (100k + 100k over 100k)", "+-1.25 V, 256 points"): (0.069, 0.086), ("ADS124S08", "k = 1/3 (100k + 100k over 100k)", "+-5 V, 1024 points"): (0.092, 0.109),
           ("ADS1220", "k = 1/2 (2 x 100k)", "+-1.25 V, 256 points"): (0.063, 0.063), ("ADS1220", "k = 1/2 (2 x 100k)", "+-5 V, 1024 points"): (0.085, 0.111),
           ("ADS1220", "k = 1/3 (100k + 100k over 100k)", "+-1.25 V, 256 points"): (0.088, 0.113), ("ADS1220", "k = 1/3 (100k + 100k over 100k)", "+-5 V, 1024 points"): (0.111, 0.136)}
def tee_figures(adc="ADS124S08"):
    """whatif/tee's totals (report.md re-run section) and its fit from inl.json for the guard"""
    inl = json.load(open(os.path.join(TEE_DIR, "inl.json")))["abs"]
    out = {}
    for kl in (TEE_K, "k = 1/3 (100k + 100k over 100k)"):
        for lab, key in TEE_RUNS.items():
            nom, bnd = TEE_TAB[(adc, kl, lab)]
            out[(kl, lab)] = dict(nominal=nom, bound=bnd, fit=inl[key], key=key)
    return out
def run_tee():
    out = {}
    for (kl, lab), v in tee_figures().items():
        out[f"{kl}|{lab}"] = dict(**v, linear=v["bound"])
        tag = lab if kl == TEE_K else f"{lab}, k = 1/3 (previous)"
        case(f"C3-t [{tag}]", f"PA-3 tee calibration, ADS124S08: gain fit + ratio measurement + 10 K drift, {lab}, {kl} (whatif/tee re-run with the ADC's INL at the AWG)", f"<= {LIM_TEE:.2f} % (owner, 2026-11-11)",
             f"{v['nominal']:.3f} % ({v['bound']:.3f} % at the bound)", f"{LIM_TEE-v['bound']:.3f} %", v["bound"] <= LIM_TEE,
             "quoted from whatif/tee report.md (re-run section), not recomputed; judged at the bound")
    # PA-4 ratio switch.  Design: the ADC reads the divider's bottom node (after the switch), so the estimator
    # 1 - k = (tap2 - tap1) / (bot2 - bot1) holds whatever the switch adds in series: Ron and the switch's leakage both
    # land on the read node and drop out.  What is left is the ADC's own input current at the tap and the bottom node.
    # Variant (sources read instead of the bottom node): Ron differs between the throws and enters the ratio.
    ra, rb = 100e3, 100e3; dron = 2.2 + 0.4                          # TMUX1119 at 3.3 V: Ron flatness 2.2 ohm + channel matching 0.4 ohm, -40..125 C (SCDS401C Sec 5.6)
    ileak = 0.35e-9; ron = 9.8                                 # channel leakage 0.35 nA max (-40..85 C; Sec 5.5, the 3.3 V row is taken equal) *(check)*; Ron 9.8 ohm max
    dk_ron_var = dron*ra/(ra+rb)**2                            # d(1-k) from Rb changing by dron between the two states
    dk_leak_var = ileak*ron/(3.0-1.65)
    dk_ads = 0.5e-9*ron/(3.0-1.65)                             # the ADC's 0.5 nA (typ, no max) through Ron at the read bottom node: read, so only a reading offset common to both states
    out["ratio_switch"] = dict(dk_design_pct=0.0, dk_ron_variant_pct=dk_ron_var*100, dk_leak_variant_pct=dk_leak_var*100, ads_rth_gain_pct=1e-9*par(ra, rb)*100)
    case("C3-u", "PA-4 ratio switch (one TMUX1119 at the sense divider's bottom: S1 Vmid / S2 3.0 V ladder top): Ron and leakage error on the measured ratio, with the ADC reading the bottom node",
         f"<= {LIM_RSW:.3f} % (proposed: 1/10 of the tee's {LIM_TEE:.1f} %)", f"0 to first order: Ron ({ron:.1f} ohm max) and leakage ({ileak*1e9:.2f} nA) act on the node the ADC reads; with the sources read instead (variant) Ron's {dron:.1f} ohm throw-to-throw difference gives {dk_ron_var*100:.5f} % and leakage {dk_leak_var*100:.1e} %",
         f"{LIM_RSW:.4f} %", True,
         f"the ADS124S08's 1 nA/V input current on the tap's 50 kohm is {1e-9*par(ra, rb)*100:.4f} % of gain, already in whatif/tee's sense term; the variant also passes ({(dk_ron_var+dk_leak_var)*100:.4f} %)")
    case("C3-v", "PA-4 ratio switch default state: SEL pulled down, so S1 (the AWG's Vmid) at reset, unpowered Due and unconfigured pin (TMUX1119 truth table, Sec 7.5: SEL 0 -> S1)",
         "default = Vmid", "S1 = Vmid with SEL low; both throws (1.65 V, 3.0 V) inside the switch's 0 to +3.3 V_A supply", "-", True,
         "the pull-down is the existing 4.7k (or 10k) type; the AWG sees 200 kohm to the far end either way")
    out["retired"] = "C3-a/b/c/d/e/f and the SC-9 injection rows retired 2026-11-11 with the T-switches and the 249 ohm injection branch"
    R["tee"] = out
    run_inprot()

BAT_LIB = "../../models-open/bat54s-c7420333/bat54s_c7420333.lib"     # our own fit to C7420333's datasheet (SOURCE.txt beside it)
RS_S1 = 100e3       # series resistor, the AWG's Vmid node -> the ratio switch's S1 (100k 0.1 %, C394537; approved 2026-11-11: the
                    # previous 4.7k back-fed the dead +3.3 V_A to 0.80 V, C1-r), the clamp behind it
def clamp_netlist(vx, vvm, vdd, chan, dmod, clamp=True, rs=None):
    """Unpowered ratio switch and ADC sense inputs, DC.  BNC forced to vx; the AWG's Vmid node (S1's source) at vvm,
    sim/awg's unpowered level backed out of its tap figures (an ideal source: pessimistic).  vdd: 'held' (+3.3 V_A held
    at 0 V) or 'float' (only the 4.7k bleed to ground).  chan: the unpowered TMUX1119's D-S1 channel, 'open' or 'on'
    (10 ohm); its unpowered behaviour is not in its datasheet.  Every IC pin has an ESD pair to its supply and ground
    (generic, IS 1e-15, the sense.py diode).  The BAT54S pairs (one package per node: one die to ground, one to +3.3 V_A)
    sit on D and on S1 (behind RS_S1)."""
    L = [f"* unpowered ratio switch clamp vx={vx} vvm={vvm} vdd={vdd} chan={chan} {dmod} clamp={clamp}", f".include {BAT_LIB}",
         ".model DESD D(IS=1e-15 N=1 RS=5)",
         f"Vx bnc 0 DC {vx}", "Rse1 bnc tap 100k", "Rse2 tap d 100k", "Rint tap 0 1G", "Rind d 0 1G",
         f"Vvm vmw 0 DC {vvm}", f"Rs vmw s1 {RS_S1 if rs is None else rs}", "Rlad s2 0 1328",
         ("Rch d s1 10" if chan == "on" else "Rch d s1 1G"), "Rch2 d s2 1G"]
    for n in ("tap", "d", "s1", "s2"):
        L += [f"De1{n} {n} vdd DESD", f"De2{n} 0 {n} DESD"]
    if clamp:
        for n in ("d", "s1"):
            L += [f"Dc1{n} {n} vdd {dmod}", f"Dc2{n} 0 {n} {dmod}"]
    L.append("Vdd vdd 0 DC 0" if vdd == "held" else "Rbl vdd 0 4.7k")
    L += [".control", "op", "print v(tap) v(d) v(s1) v(s2) v(vdd)", ".endc", ".end"]
    return "\n".join(L) + "\n"

def run_inprot():
    """ADS124S08 inputs (the sense tap and the divider's bottom node) and the ratio switch's pins against their absolute
    maxima.  ADS124S08 (SBAS660C 7.1): AINx AVSS - 0.3 .. AVDD + 0.3 V and 10 mA continuous.  Owner ruling (2026-11-11,
    PR-4): an unpowered pin past its voltage rating may rely on current limiting only where that part's datasheet allows
    it; the ADS124S08 does (SBAS660C 9.3 and the +-10 mA rating), so its inputs are judged on current when unpowered.
    The TMUX1119 does not (SCDS401C 5.1: VS/VD -0.5 .. VDD + 0.5 V; IS/ID is the conduction rating), so its pins are
    judged on voltage, with a BAT54S clamp (ngspice, our open model).  Divider: 200k BNC -> tap, 100k tap -> D.  Tap
    voltages are sim/awg's (raw/results.json 'sense', k = 1/3, read 2026-11-11)."""
    rth = par(100e3, 100e3); avdd_nom, avdd_min = 3.288, 3.25
    # k = 1/2 (2026-11-11): tap = (Va + Vfar)/2.  sim/awg's AWG node levels (AW-8 -1.720 .. +1.513 V; its k = 1/2 tap rows are
    # pending) and AW-8's +-2.1 V requirement bound; far ends Vmid 1.624-1.676 V, the reference 2.994-3.006 V; unpowered, the
    # dead Vmid node backed out of sim/awg's k = 1/3 taps (tap = Va/3 + 2/3 Vfar) and the reference at 0 V *(check)*.
    VM_DEAD = {1.8: ((-1.049 + 0.6)*1.5, (1.795 - 0.6)*1.5), 5.0: ((-2.131 + 5/3)*1.5, (3.674 - 5/3)*1.5)}
    t2 = lambda lo, hi, f: ((lo + f[0])/2, (hi + f[1])/2)
    vm_, rf_ = (1.624, 1.676), (2.994, 3.006)
    AWG = {"AW-8 reset/boot excursion, powered (sim/awg -1.720 .. +1.513 V)": {"Vmid": t2(-1.720, 1.513, vm_), "3.0 V top": t2(-1.720, 1.513, rf_)},
           "AW-8 requirement bound +-2.1 V, powered": {"Vmid": t2(-2.1, 2.1, vm_), "3.0 V top": t2(-2.1, 2.1, rf_)},
           "PR-4 +-1.8 V forced, powered": {"Vmid": t2(-1.8, 1.8, vm_), "3.0 V top": t2(-1.8, 1.8, rf_)},
           "PR-4 +-1.8 V forced, unpowered": {"Vmid (dead)": t2(-1.8, 1.8, VM_DEAD[1.8]), "3.0 V top (0 V)": (-0.9, 0.9)},
           "PR-4 +-5 V forced, powered": {"Vmid": t2(-5.0, 5.0, vm_), "3.0 V top": t2(-5.0, 5.0, rf_)},
           "PR-4 +-5 V forced, unpowered": {"Vmid (dead)": t2(-5.0, 5.0, VM_DEAD[5.0]), "3.0 V top (0 V)": (-2.5, 2.5)}}
    must = lambda lab: "+-5 V" not in lab                       # PR-4: above +-1.8 V the shield may be damaged
    # ---- the clamp, unpowered +-1.8 V (and +-5 V for the record), ngspice
    jobs, keys = [], []
    for va in (1.8, 5.0):
        for sg, vvm in ((+1, VM_DEAD[va][1]), (-1, VM_DEAD[va][0])):
            for vdd in ("held", "float"):
                for chan in ("open", "on"):
                    for dm, cl in (("DBAT54S_MAX", True), ("DBAT54S_TYP", True), ("none", False)):
                        if not cl and (vdd, dm) != ("held", "none"): continue
                        nm = f"clamp_{va:g}_{'p' if sg > 0 else 'n'}_{vdd}_{chan}_{dm}"
                        jobs.append((nm, clamp_netlist(sg*va, vvm, vdd, chan, dm if cl else "DBAT54S_TYP", clamp=cl))); keys.append((va, sg, vdd, chan, dm))
    cl = {}
    for k_, log in zip(keys, spice_many(jobs)):
        v = {n: meas(log, f"v({n})") for n in ("tap", "d", "s1", "s2", "vdd")}
        rel = max(max(v[n] - v["vdd"] for n in ("d", "s1", "s2")), max(-v[n] for n in ("d", "s1", "s2")))
        cl[k_] = dict(v, worst_beyond_rail=rel, i_s1_mA=abs(VM_DEAD[k_[0]][0 if k_[1] < 0 else 1] - v["s1"])/RS_S1*1e3)
    def worst(va, dm):
        rows = [x for k_, x in cl.items() if k_[0] == va and k_[4] == dm]
        return max(rows, key=lambda x: x["worst_beyond_rail"])
    R["clamp_rs_kohm"] = RS_S1/1e3
    R["clamp"] = {f"{k_[0]:g}|{'+' if k_[1] > 0 else '-'}|{k_[2]}|{k_[3]}|{k_[4]}": x for k_, x in cl.items()}
    for va in (1.8, 5.0):
        wn, wm, wt = worst(va, "none"), worst(va, "DBAT54S_MAX"), worst(va, "DBAT54S_TYP")
        ok = wm["worst_beyond_rail"] <= 0.5
        imax = max(x["i_s1_mA"] for k_, x in cl.items() if k_[0] == va and k_[4] != "none")
        lab = f"PR-4 +-{va:g} V forced, unpowered"
        case(f"C1-q [{lab}]", f"TMUX1119 ratio-switch pins (D, S1, S2) unpowered, {lab}: BAT54S (C7420333) on D and on S1 (behind {RS_S1/1e3:.1f}k from the AWG's Vmid node), to ground and +3.3 V_A; +3.3 V_A held at 0 V or floating on the 4.7k bleed; channel open or on",
             "-0.5 V .. VDD + 0.5 V (SCDS401C 5.1)", f"worst {wm['worst_beyond_rail']:.3f} V beyond a rail (BAT54S at its datasheet maximum Vf; {wt['worst_beyond_rail']:.3f} V typical); without the clamps {wn['worst_beyond_rail']:.3f} V; S1 clamp current <= {imax:.2f} mA",
             f"{0.5-wm['worst_beyond_rail']:.3f} V", ok or va > 2,
             "the AWG's Vmid node is an ideal source at sim/awg's backed-out unpowered level (pessimistic); the TMUX1119's own ESD and unpowered channel are generic *(check)*" + ("" if va < 2 else "; recorded, not judged: PR-4 allows shield damage at +-5 V"))
    # ---- back-feed: the clamps' current lifts the dead +3.3 V_A (only its 4.7k bleed modelled: pessimistic); PR-3/PR-4 want
    # the rails under 0.5 V.  The design's 4.7k to S1, and larger series resistors from existing types
    bf_jobs, bf_keys = [], []
    for rsx in (4.7e3, 3*4.7e3, 100e3):
        for va in (1.8, 5.0):
            for chan in ("open", "on"):
                bf_jobs.append((f"bfeed_{rsx:g}_{va:g}_{chan}", clamp_netlist(va, VM_DEAD[va][1], "float", chan, "DBAT54S_TYP", rs=rsx))); bf_keys.append((rsx, va, chan))
    bf = {}
    for k_, log in zip(bf_keys, spice_many(bf_jobs)):
        bf[k_] = dict(vdd=meas(log, "v(vdd)"), s1=meas(log, "v(s1)"), d=meas(log, "v(d)"))
    R["backfeed"] = {f"{k_[0]:g}|{k_[1]:g}|{k_[2]}": v for k_, v in bf.items()}
    for rsx in (4.7e3, 3*4.7e3, 100e3):
        w18 = max(bf[(rsx, 1.8, c_)]["vdd"] for c_ in ("open", "on")); w5 = max(bf[(rsx, 5.0, c_)]["vdd"] for c_ in ("open", "on"))
        des = rsx == RS_S1
        tag = "" if des else (" [4.7k to S1, previous]" if rsx < 5e3 else " [3 x 4.7k to S1]")
        case(f"C1-r{tag}", f"PR-3 / PR-4 unpowered: +3.3 V_A lifted by the ratio-switch clamps' current (S1 behind {rsx/1e3:.1f}k from the AWG's Vmid node; the rail loaded by its 4.7k bleed only), BNC forced +1.8 V and +5 V",
             "< 0.5 V (PR-3)", f"+1.8 V: {w18:.3f} V; +5 V: {w5:.3f} V", f"{0.5-w18:.3f} V at 1.8 V", w18 < 0.5,
             "the bleed is the rail's only load here; the unpowered op-amps, the REF3030 and the ADC also sink it *(check)*; +5 V is recorded (PR-4 allows shield damage, but not back-feed into the Due)")
    out = {}
    for lab, fars in AWG.items():
        pw = "unpowered" not in lab
        hi_nom = (avdd_nom + 0.3) if pw else 0.3; hi_min = (avdd_min + 0.3) if pw else 0.3; rail = avdd_nom if pw else 0.0
        lo_all = min(v[0] for v in fars.values()); hi_all = max(v[1] for v in fars.values())
        i_cl = max(max(0.0, hi_all - rail), max(0.0, -lo_all))/rth
        ok_v = lo_all >= -0.3 and hi_all <= hi_min
        ok = ok_v if pw else i_cl <= 10e-3                        # unpowered: current limiting allowed for the ADS124S08 (owner ruling)
        out[lab] = dict(tap_V={f: list(v) for f, v in fars.items()}, i_clamp_max_uA=i_cl*1e6, ok_tap=ok, ok_voltage=ok_v, must=must(lab), limit_V=[-0.3, hi_min])
        tv = "; ".join(f"far end {f}: {v[0]:+.3f} .. {v[1]:+.3f} V" for f, v in fars.items())
        lim = (f"AINx -0.3 .. AVDD + 0.3 = {hi_min:.2f} V at AVDD min ({hi_nom:.3f} V nominal), 10 mA" if pw
               else "AVDD = 0: AINx current <= 10 mA (current limiting allowed for this part, owner ruling 2026-11-11); voltage -0.3 .. +0.3 V for the record")
        res = f"tap {tv}; clamp current <= {i_cl*1e6:.1f} uA through 100k || 100k" + ("" if ok_v else f"; voltage beyond the rating by {max(-0.3 - lo_all, hi_all - hi_min):.3f} V")
        if pw: res += f"; operating window -0.05 .. {avdd_min+0.05:.2f} V: {'inside' if lo_all >= -0.05 and hi_all <= avdd_min + 0.05 else 'outside (no reading is taken then)'}"
        case(f"C1-p [{lab}]", f"ADS124S08 sense inputs (tap; the bottom node is the clamped D, C1-q) against absolute maximum, {lab}, k = 1/2 (taps from sim/awg's AWG levels)", lim, res,
             "-" if ok else "over the voltage limit; PR-4 permits shield damage above +-1.8 V", ok or not must(lab),
             ("voltage judged powered" if pw else "unpowered: judged on current, the voltage rating exceeded through current limiting as SBAS660C allows")
             + ("" if must(lab) else "; recorded, not judged: PR-4 allows shield damage at +-5 V"))
    # ---- the clamps in normal operation: leakage at D (1.65 V or 3.0 V) and at S1 (1.65 V), +3.3 V_A 3.235-3.342 V
    IS_T, N_T, IS_M, N_M, VT_ = 2.51e-8, 1.015, 1.63e-8, 1.120, 0.025852
    def ileak(vr, model):                                      # reverse current of one die at vr: the junction plus the BAT54S_LEAK resistor (25 V / 2 uA)
        is_, n_ = (IS_T, N_T) if model == "typ" else (IS_M, N_M)
        return is_*(1 - math.exp(-vr/(n_*VT_))) + (vr/12.5e6 if model == "leak" else 0.0)
    lk = {}
    for vdd in (3.235, 3.342):
        for vd in (1.65, 3.006):
            for m in ("typ", "leak"):
                lk[f"{vdd}|{vd}|{m}"] = (ileak(vdd - vd, m) - ileak(vd, m))*1e9    # nA into D (from the +3.3 V_A die, out through the ground die)
    worst_diff = max(abs(lk[f"{v}|3.006|leak"] - lk[f"{v}|1.65|leak"]) for v in (3.235, 3.342))
    ron = 9.8
    out["clamp_leak_nA"] = lk; out["clamp_leak_state_diff_nA"] = worst_diff
    out["clamp_leak_D_shift_uV_datasheet"] = 2*2e-6*ron*1e6     # both dies at the 2 uA datasheet bound, through Ron
    case("C3-w", "PA-4 BAT54S clamp leakage in normal operation, and its effect on the measured ratio",
         f"<= {LIM_RSW:.3f} % on the ratio (C3-u's share)",
         f"model {lk['3.235|1.65|typ']:.2f} / {lk['3.235|3.006|typ']:.2f} nA (junction only) and {lk['3.235|1.65|leak']:.0f} / {lk['3.235|3.006|leak']:.0f} nA (with the 25 V / 2 uA resistor) into D at 1.65 / 3.0 V, a {worst_diff:.0f} nA difference between the states; the datasheet's only figure is 2 uA max at 25 V, so at 1-3 V it bounds each die by 2 uA and no better (monotone in VR assumed). The clamps sit on D and S1, not on the tap: D's leakage flows through the switch into its source, through Ron alone on S2 and through Ron + {RS_S1/1e3:.0f}k on S1, and moves D by up to {2*2e-6*(ron+RS_S1):.2f} V at the datasheet bound ({2*abs(lk['3.235|1.65|leak'])*1e-9*(ron+RS_S1)*1e3:.1f} mV with the model), which the ADC reads; S1's own leakage flows through the same {RS_S1/1e3:.0f}k and is read the same way. Ratio error 0 to first order",
         f"{LIM_RSW:.4f} %", True,
         "the ~0.67 nA tolerance applies to current injected at the tap, where no clamp sits; a clamp on the tap would cost 2 uA x 66.7 kohm = 133 mV there and is not used")
    R["inprot"] = out

def run_c4():
    """PA-1 / PA-6 / timing with the ADS124S08 (low-latency filter, 20 SPS)"""
    bw_enb = 20.0/2                                            # equivalent bandwidth taken as DR / 2 *(check: the filter's ENB is not in the datasheet text read)*
    n_adc = ADS_NOISE
    n_ref = 51e-6/math.sqrt(10e3-10)*math.sqrt(bw_enb) ; n_ref = math.hypot(n_ref, 24e-6/6.6)      # REF3030E: 51 uVrms (10 Hz-10 kHz) white + 24 uVpp (0.1-10 Hz) as 6.6 sigma
    n_buf = 5e-6/6.6                                           # OPA365 5 uVpp 0.1-10 Hz
    ext = math.hypot(n_adc, n_ref, n_buf)
    bits_taps = math.log2(VREF/ADS_NOISE_PP); bits_ext = math.log2(VREF/(6.6*ext))
    R["c4_noise"] = dict(n_mcp_uV=n_adc*1e6, n_ref_uV=n_ref*1e6, n_buf_uV=n_buf*1e6, ext_uV=ext*1e6, bits_taps=bits_taps, bits_ext=bits_ext, bw_hz=bw_enb)
    case("C4-a", "PA-1 effective resolution of the ADS124S08 path, noise-free over the 3.0 V span, 20 SPS low-latency filter (Table 3: 1.2 uVrms, 8.0 uVpp)",
         ">= 16 bit", f"{bits_ext:.1f} bit on external signals (reference noise {n_ref*1e6:.1f} uV dominates), {bits_taps:.1f} bit on ladder taps from the 8.0 uVpp (ratiometric: the reference's noise cancels)",
         f"{bits_ext-16:.1f} bit", bits_ext >= 16, "Table 3 is for PGA enabled, gain 1, internal 2.5 V reference; PGA bypassed at 3.0 V is not tabulated *(check)*")
    terms = {"REF3030E initial accuracy 0.1 %": 3.0*0.001, "tempco 15 ppm/C x +-10 C (15-35 C about the 25 C calibration)": 3.0*15e-6*10,
             "long-term drift 40 ppm first 1000 h": 3.0*40e-6, "REF3030E load regulation 15 ppm/mA x the ladder + REFP0 (B: no buffer)": 3.0*15e-6*(VREF/(RLAD_TOTAL*(1-RLAD_TOL))*1e3 + 0.018), "REF3030E self-heating at that load": 3.0*15e-6*(VP_MAX - VREF)*(VREF/(RLAD_TOTAL*(1-RLAD_TOL)))*218.5,
             "ADS124S08 INL 10 ppm FSR x 6 V": 60e-6, "ADS124S08 input current 1 nA/V x 3 V x the worst tap": 1e-9*3.0*ZI_NOM.max()}
    tot = sum(terms.values())
    meter = 3.0*70e-6                                          # 6.5-digit meter, ~70 ppm of reading at 3 V, ASSUMED *(check the borrowed meter's certificate)*
    with_meter = meter + sum(v for k, v in terms.items() if not k.startswith(("REF3030E initial", "REF3030E load regulation", "long-term")))
    R["c4_pa6"] = dict(terms_mV={k: v*1e3 for k, v in terms.items()}, total_mV=tot*1e3, total_pct=tot/3.0*100, with_meter_mV=with_meter*1e3, with_meter_pct=with_meter/3.0*100)
    case("C4-b", "PA-6 absolute accuracy of the ladder and sense readings, claimed only as far as the references allow (worst-case sum, no meter)", "no claim finer than the sum of its terms",
         f"+-{tot*1e3:.2f} mV = +-{tot/3.0*100:.3f} % at 3.0 V; with a 6.5-digit meter calibrating the reference: +-{with_meter*1e3:.2f} mV = +-{with_meter/3.0*100:.3f} %", "-", True,
         "the ADS124S08's 120 ppm gain error does not enter: every reading is taken against the ladder's top tap")
    t_due = NTAP*4096/1_046_510
    n_read = NTAP + 2*2                                        # six taps, and the sense tap and bottom node in both switch states
    R["c4_time"] = dict(due_ladder_s=t_due, mcp_channel_s=ADS_T_CONV, mcp_all8_s=n_read*ADS_T_CONV, n_read=n_read)
    case("C4-c", f"Sample-rate cost: ladder read ({NTAP} taps x 4096 samples at 1,046,510 sps total) and ADS124S08 readings ({n_read} single-shot 20 SPS conversions, {ADS_T_CONV*1e3:.1f} ms each, Table 13)", "calibration only (PA-9)",
         f"{t_due*1e3:.1f} ms Due side; {n_read*ADS_T_CONV:.2f} s ADC side", "-", True, "the tee calibration's own point count and time are whatif/tee's")
    # ---- the REF3030 output = ADS124S08 REFP0 = the OPA365 reference buffer's input: what capacitance may it carry?
    # REF30E EC table (SBVS032K Sec 6.5): stable output capacitor 0.1-22 uF, with note (3): "ESR for the capacitor can range from
    # 10 mohm to 500 mohm".  The non-E REF30 gives no range and warns about low ESR with large C (Sec 8.2); the design uses the
    # REF3030E (C38423 on the BOM is REF3030AIDBZR, the non-E grade, bom.md F-10).  No usable model (REF3030.lib is encrypted).
    # ADS124S08 (SBAS660C Sec 9.3.3.2): unbuffered reference input ~250 kohm (absolute input current 6 uA/V max with the
    # buffers off, Sec 7.5); "connect a 100-nF bypass capacitor across the external reference input pins".  The 10 uF at 3.0 V: Samsung's derating with -10 %; ESR from its curve at 0.1-1 MHz.
    c10 = 10e-6*SAM["k"](3.0)*C10_TOL; e10 = max(SAM["esr"](x) for x in (1e5, 3e5, 1e6))
    ESR_100N, ESR_1U = 0.03, 0.02      # 100 nF (Yageo CC0603KRX7R9BB104, C14663) and 1 uF X7R 0603 ESR, assumed *(check)*: Yageo's
                                       # data could not be fetched (2026-11-11: its site serves an HTML front end) and its MLCC datasheets give no ESR
    arr = {"100 nF alone at REFP0 (ADS124S08 Sec 9.3.3.2)": (0.1e-6*0.9, ESR_100N),
           "2 x 100 nF at REFP0": (2*0.1e-6*0.9, ESR_100N/2),
           "100 nF + 10 uF direct (BOM review)": (0.1e-6 + c10, e10),
           "100 nF + 1R + 10 uF (montreal5)": (0.1e-6 + c10, 1.0 + e10),
           "100 nF + (1R || 1R || 1R) + 10 uF": (0.1e-6 + c10, 1/3 + e10),
           "100 nF + (1R || 1R) + 10 uF": (0.1e-6 + c10, 0.5 + e10),
           "1 uF alone at REFP0 (fallback)": (1e-6, ESR_1U)}
    ref = {}
    for lab, (cl, esr) in arr.items():
        ok = 0.1e-6 <= cl <= 22e-6 and 0.010 <= esr <= 0.500
        ref[lab] = dict(C_uF=cl*1e6, ESR_mohm=esr*1e3, inside=ok)
        case(f"C4-d [{lab}]", "REF3030E output load (= ADS124S08 REFP0): inside the datasheet's stable range (CL 0.1-22 uF with ESR 10-500 mohm, REF30E Sec 6.5 note 3)",
             "0.1-22 uF and 10-500 mohm", f"{cl*1e6:.2f} uF effective, ESR {esr*1e3:.1f} mohm in the large capacitor's branch", "-" if ok else "outside", ok,
             "the 1R / 10 uF branch carries no DC, so the series R costs no DC accuracy; the reference's ringing with any load is not simulated (encrypted model) *(check, VT)*"
             + ("; the 1 uF's ESR is assumed *(check)*" if "1 uF" in lab else "") + ("; the 100 nF's ESR is assumed *(check)*; C at its -10 % tolerance (X7R K), DC bias at 3 V not in Yageo's data *(check)*" if "100 nF at REFP0" in lab or "alone at REFP0 (ADS" in lab else ""))
    R["c4_ref_load"] = ref

# =============================================================== lowcost what-if (2026-11-11, the owner's $35/board target)
# A ADS1220 (TI SBAS501D, models/ads1220/) instead of the ADS124S08; B the ladder straight on the REF3030 (no OPA365
# reference buffer); E the ladder from 1 % Basic resistors, 3 inner taps + the top.  LCSC prices read 2026-11-11 from
# its product-detail API (qty 10 column; untrusted data, not stored): ADS1220IPWR C48263 $1.9936 (stock 17,850),
# ADS124S08IPBSR C2870171 $7.5267 (1,257), OPA365AIDBVR C96626 $2.5707 (16,615), TMUX1119DCKR C2673327 $2.1406 (5,082),
# PTFR0603B249RN9 C2692731 $0.1735 (qty 5; 3,875), PTFR0603B100KN9 C394537 $0.174, 680R 1 % C23228 $0.0021 (756,200),
# BAT54S C7420333 $0.013, 100 nF CC0603KRX7R9BB104 C14663 $0.0166 (stock 0 at LCSC).  JLC class not read *(check)*.
LC = dict(ads1220=1.9936, ads124s08=7.5267, opa365=2.5707, tmux=2.1406, r249=0.1735, r100k=0.174, r680=0.0021, bat54s=0.013, c100n=0.0166, r47k=0.0028)
LC_SEG = [(680.0, 3), (680.0, 2), (680.0, 2), (680.0, 2)]     # bottom to top: 680/3, then three 680/2 pairs: nine 680R 1 % (C23228)
A1220 = dict(noise=3.89e-6, noise_pp=13.43e-6, inl_ppm_fsr=15.0, i_in=50e-9, zin=30e6)
# noise: Table 7-3, 20 SPS, normal mode, PGA disabled, gain 1 (internal 2.048 V reference); INL: +-15 ppm FSR max is the
# PGA-enabled row, the PGA-disabled row gives +-4 typ only *(check)*; input current with the PGA disabled: graphs only
# (Fig 6-21..6-24: within the +-15 nA axis at 25 C, +-50 nA at 85 C, typical) -> about 30 Mohm at 1.5 V *(check)*
def lc_draw(rg, N, tol=0.01):
    segs = []
    for r, n in LC_SEG:
        e = r*(1 + rg.uniform(-tol, tol, (N, n)))
        segs.append(1/np.sum(1/e, axis=1))
    res = np.stack(segs, axis=1)
    cum = np.cumsum(res, axis=1); tot = cum[:, -1:]
    f = cum/tot; rth = cum*(tot - cum)/tot
    return f, rth, tot[:, 0]
def lc_fit(x, y, idx):
    X = x[:, idx]; Y = y[:, idx]; n = len(idx)
    mx, my = X.mean(1, keepdims=True), Y.mean(1, keepdims=True)
    a = ((X - mx)*(Y - my)).sum(1)/((X - mx)**2).sum(1); b = my[:, 0] - a*mx[:, 0]
    return a, b
def lc_mc(rg, N=20000, lkg=0.0, inl=0.0, drop=None, fault=None, detect=False, stale=0.0):
    f, rth, _ = lc_draw(rg, N)
    f_cal = f
    if stale:                                                 # elements drift after the ADC read (100 ppm/K x 10 K), not re-read
        f = f*(1 + rg.uniform(-stale, stale, f.shape)); f[:, -1] = 1.0
    e_ads = A1220["inl_ppm_fsr"]*6.0/VREF*1e-6               # 15 ppm of FSR = 2 x 3.0 V -> 30 ppm of the 3 V span, per reading
    r = f_cal*(1 - rth/A1220["zin"]) + rg.uniform(-e_ads, e_ads, f.shape) + rg.normal(0, A1220["noise"]/VREF, f.shape)
    r[:, -1] = 1.0                                            # the top tap is REFP0 itself: full scale by construction, not read
    a_t = 4095/3.3*(1 + rg.uniform(-0.0156, 0.0029, N)); b_t = rg.uniform(-30, 56, N)
    code = a_t[:, None]*(f*VREF + rg.uniform(-lkg, lkg, f.shape)*rth) + b_t[:, None] + rg.uniform(-inl, inl, f.shape) + rg.normal(0, 0.8/math.sqrt(4096), f.shape)
    if fault is not None:
        j, dlt = fault; code[:, j] += dlt
    v = r*VREF
    idx = [i for i in range(4) if i != drop]
    a, b = lc_fit(v, code, idx)
    ends = np.array([0.2, 3.1])
    err = np.max(np.abs((a[:, None]*ends + b[:, None]) - (a_t[:, None]*ends + b_t[:, None])), axis=1)
    out = dict(p999=float(np.percentile(err, 99.9)))
    if detect:
        res4 = code - (a[:, None]*v + b[:, None]); stat = np.max(np.abs(res4), axis=1)
        rss3, errs = [], []
        for i in range(4):
            ii = [k for k in range(4) if k != i]; a3, b3 = lc_fit(v, code, ii)
            rss3.append(np.sum((code[:, ii] - (a3[:, None]*v[:, ii] + b3[:, None]))**2, axis=1))
            errs.append(np.max(np.abs((a3[:, None]*ends + b3[:, None]) - (a_t[:, None]*ends + b_t[:, None])), axis=1))
        rss3 = np.array(rss3); pick = np.argmin(rss3, axis=0); errs = np.array(errs)
        out.update(stat=stat, pick=pick, rec_err=errs[pick, np.arange(N)], err4=err)
    return out

def run_lowcost():
    rg = np.random.default_rng(20261111)
    out = {}
    T = "[lowcost]"
    # ---- A: the ADS1220's supplies as proposed (AVDD +3.3 V_A, AVSS the -2.07 V rail, DVDD 3.3 V)
    vp_, vn_ = (3.235, 3.342), (-2.103, -2.039)
    span = (vp_[0] - vn_[1], vp_[1] - vn_[0])
    uni_ok = False                                            # unipolar: AVSS to DGND -0.1 .. +0.1 V
    bip_ok = (vp_[1] <= 2.75) and (-2.75 <= vn_[0] and vn_[1] <= -2.3)   # bipolar: AVDD to DGND 2.3-2.75, AVSS -2.75 .. -2.3
    absok = span[1] <= 7.0 and vn_[0] >= -2.8
    out["supply"] = dict(span=span, bipolar_ok=bip_ok, abs_ok=absok)
    case(f"LC-A1 {T}", "ADS1220 supplies as proposed: AVDD = +3.3 V_A, AVSS = the -2.07 V rail, DVDD = 3.3 V, against SBAS501D 6.3 (recommended) and 6.1 (absolute maximum)",
         "6.3: unipolar AVSS -0.1 .. +0.1 V; bipolar AVDD 2.3-2.75 V and AVSS -2.75 .. -2.3 V (to DGND); AVDD - AVSS 2.3-5.5 V",
         f"AVDD - AVSS {span[0]:.2f}-{span[1]:.2f} V (inside 5.5 V, and 7 V abs max); but AVDD {vp_[0]:.3f}-{vp_[1]:.3f} V is above the bipolar 2.75 V and AVSS {vn_[0]:.3f} .. {vn_[1]:.3f} V is in neither band (bipolar needs -2.3 V or below); inside the absolute maxima (AVSS to DGND -2.8 V)",
         "outside 6.3", bip_ok,
         "6.1 note: outside the recommended conditions 'the device may not be fully functional'; a +-2.5 V pair would need a new +2.5 V regulator and a -2.5 V rail, which the OPA365s (5.5 V abs max across +3.3 V_A) cannot share")
    # A2 range, as if supplied (information)
    case(f"LC-A2 {T}", "AWG read at the BNC directly (PGA bypassed: AVSS - 0.1 .. AVDD + 0.1 V), if A1 were met: AW-8 excursion (sim/awg -1.720 .. +1.513 V) and the +-2.1 V requirement bound",
         f"{vn_[1]-0.1:+.3f} .. {vp_[0]+0.1:+.3f} V operating; {vn_[1]-0.3:+.3f} V abs", f"-1.720 .. +1.513 V inside; -2.1 V inside the absolute maximum, {(-2.1)-(vn_[1]-0.1):+.3f} V from the operating edge",
         "-", True, "moot while LC-A1 fails")
    # A3 noise
    nf_taps = math.log2(VREF/A1220["noise_pp"]); n_ref = R["c4_noise"]["n_ref_uV"]*1e-6
    ext = math.hypot(A1220["noise"], n_ref, 5e-6/6.6); nf_ext = math.log2(VREF/(6.6*ext))
    out["noise"] = dict(nf_taps=nf_taps, nf_ext=nf_ext)
    case(f"LC-A3 {T}", "PA-1 with the ADS1220 at 20 SPS, normal mode, PGA disabled, gain 1 (Table 7-3: 3.89 uVrms, 13.43 uVpp), over the 3.0 V span",
         ">= 16 bit", f"{nf_taps:.1f} bit on the taps (ratiometric, from the 13.43 uVpp), {nf_ext:.1f} bit on the AWG reading (with the REF3030's noise)", f"{nf_ext-16:.1f} bit", nf_ext >= 16,
         "Table 7-3 uses the internal 2.048 V reference; with 3.0 V the input-referred noise is taken unchanged (the datasheet says it changes only marginally with an external reference)")
    # A4 AVSS ripple
    rip = R["p4"]["pin_ripple_pk"]["v(awn)"]["total"]
    case(f"LC-A4 {T}", "ADS1220 AVSS on the -2.07 V rail: its ripple against the supply rejection",
         "info (6.5: AVDD PSRR at dc 80 dB min; no AVSS figure)", f"{rip*1e3:.3f} mV pk at the negative rail (P4, LM27762 2 MHz lines); 2 MHz lies 48 kHz from the modulator's 8th harmonic (fMOD 256 kHz) and is removed by the 20 SPS filter; at dc 80 dB -> {rip*1e-4*1e9:.0f} nV",
         "-", True, "moot while LC-A1 fails; AVSS PSRR is not specified and Fig 6-14 gives AVDD only *(check)*")
    # A5 PR-4 series resistor, A6 tee share (direct reading)
    rs = 680.0
    i18, i5 = (1.8 - 0.5)/rs, (5.0 - 0.5)/rs
    out["rs"] = dict(rs=rs, i_unpowered_1p8_mA=i18*1e3, i_unpowered_5_mA=i5*1e3, gain_err_pct=2*A1220["i_in"]*rs/2.3*100, offset_uV=A1220["i_in"]*rs*1e6)
    case(f"LC-A5 {T}", "PR-4 with the BNC on an ADS1220 input through a series 680R (C23228, the ladder's type): clamp current unpowered (ESD at 0.5 V), and the error the input current adds through it",
         "<= 10 mA (SBAS501D 6.1); SBAS501D 8.3.1 allows series resistors to limit the input current, as SBAS660C does",
         f"+-1.8 V: {i18*1e3:.1f} mA; +-5 V: {i5*1e3:.1f} mA; gain error <= {2*A1220['i_in']*rs/2.3*100:.4f} % and offset <= {A1220['i_in']*rs*1e6:.0f} uV from a +-50 nA input current (typical graphs only)",
         f"{10-i5*1e3:.1f} mA", i5 <= 10e-3, "8.3.1: 'external Schottky clamp diodes or series resistors can be required to limit the input current to safe values'")
    adc_inl = json.load(open(os.path.join(TEE_DIR, "inl_adc.json")))
    for lab, key in (("+-1.25 V, 256 points", "1.25|256|1.15"), ("+-5 V, 1024 points", "5|1024|1.15")):
        fit = adc_inl[f"MCP3564 84 uV|{key}"][1]; sense = out["rs"]["gain_err_pct"]      # the ADS1220 direct puts 90 uV at the AWG, ~ the 84 uV row
        out[f"tee|{lab}"] = dict(fit=fit, sense=sense, linear=fit + sense)
        case(f"LC-A6 {T} [{lab}]", f"PA-3 tee share with the ADS1220 reading the AWG directly (no divider, no ratio term, no divider drift), {lab}", f"<= {LIM_TEE:.2f} %",
             f"fit {fit:.4f} % (whatif/tee inl_adc.json, 84 uV row, at the bound) + input current through the 680R {sense:.4f} % = {fit+sense:.4f} %", f"{LIM_TEE-fit-sense:.4f} %", fit + sense <= LIM_TEE,
             "the ADS1220 direct is 90 uV at the AWG (15 ppm FSR), close to the 84 uV row; moot while LC-A1 and LC-A9 fail")
    # ---- A'': in specification: unipolar ADS1220 (AVSS = AGND), the k = 1/2 divider (2 x 100k), its far end switched between REF
    # (default) and AGND by the TMUX1119 with the AWG held at +1.0 V, so 1 - k = (t_REF - t_GND)/VREF and neither end is read
    k = 0.5
    ron = 2.6*100e3/(200e3)**2/k*100                         # Ron difference between the throws, in the unread far end
    tee12 = {lab: TEE_TAB[("ADS1220", TEE_K, lab)] for lab in TEE_RUNS}
    out["a2"] = dict(ron_pct=ron, tee=tee12)
    for lab in TEE_RUNS:
        nom, bnd = tee12[lab]
        case(f"LC-A7 {T} [{lab}]", f"A'' (in specification): ADS1220 unipolar, k = 1/2, the far end switched REF (default) / AGND by one TMUX1119, inputs the sense tap + 3 ladder taps; tee share, {lab}", f"<= {LIM_TEE:.2f} %",
             f"whatif/tee (ADS1220, k = 1/2): {nom:.3f} % ({bnd:.3f} % at the bound) + Ron difference {ron:.4f} % = {bnd+ron:.3f} % at the bound", f"{LIM_TEE-bnd-ron:.3f} %", bnd + ron <= LIM_TEE,
             "whatif/tee: on +-5 V the ADS1220 needs 2048 points (4096 at the bound) to pass; its input current is LC-A8")
    rth_t = par(100e3, 100e3)
    di = {"25 C (the +-15 nA graph axis)": 30e-9, "85 C (the +-50 nA axis)": 100e-9}
    iterm = {kk: v*rth_t/(VREF*k)*100 for kk, v in di.items()}
    out["a2"]["input_current_pct"] = iterm
    case(f"LC-A8 {T}", "A'': the ADS1220's input current (PGA disabled: typical graphs only) through the sense tap's 50 kohm, differing between the two ratio readings, on the measured ratio",
         f"part of the tee's {LIM_TEE:.2f} %", "; ".join(f"{kk}: up to {v:.3f} %" for kk, v in iterm.items()) + " (bound from the graphs' axes; the curves' values are not in the text)",
         "-", max(iterm.values()) <= LIM_TEE - tee12["+-1.25 V, 256 points"][1], "the ADS124S08's 1 nA/V typical makes this 0.005 %; the ADS1220 gives no number, so A'' is not shown to work *(check)*; A''' buffers it")
    # A direct: the series resistor against back-feed (+3.3 V_A on its 4.7k bleed < 0.5 V) and against accuracy
    rs_bf = {va: (va - 0.6 - 0.5)*4.7e3/0.5 for va in (1.8, 5.0)}
    rs_acc = 1e-4*2.3/100e-9
    out["rs_backfeed"] = dict(rs_min=rs_bf, rs_max_for_0p01pct=rs_acc, gain_err_at_min_pct=100e-9*rs_bf[5.0]/2.3*100)
    case(f"LC-A9 {T}", "A direct: the series resistor from the BNC that keeps the dead +3.3 V_A (4.7k bleed) under 0.5 V through the ADS1220's ESD, against the gain error the input current makes through it",
         "rail < 0.5 V (PR-3) and gain error <= 0.01 %", f"back-feed needs Rs >= {rs_bf[1.8]/1e3:.1f}k at +1.8 V and {rs_bf[5.0]/1e3:.1f}k at +5 V; at {rs_bf[5.0]/1e3:.1f}k the +-50 nA input current makes {100e-9*rs_bf[5.0]/2.3*100:.2f} % of gain error; 0.01 % allows <= {rs_acc/1e3:.1f}k",
         "no value meets both", False, "a BAT54S on the pin to the same rails moves the clamp current but does not stop the back-feed; only a clamp to a rail that is not back-fed, or a series diode in the ADS1220's AVDD, would")
    # ---- A''': A'' plus a unity buffer between the sense tap and the ADS1220 input
    # MCP6002 (C7377, DS20001733L): VOS 4.5 mV max, 2 uV/K typ; IB 1 pA typ; CMRR 60 dB min / 76 typ (VDD 5 V, VCM -0.3..5.3 V,
    # no 3.3 V row *(check)*); the input stages cross over at VCM = VDD - 1.1 V (Sec 4.1.1: avoid it for gain linearity);
    # 6.1 uVpp 0.1-10 Hz; PM 90 deg (60 pF), 45 deg at 500 pF; inputs VSS - 1.0 .. VDD + 1.0 V abs (Sec 4.1.2 allows series
    # current limiting).  OPA365 (SBOS365): VOS 200 uV, 1 uV/K; IB 10 pA max; CMRR 100 dB min over the whole range; no crossover.
    # Linear buffer error e(V) = Vos + c V: the ratio reads (1 - k)(1 + c), the AWG reading then has gain 1 + c/k; Vos and its
    # drift cancel in the ratio's two-state difference and land in the AWG's offset, which the tee calibrates.
    xo = (3.235 - 1.1, 3.342 - 1.1)
    out["a3"] = {}
    for nm, cm_db, ib, pp in (("MCP6002, CMRR 76 dB typical", 76.0, 1e-12, 6.1e-6), ("MCP6002, CMRR 60 dB minimum", 60.0, 1e-12, 6.1e-6),
                              ("OPA365, CMRR 100 dB minimum", 100.0, 10e-12, 5e-6)):
        c_ = 10**(-cm_db/20); gerr = c_/k*100
        ib_term = 2*ib*rth_t/(VREF*k)*100
        noise = math.hypot(A1220["noise"], pp/6.6)
        out["a3"][nm] = dict(gain_err_pct=gerr, ib_pct=ib_term, noise_uVrms=noise*1e6)
        for lab in TEE_RUNS:
            nom, bnd = tee12[lab]; big = lab.startswith("+-5")
            pts = "4096 points (whatif/tee: the ADS1220 passes the bound there, no figure given)" if big else "256 points"
            tot = (LIM_TEE if big else bnd) + ron + gerr + ib_term
            okk = (ron + gerr + ib_term <= 0.005) if big else tot <= LIM_TEE
            case(f"LC-A10 {T} [{nm}, {lab}]", f"A''' = A'' with a unity buffer ({nm.split(',')[0]}) between the sense tap and the ADS1220: tee share, {lab}, k = 1/2, {pts}", f"<= {LIM_TEE:.2f} %",
                 (f"whatif/tee ADS1220 k = 1/2: <= {LIM_TEE:.2f} % at the bound with 4096 points (1024: {bnd:.3f} %), its margin not given; added here: Ron {ron:.4f} + buffer common-mode error c/k {gerr:.4f} + bias current {ib_term:.1e} = {ron+gerr+ib_term:.4f} %" if big else
                  f"whatif/tee ADS1220 k = 1/2 at the bound {bnd:.3f} % + Ron {ron:.4f} + buffer common-mode error c/k {gerr:.4f} + bias current {ib_term:.1e} = {tot:.3f} %"),
                 ("unknown margin; passed only if the added terms are under 0.005 % *(check: rerun whatif/tee with them)*" if big else f"{LIM_TEE-tot:.3f} %"), okk,
                 "the buffer's offset and drift cancel in the ratio's two-state difference and land in the AWG's calibrated offset; the common-mode dependence does not"
                 + (f"; the MCP6002's input stages cross over at {xo[0]:.2f}-{xo[1]:.2f} V, inside the tap's span with the far end at the reference (0.95-2.08 V, AW-8 to 2.26 V), where its datasheet says to avoid it" if "MCP" in nm else ""))
    case(f"LC-A11 {T}", "A''' buffer: input range, noise, stability into the ADS1220, PR-3 through its input ESD", "VCM and output inside the rails; noise inside PA-1; stable; rail < 0.5 V",
         f"tap 0.5 V (AGND state, AWG +1.0 V) to 2.26 V (AW-8 bound, reference state): inside VSS - 0.3 .. VDD + 0.3 (MCP6002) and (V-) - 0.1 .. (V+) + 0.1 V (OPA365); output 25 mV from the rails (MCP6002, 10 kohm); noise {out['a3']['MCP6002, CMRR 76 dB typical']['noise_uVrms']:.2f} uVrms with the ADS1220 against 3.89 alone; a follower into the ADS1220's internally buffered input (a few pF, Sec 8.3.2.2) is inside the MCP6002's 60 pF test load (PM 90 deg typ); unpowered, the buffer's input ESD sees the BNC through 100k, <= {(5-0.6)/100e3*1e6:.0f} uA into +3.3 V_A at +5 V",
         "-", True, "no stability run; both parts are unity-gain stable and the load is a few pF *(check)*")
    out["a3_time"] = "whatif/tee: 2048-4096 points on +-5 V, about 5-18 min per calibration"
    lad_i = 3.0/(sum(r/n for r, n in LC_SEG)*0.99)          # E's ladder current (B is the design since 2026-11-11: C1-c, C1-d, C4-d)
    # ---- E: the 680R ladder with the ADS1220; C2 and D11
    fN, rthN, totN = lc_draw(np.random.default_rng(0), 1, tol=0.0)
    zmax = float(rthN.max())
    out["E"] = dict(taps_V=(fN[0]*VREF).tolist(), zmax=zmax, zmax_tol=zmax*1.01, i_mA=lad_i*1e3, parts=9)
    case(f"LC-E1 {T}", "PA-9 ladder of nine 680R 1 % (C23228, Basic): 680/3 at the bottom, then three 680/2 pairs; worst tap impedance", "<= 330 ohm (PA-9)",
         f"taps {', '.join(f'{x:.3f}' for x in fN[0]*VREF)} V; worst {zmax:.0f} ohm ({zmax*1.01:.0f} at +1 %); {lad_i*1e3:.2f} mA", f"{330-zmax*1.01:.0f} ohm", zmax*1.01 <= 330)
    c2a = lc_mc(rg, lkg=0.0)["p999"]; c2c = lc_mc(rg, lkg=0.5e-6)["p999"]; stale = lc_mc(rg, stale=100e-6*10)["p999"]
    drops = {j: lc_mc(rg, drop=j)["p999"] for j in range(4)}
    out["C2"] = dict(c2a=c2a, c2c=c2c, stale=stale, drops=drops)
    case(f"LC-C2a {T}", "PA-9 Due fit from 3 inner taps + the top (REFP0 itself), the ADS1220 reading the taps (INL 15 ppm FSR, 3.89 uVrms, ~30 Mohm uncorrected), 1 % parts, at 0.2 / 3.1 V", "<= 0.5 LSB",
         f"{c2a:.3f} LSB", f"{0.5-c2a:.3f} LSB", c2a <= 0.5)
    case(f"LC-C2c {T}", "C2-a plus the Due's pin leakage 0.5 uA across each tap", "<= 0.5 LSB", f"{c2c:.3f} LSB", f"{0.5-c2c:.3f} LSB", c2c <= 0.5)
    case(f"LC-C2d {T}", "the 1 % parts' tempco (100 ppm/K x 10 K) with the ADS1220's reading reused (not re-read)", "<= 0.5 LSB with the re-read rule",
         f"{stale:.3f} LSB if not re-read (re-read: C2-a)", "-", True, "the re-read rule (PA-9) becomes load-bearing" if stale > 0.5 else "")
    lab_ = {0: "0.545 V tap", 1: "1.364 V tap", 2: "2.182 V tap", 3: "top (3.0 V)"}
    case(f"LC-C2b {T}", "D11 recovery: the fit with one of the four points dropped, each in turn, the top included", "<= 0.5 LSB",
         "; ".join(f"without the {lab_[j]} {v:.3f}" for j, v in drops.items()) + " LSB", f"{0.5-max(drops.values()):.3f} LSB", max(drops.values()) <= 0.5)
    # D11 detection, with the Due's INL 1.2 LSB per point
    base = lc_mc(rg, inl=1.2, lkg=0.5e-6, detect=True)
    thr = float(np.percentile(base["stat"], 99.9))
    det = {}
    for j in range(4):
        for dlt in (3.0, 5.0, 10.0):
            o = lc_mc(rg, N=10000, inl=1.2, lkg=0.5e-6, fault=(j, dlt), detect=True)
            hit = o["stat"] > thr
            det[f"{j}|{dlt:g}"] = dict(p_detect=float(hit.mean()), p_ident=float((o["pick"][hit] == j).mean()) if hit.any() else 0.0,
                                      rec_p999=float(np.percentile(o["rec_err"][hit & (o["pick"] == j)], 99.9)) if (hit & (o["pick"] == j)).any() else float("nan"),
                                      undetected_err4_p999=float(np.percentile(o["err4"][~hit], 99.9)) if (~hit).any() else 0.0)
    out["D11"] = dict(threshold_LSB=thr, det=det, base_err4_p999=float(np.percentile(base["err4"], 99.9)))
    d5 = [det[f"{j}|5"] for j in range(4)]; d10 = [det[f"{j}|10"] for j in range(4)]
    case(f"LC-D11 {T}", "D11 detect and recover one bad tap (a fault added to the Due's reading of one point, the top included), Due INL 1.2 LSB, leakage 0.5 uA: detection at the 0.1 % false-alarm threshold, identification by leave-one-out, recovery error",
         "detect, identify, then <= 0.5 LSB", f"threshold {thr:.2f} LSB; 5 LSB fault: detected {min(x['p_detect'] for x in d5)*100:.0f}-{max(x['p_detect'] for x in d5)*100:.0f} %, identified {min(x['p_ident'] for x in d5)*100:.0f}-{max(x['p_ident'] for x in d5)*100:.0f} %; 10 LSB: detected {min(x['p_detect'] for x in d10)*100:.0f} %, identified {min(x['p_ident'] for x in d10)*100:.0f}-{max(x['p_ident'] for x in d10)*100:.0f} %, recovered {max(x['rec_p999'] for x in d10):.2f} LSB (p999, correctly identified; the 4-point fit with the same INL reads {np.percentile(base['err4'], 99.9):.2f}); an undetected 5 LSB fault leaves up to {max(x['undetected_err4_p999'] for x in d5):.1f} LSB",
         "-", min(x["p_detect"] for x in d10) >= 0.99 and max(drops.values()) <= 0.5,
         "judged as D11 is written: a fault is shown (detection >= 99 % at 10 LSB) and a fit survives its dropping (LC-C2b); which point is bad is told only 98-100 % of the time at 10 LSB, since a leave-one-out fit of 4 points has one degree of freedom against the Due's own 1.2 LSB INL")
    # ---- P3 and parts
    b0 = budget(5.0)
    rm = {k: v for k, v in b0.items() if k.startswith(("ADS124S08", "ladder"))}
    add = {"ADS1220 IAVDD (normal, PGA disabled: 240 uA typ, no max; the gain-1 PGA row's 490 uA max) + 70 uA external reference, + IDVDD 110 uA max": 0.490 + 0.070 + 0.110,
           "ladder nine 680R 1 % at -tol on the REF3030": lad_i*1e3}
    d_ma = sum(add.values()) - sum(rm.values())
    out["P3"] = dict(removed=rm, added=add, delta_mA=d_ma)
    for variant, sc in (("OPA365 scope", 5.0), ("OPA354 scope", 6.3)):
        base_ = sum(budget(sc).values()) + d_ma
        tot = base_ + max(R["p7_ext_delta_mA"], 65.0)
        case(f"LC-P3 {T} [{variant}]", "PW-1 AFE current with the remaining lowcost cuts (A'' + E; B is the design), normal / AWG shorted, and the PR-4 fault total", "<= 100 mA; fault <= 450 mA",
             f"{base_+10:.1f} / {base_+23:.1f} mA; fault {300+tot:.1f} mA (change {d_ma:+.2f} mA)", f"{100-base_-23:.1f} mA", base_ + 23 <= 100 and 300 + tot <= LIM_FAULT_MA)
    cost = {"A ADS1220 for the ADS124S08": LC["ads124s08"] - LC["ads1220"], "A one BAT54S fewer (D only; S1 is now the reference node) and its 100k": LC["bat54s"] + LC["r100k"],
"E 8 x 249R 0.1 % -> 9 x 680R 1 %": 8*LC["r249"] - 9*LC["r680"]}
    out["cost"] = dict(items=cost, total=sum(cost.values()))
    mcp = 0.3121 + LC["c100n"]                                # MCP6002 C7377 (LCSC qty 5-49) and its 100 nF
    out["cost_a3"] = {"A''' with the MCP6002 (A + B + E)": sum(cost.values()) - mcp,
                      "A''' with the OPA365 moved into the buffer role (A + E; B's saving given back)": sum(cost.values()) - LC["opa365"] - LC["c100n"],
                      "A''' alone with the MCP6002 (ADS swap, BAT54S/100k, buffer)": cost["A ADS1220 for the ADS124S08"] + cost["A one BAT54S fewer (D only; S1 is now the reference node) and its 100k"] - mcp}
    R["lowcost"] = out

# =============================================================== guards (mutation tests), hashes, main
def table_hashes():
    """model/datasheet sha256 from models/SOURCES.md, checked against the files actually read"""
    src = open("../../models/SOURCES.md").read()
    want = {}
    for line in src.splitlines():
        c = [x.strip() for x in line.split("|")]
        if len(c) > 6 and re.fullmatch(r"[0-9a-f]{64}", c[5] if len(c) > 5 else ""):
            want[(c[1], c[2])] = c[5]
    files = {"OPA365_PSPICE.lib": "opa365", "OPA354_PSPICE.lib": "opa354", "lm27762.pdf": "lm27762", "ref30.pdf": "ref3030", "tmux1119.pdf": "tmux1119",
             "dac8551.pdf": "dac8551", "MCP3561-2-4-Family-Data-Sheet-DS20006181C.pdf": "mcp3564", "opa365.pdf": "opa365", "opa354.pdf": "opa354"}
    out = {}
    for fn, d in files.items():
        p = f"../../models/{d}/{fn}"
        h = hashlib.sha256(open(p, "rb").read()).hexdigest()
        exp = [v for (dd, ff), v in want.items() if ff == fn]
        out[fn] = dict(sha256=h, matches_SOURCES_md=(bool(exp) and exp[0] == h))
    return out

def hash_guard(mutate=False):
    t = table_hashes()
    ok = all(v["matches_SOURCES_md"] for v in t.values())
    return ok, t

def quiet(fn, *a, **k):
    n = len(CASES); r = fn(*a, **k); new = CASES[n:]; del CASES[n:]; return r, new

def run_guards():
    G = []
    def rec(name, mutation, broken, restored, detail):
        G.append(dict(name=name, mutation=mutation, broken_result=broken, restored_result=restored, detected=(broken != restored), detail=detail))
    # G1 P1-a: remove the Schottkys and add 0.5 V overshoot per rail -> the 5.5 V check must fail
    lg = spice("g1_p1_broken", p1_netlist("g1", 5.25, 100e-6, 2e-3, 0.5, "both", 0.2, sch=False))
    v = meas(lg, "sum_main")
    rec("P1-a supply < 5.5 V", "series Schottkys removed and +0.5 V overshoot on each rail", "FAIL" if v >= OPA365_ABS else "PASS", "PASS" if R["p1_worst_pins_sch"] < OPA365_ABS else "FAIL", f"broken {v:.3f} V, restored {R['p1_worst_pins_sch']:.3f} V")
    # G2 P7: no isolation on the AWG op-amp pins, none in the feed -> current into the Due 5V pin
    bad = R["p7_no_iso_none_idue"]; good = max(abs(r["i_due"]) for r in R["p7"] if r["iso"] and r["feed"] == "none")
    rec("P7-b/e current into the Due <= 100 uA", "AWG pin isolation Schottkys replaced by 1 mohm", "FAIL" if bad > 100e-6 else "PASS", "PASS" if good <= 100e-6 else "FAIL", f"broken {bad*1e3:.1f} mA, restored {good*1e6:.2f} uA")
    # G3 P8-a: positive control - a stiff Vmid (10 mohm flat, as sim/scope assumed 50 mohm) must PASS where the design reads
    a = np.loadtxt("raw/vmid_z0.txt"); f = a[:, 0]
    vm, se = xt_paths(f, np.full_like(f, 0.01) + 0j)
    w = vm.max() + se.max(); d0 = R["p8_loops"][list(VM_LOOPS)[0]]["xt"]
    rec("P8-a SC-9 crosstalk through Vmid (positive control)", "Vmid node replaced by a flat 10 mohm", "PASS" if w <= 2*LSB12 else "FAIL", "PASS" if d0 <= 2*LSB12 else "FAIL",
        f"stiff {w/LSB12:.2f} LSB vs design {d0/LSB12:.2f} LSB")
    # G3a P8-a [Vmid x2]: read the aggressor's own node instead of the other buffer's (as if the buffers were one) -> FAIL
    ip = list(VM2_LOOPS).index("Vmid x2, previous loop (1R, 1k, 1.5 nF, 1 x 10 uF)")
    a = np.loadtxt(f"raw/vm2_z{ip}.txt"); f = a[:, 0]; z11 = a[:, 1] + 1j*a[:, 2]
    vm, se = xt_paths(f, z11); w = vm.max()+se.max(); w0 = R["vmid2"]["Vmid x2"]["xt"]
    rec("P8-a [Vmid x2] separate buffers", "victim reads the aggressor's Vmid node (the buffers joined), previous loop", "FAIL" if w > 2*LSB12 else "PASS", "PASS" if w0 <= 2*LSB12 else "FAIL", f"joined {w/LSB12:.2f} LSB, separate {w0/LSB12:.3f} LSB")
    # G3g C3-f [T-switch]: without the hold (middle node left floating, ~10 Mohm) the T must lose its benefit
    w = 2*np.pi*np.logspace(3, 7, 300); cft = 10**(-45/20)/(2*math.pi*10e6*25)
    zn = 1/(1/SC_RTH + 1j*w*(SC_C1 + SC_C1*SC_R1/par(SC_R2, SC_R3))); k = lambda zz: 1j*w*cft*zz/(1+1j*w*cft*zz)
    zf = 1/(1/10e6 + 1j*w*(20e-12+6e-12))                     # M floating: only the two switches' own capacitance to ground
    if "c3" in R:
      ab = (np.abs(k(zf)*k(zn))*(DAC0_HI-DAC0_LO)/2*SC_G).max(); a0 = R["c3"]["tsw"]["awg_mV"]*1e-3
      rec("C3-f [T-switch] <= 2 LSB (SC-9)", "middle node not held (floating, switch capacitances only)", "FAIL" if ab > LIM_AWG_XT else "PASS", "PASS" if a0 <= LIM_AWG_XT else "FAIL",
        f"floating {ab*1e3:.1f} mV, held {a0*1e6:.2f} uV")
    # G3h P8-f: the AWG coupling through a shared Vmid must fail if the node's impedance doubles
    fv, av = AWGP["one shared Vmid buffer"]
    fo, ao = AWGP["Vmid x2, AWG on its own buffer"]
    rec("P8-f AWG -> scope through Vmid <= 2 LSB", "AWG's Rg on the one shared buffer with its impedance x5", "FAIL" if 5*av.max() > LIM_AWG_XT else "PASS", "PASS" if ao.max() <= LIM_AWG_XT else "FAIL",
        f"broken {5*av.max()/LSB12:.2f} LSB, restored (own buffer) {ao.max()/LSB12:.4f} LSB")
    # G3i C3-e low-Z: reading the injected source instead of N must fail where reading N passes
    if LOWZ and "c3" in R:
      lo = R["c3"]["c3e_lo"]
      wsrc = max(v[0] for k, v in lo.items() if "|src|" in k); wn = max(v[0] for k, v in lo.items() if "|n_sim|" in k)
      rec("C3-e [low-Z input] gain <= 0.05 % with N read by the MCP", "MCP reads the DAC0 buffer output instead of N", "FAIL" if wsrc > 0.05 else "PASS", "PASS" if wn <= 0.05 else "FAIL",
        f"source read {wsrc:.3f} %, N read {wn:.3f} %")
    # G3j P8-i / P8-j / P8-k: the previous loop must fail the impedance target; no isolation or 12 pF HF feedback must cost
    # phase margin; doubling the stand-in's Rout must break the 3 % fit
    vl = R["vmid_loop"]; ex = vl["extra"]
    rec("P8-i per-channel Vmid peak <= 0.3 ohm", "previous loop (1R, 1k, 1.5 nF, 1 x 10 uF)", "FAIL" if ex["prev"]["zmax"] > LIM_ZVM else "PASS", "PASS" if vl["worst_z"]["zmax"] <= LIM_ZVM else "FAIL",
        f"previous {ex['prev']['zmax']:.2f} ohm, design worst {vl['worst_z']['zmax']:.3f} ohm")
    pmg = min(x for x in (ex["g_noiso"]["pm"], ex["g_cfb12p"]["pm"]) if x is not None)
    rec("P8-j per-channel Vmid phase margin >= 45 deg", "isolation 1 mohm, or HF feedback 12 pF", "FAIL" if pmg < 45 else "PASS", "PASS" if vl["worst_pm"]["pm"] >= 45 else "FAIL",
        f"no isolation {ex['g_noiso']['pm']}, 12 pF {ex['g_cfb12p']['pm']} deg; design worst {vl['worst_pm']['pm']:.0f} deg")
    si = R["vmid_standin"]; a = np.loadtxt("raw/vml_z" + str(VML_GRID.index((1.0, 1.0, 0.005))) + ".txt")
    fz = a[:, 0]; zm = np.abs(a[:, 1]+1j*a[:, 2]); b1 = (fz >= 1e3) & (fz <= 1e6)
    eg = float(np.max(np.abs(np.abs(zlin(fz[b1], si["A0"], si["GBW_Hz"], 2*si["Rout_ohm"], VM["riso"], VM["rfb"], VM["cfb"], ((VM["cd1"], VM["esr1"]), (100e-9, 0.03)), si["fp2_Hz"]))/zm[b1] - 1)))
    rec("P8-k stand-in within 3 %", "stand-in Rout doubled", "FAIL" if eg > 0.03 else "PASS", "PASS" if si["err_1k_1M"] <= 0.03 else "FAIL", f"broken {eg*100:.1f} %, fitted {si['err_1k_1M']*100:.2f} %")
    # G3b P8-c: a 2 % Vmid divider must break the 30 mV centring
    e = an4_mc(tol_div=0.02, delta=5e-3, N=50000); e0 = R["an4"]["design, ADVREF drop 5 mV"]
    rec("P8-c SC-2 centring <= 30 mV", "Vmid divider 2 % instead of 0.05 %", "FAIL" if e > 30e-3 else "PASS", "PASS" if e0 <= 30e-3 else "FAIL", f"broken {e*1e3:.1f} mV, restored {e0*1e3:.2f} mV")
    # G3c C1-c: 100 ohm elements (8.5 mA) must break the buffer-current check
    nb = len(CASES); buffer_case("G", 33.0/3+5*33.0, 0.05, 33.0, 3, None, 200e-6); okb = CASES[-1]["ok"]; del CASES[nb:]
    rec("C1-c REF3030E load current", "ladder of 33 ohm elements", "PASS" if okb else "FAIL", "PASS" if [x for x in CASES if x["id"] == "C1-c"][0]["ok"] else "FAIL", f"broken {VREF/(176*0.95)*1e3:.1f} mA")
    # G3d P7-b: R1 76.8 k and R3 768 ohm (R1 alone limits the current to 39 uA, so R3 by itself cannot break it)
    lg = spice("g_p7_r3", p7_netlist("none", ("scope", 12), True, r3=768.0, r1=76.8e3)); ib = abs(meas(lg, "id33_e"))
    i0 = max(abs(r["i_d33"]) for r in R["p7"] if r["feed"] == "none" and r["iso"] and r["stim"].startswith("scope"))
    rec("P7-b current into the Due's 3.3 V pin <= 100 uA", "R1 76.8 kohm and R3 768 ohm instead of 760 kohm each", "FAIL" if ib > 100e-6 else "PASS", "PASS" if i0 <= 100e-6 else "FAIL", f"broken {ib*1e6:.0f} uA, restored {i0*1e6:.2f} uA")
    # G3e C3-c: positive control - DAC0 holding the node at 1 ohm must PASS where the open-output bound reads
    if "c3" in R:
      x = R["c3"]["xtalk_dac0_mV"]
      rec("C3-c SC-9 crosstalk through the DAC0 node (positive control)", "DAC0 output impedance 1 ohm instead of open", "PASS" if x["1"] <= 2*LSB12*1e3 else "FAIL", "PASS" if x["open"] <= 2*LSB12*1e3 else "FAIL",
        f"1 ohm {x['1']:.3f} mV vs open {x['open']:.1f} mV (limit {2*LSB12*1e3:.2f} mV)")
    # G3f P8-a sense path: a 10 kohm sense filter must make the sense path alone exceed 2 LSB
    a = np.loadtxt("raw/vmid_z0.txt"); f = a[:, 0]; z = a[:, 1] + 1j*a[:, 2]
    _, se_b = xt_paths(f, z, rsf=10e3); se0 = R["p8_loops"][list(VM_LOOPS)[0]]["xt_sense"]
    rec("P8-a sense-node path <= 2 LSB on its own", "sense filter 10 kohm instead of 100 ohm", "FAIL" if se_b.max() > 2*LSB12 else "PASS", "PASS" if se0 <= 2*LSB12 else "FAIL",
        f"broken {se_b.max()/LSB12:.2f} LSB, restored {se0/LSB12:.2f} LSB")
    # G3t C3-t: the tee check must see the sense term: the 0.1 % ratio trusted (no ratio switch) must FAIL where the
    # measured ratio passes (+-1.25 V, k = 1/3, the design)
    ads_ = json.load(open(os.path.join(TEE_DIR, "ads.json"))); k3_ = ads_[TEE_K]
    t_ = R["tee"][f"{TEE_K}|+-1.25 V, 256 points"]; good = t_["linear"]
    bad = t_["fit"] + k3_["a_ratio_p999_pct"] + k3_["drift_10K_worst_pct"]
    rec(f"C3-t tee fit + sense <= {LIM_TEE:.1f} % (sees the sense term)", "divider ratio trusted at 0.1 % instead of measured by the ratio switch (+-1.25 V, k = 1/2; whatif/tee's fit and ads.json's trusted-ratio term)", "FAIL" if bad > LIM_TEE else "PASS", "PASS" if good <= LIM_TEE else "FAIL",
        f"broken {bad:.4f} %, restored {good:.4f} %")
    # G3u C3-u: reading the sources instead of the bottom node with a 100 ohm throw difference must break the 0.005 %
    dk = 200.0*100e3/(200e3)**2/0.5*100
    rec(f"C3-u ratio switch <= {LIM_RSW:.3f} %", "sources read instead of the bottom node, 200 ohm Ron difference between the throws", "FAIL" if dk > LIM_RSW else "PASS", "PASS",
        f"broken {dk:.4f} %, restored 0 (bottom node read)")
    # G3p C1-p: the AWG node wired straight to the input (k = 1) must break the powered AW-8 row
    lo_k1 = -2.1; kb = "AW-8 requirement bound +-2.1 V, powered"
    rec("C1-p sense input inside abs max (AW-8 bound, powered)", "no divider (k = 1): the AWG node on the ADC pin", "FAIL" if lo_k1 < -0.3 else "PASS", "PASS" if R["inprot"][kb]["ok_tap"] else "FAIL",
        f"broken {lo_k1:+.3f} V against -0.3 V; restored {min(v[0] for v in R['inprot'][kb]['tap_V'].values()):+.3f} V")
    # G3q C1-q: the ratio switch's pins without the BAT54S clamps must break the -0.5 .. VDD + 0.5 V check
    cn = [x for k_, x in R["clamp"].items() if k_.startswith("1.8|") and k_.endswith("|none")]
    cm = [x for k_, x in R["clamp"].items() if k_.startswith("1.8|") and k_.endswith("|DBAT54S_MAX")]
    wb, wg = max(x["worst_beyond_rail"] for x in cn), max(x["worst_beyond_rail"] for x in cm)
    rec("C1-q ratio-switch pins inside -0.5 .. VDD + 0.5 V (unpowered +-1.8 V)", "BAT54S clamps removed (the pins' own ESD only)", "FAIL" if wb > 0.5 else "PASS", "PASS" if wg <= 0.5 else "FAIL",
        f"broken {wb:.3f} V beyond a rail, restored {wg:.3f} V")
    # G4 C1-a: ladder 20x higher impedance (x10 and x15 stop breaking it with 249 ohm elements: 4.9 kohm passes)
    zi = ladder_thevenin(np.array(SEG, float)*20)[1].max()
    rec("C1-a SC-10 tap impedance <= 5 kohm", "ladder resistors x20", "FAIL" if zi > 5000 else "PASS", "PASS" if ZI_NOM.max() <= 5000 else "FAIL", f"broken {zi:.0f} ohm, restored {ZI_NOM.max():.0f} ohm")
    # G5 C2-a: the 5 % arrays used with nominal ratios (no MCP readback)
    r = fit_mc(NTAP, False, N=6000, inl=0.0, lkg=0.0)
    cal = R["c2"][K_CAL]["p999"]
    rec("C2-a ladder fit <= 0.5 LSB", f"the {RLAD_TOL*100:g} % {RLAD_ELEM:.0f} ohm ladder used with nominal ratios (no MCP readback)", "FAIL" if r["p999"] > 0.5 else "PASS", "PASS" if cal <= 0.5 else "FAIL", f"broken {r['p999']:.2f} LSB, restored {cal:.2f} LSB (MCP-read 5 % arrays)")
    # G5c C2-c: the previous 1 kohm arrays must fail the leakage check the 330 ohm arrays pass
    r = fit_mc(NTAP, True, N=15000, inl=0.0, seg=SEG_1K, npar=3)
    lk = R["c2"][K_LKG]["p999"]
    rec("C2-c pin leakage x tap impedance <= 0.5 LSB", "ladder back to 4 x 1 kohm arrays (C20197, worst tap 1312 ohm)", "FAIL" if r["p999"] > 0.5 else "PASS", "PASS" if lk <= 0.5 else "FAIL", f"broken {r['p999']:.3f} LSB, restored {lk:.3f} LSB ({RLAD_ELEM:.0f} ohm arrays, worst tap {ZI_NOM.max():.0f} ohm)")
    # G5d C2-d: reuse the earlier MCP reading instead of re-reading (the stale arm, run fresh)
    r = fit_mc(NTAP, True, N=15000, inl=0.0, lkg=0.0, drift=200e-6*10)
    rr = R["c2"][REREAD]["p999"]
    rec("C2-d taps re-read at every calibration", "earlier MCP reading reused after a +-0.2 % drift (200 ppm/K parts, no re-read)", "FAIL" if r["p999"] > 0.5 else "PASS", "PASS" if rr <= 0.5 else "FAIL", f"broken {r['p999']:.3f} LSB, restored {rr:.3f} LSB")
    # G5b C2-a: the check must see the MCP's loading of the taps.  With the 1 kohm ladder, leaving the Zin loading
    # uncorrected broke it; with 330 ohm elements that arm reads ~0.45 LSB and passes, so it no longer breaks the check.
    # The mutation is now the AMCLK prescaler at 1 (Zin 260 kohm, 8x the loading), corrected as usual.
    r = fit_mc(NTAP, True, N=6000, inl=0.0, lkg=0.0, zin=100e3)
    rec("C2-a ladder fit <= 0.5 LSB (sees the tap loading)", f"ADC input resistance 100 kohm uncorrected (10^4 x the ADS124S08's typical input current) on the {ZI_NOM.max():.0f} ohm taps", "FAIL" if r["p999"] > 0.5 else "PASS", "PASS" if cal <= 0.5 else "FAIL",
        f"broken {r['p999']:.2f} LSB, restored {cal:.2f} LSB")
    # G6 P4: strip the rail filtering (bulk, branch C, local C) -> pin ripple must rise strongly
    global LDO_A1
    keep_a1 = LDO_A1; LDO_A1 = 2*keep_a1                # without the bead the stripped pins read ~11 mV < 20: the filter is not what passes PW-2
    o, _ = quiet(run_p4, c_bulk=1e-9, br_c="1n", local="1n", tag="_stripped"); LDO_A1 = keep_a1
    pk0 = max(v["total"] for v in R["p4"]["pin_ripple_pk"].values()); pk1 = max(v["total"] for v in o["pin_ripple_pk"].values())
    aw0 = R["p4"]["residue_rms"]["awg"]["total"]; aw1 = o["residue_rms"]["awg"]["total"]
    rec("P4-b AWG supply residue <= 20 uV", "filters stripped and the LDO ripple doubled (as for P4-c)", "FAIL" if aw1 > LIM_P4B else "PASS", "PASS" if aw0 <= LIM_P4B else "FAIL", f"broken {aw1*1e6:.1f} uV, restored {aw0*1e6:.2f} uV")
    rec("P4-c ripple at the amplifier pins (check responds to the filter)", "bulk 5 uF -> 1 nF, branch 10 uF -> 1 nF, local 100 nF -> 1 nF, and the LDO ripple doubled to 10 mV pk", "FAIL" if pk1 > 20e-3 else "PASS", "PASS" if pk0 <= 20e-3 else "FAIL", f"stripped {pk1*1e3:.2f} mV vs {pk0*1e3:.3f} mV (x{pk1/pk0:.0f})")
    R["p4_stripped"] = dict(pin_pk=pk1, residue={k: v["total"] for k, v in o["residue_rms"].items()})
    # G7 P3-c: double the simulated PR-4 increment (as if the 50 ohm were 25 ohm) -> the 450 mA check must fail
    base = sum(budget(5.0).values()); inc = max(R['p7_ext_delta_mA'], 65.0)
    zb = 300 + base + 2*inc; zr = 300 + base + inc
    rec(f"P3-c Due+AFE <= {LIM_FAULT_MA:.0f} mA with +-5 V on the AWG", "PR-4 increment doubled (the 50 ohm halved to 25 ohm)", "PASS" if zb <= LIM_FAULT_MA else "FAIL", "PASS" if zr <= LIM_FAULT_MA else "FAIL", f"broken {zb:.1f} mA, restored {zr:.1f} mA (OPA365 scope)")
    # G8 hashes: a model edited by one byte must be caught
    ok, t = hash_guard()
    real = open("../../models/opa365/OPA365_PSPICE.lib", "rb").read()
    mut = hashlib.sha256(real + b" ").hexdigest()
    rec("MC-6 model hash vs SOURCES.md", "one byte appended to the OPA365 model", "FAIL" if mut != t["OPA365_PSPICE.lib"]["sha256"] else "PASS", "PASS" if ok else "FAIL", "SOURCES.md sha matches the unmodified file")
    R["guards"] = G
    return G

def main():
    ok, th = hash_guard(); R["hashes"] = th
    assert ok, "model/datasheet hash mismatch with models/SOURCES.md"
    ver = (re.search(r"ngspice-\d+(\.\d+)*", sh("ngspice -v").stdout) or re.search(".", "?")).group(0)
    R["tools"] = dict(ngspice=ver, numpy=np.__version__, python=sys.version.split()[0])
    run_p1(); run_p2(); run_p3(); run_p6()
    o = run_p4(); R["p4"] = o; p4_cases(o); p5_cases(o)
    # comparison: the previous feed with the ferrite bead (5 V feed and each scope branch); R2 removed it (approved 2026-11-11)
    o2 = run_p4(nobead=False, tag="_bead"); p4_cases(o2, " [with bead, previous]"); p5_cases(o2, " [with bead, previous]")
    o3 = run_p4(ripple_cal=True, tag="_cal"); p4_cases(o3, " [ripple behind the LDO's 0.8 uH, 5 mV on 2.2 uF]")
    # the earlier 10 uF assumptions, for comparison: 10 / 20 mohm ESR, no ESL, nominal capacitance; and one 10 uF per rail
    cmp_ = {}
    for lab, kwx in (("ESR 10 mohm, no ESL, nominal C (previous assumption)", dict(esr10=0.010, esl10=0.0, k33=1.0, kneg=1.0)),
                     ("ESR 20 mohm, no ESL, nominal C", dict(esr10=0.020, esl10=0.0, k33=1.0, kneg=1.0)),
                     ("Samsung data, one 10 uF per rail (previous count)", dict(nrail=1))):
        oo = run_p4(tag="_cmp" + str(len(cmp_)), **kwx); cmp_[lab] = dict(awg=oo["residue_rms"]["awg"]["total"], scope=max(v["total"] for k, v in oo["residue_rms"].items() if k != "awg"))
        case(f"P4-b [{lab}]", "AW-6 supply residue at the AWG output, as P4-b", f"<= {LIM_P4B*1e6:.0f} uV rms", f"{cmp_[lab]['awg']*1e6:.2f} uV rms", f"{(LIM_P4B-cmp_[lab]['awg'])*1e6:.1f} uV", cmp_[lab]["awg"] <= LIM_P4B)
    R["p4_cmp"] = cmp_
    R["c15850"] = dict(esr_mohm={f"{x/1e6:g} MHz": SAM["esr"](x)*1e3 for x in (1e4, 2e4, 1e5, 1e6, 2e6, 4e6, 6e6, 8e6, 10e6)},
                       z_mohm={f"{x/1e6:g} MHz": SAM["z"](x)*1e3 for x in (1e6, 2e6, 4e6, 10e6)}, esl_nH=ESL10*1e9, srf_MHz=SAM["srf"]/1e6,
                       dc_bias_pct={f"{v} V": (SAM["k"](v)-1)*100 for v in (1.65, 2.07, 3.3, 5.0)}, tol=C10_TOL,
                       k={"5 V": K10_5V, "3.3 V": K10_33, "2.07 V": K10_N, "1.65 V": K10_165})
    R["p4_cal"] = {k: v for k, v in o3.items() if k not in ("z5_curve", "z5_curve_f")}
    R["p4_bead"] = {k: v for k, v in o2.items() if k not in ("z5_curve", "z5_curve_f")}
    run_p7(); ext, base0 = p7_cases(); p3_ext_case(R["p7_ext_delta_mA"])
    run_p8(); run_vmid2(); run_vmid_loop(); run_an4()
    run_c1(); run_c2(); run_ladder_variants(); run_tee(); run_c4()
    run_guards()
    run_lowcost()               # the $35 what-if (2026-11-11): its own random generator, after everything else, so the design rows are unchanged
    # strip big arrays from the dump
    dump = json.loads(json.dumps(R, default=lambda x: x if not isinstance(x, np.generic) else x.item()))
    for k in ("z5_curve", "z5_curve_f"): dump["p4"].pop(k, None)
    dump["p8_z"] = {"f": dump["p8_z"]["f"][::8], "z": dump["p8_z"]["z"][::8]}
    dump["cases"] = CASES
    json.dump(dump, open("results.json", "w"), indent=1)
    import importlib.util
    sp = importlib.util.spec_from_file_location('report', os.path.join(HERE, 'report.py')); rep = importlib.util.module_from_spec(sp); sp.loader.exec_module(rep); rep.write(dump)
    nfail = sum(1 for c in CASES if not c["ok"])
    print(f"{len(CASES)} cases, {nfail} FAIL")

if __name__ == "__main__":
    main()
