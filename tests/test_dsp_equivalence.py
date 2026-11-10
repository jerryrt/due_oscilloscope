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


def test_the_global_scan_matches_the_per_phase_correlation():
    """The large-period search: every whole-tick phase, against corr_many."""
    rnd = random.Random(5)
    period = 6007
    tmpl = [rnd.uniform(-1, 1) for _ in range(period)]
    win = [rnd.uniform(-1, 1) for _ in range(150)]
    xs = [(1234 + i) * 46 for i in range(150)]
    got = dsp.corr_scan(win, xs, tmpl, period, 0, period)
    ref = dsp.corr_many(win, xs, tmpl, period, [float(p) for p in range(period)])
    assert list(got) == pytest.approx(ref, rel=1e-12, abs=1e-9)
    assert int(np.argmax(got)) == max(range(period), key=ref.__getitem__)


def test_the_running_line_matches_the_refit():
    rnd = random.Random(2)
    pts = [(i * 6900.0 + rnd.uniform(-5, 5), 0.3 + i * 1e-4 + rnd.gauss(0, 0.2))
           for i in range(3000)]
    line = etsperiod._RunningLine()
    for n, (x, y) in enumerate(pts, 1):
        line.add(x, y)
        if n in (3, 50, 3000):
            assert line.slope() == pytest.approx(etsperiod._slope(pts[:n]), rel=1e-9)


def test_the_thread_pool_changes_nothing(monkeypatch):
    """One thread and many give the same fold and the same labels."""
    import etspam
    import etspattern
    vals, syms, period = _capture(300_000)
    pat = etspattern.pattern(4)
    trk = etsperiod.track_clock_ratio(vals, RC_ADC, syms, RC_DAC, levels=4)
    out = {}
    for w in ("1", "4"):
        monkeypatch.setenv("DUE_DSP", "numpy")
        monkeypatch.setenv("DUE_DSP_WORKERS", w)
        c, n = etsperiod.fold_warped(vals, RC_ADC, trk["model"], period, 1)
        cells = {}
        cen, by_t = etspam.label_samples(vals, RC_ADC, trk["model"], pat, RC_DAC, 3.0, cells, 0)
        out[w] = (n, [list(h) for h in cen], cells, c)
    assert out["1"][0] == out["4"][0]
    assert out["1"][1] == out["4"][1] and out["1"][2] == out["4"][2]
    assert sum(a != b for a, b in zip(out["1"][3], out["4"][3])
               if a is not None and b is not None and abs(a - b) > 1e-9) == 0


def test_a_broken_pool_split_is_caught(monkeypatch):
    """Drop one range: the totals must differ, so the comparison above can fail."""
    vals, syms, period = _capture(300_000)
    trk = etsperiod.track_clock_ratio(vals, RC_ADC, syms, RC_DAC, levels=4)
    monkeypatch.setenv("DUE_DSP", "numpy")
    monkeypatch.setenv("DUE_DSP_WORKERS", "4")
    real = dsp.map_ranges
    monkeypatch.setattr(dsp, "map_ranges", lambda *a, **k: real(*a, **k)[:-1])
    c, n = etsperiod.fold_warped(vals, RC_ADC, trk["model"], period, 1)
    assert sum(n) < len(vals)


def test_the_vectorised_phase_index_matches_the_segment_loop():
    vals, syms, period = _capture(50_000)
    model = {"coef": [0.0, 0.3, 0.1], "xmid": 1.0e6, "xhalf": 1.0e6}
    for k in (1, 10):
        ref = list(etsperiod.phase_indices(len(vals), RC_ADC, model, period, k, 77))
        got = dsp.phase_indices(len(vals), RC_ADC, lambda x: etsperiod.phase_at(model, x),
                                period, k, 77, etsperiod.SEGMENT)
        assert got.tolist() == ref


def _close(a, b):
    """Equal in structure and in every number to 1e-9; the moments are matrix products."""
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(_close(a[k], b[k]) for k in a)
    if isinstance(a, (list, tuple)):
        return len(a) == len(b) and all(_close(x, y) for x, y in zip(a, b))
    if isinstance(a, float):
        return a == pytest.approx(b, rel=1e-9, abs=1e-9)
    return a == b


def test_the_batched_level_analysis_matches_the_loops(monkeypatch):
    """analyze_levels on matrices against the per-histogram loops, every field."""
    import etspam
    import etspattern
    for pam in (4, 16):
        pat = etspattern.pattern(pam)
        vals, syms, period = _capture(400_000, pam=pam)
        trk = etsperiod.track_clock_ratio(vals, RC_ADC, syms, RC_DAC, levels=pam)
        monkeypatch.setenv("DUE_DSP", "numpy")
        centre, by_t = etspam.label_samples(vals, RC_ADC, trk["model"], pat, RC_DAC, 3.0, None, 0)
        got = {}
        for which in ("python", "numpy"):
            monkeypatch.setenv("DUE_DSP", which)
            got[which] = etspam.analyze_levels(centre, by_t, pat)
        assert _close(got["python"], got["numpy"])
