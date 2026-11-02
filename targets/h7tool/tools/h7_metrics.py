"""Waveform metrics for the H7 AWG measurements, kept out of the sweep script so they can be tested.

All of them take a waveform rebuilt by h7_ets.reconstruct (one cycle, circular, arbitrary start, NaN where no
sample fell) and say when they cannot give an answer, instead of returning a number: an edge that is not
resolved at the bin width, or a plateau that is not there, is reported invalid with the reason.
"""
import numpy as np

TICK_NS = 5.0


def fill_nan(w):
    """Circular linear interpolation over empty bins (a few at most; reconstruct reports the counts)."""
    w = np.asarray(w, dtype=float).copy(); bad = np.isnan(w)
    if bad.all():
        raise ValueError("no samples in any bin")
    if bad.any():
        x = np.arange(len(w)); w[bad] = np.interp(x[bad], x[~bad], w[~bad], period=len(w))
    return w


def sine_metrics(wave, harmonics=5):
    """Fundamental peak, mean and the harmonic content (2nd..nth, root-sum-square over the fundamental)."""
    w = fill_nan(wave); F = np.abs(np.fft.rfft(w)) * 2 / len(w)
    top = min(harmonics + 1, len(F))
    return dict(amp=float(F[1]), mean=float(w.mean()), thd=float(np.sqrt(np.sum(F[2:top] ** 2)) / F[1]) if F[1] > 0 else float("nan"),
                lo=float(w.min()), hi=float(w.max()))


def _walk(w, centre, level, step):
    """From `centre`, step by +-1 (circularly) until the waveform crosses `level`; return the distance in bins."""
    n = len(w); i = centre; k = 0
    cond = (lambda v: v > level) if step < 0 else (lambda v: v < level)        # rising edge: before it, w<=t10; after, w>=t90
    return i, k, cond


def _edge_bins(w, centre, t_lo, t_hi, rising):
    """Bins between the last point at/below t_lo and the first at/above t_hi around an edge centre (swapped for falling)."""
    n = len(w); a, b = (t_lo, t_hi) if rising else (t_hi, t_lo)
    # walk back to the start level, forward to the end level
    i = centre; k = 0
    while (w[i % n] > a if rising else w[i % n] < a) and k < n // 2:
        i -= 1; k += 1
    start = i
    j = centre; k = 0
    while (w[j % n] < b if rising else w[j % n] > b) and k < n // 2:
        j += 1; k += 1
    return j - start, start % n, j % n


def edge_metrics(wave, g, min_edge_bins=3):
    """Levels, 10-90 % rise and fall (ns), overshoot. `valid` is False, with `reason`, when the result cannot be trusted:
    no two clear plateaus, an edge narrower than min_edge_bins bins (unresolved at this binning), or a rise and a
    fall that differ by more than 2x."""
    w = fill_nan(wave); n = len(w)
    p5, p95 = np.percentile(w, 5), np.percentile(w, 95); mid = (p5 + p95) / 2
    lo, hi = float(np.median(w[w < mid])), float(np.median(w[w >= mid])); span = hi - lo
    out = dict(lo=lo, hi=hi, span=span, valid=False, reason="")
    if span <= 0 or (w < mid).sum() < n // 8 or (w >= mid).sum() < n // 8:
        out["reason"] = "no two plateaus"; return out
    t10, t90 = lo + 0.1 * span, lo + 0.9 * span
    d = np.roll(w, -1) - w; ds = np.convolve(np.concatenate([d[-1:], d, d[:1]]), np.ones(3) / 3, mode="valid")
    rc, fc = int(np.argmax(ds)), int(np.argmin(ds))
    rb, rs, re_ = _edge_bins(w, rc, t10, t90, True); fb, fs_, fe = _edge_bins(w, fc, t10, t90, False)
    out["rise_ns"] = rb * g * TICK_NS; out["fall_ns"] = fb * g * TICK_NS
    after = np.concatenate([w[re_:], w[:re_]])[: max(8, n // 4)]
    out["overshoot_pct"] = float(100 * max(0.0, after.max() - hi) / span)
    if rb < min_edge_bins or fb < min_edge_bins:
        out["reason"] = f"edge unresolved ({rb} / {fb} bins; need >= {min_edge_bins})"; return out
    if not 0.5 <= rb / fb <= 2.0:
        out["reason"] = f"rise {out['rise_ns']:.0f} ns and fall {out['fall_ns']:.0f} ns differ by more than 2x"; return out
    out["valid"] = True
    return out
