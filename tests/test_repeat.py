"""Phase 0's arithmetic, on synthetic series and no bench.

The reason these exist is on issue #6. Six real bugs in one experiment's
analysis were caught by synthetic tests rather than by a bench run, and
two of them produced confident wrong *positive* results - a
repeatability check that reported "same place, same sign, every round"
on residuals that were all exactly zero, because `max(..., key=abs)`
over a flat array returns index 0 every time and the control arm
reproduced it just as tightly.

A repeatability harness is exactly the kind of code that fails that way:
its output is a small number, a small number looks like agreement, and
agreement is what it is being asked to find. So every case here has a
known answer, and the flat-series cases are here specifically because
they are the ones that lie convincingly.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "host"))
import repeat  # noqa: E402


# ------------------------------------------------------------------
# flatten
# ------------------------------------------------------------------

def test_flatten_joins_nested_dicts_with_dots():
    assert repeat.flatten({"a": {"b": 2.0}}) == {"a.b": 2.0}


def test_a_labelled_row_is_named_by_its_band_not_its_position():
    """`settle` returns one row per band and a run that skipped a band
    must still line up with one that did not. Position would silently
    compare the 2-code band against the 1-code band."""
    got = repeat.flatten({"bands": [{"codes": 2.0, "last_s": 1e-4},
                                    {"codes": 1.0, "last_s": 2e-4}]})
    assert got == {"bands.2.last_s": 1e-4, "bands.1.last_s": 2e-4}


def test_a_row_with_no_label_falls_back_to_its_position():
    got = repeat.flatten({"rows": [{"x": 1.0}, {"x": 2.0}]})
    assert got == {"rows.0.x": 1.0, "rows.1.x": 2.0}


def test_non_numbers_are_dropped_rather_than_stringified():
    """A spread is something you can take of a series. A field that is
    not a number is not part of one, and carrying it as a string would
    put it in the report as if it were."""
    got = repeat.flatten({"n": 3, "note": "window-limited", "gap_s": None})
    assert got == {"n": 3}


def test_infinities_and_nans_do_not_reach_the_record():
    got = repeat.flatten({"a": float("inf"), "b": float("nan"), "c": 1.0})
    assert got == {"c": 1.0}


def test_booleans_survive_as_zero_and_one():
    """Whether a row hit the instrument's window limit is a fact whose
    run-to-run stability is worth seeing, and `step` reports exactly
    that."""
    got = repeat.flatten({"points": [{"timebase_s": 1e-6,
                                      "settle_window_limited": True}]})
    assert got == {"points.1e-06.settle_window_limited": 1}


def test_comment_keys_are_not_measurements():
    assert repeat.flatten({"_comment": {"a": 1.0}, "b": 2.0}) == {"b": 2.0}


# ------------------------------------------------------------------
# summarise
# ------------------------------------------------------------------

def test_spread_is_what_was_observed():
    st = repeat.summarise([10.0, 11.0, 12.0])
    assert st["n"] == 3
    assert st["spread"] == pytest.approx(2.0)
    assert st["median"] == pytest.approx(11.0)


def test_half_width_is_not_half_the_spread_on_an_asymmetric_series():
    """The distinction a symmetric tolerance lives or dies on. Median 1,
    range 0 to 10: half the spread is 5 and a +-5 band misses the 10."""
    st = repeat.summarise([0.0, 1.0, 1.0, 10.0])
    assert st["spread"] == pytest.approx(10.0)
    assert st["half_width"] == pytest.approx(9.0)


def test_a_flat_series_has_no_spread_and_says_so():
    """The case that lies. Seven identical readings are either a very
    stable metric or a measurement that is not connected to anything,
    and this cannot tell them apart - so it must not dress the second
    one up as the first."""
    st = repeat.summarise([4.0] * 7)
    assert st["spread"] == 0.0
    assert st["half_width"] == 0.0
    assert st["stdev"] == 0.0
    assert st["spread_rel"] == 0.0


def test_a_zero_median_gives_no_relative_spread_rather_than_infinity():
    st = repeat.summarise([-1.0, 0.0, 1.0])
    assert st["spread_rel"] is None


def test_missing_points_are_counted_not_quietly_dropped():
    """A run that produced no value for a key did something different,
    and a spread over the runs that worked cannot show that."""
    st = repeat.summarise([1.0, None, 2.0])
    assert st["n"] == 2 and st["n_missing"] == 1


def test_an_empty_series_is_n_zero_and_nothing_else():
    assert repeat.summarise([]) == {"n": 0}


# ------------------------------------------------------------------
# tolerance
# ------------------------------------------------------------------

def test_one_point_yields_no_tolerance():
    """One reading has no repeatability. A tolerance derived from it
    would be zero, which is the tightest possible lie."""
    assert repeat.suggest_tolerance(repeat.summarise([1.0])) is None


def test_the_tolerance_is_a_stated_multiple_of_the_observed_half_width():
    st = repeat.summarise([10.0, 12.0])
    assert repeat.suggest_tolerance(st) == pytest.approx(2.0 * 1.0)


def test_a_floor_stops_a_tolerance_claiming_to_beat_the_ruler():
    """A spread smaller than one screen level is a property of the
    instrument's quantiser, not of the converter."""
    st = repeat.summarise([10.0, 10.0, 10.0])
    assert repeat.suggest_tolerance(st, floor=0.25) == pytest.approx(0.25)


