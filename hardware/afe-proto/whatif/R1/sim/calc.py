#!/usr/bin/env python3
"""WHATIF R1: the arithmetic on top of results/r1.json (gain-4 margins with the ADC's own errors, noise in gain-4
codes, SM-5 normalised growth, differential ranges, the loop shelf slope).  python3 -I calc.py > results/calc.txt"""
import json, os
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
R = json.load(open(os.path.join(HERE, "results", "r1.json")))
A = 0.232389          # alpha, 760k / 330k / 760k (sim g_dc 0.2324)
GE_MAX = 0.29e-2; OE_LO, OE_HI = -30, 56          # Table 46-31 (11057B), single ended, GAIN=xx, VDDIN 3.0-3.6 V
c4 = lambda aref: aref / 4 / 4096                   # one gain-4 code at the pin (46.7.0.1)
c1 = lambda aref: aref / 4096
snr_codes = lambda db: 4096 / (2 * 2 ** 0.5) / 10 ** (db / 20)   # full-scale sine rms / 10^(SNR/20)
P = print

P("== Q1 gain-4 window (Figure 44-6: 3/8..5/8 AREF at OFF=1), pin-referred, one-at-a-time worst case (sim) ==")
for a in ("3.20", "3.25", "3.30"):
    d = R["dc"][f"dc|{a}|330"]; aref = float(a); w = d["worst"]
    sw = 1.25 * d["gain_max"]
    hi = w["w_hi"] - sw * GE_MAX - OE_HI * c4(aref); lo = w["w_lo"] - sw * GE_MAX - (-OE_LO) * c4(aref)
    P(f"AREF {a}: sim worst hi {w['w_hi']*1e3:.1f} lo {w['w_lo']*1e3:.1f} mV; + ADC Ge +0.29 %, Oe +56/-30 LSB: hi {hi*1e3:.1f} lo {lo*1e3:.1f} mV;"
      f" in gain-4 codes (sim worst) {min(w['w_hi'], w['w_lo'])/c4(aref):.0f}; usable input with 0 margin +/-{(aref/8 - 0.030)/d['gain_max']:.3f} V;"
      f" +/-5 V (+/-6 V) worst {min(w['m5_hi'], w['m5_lo'])*1e3:.1f} mV")
for r2 in ("340", "360"):
    w = R["dc"][f"dc|3.20|{r2}"]["worst"]; P(f"guard R2 {r2}k @3.20: window worst {min(w['w_hi'], w['w_lo'])*1e3:.1f} mV")
for aref in (3.20, 3.27, 3.30):
    P(f"AREF {aref}: +/-1.25 V fills {2*1.25*4*A/aref*100:.1f} % FS, +/-1 V {2*1*4*A/aref*100:.1f} %, step {c4(aref)/A*1e3:.3f} mV/code at the input;"
      f" +/-5 V range: {2*5*A/aref*100:.1f} % FS, {c1(aref)/A*1e3:.2f} mV/code")
d = R["dc"]["dc|3.30|330"]; P(f"SC-4 occupancy at 3.30, gain window {d['gain_min']:.5f}-{d['gain_max']:.5f}: {2*5*d['gain_min']/3.3*100:.2f}-{2*5*d['gain_max']/3.3*100:.2f} %")

P("\n== Q2 noise at the pin and in gain-4 codes (AREF 3.20) ==")
for k, v in R["noise"].items():
    P(f"{k}: to {v['fmax']/1e6:.1f} MHz total {v['total']*1e6:.1f} uV (res {v['res']*1e6:.1f}, amp {v['amp']*1e6:.1f}, Vmid {v['vmid']*1e6:.1f} assumed 20 nV),"
      f" through ADC pole {v['thru_adc_pole']*1e6:.1f} uV = {v['total']/c4(3.2):.3f} / {v['thru_adc_pole']/c4(3.2):.3f} gain-4 codes; density {v['density_nV']}")
P("ADC own noise from SNR (Table 46-33, full-scale sine): " + ", ".join(f"{n} {db} dB -> {snr_codes(db):.2f} codes" for n, db in
  (("gain2 typ", 71), ("gain2 min", 66), ("other max", 68), ("other typ", 62), ("other min", 57))))
nb = R["noise"]["1p5bw"]["total"] / c4(3.2); nx = R["noise"]["x10_1p5bw"]["total"] / c4(3.2)
P("SC-6-style growth sqrt(F^2+n^2)/F-1, n = buffer at 1.5 BW, F = the ADC's own gain-4 floor (codes):")
for F, lab in ((0.41, "gain-2 SNR typ"), (0.58, "other max"), (0.72, "gain-1 measured A2, if unchanged"), (0.8, "afe 4.1 held code"),
               (1.15, "other typ"), (2.04, "other min"), (2.88, "0.72 x 4: pre-PGA noise")):
    g = np.sqrt(F**2 + nb**2) / F - 1; gx = np.sqrt(F**2 + nx**2) / F - 1
    P(f"  F {F:.2f} ({lab}): buffer {g*100:+.1f} %   10x buffer {gx*100:+.1f} %")
