"""Run a step under the cap and judge it against a committed budget, with distinct outcomes.

    out = run_step("lr_check v1", argv, budget=budgets["v1"]["lr_check"], mem="2G")
    assert_ok(out)        # raises one of the four classes below, never a bare AssertionError

A budget is {"peak_rss_kb": N, "wall_s": S, "machine": M}: the median of the measured runs times a stated margin
(see bench.py). The outcomes are kept apart on purpose - a segfault, an out-of-memory kill and a
timeout are different defects and a generic "failed" hides which:

    CrashError       the step died by a signal other than SIGKILL (exit 128+n), e.g. SIGSEGV
    OomError         exit 137: the memory cap killed it (or something sent SIGKILL)
    StepTimeout      exit 124: the time limit
    BudgetExceeded   it finished, and its peak or wall time is over the budget
    StepFailed       it finished with another non-zero exit

Which budget applies is the caller's; this module only measures and classifies.

PEAK MEMORY IS PORTABLE, WALL TIME IS NOT. A peak-RSS budget is enforced on every machine. A wall-time
budget is enforced only when this run's machine is the one the budget was measured on (budget["machine"]
equals `machine`, default `current_machine()`); anywhere else the wall time is reported as a ratio to the
budget (Outcome.wall_ratio) and never fails the step, and the time limit is not tightened to the budget.
A budget with no machine recorded enforces no wall time: it cannot say where it was measured.
"""
import os
import signal
import socket
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


def current_machine():
    return os.environ.get("DUE_PCB_MACHINE") or socket.gethostname()


@dataclass
class Outcome:
    name: str
    kind: str                # OK, CRASH, OOM, TIMEOUT, OVER_BUDGET, FAIL
    returncode: int
    peak_rss_kb: int | None
    wall_s: float | None
    detail: str
    result: capped.Result
    wall_ratio: float | None = None       # wall / budget wall, set whenever a budget is given
    wall_enforced: bool = False


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


def run_step(name, argv, *, budget=None, mem="2G", timeout=None, cwd=None, env=None, machine=None):
    """Run once under the cap. Where the wall budget is enforced (same machine) the time limit is the
    budget's wall time unless `timeout` is given, with no slack added: a step over it is OVER_BUDGET if it
    finished within the limit and TIMEOUT if it did not. Elsewhere the limit is 300 s."""
    machine = machine or current_machine()
    enforce_wall = bool(budget and budget.get("machine") and budget["machine"] == machine)
    limit = timeout if timeout is not None else (max(int(budget["wall_s"]) + 1, 2) if enforce_wall else 300)
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
        if enforce_wall and res.wall_s is not None and res.wall_s > budget["wall_s"]:
            over.append(f"wall {res.wall_s:.2f} s > {budget['wall_s']} s")
        if peak is None or res.wall_s is None:
            over.append("no measurement taken, so no budget can be checked")
        if over:
            kind, detail = "OVER_BUDGET", "; ".join(over)
    ratio = (res.wall_s / budget["wall_s"]) if (budget and res.wall_s is not None and budget["wall_s"]) else None
    return Outcome(name, kind, res.returncode, peak, res.wall_s, detail, res, wall_ratio=ratio, wall_enforced=enforce_wall)


_RAISES = {"CRASH": CrashError, "OOM": OomError, "TIMEOUT": StepTimeout,
           "OVER_BUDGET": BudgetExceeded, "FAIL": StepFailed}


def assert_ok(out):
    if out.kind != "OK":
        tail = out.result.stderr.strip().splitlines()[-3:]
        raise _RAISES[out.kind](f"{out.name}: {out.kind} (exit {out.returncode}) {out.detail} {' | '.join(tail)}")
    return out
