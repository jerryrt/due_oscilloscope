"""The per-host timing audit: a budget is a host's own spread, and it warns.

No board and no pytest run: the audit's arithmetic, on durations whose
answer is known.
"""
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tools"))
import timing_audit as ta  # noqa: E402


def _xml(tests, skipped=()):
    cases = "".join(f'<testcase classname="t" name="{n}" time="{s}"/>'
                    for n, s in tests.items())
    cases += "".join(f'<testcase classname="t" name="{n}" time="9"><skipped/></testcase>'
                     for n in skipped)
    return f"<testsuites><testsuite>{cases}</testsuite></testsuites>"


def _rows(per_pass):
    return [{"tests": {f"t::{n}": s for n, s in p.items()}} for p in per_pass]


STEADY = [{"a": 2.0, "slow": 5.0}, {"a": 2.1, "slow": 5.2}, {"a": 1.9, "slow": 4.9},
          {"a": 2.0, "slow": 5.1}]


def test_durations_reads_every_test_that_ran_and_skips_the_skipped():
    got = ta.durations(_xml({"x": 1.5, "y": 2.5}, skipped=("z",)))
    assert got == {"t::x": 1.5, "t::y": 2.5}


def test_a_budget_needs_three_passes_and_drops_the_first():
    assert ta.budgets(_rows(STEADY[:2])) == {}
    # the first pass is an outlier and must not be in the median
    rows = _rows([{"a": 90.0}, {"a": 2.0}, {"a": 2.1}, {"a": 1.9}])
    med, tol = ta.budgets(rows)["t::a"]
    assert med == pytest.approx(2.0)
    assert tol < 1.0


def test_a_test_over_its_own_tolerance_is_flagged_slow_and_one_inside_is_not():
    rows = _rows(STEADY)
    med = ta.budgets(rows)["t::a"][0]
    findings, _ = ta.audit({"t::a": med + 0.2, "t::slow": 5.1}, rows)
    assert findings == []
    findings, _ = ta.audit({"t::a": med + 5.0, "t::slow": 5.1}, rows)
    assert [(k, t) for k, t, *_ in findings] == [("SLOW", "t::a")]


def test_the_tolerance_is_the_hosts_own_spread_not_a_fixed_margin():
    tight = _rows([{"a": 2.0}, {"a": 2.0}, {"a": 2.0}, {"a": 2.0}])
    loose = _rows([{"a": 2.0}, {"a": 2.0}, {"a": 4.0}, {"a": 8.0}, {"a": 3.0}])
    assert ta.budgets(tight)["t::a"][1] == pytest.approx(ta.FLOOR_S)
    assert ta.budgets(loose)["t::a"][1] > ta.budgets(tight)["t::a"][1] * 3


def test_a_new_test_and_a_gone_test_are_reported():
    rows = _rows(STEADY)
    findings, total = ta.audit({"t::a": 2.0, "t::brand_new": 3.0}, rows)
    kinds = {(k, t) for k, t, *_ in findings}
    assert ("NEW", "t::brand_new") in kinds and ("GONE", "t::slow") in kinds
    assert total == pytest.approx(5.0)


def test_calibrate_appends_a_row_and_audit_warns_but_exits_zero(tmp_path, capsys):
    root = str(tmp_path)
    for i, a in enumerate((2.0, 2.0, 2.1, 1.9)):
        x = tmp_path / f"p{i}.xml"
        x.write_text(_xml({"a": a}), encoding="utf-8")
        assert ta.main(["calibrate", str(x), "--bench", "h", "--track", "b",
                        "--root", root]) == 0
    rows = ta.load_rows(ta.record_path("h", "b", root))
    assert len(rows) == 4 and rows[0]["bench"] == "h" and rows[0]["track"] == "b"
    slow = tmp_path / "slow.xml"
    slow.write_text(_xml({"a": 30.0}), encoding="utf-8")
    assert ta.main(["audit", str(slow), "--bench", "h", "--track", "b",
                    "--root", root]) == 0
    assert "SLOW" in capsys.readouterr().out
    assert ta.main(["audit", str(slow), "--bench", "h", "--track", "b",
                    "--root", root, "--strict"]) == 1


def test_an_audit_with_too_few_passes_says_so_instead_of_inventing_a_budget(tmp_path, capsys):
    x = tmp_path / "p.xml"
    x.write_text(_xml({"a": 2.0}), encoding="utf-8")
    ta.main(["calibrate", str(x), "--bench", "h", "--track", "b", "--root", str(tmp_path)])
    ta.main(["audit", str(x), "--bench", "h", "--track", "b", "--root", str(tmp_path)])
    assert "needs 3" in capsys.readouterr().out
