"""The square-shape gate on synthetic results, with literal bounds.

Board-free. `check_square` in test_square_shape_board.py must accept
both rise modes with a tick of headroom and refuse each crossed bound,
a missing key, and the values a zero DAC bias produces.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_square_shape_board import check_square  # noqa: E402

CFG = {"rise_ns_100k_max": 324.86, "rise_ns_400k_max": 324.56,
       "fall_ns_100k_max": 326.91, "fall_ns_400k_max": 326.58,
       "vpp_frac_400k_min": 0.99,
       "flat_hi_400k_min": 0.64286, "flat_lo_400k_min": 0.64286,
       "flat_hi_100k_min": 0.83571, "flat_lo_100k_min": 0.82768}


def good(**over):
    v = {"rise_ns_100k": 300.0, "rise_ns_400k": 277.0,
         "fall_ns_100k": 303.0, "fall_ns_400k": 280.0,
         "vpp_frac_400k": 0.9973,
         "flat_hi_400k": 0.7143, "flat_lo_400k": 0.7143,
         "flat_hi_100k": 0.9286, "flat_lo_100k": 0.9196}
    v.update(over)
    return v


def test_values_inside_the_bands_pass():
    check_square(good(), CFG)


@pytest.mark.parametrize("rise", [301.0, 322.0])
def test_both_rise_modes_and_a_tick_of_headroom_pass(rise):
    check_square(good(rise_ns_100k=rise, rise_ns_400k=rise), CFG)


CROSSED = [("rise_ns_100k", 325.0), ("rise_ns_400k", 325.0),
           ("fall_ns_100k", 327.0), ("fall_ns_400k", 327.0),
           ("vpp_frac_400k", 0.989), ("flat_hi_400k", 0.64),
           ("flat_lo_400k", 0.64), ("flat_hi_100k", 0.83),
           ("flat_lo_100k", 0.82)]


@pytest.mark.parametrize("key,val", CROSSED)
def test_each_crossed_bound_fails_naming_it(key, val):
    with pytest.raises(AssertionError, match=key):
        check_square(good(**{key: val}), CFG)


@pytest.mark.parametrize("key", [k for k, _ in CROSSED])
def test_a_missing_key_fails(key):
    v = good()
    del v[key]
    with pytest.raises(AssertionError, match="not measured"):
        check_square(v, CFG)


def test_a_missing_bound_fails():
    cfg = dict(CFG)
    del cfg["vpp_frac_400k_min"]
    with pytest.raises(AssertionError, match="vpp_frac_400k_min"):
        check_square(good(), cfg)


@pytest.mark.parametrize("key,val", [("rise_ns_400k", 838.0),
                                     ("flat_hi_400k", 0.07),
                                     ("vpp_frac_400k", 0.957)])
def test_the_bias_zero_values_fail(key, val):
    with pytest.raises(AssertionError, match=key):
        check_square(good(**{key: val}), CFG)
