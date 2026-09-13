"""A truncated site list must announce itself, and must not be compared
against a full one.

`tools/issue5_sites.py` stored `found[:6]` until 2026-09-13. `found` is
ordered by descending |deviation|, so that kept the six strongest sites
and dropped the rest with nothing in the row to say so. At FWS 6 it
truncated **every row of every bench** in the cross-bench arm the freeze
was called for: the six recorded sites hold 40-55% of `total_abs` there,
and phases 180 and 247 were never once recorded together in 120 runs
because they were competing for the sixth slot. That reads as an
incidence and is a cap.

Three things are asserted here, and each is a control for one of the
others:

  * `censored()` is exact - it recovers the dropped total on a synthetic
    profile with a known number of planted spikes, and reads zero when
    nothing was dropped. The zero cases are the negative control: a
    detector that fires on everything would satisfy the positive ones.
  * The committed FWS 6 rows are all censored and the committed FWS 4
    rows mostly are not. This is the control on real data - if the
    arithmetic were wrong in a way the synthetics missed, it would have
    to be wrong identically on both.
  * The comparison refuses to read a truncated set against a full one,
    because a short list disagrees at every phase it could not reach.

Needs no board.
"""
import json
import os
import statistics
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "host"))
sys.path.insert(0, os.path.join(REPO, "tools"))

import measure  # noqa: E402
import issue5_onimage_compare as cmp  # noqa: E402

RECORDS = os.path.join(REPO, "records")


def planted(n, size=256):
    """A flat profile with `n` spikes of known, distinct magnitude."""
    prof = [0.0] * size
    for i in range(n):
        prof[20 * i + 5] = (40.0 - 2.0 * i) * (-1) ** i
    return prof


def row_from(profile, keep):
    """The row `issue5_sites.py` would have written, keeping `keep` sites."""
    found, _mad = measure.fold_sites(profile)
    return {"site_abs": round(sum(abs(v) for _b, v, _z in found), 2),
            "sites": [[b, round(v, 2), round(z, 1)]
                      for b, v, z in found[:keep]]}, found


@pytest.mark.parametrize("n", [3, 6, 7, 9, 12])
def test_censored_recovers_exactly_what_was_dropped(n):
    row, found = row_from(planted(n), keep=6)
    dropped = sum(abs(v) for _b, v, _z in found[6:])
    assert len(found) == n, "the planted spikes must all be found"
    assert cmp.censored(row) == pytest.approx(dropped, abs=cmp.CENSOR_EPS)


@pytest.mark.parametrize("n", [3, 6])
def test_censored_reads_zero_when_nothing_was_dropped(n):
    """The negative control. A detector that cannot read zero proves
    nothing when it reads non-zero."""
    row, _ = row_from(planted(n), keep=6)
    assert cmp.censored(row) <= cmp.CENSOR_EPS


def test_censored_reads_zero_on_a_full_list():
    """And the same profile stored whole is clean however many sites it
    has - so the detector is reading the truncation, not the count."""
    row, found = row_from(planted(12), keep=99)
    assert len(row["sites"]) == 12
    assert cmp.censored(row) <= cmp.CENSOR_EPS


def _onimage(fws):
    out = {}
    for name in sorted(os.listdir(RECORDS)):
        if not (name.startswith("issue5-onimage-") and name.endswith(".jsonl")):
            continue
        with open(os.path.join(RECORDS, name), encoding="utf-8") as fh:
            rows = [json.loads(l) for l in fh if l.strip()]
        out[name] = [r for r in rows if r.get("fws") == fws]
    return out


def test_every_committed_fws6_row_is_censored():
    """The finding itself, asserted so it cannot be quietly un-noticed
    if someone re-derives these rows."""
    files = _onimage(6)
    assert len(files) >= 3, "the cross-bench arm should be here"
    for name, rows in files.items():
        assert rows, name
        hidden = [cmp.censored(r) for r in rows]
        assert all(h > cmp.CENSOR_EPS for h in hidden), (
            f"{name}: {sum(1 for h in hidden if h <= cmp.CENSOR_EPS)} of "
            f"{len(rows)} FWS 6 rows read as complete")
        # And the truncation is material, not a rounding tail.
        assert statistics.median(hidden) > 50.0, name


def test_the_uncensored_rows_read_as_uncensored():
    """The control on real data. If every row read as censored the test
    above would pass on a broken detector."""
    clean = dirty = 0
    for rows in _onimage(4).values():
        for r in rows:
            if len(r["sites"]) < 6:
                # It cannot have been truncated: the slice was 6.
                assert cmp.censored(r) <= cmp.CENSOR_EPS
                clean += 1
            else:
                dirty += 1
    assert clean > 50, f"only {clean} rows could act as the control"


def test_a_truncated_set_is_not_compared_against_a_full_one(tmp_path,
                                                            monkeypatch,
                                                            capsys):
    """Break-on-purpose: with both sides truncated the tool compares and
    warns; with one side full it must refuse. The two cases differ only
    in whether one file's rows carry their seventh site."""
    def write(name, bench, keep):
        rows = []
        for run in range(1, 13):
            prof = planted(9)
            row, found = row_from(prof, keep=keep)
            row.update(run=run, bench=bench, fws=6, total_abs=500.0,
                       fw_repo_rev="1b2a2d1", fw_layout="deadbeef",
                       fw_build_env="container", preset="=200000,200000M",
                       track="b")
            rows.append(row)
        (tmp_path / name).write_text(
            "".join(json.dumps(r) + "\n" for r in rows))

    monkeypatch.setattr(cmp, "RECORDS", str(tmp_path))

    write("issue5-onimage-alpha.jsonl", "alpha", keep=6)
    write("issue5-onimage-beta.jsonl", "beta", keep=6)
    cmp.main()
    both = capsys.readouterr().out
    assert "REFUSING the site comparison" not in both
    assert "truncated at the same depth" in both

    # Now give beta its whole list and nothing else changes.
    write("issue5-onimage-beta.jsonl", "beta", keep=99)
    cmp.main()
    mixed = capsys.readouterr().out
    assert "REFUSING the site comparison" in mixed, (
        "a six-site list was compared against a nine-site one")
