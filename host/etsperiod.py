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

The work is numpy array operations (`dsp`); there is no pure-Python path
behind it, and `tests/test_etsperiod.py` holds it to clocks known by construction.
"""
import math

import numpy as np

import dsp

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


def template(bits, rc_dac, levels=2):
    """The ideal staircase over one pattern, one entry per source tick.

    `bits` holds the level index of each symbol, 0 to `levels - 1`, and the
    template runs from -1 for level 0 to +1 for the top level.
    """
    top = float(levels - 1)
    return (2.0 * np.asarray(bits, dtype=np.float64) / top - 1.0).repeat(rc_dac)


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
    if n >= dsp.SCAN_MIN and step == 1.0 and n <= period:
        cs = dsp.corr_scan(win, xs, tmpl, period, lo, n)     # whole-tick phases
    else:
        cs = np.asarray(dsp.corr_many(win, xs, tmpl, period,
                                      [lo + i * step for i in range(n)]))
    i = int(cs.argmax())
    on_edge = i < 2 or i >= n - 2
    frac = 0.0
    if not on_edge:
        y = cs[i - 2:i + 3]
        b1 = (-2 * y[0] - y[1] + y[3] + 2 * y[4]) / 10.0
        a2 = ((4 * y[0] + y[1] + y[3] + 4 * y[4]) - 2 * y.sum()) / 14.0
        if a2 < 0:
            frac = max(-1.0, min(1.0, -b1 / (2 * a2)))
    return lo + (i + frac) * step, float(cs[i]), on_edge


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


def _horner(coef, t):
    v = 0.0
    for c in reversed(coef):
        v = v * t + c
    return v


def _polyfit(ts, ys, deg):
    """Least-squares polynomial of degree `deg`, lowest coefficient first."""
    return np.polyfit(ts, ys, deg)[::-1].tolist()


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
    p = np.asarray(pts, dtype=np.float64)
    xs, ys = p[:, 0], p[:, 1]
    xmid, xhalf = (xs[0] + xs[-1]) / 2.0, (xs[-1] - xs[0]) / 2.0 or 1.0
    ts = (xs - xmid) / xhalf
    n = len(ys)
    best = None
    rss_by = {}
    for deg in range(1, MAX_DEGREE + 1):
        coef = _polyfit(ts, ys, deg)
        rss = float(((ys - _horner(coef, ts)) ** 2).sum())
        rss_by[deg] = rss
        bic = n * math.log(rss / n + 1e-12) + (deg + 1) * math.log(n)
        if best is None or bic < best[0]:
            best = (bic, deg, coef)
    _, deg, coef = best
    # A block that matches badly is an outlier to drop, not a feature of the
    # clock: refit without the ones far outside the rest, a few passes at most.
    keep = np.arange(n)
    for _ in range(3):
        res = ys[keep] - _horner(coef, ts[keep])
        sig = 1.4826 * np.sort(np.abs(res))[len(res) // 2] or 1e-12
        kept = keep[np.abs(res) <= OUTLIER_SIGMA * sig]
        if len(kept) == len(keep) or len(kept) < 8:
            break
        keep = kept
        coef = _polyfit(ts[keep], ys[keep], deg)
    res = ys[keep] - _horner(coef, ts[keep])
    nk = len(keep)
    ss = float((res * res).sum()) or 1e-12
    rho1 = float((res[:-1] * res[1:]).sum()) / ss
    rms_k = math.sqrt(ss / nk)
    lin = _polyfit(ts, ys, 1)
    grid = np.arange(101) / 100.0 * 2 - 1
    resid = _horner(coef, grid) - _horner(lin, grid)
    return {"coef": coef, "xmid": float(xmid), "xhalf": float(xhalf), "degree": deg,
            "rms": rms_k, "rms_linear": math.sqrt(rss_by[1] / n),
            "wander_ptp": float(resid.max() - resid.min()), "rho1": rho1,
            "sigma_model": rms_k * math.sqrt((deg + 1) / nk),
            "outliers": int(n - nk)}


def phase_at(model, x):
    """The fitted phase at `x`, a number or an array."""
    return _horner(model["coef"], (x - model["xmid"]) / model["xhalf"])


def block_noise(pts, consecutive):
    """Scatter of a block match, from second differences of neighbours."""
    ph = np.asarray([p[1] for p in pts[:consecutive]], dtype=np.float64)
    if len(ph) < 6:
        return None
    d2 = ph[2:] - 2 * ph[1:-1] + ph[:-2]
    return math.sqrt(float((d2 * d2).mean()) / 6.0)


def fold_warped(vals, rc_adc, model, period, k=1, start=0):
    """Mean per bin on the fitted phase curve: `(curve, counts)`."""
    nb = period * k
    v = np.asarray(vals)

    def part(a, b):
        acc = np.zeros(nb)
        cnt = np.zeros(nb, dtype=np.int64)
        for i in range(a, b, dsp.CHUNK):                     # small chunks stay in cache
            m = min(dsp.CHUNK, b - i)
            idx = dsp.phase_indices(m, rc_adc, lambda x: phase_at(model, x),
                                    period, k, start + i, SEGMENT)
            acc += np.bincount(idx, weights=v[i:i + m].astype(np.float64), minlength=nb)
            cnt += np.bincount(idx, minlength=nb)
        return acc, cnt
    parts = dsp.map_ranges(part, len(v), SEGMENT)
    acc = sum(p[0] for p in parts)
    cnt = sum(p[1] for p in parts)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = acc / cnt
    return ([None if c == 0 else m for m, c in zip(mean.tolist(), cnt.tolist())],
            cnt.tolist())


def is_adequate(model, nblocks, lattice):
    """Whether a fitted phase curve can be trusted for a fold."""
    return bool(abs(model["rho1"]) <= RHO_MAX
                and model["outliers"] <= MAX_OUTLIER_SHARE * nblocks
                and lattice <= MAX_LATTICE_GCD)


#: Blocks between the coarse pass's matches, which predict the batched pass.
COARSE_STRIDE = 400
#: Blocks refined per numpy call; the index tensor is `chunk x 2 * window x block`.
BATCH_CHUNK = 256


def _blocks_batched(cen, absum, tmpl, period, coarse, start, block, rc_adc,
                    first_blocks, stride, window):
    """The sequential tracker's block matches, all at once around a prediction.

    The sequential tracker is sequential only because each block is searched
    around the last block's phase. A coarse pass on every `COARSE_STRIDE`-th
    block gives a smooth curve that predicts every block's phase well inside
    the search window, so every block can be matched independently, in
    batches of array operations on threads. The blocks and the match are the
    sequential ones: the same schedule (the coarse pass's first block, then
    `first_blocks` in a row, then every `stride`-th), the same whole-tick
    correlation and the same parabola on its top five points.
    """
    nblk = len(absum)
    xm0 = coarse["points"][0][0]
    j0 = int((xm0 / rc_adc - start - block // 2) // block)
    js = np.concatenate([np.arange(j0, j0 + first_blocks),
                         np.arange(j0 + first_blocks - 1 + stride, nblk, stride)])
    js = js[js < nblk]
    xms = (start + js * block + block // 2) * rc_adc
    mdl = coarse["model"]
    pred = np.asarray(phase_at(mdl, xms.astype(np.float64)), dtype=np.float64)
    lo = np.floor(pred - window + 0.5).astype(np.int64)
    n = int(round(2 * window))
    off = np.arange(block, dtype=np.int64)
    ph = np.arange(n, dtype=np.int64)
    tm = np.asarray(tmpl, dtype=np.float64)
    cen_a = np.asarray(cen)

    def part(a, b):
        out_phi, out_c, out_edge = [], [], []
        for c0 in range(a, b, BATCH_CHUNK):
            c1 = min(c0 + BATCH_CHUNK, b)
            i0 = js[c0:c1] * block
            win = cen_a[i0[:, None] + off]                          # (b, block)
            xs = (start + i0)[:, None] * rc_adc + off * rc_adc      # whole ticks
            idx = (xs[:, None, :] + (lo[c0:c1, None] + ph)[:, :, None]) % period
            cs = np.einsum("bpk,bk->bp", tm[idx], win)
            i = cs.argmax(axis=1)
            edge = (i < 2) | (i >= n - 2)
            ic = np.clip(i, 2, n - 3)
            y = np.take_along_axis(cs, ic[:, None] + np.arange(-2, 3), axis=1)
            b1 = (-2 * y[:, 0] - y[:, 1] + y[:, 3] + 2 * y[:, 4]) / 10.0
            a2 = ((4 * y[:, 0] + y[:, 1] + y[:, 3] + 4 * y[:, 4]) - 2 * y.sum(axis=1)) / 14.0
            with np.errstate(divide="ignore", invalid="ignore"):
                frac = np.where((a2 < 0) & ~edge, np.clip(-b1 / (2 * a2), -1.0, 1.0), 0.0)
            out_phi.append(lo[c0:c1] + i + frac)
            out_c.append(cs[np.arange(c1 - c0), i])
            out_edge.append(edge)
        return np.concatenate(out_phi), np.concatenate(out_c), np.concatenate(out_edge)

    parts = dsp.map_ranges(part, len(js), BATCH_CHUNK)
    phi = np.concatenate([p[0] for p in parts])
    c = np.concatenate([p[1] for p in parts])
    edge = np.concatenate([p[2] for p in parts])
    den = np.where(absum[js] == 0, 1.0, absum[js])
    keep = c / den >= MIN_SCORE
    pts = list(zip(xms[keep].astype(float).tolist(), phi[keep].tolist()))
    return pts, int(edge[keep].sum()), int((~keep).sum())


def _finish(pts, edge, skipped, period, lattice, first_blocks, nblk):
    if len(pts) < 8:
        raise ValueError("fewer than 8 blocks looked like the pattern: "
                         "%d of %d" % (len(pts), nblk))
    p = np.asarray(pts, dtype=np.float64)
    b, a = np.polyfit(p[:, 0], p[:, 1], 1)
    sl = float(b)
    rms = math.sqrt(float(((p[:, 1] - (a + b * p[:, 0])) ** 2).mean()))
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


def track_clock_ratio(vals, rc_adc, bits, rc_dac, start=0, block=150,
                      first_blocks=40, stride=20, window=8.0, levels=2, batched=True):
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
    `batched` matches every block at once around a coarse curve, and falls back
    to the block-by-block search when a match lands on its window's edge.
    """
    period = len(bits) * rc_dac
    lattice = math.gcd(int(round(rc_adc)), period)
    tmpl = template(bits, rc_dac, levels)
    cen, mean, amp = dsp.center(vals)
    nb_all = len(vals) // block
    absum = np.empty(nb_all)                # per-block sums of |cen|, a slab at a time
    for a in range(0, nb_all, 4096):
        z = min(a + 4096, nb_all)
        absum[a:z] = np.abs(cen[a * block:z * block]).reshape(z - a, block).sum(axis=1)
    xs_off = np.arange(block) * rc_adc
    if batched:
        coarse = track_clock_ratio(vals, rc_adc, bits, rc_dac, start, block,
                                   first_blocks, COARSE_STRIDE, window, levels,
                                   batched=False)
        pts, edge, skipped = _blocks_batched(cen, absum, tmpl, period, coarse, start, block,
                                             rc_adc, first_blocks, stride, window)
        if edge == 0 and skipped == 0 and len(pts) >= 8:
            return _finish(pts, edge, skipped + coarse["skipped"], period, lattice,
                           first_blocks, len(vals) // block)
        # A match on the edge of its window, or a block that did not match,
        # means the coarse curve predicted badly: the sequential search follows
        # the phase block by block and decides what happens next.
    pts = []                                   # (x of block centre, unwrapped phase)
    line = _RunningLine()                      # the same line, kept as blocks arrive
    edge = skipped = 0
    j = 0
    nblk = len(vals) // block
    while j < nblk:
        i0 = j * block
        win = cen[i0:i0 + block]
        xm = (start + i0 + block // 2) * rc_adc
        xs = xs_off + (start + i0) * rc_adc
        den = float(absum[j]) or 1.0
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
                sl = line.slope()
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
        line.add(xm, phi)
        j += 1 if len(pts) < first_blocks else stride
    return _finish(pts, edge, skipped, period, lattice, first_blocks, nblk)


class _RunningLine:
    """Least-squares slope of the points added so far, in constant time per
    point: refitting every block from the list was quadratic."""

    def __init__(self):
        self.n = 0
        self.mx = self.my = self.sxx = self.sxy = 0.0

    def add(self, x, y):
        self.n += 1
        dx = x - self.mx
        self.mx += dx / self.n
        self.my += (y - self.my) / self.n
        self.sxx += dx * (x - self.mx)
        self.sxy += dx * (y - self.my)

    def slope(self):
        return self.sxy / self.sxx if self.sxx else 0.0


def fold_scaled(vals, rc_adc, period, bins, start=0):
    """Mean per bin of a fold on a non-integer `period`.

    `bins` bins span one period, so a bin is `period / bins` ticks of the
    ADC's clock. With `bins` = `L * rc_dac` that is one tick of the
    *source's* clock, which is the axis `ets_phase0.analyze` reads.
    Returns `(curve, counts)`; a bin nothing landed in is None.
    """
    return dsp.fold_scaled(vals, rc_adc, period, bins, start)
