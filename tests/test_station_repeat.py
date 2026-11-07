"""tools/station_repeat.py: the summary drops run 1 by index, and only that."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import station_repeat as sr  # noqa: E402


def _row(label, run, rms, sinad=60.0, rc=86):
    return {"label": label, "run": run, "rc": rc,
            "noise": {"rms_lsb": rms}, "sinad": {"sinad_db": sinad,
                                                  "noise_floor_rms_lsb": 0.5}}


def test_run_one_is_dropped_even_when_it_looks_normal():
    # Run 1 reads 1.0, in line with the rest: a filter on "looks wrong"
    # would keep it; the index rule drops it, so n is 3 and the mean is
    # the mean of runs 2-4 alone.
    rows = [_row("a", 1, 1.0), _row("a", 2, 1.2), _row("a", 3, 1.3),
            _row("a", 4, 1.4)]
    st = sr.summarise(rows)[("a", 86)]
    assert st["n"] == 3
    assert abs(st["rms_lsb"]["mean"] - 1.3) < 1e-9


def test_only_run_one_of_each_group_is_dropped():
    rows = [_row("a", 1, 9.0), _row("a", 2, 1.0), _row("b", 1, 9.0),
            _row("b", 2, 2.0), _row("b", 1, 9.0, rc=225), _row("b", 2, 3.0, rc=225)]
    s = sr.summarise(rows)
    assert s[("a", 86)]["rms_lsb"]["mean"] == 1.0
    assert s[("b", 86)]["rms_lsb"]["mean"] == 2.0
    assert s[("b", 225)]["rms_lsb"]["mean"] == 3.0


def test_between_is_the_spread_of_condition_means():
    rows = [_row("a", 1, 0), _row("a", 2, 1.0), _row("b", 1, 0),
            _row("b", 2, 2.0)]
    sd, k = sr.between(sr.summarise(rows), "rms_lsb")[86]
    assert k == 2 and abs(sd - 0.7071067811865476) < 1e-9