def test_an_entry_carries_the_evidence_and_not_only_the_number():
    e = repeat.entry(repeat.summarise([1.0, 1.5, 2.0]), "in-place")
    assert e["n"] == 3
    assert e["spread"] == pytest.approx(1.0)
    assert e["axis"] == "in-place"
    assert "half-width" in e["tolerance_from"]


# ------------------------------------------------------------------
# series, keys, axes
# ------------------------------------------------------------------

def _rec(i, axis, values, error=None):
    return {"run": i, "axis": axis, "metric": "settle",
            "values": values, "error": error}


def test_a_failed_run_contributes_no_values():
    recs = [_rec(0, "in-place", {"a": 1.0}),
            _rec(1, "in-place", {}, error="no coarse capture"),
            _rec(2, "in-place", {"a": 3.0})]
    assert repeat.series(recs, "a") == [1.0, 3.0]


def test_the_order_runs_were_taken_in_is_preserved():
    """A drift and a scatter have the same spread and are different
    findings. Only the sequence separates them."""
    recs = [_rec(i, "in-place", {"a": float(i)}) for i in range(4)]
    assert repeat.series(recs, "a") == [0.0, 1.0, 2.0, 3.0]


def test_keys_are_a_union_so_a_key_seen_once_is_not_hidden():
    recs = [_rec(0, "in-place", {"a": 1.0}),
            _rec(1, "in-place", {"a": 2.0, "b": 9.0})]
    assert repeat.keys(recs) == ["a", "b"]


def test_summarise_all_separates_the_axes():
    recs = ([_rec(i, "in-place", {"a": 10.0}) for i in range(3)]
            + [_rec(i, "reflash", {"a": 10.0 + i}) for i in range(3)])
    s = repeat.summarise_all(recs)
    assert s["in-place"]["keys"]["a"]["spread"] == 0.0
    assert s["reflash"]["keys"]["a"]["spread"] == pytest.approx(2.0)


def test_summarise_all_reports_failures_per_axis():
    recs = [_rec(0, "in-place", {"a": 1.0}),
            _rec(1, "in-place", {}, error="only 3 samples on screen")]
    s = repeat.summarise_all(recs)
    assert s["in-place"]["runs"] == 2 and s["in-place"]["failed"] == 1
    assert s["in-place"]["errors"] == ["only 3 samples on screen"]


# ------------------------------------------------------------------
# the axis question itself
# ------------------------------------------------------------------

def test_an_axis_that_bought_nothing_reads_as_a_ratio_of_one():
    recs = ([_rec(i, "in-place", {"a": 10.0 + i}) for i in range(3)]
            + [_rec(i, "reflash", {"a": 10.0 + i}) for i in range(3)])
    rows = repeat.compare_axes(repeat.summarise_all(recs),
                               "in-place", "reflash")
    assert rows[0]["ratio"] == pytest.approx(1.0)


def test_the_worst_key_sorts_first_because_it_decides_the_axis():
    recs = ([_rec(i, "in-place", {"a": 10.0 + i, "b": 10.0 + i})
             for i in range(3)]
            + [_rec(i, "reflash", {"a": 10.0 + i, "b": 10.0 + 5 * i})
               for i in range(3)])
    rows = repeat.compare_axes(repeat.summarise_all(recs),
                               "in-place", "reflash")
    assert [r["key"] for r in rows] == ["b", "a"]
    assert rows[0]["ratio"] == pytest.approx(5.0)


def test_no_in_place_movement_gives_no_ratio_rather_than_infinity():
    recs = ([_rec(i, "in-place", {"a": 10.0}) for i in range(3)]
            + [_rec(i, "reflash", {"a": 10.0 + i}) for i in range(3)])
    rows = repeat.compare_axes(repeat.summarise_all(recs),
                               "in-place", "reflash")
    assert rows[0]["ratio"] is None


# ------------------------------------------------------------------
# the record itself
# ------------------------------------------------------------------

def test_a_run_is_on_disk_before_the_next_one_starts(tmp_path):
    """The whole reason this is JSON Lines. `--calibrate` wrote at
    session end, a run hung at 90%, and twelve minutes of bench time
    yielded nothing."""
    p = tmp_path / "r.jsonl"
    rec = repeat.Recorder(str(p))
    rec.add(_rec(0, "in-place", {"a": 1.0}))
    assert len(repeat.load(str(p))) == 1
    rec.add(_rec(1, "in-place", {"a": 2.0}))
    assert repeat.series(repeat.load(str(p)), "a") == [1.0, 2.0]


def test_a_truncated_last_line_costs_only_that_run(tmp_path):
    p = tmp_path / "r.jsonl"
    rec = repeat.Recorder(str(p))
    rec.add(_rec(0, "in-place", {"a": 1.0}))
    with open(p, "a") as f:
        f.write('{"run": 1, "axis": "in-pl')
    assert repeat.series(repeat.load(str(p)), "a") == [1.0]


def test_loading_a_record_that_does_not_exist_is_not_an_error(tmp_path):
    assert repeat.load(str(tmp_path / "nothing.jsonl")) == []


def test_the_record_is_json_a_report_generator_can_read(tmp_path):
    """Item 7 on issue #6 reads these. One line, one run, sorted keys -
    so a diff between two records is about the numbers."""
    p = tmp_path / "r.jsonl"
    repeat.Recorder(str(p)).add(_rec(0, "in-place", {"b": 1.0, "a": 2.0}))
    line = p.read_text().strip()
    assert json.loads(line)["values"] == {"a": 2.0, "b": 1.0}
    assert line.index('"axis"') < line.index('"values"')
