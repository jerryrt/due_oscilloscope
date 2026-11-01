"""Amplitude on A0 and crosstalk on A1 against tone, gated to the bands.

`tone_sweep_once` in tools/metrics.py is the instrument: one matched
loop per tone `fs/N`, N samples per cycle. This runs it and judges the
A0 amplitude, the fraction of windows above the floor and the A1
crosstalk against `baseline.json`'s `tone_sweep` section. The recorded
data holds spikes, so a failure is confirmed by one fresh measurement
before it fails the test.
"""

import os
import sys

import pytest

import measure
import pacing
from helpers import confirm_measurement, record

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import metrics  # noqa: E402

NS = (256, 64, 16, 8)
FRAC_NS = (256, 64, 16)
XTALK_NS = (256, 64, 16, 8)


def check_tone_sweep(values, cfg):
    """Raise AssertionError unless one `tone_sweep_once` result fits `cfg`."""
    needed = ([f"amp_min_n{n}" for n in NS] + [f"amp_max_n{n}" for n in NS]
              + [f"xtalk_max_n{n}" for n in XTALK_NS] + ["frac_min"])
    for bound in needed:
        assert cfg.get(bound) is not None, (
            f"tests/baseline.json tone_sweep.{bound} is missing: the band "
            f"has not been measured, and a null is not a pass")
    for n in NS:
        amp = values[f"amp_n{n}"]
        assert amp is not None, f"amp_n{n} was not measured"
        assert amp >= cfg[f"amp_min_n{n}"], (
            f"amp_n{n} {amp:.3f} is below the recorded bound "
            f"amp_min_n{n} {cfg[f'amp_min_n{n}']}")
        assert amp <= cfg[f"amp_max_n{n}"], (
            f"amp_n{n} {amp:.3f} is above the recorded bound "
            f"amp_max_n{n} {cfg[f'amp_max_n{n}']}")
    for n in FRAC_NS:
        frac = values[f"amp_n{n}_frac"]
        assert frac is not None and frac >= cfg["frac_min"], (
            f"amp_n{n}_frac {frac} is below the recorded bound "
            f"frac_min {cfg['frac_min']}")
    for n in XTALK_NS:
        xt = values[f"xtalk_n{n}"]
        assert xt is not None, f"xtalk_n{n} was not measured"
        assert xt <= cfg[f"xtalk_max_n{n}"], (
            f"xtalk_n{n} {xt:.3f} is above the recorded bound "
            f"xtalk_max_n{n} {cfg[f'xtalk_max_n{n}']}")


@pytest.mark.parametrize("adc_rc", [measure.rc_for(200000), 86],
                         ids=["adc200k", "rc86"])
def test_amplitude_and_crosstalk_stay_inside_the_recorded_bands_across_tone(
        board, baseline, calibration, adc_rc):
    cfg = baseline["tone_sweep"]
    last = []

    def once():
        last[:] = [metrics.tone_sweep_once(board, adc_rc, pacing.SHORT)]
        return last[0]

    outcome = {}
    try:
        outcome = confirm_measurement(
            once, lambda v: check_tone_sweep(v, cfg))
    finally:
        if last:
            row = {"retried": outcome.get("retried", True),
                   "first": outcome.get("first")}
            for n in NS:
                row[f"amp_n{n}"] = round(last[0][f"amp_n{n}"], 3)
                row[f"xtalk_n{n}"] = round(last[0][f"xtalk_n{n}"], 3)
            record(calibration, f"tone_sweep_rc{adc_rc}", row)
