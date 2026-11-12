#!/usr/bin/env python3
"""The MCP3564 reading the AWG node at the tee (CH1 through its sense divider), and the one-switch-per-channel
fallback's AWG coupling (C3-f).  Analytic + numpy; the formulas are powercal's (sim/powercal/run.py run_c3) where
they exist.  python3 -I sense.py -> results/sense.json.  Every check is broken on purpose at the end.

Sense divider (whatif/bom.md placeholder F-11): Ra from the AWG BNC node to the tap, Rb from the tap to the AWG's own
Vmid, Ra = Rb = 100k 0.1 % 10 ppm/K (C394537), k = Rb / (Ra + Rb) = 1/2, so tap = k Vawg + (1 - k) Vmid.
MCP3564 facts (DS20006181C p4-6, read 2026-11-11): analog inputs -0.3 V to AVDD + 0.3 V absolute, current at input
pins +-5 mA absolute, operating AGND - 0.1 to AVDD + 0.1 V; differential input impedance 260 kohm at gain 1 and
AMCLK 4.9152 MHz, proportional to 1/AMCLK, a typical with no limits (so 2.08 Mohm at prescaler 8); leakage +-10 nA
in shutdown only.
"""
import os, sys, json, math
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = {}
RA = RB = 100e3
K = RB / (RA + RB)
RTH = RA * RB / (RA + RB)
V33 = (3.25, 3.35)          # +3.3 V_A (LM27762 VFB +-1.5 %, powercal P6) -> AVDD and the AWG's Vmid divider *(check)*
VMID = (V33[0] / 2 * 0.999, V33[1] / 2 * 1.001)
AVDD_MIN = V33[0]

# ---- 1. input range: what reaches CH1 for each AWG-node condition ------------------------------------------------
IS, N_, RS = 1e-15, 1.0, 5.0     # generic ESD diode (sim/scope netlib DESD: 0.60 V at 10 uA) *(assumption: no I-V given)*
VT = 0.02585

def clamp(voc, rth, rail):
    """Thevenin voc/rth into a diode to `rail` (forward when voc beyond it): returns (pin voltage, diode current)."""
    sgn = 1.0 if voc > rail else -1.0
    lo, hi = 0.0, abs(voc - rail)
    for _ in range(200):                      # bisection on the diode's forward voltage
        vd = (lo + hi) / 2
        i = IS * (math.exp(vd / (N_ * VT)) - 1)
        if (abs(voc - rail) - vd) / rth - i > 0:
            lo = vd
        else:
            hi = vd
    i = (abs(voc - rail) - lo) / rth
    return rail + sgn * lo * (1 if i < 1e-12 else 1), sgn * i

def tap(vawg, vmid, k=K):
    return k * vawg + (1 - k) * vmid

conds = {"AWG +-1.15 V (tee, normal)": (-1.15, 1.15), "AWG +-2.1 V (AW-8 reset/boot bound)": (-2.1, 2.1),
         "PR-4 +-1.8 V forced, powered": (-1.8, 1.8), "PR-4 +-5 V forced (shield damage allowed)": (-5.0, 5.0)}
rng_rows = {}
for lab, (lo, hi) in conds.items():
    vmin = tap(lo, VMID[0]); vmax = tap(hi, VMID[1])
    row = dict(vmin=vmin, vmax=vmax, in_abs=bool(vmin >= -0.3 and vmax <= AVDD_MIN + 0.3),
               in_oper=bool(vmin >= -0.1 and vmax <= AVDD_MIN + 0.1))
    # clamp current if outside: the pin is the tap (direct) and the ESD diodes conduct to AGND / AVDD
    i_lo = 0.0 if vmin > 0 else clamp(vmin, RTH, 0.0)[1]
    i_hi = 0.0 if vmax < AVDD_MIN else clamp(vmax, RTH, AVDD_MIN)[1]
    row.update(i_clamp_lo_uA=i_lo * 1e6, i_clamp_hi_uA=i_hi * 1e6, i_ok=bool(max(abs(i_lo), abs(i_hi)) < 5e-3))
    rng_rows[lab] = row
