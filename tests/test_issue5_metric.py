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
    with open(os.path.join(REPO, "records", name), encoding="utf-8") as fh:
        rows = [json.loads(l) for l in fh if l.strip()]
    return [r for r in rows if r["run"] != 1 and r["fws"] == fws]


def test_the_lattice_is_the_stated_comb():
    """Every point congruent to 12 mod 21 and inside one cycle, and the
    metric's set is a subset of it with every omission named."""
    assert m.LATTICE_FULL == [12 + 21 * k for k in range(12)]
    for b in m.LATTICE_FULL:
        assert b % 21 == 12 and b < 256
    assert set(m.OCCUPIED) <= set(m.LATTICE_FULL)
    assert sorted(m.OCCUPIED + m.UNOCCUPIED) == m.LATTICE_FULL
    # The metric is the occupied points minus the mode-dependent ones,
    # and nothing is dropped without appearing in one of the two lists.
    assert sorted(m.LATTICE + m.EXCHANGE) == m.OCCUPIED
    assert len(m.LATTICE) == 7


@pytest.mark.skipif(not CAMPAIGN, reason="no campaign records")
def test_the_exchange_sites_are_why_they_are_excluded():
    """They must actually be less stable across benches than the seven.

    The reason for excluding them is that they move with the severity
    mode, so a sum containing them is part mode occupancy - the defect
    this metric was written to fix in `total_abs`. If the three were as
    steady as the seven, the exclusion would be unjustified trimming.
    """
    if len(CAMPAIGN) < 3:
        pytest.skip("needs all three arms")
    def spread(pts):
        v = []
        for name in CAMPAIGN:
            rows = rows_of(name)
            rows = [r for r in rows
                    if not (r["bench"] == "linux-x1" and r["run"] == 31)]
            v.append(statistics.median(
                [sum(abs(x) for b, x, _z in r["sites"] if b in pts)
                 for r in rows]))
        return max(v) / min(v)
    assert spread(m.LATTICE) < spread(m.EXCHANGE), (
        f"seven-site spread {spread(m.LATTICE):.3f} is not tighter than "
        f"the exchange sites' {spread(m.EXCHANGE):.3f}")
    # And tighter than the set that includes them, which is the claim.
    assert spread(m.LATTICE) < spread(m.OCCUPIED)


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
    with open(src, encoding="utf-8") as fh:
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

@pytest.mark.skipif(not CAMPAIGN, reason="no campaign records")
def test_per_site_medians_come_from_the_profile_not_the_site_list():
    """A site list is thresholded, so a median over "runs where this
    position was a site" silently selects which runs contribute.

    On windows-desk position 75 clears threshold in 19 of 24 runs and the
    ones it misses are mostly high-mode, so the present-only median reads
    5.22 - its LOW-mode value - against 3.42 over all runs. The published
    "180 is half on iron" comparison was made with the biased figure.

    This asserts the two disagree where thresholding bites, so the tool
    cannot quietly go back to the site list, and agree where it does not.
    """
    name = "issue5-campaign-windows-desk.jsonl"
    if name not in CAMPAIGN:
        pytest.skip("windows-desk's arm is not here")
    v = rows_of(name)
    assert all(r.get("profile") for r in v)

    def present_only(b):
        vals = [abs(x) for r in v for bb, x, _z in r["sites"] if bb == b]
        return statistics.median(vals) if vals else None

    # 75 is the biased cell: present in fewer than every run.
    n75 = sum(1 for r in v if any(bb == 75 for bb, _x, _z in r["sites"]))
    assert n75 < len(v), "75 clears threshold everywhere; pick another cell"
    assert m.site_dev(v, 75) < present_only(75) * 0.8, (
        f"all-runs {m.site_dev(v, 75):.2f} against present-only "
        f"{present_only(75):.2f} - the bias should be large here")

    # 180 clears threshold in every run, so the two must agree there.
    n180 = sum(1 for r in v if any(bb == 180 for bb, _x, _z in r["sites"]))
    if n180 == len(v):
        assert m.site_dev(v, 180) == pytest.approx(present_only(180), rel=0.02)


@pytest.mark.skipif(not CAMPAIGN, reason="no campaign records")
def test_a_bimodal_arm_is_not_pooled_in_the_site_table(capsys):
    """180 is 13.72 in every windows-desk low-mode run and 19.70 in every
    high-mode one. No run sits at the pooled 16.74, so a pooled cell hides
    exactly what the table was added to show."""
    if "issue5-campaign-windows-desk.jsonl" not in CAMPAIGN:
        pytest.skip("windows-desk's arm is not here")
    sys.argv = ["issue5_metric.py"]
    m.main()
    out = capsys.readouterr().out
    assert "lo (n=" in out and "hi (n=" in out, (
        "a bimodal arm was pooled in the exchange-site table")


