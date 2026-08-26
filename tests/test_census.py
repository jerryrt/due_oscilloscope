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


def test_a_splice_is_not_periodic_and_the_issue_5_signature_is():
    """The discrimination the suite rests on. A splice is one event; the
    open device artifact is a metronome at the DAC table length, and only
    the second may be excused."""
    v = staircase()
    once = measure.level_census(v[:100_000] + v[133_337:])
    assert once["count"] == 1
    assert not once["periodic"]

    # The shape the board actually produces: a staircase with one sample
    # displaced once per DAC table wrap.
    w = staircase(noise=2)
    for i in range(444, len(w), TABLE):
        w[i] |= 0x40
    metronome = measure.level_census(w)
    assert metronome["periodic"], metronome
    assert metronome["period"] == TABLE, metronome


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


# ---------------------------------------------------------------------
# The flat-channel census
#
# measure.flat_census() exists because the tests above are not enough.
# They pin the signature at +64 codes, which is what Windows reported and
# which level_census() sees comfortably at STEP_SPLICE_CODES = 45. On
# macOS the same signature arrives at 26-32 codes, under that threshold,
# and tools/splices.py reported 0 splices for ten runs while six runs in
# ten were displacing samples on A1. The instrument said "does not
# reproduce" about a board that was reproducing it.
# ---------------------------------------------------------------------

MACOS_DEV = 29                   # 26-32 measured; the middle of it


def flat(n=100_000, level=2055, noise=1, dev=0, first=318, period=TABLE):
    """A1 under preset `M`: DC 2048 out of DAC1, so a flat line plus ADC
    noise, optionally with one sample displaced every `period`."""
    rng = random.Random(20260825)
    v = [level + rng.randint(-noise, noise) for _ in range(n)]
    if dev:
        for i in range(first, n, period):
            v[i] += dev
    return v


def test_a_flat_line_has_no_events():
    c = measure.flat_census(flat())
    assert c["count"] == 0
    assert c["max_dev"] < measure.FLAT_DEV_CODES


def test_the_macos_signature_is_counted_once_per_occurrence():
    """+29 codes, once per DAC table wrap. Counted once per event, not
    twice: unlike the staircase census this measures deviation from the
    median rather than steps between levels, so one displaced sample is
    one crossing."""
    n = 100_000
    c = measure.flat_census(flat(n=n, dev=MACOS_DEV))
    assert c["count"] == len(range(318, n, TABLE)), c
    assert c["periodic"] and c["period"] == TABLE, c


def test_the_staircase_census_cannot_see_the_macos_signature():
    """The regression this pair of instruments exists to prevent.

    Not an assertion about what level_census() *should* do - it is
    judging steps against a 38-code DAC staircase and 29 is honestly
    below that. It is a record of why censusing A0 alone is not an
    answer, so that "splices.py reported zero" is never again read as
    "the board is clean".
    """
    v = flat(dev=MACOS_DEV)
    assert measure.level_census(v)["count"] == 0
    assert measure.flat_census(v)["count"] > 0


def test_the_windows_signature_is_seen_by_both():
    v = flat(dev=64)
    assert measure.level_census(v)["count"] > 0
    assert measure.flat_census(v)["count"] > 0


def test_the_flat_threshold_sits_in_an_empty_gap():
    lo, hi = measure.flat_census(flat(dev=MACOS_DEV))["gap"]
    assert lo <= measure.FLAT_DEV_CODES <= hi
    assert hi - lo >= 4


def test_a_single_displacement_is_not_periodic():
    """One event is not the device artifact, and must not be excused as
    one however small it is."""
    v = flat()
    v[50_000] += MACOS_DEV
    c = measure.flat_census(v)
    assert c["count"] == 1
    assert not c["periodic"]


def test_an_empty_series_is_not_an_error():
    assert measure.flat_census([])["count"] == 0
    assert measure.flat_census([2055])["count"] == 0
