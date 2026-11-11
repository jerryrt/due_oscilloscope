"""The CUDA kernels against their numpy twins (host/dsp_cuda.py, host/dsp.py).

What these cannot see: the kernel's `--fmad=false`. Turning it on changes no bin
index in 20 M samples, so no test here fails when it is removed.

Skipped where pycuda or a device is missing, as test_dsp_equivalence.py is where
numpy is. Each check also has a positive control: the same comparison on a
deliberately wrong input must see a difference, so a skip or a vacuous pass
cannot stand for a result.
"""
import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("pycuda")
try:
    import pycuda.driver as _drv
    _drv.init()
    _HAVE_DEVICE = _drv.Device.count() > 0
except Exception:
    _HAVE_DEVICE = False
pytestmark = pytest.mark.skipif(not _HAVE_DEVICE, reason="no CUDA device answers")

import dsp  # noqa: E402
import dsp_cuda  # noqa: E402


def _phase_at(x):
    return 3.0e-9 * x * x + 2.5e-4 * x + 11.0


def test_phase_indices_equal_the_numpy_ones_exactly():
    for n, start, period, k in ((100_000, 0, 7 * 28, 10), (50_001, 80_000, 127 * 29, 10),
                                (4_097, 3, 1_834_980, 1)):
        want = dsp.phase_indices(n, 45, _phase_at, period, k, start, 2048)
        got = dsp_cuda.phase_indices(n, 45, _phase_at, period, k, start, 2048)
        assert got.shape == want.shape and (got == want).all(), (n, period, k)
    # the control: a different phase curve must change the result
    other = dsp_cuda.phase_indices(100_000, 45, lambda x: _phase_at(x) + 0.7, 7 * 28, 10, 0, 2048)
    assert (other != dsp.phase_indices(100_000, 45, _phase_at, 7 * 28, 10, 0, 2048)).any()


def test_fold_warped_equals_the_numpy_fold():
    rng = np.random.default_rng(5)
    nb = 5_000
    idx = rng.integers(0, nb - 40, 300_000)             # the last bins stay empty
    vals = rng.integers(0, 4096, 300_000).astype(np.float64)
    want_curve, want_cnt = dsp.fold_warped(vals, idx, nb)
    got_curve, got_cnt = dsp_cuda.fold_warped(vals, idx, nb)
    assert got_cnt == want_cnt
    assert got_curve == want_curve, "integer-valued sums are exact, so the means must be"
    assert got_curve[-1] is None and got_cnt[-1] == 0
    bad = vals.copy()
    bad[0] += 1.0
    assert dsp_cuda.fold_warped(bad, idx, nb)[0] != want_curve


def test_corr_many_matches_numpy_and_reuses_the_template():
    rng = np.random.default_rng(9)
    period = 1_901
    tmpl = rng.standard_normal(period).tolist()
    xs = (np.arange(150) * 45.0).tolist()
    win = rng.standard_normal(150).tolist()
    phis = list(range(0, period, 7))
    want = dsp.corr_many(win, xs, tmpl, period, phis)
    got = dsp_cuda.corr_many(win, xs, tmpl, period, phis)
    assert np.allclose(got, want, rtol=1e-10, atol=1e-10)
    again = dsp_cuda.corr_many(win, xs, tmpl, period, phis)
    assert again == got
    assert len(dsp_cuda._state["tmpl"]) == 1, "one template, copied once"
    other = dsp_cuda.corr_many([w * 1.01 for w in win], xs, tmpl, period, phis)
    assert not np.allclose(other, want, rtol=1e-6)


def _label_case(pam, n=300_000):
    import etspam
    import etsperiod
    from test_etspam import _synth
    pat, vals = _synth(pam, n=n, sigma=1.3)
    trk = etsperiod.track_clock_ratio(vals, 46, pat.symbols, 29, levels=pat.pam)
    return etspam, pat, trk["model"], np.asarray(vals, dtype=np.uint16)


@pytest.mark.parametrize("pam", [4, 16])
def test_label_range_equals_the_numpy_histograms_exactly(pam, monkeypatch):
    etspam, pat, model, v = _label_case(pam)
    monkeypatch.setenv("DUE_DSP", "numpy")
    for want_cells in (True, False):
        c0, t0, x0 = etspam.label_range(v, 0, len(v), 46, model, pat, 29, 3.0, want_cells, 0)
        c1, t1, x1 = dsp_cuda.label_range(v, 0, len(v), 46, model, pat, 29, 3.0, want_cells, 0)
        assert (c0 == c1).all() and (t0 == t1).all()
        assert (x0 is None and x1 is None) or (x0 == x1).all()
        assert c1.sum() > 0 and t1.sum() == len(v)


def test_label_range_does_not_depend_on_the_chunk_or_the_range(monkeypatch):
    etspam, pat, model, v = _label_case(4)
    monkeypatch.setenv("DUE_DSP", "numpy")
    monkeypatch.setattr(dsp_cuda, "CHUNK", 2048 * 3)
    want = etspam.label_range(v, 2048, 200_000, 46, model, pat, 29, 3.0, True, 5)
    got = dsp_cuda.label_range(v, 2048, 200_000, 46, model, pat, 29, 3.0, True, 5)
    assert all((a == b).all() for a, b in zip(want, got))


def test_label_range_can_fail(monkeypatch):
    etspam, pat, model, v = _label_case(4)
    monkeypatch.setenv("DUE_DSP", "numpy")
    want = etspam.label_range(v, 0, len(v), 46, model, pat, 29, 3.0, False, 0)
    moved = dsp_cuda.label_range(v, 0, len(v), 46, model, pat, 29, 3.0 + 29, False, 0)
    assert not (want[0] == moved[0]).all(), "a boundary shifted by a symbol must change the centre histogram"