def test_every_issue5_tool_names_its_encoding():
    """Not one function - the whole class, across every `issue5_*` file.

    `tools/issue5_report.py` and its template carry 8 and 133 non-ASCII
    bytes, and every `open()` in that path used the locale default. On
    `windows-desk`, whose default is cp936, the report tests failed with
    `UnicodeDecodeError: 'gbk' codec can't decode byte 0x94` - 1 failed
    and 5 errors, on a bench where nothing had changed. They fixed those
    five sites in `fe2bf3b`.

    This test exists because the version it replaces checked ONE
    function, `issue5_metric.arms()`, and passed while seventeen other
    sites across ten files had the same defect - including three in
    `issue5_campaign.py`, one of which reads a source file during the
    preflight that gates a three-bench measurement.

    The encoding is not a platform branch and so does not belong behind
    `CLAUDE.md`'s `host/transport.py` seam: "read this file as UTF-8" is
    one uniform policy, correct everywhere, and the seam is for code that
    must *differ* by platform.

    Binary modes are exempt - they have no encoding to name.
    """
    import re
    files = ([os.path.join("tools", n) for n in sorted(os.listdir(
                os.path.join(REPO, "tools")))
              if n.startswith("issue5_") and n.endswith(".py")]
             + [os.path.join("tests", n) for n in sorted(os.listdir(
                 os.path.join(REPO, "tests")))
                if n.startswith("test_issue5") and n.endswith(".py")])
    assert len(files) >= 8, f"expected the issue5 family, found {files}"
    offenders = []
    for rel in files:
        with open(os.path.join(REPO, rel), encoding="utf-8") as fh:
            src = fh.read()
        for mt in re.finditer(r"(?<![.\w])open\s*\(\s*[^)\n]", src):
            j, depth = mt.end() - 1, 1
            while j < len(src) and depth:
                depth += (src[j] == "(") - (src[j] == ")")
                j += 1
            call = src[mt.start():j]
            if "encoding" in call or re.search(r"[\"'](?:rb|wb|ab)[\"']", call):
                continue
            offenders.append(f"{rel}:{src[:mt.start()].count(chr(10)) + 1}")
    assert not offenders, (
        "open() without encoding= in the #5 tools, which breaks on a "
        f"cp936 default the moment the file holds a non-ASCII byte: "
        f"{offenders}")

@pytest.mark.skipif(not CAMPAIGN, reason="no campaign records")
def test_a_sign_flipping_site_is_not_cancelled():
    """|median of deviations| cancels a site that changes sign; the
    metric must use median of |deviations|.

    `comb_from_profile` originally summed |median(signed)|, while
    `site_dev` summed median(|signed|). One file, two conventions. They
    agree on a unimodal arm and diverged by 7.95 on windows-desk - all of
    it at phase 201 (1.63 against 8.07) and phase 75 (1.91 against 3.42),
    because 201 CHANGES SIGN between that bench's two FWS 6 modes.

    A statistic that reports a site as nearly absent because it flips is
    measuring the sign, not the size, and it is the size this metric
    exists to measure. This pins the correct convention on the one arm
    where the two can be told apart.
    """
    name = "issue5-campaign-windows-desk.jsonl"
    if name not in CAMPAIGN:
        pytest.skip("the bimodal arm is not here")
    v = rows_of(name)
    assert all(r.get("profile") for r in v)

    def abs_of_median(b):
        return abs(statistics.median(
            [r["profile"][b] - statistics.median(r["profile"]) for r in v]))

    # Phase 201 is the discriminating case: large in every run, near zero
    # under the wrong convention.
    assert abs_of_median(201) < 3.0, "201 no longer straddles zero here"
    assert m.site_dev(v, 201) > 6.0
    # And the sum must use the convention that keeps it.
    assert m.comb_from_profile(v, m.OCCUPIED) == pytest.approx(
        sum(m.site_dev(v, b) for b in m.OCCUPIED), rel=1e-9), (
        "comb_from_profile and site_dev disagree about abs-vs-median order")
    # The wrong convention is measurably lower on this arm, so the
    # assertion above cannot pass by accident.
    wrong = sum(abs_of_median(b) for b in m.OCCUPIED)
    assert m.comb_from_profile(v, m.OCCUPIED) - wrong > 5.0
