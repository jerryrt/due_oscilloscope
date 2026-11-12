#!/usr/bin/env python3
"""DF-3 after the PA-3 gain calibration: analytic worst-corner CMRR.

Same sensitivities as sim/diff/report.md 'Analytic cross-check' (which the
simulator reproduced within 0.1 dB).  Worst case mismatch between the two
channels, as a fraction of gain:

  divider   2 * (0.765 + 0.530 + 0.235) * (tol_div + tc_div*dT)   R1,R2,R3
  stage     2 * 1.586 * (tol_st + tc_st*dT)   (+-1.25 V: RF, RG)
            dRon/RG/1.02                      (+-5 V: switch Ron spread)
  op-amp    2 * 0.040 %                       (68 dB, typ-or-min *(check)*)
  source    100 ohm / 1.004 Mohm

The PA-3 calibration injects at node N, after the divider: it fits the
STAGE gain of each channel, so the stage tolerance and the Ron spread drop
out at the calibration temperature and only their drift over dT stays.  It
cannot see the divider ratio (no source at the input pin), so the divider
tolerance stays whole.  Cal residual (ADC noise, DAC8551 accuracy) is a
parameter, default 0.01 % *(check: not yet derived)*.

One-time trim (sim/diff scenarios trim_cal and trim_raw, same assumptions): a 10 kohm SMD cermet
trimmer (5 kohm mid-setting, 0..10 kohm, 100 ppm/K *(check: datasheet of the actual part not read)*) in
series with a fixed 330 kohm R2 (the 335 kohm leg), set once at build to null the common-mode response at
+-6 V on the +-5 V range.  Set AFTER the PA-3 calibration ("cal") it removes the divider's tolerance and
leaves the setting residual (TRIM_RES = 0.05 % of divider ratio *(check)*), the divider's drift over dT, the
trimmer's own drift, and the stage terms above.  Set on the raw reading ("raw") it compensates the stage
mismatch with the divider, and the calibration then puts that stage mismatch back: it does not help.

Run: python3 -I hardware/afe-proto/budget/df3_postcal.py   (exit 0)
"""
import math

DT = 10.0  # K between calibration and use (same as the sim/diff report)
LIMIT_DB = 46.0


def cmrr_db(m):
    return -20 * math.log10(m)


TRIM_RES = 5e-4          # residual of the one-time trim, relative divider ratio *(check)*
RT_MAX_OHM, RT_TC, LEG = 10e3, 100e-6, 335e3   # trimmer travel, tempco, R2 leg at mid-setting


def mismatch(tol_div, tc_div, tol_st, tc_st, ron_drift, calibrated,
             cal_res=1e-4, dron=5.1, rg=249.0, rng="1.25", trim=None, trim_res=TRIM_RES):
    if trim is None:
        div = 2 * (0.765 + 0.530 + 0.235) * (tol_div + tc_div * 1e-6 * DT)
    else:
        # tolerance trimmed out; what stays: the divider's drift over dT (the two channels drift apart), the trimmer's
        # own drift (worst case the whole 10 kohm), and the setting residual
        div = (2 * (0.765 + 0.530 + 0.235) * tc_div * 1e-6 * DT
               + 2 * 0.530 * RT_MAX_OHM * RT_TC * DT / LEG + trim_res)
        if trim == "raw":
            # the trim compensated the raw stage mismatch with the divider; the calibration removes the stage and
            # leaves the compensation: the stage mismatch at the calibration temperature, whole
            div += (2 * 1.586 * tol_st) if rng == "1.25" else dron / rg / 1.02
    if rng == "1.25":
        st_raw = 2 * 1.586 * (tol_st + tc_st * 1e-6 * DT)
        st_cal = 2 * 1.586 * (tc_st * 1e-6 * DT)
    else:
        st_raw = dron / rg / 1.02
        st_cal = dron * ron_drift / rg / 1.02
    st = (st_cal + cal_res) if calibrated else st_raw
    return div + st + 2 * 0.00040 + 100 / 1.004e6


def row(label, **kw):
    out = []
    for rng in ("5", "1.25"):
        m = mismatch(rng=rng, **kw)
        out.append((rng, m, cmrr_db(m)))
    return label, out


