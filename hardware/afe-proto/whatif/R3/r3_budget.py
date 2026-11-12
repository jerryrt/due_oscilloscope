#!/usr/bin/env python3
"""What-if R3: scope divider at 1 % Basic thick film, divider ratio calibrated by an
AWG -> BNC cable -> scope loopback with the MCP3564 reading the AWG at the BNC.

Analytic only, in the form of budget/df3_postcal.py (copied here as df3_postcal_ref.py);
no simulation.  Run: python3 -I r3_budget.py   (exit 0; asserts are the guards)

Divider: R1 from the input to node N, R2 from N to Vmid, R3 from N to the 3.3 V sense
node (= AREF).  alpha = (R2||R3)/(R1 + R2||R3).  N(0) = Vmid needs R3 = R1 exactly.
Stage: +-5 V range G = 1 + Ron/RG (Ron 3.7..8.8 ohm, RG 249); +-1.25 V range G = 1 + RF/RG
(953/249, 0.1 %, RF 25 ppm/K, RG 10 ppm/K).

Tracking tau (ppm/K): every resistor's tempco lies in a band tau wide (TC0 +- tau/2).  A
common TC0 cancels in the ratio.  The df3_postcal "25 ppm/K" (each part +-25) is tau = 50.
The UNI-ROYAL datasheet gives only +-100 ppm/K absolute for 0603 >10 ohm, no tracking, so
the datasheet-only worst case is tau = 200.

Every figure that is an assumption is marked (check) in the printout.
"""
import math

DB_AFTER = 44.0            # DF-3 after calibration (afe.md, 2026-11-11)
DB_BEFORE = 30.0           # DF-3 before calibration, DC
VS = 3.30                  # sense node = AREF nominal; Vmid = VS/2
RG, RF = 249.0, 953.0
RON_TYP, RON_MAX = 3.7, 8.8
DRON = 5.1                 # Ron spread between channels (sim/diff)
RON_DRIFT_PER_K = 0.01 / 10   # 1 % per 10 K (check: TMUX1119 curve not read), as df3_postcal
OPAMP = 2 * 0.00040        # op-amp CMRR term, kept as df3_postcal / C2 (check: typ or min)
RSRC = 100.0


def par(*r):
    return 1.0 / sum(1.0 / x for x in r)


def alpha(r1, r2, r3):
    p = par(r2, r3)
    return p / (r1 + p)


def sens(r1, r2, r3):
    """d ln(alpha) / d ln(Ri)."""
    a0 = alpha(r1, r2, r3)
    h = 1e-7
    out = []
    for i in range(3):
        rr = [r1, r2, r3]
        rr[i] *= 1 + h
        out.append((math.log(alpha(*rr)) - math.log(a0)) / h)
    return out


def node(vin, r1, r2, r3, vs=VS, vmid=None):
    vmid = vs / 2 if vmid is None else vmid
    return (vin / r1 + vmid / r2 + vs / r3) / (1 / r1 + 1 / r2 + 1 / r3)


def db(m):
    return -20 * math.log10(m)


def stage_drift_mismatch(rng, dT):
    if rng == "5":
        return DRON * RON_DRIFT_PER_K * dT / RG / 1.02
    return 2 * 1.586 * 25e-6 * dT          # df3_postcal's RF/RG term (2 x 1.586 x tc x dT)


def stage_raw_mismatch(rng, dT, tol_st=1e-3, tc_st=25e-6):
    if rng == "5":
        return DRON / RG / 1.02
    return 2 * 1.586 * (tol_st + tc_st * dT)


def df3_r3(rng, S, tau, dT, cal_res, rin):
    """R3: whole chain calibrated by the loop at the calibration temperature.  What stays:
    the divider's drift since calibration (tracking), the stage's drift, the loop's own
    residual, the op-amp and source terms."""
    div = S * tau * 1e-6 * dT
    return div + stage_drift_mismatch(rng, dT) + cal_res + OPAMP + RSRC / rin


def df3_stage_only(rng, S, tol, tc, dT, cal_res, rin):
    """Present PA-3: stage calibrated by injection, divider trusted (df3_postcal form)."""
    # df3_postcal: 2 * (0.765 + 0.530 + 0.235) * (tol + tc*dT), and S = sum|sens| = 1.53
    div = 2 * S * (tol + tc * 1e-6 * dT)
    return div + stage_drift_mismatch(rng, dT) + cal_res + OPAMP + RSRC / rin


def df3_before(rng, S, tol, tc, dT, rin):
    div = 2 * S * (tol + tc * 1e-6 * dT)
    return div + stage_raw_mismatch(rng, dT) + OPAMP + RSRC / rin


def corners(n):
    for k in range(2 ** n):
        yield [1 if (k >> i) & 1 else -1 for i in range(n)]


