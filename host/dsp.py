"""The ETS analysis's inner loops, with the backend chosen at run time.

`etsperiod` keeps its pure-Python code as the reference. This module holds
the same three computations vectorised: the correlation of a block against
the pattern at many phases, the fold on a non-integer period, and the fold
on a fitted phase curve. `tests/test_dsp_equivalence.py` holds each one to
the reference.

Backends, by `DUE_DSP`: `python` runs the reference, `numpy` the vectorised
code, and unset or `auto` takes numpy when it imports and the reference
otherwise. `cuda` is accepted only where pycuda imports and a device
answers, and no CUDA kernel exists yet: asking for it raises, rather than
quietly running something else.
"""
import os

try:
    import numpy as np
except ImportError:
    np = None


class BackendUnavailable(RuntimeError):
    pass


def _cuda_present():
    try:
        import pycuda.driver as drv
    except ImportError:
        return False
    drv.init()
    return drv.Device.count() > 0


def name():
    """The backend in force: 'python' or 'numpy'."""
    want = (os.environ.get("DUE_DSP") or "auto").lower()
    if want == "python":
        return "python"
    if want == "numpy":
        if np is None:
            raise BackendUnavailable("DUE_DSP=numpy but numpy does not import")
        return "numpy"
    if want == "cuda":
        if not _cuda_present():
            raise BackendUnavailable("DUE_DSP=cuda but no pycuda device answers")
        raise BackendUnavailable("DUE_DSP=cuda: no CUDA kernel is written yet")
    if want != "auto":
        raise BackendUnavailable("DUE_DSP=%r is not python, numpy, cuda or auto" % want)
    return "numpy" if np is not None else "python"


def corr_many(win, xs, tmpl, period, phis):
    """`sum(win * tmpl[int((xs + phi) % period)])` for each phase in `phis`."""
    w = np.asarray(win, dtype=np.float64)
    x = np.asarray(xs, dtype=np.float64)
    t = np.asarray(tmpl, dtype=np.float64)
    ph = np.asarray(phis, dtype=np.float64)
    idx = np.fmod(x[None, :] + ph[:, None], period)
    idx = np.where(idx < 0, idx + period, idx).astype(np.int64)
    return (t[idx] * w[None, :]).sum(axis=1).tolist()


def _bin_mean(idx, vals, bins):
    cnt = np.bincount(idx, minlength=bins)
    acc = np.bincount(idx, weights=vals, minlength=bins)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = acc / cnt
    return [None if c == 0 else m for m, c in zip(mean.tolist(), cnt.tolist())], cnt.tolist()


def fold_scaled(vals, rc_adc, period, bins, start=0):
    """The mean per bin on a non-integer `period`; `(curve, counts)`."""
    v = np.asarray(vals, dtype=np.float64)
    n = np.arange(len(v), dtype=np.float64)
    ph = np.fmod(start * rc_adc + n * (rc_adc % period), period)
    idx = np.minimum((ph * (bins / period)).astype(np.int64), bins - 1)
    return _bin_mean(idx, v, bins)


def phase_indices(n, rc_adc, phase_at, period, k=1, start=0, segment=2048):
    """The fold bin of each of `n` samples on a fitted phase curve."""
    nb = period * k
    out = np.empty(n, dtype=np.int64)
    i = 0
    while i < n:
        m = min(segment, n - i)
        x0 = (start + i) * rc_adc
        x1 = (start + i + m) * rc_adc
        p0 = x0 + phase_at(x0)
        dp = (x1 + phase_at(x1) - p0) / m
        u = np.fmod(p0 + dp * np.arange(m, dtype=np.float64), period)
        u = np.where(u < 0, u + period, u)
        out[i:i + m] = (u * k).astype(np.int64) % nb
        i += m
    return out


def fold_warped(vals, idx, nb):
    """The mean per bin given each sample's bin; `(curve, counts)`."""
    return _bin_mean(np.asarray(idx), np.asarray(vals, dtype=np.float64), nb)


def center(vals):
    """`(centred, mean, amp)`: `vals` less its mean, over half its span.

    Takes a list or an array, and keeps an array an array: a 76 M-sample
    capture is 150 MB as uint16 and several GB as a list of floats.
    """
    v = np.asarray(vals)
    lo, hi = float(v.min()), float(v.max())
    mean = float(v.mean(dtype=np.float64))
    amp = (hi - lo) / 2.0 or 1.0
    return (v.astype(np.float64) - mean) / amp, mean, amp


#: Phases at or above which a search takes `corr_scan` rather than `corr_many`.
SCAN_MIN = 2048


def corr_scan(win, xs, tmpl, period, lo, n):
    """`corr_many` over the whole-tick phases `lo .. lo + n - 1`, without the
    `n x len(win)` index matrix.

    The first, global search of the tracker tries every phase of the pattern:
    1.9 M of them at PAM128, against a 150-sample block, which `corr_many`
    would build as 285 M indices (2.3 GB, and a run that never finished). Each
    sample instead adds its weight times a slice of the doubled template, so
    the memory is the template and the work is `len(win)` passes over it.
    `xs` and `lo` must be whole ticks and `n` at most `period`.
    """
    t = np.asarray(tmpl, dtype=np.float64)
    t2 = np.concatenate([t, t])
    acc = np.zeros(n, dtype=np.float64)
    for w, x in zip(np.asarray(win, dtype=np.float64).tolist(), xs):
        s = (int(x) + int(lo)) % period
        acc += w * t2[s:s + n]
    return acc
