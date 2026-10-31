"""The DC transfer fit and its gates, against synthetic points.

Board-free: the board test feeds these same functions measured means.
"""

import random

import pytest

from helpers import assert_dc_fit, dc_fit

CODES = (512, 1024, 2048, 3072, 3583)
SLOPE, OFFSET = 0.67, 120.0
REF = dict(slope_ref=SLOPE, offset_ref=OFFSET, slope_tol=0.005,
           offset_tol=10.0, physics_tol=0.05, resid_max=3.0)


def line(slope=SLOPE, offset=OFFSET, shift=None):
    pts = [(c, offset + slope * c) for c in CODES]
    if shift:
        i, d = shift
        pts[i] = (pts[i][0], pts[i][1] + d)
    return pts


def test_exact_line_has_no_residual():
    slope, offset, rms, worst = dc_fit(line())
    assert slope == pytest.approx(SLOPE)
    assert offset == pytest.approx(OFFSET)
    assert rms < 1e-9 and worst < 1e-9


def test_noise_of_known_rms_gives_residual_near_it():
    rnd = random.Random(7)
    pts = [(c, OFFSET + SLOPE * c + rnd.gauss(0, 2.0)) for c in range(0, 4000, 20)]
    _, _, rms, _ = dc_fit(pts)
    assert 1.6 < rms < 2.4


def test_clean_line_passes():
    assert_dc_fit(line(), **REF)


def test_one_shifted_level_fails_the_residual_only():
    pts = line(shift=(2, 8.0))
    slope, offset, _, _ = dc_fit(pts)
    # the fit absorbs part of the shift, so slope and offset stay inside
    assert abs(slope - SLOPE) <= REF["slope_tol"]
    assert abs(offset - OFFSET) <= REF["offset_tol"]
    with pytest.raises(AssertionError, match="DC transfer residual"):
        assert_dc_fit(pts, **REF)


def test_slope_ten_percent_off_fails_the_physics_bound():
    wide = dict(REF, slope_ref=SLOPE * 1.1, slope_tol=1.0)
    with pytest.raises(AssertionError, match="nominal"):
        assert_dc_fit(line(slope=SLOPE * 1.1), physics_slope=SLOPE, **wide)


def test_moved_slope_fails_the_regression_gate():
    with pytest.raises(AssertionError, match="regression"):
        assert_dc_fit(line(slope=SLOPE + 0.02), **REF)


def test_moved_offset_fails_the_regression_gate():
    with pytest.raises(AssertionError, match="regression"):
        assert_dc_fit(line(offset=OFFSET + 30), **REF)


def _recorded():
    import json
    import os
    with open(os.path.join(os.path.dirname(__file__), "baseline.json"),
              encoding="utf-8") as f:
        c = json.load(f)["dc_transfer"]
    return dict(slope_ref=c["slope_ref"], offset_ref=c["offset_ref"],
                slope_tol=c["slope_tol"], offset_tol=c["offset_tol"],
                physics_tol=c["physics_tol"], resid_max=c["resid_max_codes"])


@pytest.mark.parametrize("level", range(len(CODES)))
@pytest.mark.parametrize("sign", (1, -1))
def test_the_recorded_gate_passes_one_level_3_2_codes_off(level, sign):
    """A whole run can sit 3.2 codes off at any one level (measured, 4 of 60
    level readings, mechanism not established), so the recorded gate must pass
    it at every level and in both directions."""
    rec = _recorded()
    pts = line(rec["slope_ref"], rec["offset_ref"], (level, sign * 3.2))
    assert_dc_fit(pts, **rec)


@pytest.mark.parametrize("level", range(len(CODES)))
@pytest.mark.parametrize("sign", (1, -1))
def test_the_recorded_gate_fails_one_level_8_codes_off(level, sign):
    rec = _recorded()
    pts = line(rec["slope_ref"], rec["offset_ref"], (level, sign * 8.0))
    with pytest.raises(AssertionError, match="DC transfer"):
        assert_dc_fit(pts, **rec)
