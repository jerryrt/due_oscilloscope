"""The period of a known pattern from a source with a clock of its own.

Equivalent-time folding needs the waveform's period in ADC timer ticks.
When the source shares the ADC's master clock the period is an exact
integer (`eqtime.period_ticks`). A second board's DAC has a clock of its
own: its period is not an integer, and it differs from the nominal one by
tens of ppm that no table gives.

The pattern is known, so the unknown is one number, the clock ratio. Each
short block of samples is matched against the pattern's ideal waveform to
find where in the pattern it falls; that phase moves linearly with time at
a rate equal to the ratio's error, and a line fitted through the phases of
blocks spread over the whole capture reads it to about a part per billion.

Two crystals do not hold a ratio: it moves by a fraction of a ppm over
minutes, and over a 16 s capture that is half a tick or more of phase
curvature, far more than the fold's own repeatability. The phase is
therefore fitted as a smooth curve, not a line, with the degree chosen by
BIC, and the fit is judged: the scatter about it must match the noise of the
block matches themselves, or the capture is reported as not adequately
modelled and nothing downstream should trust a fold on it.

A search that scores whole-capture folds on candidate periods was tried
first and does not work here: a fold on bins as wide as a symbol cannot
tell a period that is 8 ticks out by the end of its window from the right
one, because a flat top hides the error, so each stage's pick is noise and
the next stage starts from the wrong place.

Pure Python on purpose: the venv carries no numpy.
"""
import math

#: Largest common factor of the ADC RC and the pattern period that block
#: matching tolerates. The samples then land only on every `gcd`-th source
#: tick, and at 4 the matches of a short block degrade from about 0.2 ticks
#: of scatter to 1.1, with correlated residuals that read as a bad model.
MAX_LATTICE_GCD = 2

#: A block is taken as the pattern when its best correlation, as a share of
#: the most a perfect match could give, is at least this. A block of idle
#: level or of a different signal scores near 0; a matched one near 1.
MIN_SCORE = 0.5
#: Blocks tried for the first, global match before giving up.
MAX_FIRST_TRIES = 12
#: A block whose mean distance from the capture's mean level, in units of
#: half the capture's span, is below this is idle and needs no search.
IDLE_SHARE = 0.3


def template(bits, rc_dac):
    """The ideal NRZ waveform over one pattern, one entry per source tick."""
    return [1.0 if b else -1.0 for b in bits for _ in range(rc_dac)]


def _corr(win, xs, tmpl, period, phi):
    """Sum of sample * template at the whole-tick phase `phi`."""
    acc = 0.0
    for v, x in zip(win, xs):
        acc += v * tmpl[int((x + phi) % period)]
    return acc


def _best_phase(win, xs, tmpl, period, lo, hi, step=1.0):
    """The phase in [lo, hi) with the highest correlation, to a sub-tick.

    The correlation is taken at whole-tick shifts, one tick apart, and the
    peak read from a least squares parabola through its top five points.
    Samples sit on whole ticks, so the correlation between whole-tick shifts
    is piecewise linear and its maximum is always at one of them; reading a
    fraction off the two neighbours with a triangle formula leaves a bias that
    depends on where the true phase sits within the tick, a sawtooth of about
    0.4 ticks that a smooth fit through the points removes (0.57 ticks of
    block scatter on data with perfect timing against 0.2).
    """
    lo, hi = float(math.floor(lo + 0.5)), float(math.floor(hi + 0.5))
    n = int(round((hi - lo) / step))
    cs = [_corr(win, xs, tmpl, period, lo + i * step) for i in range(n)]
    i = max(range(n), key=cs.__getitem__)
    on_edge = i < 2 or i >= n - 2
    frac = 0.0
    if not on_edge:
        y = cs[i - 2:i + 3]
        b1 = (-2 * y[0] - y[1] + y[3] + 2 * y[4]) / 10.0
        a2 = ((4 * y[0] + y[1] + y[3] + 4 * y[4]) - 2 * sum(y)) / 14.0
        if a2 < 0:
            frac = max(-1.0, min(1.0, -b1 / (2 * a2)))
    return lo + (i + frac) * step, cs[i], on_edge


MAX_DEGREE = 6
#: The residuals of an adequate model look like noise: neighbouring ones
#: are not correlated, and none is far outside the rest. A smooth curve
#: through a jump leaves a run of one sign and a few large ones.
RHO_MAX = 0.35
OUTLIER_SIGMA = 6.0
#: More dropped blocks than this share of them is not a few bad matches.
MAX_OUTLIER_SHARE = 0.05
#: Samples per linear segment when a model is evaluated along a capture.
SEGMENT = 2048


def _solve(a, b):
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for c in range(n):
        piv = max(range(c, n), key=lambda r: abs(m[r][c]))
        m[c], m[piv] = m[piv], m[c]
        for r in range(c + 1, n):
            f = m[r][c] / m[c][c]
            for k in range(c, n + 1):
                m[r][k] -= f * m[c][k]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        x[r] = (m[r][n] - sum(m[r][k] * x[k] for k in range(r + 1, n))) / m[r][r]
    return x


