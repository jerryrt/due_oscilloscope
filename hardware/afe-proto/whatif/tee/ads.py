#!/usr/bin/env python3
"""The AWG-sense path into the precision ADC, for the ADS124S08 alternative (and the MCP3564), as the absolute-gain
term of every tee calibration.  numpy only.  python3 -I ads.py -> results/ads.json.

ADS124S08 facts read from models/ads124s08/ads124s08.pdf (2026-11-11), PGA bypassed: inputs AVSS - 0.05 to
AVDD + 0.05 V operating, AVSS - 0.3 to AVDD + 0.3 V absolute, 10 mA continuous per input absolute; absolute input
current 0.5 nA typ (no maximum given), differential input current 1 nA/V typ (no maximum); INL 1 ppm FSR typ,
10 ppm FSR max (FSR = 2 VREF = 6 V at REFP0 = REF3030, so 6 / 60 uV); gain error 120 ppm max, drift 1 ppm/K max;
offset after calibration ~ noise, global chop 2 uV max.  Typical-only figures are marked (check) where used.

(a) a fixed 0.1 % divider to Vmid, ratio trusted.
(b) the same divider, ratio MEASURED at every calibration: a TMUX1119 moves the divider's bottom from Vmid to the
    buffered 3.0 V ladder top (CH7's node) while the AWG is held at one level, so
        tap1 = k Va + (1 - k) Vmid,  tap2 = k Va + (1 - k) Vtop  ->  1 - k = (tap2 - tap1) / (Vtop - Vmid)
    with all four voltages read by the ADC.  The switch sits on the 0..3 V side (both throws inside its supply), and its
    Ron is in Rb in both states, so it is inside the measured k.  (b') the variant with the switch at the divider's top
    (AWG node <-> a ladder tap) is rejected: the AWG node swings to -1.15 V (-2.1 V in AW-8), below a single-supply
    TMUX1119's ground.
"""
import os, json, math
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
rng = np.random.default_rng(11)
N = 200000
OUT = {}
VMID, VTOP = 1.65, 3.0
INL = {"max (10 ppm FSR, 60 uV)": 60e-6, "typ (1 ppm FSR, 6 uV) (check)": 6e-6}
TC, DT = 10e-6, 10.0            # 100k 0.1 % 10 ppm/K (C394537)

def p999(x):
    return float(np.percentile(np.abs(x), 99.9))

for k_lab, (ra, rb) in {"k = 1/2 (2 x 100k)": (100e3, 100e3), "k = 1/3 (100k + 100k over 100k)": (200e3, 100e3)}.items():
    k = rb / (ra + rb); rth = ra * rb / (ra + rb)
    row = {}
    # (a) trusted ratio: tolerance (0.1 % each part; the 200k is two 100k parts in series, independent) and drift
    if ra == rb:
        ea = rng.uniform(-1e-3, 1e-3, N)
    else:
        ea = (rng.uniform(-1e-3, 1e-3, N) + rng.uniform(-1e-3, 1e-3, N)) / 2
    eb = rng.uniform(-1e-3, 1e-3, N)
    dk = (1 - k) * (eb - ea)
    row["a_ratio_p999_pct"] = p999(dk) * 100
    row["a_ratio_worst_pct"] = (1 - k) * 2e-3 * 100
    row["drift_10K_worst_pct"] = (1 - k) * 2 * TC * DT * 100
    # exact offset term: Vawg_est = (tap - (1-k0) Vmid) / k0 with k0 nominal -> error at Vawg = 0 is (k - k0)/k0 * ... :
    # tap = k Va + (1 - k) Vm; est = (tap - (1 - k0) Vm) / k0 = (k/k0) Va + (k0 - k) Vm / k0 -> offset -dk Vm
    row["a_offset_p999_mV"] = p999(dk) * VMID * 1e3
    # input current of the ADS124S08 against the divider Thevenin (typ only, no max) *(check)*
    row["ads_diff_current_gain_pct"] = 1e-9 * rth * 100          # 1 nA/V x Rth
    row["ads_abs_current_offset_uV"] = 0.5e-9 * rth * 1e6
    row["mcp3564_zin_gain_pct"] = rth / (rth + 2.08e6) * 100     # for comparison: the MCP's 2.08 Mohm (sense.py)
    # reset excursion and clamp margin (Vmid at its low end, 1.624 V; AVDD 3.25 V)
    tmin, tmax = k * -2.1 + (1 - k) * 1.624, k * 2.1 + (1 - k) * 1.676
    row["aw8_tap_V"] = (tmin, tmax); row["aw8_in_abs"] = bool(tmin >= -0.3 and tmax <= 3.25 + 0.3)
    row["aw8_in_oper"] = bool(tmin >= -0.05 and tmax <= 3.25 + 0.05)
    row["tee_load_kohm"] = (ra + rb) / 1e3
    # (b) measured ratio: INL error on each of the four readings, uniform +-e, plus noise 1 uV
    for il, e in INL.items():
        r = lambda: rng.uniform(-e, e, N) + rng.normal(0, 1e-6, N)
        va = rng.uniform(-1.15, 1.15, N)
        t1 = k * va + (1 - k) * VMID + r(); t2 = k * va + (1 - k) * VTOP + r()
        vm = VMID + r(); vt = VTOP + r()
        k_est = 1 - (t2 - t1) / (vt - vm)
        row[f"b_ratio_p999_pct|{il}"] = p999(k_est / k - 1) * 100
        row[f"b_ratio_worst_pct|{il}"] = (2 * e + 2 * e * (1 - k)) / ((VTOP - VMID) * k) * 100   # |d(1-k)| <= (2e + 2e(1-k)) / dV
    OUT[k_lab] = row