# unpowered (AVDD = 0, Vmid = 0): +5 V forced on the AWG node
voc = tap(5.0, 0.0)
v_, i_ = clamp(voc, RTH, 0.0)
rng_rows["PR-4 +5 V forced, unpowered (AVDD 0, Vmid 0)"] = dict(vmin=None, vmax=voc, in_abs=False, in_oper=False,
                                                                i_clamp_hi_uA=i_ * 1e6, i_ok=bool(abs(i_) < 5e-3))
OUT["range"] = rng_rows

# ---- 2. its ratio: an uncalibrated term of the absolute gain, and an offset term --------------------------------
rng = np.random.default_rng(5)
tol, tc, dT = 1e-3, 10e-6, 10.0
ea, eb = rng.uniform(-tol, tol, 200000), rng.uniform(-tol, tol, 200000)
dk = (1 - K) * (eb - ea)                       # d k / k
ta, tb = rng.uniform(-tc, tc, 200000), rng.uniform(-tc, tc, 200000)
dkT = (1 - K) * (tb - ta) * dT
OUT["ratio"] = dict(worst_pct=(1 - K) * 2 * tol * 100, p999_pct=float(np.percentile(np.abs(dk), 99.9) * 100),
                    drift_worst_pct=(1 - K) * 2 * tc * dT * 100, drift_p999_pct=float(np.percentile(np.abs(dkT), 99.9) * 100),
                    # the tap is referred to Vmid, so a ratio error is also an offset: Vawg_est = (1 + d) Vawg - d Vmid
                    offset_worst_mV=(1 - K) * 2 * tol * VMID[1] * 1e3,
                    offset_p999_mV=float(np.percentile(np.abs(dk), 99.9) * VMID[1] * 1e3))

# ---- 3. the MCP's own input impedance against the divider's Thevenin -------------------------------------------
load = {}
for zin, lab in ((2.08e6, "prescaler 8 (2.08 Mohm, powercal C2)"), (260e3, "prescaler 1 (260 kohm, powercal C4-c's AMCLK 4.9152 MHz)")):
    e = RTH / (RTH + zin)
    load[lab] = dict(err_pct=e * 100, unc30_pct=abs(RTH / (RTH + zin * 0.7) - e) * 100)
# with an OPA365 follower on the tap (a type in the design): output impedance and gain terms
load["OPA365 follower on the tap"] = dict(err_pct=(1e-5 + 1e-5) * 100, unc30_pct=0.0,
                                         note="AOL >= 100 dB and CMRR >= 100 dB (datasheet-facts.md p6) -> <= 2e-5; offset 200 uV max -> 0.4 mV at the AWG node, an uncalibrated offset")
OUT["mcp_load"] = load
# loading of the tee node (the AWG's 50 ohm source after its op-amp): 1 Mohm || 1 Mohm || (Ra + Rb to Vmid)
rin = 990.1e3
zt = 1 / (2 / rin + 1 / (RA + RB))
OUT["tee_load"] = dict(z_kohm=zt / 1e3, droop_pct=49.9 / (zt + 49.9) * 100, vmid_inject_mV=VMID[1] * 49.9 / (RA + RB) * 1e3,
                       note="all inside the node the MCP reads (the AWG BNC), so calibrated; the scope inputs see the same node at DC")

