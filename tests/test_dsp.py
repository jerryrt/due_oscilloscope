"""The numpy kernels of the ETS analysis against answers known by hand or by
construction. No board, and no second implementation to compare with: numpy is
the implementation, so each test states what the answer has to be.
"""
import math
import random

import numpy as np
import pytest

import dsp
import etsperiod
import pam_oracle

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
    return np.asarray(out), syms, period


def test_the_correlation_is_the_sum_of_the_templates_it_lands_on():
    # tmpl = 1 2 3 4, a block of two samples at ticks 0 and 1: the sum at
    # phase p is tmpl[p] + tmpl[p + 1], wrapping at the period of 4.
    got = dsp.corr_many([1.0, 1.0], [0, 1], [1, 2, 3, 4], 4, [0, 1, 2, 3])
    assert got == [3.0, 5.0, 7.0, 5.0]
    assert list(dsp.corr_scan([1.0, 1.0], [0, 1], [1, 2, 3, 4], 4, 0, 4)) == [3.0, 5.0, 7.0, 5.0]
    # weights scale it, and a scan starting at phase 2 reads the same cycle from there
    assert list(dsp.corr_scan([2.0, 1.0], [0, 1], [1, 2, 3, 4], 4, 2, 4)) == [2 * 3 + 4, 2 * 4 + 1,
                                                                             2 * 1 + 2, 2 * 2 + 3]


def test_the_global_scan_agrees_with_the_per_phase_kernel_on_a_large_period():
    rnd = random.Random(5)
    period = 6007
    tmpl = [rnd.uniform(-1, 1) for _ in range(period)]
    win = [rnd.uniform(-1, 1) for _ in range(150)]
    xs = [(1234 + i) * 46 for i in range(150)]
    got = dsp.corr_scan(win, xs, tmpl, period, 0, period)
    ref = dsp.corr_many(win, xs, tmpl, period, [float(p) for p in range(period)])
    assert list(got) == pytest.approx(ref, rel=1e-12, abs=1e-9)


def test_the_scan_threads_split_the_range_without_changing_it(monkeypatch):
    rnd = random.Random(8)
    period = 9001
    tmpl = [rnd.uniform(-1, 1) for _ in range(period)]
    win = [rnd.uniform(-1, 1) for _ in range(40)]
    xs = [(77 + i) * 46 for i in range(40)]
    out = {}
    for w, threshold in (("1", 10 ** 9), ("4", 100)):
        monkeypatch.setattr(dsp, "SCAN_THREADS_MIN", threshold)
        monkeypatch.setenv("DUE_DSP_WORKERS", w)
        out[w] = dsp.corr_scan(win, xs, tmpl, period, 0, period)
    assert np.array_equal(out["1"], out["4"])


def test_a_free_clock_fold_lands_each_sample_in_the_bin_its_phase_names():
    # period 8, one sample every 3 ticks: phases 0, 3, 6, 9 % 8 = 1
    curve, cnt = dsp.fold_scaled([10.0, 20.0, 30.0, 40.0], 3, 8.0, 8)
    assert curve == [10.0, 40.0, None, 20.0, None, None, 30.0, None]
    assert cnt == [1, 1, 0, 1, 0, 0, 1, 0]
    # starting at sample 1 shifts every phase by one step
    curve, _ = dsp.fold_scaled([10.0], 3, 8.0, 8, start=1)
    assert curve[3] == 10.0


def test_the_phase_curve_moves_each_samples_bin_by_exactly_its_phase():
    flat = lambda x: 0.0 * x
    assert dsp.phase_indices(6, 3, flat, 8, 1, 0, 2048).tolist() == [0, 3, 6, 1, 4, 7]
    two = lambda x: 0.0 * x + 2.0
    assert dsp.phase_indices(6, 3, two, 8, 1, 0, 2048).tolist() == [2, 5, 0, 3, 6, 1]
    # ten bins a tick: the bin is the tick's tenth
    half = lambda x: 0.0 * x + 0.5
    assert dsp.phase_indices(3, 3, half, 8, 10, 0, 2048).tolist() == [5, 35, 65]
    # a start offset reads the same curve from later in the capture
    assert dsp.phase_indices(2, 3, flat, 8, 1, 4, 2048).tolist() == [4, 7]


