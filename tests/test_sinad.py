"""Coherent-sine SINAD, THD and ENOB, on signals whose answer is known.

Board-free. The prediction in every case is arithmetic on the synthesis
parameters, never a figure read off a first run.
"""
import math
import os
import random
import sys
from types import SimpleNamespace

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "host"))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import measure  # noqa: E402
import noise  # noqa: E402

W = 8192
FS = 200000.0
CYC = 32
TONE = CYC * FS / W          # whole cycles in a window
N = 10 * W


def tone(amp, cycles=CYC, n=N, phase=0.3):
    return [amp * math.sin(2 * math.pi * cycles * i / W + phase)
            for i in range(n)]


def db(x):
    return 10 * math.log10(x)


def test_a_pure_coherent_sine_is_limited_only_by_float_rounding():
    """Float64 rounding sits near -300 dB; 90 dB is a wide margin."""
    r = noise.sinad(tone(1000.0), FS, TONE)
    assert r["sinad_db"] > 90 and r["thd_db"] < -90
    assert r["n_windows"] == 10
    assert r["signal_rms_lsb"] == pytest.approx(1000 / math.sqrt(2), rel=1e-9)


def test_a_third_harmonic_at_minus_60_dbc_reads_as_minus_60_thd():
    a = tone(1000.0)
    h3 = tone(1.0, cycles=3 * CYC, phase=1.1)
    r = noise.sinad([x + y for x, y in zip(a, h3)], FS, TONE)
    assert r["thd_db"] == pytest.approx(-60.0, abs=0.5)
    assert r["sinad_db"] == pytest.approx(60.0, abs=0.5)
    assert r["noise_floor_rms_lsb"] < 1e-6


def test_white_noise_of_known_rms_sets_the_floor_and_the_sinad():
    sigma, amp = 3.0, 1000.0
    rng = random.Random(7)
    x = [2048.0 + s + rng.gauss(0.0, sigma) for s in tone(amp)]  # DC offset must not count
    r = noise.sinad(x, FS, TONE)
    # The floor excludes the DC, fundamental and harmonic bins, which hold
    # (2 + harmonics) of W/2 bins' worth of noise. Chosen band, not
    # measured: 5 standard errors of an rms from N samples is
    # 5 * sigma / sqrt(2N).
    assert r["noise_floor_rms_lsb"] == pytest.approx(
        sigma, abs=5 * sigma / math.sqrt(2 * N))
    # SINAD is signal over everything but DC and the fundamental, so the
    # noise term is sigma^2 less the same few bins: sigma^2 to 0.1%.
    want = db((amp * amp / 2) / (sigma * sigma))
    assert r["sinad_db"] == pytest.approx(want, abs=0.05)


def test_quantised_to_codes_matches_the_quantisation_noise_prediction():
    amp = 1371.0
    x = [round(v + 2048) for v in tone(amp)]
    r = noise.sinad(x, FS, TONE)
    want = db((amp * amp / 2) / (noise.Q_RMS_LSB ** 2))
    assert r["sinad_db"] == pytest.approx(want, abs=1.0)
    assert r["enob"] == pytest.approx((r["sinad_db"] - 1.76) / 6.02)
    assert r["enob"] == pytest.approx(want / 6.02 - 0.29, abs=0.2)
    # The error repeats every 256 samples, so some of it lands on the
    # harmonic bins the floor excludes: at most 1/sqrt(12), not much less.
    assert 0.85 * noise.Q_RMS_LSB < r["noise_floor_rms_lsb"] < 1.02 * noise.Q_RMS_LSB


def test_a_tone_that_is_not_whole_cycles_per_window_is_refused():
    with pytest.raises(ValueError):
        noise.sinad(tone(1000.0, cycles=32.5), FS, 32.5 * FS / W)
    with pytest.raises(ValueError):
        noise.sinad(tone(1000.0), FS, TONE * 1.001)


def test_a_partial_trailing_window_is_dropped():
    r = noise.sinad(tone(1000.0, n=N + 1000), FS, TONE)
    assert r["n_windows"] == 10


def test_a_harmonic_that_folds_onto_the_fundamental_is_skipped():
    """fs = 4 * tone: 2nd is Nyquist, 3rd and 5th fold onto the fundamental,
    4th and 8th onto DC. Putting power on the 3rd must not read as THD."""
    cyc = W // 4
    x = [1000 * math.sin(2 * math.pi * cyc * i / W + 0.2)
         + 100 * math.sin(2 * math.pi * 3 * cyc * i / W + 0.9)
         for i in range(2 * W)]
    r = noise.sinad(x, 4.0, 1.0)
    assert r["harmonic_bins"] == [W // 2]
    assert r["thd_db"] < -90


# --- the wiring ---------------------------------------------------------

def test_sinad_once_runs_the_matched_loop_and_returns_flat_numbers(monkeypatch):
    import noise_metrics as nm
    import phase0
    calls = []
    hz = measure.hz_for(225)
    vals = [round(2048 + 1000 * math.sin(2 * math.pi * i / 256.0))
            for i in range(12 * W)]

    class Stream:
        series = {measure.CH_A0: vals}

        def _index_at(self, tag, us):
            calls.append(("from", us))
            return 100

    def run_loop(board, **kw):
        calls.append(kw)
        return SimpleNamespace(refused=False, stream=Stream(),
                               tone_hz=kw["tone"])
    monkeypatch.setattr(measure, "run_loop", run_loop)
    out = phase0.METRICS["sinad"]["fn"](
        None, None, phase0.loop_default_args("sinad"))
    kw = calls[0]
    assert kw["dac_sps"] == hz and kw["adc_hz"] == hz and kw["tone"] == hz / 256.0
    assert ("from", measure.SETTLE_US) in calls
    assert set(out) == {"sinad_db", "thd_db", "enob", "signal_rms_lsb",
                        "noise_floor_rms_lsb", "n_windows", "tone_hz",
                        "rc", "fs"}
    assert out["rc"] == 225 and out["fs"] == hz and out["n_windows"] == 11
    assert 50 < out["sinad_db"] < 90
    assert phase0.METRICS["sinad"]["scope"] is False
