"""The noise on a held code, gated against the recorded band.

`noise-fast` in tools/noise_metrics.py is the instrument; this runs it
and judges its figure against `baseline.json`'s `noise` section. Three
checks, each able to fail on its own: the rms is under a ceiling, no
spectral line carries more than a bound of the power, and the rms is not
below what the converter's own quantiser produces, since a reading
under that is a flat or stale capture and not a quiet board.
"""

import os
import sys

import pytest

import measure
from helpers import gate_note
import pacing

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import noise_metrics as nm  # noqa: E402

CODE = 2048
WINDOW = 4096


def check_noise(flat, cfg):
    """Raise AssertionError unless one `noise_metrics._run` result fits."""
    for key in ("rms_ceiling_lsb", "line_fraction_ceiling", "floor_factor"):
        assert cfg.get(key) is not None, (
            f"tests/baseline.json noise.{key} is missing: the held-code "
            f"noise has not been measured, and a null is not a pass")
    rms = flat["rms_lsb"]
    quant = flat["quantisation_floor_lsb"]
    floor_rms = flat.get("split.floor_rms_lsb")
    frac = flat.get("split.line_power_fraction") or 0.0
    assert rms <= cfg["rms_ceiling_lsb"], (
        f"{rms:.3f} codes rms on a held code is above the recorded "
        f"ceiling {cfg['rms_ceiling_lsb']} (floor part {floor_rms})"
        f"{gate_note(cfg)}")
    assert frac <= cfg["line_fraction_ceiling"], (
        f"spectral lines carry {frac:.3f} of the power, above "
        f"{cfg['line_fraction_ceiling']} ({flat.get('n_lines')} lines)")
    assert rms >= cfg["floor_factor"] * quant, (
        f"{rms:.3f} codes rms is below {cfg['floor_factor']} x the "
        f"quantisation floor {quant:.4f}: a converter cannot be quieter "
        f"than its quantiser, so the capture is flat or stale")


@pytest.mark.parametrize("adc_rc", [measure.rc_for(200000), 86],
                         ids=["adc200k", "rc86"])
def test_the_noise_on_a_held_code_stays_inside_the_recorded_band(
        board, baseline, adc_rc):
    cfg = baseline["noise"]
    flat = nm._run(board, CODE, pacing.SHORT, WINDOW, preset="5", rc=adc_rc)
    check_noise(flat, cfg)


# Board-free: the assertions on synthetic series, through the same
# analysis function the tool uses.

CFG = {"rms_ceiling_lsb": 1.04, "line_fraction_ceiling": 0.05,
       "floor_factor": 0.9}
FS = 200_000
N = 4096 * 12


def _flat(values):
    import noisetool
    a = noisetool.analyse([round(v) for v in values], FS, 1.0, window=4096)
    return nm._flat(a)


def _quiet(rms):
    # Pre-rounding level at a code boundary so the quantiser dithers.
    return nm.add_known_noise([2048.3] * N, rms)


def test_a_series_at_the_recorded_level_passes():
    check_noise(_flat(_quiet(0.8)), CFG)


def test_noise_above_the_ceiling_fails():
    with pytest.raises(AssertionError, match="ceiling"):
        check_noise(_flat(_quiet(1.5)), CFG)


def test_a_flat_series_fails_the_floor_check():
    with pytest.raises(AssertionError, match="flat or stale"):
        check_noise(_flat(_quiet(0.05)), CFG)


def test_a_tone_line_fails_the_line_check():
    import math
    tone = [v + 0.5 * math.sin(2 * math.pi * 12500 * i / FS)
            for i, v in enumerate(_quiet(0.8))]
    with pytest.raises(AssertionError, match="spectral lines"):
        check_noise(_flat(tone), CFG)


def test_a_missing_key_is_not_a_pass():
    with pytest.raises(AssertionError, match="missing"):
        check_noise(_flat(_quiet(0.8)), {})
