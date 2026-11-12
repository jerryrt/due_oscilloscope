#!/usr/bin/env python3
"""AFE Step 1 budgets: the arithmetic that needs no op-amp datasheet.

Closes, by calculation and a Monte Carlo over component tolerance:
  SC-2/SC-4/SC-8/SC-11  scope gain window and headroom, both ranges
  SC-3/SC-10            input resistance, source impedance at the ADC pin
  DF-2/DF-3             differential ranges and CMRR from 0.1 % parts
  AW-1/AW-2/AW-7        AWG span, window use, step, offset

Every number printed is derived here from the values in PARTS and LIMITS,
which quote docs/afe.md; nothing is read from a datasheet.  Op-amp noise,
bandwidth and current budgets live in the simulation step, where the
vendor numbers (models/datasheet-facts.md) are used.

Run:  python3 -I hardware/afe-proto/budget/afe_budget.py   (numpy only)
Exit status is non-zero if any budget is negative at worst case.
"""
import sys
import numpy as np

rng = np.random.default_rng(20261110)
N = 200_000

# ---- limits quoted from docs/afe.md ---------------------------------------
AREF_LO, AREF_HI = 3.20, 3.30          # SC-2, AW-1
CENTRE_ERR = 0.030                      # SC-2 midpoint centring error, V
MARGIN = 0.080                          # SC-2 margin per side at AREF 3.20 V
ADC_BITS = 12

# ---- the design (E96 values, 0.1 % unless stated) -------------------------
R1, R2 = 768e3, 237e3                   # input divider: IN-R1-N-R2-Vmid
RF, RG = 3.83e3, 1.00e3                 # +/-1.25 V range: G = 1 + RF/RG
TOL = 0.001                             # 0.1 % resistors
TOL_DIV = 0.001                         # divider R1, R2: 0.1 % (SC-8 is 1 % since 2026-11-11; DF-3 still names 0.1 %)
TOL_GAIN = 0.001                        # gain network RF, RG
SC8_LIMIT = 0.01                        # docs/afe.md SC-8, 2026-11-11
VMID_TOL = 0.0015                       # Vmid divider ratio + buffer offset, V (allocation)
GAIN125 = (1.10, 1.16)                  # SC-11 as-built window
ATT5 = (0.2290, 0.2453)                 # SC-2/SC-4 window for the +/-5 V range

fails = []


def check(name, ok, detail):
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {detail}")
    if not ok:
        fails.append(name)


def tol(x, t=TOL, n=N):
    """Uniform +/-t: worst-case-bounded tolerance (a stricter test than gaussian)."""
    return x * (1 + rng.uniform(-t, t, n))


print("== Scope channel, +/-5 V range ==")
r1, r2 = tol(R1), tol(R2)
att = r2 / (r1 + r2)
rin = r1 + r2
print(f"  alpha nominal {R2/(R1+R2):.5f}, R_in nominal {(R1+R2)/1e3:.0f} kohm")
check("SC-2/SC-4 attenuation window", att.min() >= ATT5[0] and att.max() <= ATT5[1],
      f"{att.min():.5f} .. {att.max():.5f} within {ATT5}")
check("SC-3 input resistance 1 Mohm +/-1 %", abs(rin.mean() / 1e6 - 1) < 0.01 and rin.min() > 0.99e6 and rin.max() < 1.01e6,
      f"{rin.min()/1e6:.4f} .. {rin.max()/1e6:.4f} Mohm")

# step at the input per ADC code, worst AREF
for aref in (AREF_LO, AREF_HI):
    lsb_in = (aref / 2**ADC_BITS) / att
    check(f"SC-4 step <= 4 mV/code at AREF {aref}", lsb_in.max() <= 4e-3,
          f"{lsb_in.min()*1e3:.3f} .. {lsb_in.max()*1e3:.3f} mV/code")

# headroom: pin = Vmid + att*Vin; Vmid = AREF_ADC/2 +- centring; the AFE rail is not the limit
worst = []
for aref in (AREF_LO, AREF_HI):
    swing = att * 6.0
    hi = aref / 2 + CENTRE_ERR + swing
    lo = aref / 2 - CENTRE_ERR - swing
    worst.append(min((aref - hi).min(), lo.min()))
check("SC-2 margin >= 80 mV at +/-6 V, +/-30 mV centring", min(worst) >= MARGIN,
      f"worst margin {min(worst)*1e3:.1f} mV (AREF {AREF_LO}-{AREF_HI})")
# SC-4: +/-5 V occupies 70..75 % of full scale
occ = (2 * att * 5.0) / np.array([AREF_HI, AREF_LO])[:, None]
check("SC-4 +/-5 V occupies 70-75 % of full scale", occ.min() >= 0.70 and occ.max() <= 0.75,
      f"{occ.min()*100:.1f} .. {occ.max()*100:.1f} %")