def gain_window(r1, r2, r3, tol, tc, dT):
    lo5 = lo125 = 1e9
    hi5 = hi125 = -1e9
    for s in corners(3):
        e = [s[i] * (tol + tc * 1e-6 * dT) for i in range(3)]
        a = alpha(r1 * (1 + e[0]), r2 * (1 + e[1]), r3 * (1 + e[2]))
        g5lo, g5hi = 1 + 3.7 / (RG * 1.001), 1 + RON_MAX / (RG * 0.999)   # sim/scope: +1.5 .. +3.5 %
        g125lo = 1 + RF * 0.999 / (RG * 1.001)
        g125hi = 1 + RF * 1.001 / (RG * 0.999)
        lo5, hi5 = min(lo5, a * g5lo), max(hi5, a * g5hi)
        lo125, hi125 = min(lo125, a * g125lo), max(hi125, a * g125hi)
    return (lo5, hi5), (lo125, hi125)


def margin_model(r1, r2, r3, tol, tc, dT, rng, aref=3.20, vmid_err=0.030, vos=0.0):
    """Worst pin margin to 0 and AREF, ideal stage (no swing limit).  Used only as a
    DELTA against the simulated margin (sim/scope/report.md), never as the margin."""
    vin = 6.0 if rng == "5" else 1.25
    worst = 1e9
    for s in corners(3):
        e = [s[i] * (tol + tc * 1e-6 * dT) for i in range(3)]
        R = (r1 * (1 + e[0]), r2 * (1 + e[1]), r3 * (1 + e[2]))
        for vm_e in (-vmid_err, vmid_err):
            vmid = aref / 2 + vm_e
            for g in ((1 + 3.7 / RG, 1 + RON_MAX / RG) if rng == "5" else
                      (1 + RF * 0.998 / RG, 1 + RF * 1.002 / RG)):
                for v in (vin, -vin):
                    n = node(v, *R, vs=aref, vmid=vmid)
                    pin = vmid + g * (n - vmid) + g * vos
                    worst = min(worst, aref - pin, pin)
    return worst


def centring(r1, r2, r3, tol, tc, dT):
    """Worst |N(0) - Vmid| from resistor tolerance+drift alone (V)."""
    w = 0.0
    for s in corners(3):
        e = [s[i] * (tol + tc * 1e-6 * dT) for i in range(3)]
        n = node(0.0, r1 * (1 + e[0]), r2 * (1 + e[1]), r3 * (1 + e[2]))
        w = max(w, abs(n - VS / 2))
    return w


