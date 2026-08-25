"""
The splice census. No board required.

measure.level_census() is the instrument that settled issue #5, and it
replaced a pass/fail check that had a real defect under it for a whole
session. An instrument that reports a defect nobody can reproduce is
worth less than no instrument, so it is tested here against waveforms
whose answer is known by construction: the device is not needed to know
that a clean staircase has no splices in it.

The numbers in the assertions are the ones measured on hardware over 25
runs across the two firmwares - 778-780 on every defective run, 0 on
every healthy one - and the synthetic signals below are built to the
same shape.
"""

import math
import random

import measure

FS = 200_000
AMPLITUDE = 1371
MID = 2048
TABLE = 512                      # gen's sine table, and the DAC ring slot


def staircase(n=200_000, hold=2, noise=0):
    """`gen`'s output as the ADC sees it: a level per table entry, each
    held for `hold` samples, stepping by up to ~38 codes."""
    rng = random.Random(20260825)
    tone = FS / TABLE
    out = []
    for i in range(n):
        level = i // hold
        v = MID + AMPLITUDE * math.sin(2 * math.pi * tone * level * hold / FS)
        out.append(round(v) + (rng.randint(-noise, noise) if noise else 0))
    return out


def test_a_clean_staircase_has_no_splices():
    """The DAC step is not a splice, however much larger it is than the
    derivative of the sine that shape approximates."""
    c = measure.level_census(staircase())
    assert c["count"] == 0
    assert c["max_step"] < measure.STEP_SPLICE_CODES


def test_adc_noise_does_not_become_a_splice():
    c = measure.level_census(staircase(noise=2))
    assert c["count"] == 0


def test_a_splice_is_counted():
    """Data joined from two points in time, which is invariant 5."""
    v = staircase()
    joined = v[:100_000] + v[133_337:]
    assert measure.level_census(joined)["count"] == 1


def test_the_issue_5_signature_is_counted_once_per_occurrence():
    """Issue #5 is not a splice: it sets bit 6 of one sample every
    PLAY_BUF_SAMPLES, once per DAC ring slot. On the flat channel that
    is a single-sample spike of +64 codes, which crosses the threshold
    going up and again coming down.

    It is counted here on a flat channel exactly as the hardware shows
    it, because the census must not depend on there being a waveform
    underneath - A1 is unconnected and it is where the signature was
    first seen cleanly.
    """
    v = [MID] * 100_000
    hits = list(range(444, len(v), TABLE))
    for i in hits:
        v[i] |= 0x40
    c = measure.level_census(v)
    assert c["count"] == 2 * len(hits)
    assert c["max_step"] >= 64


def test_the_threshold_sits_in_an_empty_gap():
    """The census reports the void it is judging in, so a later board
    that narrows it shows the number to move instead of hiding it."""
    lo, hi = measure.level_census(staircase(noise=2))["gap"]
    assert lo <= measure.STEP_SPLICE_CODES <= hi
    assert hi - lo >= 4


def test_a_flat_line_and_an_empty_series_are_not_errors():
    assert measure.level_census([])["count"] == 0
    assert measure.level_census([MID] * 1000)["count"] == 0
    assert measure.level_steps([MID]) == []
