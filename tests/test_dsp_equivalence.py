"""The numpy backend against the pure-Python reference. No board.

Skipped where numpy is absent, which is the container image today: the
reference is what the gate runs there, and this file holds the vectorised
code to it wherever both exist.
"""
import math
import random

import pytest

np = pytest.importorskip("numpy")

import dsp  # noqa: E402
import etsperiod  # noqa: E402
import pam_oracle  # noqa: E402

pytestmark = pytest.mark.smoke

RC_DAC, RC_ADC = 29, 46


def _capture(n, delta=-2.5e-6, seed=1, noise=1.0, pam=4):
    """Samples of the oracle's PAM pattern as an ADC with its own clock sees it."""
    syms = pam_oracle.symbols(pam)
    codes = pam_oracle.dac_codes(pam)
    period = len(syms) * RC_DAC
    rnd = random.Random(seed)
    out = []
    for k in range(n):
        x = (k * RC_ADC) / (1.0 + delta) % period
        out.append(codes[syms[int(x) // RC_DAC]] + rnd.gauss(0, noise))
    return out, syms, period


def _force(monkeypatch, which):
    monkeypatch.setenv("DUE_DSP", which)
    assert dsp.name() == which


def test_the_correlation_matches_per_phase(monkeypatch):
    vals, syms, period = _capture(400)
    tmpl = etsperiod.template(syms, RC_DAC, 4)
    win = vals[100:250]
    xs = [(100 + i) * RC_ADC for i in range(150)]
    phis = [float(p) for p in range(0, 40)]
    ref = [etsperiod._corr(win, xs, tmpl, period, p) for p in phis]
    got = dsp.corr_many(win, xs, tmpl, period, phis)
    assert got == pytest.approx(ref, rel=1e-12, abs=1e-9)


def test_the_fold_on_a_free_clock_matches(monkeypatch):
    vals, syms, period = _capture(60000)
    p = period * (1.0 - 2.5e-6)
    _force(monkeypatch, "python")
    c0, n0 = etsperiod.fold_scaled(vals, RC_ADC, p, period)
    _force(monkeypatch, "numpy")
    c1, n1 = etsperiod.fold_scaled(vals, RC_ADC, p, period)
    assert sum(a != b for a, b in zip(n0, n1)) <= 2          # float drift at a bin edge
    assert sum(n0) == sum(n1) == len(vals)
    both = [(a, b) for a, b in zip(c0, c1) if a is not None and b is not None]
    assert len(both) > 0.99 * len(c0)
    assert sum(abs(a - b) > 1.0 for a, b in both) <= 4


def test_the_fold_on_a_fitted_curve_matches(monkeypatch):
    vals, syms, period = _capture(60000)
    model = {"coef": [0.0, 0.3, 0.1], "xmid": 1.0e6, "xhalf": 1.0e6}
    _force(monkeypatch, "python")
    c0, n0 = etsperiod.fold_warped(vals, RC_ADC, model, period, 1)
    _force(monkeypatch, "numpy")
    c1, n1 = etsperiod.fold_warped(vals, RC_ADC, model, period, 1)
    assert sum(a != b for a, b in zip(n0, n1)) <= 4
    assert sum(n0) == sum(n1) == len(vals)


def test_the_tracker_reads_the_same_clock(monkeypatch):
    vals, syms, period = _capture(150000, delta=-2.5e-6)
    got = {}
    for which in ("python", "numpy"):
        _force(monkeypatch, which)
        got[which] = etsperiod.track_clock_ratio(vals, RC_ADC, syms, RC_DAC, levels=4)
    a, b = got["python"], got["numpy"]
    assert a["blocks"] == b["blocks"]
    assert a["delta"] == pytest.approx(b["delta"], abs=2e-9)
    assert a["rms"] == pytest.approx(b["rms"], abs=1e-6)
    assert a["adequate"] == b["adequate"]
    assert a["lattice_gcd"] == b["lattice_gcd"]
    assert a["delta"] == pytest.approx(-2.5e-6, abs=5e-8)       # and it is the truth


def test_the_equivalence_can_fail(monkeypatch):
    """Break the vectorised fold: the comparison above must notice."""
    vals, syms, period = _capture(60000)
    p = period * (1.0 - 2.5e-6)
    real = dsp.fold_scaled
    monkeypatch.setattr(dsp, "fold_scaled", lambda v, r, pe, b, s=0: real(v, r + 1, pe, b, s))
    _force(monkeypatch, "python")
    c0, n0 = etsperiod.fold_scaled(vals, RC_ADC, p, period)
    _force(monkeypatch, "numpy")
    c1, n1 = etsperiod.fold_scaled(vals, RC_ADC, p, period)
    assert sum(a != b for a, b in zip(n0, n1)) > 100


def test_an_unavailable_backend_is_refused_not_substituted(monkeypatch):
    monkeypatch.setenv("DUE_DSP", "cuda")
    with pytest.raises(dsp.BackendUnavailable):
        dsp.name()
    monkeypatch.setenv("DUE_DSP", "nonsense")
    with pytest.raises(dsp.BackendUnavailable):
        dsp.name()
