"""Loop mode starts the DAC timer at a fixed phase of the ADC timer.

The two timers have no hardware sync, so a DAC start taken whenever the
service loop got there left the ADC sampling at the DAC's update edge in
about a fifth of runs: half the tone amplitude, a jumped A1 crosstalk,
and a loop-skew k of 1 or 2. Board-free: the start must go through the
phase-locked helper, and the helper must wait on the ADC counter.
"""
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES = ["drivers/play.c", "sketches/bringup/play.cpp"]
RAW = re.compile(r"TC0->TC_CHANNEL\[1\]\.TC_CCR\s*=\s*TC_CCR_CLKEN\s*\|\s*TC_CCR_SWTRG")


def _src(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def _func(src, name):
    i = src.index(f"{name}(")
    i = src.index("{", i)
    depth = 0
    for j in range(i, len(src)):
        depth += src[j] == "{"
        depth -= src[j] == "}"
        if depth == 0:
            return src[i:j]
    raise AssertionError(name)


@pytest.mark.parametrize("rel", FILES)
def test_play_service_starts_the_dac_through_the_locked_helper(rel):
    body = _func(_src(rel), "void play_service")
    assert "dac_timer_start_locked();" in body
    assert not RAW.search(body), "a raw DAC timer start is back in play_service"


@pytest.mark.parametrize("rel", FILES)
def test_the_helper_waits_on_the_adc_counter_and_is_bounded(rel):
    body = _func(_src(rel), "static void dac_timer_start_locked")
    assert "TC0->TC_CHANNEL[0]" in body and "TC_CV" in body
    assert "TC_SR_CLKSTA" in body, "no check that the ADC timer runs"
    assert re.search(r"for\s*\(uint32_t n = 0; n < cap", body), "unbounded wait"
    assert len(RAW.findall(body)) >= 2, "no fallback start after the cap"
