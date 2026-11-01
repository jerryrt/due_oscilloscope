"""The tone-sweep gate's check, on synthetic results (no board).

Bounds are written here as literals, not imported from the module under
test or built from the baseline, so a bound that drifts or a check that
stops looking is caught.
"""

import pytest

from test_tone_sweep_board import check_tone_sweep

CFG = {"amp_min_n256": 1350.0, "amp_min_n64": 1356.0, "amp_min_n16": 1371.0,
       "amp_min_n8": 1239.0, "amp_max_n256": 1397.0, "amp_max_n64": 1394.0,
       "amp_max_n16": 1372.7, "amp_max_n8": 1440.0, "frac_min": 0.85,
       "xtalk_max_n256": 0.25, "xtalk_max_n64": 0.58,
       "xtalk_max_n16": 4.76, "xtalk_max_n8": 5.07}


def good():
    v = {}
    for n in (256, 64, 16, 8):
        v[f"amp_n{n}"] = 1371.5
        v[f"amp_n{n}_frac"] = 1.0
        v[f"xtalk_n{n}"] = 0.13
    return v


def test_a_result_inside_the_bands_passes():
    check_tone_sweep(good(), CFG)


@pytest.mark.parametrize("n,low", [(256, 1349.9), (64, 1355.9),
                                   (16, 1370.9), (8, 1238.9)])
def test_an_amplitude_below_its_minimum_fails(n, low):
    v = good()
    v[f"amp_n{n}"] = low
    with pytest.raises(AssertionError, match=f"amp_n{n} .*amp_min_n{n}"):
        check_tone_sweep(v, CFG)


@pytest.mark.parametrize("n,high", [(256, 1397.1), (64, 1394.1),
                                    (16, 1372.8), (8, 1440.1)])
def test_an_amplitude_above_its_maximum_fails(n, high):
    v = good()
    v[f"amp_n{n}"] = high
    with pytest.raises(AssertionError, match=f"amp_n{n} .*amp_max_n{n}"):
        check_tone_sweep(v, CFG)


@pytest.mark.parametrize("n", [256, 64, 16])
def test_a_low_window_fraction_fails(n):
    v = good()
    v[f"amp_n{n}_frac"] = 0.84
    with pytest.raises(AssertionError, match=f"amp_n{n}_frac .*frac_min"):
        check_tone_sweep(v, CFG)


def test_the_window_fraction_at_n8_is_not_gated():
    v = good()
    v["amp_n8_frac"] = 0.0
    check_tone_sweep(v, CFG)


@pytest.mark.parametrize("n,high", [(256, 0.26), (64, 0.59),
                                    (16, 4.77), (8, 5.08)])
def test_a_crosstalk_above_its_maximum_fails(n, high):
    v = good()
    v[f"xtalk_n{n}"] = high
    with pytest.raises(AssertionError, match=f"xtalk_n{n} .*xtalk_max_n{n}"):
        check_tone_sweep(v, CFG)


@pytest.mark.parametrize("key", sorted(CFG))
def test_a_missing_bound_fails_loudly(key):
    cfg = {k: x for k, x in CFG.items() if k != key}
    with pytest.raises(AssertionError, match=f"{key} is missing"):
        check_tone_sweep(good(), cfg)
    cfg[key] = None
    with pytest.raises(AssertionError, match=f"{key} is missing"):
        check_tone_sweep(good(), cfg)
