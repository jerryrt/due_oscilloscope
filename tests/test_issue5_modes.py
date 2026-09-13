"""The #5 mode classifier: what it can see, and what it must not invent.

Needs no board. The nulls are the point: a two-mode reading moves every
median comparison it touches, so a classifier that splits a unimodal
session would manufacture the result it was written to check. One null
is `linux-x1`'s FWS 6 shape - one tight mode and one outlier 40 below -
because that is the most likely wrong answer a real session offers.
"""
import json
import os
import random
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))
import issue5_modes as md  # noqa: E402

TRIALS = 2000


def _fires(draw, trials=TRIALS, seed=5):
    rng = random.Random(seed)
    return sum(md.classify(draw(rng))["modes"] == 2 for _ in range(trials))


@pytest.mark.parametrize("name", sorted(md.NULLS))
def test_unimodal_sessions_are_not_split(name):
    assert _fires(md.NULLS[name]) == 0


def test_null_mode_measures_what_the_nulls_assert():
    assert set(md.null_rates(trials=200)) == set(md.NULLS)
    assert all(rate == 0.0 for rate in md.null_rates(trials=200).values())


def test_null_mode_reports_a_rule_that_splits_noise(monkeypatch):
    """`--null` exists to put a number on a bad threshold, so it has to
    produce one: with the MAD criterion off, a noisy null must fire."""
    monkeypatch.setattr(md, "GAP_MAD", 0.0)
    monkeypatch.setattr(md, "GAP_REL", 0.0)
    assert max(md.null_rates(trials=200).values()) > 0.5


@pytest.mark.parametrize("hi", [15, 5])
def test_two_modes_far_apart_are_found_at_any_admissible_occupancy(hi):
    draw = lambda r: ([r.gauss(350, 2) for _ in range(24 - hi)]
                      + [r.gauss(445, 2) for _ in range(hi)])
    assert _fires(draw) == TRIALS


def test_the_detection_limit_is_stated_not_hidden():
    at = lambda sep: (lambda r: [r.gauss(350, 2) for _ in range(12)]
                      + [r.gauss(350 + sep, 2) for _ in range(12)])
    assert _fires(at(30)) > 0.9 * TRIALS
    assert _fires(at(15)) == 0


def _onimage(bench):
    path = os.path.join(REPO, "records", f"issue5-onimage-{bench}.jsonl")
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def test_a_one_mode_verdict_is_not_a_null():
    """`linux-x1`'s FWS 4 campaign arm: 14 runs to 42.0, nothing, then 10
    from 59.0 - and one mode, because the low side's MAD puts the gap at
    7.07x. Its onimage arm splits on a SMALLER gap. Pinned so the
    limitation is visible, and so a threshold change shows up here."""
    path = os.path.join(REPO, "records", "issue5-campaign-linux-x1.jsonl")
    with open(path, encoding="utf-8") as fh:
        wide = md.read([json.loads(line) for line in fh if line.strip()])[4]
    assert wide["modes"] == 1
    assert wide["gap"] == pytest.approx(17.0, abs=0.1)
    assert 7.0 < wide["gap_over_mad"] < 7.2
    narrow = md.read(_onimage("linux-x1"))[4]
    assert narrow["modes"] == 2 and narrow["gap"] < wide["gap"]


def test_onimage_fws6_readings_the_registration_was_written_from():
    win = md.read(_onimage("windows-desk"))[6]
    assert win["modes"] == 2 and (win["n_lo"], win["n_hi"]) == (8, 16)
    assert win["median_lo"] == pytest.approx(350.7, abs=0.1)
    assert win["median_hi"] == pytest.approx(446.7, abs=0.1)
    mac = md.read(_onimage("mac-bench-noprobes"))[6]
    assert mac["modes"] == 2 and (mac["n_lo"], mac["n_hi"]) == (14, 10)
    assert md.read(_onimage("linux-x1"))[6]["modes"] == 1


def test_run_one_is_dropped_by_index():
    """Run 1 sits inside a mode, so only a count can see it included.

    The first version put run 1 far above one tight mode and asserted
    one mode - which `MIN_SIDE` guarantees whether run 1 is dropped or
    not, so removing the drop left it green."""
    rows = [{"run": 1, "fws": 6, "total_abs": 350.0, "sites": []}]
    rows += [{"run": i, "fws": 6, "total_abs": (350.0 if i < 14 else 445.0)
              + (i % 3), "sites": []} for i in range(2, 26)]
    got = md.read(rows)[6]
    assert got["modes"] == 2 and (got["n_lo"], got["n_hi"]) == (12, 12)
    assert 1 not in got["runs_lo"]


def test_lattice_is_one_cycle():
    assert md.LATTICE == {12, 33, 54, 75, 96, 117, 138, 159, 180, 201, 222, 243}
