"""How long the harness waits, and how long a run lasts: one home.

Every wait in host/, gui/ and tests/ names a level from the first table
and every run length names a level from the second, so a bench that is
slower or faster than this one changes one number, and a figure that
used to be a bare literal can be audited against what it waits for.

    DELAYS   what a sleep waits for
    SPIN     yield in a busy loop: the transport's read loop, a feed
             that was refused a write
    POLL     re-check a flag, a queue or a descriptor
    TURN     one command and its answer, or a port changing hands
    SETTLE   a board state change to become visible: a stream starting
             or stopping, a converter settling
    RESET    the board coming back after a reset or a flash, and the
             backoff between attempts

    READS    how long a console read listens, and how long silence has to
             last to count as finished
    GLANCE   a command's answer, or the silence that means it is finished
    LISTEN   a state to be sampled, a short report
    REPORT   a status report the board prints in full
    WHOLE    a report that arrives in pieces
    TAIL     the longest a read is let to run when it has no marker

    LIMITS   how long a wait may take before it is a hang; a limit costs
             nothing when the wait ends, and fixes how long a failure takes.
             Fitted so the fewest limits grow; a limit rounds up
    QUICK    a reply that is already on the wire
    NORMAL   anything a board or the daemon does by itself
    SLOW     a flash, a re-enumeration, a build step
    BUILD    a build or a long subprocess
    MAX      the ceiling no single wait may pass

    RUNS     how long a capture lasts
    PROBE    liveness and counters only
    SHORT    one property: a DC level, a header
    STANDARD the default, for window statistics
    LONG     a rare event, an overrun guard
    SOAK     only behind the `slow` marker or an explicit request

The values are from the sleeps this suite actually makes, measured with
`--pacing-report` (tests/conftest.py): the delay sites cluster at 0.5-1
ms, 10 ms, 0.2 s, 0.5 s and 2 s, and the run lengths at 2, 3 and 6 s.

Parameterised from the environment, so a slow host changes a number
and not a file:

    DUE_DELAY_SCALE=2        multiply every delay (DUE_READ_*, DUE_LIMIT_*
                             work the same way for reads and limits)
    DUE_RUN_SCALE=0.5        multiply every run length
    DUE_DELAY_SETTLE=1.5     set one delay, in seconds
    DUE_RUN_LONG=10          set one run length, in seconds

Not delays, and deliberately outside the levels: a sleep whose length is
computed from a rate (the feeder's pacing, `FEED_PACE_CAP` bounds it) and
a sleep that is the run itself (`time.sleep(seconds)` in a capture).
"""
import os
import time

DELAYS = {"SPIN": 0.001, "POLL": 0.01, "TURN": 0.2, "SETTLE": 0.5,
          "RESET": 2.0}
READS = {"GLANCE": 0.3, "LISTEN": 1.0, "REPORT": 1.5, "WHOLE": 2.0, "TAIL": 3.0}
LIMITS = {"QUICK": 5.0, "NORMAL": 30.0, "SLOW": 120.0, "BUILD": 300.0,
          "MAX": 600.0}
RUNS = {"PROBE": 1.5, "SHORT": 2.0, "STANDARD": 3.0, "LONG": 6.0,
        "SOAK": 30.0}

#: How long the console has to be quiet, after it has said something, to
#: have finished. It is outside the ladders because it is a measured gap and
#: not a choice of how long to wait: the longest console reply seen ended
#: 0.027 s after the board started it on every track (90 reports), and this
#: is about four times that. `--pacing-report` and DUE_PACING_VERIFY=1 keep
#: checking it by counting any byte that arrives after it.
SILENCE = 0.1

#: Upper bound on a sleep whose length is derived from a byte rate. It is
#: a tuned value of the feeder, not a wait for anything, so no scale
#: applies to it.
FEED_PACE_CAP = 0.005


def _number(name, default):
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = float(raw)
    except ValueError:
        raise SystemExit(f"{name}={raw!r} is not a number of seconds")
    if value <= 0:
        raise SystemExit(f"{name}={raw!r} must be positive")
    return value


