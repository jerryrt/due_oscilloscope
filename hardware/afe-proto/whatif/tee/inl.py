"""Due-ADC INL in the tee calibration: what it leaves in each channel's gain (absolute, SC-7) and in the
ratio of the two channels' gains (DF-3).  numpy only, no simulation.

The fit is powercal's C3-e (sim/powercal/run.py, run_c3 gain_fit): least squares of the averaged Due code against
the voltage the MCP3564 reads, 99.9th percentile of |slope_fit / slope_true - 1|.  Two things differ for the tee:
  * the stimulus is the AWG at the tee, read by the MCP at the AWG BNC, so the fit is of the WHOLE channel
    (divider + stage + Due ADC) against v_awg, and its span is the AWG's +-1.0 to +-1.15 V, not DAC0 at N;
  * both channels are read at the same AWG levels by ONE ADC, so the INL is the same function of code for both.
    Whether it cancels in the ratio depends on whether the two channels sit at the same codes, which they do not:
    their offsets (OPA354 Vos up to 8 mV x the stage gain, centring) and gains (tolerance, Ron) differ.

INL models (A = amplitude in LSB):
  'pt'     powercal's: independent uniform +-A at every point and every channel (no code structure, so no
           cancellation by construction; the pessimistic bound and C3-e's own model)
  'code'   one random function of code for the ADC, shared by both channels: knots every L codes, uniform +-A,
           linear between, seen through the ADC's own 0.8-code noise (the averaged mean is INL convolved with it)
  'cubic'  smooth S-shaped bow, A at its extremes over 0..4095 (A=0.5 is afe.md 4.1's measured straightness)
  'parab'  smooth parabolic bow, A at mid-scale
"""
import math
import numpy as np

FS = 4095.0
AREF = 3.3
CPV = FS / AREF                 # codes per volt at the pin
ALPHA = 0.2324                  # divider ratio, 760k / 330k / 760k (whatif/R3 candidate a)
G125 = 1 + 953.0 / 249.0        # +-1.25 V stage
RG = 249.0
NOISE = math.hypot(0.8, 0.5)    # held-code noise per sample, ADC 0.8 + DAC/AWG 0.5 codes (powercal C3-e)
DITHER = 0.8                    # the ADC's own noise, the only part certain to dither the transfer *(conservative)*
NAVG = 100000                   # Due samples per point (powercal C3-e)


