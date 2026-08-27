"""The noise arithmetic, on signals whose answer is known in advance.

Board-free and instrument-free. Every case here is synthesised from a
formula, so a bug in the analysis cannot hide behind a plausible reading
off the bench - which is how six bugs in one experiment's analysis got
caught here this week, two of them producing confident wrong *positive*
results.

The cases that matter most are the ones designed to be lied about: a
pure sine must not read as broadband noise, broadband noise must not
read as a line, and a converter that is simply quantising must come back
as exactly its own bit depth rather than as something impressively
better.
"""
import math
import os
import random
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "host"))
import noise  # noqa: E402


def sine(n, fs, hz, amp_rms, phase=0.0):
    a = amp_rms * math.sqrt(2.0)
    return [a * math.sin(2 * math.pi * hz * i / fs + phase) for i in range(n)]


def white(n, rms, seed=1):
    rng = random.Random(seed)
    return [rng.gauss(0.0, rms) for _ in range(n)]


# ------------------------------------------------------------------
# bits
# ------------------------------------------------------------------

def test_a_converter_that_only_quantises_reads_as_its_own_depth():
    """The anchor. An ideal 12-bit converter has 1/sqrt(12) LSB of rms
    noise and nothing else, so it must come back as 12.000 bits - not
    11.8, and certainly not 13."""
    assert noise.effective_bits(noise.Q_RMS_LSB, 12) == pytest.approx(12.0)


def test_four_times_the_noise_costs_two_bits():
    a = noise.effective_bits(noise.Q_RMS_LSB, 12)
    b = noise.effective_bits(noise.Q_RMS_LSB * 4, 12)
    assert a - b == pytest.approx(2.0)


def test_noise_free_bits_are_fewer_than_effective_bits():
    """They answer different questions and the peak-to-peak one is
    always the harsher: 6.6 sigma against 1 sigma of quantisation."""
    r = 5.0
    assert noise.noise_free_bits(r, 12) < noise.effective_bits(r, 12)


def test_zero_noise_gives_no_answer_rather_than_infinity():
    """A series with no spread is either a perfect converter or a
    measurement that is not connected to anything."""
    assert noise.effective_bits(0.0) is None
    assert noise.noise_free_bits(0.0) is None


def test_describe_reports_the_excess_over_quantisation():
    vals = [2048 + v for v in white(4096, 3.0, seed=7)]
    d = noise.describe(vals, lsb_v=0.000535)
    assert d["rms_lsb"] == pytest.approx(3.0, rel=0.05)
    assert d["excess_over_quantisation"] == pytest.approx(3.0 / noise.Q_RMS_LSB,
                                                          rel=0.05)
    assert d["mean_v"] == pytest.approx(2048 * 0.000535, rel=1e-3)


def test_describe_uses_percentiles_not_extremes():
    """One outlying sample in 65,526 once read a 2.19 V pin as 3.640 V
    peak to peak on this project. Min/max is the wrong statistic for a
    long record."""
    vals = [2048.0] * 10000 + [9000.0]
    d = noise.describe(vals, lsb_v=1.0)
    assert d["span_lsb"] == pytest.approx(6952.0)
    assert d["p99_9_minus_p0_1_lsb"] == pytest.approx(0.0)


# ------------------------------------------------------------------
# spectrum
# ------------------------------------------------------------------

def test_the_transform_agrees_with_a_known_transform():
    x = [1.0, 0.0, 0.0, 0.0]
    assert [abs(v) for v in noise.fft(x)] == pytest.approx([1.0] * 4)
    y = [1.0, 1.0, 1.0, 1.0]
    got = noise.fft(y)
    assert abs(got[0]) == pytest.approx(4.0)
    assert all(abs(v) < 1e-12 for v in got[1:])


def test_a_non_power_of_two_is_refused_rather_than_padded():
    """Zero-padding changes the bin spacing and would silently move
    every frequency this reports."""
    with pytest.raises(ValueError):
        noise.fft([0.0] * 100)


def test_a_sine_lands_at_its_own_frequency_with_its_own_amplitude():
    fs, hz, amp = 453488.0, 8000.0, 4.0
    f, a = noise.spectrum(sine(4096, fs, hz, amp), fs)
    k = max(range(len(a)), key=lambda i: a[i])
    assert f[k] == pytest.approx(hz, abs=fs / 4096)
    assert a[k] == pytest.approx(amp, rel=0.05)


