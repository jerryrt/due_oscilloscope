"""`tools/settletime.py`'s guards, board-free.

The fold reaches phase (k * RC_adc) mod period, so it covers every
position only when RC_adc is coprime with the period. A fixed request
once landed on RC 222 against a DAC RC of 225, gcd 3, and the fold
was read off a third of its bins. These tests hold that the RC is
chosen coprime, that a partial fold gives no figure, and that no
verdict against the stored scope range is returned.
"""
import math
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "host"))
sys.path.insert(0, os.path.join(REPO, "tools"))

import argparse                                                  # noqa: E402
import eqtime                                                    # noqa: E402
import measure                                                   # noqa: E402
import settletime                                                # noqa: E402

POINTS = 8
DAC_HZ = settletime.DAC_HZ


def _period():
    return eqtime.period_ticks(settletime.expected_rc_dac(DAC_HZ), POINTS)


def _square(rc_adc, n, period):
    """What the ADC reads of a 0..2700 square with a 40-tick ramp."""
    out = []
    for k in range(n):
        ph = (k * rc_adc) % period
        if ph < period // 2:
            out.append(min(2700.0, ph * 2700.0 / 40))
        else:
            ph -= period // 2
            out.append(max(0.0, 2700.0 - ph * 2700.0 / 40))
    return out


def _run(monkeypatch, rc_adc, n=30000):
    vals = _square(rc_adc, n, _period())
    monkeypatch.setattr(settletime, "capture",
                        lambda board, **kw: (vals, rc_adc, None))
    monkeypatch.setattr(settletime, "adc_lsb_v",
                        lambda: (0.0008, 3300, "test"))
    args = argparse.Namespace(points=POINTS, seconds=None, pre=80,
                              dac_hz=DAC_HZ, solo=False)
    return args


def test_rc_222_against_225_is_refused():
    assert math.gcd(222, 225) == 3
    with pytest.raises(SystemExit, match="gcd 3"):
        settletime.refuse_unless_coprime(222, 225)
    with pytest.raises(SystemExit):
        settletime.refuse_unless_coprime(222, _period())


def test_the_default_dac_rate_is_rc_225_at_this_clock():
    assert settletime.expected_rc_dac(DAC_HZ) == 225


def test_the_chosen_adc_rc_is_coprime_and_nearest():
    want = measure.rc_for(settletime.ADC_HZ)
    rc, hz = settletime.coprime_adc_rc(_period(), want)
    assert math.gcd(rc, _period()) == 1
    assert measure.rc_for(hz) == rc
    assert rc != 222
    # nothing coprime lies strictly nearer
    for d in range(abs(rc - want)):
        for c in (want - d, want + d):
            assert math.gcd(c, _period()) != 1


def test_a_full_fold_reports_a_rise_and_no_verdict(monkeypatch):
    rc, _ = settletime.coprime_adc_rc(_period(), 222)
    args = _run(monkeypatch, rc)
    out = settletime.cmd_rise(None, args)
    assert out["coverage"] == 1.0
    assert out["rise_s"] > 0
    assert "agrees" not in out


def test_a_partial_fold_gives_no_rise(monkeypatch):
    args = _run(monkeypatch, 222)
    assert eqtime.coverage(eqtime.reconstruct(
        _square(222, 30000, _period()), 222, _period())[1]) < 1.0
    with pytest.raises(SystemExit, match="coverage"):
        settletime.cmd_rise(None, args)
    with pytest.raises(SystemExit, match="coverage"):
        settletime.cmd_settle(None, args)
    with pytest.raises(SystemExit, match="coverage"):
        settletime.cmd_control(None, args)


def test_no_verdict_key_in_the_settle_result(monkeypatch):
    rc, _ = settletime.coprime_adc_rc(_period(), 222)
    out = settletime.cmd_settle(None, _run(monkeypatch, rc))
    assert "agrees" not in out