# ---- 4. the one-switch fallback: C3-f with ONE off TMUX1119 (or 3157-class) between the DAC0 buffer and N -------
SC_R1, SC_R2, SC_R3, SC_C1 = 760e3, 330e3, 760e3, 12e-12
par = lambda *r: 1 / sum(1 / x for x in r)
alpha = par(SC_R2, SC_R3) / (SC_R1 + par(SC_R2, SC_R3)); rth = par(SC_R1, SC_R2, SC_R3)
c2tot = SC_C1 * SC_R1 / par(SC_R2, SC_R3)
G = 1 + 953 / 249; LSB = 3.3 / 4096; LIM = 2 * LSB
f = np.logspace(3, 7, 300); w = 2 * np.pi * f
zn = 1 / (1 / rth + 1j * w * (SC_C1 + c2tot))
kf = lambda cft, zz: 1j * w * cft * zz / (1 + 1j * w * cft * zz)
vd = (2.77 - 0.58) / 2
cft_tmux = 10 ** (-45 / 20) / (2 * math.pi * 10e6 * 25)      # powercal's 3.58 pF from the datasheet off-isolation
c3f = {}
for lab, cft in (("TMUX1119, 3.58 pF (powercal)", cft_tmux), ("3157-class, 1 pF *(check: no datasheet read)*", 1e-12),
                 ("0.1 pF", 0.1e-12), ("0.01 pF", 0.01e-12)):
    a = np.abs(kf(cft, zn)) * vd
    c3f[lab] = dict(v125_mV=float((a * G).max() * 1e3), v125_lsb=float((a * G).max() / LSB), v5_mV=float(a.max() * 1e3),
                    v5_lsb=float(a.max() / LSB), pass_125=bool((a * G).max() <= LIM), pass_5=bool(a.max() <= LIM))
# the largest feed-through capacitance one off switch may have (+-1.25 V victim, 1 kHz-10 MHz)
lo, hi = 1e-16, 1e-11
for _ in range(80):
    m = math.sqrt(lo * hi)
    if (np.abs(kf(m, zn)) * vd * G).max() > LIM:
        hi = m
    else:
        lo = m
OUT["c3f_single"] = dict(rows=c3f, cft_max_pF=lo * 1e12)

# ---- guards: each check broken on purpose -------------------------------------------------------------------
G_ = []
def guard(name, mutation, good, broken, fired):
    G_.append(dict(check=name, mutation=mutation, good=good, broken=broken, fired=bool(fired)))
# input range: the reset row passes with k = 1/2 and must fail with the AWG node wired straight to CH1 (k = 1)
good = rng_rows["AWG +-2.1 V (AW-8 reset/boot bound)"]["in_abs"]
broken = tap(-2.1, VMID[0], k=1.0) >= -0.3
guard("CH1 inside -0.3 V..AVDD+0.3 V at the AW-8 bound", "sense divider removed (k = 1)", good, broken, good and not broken)
# clamp current: must exceed 5 mA when the Thevenin is 10 ohm instead of 50 kohm at -5 V forced
i_bad = abs(clamp(tap(-5.0, VMID[0]), 10.0, 0.0)[1]); i_good = abs(rng_rows["PR-4 +-5 V forced (shield damage allowed)"]["i_clamp_lo_uA"]) * 1e-6
guard("clamp current < 5 mA at -5 V forced", "divider Thevenin 50 kohm -> 10 ohm", i_good, i_bad, i_good < 5e-3 <= i_bad)
# loading: the 0.05 % budget check passes with the follower and fails unbuffered
lg, lb = load["OPA365 follower on the tap"]["err_pct"], load["prescaler 8 (2.08 Mohm, powercal C2)"]["unc30_pct"]
guard("MCP loading residual <= 0.05 %", "follower removed (MCP CH1 straight on the 50 kohm tap)", lg, lb, lg <= 0.05 < lb)
# C3-f: the 2 LSB check must pass at 0.01 pF and fail at the TMUX1119's 3.58 pF
guard("C3-f one off switch <= 2 LSB", "feed-through 0.01 pF -> 3.58 pF", c3f["0.01 pF"]["v125_lsb"], c3f["TMUX1119, 3.58 pF (powercal)"]["v125_lsb"],
      c3f["0.01 pF"]["pass_125"] and not c3f["TMUX1119, 3.58 pF (powercal)"]["pass_125"])
# C3-f must reproduce powercal's single-switch 343 mV with its own 768k-era numbers within 5 %? (here 760k: report it)
OUT["guards"] = G_
json.dump(OUT, open(os.path.join(HERE, "results", "sense.json"), "w"), indent=1)
print(json.dumps(OUT, indent=1))
if not all(g["fired"] for g in G_):
    raise SystemExit("a guard did not fire")