def test_the_dc_level_being_held_is_not_reported_as_noise():
    fs = 100000.0
    f, a = noise.spectrum([2048.0] * 4096, fs)
    assert max(a) < 1e-9


def test_broadband_noise_does_not_produce_a_line():
    fs = 453488.0
    f, a = noise.spectrum(white(4096, 3.0, seed=3), fs)
    found = noise.peaks(f, a, floor_mult=4.0)
    assert found == [], found


def test_a_line_in_noise_is_found_and_the_noise_is_not():
    fs, hz = 453488.0, 8000.0
    x = [s + n for s, n in zip(sine(4096, fs, hz, 3.0),
                               white(4096, 1.0, seed=5))]
    found = noise.peaks(noise.spectrum(x, fs)[0], noise.spectrum(x, fs)[1])
    assert found, "the line was missed"
    assert found[0]["hz"] == pytest.approx(hz, abs=fs / 4096 * 2)
    assert found[0]["amp_lsb"] == pytest.approx(3.0, rel=0.15)


def test_one_line_reports_once_and_not_three_times():
    """A line spreads over its neighbouring bins, and reporting each of
    them separately would invent two aggressors that are not there."""
    fs = 453488.0
    x = sine(4096, fs, 8000.5 * fs / 4096 / (fs / 4096), 3.0)  # off-bin
    found = noise.peaks(*noise.spectrum(x, fs), count=10)
    assert len(found) == 1, [p["hz"] for p in found]


# ------------------------------------------------------------------
# the split, which is the whole point
# ------------------------------------------------------------------

def test_the_line_split_separates_a_tone_from_a_floor():
    fs = 453488.0
    x = [s + n for s, n in zip(sine(8192, fs, 8000.0, 4.0),
                               white(8192, 1.0, seed=11))]
    s = noise.line_split(*noise.spectrum(x, fs))
    assert s["line_rms_lsb"] == pytest.approx(4.0, rel=0.2)
    assert s["floor_rms_lsb"] == pytest.approx(1.0, rel=0.35)
    assert s["line_power_fraction"] > 0.8


def test_pure_noise_puts_essentially_no_power_in_lines():
    fs = 453488.0
    s = noise.line_split(*noise.spectrum(white(8192, 2.0, seed=13), fs))
    assert s["line_power_fraction"] < 0.05


def test_averaging_recovers_a_planted_random_and_coherent_pair():
    """rms(N)^2 = random^2/N + coherent^2, so the fit must return both
    terms from the depths alone."""
    rand, coh = 8.0, 3.0
    pts = [(n, math.sqrt(rand ** 2 / n + coh ** 2))
           for n in (1, 2, 4, 8, 16, 64, 256)]
    s = noise.split_by_averaging(pts)
    assert s["random_rms_lsb"] == pytest.approx(rand, rel=0.01)
    assert s["coherent_rms_lsb"] == pytest.approx(coh, rel=0.01)


def test_purely_random_noise_reports_no_coherent_term_rather_than_a_small_one():
    """The case that would otherwise manufacture a finding. A clamped
    intercept would report a small positive coupled term for data that
    contains none."""
    pts = [(n, 8.0 / math.sqrt(n)) for n in (1, 2, 4, 8, 16, 64, 256)]
    s = noise.split_by_averaging(pts)
    assert s["random_rms_lsb"] == pytest.approx(8.0, rel=0.01)
    assert s["coherent_rms_lsb"] is None
    assert "does not support" in s["note"]


def test_two_points_are_a_fit_and_one_is_not():
    assert noise.split_by_averaging([(1, 8.0)]) == {}
    assert noise.split_by_averaging([(1, 8.0), (4, 4.0)])["n_points"] == 2


# ------------------------------------------------------------------
# aliasing, which nothing on this board filters
# ------------------------------------------------------------------

def test_a_line_at_the_same_frequency_at_two_rates_is_stationary():
    a = [{"hz": 8000.0, "amp_lsb": 3.0}]
    b = [{"hz": 8000.4, "amp_lsb": 3.1}]
    got = noise.alias_check(a, 453488.0, b, 200000.0)
    assert got[0]["verdict"] == "stationary"


