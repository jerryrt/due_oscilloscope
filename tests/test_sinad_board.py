"""The SINAD of a coherent sine, gated against the recorded band.

`sinad_once` in tools/noise_metrics.py is the instrument: DAC0 to A0 in
the matched loop, a tone that fits the analysis window exactly. This runs
it and judges SINAD, ENOB, THD, the noise floor and the signal level
against `baseline.json`'s `sinad` section. One measurement in the
recorded data was a spike (a floor of 5.97 codes against 0.85), so a
failure is confirmed by one fresh measurement before it fails the test.
"""

import os
import sys

import pytest

import measure
import pacing
from helpers import confirm_measurement, record

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import noise_metrics as nm  # noqa: E402

LOWER = (("sinad_db", "sinad_db_min"), ("enob", "enob_min"),
         ("signal_rms_lsb", "signal_rms_lsb_min"))
UPPER = (("thd_db", "thd_db_max"),
         ("noise_floor_rms_lsb", "noise_floor_rms_lsb_max"),
         ("signal_rms_lsb", "signal_rms_lsb_max"))


def check_sinad(values, cfg):
    """Raise AssertionError unless one `sinad_once` result fits `cfg`."""
    for _, bound in LOWER + UPPER:
        assert cfg.get(bound) is not None, (
            f"tests/baseline.json sinad.{bound} is missing: the SINAD "
            f"band has not been measured, and a null is not a pass")
    for key, bound in LOWER:
        assert values[key] >= cfg[bound], (
            f"{key} {values[key]:.3f} is below the recorded bound "
            f"{bound} {cfg[bound]}")
    for key, bound in UPPER:
        assert values[key] <= cfg[bound], (
            f"{key} {values[key]:.3f} is above the recorded bound "
            f"{bound} {cfg[bound]}")


@pytest.mark.parametrize("adc_rc", [measure.rc_for(200000), 86],
                         ids=["adc200k", "rc86"])
def test_the_sinad_of_a_coherent_sine_stays_inside_the_recorded_band(
        board, baseline, calibration, adc_rc):
    cfg = baseline["sinad"]
    last = []

    def once():
        last[:] = [nm.sinad_once(board, adc_rc, pacing.SHORT)]
        return last[0]

    outcome = {}
    try:
        outcome = confirm_measurement(once, lambda v: check_sinad(v, cfg))
    finally:
        if last:
            record(calibration, f"sinad_rc{adc_rc}", {
                "retried": outcome.get("retried", True),
                "first": outcome.get("first"),
                **{k: round(last[0][k], 3) for k, _ in LOWER[:2] + UPPER[:2]},
                "signal_rms_lsb": round(last[0]["signal_rms_lsb"], 3)})
