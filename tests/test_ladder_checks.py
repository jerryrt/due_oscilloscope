"""The ladder's signal checks, on synthetic captures whose answer is known.

The checks that judge a loop run's tone and its crosstalk were written for
one rate. They are broken here on purpose, on a deep copy of the captured
stream and never on the stimulus - a feed-rate change trips the underrun
check first and proves nothing about the amplitude check - and each break
must fail the checks of its own family and none outside it.
"""
import copy
import math
import os
import sys
from array import array
from types import SimpleNamespace

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "host"))
sys.path.insert(0, HERE)
import measure  # noqa: E402
import pacing  # noqa: E402
from helpers import (LADDER_WINDOWS, assert_crosstalk, assert_tone,  # noqa: E402
                     ladder_seconds, ladder_tone)
from test_rates import AWG, ONE_CH, TWO_CH  # noqa: E402

FLOOR, FRACTION, CEILING = 1340.0, 0.9, 12.0     # tests/baseline.json "amplitude"
RC = 120
SIZE = 8192


def _result(a0=1370.0, a1=0.0, a1_phase=0.0, windows=12):
    """A loop capture: a sine of `a0` codes on A0 and `a1` on A1, locked in phase."""
    fs = measure.hz_for(RC)
    tone = ladder_tone(RC)
    n = int(fs * measure.SETTLE_US / 1e6) + (windows + 2) * SIZE   # settle, then `windows` + 1 whole windows
    ps = measure.ParsedStream(declared_rate_hz=fs, ts_first=0)
    marks = [(k, int(k / fs * 1e6)) for k in range(0, n, 2032)]
    ps.series = {
        measure.CH_A0: array("H", (int(2048 + a0 * math.sin(2 * math.pi * tone * i / fs))
                                   for i in range(n))),
        measure.CH_A1: array("H", (int(2048 + a1 * math.sin(2 * math.pi * tone * i / fs + a1_phase))
                                   for i in range(n))),
    }
    ps.marks = {measure.CH_A0: list(marks), measure.CH_A1: list(marks)}
    return SimpleNamespace(stream=ps, tone_hz=tone)


def _passes(res):
    """(amplitude check passed, crosstalk check passed)."""
    out = []
    for check in (lambda: assert_tone(res, measure.CH_A0, FLOOR, fraction=FRACTION),
                  lambda: assert_crosstalk(res, measure.CH_A1, CEILING)):
        try:
            check()
            out.append(True)
        except AssertionError:
            out.append(False)
    return out


def test_a_clean_capture_passes_both_checks():
    assert _passes(_result()) == [True, True]


def test_scaling_a0_fails_the_amplitude_checks_and_nothing_outside_that_family():
    bad = copy.deepcopy(_result())
    s = bad.stream.series[measure.CH_A0]
    for i in range(len(s)):
        s[i] = int(2048 + 0.9 * (s[i] - 2048))
    assert _passes(bad) == [False, True]
    with pytest.raises(AssertionError, match="median window amplitude"):
        assert_tone(bad, measure.CH_A0, FLOOR, fraction=FRACTION)


def test_scaling_only_a_few_windows_fails_the_fraction_and_not_the_median():
    res = copy.deepcopy(_result(windows=12))
    ps = res.stream
    start = ps._index_at(measure.CH_A0, measure.SETTLE_US)
    s = ps.series[measure.CH_A0]
    for w in (3, 4):                                  # two of twelve windows
        for i in range(start + w * SIZE, start + (w + 1) * SIZE):
            s[i] = int(2048 + 0.9 * (s[i] - 2048))
    median, amps = measure_window(res)
    assert median >= FLOOR and sum(a < FLOOR for a in amps) == 2
    assert 10 <= len(amps) <= 14, f"{len(amps)} windows"
    with pytest.raises(AssertionError, match=r"only \d+/\d+ windows"):
        assert_tone(res, measure.CH_A0, FLOOR, fraction=FRACTION)
    assert _passes(res) == [False, True]


def measure_window(res):
    from helpers import window_purity
    return window_purity(res, measure.CH_A0)


@pytest.mark.parametrize("phase", [0.0, math.pi / 2, math.pi, 3 * math.pi / 2])
def test_a_tone_on_a1_of_three_times_the_ceiling_fails_the_crosstalk_check_at_any_phase(phase):
    res = _result(a1=3 * CEILING, a1_phase=phase)
    assert _passes(res) == [True, False]
    with pytest.raises(AssertionError, match="carries"):
        assert_crosstalk(res, measure.CH_A1, CEILING)


def test_a_tone_on_a1_at_the_floor_of_noise_passes():
    assert _passes(_result(a1=0.2 * CEILING)) == [True, True]


@pytest.mark.parametrize("rc", sorted(set(TWO_CH + ONE_CH)))
def test_every_ladder_rate_has_a_whole_number_of_tone_cycles_in_a_window(rc):
    cycles = SIZE * ladder_tone(rc) / measure.hz_for(rc)
    assert cycles == pytest.approx(32.0)


@pytest.mark.parametrize("rc", sorted(set(TWO_CH + ONE_CH)))
def test_every_ladder_run_holds_enough_windows_after_the_settle(rc):
    secs = ladder_seconds(rc)
    assert secs >= pacing.SHORT
    windows = (secs - measure.SETTLE_US / 1e6) * measure.hz_for(rc) / SIZE
    assert windows >= LADDER_WINDOWS, (
        f"RC {rc}: a {secs:.2f} s run holds {windows:.1f} windows; one bad window "
        f"would then fail a {FRACTION} fraction by itself")


def test_the_awg_ladder_is_not_judged_here():
    """The play-only ladder has no capture to judge a tone on."""
    assert set(AWG).isdisjoint({780, 390})