def test_a_line_that_moves_with_the_sample_rate_is_called_out():
    a = [{"hz": 8000.0, "amp_lsb": 3.0}]
    b = [{"hz": 51000.0, "amp_lsb": 3.0}]
    got = noise.alias_check(a, 453488.0, b, 200000.0)
    assert got[0]["verdict"].startswith("moved")


def test_a_single_rate_cannot_name_anything():
    """There is no anti-alias filter on this board, so one rate gives a
    candidate and never an identification."""
    got = noise.alias_check([{"hz": 8000.0, "amp_lsb": 3.0}], 453488.0,
                            [], 200000.0)
    assert got[0]["matched_hz"] is None
    assert got[0]["verdict"].startswith("moved")


# ------------------------------------------------------------------
# the estimator itself
# ------------------------------------------------------------------

def test_averaging_windows_tightens_the_estimate():
    """The whole reason `welch` exists. The same signal, estimated from
    one window and from many: both must find the same floor, and the
    many-window estimate must scatter less across seeds.

    Measured rather than asserted from theory, because an estimator that
    is merely *different* would also pass a theory-shaped test."""
    fs = 453488.0
    one, many = [], []
    for seed in range(6):
        x = white(65536, 3.0, seed=seed)
        _, a1 = noise.spectrum(x[:4096], fs)
        one.append(math.sqrt(sum(v * v for v in a1)))
        _, a2, k = noise.welch(x, fs, window=4096)
        many.append(math.sqrt(sum(v * v for v in a2)))
        assert k == 16
    spread_one = max(one) - min(one)
    spread_many = max(many) - min(many)
    assert spread_many < spread_one / 2, (spread_one, spread_many)


def test_welch_finds_the_same_line_as_a_single_window():
    fs, hz = 453488.0, 8000.0
    x = [s + n for s, n in zip(sine(65536, fs, hz, 3.0),
                               white(65536, 1.0, seed=9))]
    f, a, k = noise.welch(x, fs, window=4096)
    found = noise.peaks(f, a)
    assert found[0]["hz"] == pytest.approx(hz, abs=fs / 4096 * 2)
    assert found[0]["amp_lsb"] == pytest.approx(3.0, rel=0.15)


def test_welch_refuses_a_record_shorter_than_one_window():
    assert noise.welch([1.0] * 100, 1000.0, window=4096) == ([], [], 0)


def test_drift_and_fast_noise_are_reported_apart():
    """A level that wanders is not a level that is noisy, and the two
    have different causes and different fixes."""
    n, w = 40960, 4096
    fast = white(n, 2.0, seed=21)
    ramp = [10.0 * i / n for i in range(n)]          # slow wander
    st = noise.stability([f + r for f, r in zip(fast, ramp)], window=w)
    assert st["within_rms_lsb"] == pytest.approx(2.0, rel=0.15)
    assert st["drift_rms_lsb"] > 2.0
    assert st["drift_span_lsb"] == pytest.approx(9.0, rel=0.2)


def test_a_steady_level_shows_no_drift():
    st = noise.stability(white(40960, 2.0, seed=23), window=4096)
    assert st["drift_rms_lsb"] < 0.2
    assert st["within_rms_lsb"] == pytest.approx(2.0, rel=0.1)


def test_a_paired_difference_survives_wander_that_swamps_the_arms():
    """The reason for interleaving. A real 0.2 difference, buried under
    round-to-round wander ten times larger: comparing arm medians cannot
    see it, and the paired difference can."""
    rng = random.Random(31)
    rounds = [(4.0 + rng.gauss(0, 2.0),) for _ in range(6)]
    pairs = [(a, a + 0.2) for (a,) in rounds]
    p = noise.paired_delta(pairs)
    assert p["mean_delta"] == pytest.approx(0.2, abs=1e-9)
    assert p["resolved"] is True


def test_an_unresolved_difference_is_reported_as_a_bound_not_a_zero():
    rng = random.Random(37)
    pairs = [(4.0, 4.0 + rng.gauss(0, 1.0)) for _ in range(5)]
    p = noise.paired_delta(pairs)
    assert p["resolved"] is False
    assert p["bound"] > 0
    assert "not resolved" in p["verdict"]


def test_one_round_is_not_a_paired_comparison():
    assert noise.paired_delta([(1.0, 2.0)]) == {}
