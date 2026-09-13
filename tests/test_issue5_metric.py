"""The comb metric must have one definition, and must refuse truncated rows.

`tools/issue5_metric.py` proposes replacing `total_abs` as the campaign's
cross-bench figure at FWS 6. Two benches independently computed "the comb
sum" and got 238.1 and 193.2 - a 19% disagreement on the metric itself -
and several different 7-of-10 subsets of the lattice reproduce 193 to
within a code, so the definition cannot be recovered by fitting it to the
number. That is what a proposed metric with no implementation in the tree
costs, and it is why this file exists.

What is asserted:

  * the two independent estimators agree. `split()` sums per run over the
    site list; `comb_from_profile()` sums the median profile at the
    lattice points. They are different routes to one quantity and they
    must stay within a few percent of each other, so a third definition
    cannot appear in this file unnoticed.
  * the metric refuses the truncated `issue5-onimage-*` rows. Those store
    the strongest six sites, which at FWS 6 are all on the lattice, so
    the metric would read ~100% on-lattice by construction - a number
    that looks like a clean result and means nothing.
  * the lattice is the stated comb and not a set fitted to the data.
  * a collapsed comb is named, not filtered.

Needs no board.
"""
import json
import os
import statistics
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))

import issue5_metric as m  # noqa: E402

CAMPAIGN = [f for f in os.listdir(os.path.join(REPO, "records"))
            if f.startswith("issue5-campaign-") and f.endswith(".jsonl")]


def rows_of(name, fws=6):
    with open(os.path.join(REPO, "records", name)) as fh:
        rows = [json.loads(l) for l in fh if l.strip()]
    return [r for r in rows if r["run"] != 1 and r["fws"] == fws]


def test_the_lattice_is_the_stated_comb():
    """Every point congruent to 12 mod 21 and inside one cycle, and the
    metric's set is a subset of it with the omissions named."""
    assert m.LATTICE_FULL == [12 + 21 * k for k in range(12)]
    for b in m.LATTICE_FULL:
        assert b % 21 == 12 and b < 256
    assert set(m.LATTICE) <= set(m.LATTICE_FULL)
    assert sorted(m.LATTICE + m.UNOCCUPIED) == m.LATTICE_FULL


@pytest.mark.skipif(not CAMPAIGN, reason="no campaign records")
@pytest.mark.parametrize("name", CAMPAIGN)
def test_the_two_estimators_agree(name):
    """The guard against a third definition. Both routes on real rows."""
    v = rows_of(name)
    assert v, name
    a = statistics.median([m.split(r)[0] for r in v])
    b = m.comb_from_profile(v)
    assert a == pytest.approx(b, rel=0.05), (
        f"{name}: site-list route {a:.2f} against profile route {b:.2f} - "
        f"two definitions of one metric")


@pytest.mark.skipif(not CAMPAIGN, reason="no campaign records")
def test_the_estimators_disagree_when_one_is_sabotaged():
    """Break-on-purpose: the agreement above must be capable of failing.

    Drop one lattice point from the profile route only. If the assertion
    still passes, it was not comparing the two routes at all.
    """
    v = rows_of(CAMPAIGN[0])
    a = statistics.median([m.split(r)[0] for r in v])
    b = m.comb_from_profile(v, lattice=m.LATTICE[1:])
    assert a != pytest.approx(b, rel=0.05), (
        "dropping a lattice point did not move the profile estimator")


def test_truncated_rows_are_refused(tmp_path, monkeypatch):
    """The onimage rows store six sites, all of them on the lattice at
    FWS 6, so this metric would read ~100% on-lattice on them. It must
    refuse rather than report a number that cannot be wrong."""
    src = os.path.join(REPO, "records", "issue5-onimage-linux-x1.jsonl")
    if not os.path.exists(src):
        pytest.skip("no onimage record")
    with open(src) as fh:
        rows = [json.loads(l) for l in fh if l.strip()]
    assert rows and "n_sites" not in rows[0], (
        "the onimage rows are supposed to be the truncated ones")
    (tmp_path / "issue5-campaign-fake.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows))
    monkeypatch.setattr(m, "RECORDS", str(tmp_path))
    monkeypatch.setattr(sys, "argv", ["issue5_metric.py"])
    assert m.main() == 2, "a truncated arm was given a comb figure"


@pytest.mark.skipif(not CAMPAIGN, reason="no campaign records")
def test_a_collapsed_comb_is_named_not_filtered(capsys):
    """linux-x1's run 31 collapsed to 28% of its peers. The summary must
    say so - a range of 72.7% otherwise reads as an unstable bench."""
    if "issue5-campaign-linux-x1.jsonl" not in CAMPAIGN:
        pytest.skip("linux-x1's arm is not here")
    sys.argv = ["issue5_metric.py"]
    m.main()
    out = capsys.readouterr().out
    assert "COLLAPSED" in out and "[31]" in out
    # And the honest range is reported beside the inflated one.
    assert "without them" in out
