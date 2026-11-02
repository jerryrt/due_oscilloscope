import os, sys
sys.path.insert(0, os.path.dirname(__file__))
import h7_cal as c


def test_the_factory_line_passes_through_its_own_points():
    cal = c.Calibration.load()
    for ch in (1, 2):
        for g in range(c.GAINS):
            p = cal._p(ch, g)
            assert abs(cal.volts(ch, g, p["x1"]) - p["y1"]) < 1e-6
            assert abs(cal.volts(ch, g, p["x2"]) - p["y2"]) < 1e-6


def test_the_published_gain_zero_figures_for_this_unit():
    cal = c.Calibration.load()
    assert abs(cal.codes_per_volt(1, 0) - 2284.9) < 0.5          # docs/05 section 5.5
    assert abs(cal.codes_per_volt(1, 7) - 296687) < 300
    assert abs(cal.zero_code(1, 0) - 32657.0) < 1.0


def test_each_gain_code_multiplies_the_scale_by_about_two():
    cal = c.Calibration.load()
    r = [cal.codes_per_volt(1, g + 1) / cal.codes_per_volt(1, g) for g in range(7)]
    assert all(1.9 < x < 2.2 for x in r), r


def test_a_measured_zero_replaces_the_factory_zero():
    cal = c.Calibration.load(zero_override={(1, 0): 32843.0})
    assert abs(cal.volts(1, 0, 32843.0)) < 1e-9
    assert abs(c.Calibration.load().volts(1, 0, 32843.0) - 186 / 2284.9) < 1e-3
    assert abs(cal.volts(2, 0, cal.zero_code(2, 0))) < 1e-9       # other channels untouched


def test_a_bad_channel_or_gain_is_refused():
    import pytest
    cal = c.Calibration.load()
    with pytest.raises(ValueError):
        cal.volts(3, 0, 1000)
    with pytest.raises(ValueError):
        cal.volts(1, 8, 1000)