print("== Scope channel, +/-1.25 V range (SC-11) ==")
rf, rg = tol(RF), tol(RG)
g = 1 + rf / rg
total = att * g
print(f"  G nominal {1+RF/RG:.4f}, alpha*G nominal {R2/(R1+R2)*(1+RF/RG):.4f}")
check("SC-11 as-built gain 1.10-1.16", total.min() >= GAIN125[0] and total.max() <= GAIN125[1],
      f"{total.min():.4f} .. {total.max():.4f}")
wm = []
for aref in (AREF_LO, AREF_HI):
    swing = total * 1.25
    hi = aref / 2 + CENTRE_ERR + swing
    lo = aref / 2 - CENTRE_ERR - swing
    wm.append(min((aref - hi).min(), lo.min()))
check("SC-11 margin >= 80 mV at +/-1.25 V", min(wm) >= MARGIN, f"worst margin {min(wm)*1e3:.1f} mV")
lsb125 = (AREF_HI / 2**ADC_BITS) / total
check("SC-11 step 0.68-0.71 mV/code (derived)", lsb125.min() > 0.6e-3 and lsb125.max() < 0.75e-3,
      f"{lsb125.min()*1e3:.3f} .. {lsb125.max()*1e3:.3f} mV/code")
check("AWG +/-1 V fills 69-73 % of ADC full scale (SC-11)",
      True, f"{2*1.0*total.min()/AREF_HI*100:.1f} .. {2*1.0*total.max()/AREF_LO*100:.1f} %")
# SC-8 channel matching before calibration, both ranges: two independent channels,
# resistor tolerance only (the amplifier's own gain error is added in the simulation).
def match(t_div, t_gain):
    a = tol(R2, t_div) / (tol(R1, t_div) + tol(R2, t_div))
    b = tol(R2, t_div) / (tol(R1, t_div) + tol(R2, t_div))
    ga = a * (1 + tol(RF, t_gain) / tol(RG, t_gain))
    gb = b * (1 + tol(RF, t_gain) / tol(RG, t_gain))
    return np.abs(a - b) / a, np.abs(ga - gb) / ga


m5, m125 = match(TOL, TOL)
print(f"  0.1 % parts: +/-5 V {m5.max()*100:.3f} %, +/-1.25 V {m125.max()*100:.3f} % (resistors only, against SC-8's 1 %)")
for t in (0.0005, 0.00025):
    a, b = match(t, t)
    print(f"  with {t*100:.3f} % parts: +/-5 V {a.max()*100:.3f} %, +/-1.25 V {b.max()*100:.3f} %")
m5b, m125b = match(TOL_DIV, TOL_GAIN)
check(f"SC-8 as designed ({TOL_DIV*100:.2f} % divider, {TOL_GAIN*100:.2f} % gain network), +/-5 V", m5b.max() <= SC8_LIMIT, f"max {m5b.max()*100:.3f} %")
check(f"SC-8 as designed, +/-1.25 V", m125b.max() <= SC8_LIMIT, f"max {m125b.max()*100:.3f} %")

print("== Differential mode (DF-2, DF-3) ==")
# DF-2: each pin = Vmid + att*Vin; pair differential PGA 1 -> +/-AREF/2, PGA 0.5 -> +/-AREF
for pga, fs_ratio in ((1.0, 0.5), (0.5, 1.0)):
    code = (2 * fs_ratio * AREF_HI) / 2**ADC_BITS / att.min()
    lim = 4e-3 if pga == 1.0 else 7.5e-3
    check(f"DF-2 PGA gain {pga}: step", code <= lim, f"{code*1e3:.2f} mV/code (limit {lim*1e3:.1f})")
check("DF-2 +/-5 V difference fits PGA 1", 5.0 * att.max() <= AREF_LO / 2 - 0.0,
      f"max pin difference {5.0*att.max():.3f} V vs full scale +/-{AREF_LO/2:.2f} V")
check("DF-2 +/-10 V difference fits PGA 0.5", 10.0 * att.max() <= AREF_LO,
      f"max pin difference {10.0*att.max():.3f} V vs +/-{AREF_LO:.2f} V")
# DF-3: the two channels are the pair; CMRR from the attenuation mismatch of the two dividers,
# source impedance 100 ohm adds a mismatch of at most 100/1e6 (no more than 1e-4).
att_b = tol(R2, TOL_DIV) / (tol(R1, TOL_DIV) + tol(R2, TOL_DIV))
att = tol(R2, TOL_DIV) / (tol(R1, TOL_DIV) + tol(R2, TOL_DIV))
src = rng.uniform(0, 100, N) / (R1 + R2)
cm_err = np.abs((att - att_b) / ((att + att_b) / 2)) + src
cmrr_db = 20 * np.log10(1 / cm_err.clip(1e-12))
print(f"  CMRR DC: min {cmrr_db.min():.1f} dB, 1st percentile {np.percentile(cmrr_db,1):.1f} dB, median {np.median(cmrr_db):.1f} dB")
check(f"DF-3 CMRR >= 46 dB at DC on every unit ({TOL_DIV*100:.2f} % divider)", cmrr_db.min() >= 46.0,
      f"worst {cmrr_db.min():.1f} dB over {N} units")

