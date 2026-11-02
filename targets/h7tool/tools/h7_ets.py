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


def reconstruct(v, p_a, W, g):
    """Bin the samples by phase. Returns (wave, counts): one value per g-tick bin, NaN where no sample fell."""
    k = np.arange(len(v), dtype=np.int64)
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
