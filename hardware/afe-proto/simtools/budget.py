"""Run a step under the cap and judge it against a committed budget, with distinct outcomes.

    out = run_step("lr_check v1", argv, budget=budgets["v1"]["lr_check"], mem="2G")
    assert_ok(out)        # raises one of the four classes below, never a bare AssertionError

A budget is {"peak_rss_kb": N, "wall_s": S}: the median of the measured runs times a stated margin
(see bench.py). The outcomes are kept apart on purpose - a segfault, an out-of-memory kill and a
timeout are different defects and a generic "failed" hides which:

    CrashError       the step died by a signal other than SIGKILL (exit 128+n), e.g. SIGSEGV
    OomError         exit 137: the memory cap killed it (or something sent SIGKILL)
    StepTimeout      exit 124: the time limit
    BudgetExceeded   it finished, and its peak or wall time is over the budget
    StepFailed       it finished with another non-zero exit

Which budget applies is the caller's; this module only measures and classifies.
"""
import signal
from dataclasses import dataclass

from . import capped


class StepError(AssertionError):
    kind = "FAIL"


class CrashError(StepError):
    kind = "CRASH"


class OomError(StepError):
    kind = "OOM"


class StepTimeout(StepError):
    kind = "TIMEOUT"


class BudgetExceeded(StepError):
    kind = "OVER_BUDGET"


class StepFailed(StepError):
    kind = "FAIL"


@dataclass
class Outcome:
    name: str
    kind: str                # OK, CRASH, OOM, TIMEOUT, OVER_BUDGET, FAIL
    returncode: int
    peak_rss_kb: int | None
    wall_s: float | None
    detail: str
    result: capped.Result


def classify(rc):
    """Exit status -> kind, before any budget is looked at."""
    if rc == 0:
        return "OK"
    if rc == capped.TIMED_OUT:
        return "TIMEOUT"
    if rc == capped.CAP_KILLED:
        return "OOM"
    if rc > 128:
        return "CRASH"
    return "FAIL"


def signal_name(rc):
    try:
        return signal.Signals(rc - 128).name
    except ValueError:
        return f"signal {rc - 128}"


def run_step(name, argv, *, budget=None, mem="2G", timeout=None, cwd=None, env=None):
    """Run once under the cap. The time limit is the budget's wall time unless `timeout` is given,
    with no slack added: a step over its wall budget is reported as OVER_BUDGET if it finished within
    the limit and as TIMEOUT if it did not."""
    limit = timeout if timeout is not None else (max(int(budget["wall_s"]) + 1, 2) if budget else 300)
    res = capped.run(argv, mem=mem, timeout=limit, cwd=cwd, env=env)
    kind = classify(res.returncode)
    peak = None if res.peak_rss_bytes is None else res.peak_rss_bytes // 1024
    detail = ""
    if kind == "CRASH":
        detail = f"died by {signal_name(res.returncode)}"
    elif kind == "OK" and budget:
        over = []
        if peak is not None and peak > budget["peak_rss_kb"]:
            over.append(f"peak {peak} KB > {budget['peak_rss_kb']} KB")
        if res.wall_s is not None and res.wall_s > budget["wall_s"]:
            over.append(f"wall {res.wall_s:.2f} s > {budget['wall_s']} s")
        if peak is None or res.wall_s is None:
            over.append("no measurement taken, so no budget can be checked")
        if over:
            kind, detail = "OVER_BUDGET", "; ".join(over)
    return Outcome(name, kind, res.returncode, peak, res.wall_s, detail, res)


_RAISES = {"CRASH": CrashError, "OOM": OomError, "TIMEOUT": StepTimeout,
           "OVER_BUDGET": BudgetExceeded, "FAIL": StepFailed}


def assert_ok(out):
    if out.kind != "OK":
        tail = out.result.stderr.strip().splitlines()[-3:]
        raise _RAISES[out.kind](f"{out.name}: {out.kind} (exit {out.returncode}) {out.detail} {' | '.join(tail)}")
    return out
