"""`tools/settle_trend.py`'s pure logic, board-free.

What is held here: `figure()` reports a rate with its own denominator
next to it (this project has already paid once tonight for a rate
with no `n` beside it reading as a spike - docs/noise.md's gen_sweep
tables), never a bare count that silently assumes every bin/repeat is
the same size; and the CLI refuses a partial `--control` pin rather
than silently falling back to ambiguous auto-discovery, which is
exactly the failure mode records/wiring-mac-bench-two-dut-2026-09-21.jsonl
documents for a bench running more than one Track B board.
"""
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(REPO, "tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)
sys.path.insert(0, os.path.join(REPO, "host"))

import settle_trend as st                                      # noqa: E402
import measure                                                   # noqa: E402


def test_figure_reports_a_rate_with_its_denominator():
    # A staircase with one real 50-code step among small noise - shaped
    # like a genuine capture, not flat noise, so level_census() takes
    # its ordinary path rather than an early "no steps" return.
    vals = [1500] * 40 + [1550] * 40 + [1500] * 20
    row = st.figure(measure, vals)
    assert row["n"] == len(vals)
    assert row["count"] >= 1
    # count_per_1e6 is count scaled to a fixed denominator, computable
    # back from count and n alone - if it drifted from that it would
    # no longer mean what its name says.
    expect = round(row["count"] / row["n"] * 1e6, 2)
    assert row["count_per_1e6"] == expect


def test_figure_on_empty_input_does_not_divide_by_zero():
    row = st.figure(measure, [])
    assert row["n"] == 0
    assert row["count_per_1e6"] is None


def test_two_captures_of_different_length_are_not_compared_by_raw_count():
    """The point of count_per_1e6 existing at all: two chunks with the
    same underlying pattern but different lengths must not read as
    different severity just because one is longer - raw count grows
    with length, the rate should not (once each chunk is long enough
    that the one-fewer-transition-than-level edge effect is negligible
    - a 3-cycle chunk is not, which is its own real, separate fact
    about level_census() worth knowing and is checked below instead of
    papered over with a loose tolerance)."""
    long_a = ([1500] * 20 + [1550] * 20) * 200
    long_b = long_a * 5
    r_a = st.figure(measure, long_a)
    r_b = st.figure(measure, long_b)
    assert abs(r_a["count_per_1e6"] - r_b["count_per_1e6"]) \
        / r_a["count_per_1e6"] < 0.01
    # Raw count must NOT have stayed close - it is a function of length,
    # which is exactly why it is the wrong number to compare on.
    assert r_b["count"] > r_a["count"]


def test_a_short_chunk_undercounts_its_own_rate_at_the_edge():
    """level_census() counts TRANSITIONS (levels - 1), so a chunk with
    only a few levels reports a rate biased low relative to the
    asymptotic one - real behaviour of the counting method, not a bug
    in figure(). Binning too finely (a --bin-seconds much shorter than
    this signal's own period) would reproduce exactly this bias in a
    real run, which is why it is worth a named test rather than a
    surprise the first time someone picks an aggressive bin size."""
    short = ([1500] * 20 + [1550] * 20) * 3
    long_ = short * 200
    r_short = st.figure(measure, short)
    r_long = st.figure(measure, long_)
    assert r_short["count_per_1e6"] < r_long["count_per_1e6"]


def test_a_partial_pin_is_refused_at_the_cli_not_silently_ignored():
    """--control alone (or any two of the three) must not fall through
    to measure.Board()'s default discovery, which cannot tell two
    Track B boards apart - see the module docstring and 86804d6."""
    r = subprocess.run(
        [sys.executable, os.path.join(TOOLS, "settle_trend.py"),
         "--control", "/dev/cu.usbmodemFAKE"],
        capture_output=True, text=True)
    assert r.returncode != 0
    assert "together or not at all" in r.stderr


def test_no_pin_arguments_at_all_parses_past_the_pin_check():
    """The common case - one board on a bench - must not be forced
    through the pin validation. This only checks argument PARSING
    reaches board discovery; it does not open a board, so it is safe
    to run with none attached."""
    r = subprocess.run(
        [sys.executable, os.path.join(TOOLS, "settle_trend.py"),
         "--repeats", "0"],
        capture_output=True, text=True)
    # repeats=0 means the loop body never runs, so this either exits 0
    # (no board needed, capture loop is empty) or fails inside board
    # discovery/open - either way it must NOT be the pin-validation
    # error, which is the one thing this test is checking.
    assert "together or not at all" not in r.stderr


def test_a_clean_zero_repeat_is_not_dropped_from_the_spread_line():
    """A genuinely clean repeat (count=0, common on a quiet board) has
    count_per_1e6 == 0.0. Found running this for real: the first
    version filtered on truthiness rather than `is not None`, so a
    board that was clean in 5 of 10 repeats reported "5 repeats" in
    the spread line instead of 10 - the exact quiet-board case this
    line exists to describe, vanishing from its own summary."""
    whole = [{"count_per_1e6": 0.0}] * 5 + [{"count_per_1e6": 0.02}] * 5
    line = st.spread_line(whole)
    assert "10 repeats" in line


def test_no_repeats_or_one_repeat_produces_no_spread_line():
    assert st.spread_line([]) == ""
    assert st.spread_line([{"count_per_1e6": 0.0}]) == ""
