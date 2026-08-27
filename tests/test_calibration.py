"""The calibration record has one home, and one reader.

Board-free. What these protect is not the numbers - those are measured
elsewhere - but the arrangement: four things outside `tests/` used to
reach into a test fixture for the DAC's span and ADVREF, each with its
own copy of the loader and its own fallback policy. One of those copies
promised in a comment to say which value it had used and then did not.

Two homes for one number is the failure `docs/shared-source.md` is
about, and it had already gone wrong here in the other direction:
`dso_metrics.py` carried a third copy of the span as a bench note, 26-60
mV from the other two, and silently scaled every "codes" figure it
printed by about 4%.
"""
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "host"))
import calibration as cal  # noqa: E402


def test_the_record_is_where_the_module_says_it_is():
    assert os.path.exists(cal.PATH), cal.PATH
    assert os.path.basename(cal.PATH) == "calibration.json"


def test_the_measured_constants_are_read_as_measured():
    advref, source = cal.advref_mv()
    assert source == "measured"
    assert 3000 < advref < 3500, advref
    lo, hi, source = cal.dac_span_mv()
    assert source == "measured"
    assert 0 < lo < hi < 3300


def test_the_span_is_the_scope_derived_pair_not_the_retired_one():
    """The ADC-derived pair folds the ADC's own offset into the DAC's
    span and reads about 32 mV low at the bottom. It is kept in the
    record as history and must not be what anything uses."""
    lo, hi, _ = cal.dac_span_mv()
    d = cal.require()["dac_mv"]
    assert (lo, hi) != (d["adc_derived_span_lo"], d["adc_derived_span_hi"])


def test_an_unreadable_record_falls_back_to_a_specification(tmp_path):
    """A display is not worth refusing to start over, and a fallback
    should be the datasheet's nominal pair rather than some other
    measurement's leftovers."""
    missing = str(tmp_path / "nope.json")
    assert cal.advref_mv(missing) == (cal.NOMINAL_ADVREF_MV,
                                      "assumed (calibration.json unreadable)")
    assert cal.dac_span_mv(missing) == (cal.NOMINAL_SPAN_MV[0],
                                        cal.NOMINAL_SPAN_MV[1], "nominal")


def test_a_measuring_tool_refuses_rather_than_guessing(tmp_path):
    """The other half of the policy. A figure scaled by a guessed span
    looks exactly like a real measurement."""
    with pytest.raises(SystemExit) as e:
        cal.require(str(tmp_path / "nope.json"))
    assert "will not guess" in str(e.value)


def test_the_numbers_left_the_test_fixture_entirely():
    """One home. If these come back into baseline.json, something
    outside tests/ will read them from there again."""
    with open(os.path.join(HERE, "baseline.json")) as f:
        base = json.load(f)
    assert "dac_mv" not in base
    assert "adc_transfer" not in base


def test_nothing_outside_the_suite_opens_the_test_fixture():
    """The structural half, because the arrangement is what decays.

    An application reading a test fixture is wrong however true the
    number in it is: `baseline.json`'s stated job is regression
    tolerances, and the day someone treats it as the suite's working
    state, the front end's Y axis moves with it.
    """
    offenders = []
    for sub in ("host", "gui", "tools"):
        root = os.path.join(REPO, sub)
        for dirpath, dirnames, names in os.walk(root):
            dirnames[:] = [d for d in dirnames
                           if not d.startswith((".", "__"))
                           and not d.startswith("xpack")]
            for n in names:
                if not n.endswith(".py"):
                    continue
                p = os.path.join(dirpath, n)
                with open(p, encoding="utf-8", errors="replace") as f:
                    if '"tests", "baseline.json"' in f.read():
                        offenders.append(os.path.relpath(p, REPO))
    assert not offenders, (
        f"{offenders} build a path into the test fixture. Measured "
        f"constants live in calibration.json and are read through "
        f"host/calibration.py.")
