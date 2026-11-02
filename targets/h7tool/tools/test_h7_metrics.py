import os, sys
import pytest
np = pytest.importorskip("numpy", reason="needs numpy (.venv-gui); a skip here is NOT a pass")
sys.path.insert(0, os.path.dirname(__file__))
import h7_metrics as m

N, G = 2500, 8


def square(tau_bins, shift=0, noise=0.0, ripple=0.0, level=1.0, seed=1):
    """A +-level square with first-order edges (10-90 % rise = 2.197 tau), circularly shifted, optionally noisy."""
    t = np.arange(N); half = N // 2; w = np.empty(N); v = -level
    for i in range(2 * N):                                     # run two cycles so the state settles, keep the second
        target = level if (i % N) < half else -level
        v += (target - v) * (1 - np.exp(-1 / tau_bins)) if tau_bins > 0 else (target - v)
        if i >= N: w[i - N] = v
    if ripple:
        w += ripple * np.exp(-((t - half) % N) / 40.0) * np.sin(0.8 * t)
    w += np.random.default_rng(seed).normal(0, noise, N)
    return np.roll(w, shift)


def test_rise_time_matches_a_first_order_edge_at_any_start_position():
    for shift in (0, 313, 1249, 2000):                          # the array may begin anywhere, even mid-edge
        e = m.edge_metrics(square(30, shift), G)
        assert e["valid"], e["reason"]
        assert abs(e["rise_ns"] - 2.197 * 30 * G * 5) < 0.1 * 2.197 * 30 * G * 5
        assert abs(e["fall_ns"] - e["rise_ns"]) < 0.1 * e["rise_ns"]


def test_noise_and_ripple_do_not_move_the_edge():
    ref = m.edge_metrics(square(30), G)["rise_ns"]
    e = m.edge_metrics(square(30, 700, noise=0.02, ripple=0.05), G)
    assert e["valid"] and abs(e["rise_ns"] - ref) < 0.15 * ref


def test_an_unresolved_edge_is_refused_not_reported():
    # the failure seen on the bench: a one-bin step read as a 40 ns rise
    e = m.edge_metrics(square(0.0, 400), G)
    assert not e["valid"] and "unresolved" in e["reason"]


def test_a_flat_line_has_no_plateaus():
    assert not m.edge_metrics(np.full(N, 0.3) + np.random.default_rng(2).normal(0, 1e-3, N), G)["valid"]


def test_a_missing_bins_are_interpolated_not_nan():
    w = square(30); w[100:104] = np.nan
    assert m.edge_metrics(w, G)["valid"]


def test_sine_metrics_recover_amplitude_and_a_known_harmonic():
    t = np.arange(N) / N; w = 0.5 * np.sin(2 * np.pi * t) + 0.01 * np.sin(2 * np.pi * 3 * t) + 0.2
    s = m.sine_metrics(w)
    assert abs(s["amp"] - 0.5) < 1e-3 and abs(s["mean"] - 0.2) < 1e-3 and abs(s["thd"] - 0.02) < 1e-3