def test_a_warped_fold_counts_every_sample_once():
    vals = np.arange(1, 7, dtype=np.float64) * 10
    model = {"coef": [0.0], "xmid": 0.0, "xhalf": 1.0}
    curve, cnt = etsperiod.fold_warped(vals, 3, model, 8)
    assert cnt == [1, 1, 0, 1, 1, 0, 1, 1]
    assert curve[0] == 10.0 and curve[3] == 20.0 and curve[6] == 30.0 and curve[1] == 40.0
    assert sum(cnt) == len(vals)


def test_the_template_runs_from_minus_one_to_plus_one_a_tick_at_a_time():
    assert etsperiod.template([0, 1, 3], 2, 4).tolist() == pytest.approx(
        [-1, -1, -1 / 3, -1 / 3, 1, 1])
    assert etsperiod.template([0, 1], 3, 2).tolist() == [-1, -1, -1, 1, 1, 1]


def test_a_known_curve_is_recovered_by_the_phase_fit():
    xs = np.linspace(0.0, 2.0e9, 3000)
    ys = 3.0 + 4.0e-6 * xs - 1.5e-15 * xs * xs
    m = etsperiod.fit_phase(list(zip(xs.tolist(), ys.tolist())))
    assert m["degree"] == 2 and m["outliers"] == 0
    assert m["rms"] < 1e-6
    assert etsperiod.phase_at(m, 1.0e9) == pytest.approx(3.0 + 4.0e3 - 1.5e3, rel=1e-9)
    # The quadratic term is -a * xhalf^2 * t^2 over t in [-1, 1]; against its own best
    # line (the mean of t^2 is 1/3) it runs from +1/3 to -2/3 of that: a peak-to-peak
    # of a * xhalf^2 = 1.5e-15 * (1e9)^2 = 1500 ticks.
    assert m["wander_ptp"] == pytest.approx(1.5e-15 * (1.0e9) ** 2, rel=1e-6)


def test_a_bad_match_is_dropped_from_the_phase_fit_and_counted():
    xs = np.linspace(0.0, 2.0e9, 2000)
    rnd = np.random.default_rng(3)
    ys = 1.0 + 2.0e-6 * xs + rnd.normal(0, 0.1, len(xs))
    ys[700] += 50.0
    m = etsperiod.fit_phase(list(zip(xs.tolist(), ys.tolist())))
    assert m["degree"] == 1 and m["outliers"] == 1
    assert m["rms"] == pytest.approx(0.1, rel=0.1)


def test_the_running_line_is_the_least_squares_slope():
    line = etsperiod._RunningLine()
    for x in range(0, 100000, 100):
        line.add(float(x), 5.0 + 3.0e-4 * x)
    assert line.slope() == pytest.approx(3.0e-4, rel=1e-12)


@pytest.mark.parametrize("pam,n", [(4, 400_000), (16, 1_500_000)])
def test_the_tracker_reads_the_clock_the_capture_was_built_with(pam, n):
    vals, syms, period = _capture(n, delta=-2.5e-6, pam=pam)
    trk = etsperiod.track_clock_ratio(vals, RC_ADC, syms, RC_DAC, levels=pam)
    assert trk["delta"] == pytest.approx(-2.5e-6, abs=5e-8)
    assert trk["adequate"] is True and trk["lattice_gcd"] == 1 and trk["edge_hits"] == 0
    assert trk["period"] == pytest.approx(period * (1 - 2.5e-6), rel=1e-7)


