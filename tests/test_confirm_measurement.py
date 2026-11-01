"""`confirm_measurement` and the SINAD band check, on synthetic values."""

import pytest

from helpers import confirm_measurement
from test_sinad_board import check_sinad

CFG = {"sinad_db_min": 59.85, "enob_min": 9.65, "thd_db_max": -75.55,
       "noise_floor_rms_lsb_max": 0.97, "signal_rms_lsb_min": 969.67,
       "signal_rms_lsb_max": 970.73}
GOOD = {"sinad_db": 61.0, "enob": 9.84, "thd_db": -77.3,
        "noise_floor_rms_lsb": 0.85, "signal_rms_lsb": 970.2}


# Written out, not imported from the module under test: a bound dropped
# there must not drop out of the tests with it.
LOWER = (("sinad_db", "sinad_db_min"), ("enob", "enob_min"),
         ("signal_rms_lsb", "signal_rms_lsb_min"))
UPPER = (("thd_db", "thd_db_max"),
         ("noise_floor_rms_lsb", "noise_floor_rms_lsb_max"),
         ("signal_rms_lsb", "signal_rms_lsb_max"))


def _seq(*vals):
    calls = []

    def measure():
        calls.append(1)
        return vals[min(len(calls), len(vals)) - 1]
    return measure, calls


def _check(v):
    assert v == "ok", f"bad {v}"


def test_a_passing_measurement_is_taken_once():
    m, calls = _seq("ok")
    assert confirm_measurement(m, _check) == {
        "retried": False, "first": None, "value": "ok"}
    assert len(calls) == 1


def test_a_failure_then_a_pass_is_retried_once_and_keeps_the_first():
    m, calls = _seq("x", "ok")
    out = confirm_measurement(m, _check)
    assert out["retried"] is True and out["value"] == "ok"
    assert out["first"].startswith("bad x")
    assert len(calls) == 2


def test_two_failures_raise_with_both_messages_after_two_calls():
    m, calls = _seq("x", "y", "ok")
    with pytest.raises(AssertionError) as e:
        confirm_measurement(m, _check)
    msg = str(e.value)
    assert "both measurements failed" in msg and "bad x" in msg \
        and "bad y" in msg
    assert len(calls) == 2


def test_a_value_inside_the_band_passes():
    check_sinad(GOOD, CFG)


@pytest.mark.parametrize("key,bound", LOWER)
def test_each_lower_bound_fails_when_crossed(key, bound):
    v = dict(GOOD, **{key: CFG[bound] - 0.01})
    with pytest.raises(AssertionError, match=bound):
        check_sinad(v, CFG)


@pytest.mark.parametrize("key,bound", UPPER)
def test_each_upper_bound_fails_when_crossed(key, bound):
    v = dict(GOOD, **{key: CFG[bound] + 0.01})
    with pytest.raises(AssertionError, match=bound):
        check_sinad(v, CFG)


@pytest.mark.parametrize("bound", [b for _, b in LOWER + UPPER])
def test_a_missing_bound_is_not_a_pass(bound):
    cfg = {k: v for k, v in CFG.items() if k != bound}
    with pytest.raises(AssertionError, match="missing"):
        check_sinad(GOOD, cfg)
