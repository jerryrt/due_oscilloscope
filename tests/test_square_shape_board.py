"""The square's edge and shape at 100 kHz and 400 kHz, gated to recorded bands.

`square_gate_once` in tools/square_shape.py is the instrument. Rise and
fall times are bimodal one 22.2 ns tick apart, so the bounds allow both
modes; flatness and the 400 kHz/100 kHz swing ratio fail on a slow DAC
output stage. A failure is confirmed by one fresh measurement. The
control sets the DAC bias to zero and requires the same bounds to fail.
`baseline.json`'s `square_shape`.
"""

import os
import re
import sys

import pacing
from helpers import confirm_measurement, record

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import square_shape  # noqa: E402

MAX_KEYS = ("rise_ns_100k", "rise_ns_400k", "fall_ns_100k", "fall_ns_400k")
MIN_KEYS = ("vpp_frac_400k", "flat_hi_400k", "flat_lo_400k",
            "flat_hi_100k", "flat_lo_100k")
RESTORED_ACR = "0000010a"


def check_bound(values, cfg, key, upper):
    """Raise AssertionError unless `values[key]` is inside its bound."""
    name = key + ("_max" if upper else "_min")
    assert cfg.get(name) is not None, (
        f"tests/baseline.json square_shape.{name} is missing: the square "
        f"has not been measured, and a null is not a pass")
    assert values.get(key) is not None, f"{key} was not measured"
    if upper:
        assert values[key] <= cfg[name], (
            f"{key} {values[key]:.5g} is above the recorded bound "
            f"{name} {cfg[name]}")
    else:
        assert values[key] >= cfg[name], (
            f"{key} {values[key]:.5g} is below the recorded bound "
            f"{name} {cfg[name]}")


def check_square(values, cfg):
    """Raise AssertionError unless one `square_gate_once` result fits `cfg`."""
    for key in MAX_KEYS:
        check_bound(values, cfg, key, True)
    for key in MIN_KEYS:
        check_bound(values, cfg, key, False)


def read_acr(board):
    board.poll_console()
    board.cmd("?")
    txt = board.drain_console(pacing.REPORT) or ""
    m = re.search(r"acr=([0-9a-fA-F]+)", txt)
    return m.group(1) if m else None


def test_the_square_edge_and_shape_stay_inside_the_recorded_bands(
        board, baseline, calibration):
    cfg = baseline["square_shape"]
    last = []

    def once():
        last[:] = [square_shape.square_gate_once(board, pacing.STANDARD)]
        return last[0]

    outcome = {}
    try:
        outcome = confirm_measurement(once, lambda v: check_square(v, cfg))
    finally:
        if last:
            v = last[0]
            record(calibration, "square_shape", {
                "retried": outcome.get("retried", True),
                "first": outcome.get("first"),
                **{k: round(v[k], 5) for k in MAX_KEYS + MIN_KEYS
                   if v.get(k) is not None}})


def test_the_bias_zero_control_fails_the_square_check(
        board, baseline, calibration):
    cfg = baseline["square_shape"]
    try:
        c = square_shape.square_bias_control(
            board, seconds=pacing.STANDARD)
        record(calibration, "square_bias_zero", {
            k: round(v, 5) for k, v in c.items()})
        for key, ctl, upper in (
                ("rise_ns_400k", "rise_ns_biased", True),
                ("flat_hi_400k", "flat_hi_biased", False),
                ("vpp_frac_400k", "vpp_frac_biased", False)):
            raised = False
            try:
                check_bound({key: c[ctl]}, cfg, key, upper)
            except AssertionError:
                raised = True
            assert raised, (
                f"bias 0 read {ctl} {c[ctl]} and {key} still passed: "
                f"the check cannot see the output stage it guards")
    finally:
        acr = read_acr(board)
    assert acr is not None and acr.lower().lstrip("0") == \
        RESTORED_ACR.lstrip("0"), (
        f"DACC_ACR reads {acr} after the control, not the default "
        f"{RESTORED_ACR}: the bias was not restored")
