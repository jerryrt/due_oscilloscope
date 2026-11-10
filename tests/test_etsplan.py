"""The RC pairing rule for equivalent-time PRBS captures.

Board-free. Each rule is held on its own, and the planner is held to its own
checker over a range of rates, so a plan the checker would refuse cannot be
returned.
"""
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "host"))
import etsplan  # noqa: E402
import etsperiod  # noqa: E402


def test_the_defaults_are_the_pairs_the_measurements_support():
    got = etsplan.plan()
    assert (got["rc_dac"], got["rc_adc"]) == (29, 46) and not got["problems"], got
    one = etsplan.plan(same_board=True)
    assert (one["rc_dac"], one["rc_adc"]) == (28, 45) and not one["problems"], one


def test_every_plan_is_accepted_by_its_own_checker_over_a_range_of_rates():
    for rc in range(28, 301):
        ind = etsplan.plan(rc_dac=rc)
        assert not ind["problems"], (rc, ind)
        assert ind["rc_dac"] % 2 == 1 and ind["rc_adc"] % 2 == 0, (rc, ind)
        assert math.gcd(ind["rc_adc"], ind["period"]) == 1, (rc, ind)
        same = etsplan.plan(rc_dac=rc, same_board=True)
        assert not same["problems"], (rc, same)
        assert math.gcd(same["rc_adc"], same["period"]) == 1, (rc, same)


def test_an_adc_rc_sharing_a_factor_of_four_with_the_period_is_refused_on_two_boards():
    got = etsplan.check_pair(28, 44, same_board=False)
    assert got["gcd"] == 4 and any("every 4th" in p for p in got["problems"]), got
    assert not etsplan.check_pair(28, 46, same_board=False)["problems"]
    assert not etsplan.check_pair(29, 44, same_board=False)["problems"]


def test_one_clock_demands_a_coprime_adc_rc_and_two_boards_do_not():
    assert etsplan.check_pair(28, 46, same_board=True)["problems"], (
        "a common factor of 2 on one clock was accepted: the fold would miss ticks")
    assert not etsplan.check_pair(28, 45, same_board=True)["problems"]


def test_the_notes_say_what_the_numbers_cost():
    odd = etsplan.check_pair(29, 45, same_board=False)
    assert not odd["problems"] and any("odd and even samples" in n for n in odd["notes"]), odd
    even_dac = etsplan.check_pair(28, 46, same_board=False)
    assert any("odd DAC RC avoids" in n for n in even_dac["notes"]), even_dac
    best = etsplan.check_pair(29, 46, same_board=False)
    assert any("best pairing" in n for n in best["notes"]), best


def test_the_floors_are_enforced():
    assert etsplan.check_pair(27, 46, same_board=False)["problems"]
    assert etsplan.check_pair(29, 40, same_board=False)["problems"]


def test_the_checker_uses_the_limit_the_tracker_uses():
    over = etsperiod.MAX_LATTICE_GCD + 1
    rc = next(r for r in range(44, 400, 2)
              if math.gcd(r, etsplan.period_ticks(28)) >= over)
    assert etsplan.check_pair(28, rc, same_board=False)["problems"]


def test_a_wanted_rate_picks_the_nearest_odd_dac_rc_on_two_boards():
    got = etsplan.plan(symbol_rate_hz=1_000_000)       # RC 45, already odd
    assert got["rc_dac"] == 45 and not got["problems"], got
    assert etsplan.plan(symbol_rate_hz=1_125_000)["rc_dac"] == 41    # RC 40 -> 41


def test_the_capture_script_plans_the_pair_for_the_pattern_it_was_asked_for():
    """PRBS11 is 2,047 = 23 * 89 symbols, so the default ADC RC 46 shares a
    factor of 23 with PAM32's period; the script must not take it."""
    import argparse
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import ets_cross
    four = argparse.Namespace(pam=4, rc=None, rc_adc=None)
    ets_cross.resolve_pair(four)
    assert (four.rc, four.rc_adc) == (29, 46)
    thirty_two = argparse.Namespace(pam=32, rc=None, rc_adc=None)
    ets_cross.resolve_pair(thirty_two)
    assert thirty_two.rc_adc != 46 and thirty_two.rc_adc % 2 == 0, thirty_two
    assert not etsplan.check_pair(thirty_two.rc, thirty_two.rc_adc, False, length=2047)["problems"]
    chosen = argparse.Namespace(pam=4, rc=None, rc_adc=44)
    ets_cross.resolve_pair(chosen)
    assert chosen.rc_adc == 44, "an ADC RC the user gave was replaced"
