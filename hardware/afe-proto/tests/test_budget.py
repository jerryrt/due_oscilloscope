import os
import signal
import sys

import pytest

from simtools import budget as B
from simtools import capped

pytestmark = [pytest.mark.hostcap, pytest.mark.skipif(not capped.available(), reason="needs the capped runner")]

PY = sys.executable
BIG = {"peak_rss_kb": 2_000_000, "wall_s": 30, "machine": "here"}


def step(code, budget=BIG, **kw):
    kw.setdefault("machine", "here")
    return B.run_step("t", [PY, "-c", code], budget=budget, mem=kw.pop("mem", "1G"), **kw)


def test_a_step_inside_its_budget_is_ok():
    assert B.assert_ok(step("x = bytearray(50_000_000)")).kind == "OK"


def test_a_budget_shrunk_below_the_measurement_is_over_budget_on_peak():
    out = step("x = bytearray(100_000_000)", budget={"peak_rss_kb": 20_000, "wall_s": 30, "machine": "here"})
    assert out.kind == "OVER_BUDGET" and "peak" in out.detail
    with pytest.raises(B.BudgetExceeded):
        B.assert_ok(out)


def test_wall_over_budget_is_over_budget_on_wall():
    out = step("import time; time.sleep(1.5)", budget={"peak_rss_kb": 2_000_000, "wall_s": 1.0, "machine": "here"}, timeout=20)
    assert out.kind == "OVER_BUDGET" and "wall" in out.detail


def test_a_segfault_is_a_crash_not_a_generic_failure():
    out = step(f"import os, signal; os.kill(os.getpid(), signal.SIGSEGV)")
    assert out.kind == "CRASH" and out.returncode == 128 + signal.SIGSEGV and "SIGSEGV" in out.detail
    with pytest.raises(B.CrashError):
        B.assert_ok(out)


def test_an_abort_is_also_a_crash():
    assert step("import os; os.abort()").kind == "CRASH"


def test_a_sleep_over_the_limit_is_a_timeout():
    out = step("import time; time.sleep(60)", timeout=2)
    assert out.kind == "TIMEOUT" and out.returncode == 124
    with pytest.raises(B.StepTimeout):
        B.assert_ok(out)


@pytest.mark.jobcap
def test_an_allocation_over_the_cap_is_oom():
    out = step("b = bytearray(600_000_000)", mem="200M")
    assert out.kind == "OOM" and out.returncode == 137
    with pytest.raises(B.OomError):
        B.assert_ok(out)


def test_an_ordinary_nonzero_exit_is_just_a_failure():
    out = step("raise SystemExit(3)")
    assert out.kind == "FAIL" and out.returncode == 3
    with pytest.raises(B.StepFailed):
        B.assert_ok(out)


def test_the_four_error_classes_are_distinct():
    kinds = {B.CrashError, B.OomError, B.StepTimeout, B.BudgetExceeded}
    assert len(kinds) == 4 and not any(issubclass(a, b) for a in kinds for b in kinds if a is not b)


@pytest.mark.parametrize("rc, kind", [(0, "OK"), (1, "FAIL"), (124, "TIMEOUT"), (137, "OOM"), (139, "CRASH"), (134, "CRASH")])
def test_classify_table(rc, kind):
    assert B.classify(rc) == kind


SLOW = "import time; time.sleep(1.5)"
TIGHT = {"peak_rss_kb": 2_000_000, "wall_s": 1.0, "machine": "x1"}


def test_wall_budget_is_enforced_on_the_machine_it_was_measured_on():
    out = step(SLOW, budget=TIGHT, machine="x1", timeout=20)
    assert out.kind == "OVER_BUDGET" and out.wall_enforced and out.wall_ratio > 1.0


def test_wall_budget_is_only_reported_on_another_machine():
    out = step(SLOW, budget=TIGHT, machine="somewhere-else", timeout=20)
    assert out.kind == "OK" and not out.wall_enforced
    assert out.wall_ratio == pytest.approx(out.wall_s / 1.0) and out.wall_ratio > 1.0     # the ratio is still reported


def test_peak_budget_is_enforced_on_every_machine():
    small = {"peak_rss_kb": 20_000, "wall_s": 60, "machine": "x1"}
    for machine in ("x1", "somewhere-else"):
        out = step("x = bytearray(100_000_000)", budget=small, machine=machine)
        assert out.kind == "OVER_BUDGET" and "peak" in out.detail, (machine, out.kind)


def test_a_budget_with_no_machine_enforces_no_wall_time():
    out = step(SLOW, budget={"peak_rss_kb": 2_000_000, "wall_s": 1.0}, machine="x1", timeout=20)
    assert out.kind == "OK" and not out.wall_enforced


def test_the_time_limit_is_not_tightened_to_a_budget_on_another_machine():
    """A slower machine must not be killed at the budget's wall time: the limit stays the default there."""
    out = B.run_step("t", [PY, "-c", SLOW], budget=TIGHT, mem="1G", machine="somewhere-else")
    assert out.kind == "OK"          # with the limit at wall_s + 1 = 2 s it would be near the edge; 300 s is not


def test_the_committed_budgets_carry_their_machine():
    import json
    import pathlib
    d = json.loads((pathlib.Path(__file__).resolve().parent / "budgets.json").read_text())
    rows = [t for b in d["budgets"].values() for t in b.values()]
    assert len(rows) >= 30 and all(r.get("machine") == d["meta"]["machine"] for r in rows)


def test_a_step_that_reports_findings_by_exiting_1_is_ok_at_1_and_a_failure_otherwise():
    assert step("raise SystemExit(1)", expect_exit=1).kind == "OK"
    assert step("raise SystemExit(0)", expect_exit=1).kind == "FAIL"
    assert step("raise SystemExit(2)", expect_exit=1).kind == "FAIL"
    assert step("raise SystemExit(1)").kind == "FAIL"                 # the default is still 0
    assert B.classify(139, expect_exit=1) == "CRASH" and B.classify(124, expect_exit=1) == "TIMEOUT"


def test_a_step_slightly_over_its_wall_budget_is_over_budget_not_a_timeout():
    """The hard limit is far above the budget (max(300 s, 3 x budget)), so a step a little over it finishes and is
    reported as OVER_BUDGET; only a runaway is a TIMEOUT. With the old limit of budget + 1 s this was a TIMEOUT."""
    out = B.run_step("t", [PY, "-c", "import time; time.sleep(2.5)"], mem="1G", machine="x1",
                     budget={"peak_rss_kb": 2_000_000, "wall_s": 1.0, "machine": "x1"})
    assert out.kind == "OVER_BUDGET" and out.returncode == 0 and out.wall_enforced, (out.kind, out.returncode)
