import os
import signal
import sys

import pytest

from simtools import budget as B
from simtools import capped

pytestmark = [pytest.mark.hostcap, pytest.mark.skipif(not capped.available(), reason="needs the capped runner")]

PY = sys.executable
BIG = {"peak_rss_kb": 2_000_000, "wall_s": 30}


def step(code, budget=BIG, **kw):
    return B.run_step("t", [PY, "-c", code], budget=budget, mem=kw.pop("mem", "1G"), **kw)


def test_a_step_inside_its_budget_is_ok():
    assert B.assert_ok(step("x = bytearray(50_000_000)")).kind == "OK"


def test_a_budget_shrunk_below_the_measurement_is_over_budget_on_peak():
    out = step("x = bytearray(100_000_000)", budget={"peak_rss_kb": 20_000, "wall_s": 30})
    assert out.kind == "OVER_BUDGET" and "peak" in out.detail
    with pytest.raises(B.BudgetExceeded):
        B.assert_ok(out)


def test_wall_over_budget_is_over_budget_on_wall():
    out = step("import time; time.sleep(1.5)", budget={"peak_rss_kb": 2_000_000, "wall_s": 1.0}, timeout=20)
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