CASES = [
    # (label, divider tol, divider tc, stage tol, stage tc, Ron drift frac/10K)
    ("0.1 %, 25 ppm/K, before cal", dict(tol_div=1e-3, tc_div=25, tol_st=1e-3, tc_st=25, ron_drift=0.01, calibrated=False)),
    ("0.1 %, 25 ppm/K, after cal", dict(tol_div=1e-3, tc_div=25, tol_st=1e-3, tc_st=25, ron_drift=0.01, calibrated=True)),
    ("divider 0.05 %, 25 ppm/K, after cal", dict(tol_div=5e-4, tc_div=25, tol_st=1e-3, tc_st=25, ron_drift=0.01, calibrated=True)),
    ("0.1 %, 25 ppm/K, trimmer set after cal (trim_cal)", dict(tol_div=1e-3, tc_div=25, tol_st=1e-3, tc_st=25, ron_drift=0.01, calibrated=True, trim="cal")),
    ("0.1 %, 25 ppm/K, trimmer set on the raw reading (trim_raw)", dict(tol_div=1e-3, tc_div=25, tol_st=1e-3, tc_st=25, ron_drift=0.01, calibrated=True, trim="raw")),
    ("0.1 %, 10 ppm/K, after cal", dict(tol_div=1e-3, tc_div=10, tol_st=1e-3, tc_st=10, ron_drift=0.01, calibrated=True)),
]

if __name__ == "__main__":
    print("Ron drift over dT is 1 % of Ron *(check: TMUX1119 Ron-vs-temperature "
          "curve not read)*; Ron spread 5.1 ohm (sim/diff).")
    res = {}
    for label, kw in CASES:
        _, out = row(label, **kw)
        res[label] = out
        print(f"{label:40s}", "  ".join(f"{r}V range {m*100:.3f} % -> {d:5.1f} dB" for r, m, d in out))
    # guard: the 'before' case must NOT reach 46 dB, i.e. the check can fail
    before = min(d for _, _, d in res["0.1 %, 25 ppm/K, before cal"])
    assert before < LIMIT_DB, "guard: uncalibrated 0.1 % parts must fail 46 dB"
    # guard 2: breaking the divider (1 % parts) must fail even after cal
    bad = mismatch(tol_div=1e-2, tc_div=25, tol_st=1e-3, tc_st=25, ron_drift=0.01,
                   calibrated=True, rng="1.25")
    assert cmrr_db(bad) < LIMIT_DB, "guard: 1 % divider must fail after cal"
    print("guards: uncalibrated and 1 % divider both fail 46 dB (check can fail)")
    # guard 3: a trim that is too coarse must fail, and a trim set on the raw reading must fail (the check can fail)
    coarse = mismatch(tol_div=1e-3, tc_div=25, tol_st=1e-3, tc_st=25, ron_drift=0.01, calibrated=True,
                      rng="1.25", trim="cal", trim_res=5e-3)
    assert cmrr_db(coarse) < LIMIT_DB, "guard: a 0.5 % trim residual must fail 46 dB"
    assert min(d for _, _, d in res["0.1 %, 25 ppm/K, trimmer set on the raw reading (trim_raw)"]) < LIMIT_DB, \
        "guard: a trim set on the raw reading must fail 46 dB after cal"
    print("guards: 0.5 % trim residual and a raw-reading trim both fail 46 dB (check can fail)")
    print("trim residual sweep, 1.25 V range (the worse):", "  ".join(
        f"{r*100:.2f} % -> {cmrr_db(mismatch(tol_div=1e-3, tc_div=25, tol_st=1e-3, tc_st=25, ron_drift=0.01, calibrated=True, rng='1.25', trim='cal', trim_res=r)):.1f} dB"
        for r in (0.0, 5e-4, 1e-3, 2e-3, 5e-3)))
    for label in ("0.1 %, 25 ppm/K, after cal", "divider 0.05 %, 25 ppm/K, after cal", "0.1 %, 25 ppm/K, trimmer set after cal (trim_cal)"):
        ok = all(d >= LIMIT_DB for _, _, d in res[label])
        print(f"{label}: {'meets' if ok else 'MISSES'} {LIMIT_DB:.0f} dB at the worst corner")