def inl_fn(model, A, L, rng):
    """Return f(codes) -> INL in LSB, as seen through the averaging (dithered), for one ADC."""
    if model == "code":
        nk = int(FS // L) + 3
        knots = rng.uniform(-A, A, nk)
        grid = np.arange(-8.0, FS + 8.0, 0.25)
        raw = np.interp(grid / L, np.arange(nk), knots)
        # convolve with the ADC's own noise (Gaussian, sigma DITHER codes)
        k = np.arange(-6 * DITHER, 6 * DITHER + 1e-9, 0.25)
        w = np.exp(-0.5 * (k / DITHER) ** 2); w /= w.sum()
        sm = np.convolve(raw, w, mode="same")
        return lambda c: np.interp(c, grid, sm)
    if model == "cubic":
        sgn = rng.choice((-1.0, 1.0))
        kk = 1 / (2 / (3 * math.sqrt(3)))           # max |x^3 - x| on [-1, 1] is 2/(3 sqrt 3)
        return lambda c: sgn * A * kk * (((c - 2048) / 2048) ** 3 - (c - 2048) / 2048)
    if model == "parab":
        sgn = rng.choice((-1.0, 1.0))
        return lambda c: sgn * A * (1 - ((c - 2048) / 2048) ** 2)
    raise ValueError(model)


def fit(npts, vt, rng_name, model="pt", A=1.2, L=8, N=20000, tol_div=1e-3, vos=8e-3, seed=1, mcp=True,
        same_codes=False, indep_adc=False, navg=NAVG, span=None, mcp_e=84e-6, mcp_bow=False):
    """Monte Carlo of the tee calibration on one range.  Returns dict of 99.9th percentiles (in %):
    'abs' = per-channel gain error, 'ratio' = |eA - eB|, 'ratio_signed_sd' = sd of eA - eB.
    same_codes: guard, both channels identical in gain and offset (the INL must then cancel exactly).
    indep_adc: guard, each channel gets its own INL function (no cancellation)."""
    rng = np.random.default_rng(seed)
    ea, eb = np.empty(N), np.empty(N)
    v = np.linspace(-vt, vt, npts) if span is None else np.linspace(span[0], span[1], npts)
    for i in range(N):
        if model != "pt":
            f_a = inl_fn(model, A, L, rng)
            f_b = inl_fn(model, A, L, rng) if indep_adc else f_a
        if rng_name == "5":
            ga = 1 + rng.uniform(3.7, 8.8) / RG
            gb = 1 + rng.uniform(3.7, 8.8) / RG
        else:
            ga = gb = G125
        # per-channel gain tolerance of the divider (sum of |sensitivities| 1.54) and offsets at the pin
        sa = CPV * ALPHA * ga * (1 + 1.54 * rng.uniform(-tol_div, tol_div))
        sb = CPV * ALPHA * gb * (1 + 1.54 * rng.uniform(-tol_div, tol_div))
        cent = 8.5e-3 * tol_div / 1e-2           # divider centring at N, scaled from whatif/R3 (8.49 mV at 1 %)
        oa = CPV * ga * (rng.uniform(-vos, vos) + rng.uniform(-cent, cent) + rng.uniform(-0.2e-3, 0.2e-3))
        ob = CPV * gb * (rng.uniform(-vos, vos) + rng.uniform(-cent, cent) + rng.uniform(-0.2e-3, 0.2e-3))
        if same_codes:
            sb, ob, gb = sa, oa, ga
        ca = 2048 + oa + sa * v
        cb = 2048 + ob + sb * v
        # the MCP's read of the AWG node (INL 7 ppm x 6 V and noise, referred through the k = 1/2 sense divider):
        # COMMON to both channels, since both are fitted against the same reading
        # mcp_e: the precision ADC's INL referred to the AWG node (its INL at its pin / k); per point (powercal's form),
        # or with mcp_bow a smooth S-bow of that amplitude over the AWG span (a systematic slope error, does not average)
        if mcp_bow:
            x = v / max(abs(v).max(), 1e-12)
            vr = v + rng.choice((-1.0, 1.0)) * mcp_e * 2.598 * (x ** 3 - x) + rng.normal(0, 2.4e-6, npts)
        else:
            vr = v + (rng.uniform(-mcp_e, mcp_e, npts) + rng.normal(0, 2.4e-6, npts) if mcp else 0.0)
        if model == "pt":
            ia, ib = rng.uniform(-A, A, npts), rng.uniform(-A, A, npts)
        else:
            ia, ib = f_a(ca), f_b(cb)
        ma = ca + ia + rng.normal(0, NOISE / math.sqrt(navg), npts)
        mb = cb + ib + rng.normal(0, NOISE / math.sqrt(navg), npts)
        X = np.vstack([vr, np.ones(npts)]).T
        ea[i] = np.linalg.lstsq(X, ma, rcond=None)[0][0] / sa - 1
        eb[i] = np.linalg.lstsq(X, mb, rcond=None)[0][0] / sb - 1
    d = ea - eb
    return dict(abs=float(np.percentile(np.abs(np.r_[ea, eb]), 99.9) * 100), ratio=float(np.percentile(np.abs(d), 99.9) * 100),
                ratio_sd=float(np.std(d) * 100), abs_sd=float(np.std(np.r_[ea, eb]) * 100), span_codes=float(np.ptp(ca)))


def end_error(vt, rng_name, model, A, npts=64, N=4000, seed=2):
    """Smooth-bow models: the reading error at the range's end (+-5 V or +-1.25 V input) after the fit, as a
    fraction of the reading, 99.9th percentile.  The INL at the end is the converter's either way; what the fit adds
    is the extrapolation of the local slope.  Reported as (with the fit, with an exact slope)."""
    rng = np.random.default_rng(seed)
    vend = 5.0 if rng_name == "5" else 1.25
    g = 1.025 if rng_name == "5" else G125
    s = CPV * ALPHA * g
    v = np.linspace(-vt, vt, npts)
    e_fit, e_ex = [], []
    for _ in range(N):
        f = inl_fn(model, A, 8, rng)
        c = 2048 + s * v
        m = c + f(c)
        sl, ic = np.polyfit(v, m, 1)
        for ve in (vend, -vend):
            ce = 2048 + s * ve
            read = (ce + f(ce) - ic) / sl
            e_fit.append(abs(read / ve - 1))
            e_ex.append(abs((ce + f(ce) - 2048) / s / ve - 1))
    return float(np.percentile(e_fit, 99.9) * 100), float(np.percentile(e_ex, 99.9) * 100)


def c3e_reference(npts=64, N=20000, seed=3, A=1.2):
    """powercal C3-e's +-5 V row with its own inputs (DAC0 0.58-2.77 V at N, stage gain 1, INL 'pt' 1.2 LSB):
    the model above must reproduce 0.036 % before its tee figures are believed."""
    rng = np.random.default_rng(seed)
    ge = []
    for _ in range(N):
        vdx = np.linspace(0.58, 2.77, npts)
        v_read = vdx + rng.uniform(-42e-6, 42e-6, npts) + rng.normal(0, 1.2e-6, npts)
        a = 4095 / 3.3 * (1 + rng.uniform(-0.0156, 0.0029)); b = rng.uniform(-30, 56)
        code = a * (vdx - 1.65) + a * 1.65 + b + rng.uniform(-A, A, npts) + rng.normal(0, NOISE / math.sqrt(NAVG), npts)
        X = np.vstack([v_read - 1.65, np.ones(npts)]).T
        sl = np.linalg.lstsq(X, code, rcond=None)[0][0]
        ge.append(abs(sl / a - 1))
    return float(np.percentile(ge, 99.9) * 100)
