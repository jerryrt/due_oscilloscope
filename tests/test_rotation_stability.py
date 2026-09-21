"""tools/rotation_stability.py: the rule that says whether a board's
repeated rows in one arrangement agree, held on rows built here."""

import importlib.util
import json
import os

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "..", "tools", "rotation_stability.py")
spec = importlib.util.spec_from_file_location("rotation_stability", TOOL)
rs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rs)

UID = "442032204e52344d3230323239313032"


def _row(median, lo, hi, taken, idle=1200, bench="b1", phase="p",
         baseline=((0.5, 1.3), (0.6, 1.3)), aborted=None, counts=(0, 2),
         die=(1040.0, 1041.0), count_median=None):
    tail = []
    if aborted:
        tail += [{"arm": "baseline", "run": i + 1, "a0_scale_codes": a,
                  "a1_scale_codes": b} for i, (a, b) in enumerate(aborted)]
        tail += [{"arm": "sync-off", "run": 1, "a0_scale_codes": 9, "a1_scale_codes": 9}]
    tail += [{"arm": "baseline", "run": i + 1, "a0_scale_codes": a,
              "a1_scale_codes": b} for i, (a, b) in enumerate(baseline)]
    tail += [{"arm": "solo", "run": 1, "a0_scale_codes": 7, "a1_scale_codes": 7}]
    return {"board_uid": UID, "board_serial": "S", "bench": bench, "phase": phase,
            "taken_at": taken, "idle_before_s": idle,
            "census_summary": {"largest_median": median, "largest_min": lo,
                               "largest_max": hi, "count_min": counts[0],
                               "count_max": counts[1],
                               "count_median": (count_median if count_median
                                                is not None else counts[0])},
            "tail_scale": tail,
            "temperatures": [{"code": c} for c in die]}


def test_four_rows_inside_their_own_range_are_stable():
    rows = [_row(43.5, 43.5, 44.5, "t1"), _row(44.0, 43.0, 45.0, "t2"),
            _row(44.5, 43.5, 45.0, "t3"), _row(43.5, 43.0, 44.5, "t4")]
    a = rs.assess(rows)
    assert len(a) == 1
    assert a[0]["verdict"] == "stable"
    assert a[0]["across"] == 1.0 and a[0]["within"] == 2.0
    assert a[0]["n_rested"] == 4


def test_rows_spread_wider_than_any_one_of_them_are_not_stable():
    rows = [_row(43.5, 43.5, 44.5, "t1"), _row(48.0, 47.0, 48.5, "t2"),
            _row(44.0, 43.5, 44.5, "t3"), _row(46.0, 45.5, 46.5, "t4")]
    a = rs.assess(rows)
    assert a[0]["verdict"] == "NOT stable"
    assert a[0]["across"] == 4.5 and a[0]["within"] == 1.5


def test_an_unrested_row_is_listed_and_excluded():
    rows = [_row(43.5, 43.5, 44.5, "t1"), _row(60.0, 59.0, 61.0, "t2", idle=30),
            _row(44.0, 43.0, 45.0, "t3")]
    a = rs.assess(rows)
    assert a[0]["verdict"] == "stable"
    assert a[0]["n_rested"] == 2
    assert [l["rested"] for l in a[0]["rows"]] == [True, False, True]
    assert "unrested, excluded" in rs.render(a)


def test_one_rested_row_gives_no_verdict():
    a = rs.assess([_row(43.5, 43.5, 44.5, "t1")])
    assert a[0]["verdict"] == "no verdict"
    assert "1 rested row" in a[0]["reason"]


def test_phases_are_never_pooled():
    rows = [_row(43.5, 43.5, 44.5, "t1", phase="shield"),
            _row(54.5, 53.0, 55.5, "t2", phase="before")]
    a = rs.assess(rows)
    assert [x["phase"] for x in a] == ["before", "shield"]
    assert all(x["verdict"] == "no verdict" for x in a)
    only = rs.assess(rows, phase="shield")
    assert [x["phase"] for x in only] == ["shield"]


def test_the_tail_scale_is_the_pair_that_completed_not_the_aborted_one():
    """A row whose parity was forced after a tie carries the aborted
    attempt's baseline pair first; the completed pair is the last one."""
    r = _row(44.0, 43.5, 44.5, "t1", baseline=((0.5, 1.3), (0.6, 1.3)),
             aborted=((1.6, 1.4), (1.7, 1.5)))
    line = rs.row_line(r)
    assert line["a0"] == 0.55 and line["a1"] == 1.3
    plain = rs.row_line(_row(44.0, 43.5, 44.5, "t1"))
    assert plain["a0"] == 0.55
    assert rs.row_line({"tail_scale": []})["a0"] is None


def test_the_count_gets_its_own_verdict_and_the_drift_is_printed():
    """A level that holds while the count moves: windows-desk's four
    shield rows read stable on the level and the count fell 3 -> 1.
    The count rule is the same spread rule on the count medians, and
    the drift is printed with no verdict so a monotone change inside
    the within-row range is still in front of the reader."""
    rows = [_row(48.0, 47.0, 48.5, "t1", counts=(3, 4), count_median=3),
            _row(47.0, 46.5, 49.5, "t2", counts=(1, 3), count_median=2),
            _row(47.5, 46.5, 49.0, "t3", counts=(1, 3), count_median=2),
            _row(46.0, 45.0, 48.5, "t4", counts=(0, 2), count_median=1)]
    a = rs.assess(rows)[0]
    assert a["verdict"] == "stable"
    assert a["count_verdict"] == "stable"           # spread 2 vs widest 2
    assert a["count_across"] == 2 and a["count_within"] == 2
    assert a["drift"] == {"largest_median": -2.0, "count_median": -2}
    text = rs.render([a])
    assert "count **stable**" in text and "count median -2" in text
    rows[3]["census_summary"]["count_median"] = 0
    rows[3]["census_summary"]["count_max"] = 0
    b = rs.assess(rows)[0]
    assert b["count_verdict"] == "NOT stable"       # spread 3 vs widest 2
    assert b["verdict"] == "stable"
    assert "count **NOT stable**" in rs.render([b])


def test_break_the_rule_on_purpose():
    """Equal spread and range is stable; one code more is not."""
    rows = [_row(43.0, 43.0, 45.0, "t1"), _row(45.0, 43.0, 45.0, "t2")]
    assert rs.assess(rows)[0]["verdict"] == "stable"
    rows[1]["census_summary"]["largest_median"] = 45.5
    assert rs.assess(rows)[0]["verdict"] == "NOT stable"


def test_main_reads_a_file_and_renders(tmp_path, capsys):
    p = tmp_path / "rot.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in
                           [_row(43.5, 43.5, 44.5, "t1"),
                            _row(44.0, 43.0, 45.0, "t2")]) + "\n",
                 encoding="utf-8")
    assert rs.main(["--rotation", str(p)]) == 0
    out = capsys.readouterr().out
    assert "**stable**" in out and UID in out
    assert rs.main(["--rotation", str(p), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data[0]["verdict"] == "stable"


def test_the_real_record_parses():
    real = os.path.join(HERE, "..", "records", "rotation.jsonl")
    if not os.path.exists(real):
        pytest.skip("no record")
    a = rs.assess(rs.rows_from(real))
    assert a, "the record names no board"
    for x in a:
        assert x["verdict"] in ("stable", "NOT stable", "no verdict")