def main():
    ok = True
    print("=" * 78)
    print("1. Divider candidates from Basic 1 % 0603 (UNI-ROYAL 0603WAF, +-100 ppm/K)")
    cands = {
        "a  R1=R3 = 330k+330k+100k (760k), R2 = 330k": (760e3, 330e3, 760e3),
        "b  R1=R3 = 330k+330k+(330k||330k||330k) (770k), R2 = 330k": (770e3, 330e3, 770e3),
        "c  R1=R3 = 470k+300k (770k), R2 = 330k": (770e3, 330e3, 770e3),
        "ref 0.1 %: R1=R3 = 768k, R2 = 330k (no trimmer)": (768e3, 330e3, 768e3),
        "ref 0.1 %: R1=R3 = 768k, R2 = 335k leg (sim nominal)": (768e3, 335e3, 768e3),
    }
    for k, (r1, r2, r3) in cands.items():
        S = sens(r1, r2, r3)
        print(f"  {k:58s} alpha {alpha(r1, r2, r3):.4f}  Rin {(r1 + par(r2, r3))/1e3:7.1f}k"
              f"  sens {S[0]:+.3f} {S[1]:+.3f} {S[2]:+.3f}")

    r1, r2, r3 = cands["a  R1=R3 = 330k+330k+100k (760k), R2 = 330k"]
    S = sum(abs(x) for x in sens(r1, r2, r3))
    rin = r1 + par(r2, r3)

    print("=" * 78)
    print("2. DF-3 at DC, worst corner (analytic, df3_postcal form), divider = candidate a")
    print("   cal residual of the loop: 62 ppm placeholder = C2's injection residual,")
    print("   (check: C2 script lost, not reproduced; loop residual derived in section 7)")
    CAL = 62e-6
    print(f"   {'case':44s} {'+-5 V':>16s} {'+-1.25 V':>16s}")
    rows = []
    for dT in (10, 20):
        for tau in (25, 50, 100, 200):
            m5 = df3_r3("5", S, tau, dT, CAL, rin)
            m1 = df3_r3("1.25", S, tau, dT, CAL, rin)
            v = "PASS" if min(db(m5), db(m1)) >= DB_AFTER else "FAIL"
            rows.append((dT, tau, db(m5), db(m1)))
            lab = f"R3 loop-cal, dT {dT} K, tracking {tau} ppm/K"
            print(f"   {lab:44s} {db(m5):6.1f} dB ({db(m5)-DB_AFTER:+.1f}) {db(m1):6.1f} dB ({db(m1)-DB_AFTER:+.1f})  {v}")
    # references and guards
    for dT in (10, 20):
        b5 = df3_stage_only("5", S, 1e-2, 100, dT, CAL, rin)
        b1 = df3_stage_only("1.25", S, 1e-2, 100, dT, CAL, rin)
        print(f"   {'guard: 1 % divider NOT loop-calibrated, dT ' + str(dT):44s} {db(b5):6.1f} dB          {db(b1):6.1f} dB          FAIL")
        assert max(db(b5), db(b1)) < DB_AFTER, "guard: an uncalibrated 1 % divider must fail 44 dB"
        c5 = df3_stage_only("5", S, 1e-3, 25, dT, CAL, rin)
        c1 = df3_stage_only("1.25", S, 1e-3, 25, dT, CAL, rin)
        print(f"   {'reference: present 0.1 %/25 ppm, dT ' + str(dT):44s} {db(c5):6.1f} dB          {db(c1):6.1f} dB")
    # reproduce C2's figures to show the form is the same
    S768 = sum(abs(x) for x in sens(768e3, 330e3, 768e3))
    c5 = df3_stage_only("5", 1.53, 1e-3, 25, 10, 55e-6, 1.004e6)
    c1 = df3_stage_only("1.25", 1.53, 1e-3, 25, 10, 62e-6, 1.004e6)
    print(f"   check: C2 reproduced as {db(c5):.2f} / {db(c1):.2f} dB (C2 record 46.06 / 45.07)")
    assert abs(db(c5) - 46.06) < 0.05 and abs(db(c1) - 45.07) < 0.05
    # break the check: a 1000 ppm/K tracking must fail
    assert db(df3_r3("1.25", S, 1000, 10, CAL, rin)) < DB_AFTER, "guard: tracking 1000 must fail"
    # before calibration (DF-3's 30 dB clause)
    for tol, tc, lab in ((1e-2, 100, "1 %, +-100"), (1e-3, 25, "0.1 %, +-25")):
        m5, m1 = df3_before("5", S, tol, tc, 10, rin), df3_before("1.25", S, tol, tc, 10, rin)
        print(f"   before cal (>= {DB_BEFORE:.0f} dB), {lab:12s} dT 10: {db(m5):5.1f} / {db(m1):5.1f} dB")
    assert db(df3_before("5", S, 1e-2, 100, 10, rin)) < DB_BEFORE
    # largest residual that holds 44 dB
    for dT in (10, 20):
        for tau in (25, 50, 100, 200):
            out = []
            for rng in ("5", "1.25"):
                base = df3_r3(rng, S, tau, dT, 0.0, rin)
                out.append((10 ** (-DB_AFTER / 20) - base) * 1e6)
            print(f"   max loop residual for 44 dB, dT {dT}, tau {tau:3d}: +-5 V {out[0]:7.0f} ppm, +-1.25 V {out[1]:7.0f} ppm")
    # largest tracking that holds 44 dB at the placeholder residual
    for dT in (10, 20):
        t = [((10 ** (-DB_AFTER / 20)) - df3_r3(rng, S, 0, dT, CAL, rin)) / (S * 1e-6 * dT) for rng in ("5", "1.25")]
        print(f"   largest tracking holding 44 dB, dT {dT}: +-5 V {t[0]:.0f}, +-1.25 V {t[1]:.0f} ppm/K")

    print("=" * 78)
    print("3. EN-1 (15-35 C, +-10 K about 25 C): AFE gain and offset drift per channel")
    s3 = sens(r1, r2, r3)
    n0 = VS / 2
    sig = 1 / r1 + 1 / r2 + 1 / r3
    dn_dl1 = n0 / (r1 * sig)
    dn_dl3 = -(VS - n0) / (r3 * sig)
    a = alpha(r1, r2, r3)
    for lab, tau in (("0.1 %, +-25 ppm/K (present)", 50), ("1 %, tracking 50", 50),
                     ("1 %, tracking 100", 100), ("1 %, datasheet only (+-100 -> 200)", 200)):
        for dT in (10, 20):
            g_div = S * tau / 2 * 1e-6 * dT
            g5 = g_div + RON_MAX * RON_DRIFT_PER_K * dT / RG
            g1 = g_div + (RF / RG) / (1 + RF / RG) * 35e-6 * dT
            off_n = (abs(dn_dl1) + abs(dn_dl3)) * tau / 2 * 1e-6 * dT
            print(f"   {lab:38s} dT {dT:2d} K: gain +-5 V {g5*100:.3f} %, +-1.25 V {g1*100:.3f} %;"
                  f" offset at N {off_n*1e3:.2f} mV = {off_n/a*1e3:.2f} mV at the input")
    print("   (EN-1 now: gain 0.2 %, offset 3 mV, 15-35 C, excluding the Due)")

    print("=" * 78)
    print("4. SC-3, SC-4, SC-11 and centring (SC-2/SC-11 margin, SC-8 offset), dT +-10 K")
    for lab, (R, tol, tc) in {
        "a 1 %": ((760e3, 330e3, 760e3), 1e-2, 100),
        "b 1 %": ((770e3, 330e3, 770e3), 1e-2, 100),
        "ref 0.1 % 768/330": ((768e3, 330e3, 768e3), 1e-3, 25),
        "ref 0.1 % 768/335 (sim nominal)": ((768e3, 335e3, 768e3), 1e-3, 25),
    }.items():
        rin_n = R[0] + par(R[1], R[2])
        rmin = R[0] * (1 - tol) + par(R[1] * (1 - tol), R[2] * (1 - tol))
        rmax = R[0] * (1 + tol) + par(R[1] * (1 + tol), R[2] * (1 + tol))
        (l5, h5), (l1, h1) = gain_window(*R, tol, tc, 10)
        c = centring(*R, tol, tc, 10)
        print(f"   {lab:32s} Rin {rin_n/1e3:.1f}k ({rmin/1e3:.1f}-{rmax/1e3:.1f}k)  "
              f"gain +-5 V {l5:.4f}-{h5:.4f} [0.2290-0.2453]  +-1.25 V {l1:.4f}-{h1:.4f} [1.10-1.16]")
        a_ = alpha(*R)
        print(f"   {'':32s} centring at N +-{c*1e3:.2f} mV -> pin +-{c*1.035*1e3:.1f} mV (+-5 V) / +-{c*4.83*1e3:.1f} mV (+-1.25 V);"
              f" input {c/a_*1e3:.1f} mV; SC-8 channel offset diff up to {2*c/a_*1e3:.1f} mV [5 mV]")
    base5 = margin_model(768e3, 335e3, 768e3, 1e-3, 25, 10, "5")
    base1 = margin_model(768e3, 335e3, 768e3, 1e-3, 25, 10, "1.25")
    for lab, R in (("a", (760e3, 330e3, 760e3)), ("b", (770e3, 330e3, 770e3))):
        m5 = margin_model(*R, 1e-2, 100, 10, "5")
        m1 = margin_model(*R, 1e-2, 100, 10, "1.25")
        e5, e1 = 110.9 + (m5 - base5) * 1e3, 115.2 + (m1 - base1) * 1e3
        print(f"   margin (sim 110.9 / 115.2 mV at the 335k nominal, 0.1 %, + model delta) {lab}: "
              f"+-5 V {e5:.1f} mV, +-1.25 V {e1:.1f} mV  [>= 80]  "
              f"{'PASS' if min(e5, e1) >= 80 else 'FAIL'}")
    # guard: the margin model must see a wrong divider (sim/scope's 450k mutation fails SC-2)
    mbad = margin_model(768e3, 450e3, 768e3, 1e-3, 25, 10, "5")
    assert 110.9 + (mbad - base5) * 1e3 < 80, "guard: margin delta model blind to a wrong R2"

    print("=" * 78)
    print("5. SC-7 gain budget, divider part only (the rest is common to both designs)")
    print(f"   present: divider trusted, 0.1 % + 25 ppm x 10 K: +-{S*(1e-3+25e-6*10)*100:.3f} % of reading")
    for tau in (50, 100, 200):
        print(f"   R3: drift since loop cal, tracking {tau}: +-{S*tau/2*1e-6*10*100:.3f} %;"
              f" plus the AWG sense divider k = R/(R+R) at 0.1 %: +-0.100 % (check: F-11 not designed)")

    print("=" * 78)
    print("7. Loop residual from noise (1 sigma, two-point slope, 1e5 Due samples per point)")
    due = math.sqrt(0.64e-3 ** 2 + 0.2e-3 ** 2)
    awg = 0.74e-3   # DAC0 0.64 mV x AWG slope 1.15 (check: AWG output noise with DAC0 driving not measured)
    for rng, g in (("5", 0.2324 * 1.02), ("1.25", 0.2324 * 4.827)):
        sd = math.sqrt(due ** 2 + (awg * g) ** 2) / math.sqrt(1e5)
        res = math.sqrt(2) * sd / (2.0 * g)
        print(f"   +-{rng} V: Due mean {sd*1e6:.2f} uV over a {2*g*1e3:.0f} mV span -> {res*1e6:.1f} ppm"
              " (MCP3564 side not included: its read of AWG noise depends on the filter, check)")
    return ok


if __name__ == "__main__":
    main()
