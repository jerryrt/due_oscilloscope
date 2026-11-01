"""The loop-skew gate on synthetic results, with literal bounds.

Board-free. `check_loop_skew` in test_loop_skew_board.py must accept a
lag of one or two whole trigger periods at either rate and refuse k = 0,
k = 3, a half-way lag, a deviation past the bound, a noisy phase and a
missing key.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_loop_skew_board import check_loop_skew  # noqa: E402

CFG = {"k_allowed": [1, 2], "deviation_ns_max": 25,
       "phase_sd_deg_max": 0.00248}
RATES = (200000, 523255)


def row(fs, k=1.0, dev_ns=0.0, sd=0.001):
    ns = k / fs * 1e9 + dev_ns
    return {"skew_s": ns * 1e-9, "skew_ns": ns, "fs": fs,
            "phase_sd_deg": sd}


@pytest.mark.parametrize("fs", RATES)
@pytest.mark.parametrize("k", [1, 2])
def test_a_whole_period_lag_within_the_deviation_passes(fs, k):
    check_loop_skew(row(fs, k, 20.0), CFG)
    check_loop_skew(row(fs, k, -20.0), CFG)


@pytest.mark.parametrize("fs", RATES)
@pytest.mark.parametrize("k", [0, 3])
def test_a_lag_of_a_period_count_not_recorded_fails(fs, k):
    with pytest.raises(AssertionError, match="k_allowed"):
        check_loop_skew(row(fs, k), CFG)


@pytest.mark.parametrize("fs", RATES)
def test_a_deviation_past_the_bound_fails(fs):
    with pytest.raises(AssertionError, match="deviation_ns_max"):
        check_loop_skew(row(fs, 1, 26.0), CFG)
    with pytest.raises(AssertionError, match="deviation_ns_max"):
        check_loop_skew(row(fs, 2, -26.0), CFG)


@pytest.mark.parametrize("fs", RATES)
def test_a_halfway_lag_fails(fs):
    half = 0.5 / fs * 1e9
    with pytest.raises(AssertionError):
        check_loop_skew(row(fs, 1.0, half), CFG)


def test_a_noisy_phase_fails():
    with pytest.raises(AssertionError, match="phase_sd_deg_max"):
        check_loop_skew(row(200000, 1, 0.0, 0.0025), CFG)


@pytest.mark.parametrize("key", ["skew_s", "skew_ns", "fs", "phase_sd_deg"])
def test_a_missing_key_fails_loudly(key):
    r = row(200000)
    del r[key]
    with pytest.raises(AssertionError, match="was not measured"):
        check_loop_skew(r, CFG)


@pytest.mark.parametrize("key", list(CFG))
def test_a_missing_bound_fails_loudly(key):
    cfg = dict(CFG)
    del cfg[key]
    with pytest.raises(AssertionError, match="is missing"):
        check_loop_skew(row(200000), cfg)
