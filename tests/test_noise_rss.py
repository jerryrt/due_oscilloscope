"""Known noise added to a capture moves the figure by the root-sum-square.

Exit check of phase F in `docs/analog-validation-plan.md`. Board-free:
the series is synthesised, rounded to integer codes as the converter
does, and run through `noisetool.analyse` - the function behind
`phase0.py noise-fast` - before and after `noise_metrics.add_known_noise`.

Tolerances come from the sampling error and nothing else. The rms of N
independent gaussian samples has a relative standard error of
1/sqrt(2N); the noisy arm's expected value is the root-sum-square of the
baseline *as measured* and the added rms, so only the added noise's own
sampling error and the cross term remain, and both are no larger than
the baseline's. Five standard errors is allowed (REL_SE_MULT).
"""
import math
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "host"))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import noise_metrics as nm  # noqa: E402

FS = 200_000
WINDOW = 4096
WINDOWS = 24                    # the bench takes ~163; fewer keeps this fast
N = WINDOW * WINDOWS * 10 // 9 + 1   # analyse drops the first tenth
MID = 2048.0
BASE_RMS = 0.8                  # the figure under test is arbitrary here
REL_SE_MULT = 5.0


def _series(extra_tone_rms=0.0):
    import random
    rng = random.Random(7)
    a = extra_tone_rms * math.sqrt(2.0)
    # 3 kHz sits on a Hann bin centre at 200 kHz / 4096 only by chance;
    # the line split does not need it to.
    return [MID + rng.gauss(0.0, BASE_RMS)
            + a * math.sin(2 * math.pi * 3000.0 * i / FS) for i in range(N)]


def _tol(base_rms, predicted, n):
    return REL_SE_MULT * predicted / math.sqrt(2.0 * n) \
        + REL_SE_MULT * base_rms / math.sqrt(2.0 * n)


@pytest.mark.parametrize("extra", [0.5, 1.0, 2.0])
def test_added_noise_moves_the_rms_by_the_root_sum_square(extra):
    base, noisy, pred = nm.rss_response(_series(), extra, FS)
    n = noisy["n"]
    assert abs(noisy["rms_lsb"] - pred) <= _tol(base["rms_lsb"], pred, n)
    # and it did move, by more than the tolerance: the check can fail
    assert noisy["rms_lsb"] - base["rms_lsb"] > 2 * _tol(base["rms_lsb"],
                                                         pred, n) / 5


def test_adding_nothing_does_not_move_the_figure():
    base, noisy, pred = nm.rss_response(_series(), 0.0, FS)
    assert noisy["rms_lsb"] == pytest.approx(base["rms_lsb"], abs=1e-9)
    assert pred == pytest.approx(base["rms_lsb"], abs=1e-9)


def test_a_helper_returns_the_requested_rms_before_rounding():
    zero = [0.0] * 50_000
    out = nm.add_known_noise(zero, 1.5)
    rms = math.sqrt(sum(v * v for v in out) / len(out))
    assert rms == pytest.approx(1.5, rel=REL_SE_MULT / math.sqrt(2 * 50_000))


def test_noise_moves_the_floor_by_the_root_sum_square_not_the_line():
    tone = 6.0                           # codes rms, far above the floor
    extra = 2.0
    base, noisy, _ = nm.rss_response(_series(tone), extra, FS)
    f0 = base["split"]["floor_rms_lsb"]
    f1 = noisy["split"]["floor_rms_lsb"]
    pred = math.sqrt(f0 * f0 + extra * extra)
    # the floor is a sum over thousands of bins per window, so its error
    # is the same 1/sqrt(2N) order; 3x more is allowed for the line
    # threshold sitting at 4x the median bin
    assert abs(f1 - pred) <= 3 * _tol(f0, pred, noisy["n"])
    assert f1 - f0 > 0.5
    # the tone itself did not change
    assert noisy["split"]["line_rms_lsb"] == pytest.approx(
        base["split"]["line_rms_lsb"], rel=0.05)


def test_a_pure_tone_has_a_floor_that_extra_noise_alone_creates():
    # no added noise: floor stays where it was; the tone is all line
    base, noisy, _ = nm.rss_response(_series(6.0), 0.0, FS)
    assert noisy["split"]["floor_rms_lsb"] == pytest.approx(
        base["split"]["floor_rms_lsb"], abs=1e-9)