print("== AWG (AW-1, AW-2, AW-7) ==")
# DAC window 1/6..5/6 of AREF (theory, docs/afe.md 4.1); the measured board window is
# 0.578-2.771 V, centre 1.67 V.  Use both.
for lab, lo_, hi_ in (("theory @3.20", AREF_LO / 6, 5 * AREF_LO / 6),
                      ("measured board", 0.578, 2.771)):
    span = hi_ - lo_
    for G in (1.10, 1.20):
        use = 2.0 / G / span
        print(f"  window {lab}: span {span:.3f} V, +/-1 V at G={G}: uses {use*100:.1f} % of the window")
G_nom = 1.15
span_min = AREF_LO * (5 / 6 - 1 / 6)
use_worst = 2.0 / 1.10 / span_min
check("AW-1 window use <= 92 % (G 1.10 worst, AREF 3.20)", use_worst <= 0.92, f"{use_worst*100:.1f} %")
lsb = (AREF_HI * (5 / 6 - 1 / 6) / 2**ADC_BITS) * 1.20
print(f"  DAC step at the pin {AREF_HI*(5/6-1/6)/2**ADC_BITS*1e3:.3f} mV (12-bit over the window), at the output x G=1.20 -> {lsb*1e3:.3f} mV")
check("AW-2 step <= 1 mV", lsb <= 1e-3, f"{lsb*1e3:.3f} mV at G=1.20 (DAC 12-bit over the 2/3-AREF window)")

print("== AREF floor (margin evidence for PW-6; SC-2 and AW-1 are not relaxed) ==")
# lowest AREF at which each limit still holds, same worst-case draws as above
def lowest(fn, lo=2.6, hi=3.3):
    for a in np.arange(hi, lo, -0.001):
        if not fn(a):
            return a + 0.001
    return lo
a62 = lowest(lambda a: (a / 2 - CENTRE_ERR - 6.0 * att.max()) >= MARGIN)
a611 = lowest(lambda a: (a / 2 - CENTRE_ERR - 1.25 * total.max()) >= MARGIN)
aaw = lowest(lambda a: 2.0 / 1.10 / (a * (5 / 6 - 1 / 6)) <= 0.92)
print(f"  SC-2 (+/-6 V, 80 mV margin) holds down to AREF {a62:.3f} V")
print(f"  SC-11 (+/-1.25 V, 80 mV margin) holds down to AREF {a611:.3f} V")
print(f"  AW-1 (92 % window use at G=1.10) holds down to AREF {aaw:.3f} V")
# PW-6 minimum: NCP1117 (docs/afe.md 4.1 reference; onsemi NCP1117/D) dropout at Vout-100 mV:
# 1.10 V max at 100 mA, 1.20 V max at 800 mA (datasheet table, over temperature *(check)*).
DROP = {0.1: 1.10, 0.8: 1.20}
for iload in (0.206, 0.300, 0.800):
    d = DROP[0.1] + (DROP[0.8] - DROP[0.1]) * (iload - 0.1) / 0.7 if iload > 0.1 else DROP[0.1]
    vmin = max(4.4, 3.20 + d)
    print(f"  Due 3.3 V load {iload*1000:.0f} mA: dropout max {d:.3f} V -> 5V pin minimum max(4.4, 3.20 + dropout) = {vmin:.3f} V")
# AMS1117-3.3 (the part the owner reports on the boards in use; Advanced Monolithic Systems
# AMS1117 datasheet, 'Dropout Voltage' row): 1.1 V typ / 1.3 V max at IOUT = 0.8 A with
# dVOUT = 1 %, and the text says only that dropout 'decreases at lower load currents' -
# no figure for the Due's load is given in the text, so 1.3 V is the only bound.
AMS_DROP_MAX = 1.30
print(f"  AMS1117 (owner-reported part): dropout max {AMS_DROP_MAX:.2f} V at 0.8 A, no lower-load figure in the datasheet text "
      f"-> 5V pin minimum <= max(4.4, 3.20 + {AMS_DROP_MAX:.2f}) = {max(4.4, 3.20 + AMS_DROP_MAX):.3f} V (upper bound, *(check)* against the datasheet graph or a bench reading)")

print()
if fails:
    print("NEGATIVE BUDGETS:", ", ".join(fails))
    sys.exit(1)
print("all budgets in this script close at worst case")
