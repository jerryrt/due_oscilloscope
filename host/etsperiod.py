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

A search that scores whole-capture folds on candidate periods was tried
first and does not work here: a fold on bins as wide as a symbol cannot
tell a period that is 8 ticks out by the end of its window from the right
one, because a flat top hides the error, so each stage's pick is noise and
the next stage starts from the wrong place.

Pure Python on purpose: the venv carries no numpy.
"""
import math

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
    """Sum of sample * template at the phase `phi`, samples at ticks `xs`."""
    acc = 0.0
    for v, x in zip(win, xs):
        acc += v * tmpl[int((x + phi) % period)]
    return acc


def _best_phase(win, xs, tmpl, period, lo, hi, step):
    """The phase in [lo, hi) with the highest correlation, to a sub-step.

    The correlation of an NRZ pattern with itself falls linearly either
    side of its peak, so the two flanks are extended to where they meet.
    """
    n = int(round((hi - lo) / step))
    cs = [_corr(win, xs, tmpl, period, lo + i * step) for i in range(n)]
    i = max(range(n), key=cs.__getitem__)
    on_edge = i in (0, n - 1)
    frac = 0.0
    if not on_edge:
        left, mid, right = cs[i - 1], cs[i], cs[i + 1]
        rise = mid - min(left, right)
        if rise > 0:
            frac = 0.5 * (right - left) / rise
    return lo + (i + frac) * step, cs[i], on_edge


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
    the blocks that did not look like the pattern and were left out.
    """
    period = len(bits) * rc_dac
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
                                      pred + window, 0.5)
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
    # The source's phase in ticks is x / (1 + delta), so against the ADC's
    # ticks it falls at -delta / (1 + delta) per tick.
    delta = -sl / (1.0 + sl)
    return {"delta": delta, "period": period * (1.0 + delta), "blocks": len(pts),
            "rms": rms, "edge_hits": edge,
            "skipped": skipped}


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