def _polyfit(ts, ys, deg):
    pw = [sum(t ** k for t in ts) for k in range(2 * deg + 1)]
    a = [[pw[i + j] for j in range(deg + 1)] for i in range(deg + 1)]
    b = [sum(y * t ** i for t, y in zip(ts, ys)) for i in range(deg + 1)]
    return _solve(a, b)


def _horner(coef, t):
    v = 0.0
    for c in reversed(coef):
        v = v * t + c
    return v


def fit_phase(pts):
    """A smooth phase curve through `(x, phase)` block matches.

    Returns `{coef, xmid, xhalf, degree, rms, rms_linear, wander_ptp}`:
    `rms` is the scatter about the chosen curve, `rms_linear` about a line,
    `wander_ptp` the peak-to-peak of the chosen curve above its own
    straight-line part in ticks, `rho1` the correlation of neighbouring
    residuals, `outliers` the blocks dropped as bad matches, and
    `sigma_model` the curve's own standard error in ticks: how well the
    time axis of a fold on it is known, whatever the bin width.
    """
    xs = [p[0] for p in pts]
    xmid, xhalf = (xs[0] + xs[-1]) / 2.0, (xs[-1] - xs[0]) / 2.0 or 1.0
    ts = [(x - xmid) / xhalf for x in xs]
    ys = [p[1] for p in pts]
    n = len(pts)
    best = None
    rss_by = {}
    for deg in range(1, MAX_DEGREE + 1):
        coef = _polyfit(ts, ys, deg)
        rss = sum((y - _horner(coef, t)) ** 2 for t, y in zip(ts, ys))
        rss_by[deg] = rss
        bic = n * math.log(rss / n + 1e-12) + (deg + 1) * math.log(n)
        if best is None or bic < best[0]:
            best = (bic, deg, coef)
    _, deg, coef = best
    # A block that matches badly is an outlier to drop, not a feature of the
    # clock: refit without the ones far outside the rest, a few passes at most.
    keep = list(range(n))
    for _ in range(3):
        res = [ys[i] - _horner(coef, ts[i]) for i in keep]
        sig = 1.4826 * sorted(abs(r) for r in res)[len(res) // 2] or 1e-12
        kept = [i for i, r in zip(keep, res) if abs(r) <= OUTLIER_SIGMA * sig]
        if len(kept) == len(keep) or len(kept) < 8:
            break
        keep = kept
        coef = _polyfit([ts[i] for i in keep], [ys[i] for i in keep], deg)
    res = [ys[i] - _horner(coef, ts[i]) for i in keep]
    nk = len(keep)
    ss = sum(r * r for r in res) or 1e-12
    rho1 = sum(a * b for a, b in zip(res, res[1:])) / ss
    rms_k = math.sqrt(ss / nk)
    lin = _polyfit(ts, ys, 1)
    grid = [i / 100.0 * 2 - 1 for i in range(101)]
    resid = [_horner(coef, t) - _horner(lin, t) for t in grid]
    return {"coef": coef, "xmid": xmid, "xhalf": xhalf, "degree": deg,
            "rms": rms_k, "rms_linear": math.sqrt(rss_by[1] / n),
            "wander_ptp": max(resid) - min(resid), "rho1": rho1,
            "sigma_model": rms_k * math.sqrt((deg + 1) / nk),
            "outliers": n - nk}


def phase_at(model, x):
    return _horner(model["coef"], (x - model["xmid"]) / model["xhalf"])


def block_noise(pts, consecutive):
    """Scatter of a block match, from second differences of neighbours."""
    ph = [p[1] for p in pts[:consecutive]]
    if len(ph) < 6:
        return None
    d2 = [ph[i + 1] - 2 * ph[i] + ph[i - 1] for i in range(1, len(ph) - 1)]
    return math.sqrt(sum(d * d for d in d2) / len(d2) / 6.0)


def phase_indices(n, rc_adc, model, period, k=1, start=0):
    """Fold bin of each of `n` samples on the fitted phase curve.

    The bin is `k` per source tick over a pattern of `period` ticks, so the
    result runs 0 to `period * k - 1`. The curve is evaluated at the ends of
    segments of `SEGMENT` samples and followed linearly between them.
    """
    nb = period * k
    i = 0
    while i < n:
        m = min(SEGMENT, n - i)
        x0 = (start + i) * rc_adc
        x1 = (start + i + m) * rc_adc
        p0 = x0 + phase_at(model, x0)
        dp = (x1 + phase_at(model, x1) - p0) / m
        u = p0 % period
        for _ in range(m):
            yield int(u * k) % nb
            u += dp
            if u >= period:
                u -= period
            elif u < 0:
                u += period
        i += m


def fold_warped(vals, rc_adc, model, period, k=1, start=0):
    """Mean per bin on the fitted phase curve: `(curve, counts)`."""
    nb = period * k
    acc = [0.0] * nb
    cnt = [0] * nb
    for v, i in zip(vals, phase_indices(len(vals), rc_adc, model, period, k, start)):
        acc[i] += v
        cnt[i] += 1
    return [a / c if c else None for a, c in zip(acc, cnt)], cnt


def is_adequate(model, nblocks, lattice):
    """Whether a fitted phase curve can be trusted for a fold."""
    return (abs(model["rho1"]) <= RHO_MAX
            and model["outliers"] <= MAX_OUTLIER_SHARE * nblocks
            and lattice <= MAX_LATTICE_GCD)


def track_clock_ratio(vals, rc_adc, bits, rc_dac, start=0, block=150,
                      first_blocks=40, stride=20, window=8.0):
    """Clock-ratio error of the source, from `vals`.

    `vals[0]` is sample number `start` of the run, so sample `k` is at tick
    `k * rc_adc` of the ADC's clock. Returns `{delta, period, blocks, rms,
    edge_hits}`: `delta` is the source's period over the nominal one minus
    1, `period` the period in ADC ticks, `rms` the scatter of the block
    phases about the fitted line in ticks, and `edge_hits` how many block
    matches landed on the edge of their search window (a sign the window
    was too narrow, and the fit should not be trusted). `skipped` counts
    the blocks that did not look like the pattern and were left out, and
    `lattice_gcd` is the common factor of the ADC RC and the period, which
    must not exceed `MAX_LATTICE_GCD` for the capture to count as modelled.
    """
    period = len(bits) * rc_dac
    lattice = math.gcd(int(round(rc_adc)), period)
    tmpl = template(bits, rc_dac)
    mean = sum(vals) / len(vals)
    amp = (max(vals) - min(vals)) / 2.0 or 1.0
    cen = [(v - mean) / amp for v in vals]
    pts = []                                   # (x of block centre, unwrapped phase)
    edge = skipped = 0
    j = 0
    nblk = len(vals) // block
    while j < nblk:
        i0 = j * block
        win = cen[i0:i0 + block]
        xs = [(start + i0 + i) * rc_adc for i in range(block)]
        xm = (start + i0 + block // 2) * rc_adc
        den = sum(abs(v) for v in win) or 1.0
        if not pts:
            if den < IDLE_SHARE * block:
                skipped += 1
                j += 1
                continue
            phi, c, _ = _best_phase(win, xs, tmpl, period, 0.0, float(period), 1.0)
            if c / den < MIN_SCORE:
                skipped += 1
                if skipped >= MAX_FIRST_TRIES:
                    raise ValueError(
                        "no block in the first %d looked like the pattern"
                        % MAX_FIRST_TRIES)
                j += 10
                continue
        else:
            if len(pts) >= 3:
                sl = _slope(pts)
                pred = pts[-1][1] + sl * (xm - pts[-1][0])
            else:
                pred = pts[-1][1]
            phi, c, hit = _best_phase(win, xs, tmpl, period, pred - window,
                                      pred + window, 1.0)
            if c / den < MIN_SCORE:
                skipped += 1
                j += stride
                continue
            edge += hit
        pts.append((xm, phi))
        j += 1 if len(pts) < first_blocks else stride
    if len(pts) < 8:
        raise ValueError("fewer than 8 blocks looked like the pattern: "
                         "%d of %d" % (len(pts), nblk))
    sl = _slope(pts)
    fit = _fit(pts)
    rms = math.sqrt(sum((y - (fit[0] + fit[1] * x)) ** 2 for x, y in pts) / len(pts))
    model = fit_phase(pts)
    noise = block_noise(pts, first_blocks)
    adequate = is_adequate(model, len(pts), lattice)
    # The source's phase in ticks is x / (1 + delta), so against the ADC's
    # ticks it falls at -delta / (1 + delta) per tick.
    delta = -sl / (1.0 + sl)
    return {"delta": delta, "period": period * (1.0 + delta), "blocks": len(pts),
            "rms": rms, "edge_hits": edge,
            "skipped": skipped, "model": model, "points": pts, "block_noise": noise,
            "lattice_gcd": lattice,
            "adequate": adequate}


def _fit(pts):
    n = len(pts)
    mx = sum(p[0] for p in pts) / n
    my = sum(p[1] for p in pts) / n
    sxx = sum((p[0] - mx) ** 2 for p in pts)
    b = sum((p[0] - mx) * (p[1] - my) for p in pts) / sxx if sxx else 0.0
    return my - b * mx, b


def _slope(pts):
    if len(pts) < 2 or pts[-1][0] == pts[0][0]:
        return 0.0
    return _fit(pts)[1]


def fold_scaled(vals, rc_adc, period, bins, start=0):
    """Mean per bin of a fold on a non-integer `period`.

    `bins` bins span one period, so a bin is `period / bins` ticks of the
    ADC's clock. With `bins` = `L * rc_dac` that is one tick of the
    *source's* clock, which is the axis `ets_phase0.analyze` reads.
    Returns `(curve, counts)`; a bin nothing landed in is None.
    """
    acc = [0.0] * bins
    cnt = [0] * bins
    scale = bins / period
    step = rc_adc % period
    ph = (start * rc_adc) % period
    for v in vals:
        i = int(ph * scale)
        if i >= bins:
            i = bins - 1
        acc[i] += v
        cnt[i] += 1
        ph += step
        if ph >= period:
            ph -= period
    return [a / c if c else None for a, c in zip(acc, cnt)], cnt
