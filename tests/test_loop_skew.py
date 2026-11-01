"""The loop skew metric, on synthetic captures with a planted lag.

`loop_skew_once` reads the phase of the tone on A1 against A0. The fake
`run_loop` plants A1 as the A0 sine delayed by a known number of
nanoseconds, so swapping the channels, dropping the fold, converting with
the wrong period or ignoring a refusal each changes an answer known here.
"""
import math
import os
import sys
from array import array
from types import SimpleNamespace

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "host"))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import measure  # noqa: E402
import metrics  # noqa: E402
import phase0  # noqa: E402

RC = 225
FS = measure.hz_for(RC)
TONE = FS / 256.0
PERIOD_NS = 1e9 / TONE
SIZE = metrics.LOOP_WINDOW
WINDOWS = 12
AMP = 2000.0
#: Codes are rounded to integers, an error of at most 0.5 code that is
#: periodic with the tone and so does not average away across windows.
#: Worst case on the fundamental: 0.5/AMP = 2.5e-4 rad, which at this
#: tone (781 Hz) is 2.5e-4/(2*pi*781) = 51 ns; 50 ns is that bound
#: (observed errors are a fraction of it). The planted lags below differ
#: from every mutation's answer by at least 960 ns.
TOL_NS = 50.0


def _fake(calls, lag_ns, refuse=False, a0_ns=0.0):
    def run_loop(board, **kw):
        calls.append(kw)
        if refuse:
            return SimpleNamespace(refused=True)
        total = int(FS * measure.SETTLE_US / 1e6) + (WINDOWS + 2) * SIZE
        ps = measure.ParsedStream(declared_rate_hz=FS, ts_first=0)
        marks = [(k, int(k / FS * 1e6)) for k in range(0, total, 2032)]

        def sine(delay_ns):
            return array("H", (round(2048 + AMP * math.sin(
                2 * math.pi * TONE * (i / FS - delay_ns * 1e-9)))
                for i in range(total)))
        ps.series = {measure.CH_A0: sine(a0_ns),
                     measure.CH_A1: sine(a0_ns + lag_ns)}
        ps.marks = {measure.CH_A0: list(marks), measure.CH_A1: list(marks)}
        return SimpleNamespace(stream=ps, tone_hz=0.0, refused=False)
    return run_loop


def _run(monkeypatch, lag_ns, **kw):
    calls = []
    monkeypatch.setattr(measure, "run_loop", _fake(calls, lag_ns, **kw))
    return metrics.loop_skew_once(None, RC), calls


# Sub-sample (0.3 sample = 1.5 us), one sample, several samples, a
# negative lag, and one near a quarter period.
@pytest.mark.parametrize("lag_ns", [960.0, 1500.0, 5000.0, 23000.0,
                                    -2400.0, -960.0])
def test_returns_the_planted_lag(monkeypatch, lag_ns):
    out, _ = _run(monkeypatch, lag_ns)
    assert out["skew_ns"] == pytest.approx(lag_ns, abs=TOL_NS)
    assert out["skew_s"] == pytest.approx(lag_ns * 1e-9, abs=TOL_NS * 1e-9)
    # Fraction of the sample period 1/fs, not of the tone period.
    assert out["skew_frac_of_period"] == pytest.approx(
        lag_ns * 1e-9 * FS, abs=TOL_NS * 1e-9 * FS)


def test_identical_channels_give_zero(monkeypatch):
    out, _ = _run(monkeypatch, 0.0)
    assert abs(out["skew_ns"]) < TOL_NS
    assert abs(out["phase_deg"]) < 0.01


def test_phase_wrapped_past_pi_follows_the_convention(monkeypatch):
    # A lag of 0.6 period is a phase of -216 degrees, which folds to
    # +144; the lag is reported folded to half a period: -0.4 period.
    out, _ = _run(monkeypatch, 0.6 * PERIOD_NS)
    assert out["skew_ns"] == pytest.approx(-0.4 * PERIOD_NS, abs=TOL_NS)
    assert out["phase_deg"] == pytest.approx(144.0, abs=0.1)


@pytest.mark.parametrize("turn", [k / 24 for k in range(24)])
def test_a_phase_that_crosses_pi_between_the_channels(monkeypatch, turn):
    # The absolute phase depends on where the first window starts, so
    # walk A0's phase round the whole circle in 15-degree steps: A1, 36 degrees
    # ahead of it, then lands across +-pi for at least one of them, where
    # the raw difference is about -324 degrees and the lag is -0.1 period.
    out, _ = _run(monkeypatch, -0.1 * PERIOD_NS, a0_ns=turn * PERIOD_NS)
    assert out["skew_ns"] == pytest.approx(-0.1 * PERIOD_NS, abs=TOL_NS)
    assert out["phase_deg"] == pytest.approx(36.0, abs=0.1)


def test_a_lag_near_half_a_period_does_not_split(monkeypatch):
    # 0.499 of a period sits against the fold: per-window phase noise
    # must not send windows to opposite signs and halve the median.
    out, _ = _run(monkeypatch, 0.499 * PERIOD_NS)
    assert out["skew_ns"] == pytest.approx(0.499 * PERIOD_NS, abs=TOL_NS)


def test_key_set_is_exact(monkeypatch):
    out, _ = _run(monkeypatch, 1000.0)
    assert set(out) == {"skew_s", "skew_ns", "skew_frac_of_period",
                        "phase_deg", "phase_sd_deg", "n_windows",
                        "tone_hz", "rc", "fs"}
    assert out["n_windows"] >= 10
    assert out["rc"] == RC and out["fs"] == FS
    assert out["phase_sd_deg"] < 0.01


def test_a_refused_run_raises(monkeypatch):
    with pytest.raises(SystemExit):
        _run(monkeypatch, 0.0, refuse=True)


def test_the_loop_is_matched_and_carries_a_sine_on_both_dacs(monkeypatch):
    out, calls = _run(monkeypatch, 0.0)
    assert len(calls) == 1
    kw = calls[0]
    assert kw["dac_sps"] == FS and kw["adc_hz"] == FS
    assert kw["channels"] == 2
    assert kw["seconds"] >= metrics.loop_seconds(RC)
    assert out["tone_hz"] == FS / 256.0
    wave = kw["wave"]
    ent = [int.from_bytes(wave[i:i + 2], "little")
           for i in range(0, len(wave), 2)]
    assert [e >> 12 for e in ent[:4]] == [0, 1, 0, 1]
    assert [e & 0xFFF for e in ent[0::2]] == [e & 0xFFF for e in ent[1::2]]
    cycle = 2 * metrics.SKEW_POINTS
    # One cycle is 256 entries at the DAC rate = 256/FS s = 1/tone.
    assert cycle / FS == pytest.approx(1.0 / out["tone_hz"])
    assert len(wave) % 512 == 0
    assert max(e & 0xFFF for e in ent) > 4000


def test_registered_scope_free_under_its_own_name():
    m = phase0.METRICS["loop-skew"]
    assert m["scope"] is False
    assert phase0.METRICS["skew"]["scope"] is True