def _levels(table, prefix):
    scale = _number(f"DUE_{prefix}_SCALE", 1.0)
    return {name: _number(f"DUE_{prefix}_{name}", base * scale)
            for name, base in table.items()}


_DELAY = _levels(DELAYS, "DELAY")
_READ = _levels(READS, "READ")
_LIMIT = _levels(LIMITS, "LIMIT")
_RUN = _levels(RUNS, "RUN")

SPIN = _DELAY["SPIN"]
POLL = _DELAY["POLL"]
TURN = _DELAY["TURN"]
SETTLE = _DELAY["SETTLE"]
RESET = _DELAY["RESET"]

GLANCE = _READ["GLANCE"]
LISTEN = _READ["LISTEN"]
REPORT = _READ["REPORT"]
WHOLE = _READ["WHOLE"]
TAIL = _READ["TAIL"]

QUICK = _LIMIT["QUICK"]
NORMAL = _LIMIT["NORMAL"]
SLOW = _LIMIT["SLOW"]
BUILD = _LIMIT["BUILD"]
MAX = _LIMIT["MAX"]

PROBE = _RUN["PROBE"]
SHORT = _RUN["SHORT"]
STANDARD = _RUN["STANDARD"]
LONG = _RUN["LONG"]
SOAK = _RUN["SOAK"]

# What each delay is called, by value, so a sleep can be attributed to its
# level in a report.
_NAME = {value: name for name, value in _DELAY.items()}
_SLEPT = {}


def pause(seconds):
    """Sleep `seconds`, which is a delay level or a computed pacing value.

    Time slept at a named level is accumulated for `report()`.
    """
    name = _NAME.get(seconds)
    if name is not None:
        count, total = _SLEPT.get(name, (0, 0.0))
        _SLEPT[name] = (count + 1, total + seconds)
    time.sleep(seconds)


def pause_at_least(seconds, minimum, why):
    """`pause`, for a wait that must outlast something the device or the
    daemon does. A scale or override that makes the level shorter than the
    thing it waits out is a configuration error and says so, instead of
    letting an assertion about the absence of an event pass for lack of
    time to see one."""
    if seconds < minimum:
        raise AssertionError(
            f"{why}: needs at least {minimum} s and the level is "
            f"{seconds} s; a DUE_DELAY_* setting made it too short")
    pause(seconds)


class Marks:
    """Name the stages of a run, so a report says where its time went.

        m = pacing.Marks("run_loop")
        ...open the port...
        m.mark("open")           # the time since the last mark is "open"

    The stages accumulate across every run in the process and are read
    back with `phases()`; `--pacing-report` prints them. A mark costs a
    clock read and a dictionary update, so it stays in the code.
    """

    def __init__(self, prefix):
        self.prefix = prefix
        self.t = time.perf_counter()

    def mark(self, name):
        now = time.perf_counter()
        rec = _PHASE.setdefault(f"{self.prefix}.{name}", [0, 0.0])
        rec[0] += 1
        rec[1] += now - self.t
        self.t = now


_PHASE = {}
_OBS = {}

#: DUE_PACING_VERIFY=1 keeps the old, full-length behaviour of a read that
#: now ends early and counts what an early end would have cut off, so a
#: run can prove the shorter wait loses nothing before it is trusted.
VERIFY = os.environ.get("DUE_PACING_VERIFY") == "1"


def observe(name, value):
    """Record one measurement; the report prints count, mean and max."""
    rec = _OBS.setdefault(name, [0, 0.0, 0.0])
    rec[0] += 1
    rec[1] += value
    rec[2] = max(rec[2], value)


def observations():
    return {k: (v[0], v[1] / v[0], v[2]) for k, v in _OBS.items()}


def phases():
    """{stage: (runs, seconds)} for every Marks stage since the process began."""
    return {k: (v[0], v[1]) for k, v in _PHASE.items()}


def report():
    """{level: (calls, requested seconds)} since the process began."""
    return dict(_SLEPT)