# ---- the share: fit (inl.json, 99.9 %) + sense-path term, per range, against 0.05 % --------------------------------
inl = json.load(open(os.path.join(HERE, "results", "inl.json")))["abs"]
share = {}
k2 = OUT["k = 1/2 (2 x 100k)"]
for rg in ("5", "1.25"):
    for vt in ("1.0", "1.15"):
        for n in (64, 256, 1024):
            for im in ("pt1.2", "pt0.5"):
                fit = inl[f"{rg}|{vt}|{im}|{n}"]
                for lab, s in (("(a) trusted 0.1 %", k2["a_ratio_p999_pct"] + k2["drift_10K_worst_pct"]),
                               ("(b) measured, ADS INL max", k2["b_ratio_p999_pct|max (10 ppm FSR, 60 uV)"] + k2["drift_10K_worst_pct"]),
                               ("(b) measured, ADS INL typ", k2["b_ratio_p999_pct|typ (1 ppm FSR, 6 uV) (check)"] + k2["drift_10K_worst_pct"])):
                    share[f"{rg}|{vt}|{n}|{im}|{lab}"] = dict(fit=fit, sense=s, linear=fit + s, rss=math.hypot(fit, s),
                                                               pass_linear=bool(fit + s <= 0.05), pass_rss=bool(math.hypot(fit, s) <= 0.05))
OUT["share"] = share

# ---- guards -------------------------------------------------------------------------------------------------------
G = []
row = OUT["k = 1/2 (2 x 100k)"]
# (1) the self-calibration must see a ratio error: put a 0.5 % error into Rb and the estimate must follow it
kt = 0.5 * 1.005 / (0.5 * 1.005 + 0.5)
va = 0.7; t1 = kt * va + (1 - kt) * VMID; t2 = kt * va + (1 - kt) * VTOP
k_est = 1 - (t2 - t1) / (VTOP - VMID)
G.append(dict(check="(b) estimate tracks the true ratio", mutation="Rb +0.5 %", good=k_est, broken=0.5, fired=bool(abs(k_est - kt) < 1e-9 and abs(kt - 0.5) > 1e-3)))
# (2) the share check must fail when the trusted ratio is used and pass when it is measured (+-1.25 V, 256 points)
a = share["1.25|1.15|256|pt1.2|(a) trusted 0.1 %"]; b = share["1.25|1.15|256|pt1.2|(b) measured, ADS INL max"]
G.append(dict(check="+-1.25 V fit + sense <= 0.05 %", mutation="measured ratio -> trusted 0.1 % ratio", good=b["linear"], broken=a["linear"], fired=bool(b["linear"] <= 0.05 < a["linear"])))
# (3) the excursion check must fail for the AWG node wired straight to an input
G.append(dict(check="AW-8 inside the ADC's absolute range", mutation="k = 1 (no divider)", good=row["aw8_in_abs"], broken=(-2.1 >= -0.3), fired=bool(row["aw8_in_abs"] and not (-2.1 >= -0.3))))
OUT["guards"] = G
json.dump(OUT, open(os.path.join(HERE, "results", "ads.json"), "w"), indent=1)
for kk, v in OUT.items():
    if kk not in ("share",):
        print(kk, json.dumps(v, indent=0)[:1500])
for kk, v in share.items():
    if "pt1.2" in kk or "|1024|" in kk:
        print(kk, round(v["fit"], 4), round(v["sense"], 4), round(v["linear"], 4), round(v["rss"], 4), v["pass_linear"], v["pass_rss"])
if not all(g["fired"] for g in G):
    raise SystemExit("a guard did not fire")
