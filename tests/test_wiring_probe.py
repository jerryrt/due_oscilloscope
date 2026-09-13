"""`tools/wiring_probe.py` may only say CONFIRMED when something moved.

Board-free: the verdict is a pure function of the rows, so it is fed
rows here. The probe exists because the first version of it confirmed a
wiring on bands that never moved - peak-to-peak with the default sync
square on, where both DAC pins swing full scale in both layouts - so the
cases below are the ways a wiring check reads as a pass without having
been able to fail.
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))

import wiring_probe as wp                                     # noqa: E402

# Medians measured on windows-desk, 2026-09-13, Track B at 1b2a2d1.
MEASURED = {
    ("off", 0): (2762, 26, 1554),
    ("off", 1): (25, 2774, 51),
    ("on", 0): (2763, 2780, 1559),
    ("on", 1): (2778, 2774, 1569),
}


def _rows(table, rounds=3):
    rows = []
    for rnd in range(rounds):
        for (sync, layout), (a0, a1, a2) in table.items():
            rows.append({"round": rnd, "sync": sync, "layout": layout,
                         "a0_ptp": a0, "a1_ptp": a1, "a2_ptp": a2})
    return rows


def test_the_measured_wiring_is_confirmed():
    """Not vacuous: the one table that should pass does."""
    code, lines = wp.verdict(_rows(MEASURED))
    assert code == 0, lines
    assert "CONFIRMED" in lines[-1]


def test_full_scale_on_both_pins_in_every_arm_is_not_a_confirmation():
    """The failure the first probe made. With sync left on, both DAC pins
    carry full scale in both layouts; a verdict that reads that as an
    exchange is a check that cannot fail."""
    sync_never_off = dict(MEASURED)
    sync_never_off[("off", 0)] = (2759, 2781, 1558)
    sync_never_off[("off", 1)] = (2777, 2775, 1570)
    code, lines = wp.verdict(_rows(sync_never_off))
    assert code == 2, lines
    assert "NOT confirmed" in lines[-1]


def test_a_positive_control_that_does_not_fire_answers_nothing():
    """If the sync-on arms do not show both pins driven, a small reading
    in the sync-off arms cannot be told from an instrument that sees
    nothing - so the verdict is NOT ANSWERED, not NOT confirmed."""
    dead = dict(MEASURED)
    dead[("on", 0)] = (2763, 30, 20)
    dead[("on", 1)] = (25, 2774, 20)
    code, lines = wp.verdict(_rows(dead))
    assert code == 1, lines
    assert "NOT ANSWERED" in lines[-1]


def test_a2_wired_to_a_dac_is_not_bare():
    """A jumper on A2 reads full scale in the arms where both DACs are at
    full scale, which is exactly where the check looks."""
    wired = {k: (a0, a1, max(a0, a1)) for k, (a0, a1, _a2) in MEASURED.items()}
    code, lines = wp.verdict(_rows(wired))
    assert code == 2, lines


def test_swapped_jumpers_are_not_the_declared_wiring():
    """DAC0 on A1 and DAC1 on A0: every reading exchanged."""
    swapped = {k: (a1, a0, a2) for k, (a0, a1, a2) in MEASURED.items()}
    code, lines = wp.verdict(_rows(swapped))
    assert code == 2, lines


def test_the_first_round_is_dropped_by_index_not_by_filter():
    """One round only, and it is round 0: nothing survives, so nothing is
    answered - even though that round alone would have confirmed."""
    code, lines = wp.verdict(_rows(MEASURED, rounds=1))
    assert code == 1, lines