P(f"pin-noise limit equivalent to SC-6's 0.2 mV at gain 1 (same codes): {0.2/4*1e3:.0f} uV; buffer {R['noise']['1p5bw']['total']*1e6:.1f} uV")

P("\n== Q2 SM-5 normalised (loop gain DAC->pin G; levels and DAC floor scale with G, the ADC's own post-PGA noise does not) ==")
b = R["loop"]["base"]; Gp = R["loop"]["buf_C2_27.63"]["spacing"] / b["spacing"]; G4 = 4 * Gp
P(f"loop gain DAC->pin {Gp:.4f}, in gain-4 codes {G4:.4f}")
def growth(dac_c1, adc1, n4, afe_c4, aw_c4):
    due = np.hypot(dac_c1, adc1)
    r1 = np.sqrt((dac_c1 * G4) ** 2 + n4 ** 2 + afe_c4 ** 2 + aw_c4 ** 2) / G4
    return r1 / due - 1
aw = 0.1e-3 * A / c4(3.2)
for lab, dac_c1, adc1 in (("owner convention: 0.8 codes all DAC0", 0.8, 0.0), ("split: ADC alone 0.72 (A2), DAC0 the rest", np.sqrt(0.8**2 - 0.72**2), 0.72)):
    P(lab)
    for n4 in (0.0, 0.41, 0.58, 0.72, 1.15, 2.04, 2.88):
        P(f"  n4 {n4:.2f}: growth {growth(dac_c1, adc1, n4, nb, aw)*100:+.1f} %   (10x buffer {growth(dac_c1, adc1, n4, nx, aw)*100:+.1f} %)")
    # largest n4 that keeps the noise growth at 10 % (no ISI left)
    f = lambda n4: growth(dac_c1, adc1, n4, nb, aw) - 0.10
    lo, hi = 0.0, 5.0
    for _ in range(60):
        m = (lo + hi) / 2; lo, hi = (m, hi) if f(m) < 0 else (lo, m)
    P(f"  largest ADC gain-4 floor inside 10 % with no ISI: {lo:.2f} gain-4 codes")

P("\n== Q5 shelf (sim/loop harness, ideal AWG, R1 buffer, PA-3 switch 6 pF at N) ==")
for k, v in R["loop"].items():
    if "error" in v or k == "base":
        continue
    g = v["spacing"] / b["spacing"]
    P(f"{k}: G {g:.4f}  ISI pin(gain-1 codes) {v['worst']-b['worst']*g:+.2f}  gain-4 codes {4*(v['worst']-b['worst']*g):+.2f}  normalised {v['worst']/g-b['worst']:+.2f}")
xs = [k for k in R["loop"] if k.startswith("buf_C2_")]
c2 = np.array([float(k.split("_")[-1]) for k in xs]); isn = np.array([R["loop"][k]["worst"] / (R["loop"][k]["spacing"] / b["spacing"]) - b["worst"] for k in xs])
o = np.argsort(c2); c2, isn = c2[o], isn[o]; k = int(np.argmin(isn))
s_dn = np.polyfit(c2[:k+1], isn[:k+1], 1)[0]; s_up = np.polyfit(c2[k:], isn[k:], 1)[0]
P(f"normalised slope {s_dn:.2f} / +{s_up:.2f} codes per pF; x G4 = gain-4 codes per pF {s_dn*G4:.2f} / +{s_up*G4:.2f}")
kn = growth(0.8, 0.0, 0.0, nb, aw) + 1
allow = (0.10 - (kn - 1)) * 8.6
P(f"owner convention, n4 = 0: noise factor {kn:.4f}, ISI allowance {allow:.2f} normalised codes at band 8.6 -> C2 accuracy +/-{allow/max(abs(s_dn), s_up)*1e3:.0f} fF")

P("\n== Q4 differential ranges on the +/-5 V divider (Table 44-6: DIFF=1 GAIN 00/01/10/11 = 0.5/1/2/2; OFFSET 0 in DIFF, Table 44-7) ==")
for aref in (3.20, 3.30):
    for g, fs in ((0.5, aref), (1, aref / 2), (2, aref / 4)):
        P(f"AREF {aref} PGA {g}: +/-{fs/A:.2f} V difference, {2*fs/4096/A*1e3:.2f} mV per code")
P(f"single-ended input limit per pin +/-6 V (SC-2), so PGA 0.5 is usable to +/-12 V of difference")
P(f"\nANACH settling: AST3 {3/22.5e6*1e9:.0f} ns, AST5 {5/22.5e6*1e9:.0f} ns, AST9 {9/22.5e6*1e9:.0f} ns, AST17 {17/22.5e6*1e9:.0f} ns against tSETTLE >= 200 ns (Table 46-28);"
  f" 21.5 + 5 clocks per conversion -> {22.5e6/26.5:.0f} sps aggregate if added to every conversion *(check)*")
P(f"tracking: Z 25 ohm -> tTRACK {0.054*25+205:.0f} ns (12-bit formula); for 0.5 gain-4 LSB, 2 bits finer: x ln(2^15)/ln(2^13) = {(0.054*25+205)*np.log(2**15)/np.log(2**13):.0f} ns against 667 ns *(derived, check)*")
