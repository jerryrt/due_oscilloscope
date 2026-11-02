"""Equivalent-time sampling (ETS) for the H7 loopback: DAC out, CH2 in.

The DAC update clock (TIM6) and the ADC trigger (TIM3) both count the same 200 MHz base. A waveform that
repeats every W = ppc * update_ticks ticks, observed by an ADC that samples every P_a ticks, is sampled
at phases (k * P_a) mod W. If P_a/g is coprime to W/g those phases visit every g-tick bin in W/g
samples, so the host can rebuild one cycle at g ticks (g x 5 ns) however slow the ADC is. The two timers
start at unrelated moments and the ADC adds a fixed conversion delay, so the result is known only up
to a constant circular shift; `align` removes it against the expected waveform.

What this cannot do: it assumes the waveform is repeatable (no drift, no noise that depends on phase),
that the capture has no gaps (checked from the frame sequence numbers), and it cannot see anything the
observer's own input stage removes. The bin width g is a property of how the ADC samples its trigger,
not of the maths; docs/15 measures it.
"""
import math
import struct
import zlib

import numpy as np

TICK_NS = 5.0                       # 200 MHz base


def plan(update_ticks, ppc, p_a_min=100, g=None):
    """Pick the ADC sample period. W = ppc*update_ticks; g = the largest of 8, 4, 2, 1 that divides W
    (or the one given); P_a is the smallest multiple of g, >= p_a_min, with gcd(P_a/g, W/g) == 1."""
    W = ppc * update_ticks
    if g is None:
        g = next(c for c in (8, 4, 2, 1) if W % c == 0)
    if W % g:
        raise ValueError(f"g={g} does not divide W={W}")
    m = -(-p_a_min // g)
    while math.gcd(m, W // g) != 1:
        m += 1
    return dict(W=W, g=g, p_a=m * g, bins=W // g)


def gapless_samples(data):
    """Parse version-4 frames (single-channel payload) and return the samples of the longest run of
    consecutive sequence numbers as float64, so sample k is exactly k trigger periods after sample 0."""
    runs, cur, last = [], [], None
    pos = data.find(b"DUE0")
    while pos >= 0 and pos + 4096 <= len(data):
        h = data[pos:pos + 32]
        if zlib.crc32(h[:28]) & 0xFFFFFFFF != struct.unpack("<I", h[28:])[0]:
            pos = data.find(b"DUE0", pos + 1); continue
        seq = struct.unpack("<I", h[8:12])[0]
        if last is not None and seq != last + 1:
            runs.append(cur); cur = []
        cur.append(np.frombuffer(data[pos + 32:pos + 4096], dtype="<u2"))
        last = seq; pos += 4096
    runs.append(cur)
    best = max(runs, key=len)
    return np.concatenate(best).astype(np.float64) if best else np.zeros(0)


def reconstruct(v, p_a, W, g, k0=0):
    """Bin the samples by phase. Returns (wave, counts): one value per g-tick bin, NaN where no sample fell.
    k0 is the index of v[0] in the capture, so a part of a capture keeps the phase it had in the whole."""
    k = np.arange(len(v), dtype=np.int64) + k0
    b = ((k * p_a) % W) // g
    n = W // g
    counts = np.bincount(b, minlength=n)
    sums = np.bincount(b, weights=v, minlength=n)
    with np.errstate(invalid="ignore", divide="ignore"):
        wave = sums / counts
    return wave, counts


def align(wave, expected):
    """Circular shift of `wave` that best matches `expected` (same length, NaN-tolerant). Returns (shift, aligned)."""
    w = np.where(np.isnan(wave), np.nanmean(wave), wave); e = np.asarray(expected, dtype=float)
    w = w - w.mean(); e = e - e.mean()
    xc = np.fft.irfft(np.fft.rfft(w) * np.conj(np.fft.rfft(e)), n=len(w))
    s = int(np.argmax(xc))
    return s, np.roll(wave, -s)


def integrity(v, p_a, W, g, rel_limit=0.002, sigma_factor=4.0):
    """Check that a capture is a repeatable waveform sampled at the phases we think, before any metric is read from it.

    The capture is rebuilt twice, from its first and its second half (each keeping its true sample indices). For a
    repeatable signal and the right phase mapping the two differ only by noise: rms(half1 - half2) is about
    sigma * sqrt(2 / n) per bin, with sigma the per-sample scatter about the full rebuild. A phase discontinuity
    (a lost trigger or frame that the sequence numbers did not show), drift, or a signal that is not repeatable makes
    them differ by much more. Returns a dict; `ok` is False with `reason` when they do.
    """
    n = len(v); half = n // 2
    full, counts = reconstruct(v, p_a, W, g)
    b = (((np.arange(n, dtype=np.int64) * p_a) % W) // g)
    resid = v - full[b]
    sigma = float(np.std(np.diff(resid)) / math.sqrt(2.0))      # consecutive-sample scatter: slow drift cancels, noise does not
    a1, c1 = reconstruct(v[:half], p_a, W, g, 0); a2, c2 = reconstruct(v[half:], p_a, W, g, half)
    both = ~np.isnan(a1) & ~np.isnan(a2)
    if both.sum() < 0.9 * len(full):
        return dict(ok=False, reason="halves cover under 90 % of the bins", half_rms=float("nan"), sigma=sigma)
    d = a1[both] - a2[both]; rms = float(np.sqrt(np.mean(d ** 2)))
    n_bin = float(np.median(c1[both])); expect = sigma * math.sqrt(2.0 / max(n_bin, 1.0))
    span = float(np.nanmax(full) - np.nanmin(full))
    limit = max(sigma_factor * expect, rel_limit * span)
    ok = rms <= limit
    return dict(ok=ok, reason="" if ok else f"halves differ by {rms*1000:.1f} mV rms, noise alone would give {expect*1000:.1f} mV",
                half_rms=rms, expected=expect, sigma=sigma, min_count=int(counts.min()))
