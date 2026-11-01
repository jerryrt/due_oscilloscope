"""The A1-after-A0 lag in the loop, gated to a whole trigger period.

`loop_skew_once` in tools/metrics.py is the instrument. The lag it reads
is DAC1's write after DAC0's plus the ADC's A1-before-A0 spacing, as one
figure, and in the recorded data it is an integer multiple k of the
trigger period. k varies between runs, so the gate allows the recorded
set and judges the distance to the nearest whole period. Six of 69
recorded rows were off it, so a failure is confirmed by one fresh
measurement before it fails the test. `baseline.json`'s `loop_skew`.
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


def check_loop_skew(values, cfg):
    """Raise AssertionError unless one `loop_skew_once` result fits `cfg`."""
    for bound in ("k_allowed", "deviation_ns_max", "phase_sd_deg_max"):
        assert cfg.get(bound) is not None, (
            f"tests/baseline.json loop_skew.{bound} is missing: the lag "
            f"has not been measured, and a null is not a pass")
    for key in ("skew_s", "skew_ns", "fs", "phase_sd_deg"):
        assert values.get(key) is not None, f"{key} was not measured"
    k = round(values["skew_s"] * values["fs"])
    assert k in cfg["k_allowed"], (
        f"k {k} (skew_s {values['skew_s']:.3e} s at fs {values['fs']}) is "
        f"not in the recorded k_allowed {cfg['k_allowed']}")
    dev = abs(values["skew_ns"] - k / values["fs"] * 1e9)
    assert dev <= cfg["deviation_ns_max"], (
        f"deviation {dev:.1f} ns from k {k} periods is above the "
        f"recorded bound deviation_ns_max {cfg['deviation_ns_max']}")
    assert values["phase_sd_deg"] <= cfg["phase_sd_deg_max"], (
        f"phase_sd_deg {values['phase_sd_deg']:.5f} is above the "
        f"recorded bound phase_sd_deg_max {cfg['phase_sd_deg_max']}")


@pytest.mark.parametrize("adc_rc", [measure.rc_for(200000), 86],
                         ids=["adc200k", "rc86"])
def test_the_lag_between_the_two_channels_is_a_whole_trigger_period(
        board, baseline, calibration, adc_rc):
    cfg = baseline["loop_skew"]
    last = []

    def once():
        last[:] = [metrics.loop_skew_once(board, adc_rc, pacing.SHORT)]
        return last[0]

    outcome = {}
    try:
        outcome = confirm_measurement(
            once, lambda v: check_loop_skew(v, cfg))
    finally:
        if last:
            v = last[0]
            k = round(v["skew_s"] * v["fs"])
            record(calibration, f"loop_skew_rc{adc_rc}", {
                "retried": outcome.get("retried", True),
                "first": outcome.get("first"), "k": k,
                "deviation_ns": round(
                    abs(v["skew_ns"] - k / v["fs"] * 1e9), 2),
                "phase_sd_deg": round(v["phase_sd_deg"], 5)})