def test_the_batched_and_the_block_by_block_search_agree(monkeypatch):
    """Both are production paths (the second is the batched one's fallback)."""
    vals, syms, period = _capture(400_000)
    a = etsperiod.track_clock_ratio(vals, RC_ADC, syms, RC_DAC, levels=4, batched=False)
    b = etsperiod.track_clock_ratio(vals, RC_ADC, syms, RC_DAC, levels=4, batched=True)
    assert a["blocks"] == b["blocks"] and a["edge_hits"] == b["edge_hits"] == 0
    assert b["delta"] == pytest.approx(a["delta"], abs=1e-9)
    assert b["rms"] == pytest.approx(a["rms"], rel=1e-2)   # flat-topped ties differ in the 3rd digit
    assert a["adequate"] == b["adequate"] and a["lattice_gcd"] == b["lattice_gcd"]


def test_a_mispredicted_batched_search_gives_a_different_answer(monkeypatch):
    """Skew the coarse prediction by 3 ticks: the match moves, so the test above can fail."""
    vals, syms, period = _capture(400_000)
    a = etsperiod.track_clock_ratio(vals, RC_ADC, syms, RC_DAC, levels=4, batched=False)
    real = etsperiod.phase_at
    calls = {"n": 0}

    def skewed(model, x):
        calls["n"] += 1
        return real(model, x) + (3.0 if calls["n"] == 1 else 0.0)   # the batched pass's prediction
    monkeypatch.setattr(etsperiod, "phase_at", skewed)
    b = etsperiod.track_clock_ratio(vals, RC_ADC, syms, RC_DAC, levels=4, batched=True)
    assert (b["delta"], b["rms"]) != (a["delta"], a["rms"]) or b["blocks"] != a["blocks"]


def test_the_thread_pool_covers_the_range_once_in_aligned_pieces(monkeypatch):
    for w in ("1", "3", "8"):
        monkeypatch.setenv("DUE_DSP_WORKERS", w)
        for n in (5000, 100_000, 1_048_577):
            got = dsp.map_ranges(lambda a, b: (a, b), n, 2048)
            assert got[0][0] == 0 and got[-1][1] == n
            assert all(g[1] == h[0] for g, h in zip(got, got[1:]))
            assert all(g[0] % 2048 == 0 for g in got)


def test_the_thread_count_does_not_change_the_fold(monkeypatch):
    vals, syms, period = _capture(300_000)
    trk = etsperiod.track_clock_ratio(vals, RC_ADC, syms, RC_DAC, levels=4)
    out = {}
    for w in ("1", "4"):
        monkeypatch.setenv("DUE_DSP_WORKERS", w)
        c, n = etsperiod.fold_warped(vals, RC_ADC, trk["model"], period, 1)
        out[w] = (c, n)
    assert out["1"][1] == out["4"][1] and sum(out["4"][1]) == len(vals)
    assert all(a == pytest.approx(b, abs=1e-9)
               for a, b in zip(out["1"][0], out["4"][0]) if a is not None)


def test_a_dropped_range_is_noticed(monkeypatch):
    """Drop one range of the split: the totals must fall short."""
    vals, syms, period = _capture(300_000)
    trk = etsperiod.track_clock_ratio(vals, RC_ADC, syms, RC_DAC, levels=4)
    monkeypatch.setenv("DUE_DSP_WORKERS", "4")
    real = dsp.map_ranges
    monkeypatch.setattr(dsp, "map_ranges", lambda *a, **k: real(*a, **k)[:-1])
    c, n = etsperiod.fold_warped(vals, RC_ADC, trk["model"], period, 1)
    assert sum(n) < len(vals)


def test_centring_scales_the_span_to_plus_minus_one():
    cen, mean, amp = dsp.center(np.array([100, 200, 300], dtype=np.uint16))
    assert mean == 200.0 and amp == 100.0
    assert cen.tolist() == [-1.0, 0.0, 1.0]


def test_only_numpy_is_a_backend(monkeypatch):
    for name in ("numpy", "auto"):
        monkeypatch.setenv("DUE_DSP", name)
        assert dsp.name() == "numpy"
    for name in ("python", "cuda", "nonsense"):
        monkeypatch.setenv("DUE_DSP", name)
        with pytest.raises(dsp.BackendUnavailable):
            dsp.name()
