"""The comb reading must find a planted comb and must not find one in noise.

`tools/issue5_spectrum.py` says the issue #5 site set is periodic: at
FWS 6 the six sites every bench draws are all congruent to 12 modulo 21.
A claim like that is only worth the instrument behind it, so this file
checks the instrument against cases whose answer is known before the
board is consulted.

The controls matter more than the positives here:

  * **Noise must not read as a comb.** The statistic is a maximum over
    ~126 candidate periods, so an uncorrected p-value calls a comb in
    scattered positions about half the time. The null is charged the
    same scan; `test_uniform_positions_are_not_a_comb` is what fails if
    that correction is ever dropped.
  * **Divisors must not be reported as the period.** A set congruent
    mod 21 is congruent mod 3 and mod 7 as well, and R is exactly 1.0
    at all three. Reporting the smallest was this tool's first
    behaviour, and it described the real data as "period 3" - true, and
    it would have hidden the lattice completely.
  * **The prediction has to be falsifiable.** On a dense lattice the
    unoccupied points are most of the record and no re-run could fail
    to confirm them, so the tool declines to predict there.

Needs no board.
"""
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))

import issue5_spectrum as sp  # noqa: E402

#: The set all five committed FWS 6 arms draw, before truncation.
REAL_FWS6 = [12, 33, 117, 138, 159, 180]


def test_a_planted_comb_is_found_with_its_generating_period():
    for period, offset in ((21, 12), (16, 3), (37, 5)):
        pts = sorted({(offset + period * k) % sp.BINS for k in range(6)})
        r, p = sp.best_comb(pts)
        assert r == pytest.approx(1.0, abs=1e-9), (period, pts)
        assert p == period, f"planted {period}, read {p} from {pts}"


def test_divisors_tie_and_the_generator_wins():
    """R is exactly 1.0 at 3, 7 and 21 for the real set. The tool must
    report 21 - the only one of the three that predicts anything."""
    assert sp.comb_score(REAL_FWS6, 3) == pytest.approx(1.0)
    assert sp.comb_score(REAL_FWS6, 7) == pytest.approx(1.0)
    assert sp.comb_score(REAL_FWS6, 21) == pytest.approx(1.0)
    assert sp.comb_score(REAL_FWS6, 42) < 0.5, "a multiple must not tie"
    assert sp.best_comb(REAL_FWS6)[1] == 21


def test_the_real_site_set_is_a_comb_and_significantly_so():
    r, p = sp.best_comb(REAL_FWS6)
    assert (r, p) == (pytest.approx(1.0, abs=1e-9), 21)
    # Valid on the rows that found the period: one scalar statistic,
    # the scan charged to the null as well.
    pv = sp.comb_pvalue(REAL_FWS6, ndraw=4000, seed=1)
    assert pv["p"] < 0.05
    # And the pre-registered test for rows taken after the period was
    # named - exact, no scan, far better powered. Not valid on these
    # rows; asserted here only so the instrument is known to work
    # before the campaign data it will be applied to exists.
    fp = sp.fixed_period_pvalue(REAL_FWS6, 21, ndraw=4000, seed=1)
    assert fp["R"] == pytest.approx(1.0) and fp["p"] <= 2.0 / 4001


def test_uniform_positions_are_not_a_comb():
    """The control. Scattered positions must not come back significant,
    and this is the assertion that fails if the scan correction is
    dropped from the null."""
    import random
    rng = random.Random(7)
    flagged = flagged_fixed = 0
    N = 40
    for _ in range(N):
        pts = sorted(rng.sample(range(sp.BINS), 6))
        if sp.comb_pvalue(pts, ndraw=1200, seed=3)["p"] < 0.05:
            flagged += 1
        if sp.fixed_period_pvalue(pts, 21, ndraw=1200, seed=3)["p"] < 0.05:
            flagged_fixed += 1
    # A calibrated 5% threshold puts about 2 of 40 here. The first
    # version of `comb_pvalue` scored 6 of 25 - it conjoined a second
    # condition onto the null and stopped being a p-value; this
    # assertion is what caught it.
    assert flagged <= 6, f"{flagged} of {N} uniform draws read as combs"
    assert flagged_fixed <= 6, (
        f"{flagged_fixed} of {N} uniform draws read as period-21 combs")


def test_lattice_names_the_unoccupied_points():
    L = sp.lattice(REAL_FWS6, 21)
    assert L["on_lattice"] == 6 and L["max_residual"] == 0
    assert L["occupied"] == REAL_FWS6
    # The pre-registered prediction, asserted so it cannot drift.
    assert sp.predict_missing(REAL_FWS6, 21) == [8, 54, 75, 96, 201, 222, 243]


def test_a_dense_lattice_predicts_nothing():
    """Period 3 puts 85 points on the lattice against 6 sites, so its
    'missing' list is unfalsifiable and must not be offered."""
    assert sp.predict_missing(REAL_FWS6, 3) is None


def test_dft_finds_a_planted_frequency():
    import math
    n = sp.BINS
    for k in (7, 16, 40):
        series = [math.sin(2 * math.pi * k * i / n) for i in range(n)]
        spec = sp.dft(series)
        assert max(range(1, len(spec)), key=lambda j: spec[j]) == k
        assert spec[k] == pytest.approx(1.0, abs=0.02)


def test_phase_table_reads_a_fixed_period_rather_than_fitting_one():
    """The cross-wait-state reading hands the period in. On the real
    FWS 6 set every site lands on one phase; a two-family set must show
    two."""
    t = sp.phase_table(REAL_FWS6, 21)
    assert t["histogram"] == {12: 6} and t["R"] == pytest.approx(1.0)
    two = sp.phase_table([75, 159, 180, 219, 240], 21)
    assert two["histogram"] == {9: 2, 12: 3}
    assert two["R"] < 1.0
