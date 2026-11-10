"""PAM-N patterns: the rules of docs/ets-pam.md, each held on its own.

Board-free. The independent oracle written on `linux-x1` from the same
document is compared with this module in tests/test_pam_oracle.py once both
exist; this file holds what this module must satisfy by itself.
"""
import math
import os
import sys
from fractions import Fraction

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "host"))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import etspattern  # noqa: E402
import ets_phase0  # noqa: E402

#: Symbols per period for each level count, from the table in the plan.
LENGTHS = {4: 127, 8: 127, 16: 511, 32: 2047, 64: 8191, 128: 65535, 256: 131071}


@pytest.mark.parametrize("n", sorted(etspattern.TAPS))
def test_every_order_is_maximal_and_balanced(n):
    bits = etspattern.prbs_bits(n)
    assert len(bits) == 2 ** n - 1
    assert sum(bits) == 2 ** (n - 1)


def test_order_seven_is_the_sequence_the_nrz_records_were_made_from():
    assert etspattern.prbs_bits(7) == ets_phase0.prbs7()


def test_a_register_that_is_not_maximal_is_refused(monkeypatch):
    monkeypatch.setitem(etspattern.TAPS, 7, (7, 5))
    with pytest.raises(ValueError):
        etspattern.prbs_bits(7)


def test_gray_decode_gives_the_pam4_ladder():
    assert [etspattern.gray_decode(g) for g in (0b00, 0b01, 0b11, 0b10)] == [0, 1, 2, 3]
    assert [etspattern.gray_decode(g) for g in range(8)] == [0, 1, 3, 2, 7, 6, 4, 5]


@pytest.mark.parametrize("pam", sorted(LENGTHS))
def test_each_level_count_puts_every_level_and_every_pair_on_the_wire(pam):
    p = etspattern.pattern(pam)
    assert p.length == LENGTHS[pam]
    levels, pairs = p.coverage()
    assert len(levels) == pam and len(pairs) == pam ** 2
    assert p.problems() == []


def test_pam128_on_order_15_loses_pairs_because_seven_divides_its_period():
    p = etspattern.pattern(128, n=15)
    assert math.gcd(7, 2 ** 15 - 1) == 7
    assert p.length == 4681 and len(p.coverage()[1]) == 4346
    assert any("symbol pairs" in x for x in p.problems()), p.problems()


def test_pam256_on_order_16_is_one_pair_short():
    """An order-16 sequence holds an all-zero run of 15, not 16, so the pair
    of two level-zero symbols never occurs."""
    p = etspattern.pattern(256, n=16)
    assert len(p.coverage()[1]) == 256 ** 2 - 1
    assert any("symbol pairs" in x for x in p.problems())


def test_the_pam4_ladder_is_the_one_in_the_plan():
    assert etspattern.level_codes(4) == [1123, 1740, 2356, 2973]


@pytest.mark.parametrize("pam", sorted(LENGTHS))
def test_the_level_codes_rise_by_at_least_two_codes_and_centre_on_mid_scale(pam):
    codes = etspattern.level_codes(pam)
    assert len(codes) == pam
    assert min(b - a for a, b in zip(codes, codes[1:])) >= 2
    assert abs(codes[0] + codes[-1] - 2 * etspattern.DAC_MID) <= 1


def test_the_level_codes_round_half_up_at_an_exact_boundary():
    """A swing of three codes puts the four levels on 2046.5, 2047.5, 2048.5
    and 2049.5 around mid-scale, exactly. Half up gives 2047 to 2050."""
    exact = Fraction(3 * 2214, 4095)
    assert etspattern.level_codes(4, swing_mv=exact) == [2047, 2048, 2049, 2050]


def test_a_level_count_that_is_not_a_power_of_two_is_refused():
    with pytest.raises(ValueError):
        etspattern.pattern(6)


def test_the_capture_time_for_the_longest_pattern_is_the_one_in_the_plan():
    p = etspattern.pattern(256)
    assert etspattern.period_ticks(p, 29) == 3_801_059
    assert abs(etspattern.capture_seconds(p, 29, 46) - 77.7) < 0.1
    assert abs(etspattern.capture_seconds(etspattern.pattern(128), 29, 46) - 38.9) < 0.1


def test_the_first_symbols_are_the_ones_derived_by_hand_from_the_register():
    """The register starts at all ones, outputs its lowest bit before it
    shifts, and its first steps give 1 0 0 0 0 0 0 1 0 0 0 0 0 1 1. Read two
    bits per symbol, first bit most significant, and Gray decoded, that is
    3 0 0 1 0 0 1; three bits per symbol it is 7 0 3 0 2. A reversed bit order
    or an output taken after the shift changes every one of them."""
    assert etspattern.prbs_bits(7)[:15] == [1, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 1, 1]
    assert etspattern.symbols(4)[:7] == [3, 0, 0, 1, 0, 0, 1]
    assert etspattern.symbols(8)[:5] == [7, 0, 3, 0, 2]


def test_the_scope_window_follows_the_swing():
    """The 2 V PAM64 swing ran off a 1.6 V window and the scope's ladder with it."""
    import os
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
    import ets_pam
    assert ets_pam.scope_scale(1000.0) == 0.2
    assert ets_pam.scope_scale(1500.0) == 0.5
    assert ets_pam.scope_scale(2000.0) == 0.5
    for swing in (1000.0, 1500.0, 2000.0, 2400.0):
        assert 8 * ets_pam.scope_scale(swing) >= swing / 1000.0 + 0.3, swing
    codes = etspattern.pattern(64, swing_mv=1500.0).codes
    assert abs((codes[-1] - codes[0]) * 2214 / 4095 - 1500.0) < 1.0, (codes[0], codes[-1])
